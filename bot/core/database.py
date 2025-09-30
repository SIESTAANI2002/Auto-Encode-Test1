from motor.motor_asyncio import AsyncIOMotorClient
from bot import Var

class MongoDB:
    def __init__(self, uri, database_name):
        self.__client = AsyncIOMotorClient(uri)
        self.__db = self.__client[database_name]
        self.__animes = self.__db.animes[Var.BOT_TOKEN.split(':')[0]]

    # ----------------- Basic Anime DB ----------------- #
    async def getAnime(self, ani_id):
        botset = await self.__animes.find_one({'_id': ani_id})
        return botset or {}

    async def saveAnime(self, ani_id, ep, qual, post_id=None):
        ep_key = str(ep)  # <--- convert ep to string for MongoDB
        quals = (await self.getAnime(ani_id)).get(ep_key, {qual: False for qual in Var.QUALS})
        quals[qual] = True
        await self.__animes.update_one({'_id': ani_id}, {'$set': {ep_key: quals}}, upsert=True)
        if post_id:
            await self.__animes.update_one(
                {'_id': ani_id},
                {'$set': {"msg_id": post_id}},
                upsert=True
            )

    async def getAllAnime(self):
        cursor = self.__animes.find({})
        all_docs = await cursor.to_list(length=None)
        return {doc["_id"]: doc for doc in all_docs if "_id" in doc}

    async def reboot(self):
        await self.__animes.drop()

    # ------------- Per-user delivery tracking ------------- #
    async def hasUserReceived(self, ani_id, ep, qual, user_id):
        """
        Check if a user has already received a specific quality of a specific episode.
        """
        anime = await self.getAnime(ani_id)
        ep_data = anime.get(str(ep), {})        # ep as string key
        qual_data = ep_data.get(qual, {})
        return qual_data.get(str(user_id), False)  # user_id as string

    async def markUserReceived(self, ani_id, ep, qual, user_id):
        """
        Mark that a user has received this file.
        """
        anime = await self.getAnime(ani_id)
        ep_key = str(ep)
        ep_data = anime.get(ep_key, {})
        qual_data = ep_data.get(qual, {})

        # Use user_id as key
        qual_data[str(user_id)] = True
        ep_data[qual] = qual_data

        await self.__animes.update_one(
            {'_id': ani_id},
            {'$set': {ep_key: ep_data}},  # ep as string key
            upsert=True
        )

db = MongoDB(Var.MONGO_URI, "FZAutoAnimes")
