from json import loads as jloads
from os import path as ospath, execl
from sys import executable
from aiohttp import ClientSession
from bot import Var, bot, ffQueue
from bot.core.text_utils import TextEditor
from bot.core.reporter import rep
from bot.core import tguploader, gdrive_uploader  # Added

import os

# ==============================
# Existing functions
# ==============================
async def upcoming_animes():
    if Var.SEND_SCHEDULE:
        try:
            async with ClientSession() as ses:
                res = await ses.get("https://subsplease.org/api/?f=schedule&h=true&tz=Asia/Kolkata")
                aniContent = jloads(await res.text())["schedule"]
            text = "<b>📆 Today's Anime Releases Schedule [IST]</b>\n\n"
            for i in aniContent:
                aname = TextEditor(i["title"])
                await aname.load_anilist()
                text += f''' <a href="https://subsplease.org/shows/{i['page']}">{aname.adata.get('title', {}).get('english') or i['title']}</a>\n    • <b>Time</b> : {i["time"]} hrs\n\n'''
            TD_SCHR = await bot.send_message(Var.MAIN_CHANNEL, text)
            await (await TD_SCHR.pin()).delete()
        except Exception as err:
            await rep.report(str(err), "error")
    if not ffQueue.empty():
        await ffQueue.join()
    await rep.report("Auto Restarting..!!", "info")
    execl(executable, executable, "-m", "bot")

async def update_shdr(name, link):
    if TD_SCHR is not None:
        TD_lines = TD_SCHR.text.split('\n')
        for i, line in enumerate(TD_lines):
            if line.startswith(f"📌 {name}"):
                TD_lines[i+2] = f"    • **Status :** ✅ __Uploaded__\n    • **Link :** {link}"
        await TD_SCHR.edit("\n".join(TD_lines))

# ==============================
# New function: Upload to Telegram + Google Drive
# ==============================
async def upload_post(file_path, tg_chat_id=None, drive_folder_id=None):
    """
    Uploads a file to Telegram and Google Drive.
    Does not touch auto/manual encode scripts.
    """
    # 1️⃣ Upload to Telegram
    if tg_chat_id:
        await tguploader.upload_file(file_path, chat_id=tg_chat_id)
        print(f"[Telegram] Uploaded: {os.path.basename(file_path)}")

    # 2️⃣ Upload to Google Drive
    if drive_folder_id:
        drive_file_id = gdrive_uploader.upload_file(file_path, folder_id=drive_folder_id)
        print(f"[GDrive] Uploaded: {os.path.basename(file_path)} (ID: {drive_file_id})")
