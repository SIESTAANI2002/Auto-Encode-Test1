import os
import pickle
from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive
from bot.core.reporter import rep
from traceback import format_exc


def gdrive_auth():
    try:
        gauth = GoogleAuth()

        # Load service account pickle
        if not os.path.exists("token.pickle"):
            raise Exception("❌ token.pickle not found in bot directory")

        with open("token.pickle", "rb") as f:
            gauth.credentials = pickle.load(f)

        drive = GoogleDrive(gauth)
        return drive

    except Exception as e:
        raise Exception(f"❌ GDrive Auth Failed: {str(e)}")


async def upload_file(file_path, filename, folder_id=None):
    try:
        drive = gdrive_auth()
        # Priority: passed folder_id > ENV > Var.DRIVE_FOLDER_ID
        folder_id = (
            folder_id
            or os.environ.get("DRIVE_FOLDER_ID")
            or getattr(__import__("bot").Var, "DRIVE_FOLDER_ID", None)
        )

        if not folder_id:
            raise Exception("❌ DRIVE_FOLDER_ID not set")

        file = drive.CreateFile({
            "title": filename,
            "parents": [{"id": folder_id}]
        })
        file.SetContentFile(file_path)
        file.Upload()
        return f"https://drive.google.com/uc?id={file['id']}"

    except Exception as e:
        await rep.report(format_exc(), "error")
        raise e


async def upload_to_drive(file_path, folder_id=None):
    filename = os.path.basename(file_path)
    return await upload_file(file_path, filename, folder_id)
