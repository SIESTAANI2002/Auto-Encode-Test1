# bot/core/tokyo_torrent.py
import os
import libtorrent as lt
from pathlib import Path
from datetime import datetime

TORRENT_DIR = "torrents"

# Ensure torrents directory exists
os.makedirs(TORRENT_DIR, exist_ok=True)

async def generate_torrent(file_path: str, name: str) -> str:
    """
    Generate a v1 torrent file for TokyoTosho upload.
    
    Args:
        file_path (str): Path to the encoded file.
        name (str): Name to use for the torrent.
    
    Returns:
        str: Path to the generated .torrent file.
    """
    path_obj = Path(file_path)
    
    if not path_obj.exists():
        raise FileNotFoundError(f"File does not exist: {file_path}")
    
    fs = lt.file_storage()
    
    if path_obj.is_file():
        lt.add_files(fs, str(path_obj))
        base_path = path_obj.parent
    else:
        lt.add_files(fs, str(path_obj))
        base_path = path_obj

    t = lt.create_torrent(fs)
    
    # Set piece size automatically (optional)
    t.set_creator("FZAutoAnimes Bot")
    
    # Include modification time
    for i in range(fs.num_files()):
        t.set_file_hash(i, lt.sha1_hash())
    
    torrent_file_name = f"{name}.torrent"
    torrent_path = os.path.join(TORRENT_DIR, torrent_file_name)
    
    with open(torrent_path, "wb") as f:
        f.write(lt.bencode(t.generate()))
    
    return torrent_path
