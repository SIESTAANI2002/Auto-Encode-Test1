from asyncio import create_task, all_tasks, sleep as asleep
from aiofiles import open as aiopen
from pyrogram import idle
from pyrogram.filters import command, user
from os import execl, kill, path as ospath
from sys import executable
from signal import SIGKILL

from bot import bot, Var, bot_loop, sch, LOGS, ffQueue, ffLock, ff_queued, ffpids_cache
from bot.core.auto_animes import fetch_animes
from bot.core.func_utils import clean_up, new_task
from bot.modules.up_posts import upcoming_animes

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
            except:
                continue
    await (await create_task('python3 update.py')).wait()
    async with aiopen(".restartmsg", "w") as f:
        await f.write(f"{rmessage.chat.id}\n{rmessage.id}\n")
    execl(executable, executable, "-m", "bot")

async def restart():
    if ospath.isfile(".restartmsg"):
        with open(".restartmsg") as f:
            chat_id, msg_id = map(int, f)
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text="<i>Restarted !</i>")
        except:
            pass

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
    for task in all_tasks():
        task.cancel()
    await clean_up()
    LOGS.info('Finished AutoCleanUp !!')

if __name__ == '__main__':
    import threading
    from web import run_web
    threading.Thread(target=run_web, daemon=True).start()
    bot_loop.run_until_complete(main())
