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
        doc = await self.animes.find_one({'_id': ani_id})
        return doc or {}

    async def saveAnime(self, ani_id, ep_no, qual, post_id=None):
        """Mark quality as uploaded for an episode, and save post_id"""
        # Fetch existing episode info
        anime_doc = await self.getAnime(ani_id)
        ep_info = anime_doc.get(str(ep_no), {}) if anime_doc else {}

        # Update the quality
        ep_info[qual] = True

        # Save episode info
        await self.animes.update_one(
            {'_id': ani_id},
            {'$set': {str(ep_no): ep_info}},
            upsert=True
        )

        # Save global post_id if provided
        if post_id:
            await self.animes.update_one(
                {'_id': ani_id},
                {'$set': {"msg_id": post_id}},
                upsert=True
            )

    async def getEpisodePost(self, ani_id, ep_no):
        """Return Telegram post_id for a given anime episode"""
        ani_data = await self.getAnime(ani_id)
        # Check if post_id saved for this episode
        ep_info = ani_data.get(str(ep_no), {})
        post_id = ep_info.get("post_id")
        if post_id:
            return post_id
        # Fallback: global msg_id
        return ani_data.get("msg_id")

    async def saveEpisodePost(self, ani_id, ep_no, post_id):
        """Save post_id specifically under episode info"""
        await self.animes.update_one(
            {'_id': ani_id},
            {'$set': {f"{ep_no}.post_id": post_id}},
            upsert=True
        )

    async def reboot(self):
        """Drop the collection (for testing)"""
        await self.animes.drop()


db = MongoDB(Var.MONGO_URI, "FZAutoAnimes")
