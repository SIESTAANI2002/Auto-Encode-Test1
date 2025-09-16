import os
from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive
from bot import Var
from .reporter import rep

def gdrive_auth():
    try:
        gauth = GoogleAuth()

        # Load credentials and token from repo files
        gauth.LoadClientConfigFile("bot/credentials.json")
        gauth.LoadCredentialsFile("bot/token.pickle")

        # Refresh or authorize if needed
        if gauth.access_token_expired:
            gauth.Refresh()
        else:
            gauth.Authorize()

        return GoogleDrive(gauth)

    except Exception as e:
        raise Exception(f"❌ GDrive Auth Failed: {str(e)}")


async def upload_to_drive(file_path: str, folder_id: str = None):
    try:
        drive = gdrive_auth()
        folder_id = folder_id or Var.DRIVE_FOLDER_ID

        file_name = os.path.basename(file_path)
        gfile = drive.CreateFile({
            "title": file_name,
            "parents": [{"id": folder_id}]
        })
        gfile.SetContentFile(file_path)
        gfile.Upload()

        file_link = f"https://drive.google.com/file/d/{gfile['id']}/view"
        await rep.report(f"[INFO] File Uploaded to Drive: {file_link}", "info")

        # Remove local file after upload
        if os.path.exists(file_path):
            os.remove(file_path)

        return file_link

    except Exception as e:
        await rep.report(f"[ERROR] GDrive Upload Failed\n{str(e)}", "error")
        raise
