# bot/core/tokyo_torrent.py
import os
import libtorrent as lt
import asyncio

async def generate_torrent(file_path, anime_name):
    """
    Generates a .torrent file for the given file.
    Returns the path to the .torrent file.
    """
    try:
        fs = lt.file_storage()
        lt.add_files(fs, file_path)
        t = lt.create_torrent(fs)
        t.add_tracker("http://tracker.opentrackr.org:1337/announce")
        t.set_creator("AnimeBot")

        torrent_data = t.generate()
        torrent_file = os.path.splitext(file_path)[0] + ".torrent"
        with open(torrent_file, "wb") as f:
            f.write(lt.bencode(torrent_data))

        return torrent_file
    except Exception as e:
        raise RuntimeError(f"Failed to generate torrent for {anime_name}: {e}")
