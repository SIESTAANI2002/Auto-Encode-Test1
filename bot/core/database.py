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
            await self.__animes.update_one(
                {'_id': ani_id},
                {'$set': {"msg_id": post_id}},
                upsert=True
            )

    async def getAllAnime(self):
        cursor = self.__animes.find({})
        all_docs = await cursor.to_list(length=None)
        # return dict with ani_id as key
        return {doc["_id"]: doc for doc in all_docs if "_id" in doc}

    async def reboot(self):
        await self.__animes.drop()

    # -------------------- Per-user delivery -------------------- #
    async def hasUserReceived(self, ani_id, ep, qual, user_id):
        """
        Check if a user has already received a specific quality of a specific episode.
        """
        anime = await self.getAnime(ani_id)
        ep_data = anime.get(ep, {})
        qual_data = ep_data.get(qual, {})
        return qual_data.get(str(user_id), False)

    async def markUserReceived(self, ani_id, ep, qual, user_id):
        """
        Mark that a user has received this file.
        """
        anime = await self.getAnime(ani_id)
        ep_data = anime.get(ep, {})
        qual_data = ep_data.get(qual, {})

        # Use user_id as key for this quality
        qual_data[str(user_id)] = True
        ep_data[qual] = qual_data

        await self.__animes.update_one(
            {'_id': ani_id},
            {'$set': {ep: ep_data}},
            upsert=True
        )

db = MongoDB(Var.MONGO_URI, "FZAutoAnimes")
