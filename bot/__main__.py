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
from bot.core.database import db

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
    """
    Handles clicks on inline buttons (1080p/720p).
    First click -> send file with protect_content=True, mark in DB.
    Second click -> send website link instead.
    """
    data = callback_query.data
    if data.startswith("sendfile|"):
        try:
            _, ani_id, ep, qual, msg_id = data.split("|")
            user_id = callback_query.from_user.id
            ep = int(ep)
            msg_id = int(msg_id)

            already = await db.hasUserReceived(ani_id, ep, qual, user_id)
            anime = await db.getAnime(ani_id)
            main_msg_id = anime.get("msg_id")

            if not main_msg_id:
                return await callback_query.answer("File not found!", show_alert=True)

            if already:
                # send website link instead
                link = f"{Var.WEBSITE_URL}/anime/{ani_id}/ep{ep}"
                await callback_query.message.reply(
                    f"🔗 You already received this file.\nHere’s the website link: {link}"
                )
            else:
                # copy/forward file to user with protect_content=True
                try:
                    await bot.copy_message(
                        chat_id=user_id,
                        from_chat_id=Var.MAIN_CHANNEL,
                        message_id=msg_id,
                        protect_content=True
                    )
                    await db.markUserReceived(ani_id, ep, qual, user_id)

                    # Info message with deletion
                    if Var.AUTO_DEL == "True":
                        info_msg = await callback_query.message.reply(
                            f"✅ File delivered. It will be auto-deleted in {Var.DEL_TIMER} seconds."
                        )
                        # Auto-delete after DEL_TIMER seconds
                        create_task(auto_delete_message(info_msg.chat.id, info_msg.id, int(Var.DEL_TIMER)))
                    await callback_query.answer("✅ File sent!", show_alert=True)
                except Exception as e:
                    await callback_query.answer(f"Error sending file: {e}", show_alert=True)

        except Exception as e:
            await callback_query.answer(f"Error: {e}", show_alert=True)


async def auto_delete_message(chat_id, msg_id, delay):
    await asleep(delay)
    try:
        await bot.delete_messages(chat_id, msg_id)
    except Exception:
        pass


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
