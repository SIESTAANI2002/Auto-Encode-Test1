# bot/core/tokyo_torrent.py
import os
import asyncio
import time
from os import path as ospath

import libtorrent as lt

from bot import LOGS, Var, bot
from .tokyo_upload import upload_to_tokyo  # your existing tokyo upload helper

# default trackers (add more here if you want)
DEFAULT_TRACKERS = [
    "udp://tracker.openbittorrent.com:80",
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://exodus.desync.com:6969/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "http://nyaa.tracker.wf:7777/announce",
    "udp://open.stealth.si:80/announce"
]


async def generate_torrent(file_path: str, torrent_name: str = None, comment: str = "", 
                           trackers: list | None = None, seed_time: int | None = None) -> str | None:
    """
    Generate a .torrent file for `file_path`, start seeding in background and:
      - upload the .torrent to LOG_CHANNEL (Telegram),
      - start background seeding (DHT/PEX/LSD enabled),
      - concurrently call upload_to_tokyo(torrent_path, torrent_name, comment) if TOKYO creds exist.

    Returns path to the generated torrent file on success, else None.
    """
    try:
        if not ospath.exists(file_path):
            LOGS.error(f"[TokyoTosho] ❌ Source file does not exist: {file_path}")
            return None

        trackers = trackers or DEFAULT_TRACKERS
        seed_time = seed_time or getattr(Var, "TOKYO_SEED_TIME", 3600)  # default 1 hour

        # ensure torrents dir
        tor_dir = ospath.join(ospath.dirname(file_path) or ".", "torrents")
        os.makedirs(tor_dir, exist_ok=True)
        torrent_basename = torrent_name or ospath.basename(file_path)
        torrent_file = ospath.join(tor_dir, f"{torrent_basename}.torrent")

        # Build libtorrent file_storage & create_torrent
        fs = lt.file_storage()
        lt.add_files(fs, file_path)  # add this single file (or directory if a folder)
        creator = lt.create_torrent(fs)

        # add trackers
        for t in trackers:
            try:
                creator.add_tracker(t)
            except Exception:
                # continue even if a tracker fails to add
                LOGS.warning(f"[TokyoTosho] Warning adding tracker: {t}")

        creator.set_comment(comment or torrent_basename)
        creator.set_creator("AnimeBot")

        # compute piece hashes (requires the base path)
        base_path = ospath.dirname(file_path) or "."
        lt.set_piece_hashes(creator, base_path)

        torrent = creator.generate()
        with open(torrent_file, "wb") as f:
            f.write(lt.bencode(torrent))

        LOGS.info(f"[TokyoTosho] Torrent created: {torrent_file}")

        # 1) Immediately upload torrent file to Telegram log channel (non-blocking)
        if getattr(Var, "LOG_CHANNEL", None):
            try:
                # pyrogram can accept path directly
                await bot.send_document(
                    chat_id=Var.LOG_CHANNEL,
                    document=torrent_file,
                    caption=f"Torrent created: {ospath.basename(torrent_file)}"
                )
                LOGS.info(f"[TokyoTosho] Uploaded torrent to log channel: {torrent_file}")
            except Exception as e:
                LOGS.error(f"[TokyoTosho] Failed to upload torrent to log channel: {e}")

        # 2) Start seeding + Tokyo upload concurrently as background tasks
        # The seeding task will run for `seed_time` seconds then stop.
        asyncio.create_task(_seed_and_manage(torrent_file, base_path, seed_time))

        # 3) Start Tokio upload concurrently (if credentials present)
        if hasattr(Var, "TOKYO_USER") and Var.TOKYO_USER:
            # run tokyo upload in background; don't await here
            asyncio.create_task(_try_upload_tokyo(torrent_file, torrent_basename, comment))

        return torrent_file

    except Exception as e:
        LOGS.error(f"[ERROR] TokyoTosho Torrent Generation Exception ({torrent_name}): {e}")
        return None


async def _try_upload_tokyo(torrent_path: str, name: str, comment: str = ""):
    """Wrapper to call your tokyo upload helper and log errors."""
    try:
        LOGS.info(f"[TokyoTosho] Starting TokyoTosho upload for: {name}")
        ok = await upload_to_tokyo(torrent_path, name, comment)
        if ok:
            LOGS.info(f"[TokyoTosho] Tokyo upload started/completed for: {name}")
        else:
            LOGS.error(f"[TokyoTosho] Tokyo upload returned failure for: {name}")
    except Exception as e:
        LOGS.error(f"[ERROR] TokyoTosho Upload Exception ({name}): {e}")


async def _seed_and_manage(torrent_path: str, save_path: str, seed_time: int = 3600):
    """
    Start libtorrent session, add torrent and seed for `seed_time` seconds.
    Uses DHT + PEX + LSD (attempts to boost connectivity).
    """
    try:
        LOGS.info(f"[TokyoTosho] Starting local seeding for {torrent_path} ...")
        ses = lt.session()

        # listen port range
        ses.listen_on(6881, 6891)

        # enable DHT
        try:
            ses.add_dht_router("router.bittorrent.com", 6881)
            ses.start_dht()
        except Exception as e:
            LOGS.warning(f"[TokyoTosho] DHT start warning: {e}")

        # configure session settings: enable PEX & LSD (if available)
        try:
            settings = lt.settings_pack()
            settings.set_bool(lt.settings_pack.enable_lsd, True)
            settings.set_bool(lt.settings_pack.enable_upnp, False)
            settings.set_bool(lt.settings_pack.enable_natpmp, False)
            ses.apply_settings(settings)
        except Exception:
            # older libtorrent may not expose the same flags; ignore if fails
            pass

        info = lt.torrent_info(torrent_path)

        # Add torrent without seed_mode to ensure libtorrent recognizes the existing file and seeds it
        params = {
            "ti": info,
            "save_path": save_path,
            # let libtorrent check files and set them as complete
            "flags": lt.torrent_flags.immutable if hasattr(lt, "torrent_flags") else 0
        }

        h = ses.add_torrent(params)

        # trigger recheck to ensure torrent is recognized as complete (helps clients to download)
        try:
            h.force_recheck()
        except Exception:
            # some versions don't provide force_recheck, ignore
            pass

        start = time.time()
        last_log = 0
        while time.time() - start < seed_time:
            s = h.status()
            now = time.time()
            # log every ~5s
            if now - last_log >= 5:
                progress_pct = s.progress * 100
                peers = s.num_peers
                up_rate = s.upload_rate / 1000.0
                down_rate = s.download_rate / 1000.0
                LOGS.info(f"[TokyoTosho] Seeding: {progress_pct:.2f}% - Peers: {peers} - Up: {up_rate:.2f} kB/s - Down: {down_rate:.2f} kB/s")
                last_log = now
            await asyncio.sleep(1)

        # remove torrent from session when done
        try:
            ses.remove_torrent(h)
        except Exception:
            pass

        LOGS.info(f"[TokyoTosho] Finished seeding {torrent_path}")

    except Exception as e:
        LOGS.error(f"[TokyoTosho] Seeding Exception: {e}")
