import feedparser
import asyncio
from .base import NewsItem, NewsSourcePlugin
from datetime import datetime

class RssNewsSource(NewsSourcePlugin):
    name = "RSS订阅"
    source_id = "rss"
    refresh_interval = 3600
    
    FEEDS = [
        "http://www.chinanews.com.cn/rss/finance.xml",
    ]
    
    async def fetch(self, feeds=None, **kwargs):
        if feeds is None:
            feeds = self.FEEDS
        
        loop = asyncio.get_event_loop()
        items = []
        for feed_url in feeds:
            try:
                feed = await loop.run_in_executor(None, feedparser.parse, feed_url)
                for entry in feed.entries[:20]:
                    items.append(NewsItem(
                        source=self.source_id,
                        title=entry.get('title', ''),
                        content=entry.get('summary', ''),
                        url=entry.get('link', ''),
                        timestamp=datetime(*entry.published_parsed[:6]) if hasattr(entry, 'published_parsed') else None,
                        hot_score=0
                    ))
            except Exception as e:
                print(f"[rss] {feed_url} error: {e}")
        return items
