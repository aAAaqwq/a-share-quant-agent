import asyncio
import aiohttp
from .base import NewsItem, NewsSourcePlugin
from datetime import datetime

class OrzHotSource(NewsSourcePlugin):
    name = "orz热点"
    source_id = "orz_hot"
    refresh_interval = 1800
    
    PLATFORMS = ["douyin", "jinritoutiao", "weibo", "zhihu", "baidu", "tskr"]
    BASE_URL = "https://orz.ai/api/v1/dailynews"
    
    async def fetch(self, platforms=None, finance_keywords=None, **kwargs):
        if platforms is None:
            platforms = self.PLATFORMS
        
        async with aiohttp.ClientSession() as session:
            tasks = []
            for p in platforms:
                url = f"{self.BASE_URL}?platform={p}"
                tasks.append(self._fetch_platform(session, url, p))
            results = await asyncio.gather(*tasks, return_exceptions=True)
        
        all_items = []
        for items in results:
            if isinstance(items, list):
                all_items.extend(items)
        return all_items
    
    async def _fetch_platform(self, session, url, platform):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()
                items = []
                for item in data.get('data', [])[:20]:  # 每平台取前20
                    items.append(NewsItem(
                        source=self.source_id,
                        title=item.get('title', ''),
                        content=item.get('desc', ''),
                        url=item.get('url', ''),
                        hot_score=float(item.get('score', 0)),
                        tags=[platform]
                    ))
                return items
        except Exception as e:
            print(f"[orz_hot] {platform} error: {e}")
            return []
