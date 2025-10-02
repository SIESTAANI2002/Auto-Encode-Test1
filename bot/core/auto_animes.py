# bot/core/auto_animes.py
import asyncio
from asyncio import Event
from os import path as ospath
from aiofiles.os import remove as aioremove
from traceback import format_exc
from pyrogram import filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.errors import RPCError

from bot import bot, bot_loop, Var, ani_cache, ffQueue, ffLock, ff_queued
from bot.core.database import db
from .tordownload import TorDownloader
from .func_utils import getfeed, encode, editMessage, sendMessage, convertBytes
from .text_utils import TextEditor
from .ffencoder import FFEncoder
from .tguploader import TgUploader
from .reporter import rep

btn_formatter = {
    '1080': '1080p',
    '720': '720p',
    '480': '480p'
}

# Read TG_PROTECT_CONTENT from env, default True
PROTECT_CONTENT = True if getattr(Var, "TG_PROTECT_CONTENT", "1") == "1" else False


# ----------------- Fetch Animes -----------------
async def fetch_animes():
    await rep.report("Fetch Animes Started !!", "info")
    while True:
        await asyncio.sleep(60)
        if ani_cache.get('fetch_animes'):
            for link in Var.RSS_ITEMS:
                if (info := await getfeed(link, 0)):
                    bot_loop.create_task(get_animes(info.title, info.link))


# ----------------- Get & Encode Anime -----------------
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
        qual_data = ani_data.get('episodes', {}).get(str(ep_no)) if ani_data else None
        if not force and qual_data and all(qual_data.get(q, {}).get('uploaded') for q in Var.QUALS):
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

        # Download with retries
        dl = None
        for attempt in range(3):
            dl = await TorDownloader("./downloads").download(torrent, name)
            if dl and ospath.exists(dl):
                break
            await rep.report(f"Download failed or incomplete. Retrying ({attempt+1}/3)...", "warning")
            await asyncio.sleep(5)

        if not dl or not ospath.exists(dl):
            await rep.report(f"File Download Incomplete after retries, Skipping", "error")
            try: await stat_msg.delete()
            except: pass
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
            await asyncio.sleep(1.0)
            await rep.report(f"Starting Encode ({qual})...", "info")

            try:
                out_path = await FFEncoder(stat_msg, dl, filename, qual).start_encode()
            except Exception as e:
                await rep.report(f"Error: {e}, Cancelled, Retry Again!", "error")
                try: await stat_msg.delete()
                except: pass
                ffLock.release()
                return

            await rep.report(f"✅ Successfully Compressed ({qual}). Uploading...", "info")
            await editMessage(stat_msg, f"‣ <b>Anime Name :</b> <b><i>{filename}</i></b>\n\n<i>Ready to Upload...</i>")
            await asyncio.sleep(1.0)

            try:
                uploaded_msg = await TgUploader(stat_msg).upload(out_path, qual)
            except Exception as e:
                await rep.report(f"Error uploading: {e}", "error")
                try: await stat_msg.delete()
                except: pass
                ffLock.release()
                return

            msg_id = uploaded_msg.id

            # ----------------- URL Button for Auto PM -----------------
            if post_msg:
                btn_label = btn_formatter.get(qual, qual)
                start_payload = f"sendfile_{ani_id}_{ep_no}_{qual}_{msg_id}"
                new_btn = InlineKeyboardButton(
                    f"{btn_label} - {convertBytes(uploaded_msg.document.file_size)}",
                    url=f"https://t.me/{Var.BOT_USERNAME}?start={start_payload}"
                )
                btns.append([new_btn])
                try:
                    await editMessage(post_msg, post_msg.caption.html if post_msg.caption else "", InlineKeyboardMarkup(btns))
                except Exception as e:
                    await rep.report(f"Failed to edit post buttons: {e}", "error")

            # Save DB
            await db.saveAnime(ani_id, ep_no, qual, msg_id=msg_id, post_id=post_id)

            bot_loop.create_task(extra_utils(msg_id, out_path))

        ffLock.release()
        try: await stat_msg.delete()
        except: pass

        try: await aioremove(dl)
        except: pass

        ani_cache.setdefault('completed', set()).add(ani_id)

    except Exception:
        await rep.report(format_exc(), "error")


# ----------------- Start Handler for Auto PM -----------------
@bot.on_message(filters.private & filters.command("start"))
async def start_handler(client, message):
    text = message.text
    if text.startswith("/start sendfile_"):
        parts = text.split("_")
        ani_id, ep, qual, msg_id = parts[1], parts[2], parts[3], parts[4]
        await handle_file_click_pm(message.chat.id, ani_id, ep, qual, msg_id)


async def handle_file_click_pm(user_id, ani_id, ep, qual, msg_id):
    """Deliver file in PM automatically."""
    try:
        file_msg = await bot.get_messages(Var.FILE_STORE, message_ids=int(msg_id))
        sent_msg = None
        if file_msg.document:
            sent_msg = await bot.send_document(
                chat_id=user_id,
                document=file_msg.document.file_id,
                caption=f"✅ File delivered. Auto-deletes in {int(getattr(Var,'DEL_TIMER',300))//60} min.",
                protect_content=PROTECT_CONTENT
            )
        elif file_msg.video:
            sent_msg = await bot.send_video(
                chat_id=user_id,
                video=file_msg.video.file_id,
                caption=f"✅ File delivered. Auto-deletes in {int(getattr(Var,'DEL_TIMER',300))//60} min.",
                protect_content=PROTECT_CONTENT
            )

        if sent_msg and getattr(Var, "AUTO_DEL", "False") == "True":
            delay = int(getattr(Var, "DEL_TIMER", 300))
            bot_loop.create_task(auto_delete_message(user_id, sent_msg.id, delay))
        await db.markUserReceived(ani_id, ep, qual, user_id)
    except Exception as e:
        pass  # can log if needed


# ----------------- Auto Delete -----------------
async def auto_delete_message(chat_id, msg_id, delay):
    await asyncio.sleep(delay)
    try:
        await bot.delete_messages(chat_id, msg_id)
    except:
        pass


# ----------------- Extra Utils -----------------
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
