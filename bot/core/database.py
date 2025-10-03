# bot/core/database.py
from motor.motor_asyncio import AsyncIOMotorClient  
from bot import Var  

class MongoDB:
    def __init__(self, uri: str, db_name: str = "animebot"):
        self.client = motor.motor_asyncio.AsyncIOMotorClient(uri)
        self.db = self.client[db_name]

        # collections
        self.animes = self.db["animes"]       # stores anime -> episode -> quality -> msg_id
        self.user_animes = self.db["user_animes"]  # stores which user got which quality

    # --------------------
    # Anime storage
    # --------------------
    async def saveAnime(self, ani_id: str, ep_no: str, qual: str, msg_id: int):
        """
        Save msg_id for a specific anime-episode-quality.
        """
        await self.animes.update_one(
            {"ani_id": str(ani_id)},
            {"$set": {f"episodes.{ep_no}.{qual}": msg_id}},
            upsert=True
        )

    async def getAnime(self, ani_id: str):
        """
        Get dict of episodes for this anime.
        """
        doc = await self.animes.find_one({"ani_id": str(ani_id)})
        return doc.get("episodes", {}) if doc else {}

    # --------------------
    # User tracking
    # --------------------
    async def mark_user_anime(self, user_id: int, ani_id: str, ep_no: str, qual: str):
        """
        Mark that a user has received a specific anime episode quality.
        """
        await self.user_animes.update_one(
            {"user_id": int(user_id)},
            {"$set": {f"received.{ani_id}.{ep_no}.{qual}": True}},
            upsert=True
        )

    async def get_user_anime(self, user_id: int, ani_id: str, ep_no: str, qual: str):
        """
        Check if a user already received a specific anime episode quality.
        """
        doc = await self.user_animes.find_one({"user_id": int(user_id)})
        if not doc:
            return False
        return (
            doc.get("received", {})
                .get(str(ani_id), {})
                .get(str(ep_no), {})
                .get(str(qual), False)
        )
        
# ----------------------
    # Drop all anime data
    # ----------------------
    async def reboot(self):
        await self.__animes.drop()

# Single instance
db = MongoDB(Var.MONGO_URI, "FZAutoAnimes")
