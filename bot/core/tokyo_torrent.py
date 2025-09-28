# bot/core/tokyo_torrent.py
import libtorrent as lt
import asyncio
import time
from os import path as ospath
from bot import LOGS, Var, bot
from pyrogram.types import InputFile
from .tokyo_upload import upload_to_tokyo  # Your TokyoTosho upload function


async def generate_torrent(file_path, torrent_name, comment=""):
    """
    Generate a .torrent file from a video file.
    """
    try:
        torrent_file_path = ospath.join("torrents", f"{torrent_name}.torrent")
        fs = lt.file_storage()
        lt.add_files(fs, file_path)
        creator = lt.create_torrent(fs)
        creator.set_creator("AnimeBot")

        # --- Add multiple public trackers ---
        trackers = [
            "udp://tracker.openbittorrent.com:80",
            "udp://tracker.opentrackr.org:1337/announce",
            "udp://tracker.internetwarriors.net:1337/announce",
            "udp://tracker.leechers-paradise.org:6969/announce",
            "udp://tracker.coppersurfer.tk:6969/announce",
            "udp://tracker.pirateparty.gr:6969/announce",
            "udp://tracker.cyberia.is:6969/announce",
            "udp://exodus.desync.com:6969/announce",
            "udp://tracker.empire-js.us:1337/announce",
            "udp://9.rarbg.to:2710/announce",
            "udp://9.rarbg.me:2710/announce"
        ]
        for tracker in trackers:
            creator.add_tracker(tracker)

        creator.set_comment(comment or torrent_name)
        lt.set_piece_hashes(creator, ospath.dirname(file_path))
        torrent = creator.generate()
        with open(torrent_file_path, "wb") as f:
            f.write(lt.bencode(torrent))

        LOGS.info(f"[TokyoTosho] Torrent created: {torrent_file_path}")

        # Seed locally for 10 min, then upload torrent file to log channel
        await seed_torrent_and_upload_log(torrent_file_path, ospath.dirname(file_path), seed_time=600)

        # Optionally upload to TokyoTosho (if login credentials exist)
        if hasattr(Var, "TOKYO_USER") and Var.TOKYO_USER:
            await upload_to_tokyo(torrent_file_path, torrent_name, comment)

        return torrent_file_path

    except Exception as e:
        LOGS.error(f"[ERROR] TokyoTosho Torrent Generation Exception ({torrent_name}): {e}")
        return None


async def seed_torrent_and_upload_log(torrent_path, download_path="./downloads", seed_time=600):
    """
    Seed torrent locally for seed_time seconds, then upload to Telegram log channel.
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

        start = time.time()
        while time.time() - start < seed_time:
            s = h.status()
            LOGS.info(f"[TokyoTosho] Seeding: {s.progress * 100:.2f}% - "
                      f"Peers: {s.num_peers} - Upload: {s.upload_rate / 1000:.2f} kB/s")
            await asyncio.sleep(5)

        ses.remove_torrent(h)
        LOGS.info(f"[TokyoTosho] Finished seeding {torrent_path}")

        # Upload torrent file to Telegram log channel
        if ospath.exists(torrent_path) and Var.LOG_CHANNEL:
            try:
                await bot.send_document(
                    chat_id=Var.LOG_CHANNEL,
                    document=InputFile(torrent_path),
                    caption=f"Torrent file: {ospath.basename(torrent_path)}"
                )
                LOGS.info(f"[TokyoTosho] Uploaded torrent to log channel: {torrent_file_path}")
            except Exception as e:
                LOGS.error(f"[TokyoTosho] Failed to upload torrent to log channel: {e}")

    except Exception as e:
        LOGS.error(f"[TokyoTosho] Seeding Exception: {e}")
