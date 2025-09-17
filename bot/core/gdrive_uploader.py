import os
from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive
from bot import Var, LOGS
from bot.core.reporter import rep
from os import path as ospath

# ---------------- Google Drive Auth ---------------- #
def gdrive_auth():
    gauth = GoogleAuth()

    try:
        # Load saved credentials
        if ospath.exists("token.json"):
            gauth.LoadCredentialsFile("token.json")

        if gauth.credentials is None:
            gauth.LoadClientConfigFile("credentials.json")
            gauth.LocalWebserverAuth()
        elif gauth.access_token_expired:
            gauth.Refresh()
        else:
            gauth.Authorize()

        gauth.SaveCredentialsFile("token.json")
    except Exception as e:
        raise Exception(f"❌ GDrive Auth Failed: {str(e)}")

    return GoogleDrive(gauth)

# ---------------- Upload Function ---------------- #
async def upload_to_drive(path: str) -> str:
    try:
        drive = gdrive_auth()
        filename = ospath.basename(path)

        file = drive.CreateFile({
            "title": filename,
            "parents": [{"id": Var.DRIVE_FOLDER_ID}]
        })

        # Upload with Shared Drive support
        file.Upload(param={'supportsAllDrives': True})

        # Make public
        file.InsertPermission({
            "type": "anyone",
            "value": "anyone",
            "role": "reader"
        })

        LOGS.info(f"GDrive upload successful: {filename}")
        return f"https://drive.google.com/file/d/{file['id']}/view"

    except Exception as e:
        await rep.report(f"❌ GDrive Upload Failed: {str(e)}", "error")
        raise e
