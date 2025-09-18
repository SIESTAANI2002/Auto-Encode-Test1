from asyncio import gather, create_task, sleep as asleep, Event
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

btn_formatter = {
    "1080": "1080p",
    "720": "𝟳𝟮𝟬𝗽"
}

async def fetch_animes():
    await rep.report("[Fetcher] Started fetching RSS feeds...", "info")
    while True:
        await asleep(60)
        if ani_cache["fetch_animes"]:
            for qual, link in Var.RSS_ITEMS.items():
                if (info := await getfeed(link, 0)):
                    bot_loop.create_task(get_animes(info.title, info.link, qual))

async def get_animes(name, torrent, qual, force=False):
    try:
        aniInfo = TextEditor(name)
        await aniInfo.load_anilist()
        ani_id, ep_no = aniInfo.adata.get("id"), aniInfo.pdata.get("episode_number")

        if ani_id not in ani_cache["ongoing"]:
            ani_cache["ongoing"].add(ani_id)
        elif not force:
            return

        if not force and ani_id in ani_cache["completed"]:
            return

        if force or (not (ani_data := await db.getAnime(ani_id)) \
            or (ani_data and not (qual_data := ani_data.get(ep_no))) \
            or (ani_data and qual_data and not qual_data.get(qual))):

            if "[Batch]" in name:
                await rep.report(f"[Skip] Batch torrent skipped: {name}", "warning")
                return

            await rep.report(f"[New] Anime Found!\n\n{name}", "info")

            # Check if post already exists for this anime episode
            ani_data = await db.getAnime(ani_id)
            post_msg = None
            if ani_data and ep_no in ani_data:
                # existing message
                post_id = list(ani_data[ep_no].values())[0]
                post_msg = await bot.get_messages(Var.MAIN_CHANNEL, post_id)
                await rep.report(f"[Merge] Adding new quality ({qual}) to existing post", "info")
            else:
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
                await rep.report(f"[Error] File Download Incomplete, Try Again", "error")
                await stat_msg.delete()
                return

            post_id = post_msg.id
            ffEvent = Event()
            ff_queued[post_id] = ffEvent
            if ffLock.locked():
                await editMessage(stat_msg, f"‣ <b>Anime Name :</b> <b><i>{name}</i></b>\n\n<i>Queued to Encode...</i>")
                await rep.report("[Queue] Task Queued...", "info")
            await ffQueue.put(post_id)
            await ffEvent.wait()

            await ffLock.acquire()
            filename = await aniInfo.get_upname(qual)
            await editMessage(stat_msg, f"‣ <b>Anime Name :</b> <b><i>{name}</i></b>\n\n<i>Ready to Encode...</i>")

            try:
                out_path = await FFEncoder(stat_msg, dl, filename, qual).start_encode()
                await rep.report(f"[Encode] Success for {filename}", "info")
            except Exception as e:
                await rep.report(f"[Encode Error] {e}", "error")
                await stat_msg.delete()
                ffLock.release()
                return

            await editMessage(stat_msg, f"‣ <b>Anime Name :</b> <b><i>{filename}</i></b>\n\n<i>Ready to Upload...</i>")

            try:
                msg = await TgUploader(stat_msg).upload(out_path, qual)
                await rep.report(f"[Upload] Uploaded {filename}", "info")
            except Exception as e:
                await rep.report(f"[Upload Error] {e}", "error")
                await stat_msg.delete()
                ffLock.release()
                return

            msg_id = msg.id
            link = f"https://telegram.me/{(await bot.get_me()).username}?start={await encode('get-'+str(msg_id * abs(Var.FILE_STORE)))}"

            # Add button for quality
            btns = []
            if post_msg.reply_markup:
                btns = list(post_msg.reply_markup.inline_keyboard)

            btns.append([
                InlineKeyboardButton(f"{btn_formatter[qual]} - {convertBytes(msg.document.file_size)}", url=link)
            ])
            await editMessage(post_msg, post_msg.caption.html if post_msg.caption else "", InlineKeyboardMarkup(btns))

            await db.saveAnime(ani_id, ep_no, qual, post_id)

            ffLock.release()
            await stat_msg.delete()
            await aioremove(dl)

        ani_cache["completed"].add(ani_id)

    except Exception:
        await rep.report(format_exc(), "error")
