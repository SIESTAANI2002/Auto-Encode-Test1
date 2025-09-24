import asyncio
from bot.core.tordownload import TorDownloader
import os
from os import path as ospath

class TorHelper:
    def __init__(self, download_dir="./downloads"):
        self.downloader = TorDownloader(download_dir)
        self.current_progress = 0.0
        self.downloaded_file = None

    async def download_with_progress(self, torrent_url):
        # Start original TorDownloader download in background
        download_task = asyncio.create_task(self.downloader.download(torrent_url))

        # Track progress by checking file size
        # Note: this assumes the torrent creates a single file in download_dir
        file_name = torrent_url.split("/")[-1]  # temporary name
        while not download_task.done():
            try:
                # get downloaded file in folder
                files = os.listdir(self.downloader._TorDownloader__downdir)
                if files:
                    fpath = ospath.join(self.downloader._TorDownloader__downdir, files[0])
                    size = ospath.getsize(fpath)
                    total_size = 1  # fallback
                    # Optional: if you can access torp._torrent_info.total_size, use it
                    self.current_progress = min(size / max(total_size, 1), 1.0)
            except:
                self.current_progress = 0.0
            await asyncio.sleep(5)

        # Wait until download finishes
        self.downloaded_file = await download_task
        self.current_progress = 1.0
        return self.downloaded_file
