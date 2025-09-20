# bot/core/auto_animes.py
import asyncio
from asyncio import Event
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

# button label mapper
btn_formatter = {
    '1080': '1080p',
    '720': '720p'
}

# in-memory cache for post messages to allow 2 buttons in single post
episode_posts = {}  # (ani_id, ep_no) -> Message


async def fetch_animes():
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
    try:
        aniInfo = TextEditor(name)
        await aniInfo.load_anilist()
        ani_id = aniInfo.adata.get('id')
        ep_no = aniInfo.pdata.get("episode_number")

        if not ani_id:
            ani_id = abs(hash(name)) % (10 ** 9)

        if ani_id not in ani_cache.get('ongoing', set()):
            ani_cache.setdefault('ongoing', set()).add(ani_id)
        elif not force:
            return

        if not force:
           anime_doc = await db.getAnime(ani_id)
        if anime_doc:
           ep_info = anime_doc.get(ep_no, {})
        if ep_info.get(qual):
            await rep.report(f"{qual} already uploaded for {name}, skipping.", "info")
            return

        if "[Batch]" in name:
            await rep.report(f"Torrent Skipped (Batch): {name}", "warning")
            return

        await rep.report(f"New Anime Torrent Found!\n{name} from {qual} feed", "info")

        post_msg = None
        post_id = None
        try:
            existing_post_id = await db.getEpisodePost(ani_id, ep_no)
        except Exception:
            existing_post_id = None

        if existing_post_id:
            try:
                post_msg = await bot.get_messages(Var.MAIN_CHANNEL, message_ids=existing_post_id)
                post_id = existing_post_id
            except Exception:
                post_msg = None
                post_id = None


async def get_animes(name, torrent, qual, force=False):
    """
    Process a single RSS entry:
      - resolve Ani metadata
      - skip already uploaded quality (per DB)
      - create or reuse one post per episode
      - download .torrent, encode (in feed quality), upload
      - append button for that quality to the post
    """
    try:
        aniInfo = TextEditor(name)
        await aniInfo.load_anilist()
        ani_id = aniInfo.adata.get('id')
        ep_no = aniInfo.pdata.get("episode_number")

        if not ani_id:
            ani_id = abs(hash(name)) % (10 ** 9)

        if ani_id not in ani_cache.get('ongoing', set()):
            ani_cache.setdefault('ongoing', set()).add(ani_id)
        elif not force:
            return

        # Safe initialization of ep_info
        anime_doc = await db.getAnime(ani_id)
        ep_info = {}
        if anime_doc:
            ep_info = anime_doc.get(ep_no, {})

        if ep_info.get(qual):  # this quality already uploaded
            await rep.report(f"{qual} already uploaded for {name}, skipping.", "info")
            return

        if "[Batch]" in name:
            await rep.report(f"Torrent Skipped (Batch): {name}", "warning")
            return

        await rep.report(f"New Anime Torrent Found!\n{name} from {qual} feed", "info")

        post_msg = None
        post_id = None
        try:
            existing_post_id = await db.getEpisodePost(ani_id, ep_no)
        except Exception:
            existing_post_id = None

        if existing_post_id:
            try:
                post_msg = await bot.get_messages(Var.MAIN_CHANNEL, message_ids=existing_post_id)
                post_id = existing_post_id
            except Exception:
                post_msg = None
                post_id = None

        if not post_msg:
            try:
                poster = await aniInfo.get_poster()
            except Exception:
                poster = None
            caption = await aniInfo.get_caption()
            post_msg = await bot.send_photo(Var.MAIN_CHANNEL, photo=poster, caption=caption)
            post_id = post_msg.id
            episode_posts[(ani_id, ep_no)] = post_msg

        stat_msg = await sendMessage(
            Var.MAIN_CHANNEL, 
            f"‣ <b>Anime Name :</b> <b><i>{name}</i></b>\n\n<i>Downloading...</i>"
        )

        dl = await TorDownloader("./downloads").download(torrent, name)
        if not dl or not ospath.exists(dl):
            await rep.report(f"File Download Incomplete, Try Again: {name}", "error")
            try:
                if stat_msg:
                    await stat_msg.delete()
            except Exception:
                pass
            return

        # safe editMessage call
        try:
            if stat_msg:
                await editMessage(stat_msg, f"‣ <b>Anime Name :</b> <b><i>{name}</i></b>\n\n<i>Ready to Encode...</i>")
        except Exception:
            pass

        await rep.report(f"Queued for encode: {name} [{qual}]", "info")
        await ffLock.acquire()

        try:
            filename = await aniInfo.get_upname(qual)
            out_path = f"./encode/{filename}" if filename else None

            try:
                if stat_msg:
                    await editMessage(stat_msg, f"‣ <b>Anime Name :</b> <b><i>{filename or name}</i></b>\n\n<i>Encoding Started...</i>")
            except Exception:
                pass

            try:
                encoded_path = await FFEncoder(stat_msg, dl, filename, qual).start_encode()
            except Exception as e:
                await rep.report(f"Error encoding {name}: {e}", "error")
                try:
                    if stat_msg:
                        await stat_msg.delete()
                except Exception:
                    pass
                return

            await rep.report(f"Successfully Compressed {filename}", "info")
            try:
                if stat_msg:
                    await editMessage(stat_msg, f"‣ <b>Anime Name :</b> <b><i>{filename}</i></b>\n\n<i>Uploading {qual}...</i>")
            except Exception:
                pass

            try:
                uploaded_msg = await TgUploader(stat_msg).upload(encoded_path, qual)
            except Exception as e:
                await rep.report(f"Error uploading {filename}: {e}", "error")
                try:
                    if stat_msg:
                        await stat_msg.delete()
                except Exception:
                    pass
                return

            me = await bot.get_me()
            tg_username = me.username
            link = f"https://telegram.me/{tg_username}?start={await encode('get-'+str(uploaded_msg.id * abs(Var.FILE_STORE)))}"
            button = InlineKeyboardButton(
                f"{btn_formatter.get(qual, qual)} - {convertBytes(uploaded_msg.document.file_size)}", 
                url=link
            )

            try:
                if (ani_id, ep_no) in episode_posts:
                    post_msg = episode_posts[(ani_id, ep_no)]
                else:
                    post_msg = await bot.get_messages(Var.MAIN_CHANNEL, message_ids=post_id)

                existing_kb = []
                if post_msg.reply_markup and hasattr(post_msg.reply_markup, "inline_keyboard"):
                    existing_kb = post_msg.reply_markup.inline_keyboard or []

                if existing_kb and len(existing_kb[-1]) == 1:
                    existing_kb[-1].append(button)
                else:
                    existing_kb.append([button])

                await editMessage(post_msg, post_msg.caption.html if post_msg.caption else "", InlineKeyboardMarkup(existing_kb))
            except Exception as e:
                await rep.report(f"Failed to edit post buttons: {e}", "error")

            try:
                await db.saveAnime(ani_id, ep_no, qual, post_id)
            except Exception:
                pass

            bot_loop.create_task(extra_utils(uploaded_msg.id, encoded_path))
            await rep.report(f"Finished {filename} [{qual}] and added button.", "info")

        finally:
            try:
                ffLock.release()
            except Exception:
                pass

            try:
                await aioremove(dl)
            except Exception:
                pass

            try:
                if stat_msg:
                    await stat_msg.delete()
            except Exception:
                pass

        ani_cache.setdefault('completed', set()).add(ani_id)

    except Exception:
        await rep.report(format_exc(), "error")

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
