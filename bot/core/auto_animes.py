# bot/core/auto_animes.py
import asyncio
from asyncio import Event
from os import path as ospath
from aiofiles.os import remove as aioremove
from traceback import format_exc
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot import bot, bot_loop, Var, ani_cache, ffQueue, ffLock, ff_queued, db
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

# ---------------- Fetch RSS / Anime ---------------- #
async def fetch_animes():
    await rep.report("Fetch Animes Started !!", "info")
    while True:
        await asyncio.sleep(60)
        if ani_cache.get('fetch_animes'):
            for link in Var.RSS_ITEMS:
                if (info := await getfeed(link, 0)):
                    bot_loop.create_task(get_animes(info.title, info.link))

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
            file_path = out_path

            # Telegram buttons for post message
            btn_label = btn_formatter.get(qual, qual)
            btn = InlineKeyboardButton(
                f"{btn_label} - {convertBytes(msg.document.file_size)}",
                callback_data=f"sendfile|{ani_id}|{ep_no}|{qual}|{file_path}"
            )
            btns.append([btn])
            await editMessage(
                post_msg,
                post_msg.caption.html if post_msg.caption else "",
                InlineKeyboardMarkup(btns)
            )

        ffLock.release()
        await stat_msg.delete()

        # Cleanup original file after all qualities
        await aioremove(dl)
        ani_cache.setdefault('completed', set()).add(ani_id)

    except Exception:
        await rep.report(format_exc(), "error")


# ---------------- Inline Button Handler ---------------- #
@bot.on_callback_query()
async def inline_button_handler(client, callback_query):
    data = callback_query.data
    if data.startswith("sendfile|"):
        try:
            _, ani_id, ep_no, qual, file_path = data.split("|")
            ep_no = int(ep_no)
            user_id = callback_query.from_user.id

            # Check if user already received
            received = await db.hasUserReceived(ani_id, ep_no, qual, user_id)

            if received:
                # User already got the file → show website button
                keyboard = InlineKeyboardMarkup(
                    [[InlineKeyboardButton("Visit Website", url=Var.WEBSITE)]]
                )
                await callback_query.edit_message_text(
                    "You already received this file! Visit our website for more content.",
                    reply_markup=keyboard
                )
                await callback_query.answer()
                return

            # Send file privately
            await bot.send_document(user_id, file_path)
            await db.markUserReceived(ani_id, ep_no, qual, user_id)
            await callback_query.answer("File sent to your PM!", show_alert=True)

        except Exception:
            await rep.report(format_exc(), "error")
