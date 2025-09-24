import asyncio
import feedparser
import os
from bot import Var, LOGS
from bot.core.tordownload import TorDownloader
from bot.core.gdrive_uploader import upload_to_drive
from bot.core.reporter import rep

async def start_task():
    # Startup log
    LOGS.info("🚀 RSS Torrent Task Started!")
    await rep.report("🚀 RSS Torrent Task Started!", "info")

    while True:
        try:
            for rss_url in Var.RSS_TOR:
                # Feed check log
                msg = f"📡 Checking RSS Feed: {rss_url}"
                LOGS.info(msg)
                await rep.report(msg, "info")

                feed = feedparser.parse(rss_url)
                entries = feed.entries[:3]  # check latest 3 torrents
                LOGS.info(f"📥 Found {len(entries)} items in feed")
                await rep.report(f"📥 Found {len(entries)} items in feed", "info")

                for entry in entries:
                    title = entry.title
                    msg = f"🔗 Found Torrent: {title}"
                    LOGS.info(msg)
                    await rep.report(msg, "info")

                    tor = TorDownloader()

                    # Download with live 10s updates
                    msg_id = await rep.report(f"⬇️ Starting download: {title}", "info")
                    task = asyncio.create_task(tor.download(entry.link, title))

                    while not task.done():
                        try:
                            # Dummy progress, you can hook real % if TorDownloader supports
                            prog = "Downloading..."
                            await rep.update_report(msg_id, f"⬇️ Downloading {title}\n{prog}")
                        except Exception:
                            pass
                        await asyncio.sleep(10)

                    dl_path = await task
                    if not dl_path:
                        err = f"❌ Torrent download failed: {title}"
                        LOGS.error(err)
                        await rep.report(err, "error")
                        continue

                    # Rename downloaded file
                    new_name = f"[{Var.SECOND_BRAND}] {title} Dual Audio.mkv"
                    new_path = os.path.join("downloads", new_name)
                    os.rename(dl_path, new_path)
                    msg = f"📂 Renamed to: {new_name}"
                    LOGS.info(msg)
                    await rep.report(msg, "info")

                    # Upload with live 10s updates
                    msg_id = await rep.report(f"☁️ Uploading: {new_name}", "info")
                    task = asyncio.create_task(upload_to_drive(new_path))

                    while not task.done():
                        try:
                            prog = "Uploading..."
                            await rep.update_report(msg_id, f"☁️ Uploading {new_name}\n{prog}")
                        except Exception:
                            pass
                        await asyncio.sleep(10)

                    gdrive_link = await task
                    msg = f"✅ Uploaded: {gdrive_link}"
                    LOGS.info(msg)
                    await rep.report(msg, "info")

        except Exception as e:
            err = f"⚠️ Error in RSS Torrent Loop: {str(e)}"
            LOGS.error(err)
            await rep.report(err, "error")

        await asyncio.sleep(60)  # wait 1 min before checking again
