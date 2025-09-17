import os
import base64
from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive
from bot.core.reporter import rep
from traceback import format_exc
from os import path as ospath

SERVICE_JSON_ENV = "GDRIVE_SERVICE_B64"  # Heroku config var name

def gdrive_auth():
    try:
        gauth = GoogleAuth()

        # Decode service account JSON from env
        service_json_b64 = os.environ.get(SERVICE_JSON_ENV)
        if not service_json_b64:
            raise Exception("❌ GDRIVE_SERVICE_JSON not found in environment")

        # Use binary mode decoding to avoid utf-8 errors
        service_json_bytes = base64.b64decode(service_json_b64)

        # Save temporarily
        with open("service.json", "wb") as f:
            f.write(service_json_bytes)

        # Authenticate using service account file
        gauth.ServiceAuth()  # No arguments
        drive = GoogleDrive(gauth)
        return drive

    except Exception as e:
        raise Exception(f"❌ GDrive Auth Failed: {str(e)}")


async def upload_file(file_path, filename):
    try:
        drive = gdrive_auth()
        folder_id = os.environ.get("DRIVE_FOLDER_ID") or getattr(os.environ, "DRIVE_FOLDER_ID", None)

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


# ------------------- Fixed upload_to_drive ------------------- #
async def upload_to_drive(file_path, filename=None):
    if filename is None:
        filename = ospath.basename(file_path)
    return await upload_file(file_path, filename)
