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

    async def getEpisodePost(self, ani_id, ep_no):
        """
        Returns the Telegram post ID for a given anime episode if it exists.
        """
        anime_data = await self.getAnime(ani_id)
        if anime_data:
            # Check if episode exists
            episode_data = anime_data.get(ep_no)
            if episode_data:
                # If we saved post_id under 'msg_id' (as in saveAnime), return it
                post_id = anime_data.get("msg_id")
                if post_id:
                    return post_id
        return None

    async def reboot(self):
        await self.__animes.drop()

db = MongoDB(Var.MONGO_URI, "FZAutoAnimes")
