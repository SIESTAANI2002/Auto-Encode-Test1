# bot/core/auto_animes.py
import asyncio
from asyncio import Event, create_task
from os import path as ospath
from aiofiles.os import remove as aioremove
from traceback import format_exc
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot import bot, bot_loop, Var, ani_cache, ffQueue, ffLock, ff_queued
from .database import db                # import DB directly to avoid bot -> db circular issues
from .tordownload import TorDownloader
from .func_utils import getfeed, encode, editMessage, sendMessage, convertBytes
from .text_utils import TextEditor
from .ffencoder import FFEncoder
from .tguploader import TgUploader
from .reporter import rep

# short labels for the post buttons
btn_formatter = {
    '1080': '1080p',
    '720': '720p',
    '480': '480p',
    '360': '360p'
}

# in-memory cache for post message object -> avoids immediate re-fetch
episode_posts = {}  # (ani_id, ep_no) -> Message

# small in-memory set to avoid concurrent duplicate sends per user
_user_sending = set()  # (ani_id, ep_no, qual, user_id)


async def fetch_animes():
    """
    Main fetch loop. Supports Var.RSS_ITEMS as:
      - dict: {"720":"url", "1080":"url"}
      - list/tuple: ["url_for_first_qual", "url_for_second_qual", ...]
    It will schedule get_animes(title, link, qual) tasks.
    """
    await rep.report("Fetch Animes Started !!", "info")
    while True:
        try:
            await asyncio.sleep(60)
            if not ani_cache.get('fetch_animes'):
                continue

            if not Var.RSS_ITEMS:
                await rep.report("No RSS feeds configured (Var.RSS_ITEMS empty).", "warning")
                continue

            # normalize feeds to (qual, feed_url) pairs
            feeds = []
            if isinstance(Var.RSS_ITEMS, dict):
                feeds = list(Var.RSS_ITEMS.items())
            elif isinstance(Var.RSS_ITEMS, (list, tuple)):
                # if list, map to Var.QUALS in order when possible, else mark qual as 'unknown'
                for idx, url in enumerate(Var.RSS_ITEMS):
                    qual = Var.QUALS[idx] if idx < len(Var.QUALS) else f"q{idx}"
                    feeds.append((qual, url))
            else:
                # fallback: single url -> unknown qual
                feeds = [(Var.QUALS[0] if hasattr(Var, "QUALS") and Var.QUALS else "auto", Var.RSS_ITEMS)]

            for qual, feed_link in feeds:
                try:
                    # minimize log spam — you can re-enable if you want more logs:
                    # await rep.report(f"Checking {qual} feed: {feed_link}", "info")
                    entry = await getfeed(feed_link, 0)
                    if entry:
                        # schedule processing
                        bot_loop.create_task(get_animes(entry.title, entry.link, qual))
                except Exception as e:
                    await rep.report(f"Error fetching feed {qual}: {e}", "error")
        except Exception:
            await rep.report(format_exc(), "error")


async def get_animes(name, torrent, qual=None, force=False):
    """
    Process a single RSS entry:
      - resolve Ani metadata
      - skip already uploaded quality (per DB)
      - create or reuse a single post per episode
      - download .torrent, encode (in configured Var.QUALS order), upload to Var.FILE_STORE
      - append inline buttons (short callback_data), storing uploaded message id in ani_cache
    """
    try:
        aniInfo = TextEditor(name)
        await aniInfo.load_anilist()
        ani_id = aniInfo.adata.get('id') or abs(hash(name)) % (10 ** 9)
        ep_no = aniInfo.pdata.get("episode_number")

        # ensure ep_no is a string key for DB consistency
        ep_key = str(ep_no) if ep_no is not None else "0"

        # avoid duplicate processing of same anime concurrently
        if ani_id not in ani_cache.get('ongoing', set()):
            ani_cache.setdefault('ongoing', set()).add(ani_id)
        elif not force:
            return

        # quick db check: if all qualities already present -> skip
        anime_doc = await db.getAnime(ani_id)
        if not force and anime_doc:
            ep_info = anime_doc.get(ep_key) or {}
            # ep_info expected like {'720': True, '1080': True}
            if ep_info and all(ep_info.get(q) for q in getattr(Var, "QUALS", [])):
                return

        # skip batches
        if "[Batch]" in name:
            await rep.report(f"Torrent Skipped (Batch): {name}", "warning")
            return

        await rep.report(f"New Anime Torrent Found!\n{name} from {qual or 'feed'}", "info")

        # create or reuse post for this episode
        post_msg = None
        post_id = None

        try:
            existing_post_id = await db.getEpisodePost(ani_id, ep_key)
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
            episode_posts[(ani_id, ep_key)] = post_msg

        # status message for progress
        stat_msg = await sendMessage(Var.MAIN_CHANNEL, f"‣ <b>Anime Name :</b> <b><i>{name}</i></b>\n\n<i>Downloading...</i>")

        # 1) Download .torrent and the file (with simple retries)
        dl = None
        for attempt in range(3):
            dl = await TorDownloader("./downloads").download(torrent, name)
            if dl and ospath.exists(dl):
                break
            await rep.report(f"File download failed / incomplete. Retry {attempt+1}/3 for {name}", "warning")
            await asyncio.sleep(5)

        if not dl or not ospath.exists(dl):
            await rep.report(f"File Download Incomplete, Try Again: {name}", "error")
            try:
                await stat_msg.delete()
            except Exception:
                pass
            return

        # 2) Put into queue and wait for encoder slot
        post_id_local = post_id
        ffEvent = Event()
        ff_queued[post_id_local] = ffEvent
        if ffLock.locked():
            await editMessage(stat_msg, f"‣ <b>Anime Name :</b> <b><i>{name}</i></b>\n\n<i>Queued to Encode...</i>")
            await rep.report("Added Task to Queue...", "info")
        await ffQueue.put(post_id_local)
        await ffEvent.wait()

        # 3) Acquire encoder lock and run encodes for all Var.QUALS in order
        await ffLock.acquire()
        try:
            # prepare button list to edit post once all qualities have uploaded
            btn_rows = []

            for q in getattr(Var, "QUALS", ["1080", "720"]):
                filename = await aniInfo.get_upname(q)
                await editMessage(stat_msg, f"‣ <b>Anime Name :</b> <b><i>{filename or name}</i></b>\n\n<i>Ready to Encode...</i>")
                await rep.report(f"Starting Encode for quality {q} ...", "info")

                try:
                    encoded_path = await FFEncoder(stat_msg, dl, filename, q).start_encode()
                except Exception as e:
                    await rep.report(f"Error encoding {name} [{q}]: {e}", "error")
                    try:
                        await stat_msg.delete()
                    except Exception:
                        pass
                    return

                await rep.report(f"Successfully Compressed {filename}", "info")
                await editMessage(stat_msg, f"‣ <b>Anime Name :</b> <b><i>{filename}</i></b>\n\n<i>Uploading {q}...</i>")

                # 4) Upload to Var.FILE_STORE via TgUploader
                try:
                    uploaded_msg = await TgUploader(stat_msg).upload(encoded_path, q)
                except Exception as e:
                    await rep.report(f"Error uploading {filename}: {e}", "error")
                    try:
                        await stat_msg.delete()
                    except Exception:
                        pass
                    return

                await rep.report(f"Successfully Uploaded {q} to Tg", "info")

                # Save reference into in-memory cache so callback_data can be small
                cache_key = f"{ani_id}|{ep_key}|{q}"
                ani_cache.setdefault('files', {})[cache_key] = {
                    "msg_id": uploaded_msg.id,
                    "size": getattr(getattr(uploaded_msg, "document", None), "file_size", None)
                             or getattr(getattr(uploaded_msg, "video", None), "file_size", None)
                             or 0,
                }

                # create the button URL link for direct "start" link (your existing scheme)
                me = await bot.get_me()
                try:
                    tg_username = me.username
                except Exception:
                    tg_username = None
                link = None
                if tg_username:
                    try:
                        enc = await encode('get-' + str(uploaded_msg.id * abs(int(Var.FILE_STORE))))
                        link = f"https://telegram.me/{tg_username}?start={enc}"
                    except Exception:
                        link = None

                # create button label and add to btn_rows
                label = f"{btn_formatter.get(q, q)} - {convertBytes(ani_cache[cache_key]['size'])}"
                new_btn = InlineKeyboardButton(label if link is None else label, callback_data=f"s|{ani_id}|{ep_key}|{q}")
                # Note: we use callback_data 's|ani|ep|qual' (keeps it short)

                # append to keyboard in existing style: if last row has 1 button -> add to same row
                if btn_rows and len(btn_rows[-1]) == 1:
                    btn_rows[-1].append(new_btn)
                else:
                    btn_rows.append([new_btn])

                # mark quality in DB
                await db.saveAnime(ani_id, ep_key, q, post_id_local)

                # extra utils (backup, copy etc.)
                create_task(extra_utils(uploaded_msg.id, encoded_path))

            # after all qualities processed, edit post to include built keyboard
            try:
                if (ani_id, ep_key) in episode_posts:
                    post_obj = episode_posts[(ani_id, ep_key)]
                else:
                    post_obj = await bot.get_messages(Var.MAIN_CHANNEL, message_ids=post_id_local)
                await editMessage(post_obj, post_obj.caption.html if post_obj.caption else "", InlineKeyboardMarkup(btn_rows))
            except Exception as e:
                await rep.report(f"Failed to edit post buttons: {e}", "error")

        finally:
            try:
                ffLock.release()
            except Exception:
                pass

        # cleanup download file (original)
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
    """
    Copy uploaded stored file message to backup channels (if configured).
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


# -------------------------
# File-send on callback
# -------------------------
async def handle_file_click(callback_query, ani_id, ep_key, qual):
    """
    Public function so main.py can import handle_file_click().
    Will copy the stored message from Var.FILE_STORE to the user's PM once.
    Subsequent clicks lead to Var.WEBSITE (if provided).
    """
    try:
        user_id = callback_query.from_user.id
        cache_key = f"{ani_id}|{ep_key}|{qual}"

        # short-circuit: ensure we have a cached msg_id
        fileinfo = ani_cache.get('files', {}).get(cache_key)
        if not fileinfo:
            await callback_query.answer("File not ready yet. Try again later.", show_alert=True)
            return

        # prevent concurrent duplicate sends to same user
        sending_key = (ani_id, ep_key, qual, user_id)
        if sending_key in _user_sending:
            await callback_query.answer("Please wait...", show_alert=False)
            return

        # check DB: has user already received this quality?
        try:
            already = await db.hasUserReceived(ani_id, ep_key, qual, user_id)
        except Exception:
            already = False

        if already:
            # direct user to website or show message
            website = getattr(Var, "WEBSITE", None)
            if website:
                # show as URL button response
                try:
                    await callback_query.answer("You already received the file — visit website instead.", url=website)
                except Exception:
                    # fallback: simple alert
                    await callback_query.answer("You already received the file! Visit website.", show_alert=True)
            else:
                await callback_query.answer("You already received the file!", show_alert=True)
            return

        # mark as "sending" to prevent race
        _user_sending.add(sending_key)
        try:
            # copy the uploaded message from FILE_STORE to user
            stored_msg_id = fileinfo.get("msg_id")
            if not stored_msg_id:
                await callback_query.answer("File not available.", show_alert=True)
                return

            # Copy the message (keeps file original metadata)
            try:
                copied = await bot.copy_message(chat_id=user_id, from_chat_id=Var.FILE_STORE, message_id=stored_msg_id)
            except Exception as e:
                await callback_query.answer(f"Failed to send file: {e}", show_alert=True)
                return

            # mark in DB that user received this quality (so second click goes to website)
            try:
                await db.markUserReceived(ani_id, ep_key, qual, user_id)
            except Exception:
                # ignore DB errors but continue
                pass

            # schedule deletion of the sent message after TTL (Var.SEND_TTL, default 600)
            ttl = int(getattr(Var, "SEND_TTL", 600))
            async def _del_after(msg_obj, ttl_s):
                try:
                    await asyncio.sleep(ttl_s)
                    await bot.delete_messages(chat_id=msg_obj.chat.id, message_ids=msg_obj.id)
                except Exception:
                    pass

            create_task(_del_after(copied, ttl))

            await callback_query.answer("File sent to your PM. It will be removed after a short time.", show_alert=True)

        finally:
            _user_sending.discard(sending_key)

    except Exception:
        await rep.report(format_exc(), "error")


# pyrogram callback registration so clicks are handled even if main.py doesn't explicitly call handle_file_click
@bot.on_callback_query()
async def _internal_callback_handler(client, callback_query):
    data = callback_query.data or ""
    # we use short callback prefix 's|' so it's tiny
    if not data.startswith("s|"):
        return
    try:
        # expected form: s|<ani_id>|<ep_key>|<qual>
        parts = data.split("|")
        if len(parts) != 4:
            await callback_query.answer("Invalid button.", show_alert=True)
            return
        _, ani_id_s, ep_key, qual = parts
        # ani_id may be int
        ani_id = int(ani_id_s) if ani_id_s.isdigit() else ani_id_s
        await handle_file_click(callback_query, ani_id, ep_key, qual)
    except Exception:
        await rep.report(format_exc(), "error")
