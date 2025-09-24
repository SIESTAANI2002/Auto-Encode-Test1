import asyncio
import os
from pathlib import Path
from xml.etree import ElementTree as ET

from bot import Var, LOGS
from bot.core.func_utils import convertBytes
from bot.core.tordownload import TorDownloader
from bot.core.gdrive_uploader import upload_file
from bot.core.reporter import log_info, log_error

# -------------------------------------
# CONFIG USAGE
# -------------------------------------
RSS_TOR = Var.RSS_TOR  # list of RSS feed URLs
SECOND_BRAND = Var.SECOND_BRAND or "AnimeToki"  # tag to rename
FFCODE_480 = Var.FFCODE_480  # True if 480p encode is required

# -------------------------------------
# RSS FETCH & PARSE
# -------------------------------------
async def fetch_rss_items(feed_url):
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(feed_url) as resp:
                xml_text = await resp.text()
        root = ET.fromstring(xml_text)
        items = root.findall(".//item")
        torrents = []
        for item in items:
            title = item.find("title").text
            link = item.find("link").text
            torrents.append({"title": title, "link": link})
        return torrents
    except Exception as e:
        log_error(f"RSS fetch failed: {feed_url} | {e}")
        return []

# -------------------------------------
# BATCH HANDLER
# -------------------------------------
def find_video_files(folder_path):
    video_ext = [".mkv", ".mp4", ".avi"]
    files = []
    for root, _, filenames in os.walk(folder_path):
        for f in filenames:
            if Path(f).suffix.lower() in video_ext:
                files.append(Path(root) / f)
    return files

# -------------------------------------
# RENAME & METADATA
# -------------------------------------
def rename_and_update_metadata(video_path: Path):
    try:
        new_name = f"[{SECOND_BRAND}] {video_path.stem.split(']')[-1].strip()}{video_path.suffix}"
        new_path = video_path.with_name(new_name)
        video_path.rename(new_path)
        # Change metadata without re-encode
        os.system(f'mkvpropedit "{new_path}" --edit info --set "title={new_name}"')
        return new_path
    except Exception as e:
        log_error(f"Rename/metadata failed: {video_path} | {e}")
        return None

# -------------------------------------
# MAIN TASK
# -------------------------------------
async def process_rss_feed(feed_url):
    torrents = await fetch_rss_items(feed_url)
    for tor in torrents:
        title = tor["title"]
        torrent_link = tor["link"]
        log_info(f"⬇️ Starting download: {title}")
        try:
            folder_path = await TorDownloader.download(torrent_url=torrent_link)  # returns folder path
            if not folder_path:
                log_error(f"Download failed: {title}")
                continue

            video_files = find_video_files(folder_path)
            if not video_files:
                log_error(f"No video found in: {folder_path}")
                continue

            for vf in video_files:
                new_file = rename_and_update_metadata(vf)
                if new_file:
                    log_info(f"✅ Renamed & metadata updated: {new_file}")
                    # Optional 480p encode
                    if FFCODE_480:
                        from bot.core.ffencoder import FFEncoder
                        await FFEncoder.encode_480p(new_file)
                    # Upload to Google Drive
                    await upload_file(new_file)
                    log_info(f"⬆️ Uploaded: {new_file}")
        except Exception as e:
            log_error(f"Torrent processing failed: {title} | {e}")

# -------------------------------------
# LOOP ALL FEEDS
# -------------------------------------
async def rss_batch_loop():
    while True:
        for feed in RSS_TOR:
            await process_rss_feed(feed)
        await asyncio.sleep(Var.RSS_LOOP_INTERVAL or 1800)  # default 30 min
