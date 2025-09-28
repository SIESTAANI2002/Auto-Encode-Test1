import aiohttp
from bs4 import BeautifulSoup
from bot import Var, LOGS

TOKYO_UPLOAD_URL = "https://www.tokyotosho.info/new.php"

async def upload_to_tokyo(torrent_path, name, comment=""):
    """
    Upload a torrent file to TokyoTosho using the real form (new.php).
    """
    try:
        async with aiohttp.ClientSession() as session:
            # Step 1: Fetch the upload page
            async with session.get(TOKYO_UPLOAD_URL) as resp:
                page = await resp.text()

            # Step 2: Parse form fields (hidden inputs)
            soup = BeautifulSoup(page, "html.parser")
            form = soup.find("form")
            if not form:
                raise Exception("Upload form not found on TokyoTosho")

            action = form.get("action", TOKYO_UPLOAD_URL)

            # Build form data
            data = aiohttp.FormData()
            data.add_field("username", Var.TOKYO_USER)
            data.add_field("password", Var.TOKYO_PASS)
            data.add_field("title", name)
            data.add_field("category", "1")  # 1 = Anime
            data.add_field("comment", comment or name)

            # Add torrent file
            with open(torrent_path, "rb") as f:
                data.add_field(
                    "torrent",
                    f,
                    filename=name,
                    content_type="application/x-bittorrent"
                )

            # Add hidden inputs if any
            for hidden in form.find_all("input", {"type": "hidden"}):
                data.add_field(hidden.get("name"), hidden.get("value", ""))

            # Step 3: Submit upload
            async with session.post(action, data=data) as resp:
                text = await resp.text()
                if resp.status != 200:
                    raise Exception(f"TokyoTosho returned {resp.status}: {text}")

                if "Upload successful" in text or "successfully" in text.lower():
                    LOGS.info(f"[TokyoTosho] ✅ Upload success: {name}")
                    return True
                else:
                    raise Exception(f"TokyoTosho response unexpected: {text[:200]}...")

    except Exception as e:
        LOGS.error(f"[ERROR] TokyoTosho Upload Exception ({name}): {e}")
        return False
