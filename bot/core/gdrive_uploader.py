import os
import base64
from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive
from bot.core.reporter import rep
from bot import Var
from traceback import format_exc

SERVICE_JSON_ENV = "GDRIVE_SERVICE_B64"  # Heroku env var
FOLDER_ID_ENV = "DRIVE_FOLDER_ID"

def gdrive_auth():
    try:
        gauth = GoogleAuth()

        # Decode service account JSON from env
        service_json_b64 = os.environ.get(SERVICE_JSON_ENV)
        if not service_json_b64:
            raise Exception("❌ GDRIVE_SERVICE_B64 not found in environment")

        service_json_content = base64.b64decode(service_json_b64).decode()

        # Write temp file for auth
        with open("service.json", "w") as f:
            f.write(service_json_content)

        # Authenticate using service account JSON
        gauth.ServiceAuth(client_json="service.json")
        drive = GoogleDrive(gauth)

        # Clean up temp file (optional)
        os.remove("service.json")

        return drive

    except Exception as e:
        raise Exception(f"❌ GDrive Auth Failed: {str(e)}")


async def upload_file(file_path, filename=None):
    try:
        drive = gdrive_auth()
        folder_id = os.environ.get(FOLDER_ID_ENV) or getattr(Var, "DRIVE_FOLDER_ID", None)
        if not folder_id:
            raise Exception("❌ DRIVE_FOLDER_ID not set")

        if filename is None:
            filename = os.path.basename(file_path)

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


async def upload_to_drive(file_path, filename=None):
    return await upload_file(file_path, filename)
