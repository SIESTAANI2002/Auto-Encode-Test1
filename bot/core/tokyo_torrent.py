# bot/core/tokyo_torrent.py
import libtorrent as lt
import asyncio
import time
from os import path as ospath
from bot import LOGS, Var, bot
from .tokyo_upload import upload_to_tokyo  # Your TokyoTosho upload function


TRACKERS = [
    "udp://tracker.openbittorrent.com:80",
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://exodus.desync.com:6969/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "http://nyaa.tracker.wf:7777/announce",
    "udp://open.stealth.si:80/announce"
]


async def generate_torrent(file_path, torrent_name, comment=""):
    """
    Generate a .torrent file from a video file, seed it, and upload concurrently.
    """
    try:
        torrent_file_path = ospath.join("torrents", f"{torrent_name}.torrent")
        fs = lt.file_storage()
        lt.add_files(fs, file_path)
        creator = lt.create_torrent(fs)
        creator.set_creator("AnimeBot")

        # Add all trackers
        for tracker in TRACKERS:
            creator.add_tracker(tracker)

        creator.set_comment(comment or torrent_name)

        lt.set_piece_hashes(creator, ospath.dirname(file_path))
        torrent = creator.generate()
        with open(torrent_file_path, "wb") as f:
            f.write(lt.bencode(torrent))

        LOGS.info(f"[TokyoTosho] Torrent created: {torrent_file_path}")

        # Start seeding + concurrent upload tasks
        await seed_torrent_and_upload(torrent_file_path, ospath.dirname(file_path), comment)

        return torrent_file_path

    except Exception as e:
        LOGS.error(f"[ERROR] TokyoTosho Torrent Generation Exception ({torrent_name}): {e}")
        return None


async def seed_torrent_and_upload(torrent_path, download_path="./downloads", comment="", seed_time=3600):
    """
    Seed torrent locally and concurrently upload to Telegram log channel and TokyoTosho.
    """
    try:
        LOGS.info(f"[TokyoTosho] Starting local seeding for {torrent_path} ...")
        ses = lt.session()
        ses.listen_on(6881, 6891)

        info = lt.torrent_info(torrent_path)
        h = ses.add_torrent({
            'ti': info,
            'save_path': download_path,
            'flags': lt.torrent_flags.seed_mode
        })

        # Start upload tasks concurrently while seeding
        tasks = []
        if ospath.exists(torrent_path) and Var.LOG_CHANNEL:
            tasks.append(asyncio.create_task(
                bot.send_document(
                    chat_id=Var.LOG_CHANNEL,
                    document=torrent_path,
                    caption=f"Torrent file: {ospath.basename(torrent_path)}"
                )
            ))

        if hasattr(Var, "TOKYO_USER") and Var.TOKYO_USER:
            tasks.append(asyncio.create_task(
                upload_to_tokyo(torrent_path, ospath.basename(torrent_path), comment)
            ))

        start = time.time()
        while time.time() - start < seed_time:
            s = h.status()
            LOGS.info(f"[TokyoTosho] Seeding: {s.progress * 100:.2f}% - "
                      f"Peers: {s.num_peers} - Upload: {s.upload_rate / 1000:.2f} kB/s")
            await asyncio.sleep(5)

        ses.remove_torrent(h)
        LOGS.info(f"[TokyoTosho] Finished seeding {torrent_path}")

        # Await the upload tasks after seeding
        if tasks:
            await asyncio.gather(*tasks)
            LOGS.info(f"[TokyoTosho] Upload tasks completed for {torrent_path}")

    except Exception as e:
        LOGS.error(f"[TokyoTosho] Seeding/Upload Exception: {e}")
