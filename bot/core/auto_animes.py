from asyncio import gather, create_task, sleep as asleep, Event
from asyncio.subprocess import PIPE
from os import path as ospath, system
from aiofiles import open as aiopen
from aiofiles.os import remove as aioremove
from traceback import format_exc
from base64 import urlsafe_b64encode
from time import time
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
    '720': '𝟳𝟮𝟬𝗽'
}

async def fetch_animes():
    await rep.report("Fetch Animes Started !!", "info")
    while True:
        await asleep(60)
        if ani_cache['fetch_animes']:
            for link in Var.RSS_ITEMS:
                if (info := await getfeed(link, 0)):
                    bot_loop.create_task(get_animes(info.title, info.link))

async def get_animes(name, torrent, force=False):
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

        # Check DB for existing post for this episode
        existing_post_id = await db.getEpisodePost(ani_id, ep_no)
        post_msg = None
        post_id = None
        if existing_post_id:
            try:
                post_msg = await bot.get_messages(Var.MAIN_CHANNEL, message_ids=existing_post_id)
                post_id = existing_post_id
            except Exception:
                post_msg = None
                post_id = None

        # Skip if all qualities already uploaded
        ani_data = await db.getAnime(ani_id) or {}
        ep_info = ani_data.get(ep_no, {})
        if not force and all(ep_info.get(q) for q in Var.QUALS):
            return

        if "[Batch]" in name:
            await rep.report(f"Torrent Skipped!\n{name}", "warning")
            return

        await rep.report(f"New Anime Torrent Found!\n{name}", "info")

        # If no existing post, create new
        if not post_msg:
            poster = await aniInfo.get_poster()
            caption = await aniInfo.get_caption()
            post_msg = await bot.send_photo(Var.MAIN_CHANNEL, photo=poster, caption=caption)
            post_id = post_msg.id
            await db.saveEpisodePost(ani_id, ep_no, post_id)

        stat_msg = await sendMessage(Var.MAIN_CHANNEL, f"‣ <b>Anime Name :</b> <b><i>{name}</i></b>\n\n<i>Downloading...</i>")

        # ✅ Torrent download with retries
        retries = 3
        dl = None
        for attempt in range(1, retries + 1):
            await rep.report(f"📥 Download attempt {attempt} for {name}", "info")
            dl = await TorDownloader("./downloads").download(torrent, name)
            if dl and ospath.exists(dl):
                break
            await rep.report("Download failed, retrying...", "warning")
            await asleep(60)

        if not dl or not ospath.exists(dl):
            await rep.report(f"❌ File Download Incomplete, Skipped {name}", "error")
            await stat_msg.delete()
            return

        ffEvent = Event()
        ff_queued[post_id] = ffEvent
        if ffLock.locked():
            await editMessage(stat_msg, f"‣ <b>Anime Name :</b> <b><i>{name}</i></b>\n\n<i>Queued to Encode...</i>")
            await rep.report("Added Task to Queue...", "info")
        await ffQueue.put(post_id)
        await ffEvent.wait()

        await ffLock.acquire()
        btns = post_msg.reply_markup.inline_keyboard if post_msg.reply_markup else []

        for qual in Var.QUALS:
            if ep_info.get(qual):
                continue  # already uploaded, skip

            filename = await aniInfo.get_upname(qual)
            await editMessage(stat_msg, f"‣ <b>Anime Name :</b> <b><i>{name}</i></b>\n\n<i>Ready to Encode...</i>")
            await asleep(1.5)

            try:
                out_path = await FFEncoder(stat_msg, dl, filename, qual).start_encode()
            except Exception as e:
                await rep.report(f"Error: {e}, Cancelled, Retry Again!", "error")
                await stat_msg.delete()
                ffLock.release()
                return

            await editMessage(stat_msg, f"‣ <b>Anime Name :</b> <b><i>{filename}</i></b>\n\n<i>Ready to Upload...</i>")
            await asleep(1.5)

            try:
                msg = await TgUploader(stat_msg).upload(out_path, qual)
            except Exception as e:
                await rep.report(f"Error: {e}, Cancelled, Retry Again!", "error")
                await stat_msg.delete()
                ffLock.release()
                return

            link = f"https://telegram.me/{(await bot.get_me()).username}?start={await encode('get-'+str(msg.id * abs(Var.FILE_STORE)))}"
            btn = InlineKeyboardButton(f"{btn_formatter.get(qual, qual)} - {convertBytes(msg.document.file_size)}", url=link)

            # Merge buttons correctly
            if btns and len(btns[-1]) == 1:
                btns[-1].append(btn)
            else:
                btns.append([btn])
            await editMessage(post_msg, post_msg.caption.html if post_msg.caption else "", InlineKeyboardMarkup(btns))

            await db.saveAnime(ani_id, ep_no, qual, post_id)
            bot_loop.create_task(extra_utils(msg.id, out_path))

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
            
    # MediaInfo, ScreenShots, Sample Video ( Add-ons Features )
