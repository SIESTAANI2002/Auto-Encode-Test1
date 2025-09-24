import asyncio
import os
from pathlib import Path
from bot import Var, LOGS
from bot.core.ffencoder import FFEncoder
from bot.core.gdrive_uploader import upload_file
from bot.core.func_utils import change_metadata, rename_file
import feedparser
import aiofiles

# -------------------- Configuration -------------------- #
RSS_FEEDS = Var.RSS_TOR  # Your RSS feed list
SECOND_BRAND = Var.SECOND_BRAND  # The rename tag
FFCODE_480 = Var.FFCODE_480  # 480p encode flag if needed
PROCESS_DELAY = 5  # seconds between processing

# -------------------- Queue -------------------- #
rss_queue = asyncio.Queue()


# -------------------- RSS Parsing -------------------- #
async def fetch_animes():
    for feed_url in RSS_FEEDS:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries:
            await rss_queue.put(entry)
            LOGS.info(f"Added to queue: {entry.title}")


# -------------------- Core Processing -------------------- #
async def process_entry(entry):
    try:
        # Assume entry.link is torrent/magnet link
        # Download folder for batch support
        download_path = Path("downloads") / entry.title
        download_path.mkdir(parents=True, exist_ok=True)

        # --- Download torrent --- #
        # Here you would call your existing TorDownloader or equivalent
        # For example: await TorDownloader(entry.link, download_path).start()

        # --- Process all video files in folder recursively --- #
        for video_file in download_path.rglob("*.*"):
            if video_file.suffix.lower() not in [".mkv", ".mp4", ".avi"]:
                continue

            # --- Rename --- #
            new_name = rename_file(video_file.name, old_tag="Abe", new_tag=SECOND_BRAND)
            new_path = video_file.with_name(new_name)
            video_file.rename(new_path)

            # --- Change metadata --- #
            await change_metadata(new_path)

            # --- Optional: 480p encode --- #
            if FFCODE_480:
                ff = FFEncoder(str(new_path), target="480p")
                await ff.encode()

            # --- Upload to Drive --- #
            await upload_file(str(new_path), folder_id=Var.GDRIVE_FOLDER_ID)

        LOGS.info(f"Processed: {entry.title}")

    except Exception as e:
        LOGS.error(f"Error processing {entry.title}: {e}")


# -------------------- Queue Loop -------------------- #
async def rss_queue_loop():
    while True:
        entry = await rss_queue.get()
        await process_entry(entry)
        await asyncio.sleep(PROCESS_DELAY)


# -------------------- Start Task -------------------- #
async def start_tasks():
    await fetch_animes()
    await rss_queue_loop()


# -------------------- If needed to start manually -------------------- #
if __name__ == "__main__":
    asyncio.run(start_tasks())
