# bot/core/rss_torrent_upload.py

import asyncio
from os import path as ospath
from bot import Var, LOGS, ffQueue, ffLock, ff_queued, bot_loop
from bot.core.ffencoder import FFEncoder
from bot.core.func_utils import sendMessage, rep
from bot.core.tordownload import TorDownloader
from bot.core.gdrive_uploader import upload_to_drive
from bot.core.rss_utils import getfeed  # your RSS fetch utility

# ------------------ Queue loop ------------------
async def queue_loop():
    LOGS.info("Queue loop started!")
    while True:
        if not ffQueue.empty():
            post_id = await ffQueue.get()
            await asyncio.sleep(1.5)
            if post_id in ff_queued:
                ff_queued[post_id].set()
            await asyncio.sleep(1.5)
            async with ffLock:
                ffQueue.task_done()
        await asyncio.sleep(5)

# ------------------ RSS Torrent Loop ------------------
async def start_task():
    LOGS.info("RSS Torrent Loop Started!")
    while True:
        try:
            for rss_url in getattr(Var, "RSS_TOR", []):
                feed = await getfeed(rss_url, 0)
                if not feed or not getattr(feed, 'entries', None):
                    await rep.report(f"❌ Invalid/Empty RSS Feed: {rss_url}", "error")
                    continue

                for entry in feed.entries:
                    post_id = id(entry)
                    if post_id in ff_queued:
                        continue
                    ff_queued[post_id] = asyncio.Event()
                    await ffQueue.put(post_id)
                    bot_loop.create_task(process_entry(post_id, entry))

        except Exception as e:
            await rep.report(f"[ERROR] RSS Fetch Error for {rss_url}: {e}", "error")

        await asyncio.sleep(60)  # check every 1 min

# ------------------ Process single entry ------------------
async def process_entry(post_id, entry):
    await ff_queued[post_id].wait()
    ff_queued[post_id].clear()

    try:
        # Get title and link safely
        if isinstance(entry, dict):
            title = entry.get("title") or "Unknown Title"
            link = entry.get("link") or ""
        else:
            # fallback if string
            title = str(entry)
            link = ""

        LOGS.info(f"⬇️ Starting download: {title}")
        await rep.report(f"⬇️ Starting download: {title}", "info")

        # ------------------ Download ------------------
        downloader = TorDownloader(link)
        dl_path = await downloader.download()
        LOGS.info(f"Downloaded: {dl_path}")
        await rep.report(f"✅ Downloaded: {title}", "info")

        # ------------------ Encode ------------------
        encoder = FFEncoder(None, dl_path, ospath.basename(dl_path), Var.QUALS[0])
        bot_msg = await sendMessage(f"Encoding started for {title}")
        encoder.message = bot_msg
        out_path = await encoder.start_encode()
        LOGS.info(f"Encoding complete: {out_path}")

        # ------------------ Upload ------------------
        upload_url = await upload_to_drive(out_path)
        LOGS.info(f"Uploaded to Drive: {upload_url}")
        await sendMessage(f"✅ {title} Uploaded!\n{upload_url}")

    except Exception as e:
        LOGS.error(f"[ERROR] Torrent processing failed for {title}: {e}")
        await rep.report(f"❌ Torrent processing failed for {title}: {e}", "error")
