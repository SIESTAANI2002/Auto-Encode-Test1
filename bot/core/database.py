# bot/core/database.py
from motor.motor_asyncio import AsyncIOMotorClient
from bot import Var

class MongoDB:
    def __init__(self, uri, database_name):
        self.__client = AsyncIOMotorClient(uri)
        self.__db = self.__client[database_name]
        # Each bot gets its own collection
        self.__animes = self.__db.animes[Var.BOT_TOKEN.split(':')[0]]

    # ----------------- Basic Anime DB ----------------- #
    async def getAnime(self, ani_id):
        doc = await self.__animes.find_one({'_id': ani_id})
        return doc or {}

    async def saveAnime(self, ani_id, ep, qual, post_id=None):
        """
        Save episode info + msg_id of posted message.
        ep stored as str (Mongo keys must be str).
        """
        ep_key = str(ep)
        anime = await self.getAnime(ani_id)

        # base structure
        ep_data = anime.get(ep_key, {})
        qual_data = ep_data.get(qual, {})

        # preserve existing users, just mark as available
        ep_data[qual] = qual_data  

        update_fields = {ep_key: ep_data}
        if post_id:
            update_fields["msg_id"] = post_id

        await self.__animes.update_one(
            {'_id': ani_id},
            {'$set': update_fields},
            upsert=True
        )

    async def getAllAnime(self):
        cursor = self.__animes.find({})
        docs = await cursor.to_list(length=None)
        return {doc["_id"]: doc for doc in docs if "_id" in doc}

    async def reboot(self):
        await self.__animes.drop()

    # ------------- Per-user delivery tracking ------------- #
    async def hasUserReceived(self, ani_id, ep, qual, user_id):
        """
        Check if user has already received this episode in this quality.
        """
        anime = await self.getAnime(ani_id)
        ep_data = anime.get(str(ep), {})
        qual_data = ep_data.get(qual, {})
        return qual_data.get(str(user_id), False)

    async def markUserReceived(self, ani_id, ep, qual, user_id):
        """
        Mark that user has received this file.
        """
        ep_key = str(ep)
        anime = await self.getAnime(ani_id)
        ep_data = anime.get(ep_key, {})
        qual_data = ep_data.get(qual, {})

        qual_data[str(user_id)] = True
        ep_data[qual] = qual_data

        await self.__animes.update_one(
            {'_id': ani_id},
            {'$set': {ep_key: ep_data}},
            upsert=True
        )

db = MongoDB(Var.MONGO_URI, "FZAutoAnimes")
