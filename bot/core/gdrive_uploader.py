import os
import json
from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive
from bot import LOGS, Var

def gdrive_auth():
    try:
        gauth = GoogleAuth()

        # Load client secrets from env var
        if "GDRIVE_CREDS" in os.environ:
            creds_json = json.loads(os.environ["GDRIVE_CREDS"])
            with open("credentials.json", "w") as f:
                json.dump(creds_json, f)

        # Load token.json from env var if exists
        if "GDRIVE_TOKEN" in os.environ:
            token_json = json.loads(os.environ["GDRIVE_TOKEN"])
            with open("token.json", "w") as f:
                json.dump(token_json, f)

        # Authenticate
        gauth.LoadCredentialsFile("token.json")
        if gauth.credentials is None:
            gauth.LoadClientConfigFile("credentials.json")
            gauth.LocalWebserverAuth()
        elif gauth.access_token_expired:
            gauth.Refresh()
        else:
            gauth.Authorize()

        gauth.SaveCredentialsFile("token.json")
        return GoogleDrive(gauth)

    except Exception as e:
        raise Exception(f"❌ GDrive Auth Failed: {str(e)}")


async def upload_file(file_path, filename=None):
    drive = gdrive_auth()
    if not filename:
        filename = os.path.basename(file_path)

    try:
        f = drive.CreateFile({
            "title": filename,
            "parents": [{"id": Var.DRIVE_FOLDER_ID}]
        })
        f.SetContentFile(file_path)
        f.Upload()
        link = f"https://drive.google.com/file/d/{f['id']}/view"
        LOGS.info(f"✅ Uploaded to GDrive: {filename}")
        return link
    except Exception as e:
        LOGS.error(f"GDrive upload failed: {filename} | {str(e)}")
        return None


async def upload_to_drive(file_path, filename=None):
    return await upload_file(file_path, filename)
