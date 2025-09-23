from bot import bot, Var, LOGS
from pyrogram import filters
from asyncio import Queue, Lock, create_task, sleep
from bot.core.ffencoder import FFEncoder
from bot.core import gdrive_uploader
from os import remove, path as ospath
import os
from re import findall
import time

# -------------------- Helper Functions -------------------- #
def convertBytes(size: int) -> str:
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024:
            return f"{size:.2f}{unit}"
        size /= 1024
    return f"{size:.2f}PB"

def convertTime(seconds: float) -> str:
    seconds = int(seconds)
    h, m = divmod(seconds, 3600)
    m, s = divmod(m, 60)
    if h > 0:
        return f"{h}h {m}m {s}s"
    elif m > 0:
        return f"{m}m {s}s"
    else:
        return f"{s}s"

# -------------------- Queue & Lock -------------------- #
ffQueue = Queue()
ffLock = Lock()
ff_queued = {}
runner_task = None

# -------------------- Queue Runner -------------------- #
async def queue_runner(client):
    global runner_task
    while True:
        encoder = await ffQueue.get()
        filename = os.path.basename(encoder.dl_path)
        ff_queued[filename] = encoder
        msg = encoder.msg

        try:
            # Download
            await msg.edit(f"⬇️ Downloading {filename}...")
            await encoder.message.download(encoder.dl_path)
            await msg.edit(f"⬇️ Download completed. Starting 720p encoding...")

            # Encode with progress
            progress_file = encoder._FFEncoder__prog_file
            encoder_task = create_task(encoder.start_encode())
            last_percent = -5

            while not encoder_task.done():
                if ospath.exists(progress_file):
                    try:
                        with open(progress_file, "r") as f:
                            text = f.read()
                            if (t := findall(r"out_time_ms=(\d+)", text)):
                                time_done = int(t[-1]) / 1000000
                                total_time = getattr(encoder, "_FFEncoder__total_time", 1)
                                percent = min(round(time_done / total_time * 100, 2), 100)

                                # Progress bar
                                total_blocks = 20
                                filled = int(percent / 100 * total_blocks)
                                bar = "█" * filled + "-" * (total_blocks - filled)

                                # ETA
                                speed = time_done and time_done and 1 or 1
                                eta = max(total_time - time_done, 0)

                                progress_str = f"""<blockquote>‣ <b>Anime Name :</b> <b><i>{encoder.__name}</i></b></blockquote>
<blockquote>‣ <b>Status :</b> <i>Encoding</i>
    <code>[{bar}]</code> {percent}%</blockquote> 
<blockquote>   ‣ <b>Time Took :</b> {convertTime(time_done)}
    ‣ <b>Time Left :</b> {convertTime(eta)}</blockquote>"""

                                if percent - last_percent >= 1:
                                    await msg.edit(progress_str, parse_mode="html")
                                    last_percent = percent

                    except Exception as e:
                        LOGS.error(f"Progress read error: {str(e)}")
                else:
                    # fallback if progress file missing
                    dots = (int(time.time()) % 4) * "."
                    await msg.edit(f"⏳ Encoding {filename}{dots}")

                await sleep(1)

            output_path = await encoder_task

            # Upload to Telegram
            await client.send_document(
                chat_id=Var.MAIN_CHANNEL,
                document=output_path,
                caption=f"✅ Encoded 720p: {filename}"
            )

            # Upload to Google Drive
            try:
                await gdrive_uploader.upload_to_drive(output_path)
            except Exception as e:
                LOGS.error(f"GDrive upload failed for {filename}: {str(e)}")

            await msg.edit(f"✅ Encoding and upload finished: {filename}")

            # Auto-delete
            if Var.AUTO_DEL:
                for f in [encoder.dl_path, output_path]:
                    if ospath.exists(f):
                        remove(f)

        except Exception as e:
            LOGS.error(f"Queue task failed: {filename} | {str(e)}")
            await msg.edit(f"❌ Task failed: {filename}")

        finally:
            ff_queued.pop(filename, None)
            ffQueue.task_done()

    runner_task = None

# -------------------- Manual Encode -------------------- #
@bot.on_message(filters.document | filters.video)
async def manual_encode(client, message):
    file_name = message.document.file_name if message.document else message.video.file_name
    download_path = f"downloads/{file_name}"

    msg = await message.reply_text(f"⏳ Queued: {file_name}")

    encoder = FFEncoder(message, download_path, file_name, "720")
    encoder.msg = msg

    await ffQueue.put(encoder)
    LOGS.info(f"Added {file_name} to queue")

    global runner_task
    if runner_task is None or runner_task.done():
        runner_task = create_task(queue_runner(client))

# -------------------- Queue Status -------------------- #
@bot.on_message(filters.command("queue"))
async def queue_status(client, message):
    status_lines = []

    for fname, encoder in ff_queued.items():
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
