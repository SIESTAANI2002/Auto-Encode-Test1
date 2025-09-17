import os
from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive
from oauth2client.service_account import ServiceAccountCredentials
from bot.core.reporter import rep
from traceback import format_exc

def gdrive_auth():
    try:
        # Scopes for full Drive access
        scopes = ['https://www.googleapis.com/auth/drive']

        # Load service account JSON
        json_path = os.path.join(os.getcwd(), "service_account.json")
        if not os.path.exists(json_path):
            raise Exception("❌ service_account.json not found in bot directory")

        credentials = ServiceAccountCredentials.from_json_keyfile_name(json_path, scopes)
        gauth = GoogleAuth()
        gauth.credentials = credentials
        drive = GoogleDrive(gauth)
        return drive

    except Exception as e:
        raise Exception(f"❌ GDrive Auth Failed: {str(e)}")


async def upload_file(file_path, filename):
    try:
        drive = gdrive_auth()
        # Use environment variable first, fallback to Var
        folder_id = os.environ.get("DRIVE_FOLDER_ID") or getattr(__import__("bot").Var, "DRIVE_FOLDER_ID", None)

        if not folder_id:
            raise Exception("❌ DRIVE_FOLDER_ID not set")

        file = drive.CreateFile({
            "title": filename,
            "parents": [{"id": folder_id}]  # For shared drive upload
        })
        file.SetContentFile(file_path)
        file.Upload()
        return f"https://drive.google.com/uc?id={file['id']}"

    except Exception as e:
        await rep.report(format_exc(), "error")
        raise e


async def upload_to_drive(file_path):
    filename = os.path.basename(file_path)
    return await upload_file(file_path, filename)
