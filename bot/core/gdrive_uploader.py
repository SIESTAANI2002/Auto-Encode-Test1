import os
import asyncio
from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive
from bot import Var, LOGS

# -------------------- Auth -------------------- #
def gdrive_auth():
    gauth = GoogleAuth()

    try:
        # Use credentials.json + token.json
        gauth.LoadClientConfigFile("credentials.json")
        gauth.LoadCredentialsFile("token.json")

        if gauth.credentials is None:
            raise Exception("❌ No credentials found.")
        if gauth.access_token_expired:
            gauth.Refresh()
        else:
            gauth.Authorize()

        gauth.SaveCredentialsFile("token.json")
        LOGS.info("✅ GDrive Authentication Success")
        return GoogleDrive(gauth)

    except Exception as e:
        raise Exception(f"❌ GDrive Auth Failed: {str(e)}")


# -------------------- Upload -------------------- #
async def upload_to_drive(file_path, filename=None):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _upload_worker, file_path, filename)


def _upload_worker(file_path, filename=None):
    try:
        drive = gdrive_auth()
        folder_id = getattr(Var, "DRIVE_FOLDER_ID", None)

        if not filename:
            filename = os.path.basename(file_path)

        file_drive = drive.CreateFile({
            "title": filename,
            "parents": [{"id": folder_id}] if folder_id else []
        })
        file_drive.SetContentFile(file_path)
        file_drive.Upload()

        link = f"https://drive.google.com/file/d/{file_drive['id']}/view?usp=drivesdk"
        LOGS.info(f"✅ Uploaded to GDrive: {filename}")
        return link

    except Exception as e:
        LOGS.error(f"[ERROR] GDrive upload failed: {str(e)}")
        raise
