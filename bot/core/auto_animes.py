import asyncio
from asyncio import Event
from os import path as ospath
from aiofiles.os import remove as aioremove
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from traceback import format_exc

from bot import bot, bot_loop, Var, ani_cache, ffQueue, ffLock, ff_queued
from .tordownload import TorDownloader
from .database import db
from .func_utils import getfeed, encode, editMessage, sendMessage
from .text_utils import TextEditor
from .ffencoder import FFEncoder
from .tguploader import TgUploader
from .reporter import rep

btn_formatter = {
    '720': '𝟳𝟮𝟬𝗽',
    '1080': '𝟭𝟬𝟴𝟬𝗽'
}

async def fetch_animes():
    await rep.report("Fetch Animes Started !!", "info")
    while True:
        await asyncio.sleep(60)
        if ani_cache['fetch_animes']:
            # RSS_ITEMS can be list or space-separated string
            rss_list = Var.RSS_ITEMS if isinstance(Var.RSS_ITEMS, list) else Var.RSS_ITEMS.split()
            for link in rss_list:
                info = await getfeed(link, 0)
                if info:
                    # Determine quality from feed link
                    if "720" in link or "r=720" in link:
                        quality = '720'
                    elif "1080" in link or "r=1080" in link:
                        quality = '1080'
                    else:
                        continue
                    bot_loop.create_task(process_anime(info.title, info.link, quality))

async def process_anime(name, torrent, quality):
    try:
        aniInfo = TextEditor(name)
        await aniInfo.load_anilist()
        ani_id = aniInfo.adata.get('id')
        ep_no = aniInfo.pdata.get("episode_number")
        
        if ani_id not in ani_cache['ongoing']:
            ani_cache['ongoing'].add(ani_id)
        else:
            # Already processing
            return

        if ani_id in ani_cache['completed'] and ep_no in ani_cache['completed'][ani_id]:
            # Already uploaded all qualities
            if quality in ani_cache['completed'][ani_id][ep_no]:
                return

        # Check DB for existing post for this episode
        ani_data = await db.getAnime(ani_id)
        post_id = None
        if ani_data and ep_no in ani_data:
            # Post exists, edit it
            post_id = ani_data[ep_no].get('post_id')
        
        if "[Batch]" in name:
            await rep.report(f"Torrent Skipped!\n{name}", "warning")
            return

        await rep.report(f"New Anime Found!\n{name}", "info")

        # If no post exists, send initial post with info
        if not post_id:
            post_msg = await bot.send_photo(
                Var.MAIN_CHANNEL,
                photo=await aniInfo.get_poster(),
                caption=await aniInfo.get_caption()
            )
            post_id = post_msg.id
        else:
            post_msg = await bot.get_messages(Var.MAIN_CHANNEL, message_ids=post_id)

        stat_msg = await sendMessage(Var.MAIN_CHANNEL, f"‣ <b>{name}</b>\n<i>Downloading...</i>")
        dl = await TorDownloader("./downloads").download(torrent, name)
        if not dl or not ospath.exists(dl):
            await rep.report(f"File Download Incomplete: {name}", "error")
            await stat_msg.delete()
            return

        ffEvent = Event()
        ff_queued[post_id] = ffEvent
        if ffLock.locked():
            await editMessage(stat_msg, f"‣ <b>{name}</b>\n<i>Queued to Encode...</i>")
        await ffQueue.put(post_id)
        await ffEvent.wait()

        await ffLock.acquire()
        try:
            filename = await aniInfo.get_upname(quality)
            await editMessage(stat_msg, f"‣ <b>{filename}</b>\n<i>Encoding...</i>")
            out_path = await FFEncoder(stat_msg, dl, filename, quality).start_encode()

            await editMessage(stat_msg, f"‣ <b>{filename}</b>\n<i>Uploading...</i>")
            msg = await TgUploader(stat_msg).upload(out_path, quality)

            # Add button
            link = f"https://telegram.me/{(await bot.get_me()).username}?start={await encode('get-'+str(msg.id * abs(Var.FILE_STORE)))}"
            if post_msg.reply_markup:
                btns = post_msg.reply_markup.inline_keyboard
                if len(btns) != 0 and len(btns[-1]) == 1:
                    btns[-1].append(InlineKeyboardButton(f"{btn_formatter[quality]} - {msg.document.file_size}", url=link))
                else:
                    btns.append([InlineKeyboardButton(f"{btn_formatter[quality]} - {msg.document.file_size}", url=link)])
            else:
                btns = [[InlineKeyboardButton(f"{btn_formatter[quality]} - {msg.document.file_size}", url=link)]]
            await editMessage(post_msg, post_msg.caption.html if post_msg.caption else "", InlineKeyboardMarkup(btns))

            # Save DB info
            await db.saveAnime(ani_id, ep_no, quality, post_id)
            if ani_id not in ani_cache['completed']:
                ani_cache['completed'][ani_id] = {}
            if ep_no not in ani_cache['completed'][ani_id]:
                ani_cache['completed'][ani_id][ep_no] = set()
            ani_cache['completed'][ani_id][ep_no].add(quality)

        finally:
            ffLock.release()
            await stat_msg.delete()
            await aioremove(dl)

    except Exception as e:
        await rep.report(f"Error: {format_exc()}", "error")
