import aiohttp
from .base import NewsItem, NewsSourcePlugin
from datetime import datetime

class WallstreetcnSource(NewsSourcePlugin):
    name = "华尔街见闻"
    source_id = "wallstreetcn"
    refresh_interval = 120
    
    API_URL = "https://api-one.wallstcn.com/apiv1/content/lives"
    
    async def fetch(self, count=30, **kwargs):
        params = {"channel": "global-channel", "limit": count}
        headers = {"User-Agent": "Mozilla/5.0"}
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(self.API_URL, params=params,
                                       headers=headers,
                                       timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    data = await resp.json()
            except Exception as e:
                print(f"[wallstreetcn] error: {e}")
                return []
        
        items = []
        for item in data.get('data', {}).get('items', []):
            title = item.get('title', '') or item.get('content_text', '')[:60]
            content = item.get('content_text', '')
            display_time = item.get('display_time', 0)
            items.append(NewsItem(
                source=self.source_id,
                title=title,
                content=content[:200],
                url=f"https://wallstreetcn.com/livenews/{item.get('id', '')}",
                timestamp=datetime.fromtimestamp(display_time) if display_time else None,
                hot_score=0
            ))
        return items
