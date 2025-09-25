# bot/core/auto_animes.py
import asyncio
from asyncio import Event
from os import path as ospath
from aiofiles.os import remove as aioremove
from traceback import format_exc

from bot import bot, bot_loop, Var, ani_cache, ffQueue, ffLock, ff_queued
from .tordownload import TorDownloader
from .database import db
from .func_utils import getfeed, encode, editMessage, sendMessage
from .text_utils import TextEditor
from .ffencoder import FFEncoder
from .tguploader import TgUploader
from .tokyo_torrent import generate_torrent
from .tokyo_upload import upload_to_tokyo
from .reporter import rep

async def fetch_animes():
    await rep.report("Fetch Animes Started !!", "info")
    while True:
        await asyncio.sleep(60)
        if ani_cache.get('fetch_animes'):
            for link in Var.RSS_ITEMS:
                if (info := await getfeed(link, 0)):
                    bot_loop.create_task(get_animes(info.title, info.link))

async def get_animes(name, torrent, force=False):
    try:
        aniInfo = TextEditor(name)
        await aniInfo.load_anilist()
        ani_id, ep_no = aniInfo.adata.get('id'), aniInfo.pdata.get("episode_number")

        # Avoid duplicate processing
        if ani_id not in ani_cache.get('ongoing', set()):
            ani_cache.setdefault('ongoing', set()).add(ani_id)
        elif not force:
            return
        if not force and ani_id in ani_cache.get('completed', set()):
            return

        # Check DB if quality already uploaded
        ani_data = await db.getAnime(ani_id)
        qual_data = ani_data.get(ep_no) if ani_data else None
        if not force and qual_data and all(qual_data.get(q) for q in Var.QUALS):
            return

        if "[Batch]" in name:
            await rep.report(f"Torrent Skipped!\n\n{name}", "warning")
            return

        await rep.report(f"New Anime Torrent Found!\n\n{name}", "info")

        # Post photo/caption
        post_msg = await bot.send_photo(
            Var.MAIN_CHANNEL,
            photo=await aniInfo.get_poster(),
            caption=await aniInfo.get_caption()
        )

        await asyncio.sleep(1.5)
        stat_msg = await sendMessage(Var.MAIN_CHANNEL,
            f"‣ <b>Anime Name :</b> <b><i>{name}</i></b>\n\n<i>Downloading...</i>")

        # Download torrent
        dl = await TorDownloader("./downloads").download(torrent, name)
        if not dl or not ospath.exists(dl):
            await rep.report(f"File Download Incomplete, Try Again", "error")
            await stat_msg.delete()
            return

        post_id = post_msg.id
        ffEvent = Event()
        ff_queued[post_id] = ffEvent
        if ffLock.locked():
            await editMessage(stat_msg,
                f"‣ <b>Anime Name :</b> <b><i>{name}</i></b>\n\n<i>Queued to Encode...</i>")
            await rep.report("Added Task to Queue...", "info")
        await ffQueue.put(post_id)
        await ffEvent.wait()

        await ffLock.acquire()

        # Process each quality sequentially
        for qual in Var.QUALS:
            filename = await aniInfo.get_upname(qual)
            await editMessage(stat_msg,
                f"‣ <b>Anime Name :</b> <b><i>{name}</i></b>\n\n<i>Ready to Encode ({qual})...</i>")
            await asyncio.sleep(1.5)
            await rep.report(f"Starting Encode: {qual}...", "info")

            try:
                out_path = await FFEncoder(stat_msg, dl, filename, qual).start_encode()
            except Exception as e:
                await rep.report(f"Error during encode ({qual}): {e}", "error")
                await stat_msg.delete()
                ffLock.release()
                return

            await rep.report(f"Successfully Compressed ({qual}). Uploading to Telegram...", "info")

            try:
                msg = await TgUploader(stat_msg).upload(out_path, qual)
            except Exception as e:
                await rep.report(f"Telegram Upload Failed ({qual}): {e}", "error")
                await stat_msg.delete()
                ffLock.release()
                return

            await rep.report(f"Telegram Upload Completed ({qual}). Generating torrent for TokyoTosho...", "info")

            # Generate torrent & upload to TokyoTosho
            try:
                torrent_file = await generate_torrent(out_path, name)
                response = await upload_to_tokyo(torrent_file, name, Var.TOKYO_API_KEY)
                await rep.report(f"TokyoTosho Upload Response ({qual}): {response}", "info")
            except Exception as e:
                await rep.report(f"TokyoTosho Upload Failed ({qual}): {e}", "error")

            # Save quality info to DB
            await db.saveAnime(ani_id, ep_no, qual, post_id)

        ffLock.release()
        await stat_msg.delete()
        await aioremove(dl)
        ani_cache.setdefault('completed', set()).add(ani_id)

    except Exception:
        await rep.report(format_exc(), "error")
