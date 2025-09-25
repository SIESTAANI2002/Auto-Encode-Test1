# bot/core/tokyo_torrent.py
import os
import libtorrent as lt
import asyncio
from bot.core.reporter import rep

async def generate_torrent(file_path, tracker_url="udp://tracker.openbittorrent.com:80/announce"):
    """
    Generate a .torrent file for a given video file.

    Args:
        file_path (str): Path to the video file.
        tracker_url (str, optional): Tracker URL. Default is public tracker.
    
    Returns:
        str: Path to the generated .torrent file.
    """
    try:
        file_name = os.path.basename(file_path)
        torrent_name = f"{file_path}.torrent"

        fs = lt.file_storage()
        lt.add_files(fs, file_path)
        t = lt.create_torrent(fs)
        t.add_tracker(tracker_url)
        t.set_creator("AnimeBot TokyoTosho Upload")

        lt.set_piece_hashes(t, os.path.dirname(file_path))
        torrent = t.generate()

        with open(torrent_name, "wb") as f:
            f.write(lt.bencode(torrent))

        await rep.report(f"✅ Torrent Generated: {file_name}", "info")
        return torrent_name
    except Exception as e:
        await rep.report(f"❌ Torrent Generation Failed: {e}", "error")
        return None
