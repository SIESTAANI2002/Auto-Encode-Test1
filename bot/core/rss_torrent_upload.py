# bot/core/rss_torrent_upload.py

import asyncio
from bot import ffQueue, ffLock, ff_queued, bot_loop, LOGS, ani_cache, Var
from bot.core.func_utils import getfeed, sendMessage
from bot.core.reporter import rep
from bot.core.tordownload import TorDownloader
from bot.core.ffencoder import FFEncoder
from os import path as ospath

# ------------------ Queue Loop ------------------
async def queue_loop():
    LOGS.info("Queue loop started!")
    while True:
        if not ffQueue.empty():
            post_id = await ffQueue.get()
            if post_id not in ff_queued:
                ff_queued[post_id] = asyncio.Event()

            ff_queued[post_id].set()  # trigger download/encode
            await asyncio.sleep(1)
            async with ffLock:
                ffQueue.task_done()
        await asyncio.sleep(10)

# ------------------ Start RSS Torrent Task ------------------
async def start_task():
    LOGS.info("RSS Torrent Loop Started!")
    while True:
        for url in getattr(Var, "RSS_ITEMS", []):
            try:
                feed_entries = await getfeed(url)
                if not feed_entries:
                    LOGS.error(f"❌ Invalid/Empty RSS Feed: {url}")
                    continue

                for entry in feed_entries:
                    post_id = (id(entry), entry)
                    if post_id not in ff_queued:
                        ff_queued[post_id] = asyncio.Event()
                        await ffQueue.put(post_id)
                        LOGS.info(f"🔗 Found Torrent: {entry.title}")
                        # Start processing in background
                        bot_loop.create_task(process_entry(post_id, entry))

            except Exception as e:
                LOGS.error(f"[ERROR] RSS Fetch Error for {url}: {e}")
        await asyncio.sleep(300)  # check every 5 minutes

# ------------------ Download → Encode → Upload ------------------
async def process_entry(post_id, entry):
    await ff_queued[post_id].wait()  # wait for queue trigger
    ff_queued[post_id].clear()

    try:
        # ------------------ Download ------------------
        LOGS.info(f"⬇️ Starting download: {entry.title}")
        downloader = TorDownloader(entry.link)
        dl_path = await downloader.download()  # must return local path

        LOGS.info(f"Downloaded: {dl_path}")

        # ------------------ Encode ------------------
        encoder = FFEncoder(None, dl_path, ospath.basename(dl_path), Var.QUALS[0])
        bot_message = await sendMessage(f"Encoding started for {entry.title}")  # optional Telegram msg
        encoder.message = bot_message
        out_path = await encoder.start_encode()
        LOGS.info(f"Encoding complete: {out_path}")

        # ------------------ Upload ------------------
        from bot.core.gdrive_uploader import upload_to_drive
        upload_url = await upload_to_drive(out_path)
        LOGS.info(f"Uploaded to Drive: {upload_url}")
        await sendMessage(f"✅ {entry.title} Uploaded!\n{upload_url}")

    except Exception as e:
        LOGS.error(f"[ERROR] Torrent processing failed for {entry.title}: {e}")
        await rep.report(f"❌ Torrent processing failed for {entry.title}: {e}", "error")
