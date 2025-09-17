import os
from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive
from oauth2client.service_account import ServiceAccountCredentials
from bot.core.reporter import rep
from traceback import format_exc

SERVICE_ACCOUNT_FILE = "service_account.json"  # Place this in bot root

def gdrive_auth():
    try:
        if not os.path.exists(SERVICE_ACCOUNT_FILE):
            raise Exception("❌ service_account.json not found in bot directory")

        # Define scopes
        scopes = ['https://www.googleapis.com/auth/drive']

        # Load credentials from service account
        credentials = ServiceAccountCredentials.from_json_keyfile_name(
            SERVICE_ACCOUNT_FILE, scopes=scopes
        )

        # Authenticate with PyDrive
        gauth = GoogleAuth()
        gauth.credentials = credentials
        drive = GoogleDrive(gauth)
        return drive

    except Exception as e:
        raise Exception(f"❌ GDrive Auth Failed: {str(e)}")


async def upload_file(file_path, filename, folder_id=None):
    try:
        drive = gdrive_auth()

        # Use folder ID from environment or Var
        if folder_id is None:
            folder_id = os.environ.get("DRIVE_FOLDER_ID") or getattr(__import__("bot").Var, "DRIVE_FOLDER_ID", None)
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
