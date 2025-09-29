import os
import time
import libtorrent as lt
import asyncio
import aiohttp
from pyrogram import Client
from bot import Var, LOGS

TOKYO_UPLOAD_URL = "https://www.tokyotosho.info/new.php"

# ----------------- Trackers ----------------- #
TRACKERS = [
    "http://nyaa.tracker.wf:7777/announce",
    "http://tracker.opentrackr.org:1337/announce",
    "http://tracker.torrent.eu.org:451/announce",
]

# ----------------- Session Setup ----------------- #
def create_session():
    ses = lt.session()
    ses.listen_on(6881, 6891)

    # Enable peer discovery
    ses.start_dht()
    ses.start_lsd()
    ses.start_upnp()
    ses.start_natpmp()

    # Bootstrap nodes
    ses.add_dht_router("router.bittorrent.com", 6881)
    ses.add_dht_router("router.utorrent.com", 6881)
    ses.add_dht_router("router.bitcomet.com", 6881)

    # Allow both TCP & UTP
    settings = ses.get_settings()
    settings["enable_outgoing_utp"] = True
    settings["enable_incoming_utp"] = True
    settings["enable_outgoing_tcp"] = True
    settings["enable_incoming_tcp"] = True
    ses.apply_settings(settings)

    return ses

# ----------------- Torrent Creation ----------------- #
def generate_torrent(file_path: str):
    fs = lt.file_storage()
    lt.add_files(fs, file_path)
    t = lt.create_torrent(fs)
    for tr in TRACKERS:
        t.add_tracker(tr)

    t.set_creator("AnimeTokiBot")
    lt.set_piece_hashes(t, os.path.dirname(file_path))
    torrent = t.generate()

    torrent_name = os.path.basename(file_path) + ".torrent"
    torrent_path = os.path.join("encode/torrents", torrent_name)
    os.makedirs(os.path.dirname(torrent_path), exist_ok=True)

    with open(torrent_path, "wb") as f:
        f.write(lt.bencode(torrent))

    LOGS.info(f"[TokyoTosho] Torrent created: {torrent_path}")
    return torrent_path

# ----------------- Seeding ----------------- #
async def seed_torrent(torrent_path: str, seed_time: int = 3600):
    ses = create_session()

    info = lt.torrent_info(torrent_path)
    params = {
        "ti": info,
        "save_path": os.path.dirname(torrent_path),
    }
    h = ses.add_torrent(params)
    LOGS.info(f"[TokyoTosho] Starting local seeding for {torrent_path} ...")

    start = time.time()
    while time.time() - start < seed_time:
        s = h.status()
        LOGS.info(
            f"[TokyoTosho] Seeding: {s.progress * 100:.2f}% "
            f"- Peers: {s.num_peers} - Upload: {s.upload_rate/1000:.2f} kB/s"
        )
        await asyncio.sleep(30)

    ses.remove_torrent(h)
    LOGS.info(f"[TokyoTosho] Seeding finished for {torrent_path}")

# ----------------- Telegram Upload ----------------- #
async def send_to_tg(bot: Client, chat_id: int, torrent_path: str):
    await bot.send_document(chat_id, torrent_path)
    LOGS.info(f"[TokyoTosho] Uploaded torrent to Telegram: {torrent_path}")

# ----------------- TokyoTosho Upload ----------------- #
async def upload_tokyotosho(torrent_path: str, title: str, category="1", comment=""):
    async with aiohttp.ClientSession() as session:
        data = {
            "title": title,
            "category": category,
            "comment": comment,
        }
        files = {"torrent": open(torrent_path, "rb")}
        async with session.post(TOKYO_UPLOAD_URL, data=data, files=files) as resp:
            if resp.status == 200:
                LOGS.info(f"[TokyoTosho] Uploaded to TokyoTosho: {title}")
            else:
                LOGS.error(f"[TokyoTosho] Upload failed: {resp.status}")

# ----------------- Main Pipeline ----------------- #
async def handle_torrent(bot: Client, file_path: str, tg_chat: int):
    # 1. Generate torrent
    torrent_path = generate_torrent(file_path)

    # 2. Start seeding in background
    asyncio.create_task(seed_torrent(torrent_path, seed_time=3600))

    # 3. Send torrent file to Telegram
    await send_to_tg(bot, tg_chat, torrent_path)

    # 4. Upload to TokyoTosho
    title = os.path.basename(file_path)
    await upload_tokyotosho(torrent_path, title)
