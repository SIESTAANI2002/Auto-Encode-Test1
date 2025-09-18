import asyncio
from bot import LOGS, Var, ani_cache, ffQueue, ffLock, ff_queued
from bot.core.tordownload import TorDownloader
from bot.core.ffencoder import FFEncoder
from bot.core.tguploader import TgUploader
from bot.core.text_utils import TextEditor
from bot.core.reporter import rep
from bot.database import db
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# Torrent Downloader instance
tor_dl = TorDownloader("./downloads")

async def get_animes(ani_id, ep_no, title, link, qual):
    """
    Main auto task:
    - Downloads torrent
    - Encodes with ffmpeg
    - Uploads to Telegram
    - Posts with 2 bottom buttons
    """
    try:
        # Check if already uploaded
        existing_post_id = await db.getEpisodePost(ani_id, ep_no)
        if existing_post_id:
            LOGS.info(f"[SKIP] Already posted {title}")
            return

        # Prepare message
        text_editor = TextEditor()
        stat_msg = await rep.send(
            f"‣ <b>Anime Name :</b> <b><i>{title}</i></b>\n\n<i>Downloading...</i>"
        )

        # 1. Download Torrent
        dl_path = await tor_dl.download(link, title)

        # 2. Rename properly
        filename = await ani_cache.get_upname(qual, title, ep_no)
        out_path = f"./downloads/{filename}"

        # 3. Encode
        await rep.edit(
            stat_msg,
            f"‣ <b>Anime Name :</b> <b><i>{filename}</i></b>\n\n<i>Encoding Started...</i>"
        )
        out_path = await FFEncoder(stat_msg, dl_path, out_path, qual).start_encode()

        # 4. Upload
        await rep.edit(
            stat_msg,
            f"‣ <b>Anime Name :</b> <b><i>{filename}</i></b>\n\n<i>Uploading {qual}...</i>"
        )
        file_id = await TgUploader(stat_msg, out_path, filename).start_upload()

        # 5. Save DB
        await db.saveAnime(ani_id, ep_no, qual, post_id=file_id)

        # 6. Final Post with 2 buttons
        buttons = [
            [
                InlineKeyboardButton("📥 720p", callback_data=f"get_{ani_id}_{ep_no}_720"),
                InlineKeyboardButton("📥 1080p", callback_data=f"get_{ani_id}_{ep_no}_1080"),
            ]
        ]
        await rep.edit(
            stat_msg,
            f"✅ <b>{filename}</b>\n\n<i>Encoded & Uploaded Successfully!</i>",
            reply_markup=InlineKeyboardMarkup(buttons),
        )

        LOGS.info(f"[SUCCESS] Uploaded {filename}")

    except Exception as e:
        LOGS.error(f"[FAILED] {title} - {e}")
        await rep.report(f"Error while processing {title}: {e}", "error")
    finally:
        if ffLock.locked():
            ffLock.release()
