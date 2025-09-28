import libtorrent as lt
import os
import asyncio
from datetime import datetime
from bot import Var, bot, LOGS
from .reporter import rep
from .tokyo_upload import upload_to_tokyo

async def generate_torrent(file_path, name):
    try:
        # Make sure encode dir exists
        os.makedirs("torrents", exist_ok=True)

        # Torrent output path
        torrent_path = os.path.join("torrents", f"{name}.torrent")

        fs = lt.file_storage()
        lt.add_files(fs, file_path)
        t = lt.create_torrent(fs)

        t.add_tracker("udp://tracker.openbittorrent.com:80")
        t.add_tracker("udp://tracker.opentrackr.org:1337")
        t.add_tracker("udp://tracker.coppersurfer.tk:6969")

        t.set_creator("AnimeToki Bot")

        lt.set_piece_hashes(t, os.path.dirname(file_path))
        torrent = t.generate()

        with open(torrent_path, "wb") as f:
            f.write(lt.bencode(torrent))

        LOGS.info(f"[TokyoTosho] Torrent created: {name}")

        # ✅ Step 1: Send torrent file to log channel
        if os.path.exists(torrent_path):
            await bot.send_document(
                chat_id=Var.LOG_CHANNEL,
                document=torrent_path,
                caption=f"🌀 Torrent generated for <b>{name}</b>\nTime: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )

        # ✅ Step 2: Upload torrent to TokyoTosho
        success = await upload_to_tokyo(torrent_path, name)
        if success:
            await rep.report(f"✅ TokyoTosho Upload Success: {name}", "info")
        else:
            await rep.report(f"❌ TokyoTosho Upload Failed: {name}", "error")

        return torrent_path

    except Exception as e:
        await rep.report(f"[ERROR] TokyoTosho Torrent Exception ({name}): {e}", "error")
        return None
