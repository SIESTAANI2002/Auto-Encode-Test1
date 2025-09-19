# cleanup_db.py
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from bot import Var

async def cleanup():
    client = AsyncIOMotorClient(Var.MONGO_URI)
    db = client["FZAutoAnimes"]
    col = db.animes[Var.BOT_TOKEN.split(":")[0]]

    cursor = col.find({})
    async for doc in cursor:
        updates = {}
        for key, value in doc.items():
            # if episode key is not under "episodes", move it there
            if key.isdigit():  
                ep_no = key
                if "episodes" not in updates:
                    updates["episodes"] = {}
                updates["episodes"][ep_no] = {
                    "post_id": doc.get("msg_id"),   # reuse msg_id if available
                    **value                         # keep qual flags
                }
                updates.pop(key, None)  # mark old key for removal

        if updates:
            # update doc properly
            await col.update_one({"_id": doc["_id"]}, {"$set": updates})
            print(f"✅ Cleaned {doc['_id']}")

    print("🎉 Cleanup done.")

if __name__ == "__main__":
    asyncio.run(cleanup())
