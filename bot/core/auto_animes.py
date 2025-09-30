# bot/core/auto_animes.py
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

# Keep labels short and stable
btn_formatter = {
    '1080': '1080p',
    '480': '480p',
    # Add other qualities if needed
}

# Cache mapping (ani_id|ep|qual) -> metadata (size, file_msg_id) to avoid races
# keys like "12345|12|1080"
ani_cache_local = {}

# ------------------------------------------------------------------
# Fetching loop that checks RSS feeds and schedules processing
# ------------------------------------------------------------------
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

            # Var.RSS_ITEMS can be dict or list — support both
            if isinstance(Var.RSS_ITEMS, dict):
                feed_iter = Var.RSS_ITEMS.items()
            else:
                # assume list of urls -> treat them as generic feed (qual will be None)
                feed_iter = ((None, url) for url in Var.RSS_ITEMS)

            for qual, feed_link in feed_iter:
                try:
                    # optional log (commented if you don't want frequent logs)
                    # await rep.report(f"Checking {qual or 'feed'}: {feed_link}", "info")
                    entry = await getfeed(feed_link, 0)
                    if entry:
                        # schedule get_animes with quality hint (qual may be None)
                        bot_loop.create_task(get_animes(entry.title, entry.link, qual))
                except Exception as e:
                    await rep.report(f"Error fetching feed {feed_link}: {e}", "error")
        except Exception:
            await rep.report(format_exc(), "error")

# ------------------------------------------------------------------
# Main single-entry processor
# ------------------------------------------------------------------
async def get_animes(name, torrent, qual_hint=None, force=False):
    """
    name: feed item's title
    torrent: feed link (torrent file or magnet)
    qual_hint: optional string '720' or '1080' if feed is quality-specific
    """
    try:
        aniInfo = TextEditor(name)
        await aniInfo.load_anilist()
        ani_id = aniInfo.adata.get('id')
        ep_no = aniInfo.pdata.get("episode_number")

        # fallback numeric hashed id
        if not ani_id:
            ani_id = abs(hash(name)) % (10 ** 9)

        # avoid duplicate runs per anime id
        if ani_id not in ani_cache.get('ongoing', set()):
            ani_cache.setdefault('ongoing', set()).add(ani_id)
        elif not force:
            return

        if not force and ani_id in ani_cache.get('completed', set()):
            return

        # check DB whether all qualities already present for this episode
        anime_doc = await db.getAnime(ani_id)
        ep_doc = {}
        if anime_doc:
            # some DBs store episodes under "episodes" or top-level digit keys; handle both
            ep_doc = anime_doc.get("episodes", {}).get(str(ep_no), {}) or anime_doc.get(str(ep_no), {}) or {}

        # If episode exists and all Var.QUALS present -> skip
        if not force and ep_doc:
            qual_flags = ep_doc.get("qualities") or {q: ep_doc.get(q) for q in Var.QUALS if q in ep_doc}
            if qual_flags and all(qual_flags.get(q) for q in Var.QUALS):
                return

        if "[Batch]" in name:
            await rep.report(f"Torrent Skipped (Batch): {name}", "warning")
            return

        await rep.report(f"New Anime Torrent Found!\n{name} from {qual_hint or 'feed'}", "info")

        # Create channel post (poster + caption)
        try:
            poster = await aniInfo.get_poster()
        except Exception:
            poster = None
        caption = await aniInfo.get_caption()
        post_msg = await bot.send_photo(Var.MAIN_CHANNEL, photo=poster, caption=caption)
        post_id = post_msg.id

        # Status message for progress (temporary)
        stat_msg = await sendMessage(Var.MAIN_CHANNEL, f"‣ <b>Anime Name :</b> <b><i>{name}</i></b>\n\n<i>Downloading...</i>")

        # 1) Download .torrent (or magnet)
        dl = await TorDownloader("./downloads").download(torrent, name)
        if not dl or not ospath.exists(dl):
            await rep.report(f"File Download Incomplete, Try Again: {name}", "error")
            try:
                await stat_msg.delete()
            except Exception:
                pass
            return

        await editMessage(stat_msg, f"‣ <b>Anime Name :</b> <b><i>{name}</i></b>\n\n<i>Ready to Encode...</i>")
        await rep.report(f"Queued for encode: {name} [{qual_hint or 'auto'}]", "info")

        # Put this post into queue mechanism your main thread uses
        ffEvent = Event()
        ff_queued[post_id] = ffEvent
        if ffLock.locked():
            await editMessage(stat_msg, f"‣ <b>Anime Name :</b> <b><i>{name}</i></b>\n\n<i>Queued to Encode...</i>")
        await ffQueue.put(post_id)
        await ffEvent.wait()

        # Acquire global encoder lock
        await ffLock.acquire()
        try:
            # We'll collect buttons state here; build keyboard from the collected file_msg_ids
            keyboard_rows = []

            # iterate in configured order
            for qual in Var.QUALS:
                # If feed itself strongly hinted qual and it doesn't match, allow encoding anyway.
                # get final upload name
                filename = await aniInfo.get_upname(qual)
                out_path = f"./encode/{filename}" if filename else None

                await editMessage(stat_msg, f"‣ <b>Anime Name :</b> <b><i>{filename or name}</i></b>\n\n<i>Encoding Started ({qual})...</i>")
                try:
                    encoded_path = await FFEncoder(stat_msg, dl, filename, qual).start_encode()
                except Exception as e:
                    await rep.report(f"Error encoding {name} [{qual}]: {e}", "error")
                    try:
                        await stat_msg.delete()
                    except Exception:
                        pass
                    return

                await rep.report(f"Successfully Compressed {filename}", "info")
                await editMessage(stat_msg, f"‣ <b>Anime Name :</b> <b><i>{filename}</i></b>\n\n<i>Uploading {qual}...</i>")

                # Upload to Telegram FILE_STORE (this returns the message object)
                try:
                    uploaded_msg = await TgUploader(stat_msg).upload(encoded_path, qual)
                except Exception as e:
                    await rep.report(f"Error uploading {filename}: {e}", "error")
                    try:
                        await stat_msg.delete()
                    except Exception:
                        pass
                    return

                await rep.report(f"Successfully Uploaded {qual} File to Tg...", "info")

                # Save file message id into DB under episodes -> qualities -> qual: {file_msg_id:..., size:...}
                file_msg_id = uploaded_msg.id
                size_bytes = getattr(uploaded_msg.document, "file_size", None) or getattr(uploaded_msg.video, "file_size", None) or 0

                # Database: try to save per-episode, per-quality metadata
                # Expectation: db.saveAnime should accept file_msg_id and post_id (adapt your DB accordingly)
                try:
                    # Newer DB save: (ani_id, ep_no, qual, post_id=None, file_msg_id=None, size=None)
                    # If your DB doesn't support the extra args, update database.py accordingly.
                    await db.saveAnime(ani_id, ep_no, qual, post_id=post_id, file_msg_id=file_msg_id, size=size_bytes)
                except TypeError:
                    # fallback to older signature: save qual flag + store global msg_id (post id)
                    await db.saveAnime(ani_id, ep_no, qual, post_id=post_id)
                    # store file msg id under anime doc directly if possible (best-effort)
                    try:
                        await db.__animes.update_one(
                            {'_id': ani_id},
                            {'$set': {f"episodes.{ep_no}.qualities.{qual}.file_msg_id": file_msg_id,
                                      f"episodes.{ep_no}.qualities.{qual}.size": size_bytes}},
                            upsert=True
                        )
                    except Exception:
                        pass

                # build short callback_data that fits telegram limits:
                # format: "s|ani_id|ep_no|qual|file_msg_id"
                # all numeric/short -> stays small
                cb = f"s|{ani_id}|{ep_no}|{qual}|{file_msg_id}"

                # For button label show quality and human size
                label = f"{btn_formatter.get(qual, qual)} - {convertBytes(size_bytes)}"
                keyboard_rows.append([InlineKeyboardButton(label, callback_data=cb)])

                # schedule any extras (backup copy etc.)
                bot_loop.create_task(extra_utils(file_msg_id, encoded_path))

            # At the end, edit the post to include the inline keyboard (all constructed)
            try:
                if keyboard_rows:
                    await editMessage(post_msg, post_msg.caption.html if post_msg.caption else "", InlineKeyboardMarkup(keyboard_rows))
            except Exception as e:
                await rep.report(f"Failed to edit post buttons: {e}", "error")

        finally:
            # release lock always
            try:
                ffLock.release()
            except Exception:
                pass

            # delete temp download file (original torrent/file) to save space
            try:
                await aioremove(dl)
            except Exception:
                pass

            try:
                await stat_msg.delete()
            except Exception:
                pass

        # mark completed in memory cache
        ani_cache.setdefault('completed', set()).add(ani_id)

    except Exception:
        await rep.report(format_exc(), "error")

# ------------------------------------------------------------------
# Callback handler for inline button clicks
# ------------------------------------------------------------------
async def handle_file_click(client, callback_query):
    """
    Expected callback_data format:
        "s|{ani_id}|{ep_no}|{qual}|{file_msg_id}"
    Behavior:
      - If user has NOT received that file before -> bot sends the file to user's PM, marks DB,
        starts a timer to delete bot-delivered file after Var.SEND_EXPIRE seconds.
      - If user already received -> reply callback with website link (Var.WEBSITE).
    """
    try:
        data = callback_query.data or ""
        user = callback_query.from_user
        user_id = user.id if user else None

        if not data.startswith("s|"):
            await callback_query.answer("Invalid request.", show_alert=True)
            return

        parts = data.split("|")
        if len(parts) != 5:
            await callback_query.answer("Invalid data.", show_alert=True)
            return

        _, ani_id_s, ep_s, qual, file_msg_id_s = parts
        try:
            ani_id = int(ani_id_s)
            ep_no = str(int(ep_s))  # keep string key for DB
            file_msg_id = int(file_msg_id_s)
        except Exception:
            await callback_query.answer("Invalid ids.", show_alert=True)
            return

        # Check DB whether this user already got the file for this (ani, ep, qual)
        try:
            already = await db.hasUserReceived(ani_id, ep_no, qual, user_id)
        except Exception:
            # if DB method missing, fallback to in-memory map (not persistent)
            already = False

        if already:
            # second click -> send website link (if present)
            url = getattr(Var, "WEBSITE", None)
            if url:
                # callback answer with url (Telegram expects valid url)
                try:
                    await callback_query.answer("You already received the file — visit website instead.", url=url)
                except Exception:
                    # fallback to simple alert
                    await callback_query.answer("You already received the file — visit website instead.", show_alert=True)
            else:
                await callback_query.answer("You already received the file.", show_alert=True)
            return

        # Not received yet -> send file to user's PM
        try:
            # fetch the file message from FILE_STORE to copy/send it to user
            # we use get_messages to fetch the message object and then copy to user to preserve file ID
            file_msg = await bot.get_messages(Var.FILE_STORE, message_ids=file_msg_id)
            if not file_msg:
                await callback_query.answer("File temporarily unavailable.", show_alert=True)
                return

            # send by copy (preserves file, faster)
            await callback_query.answer("Preparing file...", show_alert=False)

            # copy (preferred) rather than re-uploading
            sent = await file_msg.copy(user_id)
            # mark DB: user received
            try:
                await db.markUserReceived(ani_id, ep_no, qual, user_id)
            except Exception:
                # silent fail if DB doesn't support it
                pass

            # Tell user
            try:
                await bot.send_message(user_id, f"✅ Sent: {file_msg.document.file_name if getattr(file_msg, 'document', None) else 'file'}\nThis link will be available for {getattr(Var, 'SEND_EXPIRE', 3600)} seconds.")
            except Exception:
                pass

            # schedule deletion of message after SEND_EXPIRE seconds (if configured)
            expire = getattr(Var, "SEND_EXPIRE", 600)  # default 600s = 10min
            if expire and expire > 0:
                async def _del_after(u_id, m_id, ttl):
                    await asyncio.sleep(ttl)
                    try:
                        await bot.delete_messages(chat_id=u_id, message_ids=m_id)
                    except Exception:
                        pass
                # run background cleanup
                bot_loop.create_task(_del_after(user_id, sent.id, expire))
        except Exception as e:
            await callback_query.answer("Failed to send file.", show_alert=True)
            await rep.report(f"Error sending file to user {user_id}: {e}", "error")

    except Exception:
        await rep.report(format_exc(), "error")

# A Pyrogram handler wrapper -- import this function in your __main__ and register:
# from bot.core.auto_animes import handle_file_click
# @bot.on_callback_query()
# async def inline_button_handler(client, callback_query):
#     await handle_file_click(client, callback_query)

# ------------------------------------------------------------------
# Extra utils (backup copying, etc.)
# ------------------------------------------------------------------
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
