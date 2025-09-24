import asyncio
from pathlib import Path
from bot.core.func_utils import rename_file
from bot.core.ffencoder import FFEncoder
from bot.core.gdrive_uploader import upload_to_drive
from bot import Var
import feedparser
import aiofiles
import shutil

async def rss_queue_loop():
    """
    Continuously fetch RSS items and process them.
    """
    while True:
        for rss_url in Var.RSS_TOR:
            feed = feedparser.parse(rss_url)
            for entry in feed.entries:
                torrent_url = entry.link
                # Download torrent using your existing downloader
                await download_and_process(torrent_url)
        await asyncio.sleep(3600)  # every 1 hour

async def download_and_process(torrent_url: str):
    """
    1️⃣ Download torrent
    2️⃣ Detect batch folder
    3️⃣ Process videos
    """
    # Replace with your existing torrent downloader
    folder_path = await download_torrent_to_folder(torrent_url)

    # Detect batch / subfolders
    await process_batch(folder_path)

async def process_video(file_path: str):
    """
    Rename -> encode 480p -> upload
    """
    from bot import Var

    # Rename
    renamed_file = rename_file(file_path, brand_tag=Var.SECOND_BRAND)

    # Encode 480p
    encoder = FFEncoder(renamed_file)
    final_file = await encoder.encode_480p(Var.FFCODE_480)

    # Upload
    await upload_to_drive(final_file)

async def process_batch(folder_path: str):
    """
    Recursively process all video files in folder.
    """
    folder = Path(folder_path)
    tasks = []

    for file in folder.rglob("*"):
        if file.suffix.lower() in [".mkv", ".mp4", ".webm"]:
            tasks.append(process_video(str(file)))

    await asyncio.gather(*tasks)

# Placeholder for your torrent download function
async def download_torrent_to_folder(torrent_url: str):
    """
    Download the torrent and return the folder path.
    Replace with your existing download code.
    """
    folder_path = "/tmp/downloaded_torrent"  # temporary path
    # Use your existing downloader here
    return folder_path

async def start_tasks():
    await rss_queue_loop()
