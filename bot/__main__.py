# main.py
from asyncio import create_task, create_subprocess_exec, all_tasks, sleep as asleep
from aiofiles import open as aiopen
from pyrogram import idle
from pyrogram.filters import command, user
from pyrogram.types import CallbackQuery
from os import path as ospath, execl, kill
from sys import executable
from signal import SIGKILL

from bot import bot, Var, bot_loop, sch, LOGS, ffQueue, ffLock, ffpids_cache, ff_queued
from bot.core.auto_animes import fetch_animes
from bot.core.func_utils import clean_up, new_task
from bot.modules.up_posts import upcoming_animes
from bot.core.database import db  # ensure db import here (no circular import with auto_animes)

# ------------------ Restart command ------------------
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

async def restart():
    if ospath.isfile(".restartmsg"):
        with open(".restartmsg") as f:
            chat_id, msg_id = map(int, f)
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text="<i>Restarted !</i>")
        except Exception as e:
            LOGS.error(e)


# ---------------- Inline Button Handler ----------------
@bot.on_callback_query()
async def inline_button_handler(client, callback_query: CallbackQuery):
    data = callback_query.data or ""
    if not data:
        return await callback_query.answer()

    if data.startswith("sendfile|"):
        # format: sendfile|{ani_id}|{ep}|{qual}|{msg_id}
        parts = data.split("|")
        if len(parts) != 5:
            return await callback_query.answer("Invalid button data.", show_alert=True)
        _, ani_id, ep, qual, msg_id = parts
        try:
            ep = int(ep)
            msg_id = int(msg_id)
        except Exception:
            return await callback_query.answer("Invalid episode or message id.", show_alert=True)

        # forward to handler in auto_animes.py
        await handle_file_click(callback_query, ani_id, ep, qual, msg_id)

@bot.on_message(filters.private & filters.command("start"))
async def start_handler(client, message):
    if message.text.startswith("/start autofile-"):
        await handle_autofile_start(client, message)
    else:
        await message.reply_text("Welcome! Start using the bot via links.")

# ------------------ Queue loop ------------------
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

# ------------------ Main ------------------
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

if __name__ == '__main__':
    import threading
    from web import run_web

    # Start the web server in a background thread (for Koyeb health check)
    threading.Thread(target=run_web, daemon=True).start()

    # Start the bot loop
    bot_loop.run_until_complete(main())
