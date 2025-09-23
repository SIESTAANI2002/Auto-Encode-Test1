# bot/core/auto_animes.py
import asyncio
from asyncio import Event
from os import path as ospath
from aiofiles.os import remove as aioremove
from traceback import format_exc
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot import bot, bot_loop, Var, ani_cache, ffLock, ffQueue, ff_queued
from .tordownload import TorDownloader
from .database import db
from .func_utils import getfeed, encode, editMessage, sendMessage, convertBytes
from .text_utils import TextEditor
from .ffencoder import FFEncoder
from .tguploader import TgUploader
from .reporter import rep

# Quality label mapping
btn_formatter = {
    '1080': '1080p',
    '720': '720p'
}

# In-memory cache to store post messages
episode_posts = {}  # (ani_id, ep_no) -> Message


async def fetch_animes():
    """
    Main loop to fetch RSS feeds.
    Supports single or multiple feeds.
    """
    await rep.report("Fetch Animes Started !!", "info")
    while True:
        try:
            await asyncio.sleep(60)
            if not ani_cache.get('fetch_animes'):
                continue

            if not Var.RSS_ITEMS:
                await rep.report("No RSS feeds configured.", "warning")
                continue

            # handle if RSS_ITEMS is dict or list
            if isinstance(Var.RSS_ITEMS, dict):
                feeds = Var.RSS_ITEMS.items()
            else:
                feeds = [(f"feed_{i}", link) for i, link in enumerate(Var.RSS_ITEMS)]

            for qual, feed_link in feeds:
                try:
                    entry = await getfeed(feed_link, 0)
                    if entry:
                        bot_loop.create_task(get_animes(entry.title, entry.link, qual))
                except Exception as e:
                    await rep.report(f"Error fetching feed {qual}: {e}", "error")
        except Exception:
            await rep.report(format_exc(), "error")


async def get_animes(name, torrent, qual, force=False):
    """
    Process a single anime episode:
    - Resolves metadata
    - Checks DB to prevent duplicate uploads
    - Downloads torrent with retry
    - Encodes and uploads
    - Adds buttons per quality
    """
    try:
        aniInfo = TextEditor(name)
        await aniInfo.load_anilist()
        ani_id = aniInfo.adata.get('id') or abs(hash(name)) % (10 ** 9)
        ep_no = aniInfo.pdata.get("episode_number")

        # Ongoing/completed caching
        if ani_id not in ani_cache.get('ongoing', set()):
            ani_cache.setdefault('ongoing', set()).add(ani_id)
        elif not force:
            return

        # DB check for this quality
        anime_doc = await db.getAnime(ani_id)
        ep_info = anime_doc.get(ep_no, {}) if anime_doc else {}
        if ep_info.get(qual) and not force:
            await rep.report(f"{qual} already uploaded for {name}, skipping.", "info")
            return

        if "[Batch]" in name:
            await rep.report(f"Torrent Skipped (Batch): {name}", "warning")
            return

        await rep.report(f"New Anime Torrent Found!\n{name} from {qual} feed", "info")

        # Check for existing post
        post_msg = None
        post_id = await db.getEpisodePost(ani_id, ep_no)
        if post_id:
            try:
                post_msg = await bot.get_messages(Var.MAIN_CHANNEL, message_ids=post_id)
            except Exception:
                post_msg = None
                post_id = None

        if not post_msg:
            poster = await aniInfo.get_poster()
            caption = await aniInfo.get_caption()
            post_msg = await bot.send_photo(Var.MAIN_CHANNEL, photo=poster, caption=caption)
            post_id = post_msg.id
            episode_posts[(ani_id, ep_no)] = post_msg

        # Status message
        stat_msg = await sendMessage(Var.MAIN_CHANNEL, f"‣ <b>Anime Name :</b> <b><i>{name}</i></b>\n\n<i>Downloading...</i>")

        # --- Torrent Download with Retry ---
        dl_path = None
        retry_count = 0
        while retry_count < 3:
            dl_path = await TorDownloader("./downloads").download(torrent, name)
            if dl_path and ospath.exists(dl_path):
                break
            retry_count += 1
            await rep.report(f"Download incomplete, retry {retry_count}/3: {name}", "warning")
            await asyncio.sleep(5)

        if not dl_path or not ospath.exists(dl_path):
            await rep.report(f"❌ Failed to download after 3 retries: {name}", "error")
            try: await stat_msg.delete()
            except: pass
            return

        await editMessage(stat_msg, f"‣ <b>Anime Name :</b> <b><i>{name}</i></b>\n\n<i>Ready to Encode...</i>")
        await rep.report(f"Queued for encode: {name} [{qual}]", "info")
        await ffLock.acquire()
        try:
            filename = await aniInfo.get_upname(qual)
            if not filename:
                filename = name.replace("/", "_")

            encoded_path = await FFEncoder(stat_msg, dl_path, filename, qual).start_encode()
            await rep.report(f"Successfully Compressed {filename}", "info")

            await editMessage(stat_msg, f"‣ <b>Anime Name :</b> <b><i>{filename}</i></b>\n\n<i>Uploading {qual}...</i>")
            uploaded_msg = await TgUploader(stat_msg).upload(encoded_path, qual)
            tg_username = (await bot.get_me()).username
            link = f"https://telegram.me/{tg_username}?start={await encode('get-'+str(uploaded_msg.id * abs(Var.FILE_STORE)))}"

            # --- Button Handling ---
            btns = []
            if post_msg.reply_markup and hasattr(post_msg.reply_markup, "inline_keyboard"):
                btns = post_msg.reply_markup.inline_keyboard or []

            # Add new button for quality
            new_btn = InlineKeyboardButton(f"{btn_formatter.get(qual, qual)} - {convertBytes(uploaded_msg.document.file_size)}", url=link)
            if btns and len(btns[-1]) == 1:
                btns[-1].append(new_btn)
            else:
                btns.append([new_btn])
            await editMessage(post_msg, post_msg.caption.html if post_msg.caption else "", InlineKeyboardMarkup(btns))

            # --- Save DB ---
            await db.saveAnime(ani_id, ep_no, qual, post_id)
            bot_loop.create_task(extra_utils(uploaded_msg.id, encoded_path))

        finally:
            try: ffLock.release()
            except: pass
            try: await aioremove(dl_path)
            except: pass
            try: await stat_msg.delete()
            except: pass

        ani_cache.setdefault('completed', set()).add(ani_id)

    except Exception:
        await rep.report(format_exc(), "error")


async def extra_utils(msg_id, out_path):
    """After successful upload: copy to backup channels"""
    try:
        msg = await bot.get_messages(Var.FILE_STORE, message_ids=msg_id)
        if Var.BACKUP_CHANNEL and Var.BACKUP_CHANNEL != "0":
            for chat_id in Var.BACKUP_CHANNEL.split():
                try: await msg.copy(int(chat_id))
                except: pass
    except Exception:
        await rep.report(format_exc(), "error")
