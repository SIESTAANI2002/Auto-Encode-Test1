# bot/core/database.py
from motor.motor_asyncio import AsyncIOMotorClient
from bot import Var

class MongoDB:
    def __init__(self, uri, database_name):
        self.client = AsyncIOMotorClient(uri)
        self.db = self.client[database_name]
        self.animes = self.db.animes[Var.BOT_TOKEN.split(':')[0]]

    async def getAnime(self, ani_id):
        """Get anime document by ani_id"""
        anime_doc = await self.animes.find_one({'_id': ani_id})
        return anime_doc or {}

    async def saveAnime(self, ani_id, ep_no, qual, post_id=None):
        """Mark a quality as uploaded for an episode, and save post_id"""
        anime_doc = await self.getAnime(ani_id)
        episodes = anime_doc.get("episodes", {})

        # update episode info
        ep_info = episodes.get(str(ep_no), {q: False for q in Var.QUALS})
        ep_info[qual] = True

        # save post_id if not already set
        if post_id:
            ep_info["post_id"] = post_id

        episodes[str(ep_no)] = ep_info

        await self.animes.update_one(
            {'_id': ani_id},
            {'$set': {"episodes": episodes}},
            upsert=True
        )

    async def getEpisodePost(self, ani_id, ep_no):
        """Return Telegram post_id for a given anime episode"""
        anime_doc = await self.getAnime(ani_id)
        episodes = anime_doc.get("episodes", {})
        ep_info = episodes.get(str(ep_no), {})
        return ep_info.get("post_id")

    async def saveEpisodePost(self, ani_id, ep_no, post_id):
        """Save post_id specifically under episodes dict"""
        await self.animes.update_one(
            {'_id': ani_id},
            {'$set': {f"episodes.{ep_no}.post_id": post_id}},
            upsert=True
        )

    async def reboot(self):
        """Drop the collection (for testing)"""
        await self.animes.drop()


db = MongoDB(Var.MONGO_URI, "FZAutoAnimes")
