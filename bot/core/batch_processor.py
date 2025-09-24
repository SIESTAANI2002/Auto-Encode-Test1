import os
import asyncio
from tordownload import TorDownloader
from bot.core.gdrive_uploader import upload_to_drive
from bot.core.ffencoder import FFEncoder
from bot.core.reporter import rep
from bot import LOGS

DOWNLOAD_DIR = "downloads"
PROCESSED_DIR = "processed"
VIDEO_EXTENSIONS = (".mkv", ".mp4", ".avi")
RSS_FEEDS = [
    "https://nyaa.si/?page=rss&q=Ember+batch&c=0_0&f=0"
]

# ---------------- Utility Functions ---------------- #
def rename_video_file(file_path):
    """Rename files using a standard pattern (customize as needed)."""
    dir_name, filename = os.path.split(file_path)
    name, ext = os.path.splitext(filename)
    new_name = name.replace(".", " ").title() + ext
    new_path = os.path.join(dir_name, new_name)
    os.rename(file_path, new_path)
    LOGS.info(f"Renamed {file_path} → {new_path}")
    return new_path

async def fetch_and_download(feed_items, download_dir):
    """Download torrents from feed items using TorDownloader."""
    downloader = TorDownloader(download_dir)
    downloaded_files = []
    for item in feed_items:
        try:
            file_path = await downloader.download(item['torrent_url'])
            if file_path:
                downloaded_files.append(file_path)
                LOGS.info(f"Downloaded: {file_path}")
            else:
                LOGS.error(f"Download failed for {item['torrent_url']}")
        except Exception as e:
            LOGS.error(f"Exception during download: {str(e)}")
            await rep.report(str(e), "error")
    return downloaded_files

async def process_videos(file_paths, quality="720"):
    """Rename, encode, and upload videos."""
    if not os.path.exists(PROCESSED_DIR):
        os.makedirs(PROCESSED_DIR)

    for fpath in file_paths:
        try:
            # 1️⃣ Rename
            new_path = rename_video_file(fpath)

            # 2️⃣ Encode / Metadata Update
            ffencoder = FFEncoder(message=None, path=os.path.dirname(new_path),
                                  name=os.path.basename(new_path), qual=quality)
            final_path = await ffencoder.start_encode()
            if not final_path:
                LOGS.warning(f"Encoding cancelled or failed: {new_path}")
                continue
            LOGS.info(f"Encoding finished: {final_path}")

            # 3️⃣ Move to processed folder
            proc_path = os.path.join(PROCESSED_DIR, os.path.basename(final_path))
            os.rename(final_path, proc_path)
            LOGS.info(f"Moved to processed folder: {proc_path}")

            # 4️⃣ Upload to Google Drive
            drive_link = await upload_to_drive(proc_path)
            LOGS.info(f"Uploaded to Drive: {drive_link}")

        except Exception as e:
            LOGS.error(f"Exception during processing: {str(e)}")
            await rep.report(str(e), "error")

# ---------------- Main Pipeline ---------------- #
async def main():
    for feed in RSS_FEEDS:
        try:
            LOGS.info(f"Fetching and downloading from RSS: {feed}")
            # Dummy feed_items structure, replace with real RSS parser
            feed_items = [{"torrent_url": feed}]  # Replace with actual URLs
            downloaded_files = await fetch_and_download(feed_items, DOWNLOAD_DIR)

            await process_videos(downloaded_files, quality="720")
        except Exception as e:
            LOGS.error(f"Pipeline exception for feed {feed}: {str(e)}")
            await rep.report(str(e), "error")

    LOGS.info("Batch RSS pipeline completed!")

if __name__ == "__main__":
    asyncio.run(main())
