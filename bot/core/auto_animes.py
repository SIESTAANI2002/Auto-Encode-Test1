# bot/core/auto_animes.py
import asyncio
from asyncio import Event
from os import path as ospath
from aiofiles.os import remove as aioremove
from traceback import format_exc
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot import bot, bot_loop, Var, ani_cache, ffLock
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

episode_posts = {}  # cache to prevent duplicate posts per episode


async def fetch_animes():
    """Fetch each RSS feed and schedule get_animes"""
    await rep.report("Fetch Animes Started !!", "info")
    while True:
        try:
            await asyncio.sleep(60)
            if not ani_cache.get('fetch_animes'):
                continue
            if not Var.RSS_ITEMS:
                await rep.report("No RSS feeds configured.", "warning")
                continue

            for qual, feed_link in Var.RSS_ITEMS.items():
                try:
                    entry = await getfeed(feed_link, 0)
                    if entry:
                        bot_loop.create_task(get_animes(entry.title, entry.link, qual))
                except Exception as e:
                    await rep.report(f"Error fetching feed {qual}: {e}", "error")

        except Exception:
            await rep.report(format_exc(), "error")


async def get_animes(name, torrent, qual, force=False):
    """Process a single anime entry"""
    try:
        aniInfo = TextEditor(name)
        await aniInfo.load_anilist()
        ani_id = aniInfo.adata.get('id') or abs(hash(name)) % (10 ** 9)
        ep_no = aniInfo.pdata.get("episode_number")

        # Prevent duplicate processing
        if ani_id in ani_cache.get('ongoing', set()) and not force:
            return
        ani_cache.setdefault('ongoing', set()).add(ani_id)

        # Check DB if quality already uploaded
        anime_doc = await db.getAnime(ani_id)
        ep_info = anime_doc.get(ep_no, {}) if anime_doc else {}
        if ep_info.get(qual):
            await rep.report(f"{qual} already uploaded for {name}, skipping.", "info")
            return

        if "[Batch]" in name:
            await rep.report(f"Torrent Skipped (Batch): {name}", "warning")
            return

        await rep.report(f"New Anime Torrent Found!\n{name} from {qual} feed", "info")

        # Get or create post message
        post_msg = None
        post_id = await db.getEpisodePost(ani_id, ep_no)
        if post_id:
            try:
                post_msg = await bot.get_messages(Var.MAIN_CHANNEL, message_ids=post_id)
            except Exception:
                post_msg = None

        if not post_msg:
            poster = await aniInfo.get_poster()
            caption = await aniInfo.get_caption()
            post_msg = await bot.send_photo(Var.MAIN_CHANNEL, photo=poster, caption=caption)
            post_id = post_msg.id
            episode_posts[(ani_id, ep_no)] = post_msg

        stat_msg = await sendMessage(Var.MAIN_CHANNEL, f"‣ <b>Anime Name :</b> <b><i>{name}</i></b>\n\n<i>Downloading...</i>")

        # Retry logic for torrent download
        dl = None
        for attempt in range(3):
            dl = await TorDownloader("./downloads").download(torrent, name)
            if dl and ospath.exists(dl):
                break
            await rep.report(f"Download attempt {attempt+1} failed for {name}. Retrying...", "warning")
            await asyncio.sleep(15)
        if not dl or not ospath.exists(dl):
            await rep.report(f"File Download Incomplete after retries: {name}", "error")
            try:
                await stat_msg.delete()
            except Exception:
                pass
            return

        await editMessage(stat_msg, f"‣ <b>Anime Name :</b> <b><i>{name}</i></b>\n\n<i>Ready to Encode...</i>")
        await rep.report(f"Queued for encode: {name} [{qual}]", "info")

        await ffLock.acquire()
        try:
            filename = await aniInfo.get_upname(qual)
            encoded_path = await FFEncoder(stat_msg, dl, filename, qual).start_encode()
            await rep.report(f"Successfully Compressed {filename}", "info")

            await editMessage(stat_msg, f"‣ <b>Anime Name :</b> <b><i>{filename}</i></b>\n\n<i>Uploading {qual}...</i>")
            uploaded_msg = await TgUploader(stat_msg).upload(encoded_path, qual)

            link = f"https://telegram.me/{(await bot.get_me()).username}?start={await encode('get-'+str(uploaded_msg.id * abs(Var.FILE_STORE)))}"
            button = InlineKeyboardButton(f"{btn_formatter.get(qual, qual)} - {convertBytes(uploaded_msg.document.file_size)}", url=link)

            # Add button to post message
            try:
                if post_msg:
                    existing_kb = post_msg.reply_markup.inline_keyboard if post_msg.reply_markup else []
                    if existing_kb and len(existing_kb[-1]) == 1:
                        existing_kb[-1].append(button)
                    else:
                        existing_kb.append([button])
                    await editMessage(post_msg, post_msg.caption.html if post_msg.caption else "", InlineKeyboardMarkup(existing_kb))
            except Exception as e:
                await rep.report(f"Failed to edit post buttons: {e}", "error")

            # Save in DB
            await db.saveAnime(ani_id, ep_no, qual, post_id)
            bot_loop.create_task(extra_utils(uploaded_msg.id, encoded_path))

            await rep.report(f"Finished {filename} [{qual}] and added button.", "info")

        finally:
            ffLock.release()
            try:
                await aioremove(dl)
            except Exception:
                pass
            try:
                await stat_msg.delete()
            except Exception:
                pass

        ani_cache.setdefault('completed', set()).add(ani_id)

    except Exception:
        await rep.report(format_exc(), "error")


async def extra_utils(msg_id, out_path):
    """Called after successful upload"""
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
