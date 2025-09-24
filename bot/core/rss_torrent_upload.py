import os
import asyncio
import feedparser
from bot import Var, LOGS, bot_loop, ffQueue, ffLock
from bot.core.tordownload import TorDownloader
from bot.core.ffencoder import FFEncoder
from bot.core.gdrive_uploader import upload_to_drive
from bot.core.reporter import rep

# ---------------- Polling download progress ---------------- #
async def track_download_progress(file_path, msg_id):
    prev_size = 0
    while not os.path.exists(file_path):
        await asyncio.sleep(2)  # wait for file to appear

    while True:
        if not os.path.exists(file_path):
            break
        curr_size = os.path.getsize(file_path)
        speed = (curr_size - prev_size) / 10  # bytes per 10s
        prev_size = curr_size

        mb_done = curr_size / (1024*1024)
        mb_speed = speed / (1024*1024)
        await rep.update_report(
            msg_id,
            f"⬇️ Downloading: {mb_done:.2f}MB | Speed: {mb_speed:.2f}MB/s"
        )
        await asyncio.sleep(10)

# ---------------- Process one torrent ---------------- #
async def process_torrent(entry):
    title = entry.title
    msg_id = await rep.report(f"⬇️ Starting download: {title}", "info")

    tor = TorDownloader()
    # Start download in background
    dl_task = asyncio.create_task(tor.download(entry.link, title))

    # Track progress using polling
    # We assume file will appear in "downloads/" with a .mkv extension (you can adjust)
    file_name_guess = f"{title}.mkv"
    file_path = os.path.join("downloads", file_name_guess)
    progress_task = asyncio.create_task(track_download_progress(file_path, msg_id))

    dl_path = await dl_task
    await progress_task

    if not dl_path:
        err = f"❌ Torrent download failed: {title}"
        LOGS.error(err)
        await rep.report(err, "error")
        return

    # ---------------- Rename & Encode ---------------- #
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
                    await ffQueue.put((id(entry), entry))  # add to queue

        except Exception as e:
            err = f"⚠️ Error in RSS Torrent Loop: {str(e)}"
            LOGS.error(err)
            await rep.report(err, "error")

        await asyncio.sleep(60)  # check feed every 60s
