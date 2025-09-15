import asyncio
from os import path as ospath
from aiofiles.os import makedirs
from bot import Var, LOGS
from bot.core.ffencoder import FFEncoder
from bot.core.tordownload import TorDownloader
from bot.core.text_utils import TextEditor
from bot.core.tguploader import post_file, edit_post_buttons
from bot.core.database import get_episode, add_episode, update_episode_quality

# Queue for handling tasks sequentially
download_queue = asyncio.Queue()
tor = TorDownloader()

async def process_feed_item(item, quality: str):
    """
    item: dict with keys: url, title, episode_number, season, year, etc.
    quality: "720" or "1080"
    """
    ep_id = f"{item['title']}_S{item.get('season', '01')}_E{item.get('episode_number', '01')}"
    existing_ep = await get_episode(ep_id)

    # Skip if this quality already done
    if existing_ep and quality in existing_ep.get('qualities', []):
        LOGS.info(f"{ep_id} already has {quality}p encoded. Skipping.")
        return

    # Download
    if item['url'].startswith("magnet:") or item['url'].endswith(".torrent"):
        try:
            downloaded_file = await tor.download(item['url'], name=None)
        except Exception as e:
            LOGS.error(f"Download failed for {ep_id}: {e}")
            return
    else:
        LOGS.error(f"Unsupported URL type: {item['url']}")
        return

    # Auto-rename
    editor = TextEditor(downloaded_file)
    await editor.load_anilist()
    new_name = await editor.get_upname(qual=quality)

    # Move file to proper name
    dest_path = ospath.join("downloads", new_name)
    await asyncio.to_thread(os.rename, downloaded_file, dest_path)

    # Encode
    encoder = FFEncoder(None, dest_path, new_name, quality)
    try:
        encoded_path = await encoder.start_encode()
    except Exception as e:
        LOGS.error(f"Encoding failed for {ep_id} [{quality}p]: {e}")
        return

    # Post to Telegram
    caption = await editor.get_caption()
    if existing_ep:
        # Update buttons for second quality
        await edit_post_buttons(existing_ep['message_id'], quality, encoded_path)
        await update_episode_quality(ep_id, quality)
    else:
        msg_id = await post_file(encoded_path, caption, quality)
        await add_episode(ep_id, msg_id, [quality])

async def worker():
    while True:
        item, qual = await download_queue.get()
        try:
            await process_feed_item(item, qual)
        except Exception as e:
            LOGS.error(f"Failed processing {item.get('title')} [{qual}p]: {e}")
        finally:
            download_queue.task_done()

def enqueue_item(item, quality):
    """
    Add an RSS item to the processing queue.
    """
    download_queue.put_nowait((item, quality))

# Start worker tasks
async def start_workers(count=2):
    await makedirs("downloads", exist_ok=True)
    for _ in range(count):
        asyncio.create_task(worker())
