import os
import base64
from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive
from bot import Var, rep
from traceback import format_exc

SERVICE_JSON_ENV = "GDRIVE_SERVICE_B64"  # Heroku config var name

def gdrive_auth():
    try:
        gauth = GoogleAuth()

        # Decode service account JSON from env
        service_json_b64 = os.environ.get(SERVICE_JSON_ENV)
        if not service_json_b64:
            raise Exception("❌ GDRIVE_SERVICE_JSON not found in environment")

        service_json_content = base64.b64decode(service_json_b64).decode()

        # Save temporarily
        with open("service.json", "w") as f:
            f.write(service_json_content)

        # Authenticate using service account
        gauth.ServiceAuth()  # No arguments
        drive = GoogleDrive(gauth)
        return drive

    except Exception as e:
        raise Exception(f"❌ GDrive Auth Failed: {str(e)}")


async def upload_file(file_path, filename):
    try:
        drive = gdrive_auth()
        folder_id = os.environ.get("DRIVE_FOLDER_ID") or Var.DRIVE_FOLDER_ID

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


async def upload_to_drive(file_path):
    filename = os.path.basename(file_path)
    return await upload_file(file_path, filename)
