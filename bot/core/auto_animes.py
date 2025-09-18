import asyncio
from traceback import format_exc
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from bot import bot, bot_loop, Var, db
from bot.core.func_utils import handle_logs
from bot.core.text_utils import TextEditor
from bot.core.tordownload import TorDownloader
from bot.core.ffencoder import start_encode
from bot.core.reporter import rep
from bot.core.feed_utils import getfeed

btn_formatter = {
    "720": "720p",
    "1080": "1080p"
}

async def fetch_animes():
    try:
        for qual, feed_link in Var.RSS_ITEMS.items():
            try:
                # Commented out feed info to stop spam messages
                print(f"[INFO] Checking {qual} feed: {feed_link}")
                # await rep.report(f"Checking {qual} feed: {feed_link}", "info")
                entry = await getfeed(feed_link, 0)
                if entry:
                    bot_loop.create_task(get_animes(entry.title, entry.link, qual))
            except Exception as e:
                await rep.report(f"Error fetching feed {qual}: {e}", "error")
    except Exception:
        await rep.report(format_exc(), "error")

async def get_animes(title, link, qual):
    try:
        ani_id = TextEditor(title).clean_name
        ep_no = TextEditor(title).get_ep_number

        # Check if already posted
        existing_post_id = await db.getEpisodePost(ani_id, ep_no)
        tor_down = TorDownloader()
        file_path = await tor_down.download(link, name=f"{title}.mkv")

        # Encode
        output_file = await start_encode(file_path, qual)

        # Upload
        msg = await bot.send_document(
            chat_id=Var.MAIN_CHANNEL,
            document=output_file,
            caption=f"‣ **Anime Name :** ***{title}***\n\nReady to Encode..."
        )

        # Buttons handling
        link_url = f"https://telegram.me/{(await bot.get_me()).username}?start={ani_id}_{ep_no}_{qual}"

        if existing_post_id:
            post_msg = await bot.get_messages(Var.MAIN_CHANNEL, message_ids=existing_post_id)
            if post_msg.reply_markup:
                btns = post_msg.reply_markup.inline_keyboard
                # Append new button if not exists
                if len(btns[-1]) == 1:
                    btns[-1].append(InlineKeyboardButton(f"{btn_formatter[qual]} - {round(msg.document.file_size/1024/1024)}MB", url=link_url))
                else:
                    btns.append([InlineKeyboardButton(f"{btn_formatter[qual]} - {round(msg.document.file_size/1024/1024)}MB", url=link_url)])
            else:
                btns = [[InlineKeyboardButton(f"{btn_formatter[qual]} - {round(msg.document.file_size/1024/1024)}MB", url=link_url)]]
            await post_msg.edit_caption(post_msg.caption or "", reply_markup=InlineKeyboardMarkup(btns))
        else:
            # First post
            btns = [[InlineKeyboardButton(f"{btn_formatter[qual]} - {round(msg.document.file_size/1024/1024)}MB", url=link_url)]]
            await msg.edit_caption(msg.caption or "", reply_markup=InlineKeyboardMarkup(btns))
            await db.saveEpisodePost(ani_id, ep_no, msg.id)

    except Exception:
        await rep.report(format_exc(), "error")
