import asyncio
import feedparser
from os import path as ospath
from time import time

from bot.core.tordownload import TorDownloader
from bot.core.ffencoder import FFEncoder
from bot.core.gdrive_uploader import upload_to_drive
from bot.core.database import db
from bot.core.func_utils import editMessage


class RSSAnimeBot:
    def __init__(self):
        # Lazy import to avoid circular import
        from bot import Var, bot_loop, LOGS
        self.Var = Var
        self.bot_loop = bot_loop
        self.LOGS = LOGS

        self.tor_downloader = TorDownloader(path="downloads")
        self.processed = set()

    async def fetch_rss_entries(self):
        entries = []
        for rss_url in getattr(self.Var, "RSS_TOR", []):
            try:
                feed = feedparser.parse(rss_url)
                entries.extend(feed.entries)
            except Exception as e:
                self.LOGS.error(f"Failed to fetch RSS {rss_url}: {str(e)}")
        return entries

    async def process_entry(self, entry):
        ani_id = entry.get("id") or entry.get("link")
        if not ani_id or ani_id in self.processed:
            return

        db_entry = await db.getAnime(ani_id)
        if db_entry.get("processed"):
            self.processed.add(ani_id)
            return

        self.processed.add(ani_id)
        title = entry.get("title") or "Anime"
        torrent_link = entry.get("link")

        msg = await editMessage(None, f"<i>Starting:</i> {title}")

        start_time = time()
        status = {
            "download": 0,
            "encode": 0,
            "upload": 0,
            "phase": "Download"
        }

        async def update_progress_loop():
            while status["phase"] != "done":
                progress_text = f"""<b>{title}</b>
‣ <b>Status:</b> {status['phase']}
‣ <b>Download:</b> {status['download']}%
‣ <b>Encode:</b> {status['encode']}%
‣ <b>Upload:</b> {status['upload']}%
‣ <b>Elapsed:</b> {int(time()-start_time)}s
"""
                await editMessage(msg, progress_text)
                await asyncio.sleep(10)  # update every 10 seconds

        progress_task = asyncio.create_task(update_progress_loop())

        # --- Step 1: Download ---
        status["phase"] = "Download"
        downloaded_file = await self.tor_downloader.download(torrent_link)
        if not downloaded_file:
            await editMessage(msg, f"❌ Failed to download {title}")
            status["phase"] = "done"
            return
        status["download"] = 100

        # --- Step 2: Rename ---
        renamed_file = self.rename_file(downloaded_file, title)

        # --- Step 3: Metadata-only encode ---
        status["phase"] = "Encode"
        encoder = FFEncoder(msg, renamed_file, ospath.basename(renamed_file), "720")
        encoded_file = await encoder.start_encode()
        if not encoded_file:
            await editMessage(msg, f"❌ Encode failed {title}")
            status["phase"] = "done"
            return
        status["encode"] = 100

        # --- Step 4: Upload ---
        status["phase"] = "Upload"
        drive_url = await upload_to_drive(encoded_file, self.Var.DRIVE_FOLDER_ID)
        status["upload"] = 100

        # --- Step 5: Update DB ---
        await db.saveAnime(ani_id, "ep1", "720", post_id=None)
        await db._MongoDB__animes.update_one({'_id': ani_id}, {'$set': {'processed': True}}, upsert=True)

        status["phase"] = "done"
        await progress_task
        await editMessage(msg, f"✅ <b>{title}</b> Uploaded\n{drive_url}")

    def rename_file(self, file_path, title):
        base = ospath.basename(file_path)
        parts = base.split(" - ")
        ep_part = parts[1] if len(parts) > 1 else "01"
        qual = "720p"
        new_name = f"[AnimeToki] {parts[0]} - {ep_part} {qual} Dual Audio.mkv"
        new_path = ospath.join("downloads", new_name)
        try:
            ospath.rename(file_path, new_path)
        except Exception:
            new_path = file_path
        return new_path

    async def run_batch(self):
        while True:
            try:
                entries = await self.fetch_rss_entries()
                for entry in entries:
                    await self.process_entry(entry)
            except Exception as e:
                self.LOGS.error(f"RSS batch loop error: {str(e)}")
            await asyncio.sleep(1800)  # fetch every 30 minutes


# --- Function to safely start the background task ---
def start_task():
    from bot import bot_loop
    bot_loop.create_task(RSSAnimeBot().run_batch())
