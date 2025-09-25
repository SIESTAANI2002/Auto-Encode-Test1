import libtorrent as lt
import asyncio
from os import path as ospath

async def generate_torrent(file_path: str, name: str, announce_url: str = "http://tracker.tokyotosho.info:2710/announce") -> str:
    """
    Generates a .torrent file from a given file or folder path.

    Args:
        file_path (str): Path to the file or folder to be turned into a torrent.
        name (str): Name for the torrent file.
        announce_url (str): Tracker announce URL for TokyoTosho.

    Returns:
        str: Path to the generated .torrent file.
    """
    if not ospath.exists(file_path):
        raise FileNotFoundError(f"Path does not exist: {file_path}")

    fs = lt.file_storage()
    lt.add_files(fs, file_path)
    if fs.num_files() == 0:
        raise ValueError("No files found in path to generate torrent")

    t = lt.create_torrent(fs)
    t.add_tracker(announce_url)
    t.set_creator("FZAutoAnimes Bot")

    torrent_path = f"{file_path}.torrent"
    torrent_data = t.generate()
    with open(torrent_path, "wb") as f:
        f.write(lt.bencode(torrent_data))

    return torrent_path
