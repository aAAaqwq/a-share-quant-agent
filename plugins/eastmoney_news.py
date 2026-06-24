"""东方财富新闻 — 使用AKShare"""
from .base import NewsItem, NewsSourcePlugin
from datetime import datetime


class EastmoneyNewsSource(NewsSourcePlugin):
    name = "东方财富要闻"
    source_id = "eastmoney"
    refresh_interval = 300

    async def fetch(self, **kwargs):
        items = []
        try:
            import akshare as ak

            df = ak.stock_news_em()
            for _, row in df.head(30).iterrows():
                items.append(
                    NewsItem(
                        source=self.source_id,
                        title=row.get("新闻标题", ""),
                        content=row.get("新闻内容", ""),
                        url=row.get("新闻链接", ""),
                        timestamp=datetime.now(),
                        hot_score=0,
                        tags=[row.get("关键词", "")],
                    )
                )
        except Exception as e:
            print(f"[eastmoney] error: {e}")
        return items
