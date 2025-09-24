import os
import asyncio
import feedparser
from bot.core.tordownload import TorDownloader
from bot.core.gdrive_uploader import upload_to_drive
from bot.core.ffencoder import FFEncoder
from bot.core.reporter import rep
from bot import LOGS
from bot.core.func_utils import editMessage

# ---------------- Config ---------------- #
DOWNLOAD_DIR = "downloads"
PROCESSED_DIR = "processed"
VIDEO_EXTENSIONS = (".mkv", ".mp4", ".avi")
UPDATE_INTERVAL = 10  # Telegram message update interval in seconds

# Get Telegram IDs from config.env
MAIN_CHANNEL = int(os.environ.get("MAIN_CHANNEL"))
LOG_CHANNEL = int(os.environ.get("LOG_CHANNEL", MAIN_CHANNEL))  # fallback

RSS_FEEDS = os.environ.get("RSS_TOR", "").split()  # multiple feeds can be space-separated

# ---------------- Logging ---------------- #
def write_log(message):
    LOGS.info(message)

async def send_log_to_telegram(message):
    try:
        from bot import bot
        await bot.send_message(LOG_CHANNEL, f"<b>Pipeline Log:</b>\n{message}")
    except Exception:
        write_log("Failed to send log to Telegram")

# ---------------- Progress Utilities ---------------- #
def build_progress_bar(percent):
    filled = "█" * (percent // 8)
    empty = "▒" * (12 - (percent // 8))
    return f"[{filled}{empty}] {percent}%"

async def update_progress(msg, step_name, total_percent):
    bar = build_progress_bar(total_percent)
    text = f"""<b>Pipeline Progress</b>
‣ Step: {step_name}
‣ {bar}
‣ Completed: {total_percent}%"""
    await editMessage(msg, text)

# ---------------- RSS Parsing ---------------- #
def parse_rss_feed(url):
    feed_items = []
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries:
            torrent_url = entry.link
            feed_items.append({"torrent_url": torrent_url})
    except Exception as e:
        write_log(f"Failed to parse RSS {url}: {str(e)}")
    return feed_items

# ---------------- Download ---------------- #
async def fetch_and_download(feed_items, download_dir, msg):
    downloader = TorDownloader(download_dir)
    downloaded_files = []
    total_items = len(feed_items)
    for idx, item in enumerate(feed_items, start=1):
        try:
            await update_progress(msg, f"Downloading {idx}/{total_items}", 5 + int(55 * (idx / total_items)))
            file_path = await downloader.download(item['torrent_url'])
            if file_path:
                downloaded_files.append(file_path)
                write_log(f"Downloaded: {file_path}")
            else:
                write_log(f"Download failed for {item['torrent_url']}")
        except Exception as e:
            write_log(f"Exception during download: {str(e)}")
            await rep.report(str(e), "error")
        await asyncio.sleep(0.1)
    return downloaded_files

# ---------------- Video Processing ---------------- #
def rename_video_file(file_path):
    import os
    dir_name, filename = os.path.split(file_path)
    name, ext = os.path.splitext(filename)
    new_name = name.replace(".", " ").title() + ext
    new_path = os.path.join(dir_name, new_name)
    os.rename(file_path, new_path)
    write_log(f"Renamed {file_path} → {new_path}")
    return new_path

async def process_videos(file_paths, msg, quality="720"):
    if not os.path.exists(PROCESSED_DIR):
        os.makedirs(PROCESSED_DIR)

    total_files = len(file_paths)
    for idx, fpath in enumerate(file_paths, start=1):
        try:
            # Rename
            await update_progress(msg, f"Renaming file {idx}/{total_files}", 60 + int(5 * (idx / total_files)))
            new_path = rename_video_file(fpath)

            # Encode / Metadata Update
            ffencoder = FFEncoder(message=None, path=os.path.dirname(new_path),
                                  name=os.path.basename(new_path), qual=quality)

            # Start encoding with periodic progress update
            async def encoder_progress_updater():
                while ffencoder.__proc is None or not ffencoder.is_cancelled:
                    await asyncio.sleep(UPDATE_INTERVAL)
                    percent = min(85, 60 + int(20 * (idx / total_files)))
                    await update_progress(msg, f"Encoding {idx}/{total_files}", percent)
                    if ffencoder.__proc is None:
                        break

            asyncio.create_task(encoder_progress_updater())
            final_path = await ffencoder.start_encode()
            if not final_path:
                write_log(f"Encoding cancelled or failed: {new_path}")
                continue
            write_log(f"Encoding finished: {final_path}")

            # Move to processed folder
            proc_path = os.path.join(PROCESSED_DIR, os.path.basename(final_path))
            os.rename(final_path, proc_path)
            write_log(f"Moved to processed folder: {proc_path}")
            await update_progress(msg, f"Moved file {idx}/{total_files}", 90)

            # Upload to Google Drive
            drive_link = await upload_to_drive(proc_path)
            write_log(f"Uploaded to Drive: {drive_link}")
            await update_progress(msg, f"Uploaded file {idx}/{total_files}", 100)

        except Exception as e:
            write_log(f"Exception during processing: {str(e)}")
            await rep.report(str(e), "error")

# ---------------- Main Pipeline ---------------- #
async def main_pipeline():
    from bot import bot
    msg = await bot.send_message(MAIN_CHANNEL, "<b>Starting RSS Batch Pipeline...</b>")

    for feed_url in RSS_FEEDS:
        try:
            write_log(f"Fetching RSS feed: {feed_url}")
            await update_progress(msg, "Fetching RSS feed", 0)
            feed_items = parse_rss_feed(feed_url)
            if not feed_items:
                write_log(f"No items found in feed: {feed_url}")
                continue

            downloaded_files = await fetch_and_download(feed_items, DOWNLOAD_DIR, msg)
            await process_videos(downloaded_files, msg, quality="720")

        except Exception as e:
            write_log(f"Pipeline exception for feed {feed_url}: {str(e)}")
            await rep.report(str(e), "error")

    await update_progress(msg, "Pipeline Completed ✅", 100)
    write_log("Batch RSS pipeline completed!")

# ---------------- Entry Point ---------------- #
async def start_pipeline():
    asyncio.create_task(main_pipeline())
