# bot/core/tokyo_upload.py
import aiohttp
import os
from bot import Var
from .reporter import rep

API_KEY = Var.TOKYO_API_KEY  # Set this in your Var.py
TORRENT_DIR = "torrents"

async def upload_to_tokyo(file_path: str, anime_name: str, qual: str):
    """
    Upload a torrent to TokyoTosho.
    
    Args:
        file_path (str): Path to the torrent file.
        anime_name (str): Name of the anime for logging.
        qual (str): Quality (1080p/720p).
    """
    if not os.path.exists(file_path):
        await rep.report(f"❌ File does not exist for TokyoTosho Upload ({qual}): {file_path}", "error")
        return
    
    url = "https://www.tokyotosho.info/api.php"
    data = {
        "apikey": API_KEY,
        "name": anime_name,
        "type": "anime",
        "bitrate": qual,
    }

    try:
        async with aiohttp.ClientSession() as session:
            with open(file_path, "rb") as f:
                files = {"file": f}
                async with session.post(url, data=data) as resp:
                    text = await resp.text()
                    if resp.status != 200:
                        await rep.report(f"❌ TokyoTosho Upload Exception ({qual}): {text}", "error")
                    else:
                        await rep.report(f"✅ Successfully Uploaded {qual} File to TokyoTosho!", "info")
    except Exception as e:
        await rep.report(f"❌ TokyoTosho Upload Exception ({qual}): {e}", "error")
