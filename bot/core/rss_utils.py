# bot/core/rss_utils.py

import feedparser
from bot import LOGS

async def getfeed(url: str, retry: int = 1):
    """
    Async wrapper to fetch RSS feed using feedparser.
    Returns feed object or None on failure.
    """
    try:
        feed = feedparser.parse(url)
        if not feed.entries:
            LOGS.error(f"❌ Empty feed: {url}")
            return None
        return feed
    except Exception as e:
        LOGS.error(f"[ERROR] Failed to fetch RSS feed {url}: {e}")
        if retry > 0:
            return await getfeed(url, retry=retry-1)
        return None
