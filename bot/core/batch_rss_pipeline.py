import os
import asyncio
import feedparser
from re import findall

from bot.core.torhelper import TorHelper
from bot.core.ffencoder import FFEncoder
from bot.core.gdrive_uploader import upload_to_drive
from bot import LOGS, bot
from bot.core.func_utils import editMessage

TORRENTS_DIR = "torrents/"
DOWNLOAD_DIR = "downloads"
PROCESSED_DIR = "processed"

for folder in [TORRENTS_DIR, DOWNLOAD_DIR, PROCESSED_DIR]:
    if not os.path.exists(folder):
        os.makedirs(folder, exist_ok=True)

UPDATE_INTERVAL = 10  # seconds between Telegram updates
RSS_FEEDS = os.environ.get("RSS_TOR", "").split()
MAIN_CHANNEL = int(os.environ.get("MAIN_CHANNEL"))
LOG_CHANNEL = int(os.environ.get("LOG_CHANNEL", MAIN_CHANNEL))

downloaded_links = set()


def write_log(message):
    LOGS.info(message)


async def update_progress(msg, step_name, percent, last_percent=[-1]):
    """Flood-safe Telegram progress updates every 10 seconds or on meaningful change."""
    if abs(percent - last_percent[0]) >= 2 or percent == 100:
        bar = "█" * (percent // 8) + "▒" * (12 - percent // 8)
        text = f"""<b>Pipeline Progress</b>
‣ Step: {step_name}
‣ {bar} {percent}%"""
        try:
            await msg.edit_text(text)
            last_percent[0] = percent
        except Exception as e:
            LOGS.warning(f"[WARNING] Telegram says: {str(e)}")


def rename_video_file(file_path):
    dir_name, filename = os.path.split(file_path)
    name, ext = os.path.splitext(filename)
    new_name = name.replace(".", " ").title() + ext
    new_path = os.path.join(dir_name, new_name)
    os.rename(file_path, new_path)
    write_log(f"Renamed {file_path} → {new_path}")
    return new_path


async def encode_video(fpath, msg, step_name, qual="720"):
    ffencoder = FFEncoder(
        message=None,
        path=os.path.dirname(fpath),
        name=os.path.basename(fpath),
        qual=qual,
    )

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
                await update_progress(msg, step_name, percent)
            except:
                pass
            await asyncio.sleep(UPDATE_INTERVAL)

    asyncio.create_task(update_encoding_progress())
    final_path = await ffencoder.start_encode()
    return final_path


async def process_torrent(torrent_url, msg):
    helper = TorHelper(DOWNLOAD_DIR)
    filename = torrent_url.split("/")[-1]
    write_log(f"Start downloading {filename}")

    # Start download with real-time progress
    download_task = asyncio.create_task(helper.download_with_progress(torrent_url))

    # Update Telegram progress based on helper.current_progress
    while not download_task.done():
        percent = int(helper.current_progress * 50)  # 0-50% for download
        await update_progress(msg, f"Downloading {filename}", percent)
        await asyncio.sleep(UPDATE_INTERVAL)

    file_path = await download_task
    if not file_path:
        write_log(f"Download failed: {filename}")
        return

    await update_progress(msg, f"Downloaded {filename}", 50)

    # Rename
    new_path = rename_video_file(file_path)

    # Encode 50-95%
    final_path = await encode_video(new_path, msg, f"Encoding {filename}")

    # Move to processed folder
    if not os.path.exists(PROCESSED_DIR):
        os.makedirs(PROCESSED_DIR)
    proc_path = os.path.join(PROCESSED_DIR, os.path.basename(final_path))
    os.rename(final_path, proc_path)
    await update_progress(msg, f"Moved {filename}", 95)
    write_log(f"Moved to processed folder: {proc_path}")

    # Upload to Drive (95–100%)
    drive_link = await upload_to_drive(proc_path)
    await update_progress(msg, f"Uploaded {filename}", 100)
    write_log(f"Uploaded to Drive: {drive_link}")


async def rss_watcher():
    msg = await bot.send_message(MAIN_CHANNEL, "<b>Starting RSS Batch Pipeline...</b>")

    while True:
        for feed_url in RSS_FEEDS:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries:
                if entry.link not in downloaded_links:
                    downloaded_links.add(entry.link)
                    # Only process the first new link
                    asyncio.create_task(process_torrent(entry.link, msg))
                    break  # stop after first new link
            break  # stop after first feed
        await asyncio.sleep(600)  # check RSS every 10 minutes


async def start_pipeline():
    """Call this in main.py or wherever the bot starts"""
    asyncio.create_task(rss_watcher())
