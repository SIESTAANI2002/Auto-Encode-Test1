# bot/core/tokyo_upload.py
import aiohttp
from bot import Var, bot_loop
from bot.core.reporter import rep

API_KEY = "22969-5d89e40ea4e9dfffb056ad7dfcb6631bbcf9cdef"
UPLOAD_URL = "https://www.tokyotosho.info/upload.php"

async def upload_to_tokyo(torrent_file, title, episode=None, quality=None):
    """
    Upload a .torrent file to TokyoTosho automatically.

    Args:
        torrent_file (str): Path to the .torrent file.
        title (str): Anime title.
        episode (int, optional): Episode number.
        quality (str, optional): Quality like 1080p.
    """
    try:
        data = {
            "api_key": API_KEY,
            "type": "Anime",  # adjust type if needed
            "title": f"{title} - E{episode} [{quality}]" if episode else f"{title} [{quality}]",
            "bit_torrent_url": "",  # optional: if torrent hosted online
            "comment": "Uploaded via Anime Bot",
        }

        files = {"torrent": open(torrent_file, "rb")}

        async with aiohttp.ClientSession() as session:
            async with session.post(UPLOAD_URL, data=data, files=files) as resp:
                if resp.status == 200:
                    await rep.report(f"✅ TokyoTosho Upload Success: {title} E{episode} [{quality}]", "info")
                else:
                    text = await resp.text()
                    await rep.report(f"❌ TokyoTosho Upload Failed: {title} E{episode} [{quality}] | Status: {resp.status} | {text}", "error")
    except Exception as e:
        await rep.report(f"❌ TokyoTosho Upload Exception: {e}", "error")
