# tordownload_helper.py
import asyncio
import os
from bot.core.tordownload import download_magnet, download_torrent_file  # Your existing functions

DOWNLOAD_DIR = "./downloads"

async def download_torrent(link, filename):
    """
    Downloads a file from either a magnet link or a .torrent link.
    Returns the local file path after download.
    """
    if not os.path.exists(DOWNLOAD_DIR):
        os.makedirs(DOWNLOAD_DIR)

    out_path = os.path.join(DOWNLOAD_DIR, f"{filename}.mkv")

    try:
        if link.startswith("magnet:"):
            # Use your tordownload.py magnet download function
            await download_magnet(link, out_path)
        elif link.endswith(".torrent") or "nyaa.si" in link:
            # Use your tordownload.py torrent download function
            await download_torrent_file(link, out_path)
        else:
            raise ValueError("Unsupported link type")

        # Ensure the file exists
        if not os.path.exists(out_path):
            raise FileNotFoundError(f"Download failed for {filename}")

        return out_path

    except Exception as e:
        # Log and re-raise
        print(f"❌ Error downloading {filename}: {e}")
        raise e
