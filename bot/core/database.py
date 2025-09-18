from motor.motor_asyncio import AsyncIOMotorClient
from bot import Var

class MongoDB:
    def __init__(self, uri, database_name):
        self.__client = AsyncIOMotorClient(uri)
        self.__db = self.__client[database_name]
        self.__animes = self.__db.animes[Var.BOT_TOKEN.split(':')[0]]

    async def getAnime(self, ani_id):
        botset = await self.__animes.find_one({'_id': ani_id})
        return botset or {}

    async def saveAnime(self, ani_id, ep, qual, post_id=None):
        quals = (await self.getAnime(ani_id)).get(ep, {qual: False for qual in Var.QUALS})
        quals[qual] = True
        await self.__animes.update_one({'_id': ani_id}, {'$set': {ep: quals}}, upsert=True)
        if post_id:
            await self.__animes.update_one({'_id': ani_id}, {'$set': {"msg_id": post_id}}, upsert=True)

    async def saveEpisodePost(self, ani_id, ep_no, post_id):
        """
        Saves the Telegram post ID for a specific anime episode.
        """
        await self.__animes.update_one(
            {'_id': ani_id},
            {'$set': {f"episodes.{ep_no}.post_id": post_id}},
            upsert=True
        )

    async def getEpisodePost(self, ani_id, ep_no):
        """
        Returns the Telegram post ID for a given anime episode if it exists.
        """
        ani_data = await self.getAnime(ani_id)
        return ani_data.get("episodes", {}).get(ep_no, {}).get("post_id")

    async def reboot(self):
        await self.__animes.drop()


# Instantiate the DB
db = MongoDB(Var.MONGO_URI, "FZAutoAnimes")
