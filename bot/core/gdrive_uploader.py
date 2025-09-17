import os
import json
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

from bot import LOGS, Var

# Google Drive Scope
SCOPES = ["https://www.googleapis.com/auth/drive.file"]

def gdrive_auth():
    creds = None
    try:
        # ✅ Option 1: Load from Heroku Config Var
        if "GDRIVE_TOKEN" in os.environ:
            creds_json = json.loads(os.environ["GDRIVE_TOKEN"])
            creds = Credentials.from_authorized_user_info(creds_json, SCOPES)

        # ✅ Option 2: Load from token.json file
        elif os.path.exists("token.json"):
            creds = Credentials.from_authorized_user_file("token.json", SCOPES)

        else:
            raise Exception("❌ No token found. Provide GDRIVE_TOKEN env var or token.json file")

        # Refresh expired token
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())

    except Exception as e:
        raise Exception(f"❌ GDrive Auth Failed: {str(e)}")

    return creds


async def upload_file(file_path, filename=None):
    """ Upload file to Google Drive """
    creds = gdrive_auth()
    service = build("drive", "v3", credentials=creds)

    if not filename:
        filename = os.path.basename(file_path)

    file_metadata = {
        "name": filename,
        "parents": [Var.DRIVE_FOLDER_ID] if hasattr(Var, "DRIVE_FOLDER_ID") else []
    }

    media = MediaFileUpload(file_path, resumable=True)

    try:
        request = service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id, webViewLink"
        )
        file = request.execute()

        file_id = file.get("id")
        link = file.get("webViewLink")

        LOGS.info(f"GDrive Upload Success: {filename} ({link})")
        return link

    except Exception as e:
        LOGS.error(f"GDrive upload failed for {filename}: {str(e)}")
        raise Exception(f"GDrive upload failed: {str(e)}")
