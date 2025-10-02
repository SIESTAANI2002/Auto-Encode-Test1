from motor.motor_asyncio import AsyncIOMotorClient
from bot import Var

class MongoDB:
    def __init__(self, uri, database_name):
        self.__client = AsyncIOMotorClient(uri)
        self.__db = self.__client[database_name]
        self.__animes = self.__db.animes[Var.BOT_TOKEN.split(':')[0]]

    # ----------------- Basic Anime DB ----------------- #
    async def getAnime(self, ani_id):
        doc = await self.__animes.find_one({'_id': ani_id})
        return doc or {}

    async def saveAnime(self, ani_id, ep, qual, msg_id=None, post_id=None):
        ep_key = str(ep)
        anime = await self.getAnime(ani_id)
        episodes = anime.get('episodes', {})

        ep_doc = episodes.get(ep_key, {})
        qual_doc = ep_doc.get(qual, {})

        if msg_id is not None:
            qual_doc['msg_id'] = int(msg_id)
        qual_doc['uploaded'] = True

        ep_doc[qual] = qual_doc
        episodes[ep_key] = ep_doc

        update = {'episodes': episodes}
        if post_id is not None:
            update['post_id'] = int(post_id)

        await self.__animes.update_one({'_id': ani_id}, {'$set': update}, upsert=True)

    async def getEpisodeFileInfo(self, ani_id, ep, qual):
        anime = await self.getAnime(ani_id)
        return anime.get('episodes', {}).get(str(ep), {}).get(qual, {})

    # ------------- Per-user delivery tracking ------------- #
    async def hasUserReceived(self, ani_id, ep, qual, user_id):
        ep_info = (await self.getEpisodeFileInfo(ani_id, ep, qual)) or {}
        users = ep_info.get('users', {})
        return str(user_id) in users

    async def markUserReceived(self, ani_id, ep, qual, user_id):
        ani_doc = await self.getAnime(ani_id)
        episodes = ani_doc.get('episodes', {})
        ep_key = str(ep)
        ep_doc = episodes.get(ep_key, {})
        qual_doc = ep_doc.get(qual, {})

        users = qual_doc.get('users', {})
        users[str(user_id)] = True
        qual_doc['users'] = users

        ep_doc[qual] = qual_doc
        episodes[ep_key] = ep_doc

        await self.__animes.update_one({'_id': ani_id}, {'$set': {'episodes': episodes}}, upsert=True)

# singleton db
db = MongoDB(Var.MONGO_URI, "FZAutoAnimes")
