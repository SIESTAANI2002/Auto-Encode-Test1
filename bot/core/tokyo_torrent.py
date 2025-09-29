# bot/core/tokyo_torrent.py
import libtorrent as lt
import asyncio
import time
from os import path as ospath
from bot import LOGS, Var, bot
from pyrogram.types import InputMediaDocument
from .tokyo_upload import upload_to_tokyo


TRACKERS = [
    "udp://tracker.openbittorrent.com:80",
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://exodus.desync.com:6969/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "http://nyaa.tracker.wf:7777/announce",
    "udp://open.stealth.si:80/announce",
]


async def generate_torrent(file_path, torrent_name, comment=""):
    """
    Generate a .torrent file, seed locally, share to TG, then upload to TokyoTosho.
    """
    try:
        torrent_file_path = ospath.join("torrents", f"{torrent_name}.torrent")
        fs = lt.file_storage()
        lt.add_files(fs, file_path)
        creator = lt.create_torrent(fs)
        creator.set_creator("AnimeBot")

        # Add trackers
        for tr in TRACKERS:
            creator.add_tracker(tr)

        creator.set_comment(comment or torrent_name)

        lt.set_piece_hashes(creator, ospath.dirname(file_path))
        torrent = creator.generate()
        with open(torrent_file_path, "wb") as f:
            f.write(lt.bencode(torrent))

        LOGS.info(f"[TokyoTosho] Torrent created: {torrent_file_path}")

        # Start seeding in background
        asyncio.create_task(seed_torrent_and_upload_log(torrent_file_path, ospath.dirname(file_path), seed_time=3600))

        # Upload torrent to TG immediately
        if Var.LOG_CHANNEL:
            try:
                await bot.send_document(
                    chat_id=Var.LOG_CHANNEL,
                    document=torrent_file_path,
                    caption=f"Torrent file: {ospath.basename(torrent_file_path)}"
                )
                LOGS.info(f"[TokyoTosho] Uploaded torrent to log channel: {torrent_file_path}")
            except Exception as e:
                LOGS.error(f"[TokyoTosho] Failed to upload torrent to log channel: {e}")

        # Upload to TokyoTosho while seeding
        if hasattr(Var, "TOKYO_USER") and Var.TOKYO_USER:
            asyncio.create_task(upload_to_tokyo(torrent_file_path, torrent_name, comment))

        return torrent_file_path

    except Exception as e:
        LOGS.error(f"[ERROR] TokyoTosho Torrent Generation Exception ({torrent_name}): {e}")
        return None


async def seed_torrent_and_upload_log(torrent_path, save_path="./downloads", seed_time=3600):
    """
    Seed torrent locally for seed_time seconds.
    """
    try:
        LOGS.info(f"[TokyoTosho] Starting local seeding for {torrent_path} ...")
        ses = lt.session()
        ses.listen_on(6881, 6891)
        ses.add_dht_router("router.bittorrent.com", 6881)
        ses.add_dht_router("router.utorrent.com", 6881)
        ses.add_dht_router("dht.transmissionbt.com", 6881)
        ses.start_dht()
        ses.start_lsd()
        ses.start_upnp()
        ses.start_natpmp()

        info = lt.torrent_info(torrent_path)
        params = {
            "ti": info,
            "save_path": save_path,
            # FIXED: removed immutable, use seed_mode if available
            "flags": lt.torrent_flags.seed_mode if hasattr(lt, "torrent_flags") else 0
        }

        h = ses.add_torrent(params)

        try:
            h.force_recheck()
        except Exception:
            pass

        start = time.time()
        while time.time() - start < seed_time:
            s = h.status()
            LOGS.info(f"[TokyoTosho] Seeding: {s.progress * 100:.2f}% - "
                      f"Peers: {s.num_peers} - Upload: {s.upload_rate / 1000:.2f} kB/s")
            await asyncio.sleep(5)

        ses.remove_torrent(h)
        LOGS.info(f"[TokyoTosho] Finished seeding {torrent_path}")

    except Exception as e:
        LOGS.error(f"[TokyoTosho] Seeding Exception: {e}")
