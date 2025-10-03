# bot/core/database.py
from motor.motor_asyncio import AsyncIOMotorClient  
from bot import Var  

class MongoDB:
    def __init__(self, uri, database_name):
        self.__client = AsyncIOMotorClient(uri)
        self.__db = self.__client[database_name]
        self.__animes = self.__db.animes[Var.BOT_TOKEN.split(':')[0]]
        self.__user_animes = self.__db.user_animes  # collection for per-user tracking

    # ----------------------
    # Anime quality storage
    # ----------------------
    async def getAnime(self, ani_id):
        botset = await self.__animes.find_one({'_id': ani_id})
        return botset or {}

    async def saveAnime(self, ani_id, ep, qual, post_id=None):
        quals = (await self.getAnime(ani_id)).get(ep, {qual: False for qual in Var.QUALS})
        quals[qual] = True
        await self.__animes.update_one(
            {'_id': ani_id},
            {'$set': {ep: quals}},
            upsert=True
        )
        if post_id:
            await self.__animes.update_one(
                {'_id': ani_id},
                {'$set': {"msg_id": post_id}},
                upsert=True
            )

    # ----------------------
    # Per-user hit tracking (per-quality)
    # ----------------------
    async def get_user_anime(self, user_id, ani_id, qual=None):
        """
        Return True if user already got this anime quality.
        If qual is None, return the whole doc.
        """
        doc = await self.__user_animes.find_one({'user_id': user_id, 'anime_id': ani_id})
        if not doc:
            return False if qual else None
        if qual:
            return doc.get("got_files", {}).get(qual, False)
        return doc

    async def mark_user_anime(self, user_id, ani_id, qual):
        """
        Mark that user received this anime quality.
        Stores per-quality flags inside got_files.
        """
        doc = await self.__user_animes.find_one({'user_id': user_id, 'anime_id': ani_id})
        if doc:
            got_files = doc.get("got_files", {})
        else:
            got_files = {}
        got_files[qual] = True
        await self.__user_animes.update_one(
            {'user_id': user_id, 'anime_id': ani_id},
            {'$set': {'got_files': got_files}},
            upsert=True
        )

    # ----------------------
    # Drop all anime data
    # ----------------------
    async def reboot(self):
        await self.__animes.drop()
        await self.__user_animes.drop()

# Single instance
db = MongoDB(Var.MONGO_URI, "FZAutoAnimes")
