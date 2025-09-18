from asyncio import gather, create_task, sleep as asleep, Event, Queue
from os import path as ospath
from aiofiles.os import remove as aioremove
from traceback import format_exc
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot import bot, bot_loop, Var, ani_cache, ffQueue, ffLock, ff_queued
from .tordownload import TorDownloader
from .database import db
from .func_utils import sendMessage, editMessage, convertBytes, getfeed
from .text_utils import TextEditor
from .ffencoder import FFEncoder
from .tguploader import TgUploader
from .reporter import rep

btn_formatter = {'1080':'1080p', '720':'𝟳𝟮𝟬𝗽'}

async def fetch_animes():
    await rep.report("Fetch Animes Started !!", "info")
    while True:
        await asleep(60)
        if ani_cache['fetch_animes']:
            tasks = []
            for qual, feed_url in Var.RSS_ITEMS.items():
                await rep.report(f"[INFO] Checking {qual} feed: {feed_url}", "info")
                info = await getfeed(feed_url, 0)
                if info:
                    tasks.append(get_animes(info.title, info.link, qual))
            if tasks:
                await gather(*tasks)

async def get_animes(name, torrent, qual_feed):
    try:
        aniInfo = TextEditor(name)
        await aniInfo.load_anilist()
        ani_id = aniInfo.adata.get('id')
        ep_no = aniInfo.pdata.get("episode_number")

        if ani_id not in ani_cache['ongoing']:
            ani_cache['ongoing'].add(ani_id)
        else:
            return

        # Skip if episode already completed in DB
        if ep_data := await db.getAnime(ani_id):
            if ep_data.get(ep_no):
                return

        # Download torrent
        await rep.report(f"New Anime Torrent Found!\n{name} from {qual_feed} feed", "info")
        dl = await TorDownloader("./downloads").download(torrent, name)
        if not dl or not ospath.exists(dl):
            await rep.report(f"File Download Incomplete, Try Again", "error")
            return

        # Check if a post already exists for this episode
        post_id = None
        if ep_data and (existing_post_id := ep_data.get(ep_no, {}).get('post_id')):
            post_id = existing_post_id
        else:
            # Create new post
            post_msg = await bot.send_photo(
                Var.MAIN_CHANNEL,
                photo=await aniInfo.get_poster(),
                caption=await aniInfo.get_caption()
            )
            post_id = post_msg.id

        # Add task to queue for encoding & uploading
        ffEvent = Event()
        ff_queued[(ani_id, ep_no, qual_feed)] = ffEvent
        await ffQueue.put((ani_id, ep_no, qual_feed, dl, aniInfo, post_id))
        await ffEvent.wait()
        ani_cache['completed'].add(ani_id)

    except Exception:
        await rep.report(format_exc(), "error")


async def encode_worker():
    while True:
        ani_id, ep_no, qual_feed, dl, aniInfo, post_id = await ffQueue.get()
        await ffLock.acquire()
        try:
            filename = await aniInfo.get_upname(qual_feed)
            out_path = await FFEncoder(None, dl, filename, qual_feed).start_encode()
            msg = await TgUploader(None).upload(out_path, qual_feed)
            msg_id = msg.id
            link = f"https://t.me/{(await bot.get_me()).username}?start=get-{msg_id}"

            # Load current buttons
            ep_data = await db.getAnime(ani_id)
            current_buttons = []
            if ep_data.get(ep_no):
                for q, data in ep_data[ep_no].items():
                    if data.get('msg_id'):
                        q_link = f"https://t.me/{(await bot.get_me()).username}?start=get-{data['msg_id']}"
                        current_buttons.append([InlineKeyboardButton(f"{btn_formatter[q]} - {convertBytes(data['file_size'])}", url=q_link)])

            # Add new button
            current_buttons.append([InlineKeyboardButton(f"{btn_formatter[qual_feed]} - {convertBytes(msg.document.file_size)}", url=link)])
            await editMessage(post_id=post_id, caption=aniInfo.caption, reply_markup=InlineKeyboardMarkup(current_buttons))

            # Save in DB
            await db.saveAnime(ani_id, ep_no, qual_feed, post_id, msg.document.file_size)

            await aioremove(dl)

        except Exception as e:
            await rep.report(f"Encoding/Uploading Failed: {e}", "error")
        finally:
            ffLock.release()
            ffQueue.task_done()
