import aiohttp
import os
from bot import Var, LOGS
from .reporter import rep

TOKYO_URL = "https://tokyotosho.info/new.php"  # ✅ Correct endpoint

async def upload_to_tokyo(filepath, torrent_path, title, comment="Fansub Upload"):
    """Upload .torrent file to TokyoTosho"""
    if not os.path.exists(torrent_path):
        await rep.report(f"[ERROR] Torrent file not found: {torrent_path}", "error")
        return None

    try:
        async with aiohttp.ClientSession() as session:
            with open(torrent_path, "rb") as tf:
                data = {
                    "submit": "Submit",
                    "username": Var.TOKYO_USER,
                    "password": Var.TOKYO_PASS,
                    "website": "https://animetoki.com",
                    "comment": comment,
                    "category": "1",  # Anime category
                    "name": title
                }
                files = {"torrent": tf}

                async with session.post(TOKYO_URL, data=data, files=files) as resp:
                    text = await resp.text()

                    if resp.status != 200:
                        await rep.report(f"[ERROR] TokyoTosho Upload failed: {resp.status}\n{text}", "error")
                        return None

                    if "successfully" in text.lower():
                        LOGS.info(f"[TokyoTosho] Upload OK: {title}")
                        return f"✅ Uploaded {os.path.basename(filepath)} to TokyoTosho"

                    await rep.report(f"[ERROR] TokyoTosho Upload Response:\n{text}", "error")
                    return None

    except Exception as e:
        await rep.report(f"[ERROR] TokyoTosho Upload Exception ({title}): {str(e)}", "error")
        return None
