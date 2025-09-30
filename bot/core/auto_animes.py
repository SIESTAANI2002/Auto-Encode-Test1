# bot/core/auto_animes.py
import asyncio
from asyncio import Event
from os import path as ospath
from aiofiles.os import remove as aioremove
from traceback import format_exc
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
import hashlib

from bot import bot, bot_loop, Var, ani_cache, ffQueue, ffLock, ff_queued
from .database import db
from .tordownload import TorDownloader
from .func_utils import getfeed, encode, editMessage, sendMessage, convertBytes
from .text_utils import TextEditor
from .ffencoder import FFEncoder
from .tguploader import TgUploader
from .reporter import rep

btn_formatter = {
    '1080': '1080p',
    '480': '480p'
}

# ----------------- Fetch RSS ----------------- #
async def fetch_animes():
    await rep.report("Fetch Animes Started !!", "info")
    while True:
        await asyncio.sleep(60)
        if ani_cache.get('fetch_animes'):
            for link in Var.RSS_ITEMS:
                if (info := await getfeed(link, 0)):
                    bot_loop.create_task(get_animes(info.title, info.link))

# ----------------- Main Processing ----------------- #
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

        # ----------------- Download ----------------- #
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

        # ----------------- Encode & Upload ----------------- #
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

            # ----------------- Short key for callback ----------------- #
            key = hashlib.md5(out_path.encode()).hexdigest()
            if not hasattr(bot, "file_map"):
                bot.file_map = {}
            bot.file_map[key] = out_path

            # ----------------- Inline Button ----------------- #
            btn_label = btn_formatter.get(qual, qual)
            new_btn = InlineKeyboardButton(
                f"{btn_label} - {convertBytes(msg.document.file_size)}",
                callback_data=f"sendfile|{ani_id}|{ep_no}|{qual}|{key}"
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
            await db.saveAnime(ani_id, ep_no, qual, post_id)

            # Extra utils (backup etc.)
            bot_loop.create_task(extra_utils(msg_id, out_path))

        ffLock.release()
        await stat_msg.delete()
        await aioremove(dl)
        ani_cache.setdefault('completed', set()).add(ani_id)

    except Exception:
        await rep.report(format_exc(), "error")

# ----------------- Extra Utils ----------------- #
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

# ----------------- Callback Handler ----------------- #
@bot.on_callback_query()
async def inline_button_handler(client, callback_query):
    data = callback_query.data
    if data.startswith("sendfile|"):
        _, ani_id, ep_no, qual, key = data.split("|")
        file_path = bot.file_map.get(key)
        if not file_path:
            await callback_query.answer("File not available.", show_alert=True)
            return

        user_id = callback_query.from_user.id

        # Check if user already received file
        if await db.hasUserReceived(ani_id, int(ep_no), qual, user_id):
            # Send website link if second click
            await callback_query.answer("You already received the file! Visit website instead.", url=Var.WEBSITE, show_alert=True)
            return

        # Mark as received
        await db.markUserReceived(ani_id, int(ep_no), qual, user_id)

        # Send file in PM
        try:
            await client.send_document(user_id, file_path, caption=f"{qual} File for {ani_id} Ep{ep_no}")
            await callback_query.answer("File sent in PM!", show_alert=True)
        except Exception as e:
            await callback_query.answer(f"Failed: {e}", show_alert=True)
