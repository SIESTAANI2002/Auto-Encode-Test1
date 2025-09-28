import aiohttp
import os
from bot import Var, LOGS

async def upload_to_tokyo(torrent_path, name, comment=""):
    """
    Upload a torrent file to TokyoTosho.
    Keeps the torrent file if upload fails.
    """
    try:
        data = aiohttp.FormData()
        data.add_field("username", Var.TOKYO_USER)
        data.add_field("password", Var.TOKYO_PASS)
        data.add_field("type", "Anime")
        data.add_field("comment", comment or name)
        data.add_field(
            "torrent",
            open(torrent_path, "rb"),
            filename=name,
            content_type="application/x-bittorrent"
        )

        async with aiohttp.ClientSession() as session:
            async with session.post("https://www.tokyotosho.info/upload.php", data=data) as resp:
                text = await resp.text()
                if resp.status != 200:
                    raise Exception(f"TokyoTosho returned {resp.status}: {text}")

                LOGS.info(f"[TokyoTosho] ✅ Upload success: {name}")

                # delete only if upload succeeded
                if os.path.exists(torrent_path):
                    os.remove(torrent_path)
                    LOGS.info(f"[TokyoTosho] 🗑️ Deleted local torrent: {torrent_path}")

                return True

    except Exception as e:
        LOGS.error(f"[ERROR] TokyoTosho Upload Exception ({name}): {e}")
        return False
