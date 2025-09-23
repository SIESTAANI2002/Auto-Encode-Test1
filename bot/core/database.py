# bot/core/database.py
from motor.motor_asyncio import AsyncIOMotorClient
from bot import Var

class MongoDB:
    def __init__(self, uri, database_name):
        self.client = AsyncIOMotorClient(uri)
        self.db = self.client[database_name]
        self.animes = self.db.animes[Var.BOT_TOKEN.split(':')[0]]

    async def getAnime(self, ani_id):
        """Fetch anime document by ani_id"""
        doc = await self.animes.find_one({'_id': ani_id})
        return doc or {}

    async def saveAnime(self, ani_id, ep_no, qual, post_id=None):
        """
        Save that a quality has been uploaded for a specific episode.
        Also saves the post_id for the episode.
        """
        anime_doc = await self.getAnime(ani_id)
        episodes = anime_doc.get("episodes", {})
        ep_info = episodes.get(str(ep_no), {q: False for q in Var.QUALS})
        ep_info[qual] = True
        episodes[str(ep_no)] = ep_info

        update_data = {"episodes": episodes}
        if post_id:
            update_data["msg_id"] = post_id

        await self.animes.update_one({'_id': ani_id}, {'$set': update_data}, upsert=True)

    async def getEpisodePost(self, ani_id, ep_no):
        """Return Telegram post_id for a given episode"""
        doc = await self.getAnime(ani_id)
        # Check per-episode post first
        episodes = doc.get("episodes", {})
        post_id = episodes.get(str(ep_no), {}).get("post_id")
        if post_id:
            return post_id
        # fallback to global msg_id
        return doc.get("msg_id")

    async def saveEpisodePost(self, ani_id, ep_no, post_id):
        """Save post_id for a specific episode"""
        await self.animes.update_one(
            {'_id': ani_id},
            {'$set': {f"episodes.{ep_no}.post_id": post_id}},
            upsert=True
        )

    async def reboot(self):
        """Drop the collection (for testing only)"""
        await self.animes.drop()


# Initialize the database
db = MongoDB(Var.MONGO_URI, "FZAutoAnimes")
