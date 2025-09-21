# bot/core/database.py
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from bot import Var

class Database:
    def __init__(self, uri=None, name="AnimeDB"):
        self.client = AsyncIOMotorClient(uri or Var.MONOGO_URI)
        self.db = self.client[name]
        self.animes = self.db.animes   # stores { ani_id: { ep_no: { qual: post_id }, ... } }
        self.episodes = self.db.episodes  # stores { (ani_id, ep_no): post_id }

    async def getAnime(self, ani_id: str | int) -> dict:
        """Return anime document or {}."""
        doc = await self.animes.find_one({"_id": str(ani_id)})
        return doc or {}

    async def saveAnime(self, ani_id: str | int, ep_no: str, qual: str, post_id: int):
        """Save one episode quality for anime."""
        ani_id = str(ani_id)
        ep_no = str(ep_no)
        update = {
            "$set": {f"{ep_no}.{qual}": post_id}
        }
        await self.animes.update_one({"_id": ani_id}, update, upsert=True)

    async def getEpisodePost(self, ani_id: str | int, ep_no: str) -> int | None:
        """Return stored post_id for episode if exists."""
        ani_id = str(ani_id)
        ep_no = str(ep_no)
        key = f"{ani_id}:{ep_no}"
        doc = await self.episodes.find_one({"_id": key})
        return doc["post_id"] if doc else None

    async def saveEpisodePost(self, ani_id: str | int, ep_no: str, post_id: int):
        """Save mapping (ani_id, ep_no) -> post_id."""
        ani_id = str(ani_id)
        ep_no = str(ep_no)
        key = f"{ani_id}:{ep_no}"
        await self.episodes.update_one(
            {"_id": key},
            {"$set": {"post_id": post_id}},
            upsert=True
        )

    async def deleteEpisode(self, ani_id: str | int, ep_no: str):
        """Remove one episode from both collections."""
        ani_id = str(ani_id)
        ep_no = str(ep_no)
        await self.animes.update_one({"_id": ani_id}, {"$unset": {ep_no: ""}})
        await self.episodes.delete_one({"_id": f"{ani_id}:{ep_no}"})


# global instance
db = Database()
