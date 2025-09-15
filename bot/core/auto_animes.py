# auto_animes.py
import os
import asyncio
from datetime import datetime
from pyrogram import Client
from bot.core.ffencoder import FFEncoder
from bot.core.tordownload_helper import download_torrent
from bot.config import Var  # Your config file with RSS_ITEMS, QUALS, etc.

# Downloads directory
DOWNLOAD_DIR = "./downloads"
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

# Queue to store anime tasks
anime_queue = asyncio.Queue()


async def fetch_animes():
    """
    Fetch RSS feeds from multiple sources and enqueue new episodes
    """
    feeds = Var.RSS_ITEMS if isinstance(Var.RSS_ITEMS, list) else Var.RSS_ITEMS.split()
    print(f"[INFO] Loaded RSS feeds: {feeds}")

    for feed_url in feeds:
        # Use your existing logic to fetch items from RSS
        # Example: fetched_items = parse_rss(feed_url)
        # Here, we just simulate:
        fetched_items = await simulate_rss_fetch(feed_url)
        for ep in fetched_items:
            await anime_queue.put(ep)
    print("[INFO] Anime queue populated.")


async def simulate_rss_fetch(feed_url):
    """
    Dummy function to simulate RSS fetch; replace with actual logic
    """
    await asyncio.sleep(1)
    return [
        {
            "title": "Sample Anime Episode 1",
            "url": feed_url,  # Can be magnet or torrent link
            "quality": "720" if "720" in feed_url else "1080",
            "filename": "Sample_Anime_Ep1",
        }
    ]


async def process_anime():
    """
    Process anime from queue:
    1. Download file
    2. Encode with FFEncoder
    3. Send post to Telegram with dual buttons
    """
    while True:
        anime = await anime_queue.get()
        if not anime:
            continue

        title = anime["title"]
        dl_url = anime["url"]
        qual = anime["quality"]
        filename = anime["filename"]

        print(f"[INFO] Processing {title} [{qual}p]...")

        try:
            # Download
            dl_path = await download_torrent(dl_url, filename)
            print(f"[INFO] Downloaded to {dl_path}")

            # Encode
            stat_msg = None  # Replace with your telegram message if using progress
            encoder = FFEncoder(stat_msg, dl_path, filename, qual)
            out_path = await encoder.start_encode()
            print(f"[INFO] Encoded file saved at {out_path}")

            # Send Telegram message with buttons
            await send_telegram_post(title, qual, out_path)

            # Cleanup
            if os.path.exists(dl_path):
                os.remove(dl_path)

        except Exception as e:
            print(f"[ERROR] Failed to process {title}: {e}")

        anime_queue.task_done()


async def send_telegram_post(title, qual, file_path):
    """
    Send post to main channel with dual buttons (720p + 1080p)
    """
    buttons = []
    if qual == "720":
        buttons.append(("720p", f"t.me/download/{file_path}"))
    elif qual == "1080":
        buttons.append(("1080p", f"t.me/download/{file_path}"))

    # If both 720 & 1080 exist, add both buttons
    if qual == "720" and await check_1080_exists(title):
        buttons.append(("1080p", f"t.me/download/{file_path.replace('720', '1080')}"))

    # Example Pyrogram send_message
    async with Client("bot", api_id=Var.API_ID, api_hash=Var.API_HASH, bot_token=Var.BOT_TOKEN) as app:
        await app.send_message(
            chat_id=Var.MAIN_CHANNEL,
            text=f"<b>{title}</b>\n<i>Available in multiple qualities</i>",
            reply_markup=buttons
        )


async def check_1080_exists(title):
    """
    Check if 1080p version exists in queue or storage
    """
    # Simplified: you can implement actual check based on your logic
    return True


async def main():
    print("[INFO] Auto Anime Bot Started!")
    await fetch_animes()
    await process_anime()


if __name__ == "__main__":
    asyncio.run(main())
