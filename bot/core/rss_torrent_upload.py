import asyncio
import feedparser
import os
from bot import Var, LOGS, bot_loop, ffQueue, ffLock
from bot.core.tordownload import TorDownloader
from bot.core.gdrive_uploader import upload_to_drive
from bot.core.ffencoder import FFEncoder
from bot.core.reporter import rep

# ---------------- Progress callback ---------------- #
async def progress_cb(info, msg_id, title):
    pct = round(info["done"]*100, 2)
    speed_mb = info["speed"]/1024/1024
    eta_sec = int((info["downloaded"]/max(info["speed"],1)))
    text = f"⬇️ Downloading {title}: {pct}% | {speed_mb:.2f}MB/s | ETA {eta_sec}s"
    await rep.update_report(msg_id, text)

# ---------------- Process one torrent ---------------- #
async def process_torrent(entry):
    title = entry.title
    msg_id = await rep.report(f"⬇️ Starting download: {title}", "info")

    tor = TorDownloader()
    dl_path = await tor.download(
        entry.link,
        title,
        progress_callback=lambda info: progress_cb(info, msg_id, title)
    )

    if not dl_path:
        err = f"❌ Torrent download failed: {title}"
        LOGS.error(err)
        await rep.report(err, "error")
        return

    # ---------------- Rename & metadata ---------------- #
    new_name = f"[{Var.SECOND_BRAND}] {title} Dual Audio.mkv"
    new_path = os.path.join("downloads", new_name)

    ff = FFEncoder(message=msg_id, path=dl_path, name=new_name, qual=Var.QUALS[0])
    encoded_path = await ff.start_encode() or dl_path
    os.rename(encoded_path, new_path)

    await rep.update_report(msg_id, f"📂 Renamed to: {new_name}")

    # ---------------- Upload ---------------- #
    upload_msg_id = await rep.report(f"☁️ Uploading: {new_name}", "info")
    upload_task = asyncio.create_task(upload_to_drive(new_path))

    while not upload_task.done():
        await rep.update_report(upload_msg_id, f"☁️ Uploading {new_name} …")
        await asyncio.sleep(10)

    gdrive_link = await upload_task
    await rep.update_report(upload_msg_id, f"✅ Uploaded: {gdrive_link}")

    # ---------------- Cleanup ---------------- #
    if Var.AUTO_DEL:
        os.remove(new_path)
        await rep.report(f"🗑️ Deleted local file: {new_name}", "info")

# ---------------- Queue worker ---------------- #
async def queue_worker():
    while True:
        post_id, entry = await ffQueue.get()
        async with ffLock:
            await process_torrent(entry)
            ffQueue.task_done()
        await asyncio.sleep(1)

# ---------------- RSS fetch loop ---------------- #
async def start_task():
    LOGS.info("🚀 RSS Torrent Task Started!")
    await rep.report("🚀 RSS Torrent Task Started!", "info")

    # Start queue worker
    bot_loop.create_task(queue_worker())

    while True:
        try:
            for rss_url in Var.RSS_TOR:
                LOGS.info(f"📡 Checking RSS Feed: {rss_url}")
                await rep.report(f"📡 Checking RSS Feed: {rss_url}", "info")

                feed = feedparser.parse(rss_url)
                entries = feed.entries[:3]  # latest 3 torrents

                for entry in entries:
                    # Add torrent to queue
                    await ffQueue.put((id(entry), entry))

        except Exception as e:
            err = f"⚠️ Error in RSS Torrent Loop: {str(e)}"
            LOGS.error(err)
            await rep.report(err, "error")

        await asyncio.sleep(60)  # check feed every 60s
