from asyncio import create_task, create_subprocess_exec, create_subprocess_shell, run as asyrun, all_tasks, gather, sleep as asleep
from aiofiles import open as aiopen
from pyrogram import idle
from pyrogram.filters import command, user
from os import path as ospath, execl, kill
from sys import executable
from signal import SIGKILL
from pyrogram import filters
import base64

from bot import bot, Var, bot_loop, sch, LOGS, ffQueue, ffLock, ffpids_cache, ff_queued
from bot.core.auto_animes import fetch_animes, handle_start
from bot.core.func_utils import clean_up, new_task
from bot.modules.up_posts import upcoming_animes

# ----------------------
# /start command handler
# ----------------------
@bot.on_message(filters.command("start"))
async def start(client, message):
    if len(message.command) > 1:
        start_payload = message.text.split(" ", 1)[1]
        try:
            # Decode Base64 safely
            padded = start_payload + '=' * (-len(start_payload) % 4)
            decoded_payload = base64.urlsafe_b64decode(padded).decode()
        except Exception:
            await message.reply("Input Link is Invalid for Usage !")
            return

        # Call handle_start function from auto_animes
        await handle_start(client, message, decoded_payload)

    else:
        await message.reply("Hello! Use the button to get your file.")

# ----------------------
# Restart command
# ----------------------
@bot.on_message(command('restart') & user(Var.ADMINS))
@new_task
async def restart_cmd(client, message):
    rmessage = await message.reply('<i>Restarting...</i>')
    if sch.running:
        sch.shutdown(wait=False)
    await clean_up()
    if len(ffpids_cache) != 0: 
        for pid in ffpids_cache:
            try:
                LOGS.info(f"Process ID : {pid}")
                kill(pid, SIGKILL)
            except (OSError, ProcessLookupError):
                LOGS.error("Killing Process Failed !!")
                continue
    await (await create_subprocess_exec('python3', 'update.py')).wait()
    async with aiopen(".restartmsg", "w") as f:
        await f.write(f"{rmessage.chat.id}\n{rmessage.id}\n")
    execl(executable, executable, "-m", "bot")

# ----------------------
# Post-restart handler
# ----------------------
async def restart():
    if ospath.isfile(".restartmsg"):
        with open(".restartmsg") as f:
            chat_id, msg_id = map(int, f)
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text="<i>Restarted !</i>")
        except Exception as e:
            LOGS.error(e)

# ----------------------
# FF queue loop
# ----------------------
async def queue_loop():
    LOGS.info("Queue Loop Started !!")
    while True:
        if not ffQueue.empty():
            post_id = await ffQueue.get()
            await asleep(1.5)
            ff_queued[post_id].set()
            await asleep(1.5)
            async with ffLock:
                ffQueue.task_done()
        await asleep(10)

# ----------------------
# Main function
# ----------------------
async def main():
    sch.add_job(upcoming_animes, "cron", hour=0, minute=30)
    await bot.start()
    await restart()
    LOGS.info('Auto Anime Bot Started!')
    sch.start()
    bot_loop.create_task(queue_loop())
    await fetch_animes()
    await idle()
    LOGS.info('Auto Anime Bot Stopped!')
    await bot.stop()
    for task in all_tasks:
        task.cancel()
    await clean_up()
    LOGS.info('Finished AutoCleanUp !!')

# ----------------------
# Entry point
# ----------------------
if __name__ == '__main__':
    bot_loop.run_until_complete(main())
