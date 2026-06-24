from .base import NewsItem, NewsSourcePlugin

class WebSearchSource(NewsSourcePlugin):
    name = "关键词搜索"
    source_id = "web_search"
    refresh_interval = 0  # 按需触发
    
    async def fetch(self, **kwargs):
        # 通过OpenClaw的web_search工具实现
        # 这里只留接口
        return []
