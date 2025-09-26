# bot/core/tokyo_torrent.py
import libtorrent as lt
import os
from os import path as ospath
from datetime import datetime

async def generate_torrent(file_path: str, name: str, announce_list=None, piece_size=0):
    """
    Generate a .torrent file from the given file_path.
    Returns the path of the generated torrent.
    """
    if not ospath.exists(file_path):
        raise FileNotFoundError(f"File does not exist: {file_path}")

    # Create a file storage
    fs = lt.file_storage()
    lt.add_files(fs, file_path)

    # Create the torrent
    ct = lt.create_torrent(fs, piece_size=piece_size)
    if announce_list:
        for tier in announce_list:
            ct.add_tracker(tier)

    # Calculate piece hashes
    lt.set_piece_hashes(ct, os.path.dirname(file_path))

    # Convert file hashes to proper types
    for idx in range(fs.num_files()):
        f = fs.file_path(idx)
        # Already hashed in set_piece_hashes, no need to call set_file_hash manually
        # Just ensure idx type is correct if needed:
        idx_obj = lt.file_index(idx)
        # This line can be skipped as set_piece_hashes handles it:
        # ct.set_file_hash(idx_obj, lt.sha1_hash(...))  

    # Generate torrent filename
    torrent_name = f"{name}.torrent"
    torrent_path = ospath.join("encode", torrent_name)

    with open(torrent_path, "wb") as f:
        f.write(lt.bencode(ct.generate()))

    return torrent_path
