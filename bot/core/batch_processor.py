import os
import re
import subprocess
import feedparser
import logging
import sys

# -------------------------------
# Set up imports for repo structure
# -------------------------------
# bot/core/ contains tordownload.py and Gdrive_upload.py
sys.path.append(os.path.abspath(os.path.dirname(__file__)))
import tordownload
import Gdrive_upload

# Repo root contains config.py
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))
from config import config  # Uses RSS_TOR, DOWNLOAD_PATH, DRIVE_FOLDER_ID

# -------------------------------
# Logging setup
# -------------------------------
logging.basicConfig(
    filename='batch_process.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def log(msg):
    print(msg)
    logging.info(msg)

# -------------------------------
# Scan batch folder for videos
# -------------------------------
def scan_batch_folder(folder_path, video_extensions=None):
    if video_extensions is None:
        video_extensions = ['.mkv', '.mp4', '.avi']
    video_files = []
    for root, _, files in os.walk(folder_path):
        for f in files:
            if any(f.lower().endswith(ext) for ext in video_extensions):
                video_files.append(os.path.join(root, f))
    return video_files

# -------------------------------
# Rename files: [EMBER] -> [AnimeToki]
# -------------------------------
def rename_file(original_path):
    folder, filename = os.path.split(original_path)
    match = re.match(r"\[(.*?)\]\s*(\d+)-\s*(.*)", filename)
    if match:
        _, episode, rest_name = match.groups()
        new_tag = "AnimeToki"
        new_filename = f"[{new_tag}] {episode} - {rest_name}"
        new_path = os.path.join(folder, new_filename)
        os.rename(original_path, new_path)
        log(f"Renamed: {filename} → {new_filename}")
        return new_path
    return original_path

def rename_files(file_list):
    renamed_files = []
    for f in file_list:
        renamed_files.append(rename_file(f))
    return renamed_files

# -------------------------------
# Update metadata via FFmpeg
# -------------------------------
def update_metadata(file_path, title=None, show=None, season=None, episode=None):
    cmd = ["ffmpeg", "-i", file_path, "-c", "copy"]

    if title:
        cmd += ["-metadata", f"title={title}"]
    if show:
        cmd += ["-metadata", f"show={show}"]
    if season:
        cmd += ["-metadata", f"season_number={season}"]
    if episode:
        cmd += ["-metadata", f"episode_id={episode}"]

    temp_file = file_path + ".tmp.mkv"
    cmd.append(temp_file)

    subprocess.run(cmd, shell=False)
    os.replace(temp_file, file_path)
    log(f"Updated metadata: {os.path.basename(file_path)}")

# -------------------------------
# Fetch RSS and download using tordownload.py
# -------------------------------
def fetch_and_download_rss(rss_url, download_folder):
    feed = feedparser.parse(rss_url)
    os.makedirs(download_folder, exist_ok=True)

    for entry in feed.entries:
        video_url = entry.link
        title = entry.title
        filename = f"{title}.mkv"
        file_path = os.path.join(download_folder, filename)

        if os.path.exists(file_path):
            log(f"Skipped (already exists): {filename}")
            continue

        log(f"Downloading: {filename}")
        tordownload.download_video(video_url, file_path)
        log(f"Downloaded: {filename}")

# -------------------------------
# Full RSS → Drive batch processing
# -------------------------------
def process_rss_to_drive():
    rss_url = config["RSS_TOR"]                  # RSS feed from config
    download_folder = config["DOWNLOAD_PATH"]   # Download folder from config
    drive_folder_id = config.get("DRIVE_FOLDER_ID")  # Optional Drive folder ID

    log("=== Starting batch process ===")
    fetch_and_download_rss(rss_url, download_folder)

    log("Scanning folder for videos...")
    files = scan_batch_folder(download_folder)
    log(f"Found {len(files)} files.")

    log("Renaming files...")
    files = rename_files(files)

    log("Updating metadata...")
    for f in files:
        match = re.search(r"\[(.*?)\]\s*(\d+)\s*-\s*(.*)", os.path.basename(f))
        if match:
            _, ep_num, title = match.groups()
            update_metadata(f, title=title, show="AnimeToki", season=1, episode=ep_num)

    log("Uploading files to Google Drive...")
    for f in files:
        Gdrive_upload.upload_file(f, drive_folder_id)

    log("=== Batch processing completed! ===")

# -------------------------------
# Run the process
# -------------------------------
if __name__ == "__main__":
    process_rss_to_drive()
