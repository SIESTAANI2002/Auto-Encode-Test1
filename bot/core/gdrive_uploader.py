import os
import json
from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive
from bot.core.reporter import rep
from traceback import format_exc
from io import BytesIO

def gdrive_auth():
    try:
        gauth = GoogleAuth()

        # Get JSON from Heroku config
        sa_json = os.environ.get("SERVICE_ACCOUNT_JSON")
        if not sa_json:
            raise Exception("❌ SERVICE_ACCOUNT_JSON not set in Heroku Config Vars")

        # Load credentials from JSON string
        gauth.LoadServiceAccountCredentials(json.loads(sa_json))
        drive = GoogleDrive(gauth)
        return drive

    except Exception as e:
        raise Exception(f"❌ GDrive Auth Failed: {str(e)}")


async def upload_file(file_path, filename, folder_id=None):
    try:
        drive = gdrive_auth()

        if not folder_id:
            folder_id = os.environ.get("DRIVE_FOLDER_ID")
        if not folder_id:
            raise Exception("❌ DRIVE_FOLDER_ID not set in Heroku Config Vars")

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
