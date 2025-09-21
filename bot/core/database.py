# bot/core/database.py
from motor.motor_asyncio import AsyncIOMotorClient
from bot import Var

class MongoDB:
    def __init__(self, uri, database_name):
        self.client = AsyncIOMotorClient(uri or Var.MONGO_URI)
        self.db = self.client[database_name]
        # main collection keyed by bot token prefix
        self.animes = self.db.animes[Var.BOT_TOKEN.split(':')[0]]

    async def getAnime(self, ani_id):
        """Get anime document by ani_id"""
        anime_doc = await self.animes.find_one({'_id': ani_id})
        return anime_doc or {}

    async def saveAnime(self, ani_id, ep_no, qual, post_id=None):
        """Mark quality as uploaded and store post_id"""
        anime_doc = await self.getAnime(ani_id)
        episodes = anime_doc.get("episodes", {})

        ep_info = episodes.get(str(ep_no), {q: False for q in Var.QUALS})
        ep_info[qual] = True
        episodes[str(ep_no)] = ep_info

        update_data = {"episodes": episodes}
        if post_id:
            update_data["msg_id"] = post_id  # global fallback for post

        await self.animes.update_one({'_id': ani_id}, {'$set': update_data}, upsert=True)

    async def getEpisodePost(self, ani_id, ep_no):
        """Return Telegram post_id for a given episode"""
        ani_data = await self.getAnime(ani_id)
        post_id = ani_data.get("episodes", {}).get(str(ep_no), {}).get("post_id")
        if post_id:
            return post_id
        return ani_data.get("msg_id")  # fallback global post_id

    async def saveEpisodePost(self, ani_id, ep_no, post_id):
        """Save post_id under episodes dict"""
        await self.animes.update_one(
            {'_id': ani_id},
            {'$set': {f"episodes.{ep_no}.post_id": post_id}},
            upsert=True
        )

    async def reboot(self):
        """Drop the collection (for testing)"""
        await self.animes.drop()


# instance for use
db = MongoDB(Var.MONGO_URI, "FZAutoAnimes")
