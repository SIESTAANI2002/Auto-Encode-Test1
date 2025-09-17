import os
from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive
from bot.core.reporter import rep
from traceback import format_exc

# -------------------- Google Drive Authentication -------------------- #
def gdrive_auth():
    try:
        gauth = GoogleAuth()
        # Load Service Account JSON
        if not os.path.exists("service_account.json"):
            raise Exception("❌ service_account.json not found in bot directory")

        gauth.LoadServiceConfigFile("service_account.json")
        drive = GoogleDrive(gauth)
        return drive

    except Exception as e:
        raise Exception(f"❌ GDrive Auth Failed: {str(e)}")

# -------------------- Upload File -------------------- #
async def upload_file(file_path, filename):
    try:
        drive = gdrive_auth()
        # Folder ID from environment variable or Var
        folder_id = os.environ.get("DRIVE_FOLDER_ID") or getattr(__import__("bot").Var, "DRIVE_FOLDER_ID", None)

        if not folder_id:
            raise Exception("❌ DRIVE_FOLDER_ID not set")

        file = drive.CreateFile({
            "title": filename,
            "parents": [{"id": folder_id}]  # Shared Drive folder
        })
        file.SetContentFile(file_path)
        file.Upload()
        return f"https://drive.google.com/uc?id={file['id']}"

    except Exception as e:
        await rep.report(format_exc(), "error")
        raise e

# -------------------- Convenience Function -------------------- #
async def upload_to_drive(file_path):
    filename = os.path.basename(file_path)
    return await upload_file(file_path, filename)
