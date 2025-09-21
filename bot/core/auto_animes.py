import asyncio
from os import path as ospath
from aiofiles.os import remove as aioremove
from traceback import format_exc
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot import bot, bot_loop, Var, ani_cache, ffLock
from .tordownload import TorDownloader
from bot.core.database import db
from .func_utils import getfeed, encode, editMessage, sendMessage, convertBytes
from .text_utils import TextEditor
from .ffencoder import FFEncoder
from .tguploader import TgUploader
from .reporter import rep

# Button label mapper
btn_formatter = {'1080': '1080p', '720': '720p'}

# In-memory cache for post messages (ani_id, ep_no) -> Message
episode_posts = {}  


async def fetch_animes():
    """Main feed loop: check RSS_ITEMS and schedule get_animes for new entries."""
    await rep.report("Fetch Animes Started !!", "info")
    while True:
        try:
            await asyncio.sleep(60)
            if not ani_cache.get('fetch_animes'):
                continue

            if not Var.RSS_ITEMS:
                await rep.report("No RSS feeds configured (Var.RSS_ITEMS empty).", "warning")
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
    """Process a single RSS entry: download → encode → upload → append button."""
    try:
        aniInfo = TextEditor(name)
        await aniInfo.load_anilist()
        ani_id = aniInfo.adata.get('id') or abs(hash(name)) % (10**9)
        ep_no = aniInfo.pdata.get("episode_number")

        # Avoid duplicate processing
        if ani_id not in ani_cache.setdefault('ongoing', set()):
            ani_cache['ongoing'].add(ani_id)
        elif not force:
            return

        # Skip batch releases
        if "[Batch]" in name:
            await rep.report(f"Torrent Skipped (Batch): {name}", "warning")
            return

        # Fetch episode info from DB
        anime_doc = await db.getAnime(ani_id)
        ep_info = anime_doc.get(str(ep_no), {}) if anime_doc else {}
        if ep_info.get(qual) and not force:
            await rep.report(f"{qual} already uploaded for {name}, skipping.", "info")
            return

        await rep.report(f"New Anime Torrent Found!\n{name} from {qual} feed", "info")

        # Get or create post for this episode
        post_msg = None
        post_id = None
        existing_post_id = await db.getEpisodePost(ani_id, ep_no)
        if existing_post_id:
            try:
                post_msg = await bot.get_messages(Var.MAIN_CHANNEL, message_ids=existing_post_id)
                post_id = existing_post_id
            except Exception:
                post_msg = None

        if not post_msg:
            poster = await aniInfo.get_poster()
            caption = await aniInfo.get_caption()
            post_msg = await bot.send_photo(Var.MAIN_CHANNEL, photo=poster, caption=caption)
            post_id = post_msg.id
            episode_posts[(ani_id, ep_no)] = post_msg
            await db.saveEpisodePost(ani_id, ep_no, post_id)

        # Status message
        stat_msg = await sendMessage(Var.MAIN_CHANNEL, f"‣ <b>Anime Name :</b> <b><i>{name}</i></b>\n\n<i>Downloading...</i>")

        # Download
        dl = await TorDownloader("./downloads").download(torrent, name)
        if not dl or not ospath.exists(dl):
            await rep.report(f"File Download Incomplete, Try Again: {name}", "error")
            await safe_delete(stat_msg)
            return

        await editMessage(stat_msg, f"‣ <b>Anime Name :</b> <b><i>{name}</i></b>\n\n<i>Ready to Encode...</i>")
        await rep.report(f"Queued for encode: {name} [{qual}]", "info")

        # Encode (one at a time)
        await ffLock.acquire()
        try:
            filename = await aniInfo.get_upname(qual)
            await editMessage(stat_msg, f"‣ <b>Anime Name :</b> <b><i>{filename or name}</i></b>\n\n<i>Encoding Started...</i>")

            encoded_path = await FFEncoder(stat_msg, dl, filename, qual).start_encode()
            await rep.report(f"Successfully Compressed {filename}", "info")
            await editMessage(stat_msg, f"‣ <b>Anime Name :</b> <b><i>{filename}</i></b>\n\n<i>Uploading {qual}...</i>")

            # Upload
            uploaded_msg = await TgUploader(stat_msg).upload(encoded_path, qual)

            # Button
            me = await bot.get_me()
            tg_username = me.username
            link = f"https://t.me/{tg_username}?start={await encode('get-'+str(uploaded_msg.id * abs(Var.FILE_STORE)))}"
            button = InlineKeyboardButton(f"{btn_formatter.get(qual, qual)} - {convertBytes(uploaded_msg.document.file_size)}", url=link)

            # Merge buttons correctly
            post_msg = episode_posts.get((ani_id, ep_no)) or await bot.get_messages(Var.MAIN_CHANNEL, message_ids=post_id)
            existing_kb = []
            if post_msg.reply_markup and hasattr(post_msg.reply_markup, "inline_keyboard"):
                existing_kb = post_msg.reply_markup.inline_keyboard or []

            # Ensure 2 buttons max on one row
            if existing_kb and len(existing_kb[-1]) == 1:
                existing_kb[-1].append(button)
            else:
                existing_kb.append([button])

            await editMessage(post_msg, post_msg.caption.html if post_msg.caption else "", InlineKeyboardMarkup(existing_kb))

            # Save DB
            await db.saveAnime(ani_id, ep_no, qual, post_id)
            bot_loop.create_task(extra_utils(uploaded_msg.id, encoded_path))
            await rep.report(f"Finished {filename} [{qual}] and added button.", "info")

        finally:
            ffLock.release()
            await safe_delete(stat_msg)
            try: await aioremove(dl)
            except Exception: pass

        # Mark completed
        ani_cache.setdefault('completed', set()).add(ani_id)

    except Exception:
        await rep.report(format_exc(), "error")


async def extra_utils(msg_id, out_path):
    """Copy uploaded files to backup channels."""
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


async def safe_delete(msg):
    """Safely delete a message."""
    try: 
        if msg: 
            await msg.delete()
    except Exception: 
        pass
