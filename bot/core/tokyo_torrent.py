# bot/core/tokyo_torrent.py
import libtorrent as lt
from os import path as ospath
from datetime import datetime
from pathlib import Path

async def generate_torrent(file_path: str, name: str = None, tracker: str = "udp://tracker.opentrackr.org:1337/announce") -> str:
    """
    Generate a .torrent file from a given file path.

    Args:
        file_path (str): Path to the encoded file.
        name (str, optional): Custom name for the torrent file. Defaults to file's basename.
        tracker (str, optional): Tracker URL. Defaults to Opentrackr UDP tracker.

    Returns:
        str: Path to the generated .torrent file.
    """
    if not ospath.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    file_path_obj = Path(file_path)
    torrent_name = name or file_path_obj.stem
    torrent_path = Path("torrents") / f"{torrent_name}.torrent"
    torrent_path.parent.mkdir(exist_ok=True)

    fs = lt.file_storage()
    lt.add_files(fs, str(file_path_obj))
    
    ct = lt.create_torrent(fs)
    ct.add_tracker(tracker)
    ct.set_creator("AnimeBot")

    # Generate piece hashes
    lt.set_piece_hashes(ct, str(file_path_obj.parent))
    
    torrent_content = ct.generate()
    with open(torrent_path, "wb") as f:
        f.write(lt.bencode(torrent_content))

    return str(torrent_path)
