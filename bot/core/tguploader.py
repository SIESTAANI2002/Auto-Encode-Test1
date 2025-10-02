# bot/core/tguploader.py
from time import time, sleep
from traceback import format_exc
from math import floor
from os import path as ospath
from pyrogram.errors import FloodWait

from bot import bot, Var
from .func_utils import editMessage, convertBytes, convertTime
from .reporter import rep
from .gdrive_uploader import upload_to_drive  # ✅ optional Drive backup

class TgUploader:
    def __init__(self, status_msg):
        self.cancelled = False
        self.status_msg = status_msg
        self.__name = ""
        self.__qual = ""
        self.__client = bot
        self.__start = time()
        self.__updater = time()

    async def upload(self, path, qual, **kwargs):
        """
        Upload file to Telegram FILE_STORE and return the sent message.
        """
        self.__name = ospath.basename(path)
        self.__qual = qual
        try:
            if Var.AS_DOC:
                msg = await self.__client.send_document(
                    chat_id=Var.FILE_STORE,
                    document=path,
                    thumb="thumb.jpg" if ospath.exists("thumb.jpg") else None,
                    caption=f"<i>{self.__name}</i>",
                    force_document=True,
                    progress=self.progress_status,
                    **kwargs
                )
            else:
                msg = await self.__client.send_video(
                    chat_id=Var.FILE_STORE,
                    video=path,
                    thumb="thumb.jpg" if ospath.exists("thumb.jpg") else None,
                    caption=f"<i>{self.__name}</i>",
                    progress=self.progress_status,
                    **kwargs
                )

            await rep.report(f"[INFO] ✅ Successfully Uploaded {self.__name} to Telegram", "info")

            # Optional: upload to Google Drive
            if hasattr(Var, "BACKUP_DRIVE") and Var.BACKUP_DRIVE:
                drive_link = await upload_to_drive(path)
                if drive_link:
                    await self.__client.send_message(
                        chat_id=Var.LOG_CHANNEL,
                        text=f"✅ <b>{self.__name}</b> also uploaded to Google Drive\n🔗 {drive_link}"
                    )

            return msg  # ✅ Return message to get msg_id

        except FloodWait as e:
            sleep(e.value * 1.5)
            return await self.upload(path, qual, **kwargs)
        except Exception as e:
            await rep.report(format_exc(), "error")
            raise e

    async def progress_status(self, current, total):
        if self.cancelled:
            self.__client.stop_transmission()
        now = time()
        diff = now - self.__start
        if (now - self.__updater) >= 7 or current == total:
            self.__updater = now
            percent = round(current / total * 100, 2)
            speed = current / diff if diff > 0 else 0
            eta = round((total - current) / speed) if speed > 0 else 0
            bar = floor(percent / 8) * "█" + (12 - floor(percent / 8)) * "▒"
            progress_str = f"""‣ <b>Anime Name :</b> <b><i>{self.__name}</i></b>

‣ <b>Status :</b> <i>Uploading</i>
    <code>[{bar}]</code> {percent}%
    
    ‣ <b>Size :</b> {convertBytes(current)} / {convertBytes(total)}
    ‣ <b>Speed :</b> {convertBytes(speed)}/s
    ‣ <b>Time Taken :</b> {convertTime(diff)}
    ‣ <b>ETA :</b> {convertTime(eta)}

‣ <b>File(s) Encoded:</b> <code>{Var.QUALS.index(self.__qual)+1}/{len(Var.QUALS)}</code>"""
            await editMessage(self.status_msg, progress_str)
