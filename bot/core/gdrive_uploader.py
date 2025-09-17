import os
import base64
from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive
from bot.core.reporter import rep
from traceback import format_exc
from os import path as ospath
from bot import Var

SERVICE_JSON_ENV = "GDRIVE_SERVICE_B64"  # Heroku config var name
FOLDER_ENV = "DRIVE_FOLDER_ID"           # Heroku config var name

def gdrive_auth():
    try:
        gauth = GoogleAuth()

        # Get base64 service account from env
        service_b64 = os.environ.get(SERVICE_JSON_ENV)
        if not service_b64:
            raise Exception("❌ GDRIVE_SERVICE_B64 not found in environment")

        # Decode bytes (no UTF-8 decode!)
        service_bytes = base64.b64decode(service_b64)

        # Save temporarily
        with open("service.json", "wb") as f:
            f.write(service_bytes)

        # Authenticate using service account JSON
        gauth.ServiceAuth(client_json="service.json")
        drive = GoogleDrive(gauth)
        return drive

    except Exception as e:
        raise Exception(f"❌ GDrive Auth Failed: {str(e)}")


async def upload_file(file_path):
    try:
        drive = gdrive_auth()
        folder_id = os.environ.get(FOLDER_ENV) or getattr(Var, "DRIVE_FOLDER_ID", None)
        if not folder_id:
            raise Exception("❌ DRIVE_FOLDER_ID not set")

        if not filename:
            filename = ospath.basename(file_path)

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


async def upload_to_drive(file_path):
    filename = ospath.basename(file_path)
    return await upload_file(file_path, filename)
