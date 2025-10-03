# bot/core/auto_animes.py
import asyncio
from asyncio import Event
from os import path as ospath
from aiofiles.os import remove as aioremove
from traceback import format_exc
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
import base64

from bot import bot, bot_loop, Var, ani_cache, ffQueue, ffLock, ff_queued
from .tordownload import TorDownloader
from bot.core.database import db
from .func_utils import getfeed, editMessage, sendMessage, convertBytes
from .text_utils import TextEditor
from .ffencoder import FFEncoder
from .tguploader import TgUploader
from .reporter import rep

btn_formatter = {
    '1080': '1080p',
    '720': '720p',
    '480': '480p'
}

# ----------------------
# Base64 helpers
# ----------------------
def encode_payload(payload: str) -> str:
    """
    URL-safe encode and strip padding to avoid Telegram URL issues.
    """
    encoded = base64.urlsafe_b64encode(payload.encode()).decode()
    return encoded.rstrip("=")

def decode_payload(encoded: str) -> str:
    """
    Restore padding then decode.
    """
    if not isinstance(encoded, str):
        raise ValueError("Encoded payload must be a string")
    encoded = encoded.strip().replace(" ", "+")
    padding = "=" * ((4 - len(encoded) % 4) % 4)
    return base64.urlsafe_b64decode(encoded + padding).decode()

# ----------------------
# Fetch ongoing animes loop
# ----------------------
async def fetch_animes():
    await rep.report("Fetch Animes Started !!", "info")
    while True:
        await asyncio.sleep(60)
        if ani_cache.get('fetch_animes'):
            for link in Var.RSS_ITEMS:
                if (info := await getfeed(link, 0)):
                    bot_loop.create_task(get_animes(info.title, info.link))

# ----------------------
# Main flow: download -> encode -> upload -> button create
# ----------------------
async def get_animes(name, torrent, force=False):
    try:
        aniInfo = TextEditor(name)
        await aniInfo.load_anilist()
        ani_id, ep_no = aniInfo.adata.get('id'), aniInfo.pdata.get("episode_number")

        if ani_id not in ani_cache.get('ongoing', set()):
            ani_cache.setdefault('ongoing', set()).add(ani_id)
        elif not force:
            return

        if not force and ani_id in ani_cache.get('completed', set()):
            return

        ani_data = await db.getAnime(ani_id)
        qual_data = ani_data.get(ep_no) if ani_data else None
        if not force and qual_data and all(qual_data.get(q) for q in Var.QUALS):
            return

        if "[Batch]" in name:
            await rep.report(f"Torrent Skipped!\n\n{name}", "warning")
            return

        await rep.report(f"New Anime Torrent Found!\n\n{name}", "info")

        post_msg = await bot.send_photo(
            Var.MAIN_CHANNEL,
            photo=await aniInfo.get_poster(),
            caption=await aniInfo.get_caption()
        )

        await asyncio.sleep(1.5)
        stat_msg = await sendMessage(
            Var.MAIN_CHANNEL,
            f"‣ <b>Anime Name :</b> <b><i>{name}</i></b>\n\n<i>Downloading...</i>"
        )

        # Retry download up to 3 times if incomplete
        dl = None
        for attempt in range(3):
            dl = await TorDownloader("./downloads").download(torrent, name)
            if dl and ospath.exists(dl):
                break
            await rep.report(f"Download failed or incomplete. Retrying ({attempt+1}/3)...", "warning")
            await asyncio.sleep(5)

        if not dl or not ospath.exists(dl):
            await rep.report(f"File Download Incomplete after 3 retries, Skipping", "error")
            await stat_msg.delete()
            return

        post_id = post_msg.id
        ffEvent = Event()
        ff_queued[post_id] = ffEvent
        if ffLock.locked():
            await editMessage(stat_msg, f"‣ <b>Anime Name :</b> <b><i>{name}</i></b>\n\n<i>Queued to Encode...</i>")
            await rep.report("Added Task to Queue...", "info")
        await ffQueue.put(post_id)
        await ffEvent.wait()

        await ffLock.acquire()
        btns = []

        for qual in Var.QUALS:
            filename = await aniInfo.get_upname(qual)
            await editMessage(stat_msg, f"‣ <b>Anime Name :</b> <b><i>{name}</i></b>\n\n<i>Ready to Encode...</i>")
            await asyncio.sleep(1.5)
            await rep.report(f"Starting Encode ({qual})...", "info")

            try:
                out_path = await FFEncoder(stat_msg, dl, filename, qual).start_encode()
            except Exception as e:
                await rep.report(f"Error: {e}, Cancelled, Retry Again!", "error")
                await stat_msg.delete()
                ffLock.release()
                return

            await rep.report(f"✅ Successfully Compressed ({qual}). Uploading...", "info")
            await editMessage(stat_msg, f"‣ <b>Anime Name :</b> <b><i>{filename}</i></b>\n\n<i>Ready to Upload...</i>")
            await asyncio.sleep(1.5)

            try:
                msg = await TgUploader(stat_msg).upload(out_path, qual)
            except Exception as e:
                await rep.report(f"Error: {e}, Cancelled, Retry Again!", "error")
                await stat_msg.delete()
                ffLock.release()
                return

            await rep.report(f"✅ Successfully Uploaded {qual} File to Tg...", "info")
            msg_id = msg.id

            # Create safe Base64 payload: anime-ani_id-ep_no-qual-msg_id
            payload = f"anime-{ani_id}-{ep_no}-{qual}-{msg_id}"
            encoded_payload = encode_payload(payload)
            link = f"https://t.me/{(await bot.get_me()).username}?start={encoded_payload}"

            # Telegram buttons
            btn_label = btn_formatter.get(qual, qual)
            new_btn = InlineKeyboardButton(
                f"{btn_label} - {convertBytes(msg.document.file_size)}",
                url=link
            )
            if len(btns) != 0 and len(btns[-1]) == 1:
                btns[-1].append(new_btn)
            else:
                btns.append([new_btn])

            await editMessage(
                post_msg,
                post_msg.caption.html if post_msg.caption else "",
                InlineKeyboardMarkup(btns)
            )

            # Save quality message id in DB
            await db.saveAnime(ani_id, ep_no, qual, msg_id)

            # Extra utils
            bot_loop.create_task(extra_utils(msg_id, out_path))

        ffLock.release()
        await stat_msg.delete()

        # Cleanup original file after all qualities
        await aioremove(dl)
        ani_cache.setdefault('completed', set()).add(ani_id)

    except Exception:
        await rep.report(format_exc(), "error")


# ----------------------
# /start handler (robust decode + per-quality tracking)
# ----------------------
async def handle_start(client, message, start_payload):
    # start_payload is expected to be the encoded string (without spaces)
    try:
        if not start_payload:
            await message.reply("Invalid payload!")
            return

        decoded = decode_payload(start_payload)
        parts = decoded.split("-")
        if len(parts) != 5 or parts[0] != "anime":
            raise ValueError("Payload parts mismatch")

        ani_id = parts[1]
        ep_no = parts[2]
        qual = parts[3]
        msg_id = int(parts[4])
    except Exception as e:
        # short, clear error for debugging
        await message.reply(f"Invalid payload! ({e})")
        return

    user_id = message.from_user.id

    # DB: check per-user per-quality (db should implement this signature)
    try:
        got = await db.get_user_anime(user_id, ani_id, ep_no, qual)
    except TypeError:
        # Fallback if your DB still uses old single-key approach:
        # check using combined key - keeps backward compatibility
        got = await db.get_user_anime(user_id, f"{ani_id}-{ep_no}-{qual}")

    if got:
        if getattr(Var, "WEBSITE", None):
            await message.reply(f"🎬 You already received {qual} for this anime!\nVisit: {Var.WEBSITE} for re-download")
        else:
            await message.reply(f"🎬 You already received {qual} for this anime!")
        return

    # fetch file from file store channel
    msg = await client.get_messages(Var.FILE_STORE, message_ids=msg_id)
    if not msg:
        await message.reply("File not found!")
        return

    protect = getattr(Var, "TG_PROTECT_CONTENT", False)

    # send correct file type
    if msg.document:
        sent = await client.send_document(chat_id=message.chat.id, document=msg.document.file_id, protect_content=protect)
    elif msg.video:
        sent = await client.send_video(chat_id=message.chat.id, video=msg.video.file_id, protect_content=protect)
    elif msg.photo:
        sent = await client.send_photo(chat_id=message.chat.id, photo=msg.photo.file_id, protect_content=protect)
    else:
        await message.reply("File type not supported!")
        return

    # mark user has received this quality
    try:
        await db.mark_user_anime(user_id, ani_id, ep_no, qual)
    except TypeError:
        # fallback for older db method that accepts single key
        await db.mark_user_anime(user_id, f"{ani_id}-{ep_no}-{qual}")

    # auto delete with notice
    if getattr(Var, "AUTO_DEL", False):
        try:
            timer = int(getattr(Var, "DEL_TIMER", 60))
            notify = await client.send_message(chat_id=message.chat.id, text=f"⚠️ This file will auto-delete in {timer} seconds! Save it.")
            await asyncio.sleep(timer)
            await sent.delete()
            await notify.delete()
            await client.send_message(chat_id=message.chat.id, text="🗑️ File has been auto-deleted!")
        except Exception:
            pass


# ----------------------
# Extra utils
# ----------------------
async def extra_utils(msg_id, out_path):
    try:
        msg = await bot.get_messages(Var.FILE_STORE, message_ids=msg_id)
        if Var.BACKUP_CHANNEL and Var.BACKUP_CHANNEL != "0":
            for chat_id in Var.BACKUP_CHANNEL.split():
                try:
                    await msg.copy(int(chat_id))
                except Exception:
                    pass
    except Exception:
        await rep.report(format_exc(), "error")
