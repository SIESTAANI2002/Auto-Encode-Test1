# bot/core/tokyo_torrent.py
import libtorrent as lt
import os
from os import path as ospath

async def generate_torrent(file_path: str, name: str, announce_list=None, piece_size=0):
    """
    Generate a .torrent file from the given file_path.
    Returns the path of the generated torrent.
    """
    if not ospath.exists(file_path):
        raise FileNotFoundError(f"File does not exist: {file_path}")

    # Create a file storage and add files
    fs = lt.file_storage()
    lt.add_files(fs, file_path)

    # Create the torrent
    ct = lt.create_torrent(fs, piece_size=piece_size)
    if announce_list:
        for tier in announce_list:
            ct.add_tracker(tier)

    # Calculate piece hashes automatically
    lt.set_piece_hashes(ct, os.path.dirname(file_path))

    # Generate torrent filename
    torrent_name = f"{name}.torrent"
    torrent_path = ospath.join("encode", torrent_name)

    with open(torrent_path, "wb") as f:
        f.write(lt.bencode(ct.generate()))

    return torrent_path
