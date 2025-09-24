# bot/core/rss_torrent_upload.py

import asyncio
from os import path as ospath
from aiofiles import open as aiopen
from bot import Var, bot, bot_loop, LOGS, ffQueue, ffLock, ff_queued
from bot.core.tordownload import TorDownloader
from bot.core.ffencoder import FFEncoder
from bot.core.gdrive_uploader import upload_to_drive
from bot.core.database import db
from bot.core.func_utils import editMessage

downloader = TorDownloader()

async def start_task():
    """Background loop to fetch torrents from RSS_TOR feed."""
    while True:
        if not getattr(Var, "RSS_TOR", []):
            await asyncio.sleep(60)
            continue

        for rss_link in Var.RSS_TOR:
            try:
                from feedparser import parse
                feed = parse(rss_link)
                for entry in feed.entries:
                    torrent_link = None
                    if 'links' in entry:
                        for l in entry.links:
                            if l.get('type') == 'application/x-bittorrent':
                                torrent_link = l['href']
                                break
                    if not torrent_link:
                        continue

                    post_id = (id(entry), entry)  # Unique queue key
                    ff_queued[post_id] = asyncio.Event()
                    await ffQueue.put(post_id)

            except Exception as e:
                LOGS.error(f"RSS Fetch Failed: {e}")
        await asyncio.sleep(600)  # Check RSS every 10 min

async def queue_loop():
    """Sequential queue processing for download → rename → encode → upload."""
    while True:
        if not ffQueue.empty():
            post_id = await ffQueue.get()
            entry = post_id[1]

            try:
                msg = await bot.send_message(
                    chat_id=Var.LOG_CHANNEL or Var.OWNER_ID,
                    text=f"<b>🔗 Found Torrent:</b> {entry.title}\n\n⏳ Starting download..."
                )

                # ---------------- Download ---------------- #
                file_path = await downloader.download(entry.links[0]['href'])
                if not file_path:
                    await editMessage(msg, f"❌ Download failed: {entry.title}")
                    LOGS.error(f"Torrent download failed: {entry.title}")
                    ffQueue.task_done()
                    continue

                await editMessage(msg, f"✅ Download finished: {ospath.basename(file_path)}\n⏳ Renaming...")

                # ---------------- Rename ---------------- #
                orig_name = ospath.basename(file_path)
                new_name = f"[AnimeToki] {orig_name.split(' ', 1)[1].split('] ', 1)[-1].rsplit('.', 1)[0]} Dual Audio.mkv"
                new_path = ospath.join(ospath.dirname(file_path), new_name)
                import aiofiles.os as aioms
                await aioms.rename(file_path, new_path)
                file_path = new_path
                await editMessage(msg, f"✅ Renamed to: {new_name}\n⏳ Starting Encode...")

                # ---------------- Encode ---------------- #
                qual = "720" if "720" in orig_name else "1080"
                encoder = FFEncoder(msg, file_path, new_name, qual)
                encoded_file = await encoder.start_encode()
                if not encoded_file:
                    await editMessage(msg, f"❌ Encode failed: {new_name}")
                    ffQueue.task_done()
                    continue

                await editMessage(msg, f"✅ Encode finished: {ospath.basename(encoded_file)}\n⏳ Uploading...")

                # ---------------- Upload ---------------- #
                drive_link = await upload_to_drive(encoded_file)
                await editMessage(msg, f"✅ Uploaded: [Drive Link]({drive_link})\n🎉 Completed: {new_name}")

                # ---------------- DB Save ---------------- #
                anime_id = entry.title.split('[')[-1].split(']')[0]
                await db.saveAnime(anime_id, "01", qual)

            except Exception as e:
                await editMessage(msg, f"❌ Error: {e}")
                LOGS.error(f"Queue Task Failed: {e}")

            ffQueue.task_done()

        await asyncio.sleep(2)
