# bot/core/rss_torrent_upload.py
import asyncio
import re
from os import path as ospath
from aiofiles import open as aiopen
from bot import Var, bot_loop, ffQueue, ffLock, ff_queued, ani_cache, LOGS
from bot.core.database import db
from bot.core.tordownload import TorDownloader
from bot.core.ffencoder import FFEncoder
from bot.core.gdrive_uploader import upload_to_drive
from bot.core.func_utils import getfeed, editMessage
from bot.core.reporter import rep

tor_downloader = TorDownloader("./downloads")

# ----------------- Queue Task -----------------
async def start_task():
    await rep.report("RSS Torrent Loop Started!", "info")
    while True:
        try:
            for rss_link in getattr(Var, "RSS_TOR", Var.RSS_ITEMS):
                feed = await getfeed(rss_link, 0)
                if feed:
                    for entry in feed.entries:
                        post_id = (id(entry), entry)
                        if post_id in ani_cache.get("completed", set()):
                            continue
                        ffQueue.put_nowait(post_id)
                        ff_queued[post_id] = asyncio.Event()
                        LOGS.info(f"Queued: {entry.title}")
            await asyncio.sleep(300)  # Fetch RSS every 5 minutes
        except Exception as e:
            await rep.report(f"RSS Fetch Error: {e}", "error")
            await asyncio.sleep(60)

# ----------------- Process Queue -----------------
async def queue_loop():
    LOGS.info("Queue loop started!")
    while True:
        if not ffQueue.empty():
            post_id = await ffQueue.get()
            event = ff_queued.get(post_id)
            if not event:
                ffQueue.task_done()
                continue
            entry = post_id[1]
            try:
                await process_entry(entry)
            except Exception as e:
                await rep.report(f"Error processing {entry.title}: {e}", "error")
            finally:
                ffQueue.task_done()
                if event:
                    event.set()
                ff_queued.pop(post_id, None)
        await asyncio.sleep(5)

# ----------------- Process Single Torrent -----------------
async def process_entry(entry):
    title = entry.title
    tor_url = entry.link
    await rep.report(f"🔗 Found Torrent: {title}", "info")
    LOGS.info(f"Starting download: {title}")

    # Download torrent
    downloaded_file = await tor_downloader.download(tor_url)
    if not downloaded_file:
        await rep.report(f"❌ Torrent download failed: {title}", "error")
        return

    # Rename file
    new_name = re.sub(r"^\[.*?\]\s*", f"[{Var.SECOND_BRAND}] ", ospath.basename(downloaded_file))
    new_path = ospath.join("downloads", new_name)
    if downloaded_file != new_path:
        import shutil
        shutil.move(downloaded_file, new_path)
    await rep.report(f"✅ Download complete: {new_name}", "info")

    # Encode metadata (no re-encode video if not needed)
    ffenc = FFEncoder(None, new_path, new_name, "720")
    encoded_file = await ffenc.start_encode()
    if not encoded_file:
        encoded_file = new_path

    # Upload to Drive
    await rep.report(f"⬆️ Uploading: {new_name}", "info")
    try:
        drive_link = await upload_to_drive(encoded_file)
        await rep.report(f"✅ Uploaded: {new_name}\n{drive_link}", "info")
    except Exception as e:
        await rep.report(f"❌ Upload failed: {new_name} | {e}", "error")
        return

    # Save to DB
    await db.saveAnime(title, "01", "720")  # you can adjust ep/qual logic
    ani_cache.setdefault("completed", set()).add(title)
