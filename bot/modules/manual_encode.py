from os import path as ospath, makedirs
from aiofiles.os import remove as aioremove
from asyncio import Queue
from bot import Var, LOGS
from bot.core.ffencoder import FFEncoder
from bot.core.func_utils import sendMessage, editMessage
from bot.core.uploader import upload_to_gdrive

# manual encoding queue (to avoid parallel encode crashes)
manual_queue = Queue()

async def manual_encode(message, download_path, file_name, quality="720"):
    """
    Add a manual encode task to the queue.
    quality = "1080" or "720"
    """
    await manual_queue.put((message, download_path, file_name, quality))
    if manual_queue.qsize() == 1:
        await queue_runner()


async def queue_runner():
    """Runs tasks in queue sequentially"""
    while not manual_queue.empty():
        message, download_path, file_name, quality = await manual_queue.get()

        # reply message for progress updates
        msg = await sendMessage(message, f"⬇️ Download completed. Starting {quality}p encoding...")

        try:
            makedirs("encode", exist_ok=True)

            # FFEncoder handles progress + bar updates
            encoder = FFEncoder(msg, download_path, file_name, quality)

            # start encoding
            output_path = await encoder.start_encode()

            if not output_path or not ospath.exists(output_path):
                await editMessage(msg, f"❌ {quality}p encoding failed.")
                continue

            # upload to GDrive
            gdrive_link = await upload_to_gdrive(output_path, file_name)

            # final success message
            await editMessage(
                msg,
                f"✅ {quality}p Encoding completed & uploaded!\n\n📁 <b>{file_name}</b>\n🔗 <a href='{gdrive_link}'>Google Drive</a>"
            )

            # cleanup encoded file
            try:
                await aioremove(output_path)
            except Exception as e:
                LOGS.warning(f"Cleanup failed: {e}")

        except Exception as e:
            LOGS.error(f"Manual encode error: {e}", exc_info=True)
            await editMessage(msg, f"❌ Error: {e}")

        manual_queue.task_done()
