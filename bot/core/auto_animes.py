import asyncio
import feedparser
from os import path as ospath
from aiofiles.os import remove as aioremove
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot import LOGS, Var, bot, ani_cache, ffQueue, ffLock, ff_queued
from bot.core.tordownload import TorDownloader
from bot.core.text_utils import TextEditor
from bot.core.func_utils import handle_logs
from bot.core.database import db


# ----------------- CONFIG -----------------
RSS_ITEMS = Var.RSS_ITEMS  # loaded from config.env as JSON
CHECK_INTERVAL = 60        # seconds between feed checks


# ----------------- UTILS -----------------
def build_buttons(ani_id, ep_no, post_id):
    """
    Create InlineKeyboard buttons for both 720p & 1080p.
    """
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("⬇ Download 720p", url=f"https://t.me/{Var.BOT_USERNAME}?start={ani_id}_{ep_no}_720"),
                InlineKeyboardButton("⬇ Download 1080p", url=f"https://t.me/{Var.BOT_USERNAME}?start={ani_id}_{ep_no}_1080"),
            ]
        ]
    )


async def fetch_feed(url):
    """
    Fetch RSS feed and return parsed entries.
    """
    parsed = feedparser.parse(url)
    return parsed.entries


async def process_entry(entry, quality):
    """
    Process single RSS entry (download, encode, upload).
    """
    title = entry.title
    link = entry.link
    LOGS.info(f"[INFO] New Anime Torrent Found!\n{title} from {quality} feed")

    # Extract Anime ID & Episode
    try:
        ani_id = abs(hash("".join(title.split()[:-1]))) % (10 ** 6)
        ep_no = ''.join(filter(str.isdigit, title.split()[-2]))
    except Exception:
        ani_id, ep_no = abs(hash(title)) % (10 ** 6), "01"

    # Check DB if already posted
    existing_post_id = await db.getEpisodePost(ani_id, ep_no)
    if existing_post_id:
        LOGS.info(f"[SKIP] {title} already posted.")
        return

    # Download torrent
    tor = TorDownloader("./downloads")
    file_path = await tor.download(link, name=title + ".mkv")

    if not file_path or not ospath.exists(file_path):
        LOGS.error(f"[ERROR] Failed to download {title}")
        return

    # Queue for encoding
    editor = TextEditor()
    task_key = (ani_id, ep_no, quality, file_path, editor)

    ff_event = asyncio.Event()
    ff_queued[task_key] = ff_event

    async with ffLock:
        ffQueue.append(task_key)

    # Wait for encode/upload completion
    await ff_event.wait()

    # After encode/upload → send post
    caption = f"‣ **Anime Name :** ***{title}***\n\n✅ Uploaded Successfully"
    buttons = build_buttons(ani_id, ep_no, ani_id)

    post = await bot.send_message(
        Var.CHANNEL_ID,
        caption,
        reply_markup=buttons
    )

    # Save to DB
    await db.saveEpisodePost(ani_id, ep_no, quality, post.id)

    LOGS.info(f"[POSTED] {title} [{quality}] → {post.id}")


# ----------------- LOOP -----------------
@handle_logs
async def get_animes():
    """
    Loop through all feeds (720 & 1080).
    """
    while True:
        for quality, url in RSS_ITEMS.items():
            LOGS.info(f"[INFO] Checking {quality} feed: {url}")
            try:
                entries = await fetch_feed(url)
                for entry in entries[:2]:  # check latest 2 only
                    await process_entry(entry, quality)
            except Exception as e:
                LOGS.error(f"[ERROR] Failed parsing {quality} feed: {e}")
        await asyncio.sleep(CHECK_INTERVAL)
