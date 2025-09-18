import asyncio
from asyncio import Event, sleep as asleep
from asyncio.subprocess import PIPE
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

# Formatting buttons for Telegram post
btn_formatter = {
    '1080': "1080p",
    '720': "𝟳𝟮𝟬𝗽"
}

async def fetch_animes():
    await rep.report("Fetch Animes Started !!", "info")
    while True:
        await asleep(60)
        if ani_cache['fetch_animes']:
            for qual_feed, link in Var.RSS_ITEMS.items():
                await rep.report(f"Checking {qual_feed} feed: {link}", "info")
                info = await getfeed(link, 0)
                if info:
                    bot_loop.create_task(get_animes(info.title, info.link, qual_feed))


async def get_animes(name, torrent, qual_feed, force=False):
    try:
        aniInfo = TextEditor(name)
        await aniInfo.load_anilist()
        ani_id, ep_no = aniInfo.adata.get('id'), aniInfo.pdata.get("episode_number")

        if ani_id not in ani_cache['ongoing']:
            ani_cache['ongoing'].add(ani_id)
        elif not force:
            return

        if not force and ani_id in ani_cache['completed']:
            return

        await rep.report(f"New Anime Torrent Found!\n\n{name} from {qual_feed} feed", "info")

        post_msg = await bot.send_photo(
            Var.MAIN_CHANNEL,
            photo=await aniInfo.get_poster(),
            caption=await aniInfo.get_caption()
        )
        await asleep(1.5)

        stat_msg = await sendMessage(
            Var.MAIN_CHANNEL,
            f"‣ <b>Anime Name :</b> <b><i>{name}</i></b>\n\n<i>Downloading...</i>"
        )

        dl = await TorDownloader("./downloads").download(torrent, name)
        if not dl or not ospath.exists(dl):
            await rep.report(f"File Download Incomplete, Try Again for {name}", "error")
            await stat_msg.delete()
            return

        await rep.report(f"Downloaded {name} ({qual_feed}) successfully", "info")

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
            await asleep(1.5)

            await rep.report(f"Starting Encode for {qual}...", "info")
            try:
                out_path = await FFEncoder(stat_msg, dl, filename, qual).start_encode()
            except Exception as e:
                await rep.report(f"Error encoding {filename}: {e}", "error")
                await stat_msg.delete()
                ffLock.release()
                return
            await rep.report(f"Encoded {filename} successfully", "info")
            
            await editMessage(stat_msg, f"‣ <b>Anime Name :</b> <b><i>{filename}</i></b>\n\n<i>Uploading...</i>")
            await asleep(1.5)
            try:
                msg = await TgUploader(stat_msg).upload(out_path, qual)
            except Exception as e:
                await rep.report(f"Error uploading {filename}: {e}", "error")
                await stat_msg.delete()
                ffLock.release()
                return
            await rep.report(f"Uploaded {filename} successfully", "info")
            
            msg_id = msg.id
            link = f"https://telegram.me/{(await bot.get_me()).username}?start={await encode('get-'+str(msg_id * abs(Var.FILE_STORE)))}"
            
            # Add buttons to single post
            if post_msg:
                if len(btns) != 0 and len(btns[-1]) == 1:
                    btns[-1].insert(1, InlineKeyboardButton(f"{btn_formatter[qual]} - {convertBytes(msg.document.file_size)}", url=link))
                else:
                    btns.append([InlineKeyboardButton(f"{btn_formatter[qual]} - {convertBytes(msg.document.file_size)}", url=link)])
                await editMessage(post_msg, post_msg.caption.html if post_msg.caption else "", InlineKeyboardMarkup(btns))
                
            await db.saveAnime(ani_id, ep_no, qual, post_id)
            bot_loop.create_task(extra_utils(msg_id, out_path))
        ffLock.release()
        
        await stat_msg.delete()
        await aioremove(dl)
        ani_cache['completed'].add(ani_id)
    except Exception:
        await rep.report(format_exc(), "error")


async def extra_utils(msg_id, out_path):
    msg = await bot.get_messages(Var.FILE_STORE, message_ids=msg_id)

    if Var.BACKUP_CHANNEL != 0:
        for chat_id in Var.BACKUP_CHANNEL.split():
            await msg.copy(int(chat_id))
            
    # Add-ons: MediaInfo, Screenshots, Sample Video if needed
