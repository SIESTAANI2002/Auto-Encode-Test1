from os import path as ospath
from asyncio import create_task, gather
from bot.core.tordownload import TorDownloader
from bot.core.ffencoder import FFEncoder, ffargs
from bot.core.tguploader import post_file, edit_post_buttons
from bot.core.text_utils import TextEditor
from bot import Var, LOGS

# Simple cache to track processed episodes
EPISODE_CACHE = {}  # {episode_hash: {'msg_id': ..., 'qualities': [720, 1080]}}

async def process_anime(torrent_link, quality, message=None):
    """
    Process a single anime episode:
    - Download
    - Encode corresponding quality
    - Upload to Telegram
    - Update buttons if needed
    """
    try:
        # 1️⃣ Download
        downloader = TorDownloader(path="downloads")
        dl_file = await downloader.download(torrent_link)
        if not dl_file or not ospath.exists(dl_file):
            LOGS.error(f"Download failed for {torrent_link}")
            return

        # 2️⃣ Auto-Rename & Get Metadata
        editor = TextEditor(dl_file)
        await editor.load_anilist()
        up_name = await editor.get_upname(qual=quality)
        caption = await editor.get_caption()

        # 3️⃣ Encode
        encoder = FFEncoder(message, dl_file, up_name, quality)
        encoded_file = await encoder.start_encode()
        if not encoded_file:
            LOGS.error(f"Encoding failed for {up_name}")
            return

        # 4️⃣ Telegram Upload & Button Management
        episode_hash = f"{editor.pdata.get('anime_title')}-{editor.pdata.get('episode_number')}"
        if episode_hash in EPISODE_CACHE:
            # Episode exists, update buttons
            sent_msg_id = EPISODE_CACHE[episode_hash]['msg_id']
            EPISODE_CACHE[episode_hash]['qualities'].append(quality)
            buttons = [[f"{q}p" for q in EPISODE_CACHE[episode_hash]['qualities']]]
            await edit_post_buttons(sent_msg_id, buttons)
        else:
            # First quality, create new post
            sent_msg = await post_file(encoded_file, quality, message=message)
            EPISODE_CACHE[episode_hash] = {'msg_id': sent_msg, 'qualities': [quality]}

        LOGS.info(f"Processed {up_name} [{quality}p] successfully!")

    except Exception as e:
        LOGS.error(f"Error processing anime: {e}")
