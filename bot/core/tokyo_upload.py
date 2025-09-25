import aiohttp
import asyncio
from os import path as ospath

async def upload_to_tokyo(torrent_file: str, title: str, api_key: str):
    """
    Upload a .torrent file to TokyoTosho using the API key.

    Args:
        torrent_file (str): Path to the .torrent file.
        title (str): Torrent title.
        api_key (str): TokyoTosho API key.

    Returns:
        dict: Response from TokyoTosho API.
    """
    if not ospath.exists(torrent_file):
        raise FileNotFoundError(f"Torrent file not found: {torrent_file}")

    url = "https://tokyotosho.info/api/post"
    data = aiohttp.FormData()
    data.add_field("apikey", api_key)
    data.add_field("title", title)
    data.add_field("type", "anime")  # change type if needed
    data.add_field("file", open(torrent_file, "rb"), filename=f"{title}.torrent", content_type="application/x-bittorrent")

    async with aiohttp.ClientSession() as session:
        async with session.post(url, data=data) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise ValueError(f"TokyoTosho API returned status {resp.status}: {text}")
            return await resp.json()
