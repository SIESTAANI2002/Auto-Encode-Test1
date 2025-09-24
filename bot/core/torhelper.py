import asyncio
import os
from os import path as ospath
from bot.core.tordownload import TorDownloader

class TorHelper:
    def __init__(self, download_dir="./downloads"):
        self.downloader = TorDownloader(download_dir)
        self.download_dir = download_dir
        self.current_progress = 0.0
        self.downloaded_file = None

    async def download_with_progress(self, torrent_url, estimated_total_size=None):
        """
        Downloads a torrent and updates current_progress.
        estimated_total_size: optional, if known from RSS feed or metadata.
        """
        download_task = asyncio.create_task(self.downloader.download(torrent_url))

        # Wait a little for the file to appear
        await asyncio.sleep(1)

        self.current_progress = 0.0

        while not download_task.done():
            try:
                # Check the largest file in download folder
                files = os.listdir(self.download_dir)
                if files:
                    largest_file = max(
                        (ospath.join(self.download_dir, f) for f in files),
                        key=ospath.getsize
                    )
                    size = ospath.getsize(largest_file)

                    # Use estimated_total_size if provided; else simulate
                    total_size = estimated_total_size or max(size * 2, 1)
                    self.current_progress = min(size / total_size, 0.95)
            except:
                self.current_progress = 0.0

            await asyncio.sleep(1)  # update every 1 second

        # Download finished
        self.downloaded_file = await download_task
        self.current_progress = 1.0

        # Return file if exists
        if self.downloaded_file and ospath.exists(self.downloaded_file):
            return self.downloaded_file
        return None

    async def wait_for_download(self):
        """Optional helper to wait until download completes."""
        while self.current_progress < 1.0:
            await asyncio.sleep(1)
        return self.downloaded_file
