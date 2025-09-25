# bot/core/tokyo_upload.py
import os
import asyncio
import traceback
import torrentp  # make sure it's installed
import aiohttp
from bot import Var
from bot.core.reporter import rep

async def generate_torrent(out_path: str, name: str):
    """
    Generates a .torrent file from a folder or single file.
    Handles v1 torrents for single files to avoid 'no file tree' error.
    """
    try:
        # Check if path exists
        if not os.path.exists(out_path):
            await rep.report(f"TokyoTosho Upload Failed ({name}): Path does not exist", "error")
            return None

        # If single file, generate v1-only torrent
        if os.path.isfile(out_path):
            creator = torrentp.TorrentCreator(out_path)
            creator.create(v1_only=True)
            torrent_file = f"{out_path}.torrent"
            creator.save(torrent_file)
        else:
            # Folder: generate normally (v2)
            creator = torrentp.TorrentCreator(out_path)
            creator.create()
            torrent_file = f"{out_path}.torrent"
            creator.save(torrent_file)

        return torrent_file
    except Exception as e:
        await rep.report(f"TokyoTosho Upload Failed ({name}): Failed to generate torrent for {out_path}: {e}", "error")
        return None

async def upload_tokyo_tosho(torrent_path: str, name: str):
    """
    Uploads a generated torrent to TokyoTosho automatically using API key.
    """
    if not torrent_path or not os.path.exists(torrent_path):
        await rep.report(f"TokyoTosho Upload Failed ({name}): Torrent file missing", "error")
        return

    api_key = Var.TOKYO_API_KEY
    url = "https://www.tokyotosho.info/api/add.php"

    data = {
        "apikey": api_key,
        "type": "anime",  # adjust if needed
        "name": name,
        "comment": "Uploaded by AnimeToki | TG-@Ani_Animesh",
        "url": "https://animetoki.com",  # optional, if you have a website
    }

    try:
        async with aiohttp.ClientSession() as session:
            with open(torrent_path, "rb") as f:
                files = {"file": f}
                async with session.post(url, data=data, files=files) as resp:
                    text = await resp.text()
                    if resp.status == 200:
                        await rep.report(f"TokyoTosho Upload Success ({name})", "info")
                    else:
                        await rep.report(f"TokyoTosho Upload Failed ({name}): {text}", "error")
    except Exception:
        await rep.report(traceback.format_exc(), "error")
