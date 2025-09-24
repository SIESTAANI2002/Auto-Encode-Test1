import asyncio
import feedparser
import os
from bot import Var, LOGS, bot_loop
from bot.core.tordownload import TorDownloader
from bot.core.gdrive_uploader import upload_to_drive
from bot.core.ffencoder import FFEncoder
from bot.core.reporter import rep

async def start_task():
    LOGS.info("🚀 RSS Torrent Task Started!")
    await rep.report("🚀 RSS Torrent Task Started!", "info")

    while True:
        try:
            for rss_url in Var.RSS_TOR:
                LOGS.info(f"📡 Checking RSS Feed: {rss_url}")
                await rep.report(f"📡 Checking RSS Feed: {rss_url}", "info")

                feed = feedparser.parse(rss_url)
                entries = feed.entries[:3]  # latest 3 torrents
                LOGS.info(f"📥 Found {len(entries)} items in feed")
                await rep.report(f"📥 Found {len(entries)} items in feed", "info")

                for entry in entries:
                    title = entry.title
                    LOGS.info(f"🔗 Found Torrent: {title}")
                    await rep.report(f"🔗 Found Torrent: {title}", "info")

                    tor = TorDownloader()
                    msg_id = await rep.report(f"⬇️ Starting download: {title}", "info")
                    dl_task = asyncio.create_task(tor.download(entry.link, title))

                    # Download progress loop
                    while not dl_task.done():
                        try:
                            # Replace this with real percentage if TorDownloader supports
                            prog = f"⬇️ Downloading {title} …"
                            await rep.update_report(msg_id, prog)
                        except Exception:
                            pass
                        await asyncio.sleep(10)

                    dl_path = await dl_task
                    if not dl_path:
                        err = f"❌ Torrent download failed: {title}"
                        LOGS.error(err)
                        await rep.report(err, "error")
                        continue

                    # Metadata update / rename
                    new_name = f"[{Var.SECOND_BRAND}] {title} Dual Audio.mkv"
                    new_path = os.path.join("downloads", new_name)

                    # Optional metadata-only encoding (FFEncoder) before rename
                    ff = FFEncoder(message=msg_id, path=dl_path, name=new_name, qual=Var.QUALS[0])
                    encoded_path = await ff.start_encode() or dl_path
                    os.rename(encoded_path, new_path)

                    msg = f"📂 Renamed to: {new_name}"
                    LOGS.info(msg)
                    await rep.update_report(msg_id, msg)

                    # Upload to Google Drive with live TG updates
                    upload_msg_id = await rep.report(f"☁️ Uploading: {new_name}", "info")
                    upload_task = asyncio.create_task(upload_to_drive(new_path))

                    while not upload_task.done():
                        try:
                            await rep.update_report(upload_msg_id, f"☁️ Uploading {new_name} …")
                        except Exception:
                            pass
                        await asyncio.sleep(10)

                    gdrive_link = await upload_task
                    msg = f"✅ Uploaded: {gdrive_link}"
                    LOGS.info(msg)
                    await rep.update_report(upload_msg_id, msg)

                    # Auto-delete local file
                    if Var.AUTO_DEL:
                        os.remove(new_path)
                        msg = f"🗑️ Deleted local file: {new_name}"
                        LOGS.info(msg)
                        await rep.report(msg, "info")

        except Exception as e:
            err = f"⚠️ Error in RSS Torrent Loop: {str(e)}"
            LOGS.error(err)
            await rep.report(err, "error")

        await asyncio.sleep(60)  # check feed every 60s
