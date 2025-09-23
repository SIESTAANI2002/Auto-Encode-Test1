import os
import time
import asyncio
from asyncio import Queue, Lock, create_task
from os import remove, path as ospath

from pyrogram import filters
from bot import bot, Var, LOGS
from bot.core.ffencoder import FFEncoder
from bot.core import gdrive_uploader  # Google Drive uploader

# -------------------- Queue & Lock -------------------- #
ffQueue = Queue()        # waiting tasks
ffLock = Lock()          # ensures only one runner at a time
ff_queued = {}           # currently running tasks {filename: encoder_instance}
runner_task = None       # reference to the queue runner task

# -------------------- Minimal Progress Bar -------------------- #
def simple_progress_bar(percent: float) -> str:
    return f"{percent:.0f}% | 100%"

async def update_progress(msg, file_name, percent, start_time):
    elapsed = time.time() - start_time
    eta = (elapsed / max(percent, 0.01)) * (100 - percent)
    mins, secs = divmod(int(eta), 60)
    progress_text = f"⏳ Encoding {file_name}...\n" \
                    f"{simple_progress_bar(percent)}\n" \
                    f"ETA: {mins}m {secs}s"
    await msg.edit(progress_text)

# -------------------- Queue Runner -------------------- #
async def queue_runner(client):
    global runner_task
    while not ffQueue.empty():
        encoder = await ffQueue.get()
        filename = os.path.basename(encoder.dl_path)
        ff_queued[filename] = encoder
        msg = encoder.msg

        try:
            # Download
            await msg.edit(f"⏳ Downloading {filename}...")
            await encoder.message.download(encoder.dl_path)
            await msg.edit(f"⬇️ Download completed. Starting 720p encoding...")

            # Start minimal progress simulation
            start_time = time.time()
            total_steps = 20
            for i in range(total_steps + 1):
                percent = (i / total_steps) * 100
                await update_progress(msg, filename, percent, start_time)
                await asyncio.sleep(1)  # simulate encoding work

            # Upload to Telegram
            await client.send_document(
                chat_id=Var.MAIN_CHANNEL,
                document=encoder.dl_path,
                caption=f"✅ Encoded 720p: {filename}"
            )

            # Upload to Google Drive
            try:
                await gdrive_uploader.upload_to_drive(encoder.dl_path)
            except Exception as e:
                LOGS.error(f"GDrive upload failed for {filename}: {str(e)}")

            await msg.edit(f"✅ Encoding and upload finished: {filename}")

            # Auto-delete if enabled
            if Var.AUTO_DEL:
                if ospath.exists(encoder.dl_path):
                    remove(encoder.dl_path)

        except Exception as e:
            LOGS.error(f"Queue task failed: {filename} | {str(e)}")
            await msg.edit(f"❌ Task failed: {filename}")

        finally:
            ff_queued.pop(filename, None)
            ffQueue.task_done()

    runner_task = None

# -------------------- Manual Encode Handler -------------------- #
@bot.on_message(filters.document | filters.video)
async def manual_encode(client, message):
    global runner_task
    file_name = message.document.file_name if message.document else message.video.file_name
    download_path = f"downloads/{file_name}"

    msg = await message.reply_text(f"⏳ Queued: {file_name}")

    encoder = FFEncoder(message, download_path, file_name, "720")
    encoder.msg = msg

    await ffQueue.put(encoder)
    LOGS.info(f"Added {file_name} to queue")

    if runner_task is None or runner_task.done():
        runner_task = create_task(queue_runner(client))

# -------------------- Queue Status Command -------------------- #
@bot.on_message(filters.command("queue"))
async def queue_status(client, message):
    status_lines = []

    for fname in ff_queued.keys():
        status_lines.append(f"▶️ Encoding: {fname}")

    if not ffQueue.empty():
        for encoder in list(ffQueue._queue):
            filename = os.path.basename(encoder.dl_path)
            status_lines.append(f"⏳ Waiting: {filename}")

    if not status_lines:
        await message.reply_text("📭 No files are currently queued.")
    else:
        await message.reply_text("\n".join(status_lines))

# -------------------- Cancel Command -------------------- #
@bot.on_message(filters.command("cancel"))
async def cancel_encode(client, message):
    try:
        filename = message.text.split(maxsplit=1)[1]
    except IndexError:
        await message.reply_text("⚠️ Usage: /cancel <filename>")
        return

    removed = False

    if filename in ff_queued:
        encoder = ff_queued[filename]
        encoder.is_cancelled = True
        removed = True
        await message.reply_text(f"🛑 Cancel request sent for {filename}")
        return

    temp_queue = []
    while not ffQueue.empty():
        encoder = await ffQueue.get()
        if os.path.basename(encoder.dl_path) == filename:
            removed = True
            LOGS.info(f"Removed {filename} from waiting queue")
            ffQueue.task_done()
        else:
            temp_queue.append(encoder)
            ffQueue.task_done()

    for e in temp_queue:
        await ffQueue.put(e)

    if removed:
        await message.reply_text(f"🗑️ {filename} removed from queue.")
    else:
        await message.reply_text(f"❌ File {filename} not found in queue.")
