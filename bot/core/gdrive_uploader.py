# gdrive_uploader.py
import os
import io
import base64
from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive
from bot import Var, rep

# Decode Base64 service account and save temporarily
def get_service_account_file():
    try:
        service_b64 = os.environ.get("SERVICE_JSON_B64")
        if not service_b64:
            raise Exception("SERVICE_JSON_B64 not set in environment variables")
        data = base64.b64decode(service_b64)
        with open("sa_temp.json", "wb") as f:
            f.write(data)
        return "sa_temp.json"
    except Exception as e:
        rep.report(f"❌ GDrive Service Account Error: {str(e)}", "error")
        raise e

# Authenticate with service account
def gdrive_auth():
    try:
        sa_file = get_service_account_file()
        gauth = GoogleAuth()
        gauth.ServiceAuth(sa_file)
        drive = GoogleDrive(gauth)
        return drive
    except Exception as e:
        raise Exception(f"❌ GDrive Auth Failed: {str(e)}")

# Upload file
async def upload_to_drive(file_path, folder_id=None):
    try:
        drive = gdrive_auth()
        file_name = os.path.basename(file_path)
        gfile = drive.CreateFile({
            "title": file_name,
            "parents": [{"id": folder_id or Var.DRIVE_FOLDER_ID}]
        })
        gfile.SetContentFile(file_path)
        gfile.Upload()
        # Optional: get sharable link
        gfile.InsertPermission({
            'type': 'anyone',
            'value': 'anyone',
            'role': 'reader'
        })
        return gfile['alternateLink']
    except Exception as e:
        await rep.report(f"❌ GDrive Upload Failed for {file_path}: {str(e)}", "error")
        return None
