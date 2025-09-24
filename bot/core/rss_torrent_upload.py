import asyncio
import aiohttp
import xml.etree.ElementTree as ET
from bot import LOGS, Var
from bot.core.tordownload import TorDownloader
from bot.core.ffencoder import FFEncoder
from bot.core.gdrive_uploader import upload_file
from bot.core.func_utils import convertBytes

# -------------------- Queue -------------------- #
ffQueue = asyncio.Queue()
ffLock = asyncio.Lock()

# -------------------- RSS Fetch -------------------- #
async def fetch_rss():
    for feed_url in Var.RSS_TOR:  # renamed from RSS_FEEDS
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(feed_url) as resp:
                    xml_text = await resp.text()
            root = ET.fromstring(xml_text)
            for item in root.findall("./channel/item"):
                title = item.find("title").text
                torrent_url = item.find("link").text
                await ffQueue.put((title, torrent_url))
                LOGS.info(f"[RSS] Queued: {title}")
        except Exception as e:
            LOGS.error(f"[RSS] Fetch failed: {feed_url} | {e}")

# -------------------- Download & Process -------------------- #
async def process_queue():
    while True:
        title, torrent_url = await ffQueue.get()
        try:
            # -------------------- Download -------------------- #
            file_path = await TorDownloader().download(torrent_url)
            LOGS.info(f"⬇️ Downloaded: {title}")

            # -------------------- Rename -------------------- #
            new_name = title.replace(Var.SECOND_BRAND, "[AnimeToki]")
            LOGS.info(f"🔹 Renamed to: {new_name}")

            # -------------------- Metadata only -------------------- #
            # If FFCODE_480 enabled, encode 480p too
            if Var.FFCODE_480:
                await FFEncoder(file_path).encode_480p()

            # -------------------- Upload -------------------- #
            upload_path = await upload_file(file_path, folder="GoogleDrive")
            LOGS.info(f"✅ Uploaded: {upload_path}")

        except Exception as e:
            LOGS.error(f"[ERROR] Failed: {title} | {e}")

        ffQueue.task_done()

# -------------------- Start Tasks -------------------- #
def start_tasks(loop):
    loop.create_task(fetch_rss())
    loop.create_task(process_queue())
