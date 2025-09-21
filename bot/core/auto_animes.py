# bot/core/auto_animes.py
import asyncio
from os import path as ospath
from aiofiles.os import remove as aioremove
from traceback import format_exc
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot import bot, bot_loop, Var, ani_cache, ffLock
from bot.core.tordownload import TorDownloader
from bot.core.database import db
from bot.core.func_utils import getfeed, encode, editMessage, sendMessage, convertBytes
from bot.core.text_utils import TextEditor
from bot.core.ffencoder import FFEncoder
from bot.core.tguploader import TgUploader
from bot.core.reporter import rep

# Button label formatter
btn_formatter = {
    "1080": "1080p",
    "720": "720p"
}

# in-memory cache (episode post message objects) to avoid extra API calls
episode_posts = {}  # (ani_id, ep_no_str) -> Message


async def fetch_animes():
    """
    Main loop — check each feed in Var.RSS_ITEMS (expected dict {"720": "url", "1080": "url"})
    and schedule get_animes for each new entry.
    """
    await rep.report("Fetch Animes Started !!", "info")
    while True:
        try:
            await asyncio.sleep(60)
            if not ani_cache.get("fetch_animes"):
                continue

            if not Var.RSS_ITEMS:
                await rep.report("No RSS feeds configured (Var.RSS_ITEMS empty).", "warning")
                continue

            # Var.RSS_ITEMS should be a dict {"720": "url", "1080": "url"}
            for qual, feed_link in Var.RSS_ITEMS.items():
                try:
                    entry = await getfeed(feed_link, 0)
                    if entry:
                        # schedule async processing (don't await here)
                        bot_loop.create_task(get_animes(entry.title, entry.link, qual))
                except Exception as e:
                    await rep.report(f"Error fetching feed {qual}: {e}", "error")
        except Exception:
            await rep.report(format_exc(), "error")


async def get_animes(name, torrent, qual, force=False):
    """
    Process a single RSS entry:
      - resolve Ani metadata
      - skip already uploaded quality (per DB)
      - create or reuse one post per episode
      - download .torrent, encode (in feed quality), upload
      - append button for that quality to the post
    """
    ani_key = None
    try:
        # parse metadata
        aniInfo = TextEditor(name)
        await aniInfo.load_anilist()
        ani_id = aniInfo.adata.get("id") or abs(hash(name)) % (10 ** 9)

        raw_ep = aniInfo.pdata.get("episode_number")
        if not raw_ep:
            # If we cannot determine episode number, skip
            await rep.report(f"Cannot parse episode number for: {name}", "warning")
            return
        ep_no_str = str(raw_ep)  # always store ep as string

        # create unique key per episode+quality for in-memory cache
        ani_key = (str(ani_id), ep_no_str, str(qual))

        # skip batches early
        if "[Batch]" in name:
            await rep.report(f"Torrent Skipped (Batch): {name}", "warning")
            return

        # DB check: skip if this quality already uploaded
        try:
            anime_doc = await db.getAnime(ani_id) or {}
            ep_info = anime_doc.get(ep_no_str, {})
            if ep_info.get(qual) and not force:
                await rep.report(f"{qual} already uploaded for {name}, skipping.", "info")
                return
        except Exception:
            # if DB fails, continue but log
            await rep.report(f"DB check failed for {ani_id} ep {ep_no_str}", "warning")
            ep_info = {}

        # avoid duplicate runs per same (ani_id, ep_no, qual)
        ongoing = ani_cache.setdefault("ongoing", set())
        if ani_key in ongoing and not force:
            # already being processed
            return
        ongoing.add(ani_key)

        await rep.report(f"New Anime Torrent Found!\n{name} from {qual} feed", "info")

        # Try get existing post for this episode
        post_msg = None
        post_id = None
        try:
            existing_post_id = await db.getEpisodePost(ani_id, ep_no_str)
        except Exception:
            existing_post_id = None

        if existing_post_id:
            try:
                post_msg = await bot.get_messages(Var.MAIN_CHANNEL, message_ids=existing_post_id)
                post_id = existing_post_id
            except Exception:
                post_msg = None
                post_id = None

        # If we don't have post_msg, create a new post (first quality)
        if not post_msg:
            try:
                poster = await aniInfo.get_poster()
            except Exception:
                poster = None
            caption = await aniInfo.get_caption()
            try:
                post_msg = await bot.send_photo(Var.MAIN_CHANNEL, photo=poster, caption=caption)
                post_id = post_msg.id
                # persist post mapping right away so other qualities can find it
                try:
                    await db.saveEpisodePost(ani_id, ep_no_str, post_id)
                except Exception:
                    # still proceed even if DB save fails temporarily
                    await rep.report(f"Failed to saveEpisodePost for {ani_id}:{ep_no_str}", "warning")
                # cache in memory
                episode_posts[(str(ani_id), ep_no_str)] = post_msg
            except Exception as e:
                await rep.report(f"Failed to create post for {name}: {e}", "error")
                # release ongoing key and exit
                ongoing.discard(ani_key)
                return

        # status message for progress (separate message)
        try:
            stat_msg = await sendMessage(Var.MAIN_CHANNEL, f"‣ <b>Anime Name :</b> <b><i>{name}</i></b>\n\n<i>Downloading...</i>")
        except Exception as e:
            await rep.report(f"Failed to create status message: {e}", "warning")
            stat_msg = None

        # download the torrent/file
        dl = None
        try:
            dl = await TorDownloader("./downloads").download(torrent, name)
            if not dl or not ospath.exists(dl):
                await rep.report(f"File Download Incomplete, Try Again: {name}", "error")
                if stat_msg:
                    try: await stat_msg.delete()
                    except: pass
                ongoing.discard(ani_key)
                return
        except Exception as e:
            await rep.report(f"Download failed for {name}: {e}", "error")
            if stat_msg:
                try: await stat_msg.delete()
                except: pass
            ongoing.discard(ani_key)
            return

        # Ready to encode
        try:
            if stat_msg:
                await editMessage(stat_msg, f"‣ <b>Anime Name :</b> <b><i>{name}</i></b>\n\n<i>Ready to Encode...</i>")
        except Exception:
            pass

        await rep.report(f"Queued for encode: {name} [{qual}]", "info")

        # acquire encoder lock (only one encoder at a time)
        await ffLock.acquire()
        try:
            filename = await aniInfo.get_upname(qual)
            out_path = f"./encode/{filename}" if filename else None

            try:
                if stat_msg:
                    await editMessage(stat_msg, f"‣ <b>Anime Name :</b> <b><i>{filename or name}</i></b>\n\n<i>Encoding Started...</i>")
            except Exception:
                pass

            # start encoding (FFEncoder handles progress via stat_msg)
            try:
                encoded_path = await FFEncoder(stat_msg, dl, filename, qual).start_encode()
            except Exception as e:
                await rep.report(f"Error encoding {name}: {e}", "error")
                if stat_msg:
                    try: await stat_msg.delete()
                    except: pass
                ongoing.discard(ani_key)
                return

            await rep.report(f"Successfully Compressed {filename}", "info")

            try:
                if stat_msg:
                    await editMessage(stat_msg, f"‣ <b>Anime Name :</b> <b><i>{filename}</i></b>\n\n<i>Uploading {qual}...</i>")
            except Exception:
                pass

            # Upload to Telegram
            try:
                uploaded_msg = await TgUploader(stat_msg).upload(encoded_path, qual)
            except Exception as e:
                await rep.report(f"Error uploading {filename}: {e}", "error")
                if stat_msg:
                    try: await stat_msg.delete()
                    except: pass
                ongoing.discard(ani_key)
                return

            # Build link and button
            me = await bot.get_me()
            tg_username = me.username
            tg_link = f"https://telegram.me/{tg_username}?start={await encode('get-'+str(uploaded_msg.id * abs(Var.FILE_STORE)))}"
            btn_text = f"{btn_formatter.get(str(qual), str(qual))} - {convertBytes(uploaded_msg.document.file_size)}"
            button = InlineKeyboardButton(btn_text, url=tg_link)

            # Merge the new button into the original post (create if missing)
            try:
                # refresh post_msg from cache or API
                cache_key = (str(ani_id), ep_no_str)
                if cache_key in episode_posts:
                    post_msg = episode_posts[cache_key]
                else:
                    try:
                        post_msg = await bot.get_messages(Var.MAIN_CHANNEL, message_ids=post_id)
                        episode_posts[cache_key] = post_msg
                    except Exception:
                        post_msg = None

                if not post_msg:
                    # As last resort create a fresh post (shouldn't happen often)
                    poster = await aniInfo.get_poster()
                    caption = await aniInfo.get_caption()
                    post_msg = await bot.send_photo(Var.MAIN_CHANNEL, photo=poster, caption=caption)
                    post_id = post_msg.id
                    try:
                        await db.saveEpisodePost(ani_id, ep_no_str, post_id)
                    except Exception:
                        pass
                    episode_posts[cache_key] = post_msg

                # read existing keyboard safely
                existing_kb = []
                if getattr(post_msg, "reply_markup", None) and getattr(post_msg.reply_markup, "inline_keyboard", None):
                    existing_kb = post_msg.reply_markup.inline_keyboard or []

                # Prevent duplicate quality button (by quality label or exact text)
                existing_texts = [b.text for row in existing_kb for b in row]
                # Decide uniqueness by presence of quality label (e.g., "1080p" or "720p")
                qual_label = btn_formatter.get(str(qual), str(qual))
                if not any(qual_label in t for t in existing_texts):
                    if existing_kb and len(existing_kb[-1]) == 1:
                        existing_kb[-1].append(button)
                    else:
                        existing_kb.append([button])

                    # edit post with new keyboard
                    await editMessage(post_msg, post_msg.caption.html if getattr(post_msg, "caption", None) else "", InlineKeyboardMarkup(existing_kb))
                else:
                    # Already present: optionally update size text if different
                    # (Skip updating to avoid extra edits; can be added if needed)
                    pass

            except Exception as e:
                await rep.report(f"Failed to edit post buttons for {name}: {e}", "error")

            # Persist DB: mark quality uploaded and ensure episode->post mapping exists
            try:
                await db.saveAnime(ani_id, ep_no_str, qual, post_id)
                await db.saveEpisodePost(ani_id, ep_no_str, post_id)
            except Exception:
                await rep.report(f"Failed to save DB info for {ani_id}:{ep_no_str}", "warning")

            # run extra utilities (backup, samples, etc.)
            bot_loop.create_task(extra_utils(uploaded_msg.id, encoded_path))
            await rep.report(f"Finished {filename} [{qual}] and added button.", "info")

        finally:
            # release lock and cleanup
            try:
                ffLock.release()
            except Exception:
                pass

            try:
                if dl and ospath.exists(dl):
                    await aioremove(dl)
            except Exception:
                pass

            try:
                if stat_msg:
                    await stat_msg.delete()
            except Exception:
                pass

            # remove ongoing key so other qualities or retries can run later
            ongoing.discard(ani_key)

        # mark completed in memory cache
        ani_cache.setdefault("completed", set()).add(str(ani_id))

    except Exception:
        await rep.report(format_exc(), "error")
        # ensure ongoing key removed on unexpected error
        try:
            if ani_key:
                ani_cache.setdefault("ongoing", set()).discard(ani_key)
        except Exception:
            pass


async def extra_utils(msg_id, out_path):
    """
    Called after a successful upload. Copies to backup channels if configured.
    """
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
