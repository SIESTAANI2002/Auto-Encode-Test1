import asyncio
from asyncio import Event
from os import path as ospath
from aiofiles.os import remove as aioremove
from traceback import format_exc
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot import bot, bot_loop, Var, ani_cache, ffQueue, ffLock, ff_queued
from .tordownload import TorDownloader
from .database import db
from .func_utils import getfeed, encode, editMessage, sendMessage, convertBytes
from .text_utils import TextEditor
from .ffencoder import FFEncoder
from .tguploader import TgUploader
from .reporter import rep

btn_formatter = {
    '1080': '1080p',
    '720': '720p'
}

async def fetch_animes():
    await rep.report("Fetch Animes Started !!", "info")
    while True:
        await asyncio.sleep(60)
        if not Var.RSS_ITEMS:
            continue

        for qual, feed_link in Var.RSS_ITEMS.items():
            await rep.report(f"[INFO] Checking {qual} feed: {feed_link}", "info")
            try:
                if (info := await getfeed(feed_link, 0)):
                    bot_loop.create_task(get_animes(info.title, info.link, qual))
            except Exception as e:
                await rep.report(f"[ERROR] Fetching feed failed: {e}", "error")


async def get_animes(name, torrent, qual):
    try:
        aniInfo = TextEditor(name)
        await aniInfo.load_anilist()
        ani_id, ep_no = aniInfo.adata.get('id'), aniInfo.pdata.get("episode_number")

        if ani_id not in ani_cache['ongoing']:
            ani_cache['ongoing'].add(ani_id)
        elif ani_id in ani_cache['completed']:
            return

        if "[Batch]" in name:
            await rep.report(f"Torrent Skipped!\n\n{name}", "warning")
            return

        # Check if a post already exists for this episode
        existing_post_id = await db.getEpisodePost(ani_id, ep_no)
        post_msg = None
        btns = []

        if existing_post_id:
            post_msg = await bot.get_messages(Var.MAIN_CHANNEL, message_ids=existing_post_id)
            # Load existing buttons
            if post_msg.reply_markup:
                btns = post_msg.reply_markup.inline_keyboard

        if not post_msg:
            # Create new post if not exists
            await rep.report(f"New Anime Torrent Found!\n\n{name} from {qual} feed", "info")
            post_msg = await bot.send_photo(
                Var.MAIN_CHANNEL,
                photo=await aniInfo.get_poster(),
                caption=await aniInfo.get_caption()
            )

        stat_msg = await sendMessage(Var.MAIN_CHANNEL, f"‣ <b>Anime Name :</b> <b><i>{name}</i></b>\n\n<i>Downloading...</i>")
        dl = await TorDownloader("./downloads").download(torrent, name)
        if not dl or not ospath.exists(dl):
            await rep.report(f"File Download Incomplete, Try Again", "error")
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

        filename = await aniInfo.get_upname(qual)
        await editMessage(stat_msg, f"‣ <b>Anime Name :</b> <b><i>{name}</i></b>\n\n<i>Ready to Encode {qual}...</i>")
        await asyncio.sleep(1)

        await rep.report(f"Starting Encode for {qual}...", "info")
        try:
            out_path = await FFEncoder(stat_msg, dl, filename, qual).start_encode()
        except Exception as e:
            await rep.report(f"Error: {e}, Cancelled, Retry Again!", "error")
            await stat_msg.delete()
            ffLock.release()
            return

        await rep.report(f"Uploading {qual}...", "info")
        await editMessage(stat_msg, f"‣ <b>Anime Name :</b> <b><i>{filename}</i></b>\n\n<i>Uploading...</i>")
        await asyncio.sleep(1)

        try:
            msg = await TgUploader(stat_msg).upload(out_path, qual)
        except Exception as e:
            await rep.report(f"Error: {e}, Cancelled, Retry Again!", "error")
            await stat_msg.delete()
            ffLock.release()
            return

        await rep.report(f"Successfully Uploaded {qual} to Telegram...", "info")
        msg_id = msg.id
        link = f"https://telegram.me/{(await bot.get_me()).username}?start={await encode('get-'+str(msg_id * abs(Var.FILE_STORE)))}"

        # Add button for this quality
        if btns and len(btns[-1]) == 1:
            btns[-1].append(InlineKeyboardButton(f"{btn_formatter[qual]} - {convertBytes(msg.document.file_size)}", url=link))
        else:
            btns.append([InlineKeyboardButton(f"{btn_formatter[qual]} - {convertBytes(msg.document.file_size)}", url=link)])

        await editMessage(post_msg, post_msg.caption.html if post_msg.caption else "", InlineKeyboardMarkup(btns))

        await db.saveAnime(ani_id, ep_no, qual, post_id)
        bot_loop.create_task(extra_utils(msg_id, out_path))

        ffLock.release()
        await stat_msg.delete()
        await aioremove(dl)
        ani_cache['completed'].add(ani_id)

    except Exception as error:
        await rep.report(format_exc(), "error")


async def extra_utils(msg_id, out_path):
    msg = await bot.get_messages(Var.FILE_STORE, message_ids=msg_id)

    if Var.BACKUP_CHANNEL != 0:
        for chat_id in Var.BACKUP_CHANNEL.split():
            await msg.copy(int(chat_id))
