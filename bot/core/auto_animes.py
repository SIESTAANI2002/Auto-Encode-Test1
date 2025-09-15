from asyncio import create_task, gather
from bot.core.tguploader import TgUploader
from bot.core.ffencoder import FFEncoder
from bot.core.tordownload import TorDownloader
from bot.core.text_utils import TextEditor
from bot import LOGS, Var

async def fetch_animes(anime_url, quality="720"):
    """
    Main function to fetch anime, download, encode, and upload.
    Works with 720p or 1080p based on feed.
    """
    try:
        # 1. Initialize downloader
        downloader = TorDownloader()

        # 2. Download file
        LOGS.info(f"Starting download for {anime_url}")
        downloaded_file = await downloader.download(anime_url)

        # 3. Auto-rename using TextEditor
        editor = TextEditor(downloaded_file)
        await editor.load_anilist()
        new_name = await editor.get_upname(qual=quality)

        # Rename the downloaded file
        import os
        new_path = os.path.join("downloads", new_name)
        os.rename(downloaded_file, new_path)

        # 4. Encode file using FFEncoder
        ffencoder = FFEncoder(message=None, path=new_path, name=new_name, qual=quality)
        encoded_file = await ffencoder.start_encode()

        # 5. Upload to Telegram
        # Create TgUploader instance with optional progress message
        uploader = TgUploader(message=None)
        await uploader.upload(encoded_file, quality)

        LOGS.info(f"Upload completed for {new_name}")

    except Exception as e:
        LOGS.error(f"Error in fetch_animes: {e}")
