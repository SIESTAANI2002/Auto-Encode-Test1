import asyncio
from bot.core.tordownload import TorDownloader
import os
from os import path as ospath

class TorHelper:
    def __init__(self, download_dir="./downloads"):
        """
        Initialize TorHelper with a download directory.
        """
        self.downloader = TorDownloader(download_dir)
        self.current_progress = 0.0  # 0.0 -> 1.0
        self.downloaded_file = None
        self.download_dir = download_dir

    async def download_with_progress(self, torrent_url):
        """
        Downloads a torrent and updates current_progress gradually.
        Returns the downloaded file path when done.
        """
        # Start the download in background
        download_task = asyncio.create_task(self.downloader.download(torrent_url))

        # Smooth progress simulation
        smooth_progress = 0.0
        self.current_progress = 0.0

        while not download_task.done():
            # Slowly increase progress to 95% while download runs
            smooth_progress = min(smooth_progress + 0.02, 0.95)
            self.current_progress = smooth_progress
            await asyncio.sleep(1)

        # Download finished
        self.downloaded_file = await download_task
        self.current_progress = 1.0

        # Optional: ensure the file exists
        if self.downloaded_file and ospath.exists(self.downloaded_file):
            return self.downloaded_file
        return None

    async def wait_for_download(self):
        """
        Wait until the download finishes (helper method if needed).
        """
        while self.current_progress < 1.0:
            await asyncio.sleep(1)
        return self.downloaded_file
