import os
import asyncio
from re import findall
from tordownload import TorDownloader
from bot.core.gdrive_uploader import upload_to_drive
from bot.core.ffencoder import FFEncoder
from bot.core.reporter import rep
from bot import LOGS, bot
from bot.core.func_utils import editMessage

DOWNLOAD_DIR = "downloads"
PROCESSED_DIR = "processed"
UPDATE_INTERVAL = 10  # seconds
RSS_FEEDS = os.environ.get("RSS_TOR", "").split()
MAIN_CHANNEL = int(os.environ.get("MAIN_CHANNEL"))
LOG_CHANNEL = int(os.environ.get("LOG_CHANNEL", MAIN_CHANNEL))

def write_log(message):
    LOGS.info(message)

async def update_progress(msg, step_name, percent):
    bar = "█" * (percent // 8) + "▒" * (12 - percent // 8)
    text = f"""<b>Pipeline Progress</b>
‣ Step: {step_name}
‣ {bar} {percent}%
"""
    await editMessage(msg, text)

async def fetch_and_download(feed_items, msg):
    downloader = TorDownloader(DOWNLOAD_DIR)
    downloaded_files = []
    total_items = len(feed_items)

    for idx, item in enumerate(feed_items, start=1):
        filename = item['torrent_url'].split("/")[-1]
        write_log(f"Start downloading {filename}")

        # Start download in background
        download_task = asyncio.create_task(downloader.download(item['torrent_url']))

        # Fake progress updates until done (replace with real progress if available)
        percent = 0
        while not download_task.done():
            await update_progress(msg, f"Downloading {idx}/{total_items}", percent)
            percent = min(percent + 5, 50)
            await asyncio.sleep(UPDATE_INTERVAL)

        file_path = await download_task
        if file_path:
            downloaded_files.append(file_path)
            write_log(f"Downloaded: {file_path}")
            await update_progress(msg, f"Downloaded {idx}/{total_items}", 50)
        else:
            write_log(f"Download failed for {filename}")
    return downloaded_files

def rename_video_file(file_path):
    dir_name, filename = os.path.split(file_path)
    name, ext = os.path.splitext(filename)
    new_name = name.replace(".", " ").title() + ext
    new_path = os.path.join(dir_name, new_name)
    os.rename(file_path, new_path)
    write_log(f"Renamed {file_path} → {new_path}")
    return new_path

async def encode_video(fpath, msg, idx, total_files, qual="720"):
    ffencoder = FFEncoder(message=None, path=os.path.dirname(fpath),
                          name=os.path.basename(fpath), qual=qual)

    async def update_encoding_progress():
        while ffencoder._FFEncoder__proc is None or not ffencoder.is_cancelled:
            try:
                percent = 50
                prog_file = ffencoder._FFEncoder__prog_file
                if os.path.exists(prog_file):
                    with open(prog_file, "r") as f:
                        text = f.read()
                    if t := findall(r"out_time_ms=(\d+)", text):
                        time_done = int(t[-1]) / 1000000
                        total_time = ffencoder._FFEncoder__total_time or 1.0
                        percent = 50 + int((time_done / total_time) * 50)
                await update_progress(msg, f"Encoding {idx}/{total_files}", percent)
            except:
                pass
            await asyncio.sleep(UPDATE_INTERVAL)

    asyncio.create_task(update_encoding_progress())
    final_path = await ffencoder.start_encode()
    return final_path

async def process_videos(file_paths, msg):
    if not os.path.exists(PROCESSED_DIR):
        os.makedirs(PROCESSED_DIR)

    total_files = len(file_paths)
    for idx, fpath in enumerate(file_paths, start=1):
        try:
            new_path = rename_video_file(fpath)
            final_path = await encode_video(new_path, msg, idx, total_files)
            proc_path = os.path.join(PROCESSED_DIR, os.path.basename(final_path))
            os.rename(final_path, proc_path)
            write_log(f"Moved to processed folder: {proc_path}")
            await update_progress(msg, f"Moved {idx}/{total_files}", 90)

            drive_link = await upload_to_drive(proc_path)
            write_log(f"Uploaded to Drive: {drive_link}")
            await update_progress(msg, f"Uploaded {idx}/{total_files}", 100)
        except Exception as e:
            write_log(f"Error processing {fpath}: {str(e)}")
            await rep.report(str(e), "error")

async def main_pipeline():
    msg = await bot.send_message(MAIN_CHANNEL, "<b>Starting RSS Batch Pipeline...</b>")

    for feed_url in RSS_FEEDS:
        try:
            write_log(f"Fetching RSS feed: {feed_url}")
            await update_progress(msg, "Fetching RSS feed", 0)
            import feedparser
            feed_items = [{"torrent_url": e.link} for e in feedparser.parse(feed_url).entries]
            if not feed_items:
                write_log(f"No items found in feed: {feed_url}")
                continue

            downloaded_files = await fetch_and_download(feed_items, msg)
            await process_videos(downloaded_files, msg)

        except Exception as e:
            write_log(f"Pipeline exception for feed {feed_url}: {str(e)}")
            await rep.report(str(e), "error")

    await update_progress(msg, "Pipeline Completed ✅", 100)
    write_log("Batch RSS pipeline completed!")

async def start_pipeline():
    asyncio.create_task(main_pipeline())
