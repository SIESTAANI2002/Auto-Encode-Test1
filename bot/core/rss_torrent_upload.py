import asyncio
import feedparser
import os
from bot import Var, LOGS
from bot.core.tordownload import TorDownloader
from bot.core.gdrive_uploader import upload_to_drive
from bot.core.reporter import rep

async def start_task():
    await rep.report("✅ RSS Torrent Task Started!", "info")
    LOGS.info("✅ RSS Torrent Task Started!")

    while True:
        try:
            for rss_url in Var.RSS_TOR:
                msg = f"📡 Checking RSS Feed: {rss_url}"
                await rep.report(msg, "info")
                LOGS.info(msg)

                feed = feedparser.parse(rss_url)
                for entry in feed.entries[:3]:
                    title = entry.title
                    msg = f"🔗 Found Torrent: {title}"
                    await rep.report(msg, "info")
                    LOGS.info(msg)

                    tor = TorDownloader()

                    # ---- Download with 10s updates ----
                    msg_id = await rep.report(f"⬇️ Starting download: {title}", "info")
                    task = asyncio.create_task(tor.download(entry.link, title))

                    while not task.done():
                        prog = tor.progress()
                        await rep.update_report(msg_id, f"⬇️ Downloading {title}\n{prog}")
                        await asyncio.sleep(10)

                    dl_path = await task
                    if not dl_path:
                        err = "❌ Torrent download failed"
                        await rep.report(err, "error")
                        LOGS.error(err)
                        continue

                    # ---- Rename ----
                    new_name = f"[{Var.SECOND_BRAND}] {title} Dual Audio.mkv"
                    new_path = os.path.join("downloads", new_name)
                    os.rename(dl_path, new_path)

                    msg = f"📂 Renamed to: {new_name}"
                    await rep.report(msg, "info")
                    LOGS.info(msg)

                    # ---- Upload with 10s updates ----
                    msg_id = await rep.report(f"☁️ Uploading: {new_name}", "info")
                    task = asyncio.create_task(upload_to_drive(new_path))

                    while not task.done():
                        prog = "progress here"  # TODO: hook ffencoder-style % reporting
                        await rep.update_report(msg_id, f"☁️ Uploading {new_name}\n{prog}")
                        await asyncio.sleep(10)

                    gdrive_link = await task
                    msg = f"✅ Uploaded: {gdrive_link}"
                    await rep.report(msg, "info")
                    LOGS.info(msg)

        except Exception as e:
            err = f"⚠️ Error in RSS Torrent Loop: {str(e)}"
            await rep.report(err, "error")
            LOGS.error(err)

        await asyncio.sleep(60)  # wait 1 min before checking again
