# bot/core/tokyo_upload.py
import aiohttp
import asyncio
from os import path as ospath
from bot import Var
from .reporter import rep
from .tokyo_torrent import generate_torrent

API_URL = "https://www.tokyotosho.info/api.php"

async def upload_to_tokyo(path, name, anime_type="Anime"):
    try:
        # 1️⃣ Generate .torrent
        torrent_path = await generate_torrent(path, name)
        if not torrent_path or not ospath.exists(torrent_path):
            await rep.report(f"[ERROR] Failed to generate torrent for {name}", "error")
            return False

        # 2️⃣ Upload torrent to Telegram to get public URL
        from .tguploader import TgUploader
        uploader = TgUploader(None)  # None because no progress message needed here
        tg_msg = await uploader.upload(torrent_path, "torrent")
        tg_link = f"https://t.me/{(await uploader._TgUploader__client.get_me()).username}/{tg_msg.id}"

        # 3️⃣ Send API request to TokyoTosho
        async with aiohttp.ClientSession() as session:
            data = {
                "api": Var.TOKYO_API_KEY,
                "name": name,
                "type": anime_type,
                "url": tg_link
            }
            async with session.post(API_URL, data=data) as resp:
                text = await resp.text()
                if resp.status == 200:
                    await rep.report(f"[INFO] Successfully Uploaded {name} to TokyoTosho", "info")
                    return True
                else:
                    await rep.report(f"[ERROR] TokyoTosho Upload Failed ({name}): {text}", "error")
                    return False

    except Exception as e:
        await rep.report(f"[ERROR] TokyoTosho Upload Exception ({name}): {e}", "error")
        return False
