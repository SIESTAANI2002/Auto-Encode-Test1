from motor.motor_asyncio import AsyncIOMotorClient
from bot import Var

class MongoDB:
    def __init__(self, uri, database_name):
        self.client = AsyncIOMotorClient(uri)
        self.db = self.client[database_name]
        self.animes = self.db.animes[Var.BOT_TOKEN.split(":")[0]]

    async def getAnime(self, ani_id):
        """Get anime document by ani_id"""
        doc = await self.animes.find_one({"_id": ani_id})
        return doc or {}

    async def saveAnime(self, ani_id, ep_no, qual, post_id=None):
        """Mark a quality as uploaded for an episode and save post_id"""
        ani_doc = await self.getAnime(ani_id)
        ep_no_str = str(ep_no)

        # Ensure episode exists
        episodes = ani_doc.get("episodes", {})
        if ep_no_str not in episodes:
            episodes[ep_no_str] = {q: False for q in Var.QUALS}

        # Mark quality as uploaded
        episodes[ep_no_str][qual] = True

        update_data = {"episodes": episodes}
        if post_id:
            update_data["episodes"][ep_no_str]["post_id"] = post_id

        await self.animes.update_one({"_id": ani_id}, {"$set": update_data}, upsert=True)

    async def getEpisodePost(self, ani_id, ep_no):
        """Return Telegram post_id for a given anime episode"""
        ani_doc = await self.getAnime(ani_id)
        ep_no_str = str(ep_no)
        episodes = ani_doc.get("episodes", {})
        return episodes.get(ep_no_str, {}).get("post_id")

    async def saveEpisodePost(self, ani_id, ep_no, post_id):
        """Save post_id for a specific episode"""
        ep_no_str = str(ep_no)
        await self.animes.update_one(
            {"_id": ani_id},
            {"$set": {f"episodes.{ep_no_str}.post_id": post_id}},
            upsert=True
        )

    async def reboot(self):
        """Drop the collection (for testing)"""
        await self.animes.drop()


db = MongoDB(Var.MONGO_URI, "FZAutoAnimes")
