# bot/database.py
from motor.motor_asyncio import AsyncIOMotorClient
from bot import Var

class MongoDB:
    def __init__(self, uri, database_name):
        self.__client = AsyncIOMotorClient(uri)
        self.__db = self.__client[database_name]
        # one collection per bot token (to isolate multiple bots if used)
        self.__animes = self.__db[Var.BOT_TOKEN.split(':')[0]]

    async def getAnime(self, ani_id):
        """Get anime document by ani_id"""
        return await self.__animes.find_one({'_id': ani_id}) or {}

    async def saveAnime(self, ani_id, ep_no, qual, post_id=None):
        """
        Save episode info:
        {
            "_id": ani_id,
            "episodes": {
                "12": {
                    "qualities": { "720": true, "1080": true },
                    "post_id": 555
                }
            }
        }
        """
        # mark quality as uploaded
        update_data = {f"episodes.{ep_no}.qualities.{qual}": True}
        if post_id:
            update_data[f"episodes.{ep_no}.post_id"] = post_id

        await self.__animes.update_one(
            {"_id": ani_id},
            {"$set": update_data},
            upsert=True
        )

    async def getEpisodePost(self, ani_id, ep_no):
        """Return Telegram post_id for a given anime episode"""
        doc = await self.__animes.find_one(
            {"_id": ani_id},
            {f"episodes.{ep_no}.post_id": 1}
        )
        if doc:
            return doc.get("episodes", {}).get(ep_no, {}).get("post_id")
        return None

    async def reboot(self):
        """Drop the collection (for testing)"""
        await self.__animes.drop()


db = MongoDB(Var.MONGO_URI, "FZAutoAnimes")
