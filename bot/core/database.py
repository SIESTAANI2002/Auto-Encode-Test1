# bot/database.py
from motor.motor_asyncio import AsyncIOMotorClient
from bot import Var

class MongoDB:
    def __init__(self, uri, database_name):
        self.client = AsyncIOMotorClient(uri)
        self.db = self.client[database_name]
        self.animes = self.db.animes[Var.BOT_TOKEN.split(':')[0]]

    async def getAnime(self, ani_id):
        """Get anime document by ani_id"""
        botset = await self.animes.find_one({'_id': ani_id})
        return botset or {}

    async def saveAnime(self, ani_id, ep_no, qual, post_id=None):
        """Mark quality as uploaded for an episode, and save post_id"""
        anime_doc = await self.getAnime(ani_id)
        ep_info = anime_doc.get(ep_no, {q: False for q in Var.QUALS})
        ep_info[qual] = True
        await self.animes.update_one(
            {'_id': ani_id},
            {'$set': {str(ep_no): ep_info}},
            upsert=True
        )
        if post_id:
            await self.animes.update_one(
                {'_id': ani_id},
                {'$set': {"msg_id": post_id}},
                upsert=True
            )

    async def getEpisodePost(self, ani_id, ep_no):
        """Return Telegram post_id for a given anime episode"""
        ani_data = await self.getAnime(ani_id)
        post_id = ani_data.get("episodes", {}).get(ep_no, {}).get("post_id")
        if post_id:
            return post_id
        return ani_data.get("msg_id")

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
