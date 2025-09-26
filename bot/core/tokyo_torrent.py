import libtorrent as lt
import os
from hashlib import sha1
from bot import LOGS

async def generate_torrent(filepath, torrent_path):
    """Generate a .torrent file for the given file"""
    if not os.path.exists(filepath):
        LOGS.error(f"[TokyoTosho] File not found for torrent: {filepath}")
        return None

    try:
        fs = lt.file_storage()
        lt.add_files(fs, filepath)
        t = lt.create_torrent(fs)

        # Optional: piece size (auto if not set)
        t.set_creator("AnimeToki Bot")
        t.set_comment("Uploaded via bot")

        # Add trackers (TokyoTosho requires at least one tracker)
        trackers = [
            "udp://tracker.opentrackr.org:1337/announce",
            "udp://tracker.openbittorrent.com:6969/announce"
        ]
        for tr in trackers:
            t.add_tracker(tr)

        # Hash pieces
        lt.set_piece_hashes(t, os.path.dirname(filepath))

        # Save torrent
        torrent_data = lt.bencode(t.generate())
        with open(torrent_path, "wb") as f:
            f.write(torrent_data)

        LOGS.info(f"[TokyoTosho] Torrent created: {torrent_path}")
        return torrent_path

    except Exception as e:
        LOGS.error(f"[TokyoTosho] Torrent generation failed: {str(e)}")
        return None
