import os
import asyncio
import feedparser
from bot.core.tordownload import TorDownloader
from bot.core.gdrive_uploader import upload_to_drive
from bot.core.ffencoder import FFEncoder
from bot.core.reporter import rep
from bot import LOGS

# ---------------- Config ---------------- #
DOWNLOAD_DIR = "downloads"
PROCESSED_DIR = "processed"
VIDEO_EXTENSIONS = (".mkv", ".mp4", ".avi")
RSS_FEEDS = [
    "https://nyaa.si/?page=rss&q=Ember+batch&c=0_0&f=0"
]
LOG_FILE = "pipeline_logs.txt"

# ---------------- Logging ---------------- #
def write_log(message):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(message + "\n")
    LOGS.info(message)

async def view_logs(n=50):
    if not os.path.exists(LOG_FILE):
        return "No logs found."
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()
    return "".join(lines[-n:])

# ---------------- Utility Functions ---------------- #
def rename_video_file(file_path):
    dir_name, filename = os.path.split(file_path)
    name, ext = os.path.splitext(filename)
    new_name = name.replace(".", " ").title() + ext
    new_path = os.path.join(dir_name, new_name)
    os.rename(file_path, new_path)
    write_log(f"Renamed {file_path} → {new_path}")
    return new_path

async def fetch_and_download(feed_items, download_dir):
    downloader = TorDownloader(download_dir)
    downloaded_files = []
    for item in feed_items:
        try:
            file_path = await downloader.download(item['torrent_url'])
            if file_path:
                downloaded_files.append(file_path)
                write_log(f"Downloaded: {file_path}")
            else:
                write_log(f"Download failed for {item['torrent_url']}")
        except Exception as e:
            write_log(f"Exception during download: {str(e)}")
            await rep.report(str(e), "error")
    return downloaded_files

async def process_videos(file_paths, quality="720"):
    if not os.path.exists(PROCESSED_DIR):
        os.makedirs(PROCESSED_DIR)

    for fpath in file_paths:
        try:
            new_path = rename_video_file(fpath)
            ffencoder = FFEncoder(message=None, path=os.path.dirname(new_path),
                                  name=os.path.basename(new_path), qual=quality)
            final_path = await ffencoder.start_encode()
            if not final_path:
                write_log(f"Encoding cancelled or failed: {new_path}")
                continue
            write_log(f"Encoding finished: {final_path}")

            proc_path = os.path.join(PROCESSED_DIR, os.path.basename(final_path))
            os.rename(final_path, proc_path)
            write_log(f"Moved to processed folder: {proc_path}")

            drive_link = await upload_to_drive(proc_path)
            write_log(f"Uploaded to Drive: {drive_link}")

        except Exception as e:
            write_log(f"Exception during processing: {str(e)}")
            await rep.report(str(e), "error")

# ---------------- RSS Parsing ---------------- #
def parse_rss_feed(url):
    """Parse RSS feed and extract torrent URLs"""
    feed_items = []
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries:
            # Assume torrent URL is in 'link'; adjust if feed uses another field
            torrent_url = entry.link
            feed_items.append({"torrent_url": torrent_url})
    except Exception as e:
        write_log(f"Failed to parse RSS {url}: {str(e)}")
    return feed_items

# ---------------- Main Pipeline ---------------- #
async def main():
    for feed_url in RSS_FEEDS:
        try:
            write_log(f"Fetching RSS feed: {feed_url}")
            feed_items = parse_rss_feed(feed_url)
            if not feed_items:
                write_log(f"No items found in feed: {feed_url}")
                continue

            downloaded_files = await fetch_and_download(feed_items, DOWNLOAD_DIR)
            await process_videos(downloaded_files, quality="720")

        except Exception as e:
            write_log(f"Pipeline exception for feed {feed_url}: {str(e)}")
            await rep.report(str(e), "error")

    write_log("Batch RSS pipeline completed!")

# ---------------- Entry Point for Bot Integration ---------------- #
async def start_pipeline():
    """Call this from main.py to auto-run the pipeline"""
    await main()
