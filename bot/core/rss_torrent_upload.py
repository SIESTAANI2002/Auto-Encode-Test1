import asyncio
from bot import ffQueue, ffLock, ff_queued, bot_loop, Var, LOGS, ani_cache
from bot.core.tordownload import TorDownloader
from bot.core.ffencoder import FFEncoder
from bot.core.gdrive_uploader import upload_to_drive
from bot.core.reporter import rep
from bot.core.database import db

# ---------------- Queue Loop ---------------- #
async def queue_loop():
    LOGS.info("Queue loop started!")
    await rep.report("Queue Loop Started!", "info")
    
    while True:
        if not ffQueue.empty():
            post_id = await ffQueue.get()
            
            # Create an event for progress tracking
            ff_queued[post_id] = asyncio.Event()
            
            try:
                await process_torrent(post_id)
            except Exception as e:
                LOGS.error(f"❌ Failed processing {post_id}: {e}")
                await rep.report(f"❌ Failed processing torrent: {e}", "error")
            
            ffQueue.task_done()
        await asyncio.sleep(1)

# ---------------- Process each torrent ---------------- #
async def process_torrent(post_id):
    _, entry = post_id  # entry = feed entry
    title = entry.title
    link = entry.link
    
    LOGS.info(f"⬇️ Starting download: {title}")
    await rep.report(f"⬇️ Starting download: {title}", "info")
    
    tor_downloader = TorDownloader()
    downloaded_file = await tor_downloader.download(link)
    
    if not downloaded_file:
        raise Exception(f"Torrent download failed: {title}")
    
    LOGS.info(f"✅ Download finished: {title}")
    
    # ---------------- Encode ---------------- #
    for qual in Var.QUALS:
        encoder = FFEncoder(message=None, path=downloaded_file, name=f"{title}_{qual}", qual=qual)
        
        # Use Heroku log + Telegram progress in a task
        progress_task = asyncio.create_task(track_progress(encoder, title))
        encoded_file = await encoder.start_encode()
        progress_task.cancel()
        
        if not encoded_file:
            LOGS.error(f"❌ Encoding failed: {title} [{qual}]")
            continue
        
        LOGS.info(f"✅ Encoding finished: {title} [{qual}]")
        
        # ---------------- Upload ---------------- #
        try:
            gdrive_link = await upload_to_drive(encoded_file)
            LOGS.info(f"✅ Uploaded to Drive: {gdrive_link}")
            await rep.report(f"✅ Uploaded: {title} [{qual}]\n{gdrive_link}", "info")
        except Exception as e:
            LOGS.error(f"❌ Upload failed: {title} [{qual}] - {e}")
    
    # Mark completed in DB/cache
    ani_cache.setdefault("completed", set()).add(post_id)
    await db.saveAnime(post_id[0], ep="batch", qual=Var.QUALS[-1])

# ---------------- Track Progress ---------------- #
async def track_progress(encoder, title):
    while not encoder.is_cancelled:
        try:
            # read current progress from FFEncoder's prog.txt
            progress_file = encoder._FFEncoder__prog_file
            async with aiofiles.open(progress_file, "r") as f:
                text = await f.read()
            
            if text:
                # Parse % done
                time_done = int(findall(r"out_time_ms=(\d+)", text)[-1])/1_000_000 if findall(r"out_time_ms=(\d+)", text) else 0
                percent = min(round((time_done/encoder._FFEncoder__total_time)*100, 2) if encoder._FFEncoder__total_time else 0, 100)
                bar = "█"*(percent//8) + "▒"*(12 - percent//8)
                msg = f"📺 Encoding: {title}\n[{bar}] {percent}%"
                
                # send/edit Telegram message here if you want live updates
                # e.g., await encoder.message.edit_text(msg)
            
            await asyncio.sleep(10)  # update every 10 sec
        except Exception:
            await asyncio.sleep(10)
            continue

# ---------------- RSS Feed Fetch & Queue ---------------- #
async def start_task():
    LOGS.info("RSS Torrent Loop Started!")
    await rep.report("RSS Torrent Loop Started!", "info")
    
    while True:
        rss_list = getattr(Var, "RSS_TOR", Var.RSS_ITEMS)
        for rss_link in rss_list:
            try:
                feed = await getfeed(rss_link, 0)
                if not feed or not hasattr(feed, "entries") or not feed.entries:
                    await rep.report(f"❌ Invalid/Empty RSS Feed: {rss_link}", "error")
                    continue
                
                for entry in feed.entries:
                    post_id = (id(entry), entry)
                    if post_id in ani_cache.get("completed", set()):
                        continue
                    
                    ffQueue.put_nowait(post_id)
                    ff_queued[post_id] = asyncio.Event()
                    LOGS.info(f"Queued RSS Torrent: {entry.title}")
            
            except Exception as e:
                await rep.report(f"RSS Fetch Error for {rss_link}: {e}", "error")
        
        await asyncio.sleep(300)  # check every 5 min
