# bot/core/auto_animes.py
import asyncio
from asyncio import Event, sleep
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
    '480': '48𝟬𝗽'
}

# ----------------------
# Fetch ongoing animes
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
# Main function to download, encode, upload and create buttons
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

            # Base64 button payload
            payload = f"anime-{ani_id}-{msg_id}-{qual}"
            encoded_payload = base64.urlsafe_b64encode(payload.encode()).decode()
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

            # Save in DB
            await db.saveAnime(ani_id, ep_no, qual, msg_id)

            # Backup & cleanup task
            bot_loop.create_task(extra_utils(msg_id, out_path))

        ffLock.release()
        await stat_msg.delete()

        # Cleanup original torrent file
        if ospath.exists(dl):
            await aioremove(dl)
            await rep.report(f"Deleted original torrent file: {dl}", "info")

        ani_cache.setdefault('completed', set()).add(ani_id)

    except Exception:
        await rep.report(format_exc(), "error")


# ----------------------
# /start handler logic
# ----------------------
async def handle_start(client, message, start_payload):
    try:
        parts = start_payload.split("-")
        ani_id = parts[1]
        msg_id = int(parts[2])
        qual = parts[3]
    except:
        await message.reply("Invalid payload!")
        return

    user_id = message.from_user.id

    # Check if already got this anime
    if await db.get_user_anime(user_id, ani_id, qual):
        # Send website link on second hit
        if getattr(Var, "WEBSITE", None):
            await message.reply(f"🎬 You already received this anime!\nVisit: {Var.WEBSITE}")
        else:
            await message.reply("🎬 You already received this anime!")
        return

    # First hit → get file
    msg = await client.get_messages(Var.FILE_STORE, message_ids=msg_id)
    if not msg:
        await message.reply("File not found!")
        return

    protect = getattr(Var, "TG_PROTECT_CONTENT", False)

    if msg.document:
        sent = await client.send_document(
            chat_id=message.chat.id,
            document=msg.document.file_id,
            protect_content=protect
        )
    elif msg.video:
        sent = await client.send_video(
            chat_id=message.chat.id,
            video=msg.video.file_id,
            protect_content=protect
        )
    elif msg.photo:
        sent = await client.send_photo(
            chat_id=message.chat.id,
            photo=msg.photo.file_id,
            protect_content=protect
        )
    else:
        await message.reply("File type not supported!")
        return

    # Mark in DB
    await db.mark_user_anime(user_id, ani_id, qual)

    # Auto-delete PM message after DEL_TIMER
    if getattr(Var, "AUTO_DEL", False):
        try:
            timer = int(getattr(Var, "DEL_TIMER", 60))
            notify = await client.send_message(
                chat_id=message.chat.id,
                text=f"⚠️ This file will be auto-deleted in {timer} seconds!"
            )
            await asyncio.sleep(timer)
            await sent.delete()
            await notify.delete()
            await client.send_message(
                chat_id=message.chat.id,
                text="⏳ File has been auto-deleted!"
            )
            await rep.report(f"Auto-deleted file for user {user_id} ({qual})", "info")
        except Exception:
            await rep.report(f"Failed auto-delete for user {user_id} ({qual})", "error")


# ----------------------
# Extra utils: backup & local cleanup
# ----------------------
async def extra_utils(msg_id, out_path):
    try:
        # Backup to other channels
        msg = await bot.get_messages(Var.FILE_STORE, message_ids=msg_id)
        if Var.BACKUP_CHANNEL and Var.BACKUP_CHANNEL != "0":
            for chat_id in Var.BACKUP_CHANNEL.split():
                try:
                    await msg.copy(int(chat_id))
                except Exception:
                    pass
        # Delete local encoded file after backup
        if ospath.exists(out_path):
            await aioremove(out_path)
            await rep.report(f"Deleted local encoded file: {out_path}", "info")
    except Exception:
        await rep.report(format_exc(), "error")
