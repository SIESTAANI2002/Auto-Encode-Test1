# bot/core/database.py
from motor.motor_asyncio import AsyncIOMotorClient
from bot import Var

class MongoDB:
    def __init__(self, uri, database_name):
        self.__client = AsyncIOMotorClient(uri)
        self.__db = self.__client[database_name]
        self.__animes = self.__db.animes[Var.BOT_TOKEN.split(':')[0]]

    async def getAnime(self, ani_id):
        """Get anime document by ani_id"""
        botset = await self.__animes.find_one({'_id': ani_id})
        return botset or {}

    async def saveAnime(self, ani_id, ep_no, qual, post_id=None):
        """Mark quality as uploaded for an episode, and save post_id without overwriting others."""
        anime_doc = await self.getAnime(ani_id)

        # always ensure episodes dict exists
        episodes = anime_doc.get("episodes", {})
        ep_info = episodes.get(str(ep_no), {q: False for q in Var.QUALS})

        # mark this quality as uploaded
        ep_info[qual] = True

        # optionally attach post_id
        if post_id:
            ep_info["post_id"] = post_id

        # save back into episodes
        episodes[str(ep_no)] = ep_info

        await self.__animes.update_one(
            {"_id": ani_id},
            {"$set": {"episodes": episodes}},
            upsert=True
        )

    async def getEpisodePost(self, ani_id, ep_no):
        """Return Telegram post_id for a given anime episode"""
        ani_data = await self.getAnime(ani_id)
        # look inside episodes dict
        post_id = ani_data.get("episodes", {}).get(str(ep_no), {}).get("post_id")
        if post_id:
            return post_id
        # fallback: global msg_id saved for anime
        return ani_data.get("msg_id")

    async def saveEpisodePost(self, ani_id, ep_no, post_id):
        """Save post_id specifically under episodes dict"""
        anime_doc = await self.getAnime(ani_id)
        episodes = anime_doc.get("episodes", {})
        ep_info = episodes.get(str(ep_no), {q: False for q in Var.QUALS})
        ep_info["post_id"] = post_id
        episodes[str(ep_no)] = ep_info
        await self.__animes.update_one(
            {"_id": ani_id},
            {"$set": {"episodes": episodes}},
            upsert=True
        )

    async def reboot(self):
        """Drop the collection (for testing)"""
        await self.__animes.drop()


db = MongoDB(Var.MONGO_URI, "FZAutoAnimes")
