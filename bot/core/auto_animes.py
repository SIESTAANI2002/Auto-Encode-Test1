from asyncio import sleep as asleep, Event
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


# ===========================
# Fetch anime torrents
# ===========================
async def fetch_animes():
    await rep.report("Fetch Animes Started !!", "info")
    while True:
        await asleep(60)
        if ani_cache["fetch_animes"]:
            for qual, link in Var.RSS_ITEMS.items():
                if (info := await getfeed(link, 0)):
                    bot_loop.create_task(get_animes(info.title, info.link, qual))


# ===========================
# Process single anime
# ===========================
async def get_animes(name, torrent, feed_qual, force=False):
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

        # Check DB
        if force or (
            not (ani_data := await db.getAnime(ani_id))
            or (ani_data and not (qual_data := ani_data.get(ep_no)))
            or (ani_data and qual_data and not qual_data.get(feed_qual))
        ):

            if "[Batch]" in name:
                await rep.report(f"Torrent Skipped!\n\n{name}", "warning")
                return

            await rep.report(f"New Anime Torrent Found!\n\n{name}", "info")

            # If post already exists, reuse it
            post_msg = None
            if ani_data and ep_no in ani_data:
                for q in ani_data[ep_no].values():
                    if isinstance(q, int):
                        try:
                            post_msg = await bot.get_messages(Var.MAIN_CHANNEL, q)
                            break
                        except Exception:
                            pass

            if not post_msg:
                post_msg = await bot.send_photo(
                    Var.MAIN_CHANNEL,
                    photo=await aniInfo.get_poster(),
                    caption=await aniInfo.get_caption(),
                )

            await asleep(1.5)
            stat_msg = await sendMessage(
                Var.MAIN_CHANNEL,
                f"‣ <b>Anime Name :</b> <b><i>{name}</i></b>\n\n<i>Downloading...</i>",
            )

            # Download torrent
            dl = await TorDownloader("./downloads").download(torrent, name)
            if not dl or not ospath.exists(dl):
                await rep.report("File Download Incomplete, Try Again", "error")
                await stat_msg.delete()
                return

            # Queue encode
            post_id = post_msg.id
            ffEvent = Event()
            ff_queued[post_id] = ffEvent
            if ffLock.locked():
                await editMessage(
                    stat_msg,
                    f"‣ <b>Anime Name :</b> <b><i>{name}</i></b>\n\n<i>Queued to Encode...</i>",
                )
                await rep.report("Added Task to Queue...", "info")
            await ffQueue.put(post_id)
            await ffEvent.wait()

            await ffLock.acquire()

            filename = await aniInfo.get_upname(feed_qual)
            await editMessage(
                stat_msg,
                f"‣ <b>Anime Name :</b> <b><i>{name}</i></b>\n\n<i>Ready to Encode...</i>",
            )

            await asleep(1.5)
            await rep.report("Starting Encode...", "info")
            try:
                out_path = await FFEncoder(stat_msg, dl, filename, feed_qual).start_encode()
            except Exception as e:
                await rep.report(f"Error: {e}, Cancelled, Retry Again !", "error")
                await stat_msg.delete()
                ffLock.release()
                return

            await rep.report("Succesfully Compressed Now Going To Upload...", "info")
            await editMessage(
                stat_msg,
                f"‣ <b>Anime Name :</b> <b><i>{filename}</i></b>\n\n<i>Ready to Upload...</i>",
            )

            await asleep(1.5)
            try:
                msg = await TgUploader(stat_msg).upload(out_path, feed_qual)
            except Exception as e:
                await rep.report(f"Error: {e}, Cancelled, Retry Again !", "error")
                await stat_msg.delete()
                ffLock.release()
                return

            await rep.report("Succesfully Uploaded File into Tg...", "info")

            msg_id = msg.id
            link = f"https://telegram.me/{(await bot.get_me()).username}?start={await encode('get-'+str(msg_id * abs(Var.FILE_STORE)))}"

            # Merge buttons (keep old + new quality)
            btns = []
            if post_msg.reply_markup:
                for row in post_msg.reply_markup.inline_keyboard:
                    btns.append([InlineKeyboardButton(b.text, url=b.url) for b in row])

            btns.append(
                [InlineKeyboardButton(f"{btn_formatter[feed_qual]} - {convertBytes(msg.document.file_size)}", url=link)]
            )
            await editMessage(
                post_msg,
                post_msg.caption.html if post_msg.caption else "",
                InlineKeyboardMarkup(btns),
            )

            # Save in DB
            await db.saveAnime(ani_id, ep_no, feed_qual, post_id)

            bot_loop.create_task(extra_utils(msg_id, out_path))

            ffLock.release()
            await stat_msg.delete()
            await aioremove(dl)

        ani_cache["completed"].add(ani_id)
    except Exception:
        await rep.report(format_exc(), "error")


# ===========================
# Extra utils (backup, etc.)
# ===========================
async def extra_utils(msg_id, out_path):
    msg = await bot.get_messages(Var.FILE_STORE, message_ids=msg_id)

    if Var.BACKUP_CHANNEL != 0:
        for chat_id in Var.BACKUP_CHANNEL.split():
            await msg.copy(int(chat_id))

    # TODO: Add MediaInfo, screenshots, samples
