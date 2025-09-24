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
        download_task = asyncio.create_task(self.downloader.download(torrent_url))

        # Wait a little for file to appear
        await asyncio.sleep(1)
        total_size = None

        while not download_task.done():
            try:
                # get first file in download folder
                files = os.listdir(self.downloader._TorDownloader__downdir)
                if files:
                    fpath = ospath.join(self.downloader._TorDownloader__downdir, files[0])
                    size = ospath.getsize(fpath)
                    if total_size is None:
                        # Estimate total size as double the current file size initially
                        total_size = max(size * 2, 1)
                    self.current_progress = min(size / total_size, 0.95)
            except:
                self.current_progress = 0.0
            await asyncio.sleep(2)  # check progress every 2 seconds

        # Download finished
        self.downloaded_file = await download_task
        self.current_progress = 1.0
        return self.downloaded_file
