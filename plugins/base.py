"""情报源插件基类"""
from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime
import hashlib

@dataclass
class NewsItem:
    """统一新闻条目"""
    source: str          # 数据源ID: orz_hot, cls, eastmoney...
    title: str           # 标题
    content: str = ""    # 正文/摘要
    url: str = ""        # 原文链接
    timestamp: Optional[datetime] = None
    tags: List[str] = field(default_factory=list)
    hot_score: float = 0.0  # 热度 0-100
    
    def __hash__(self):
        return hash(self.title + self.source)
    
    def dedup_key(self) -> str:
        """去重key: 标题前30字符 + 来源"""
        key = self.title[:30] + self.source
        return hashlib.md5(key.encode()).hexdigest()

@dataclass
class EventSignal:
    """事件信号"""
    news: NewsItem
    keywords: List[str] = field(default_factory=list)
    matched_sectors: List[str] = field(default_factory=list)
    impact_direction: str = "中性"  # 利好/利空/中性
    impact_level: str = "中"       # 强/中/弱
    related_stocks: List[dict] = field(default_factory=list)

class NewsSourcePlugin:
    """情报源插件基类 — 所有新闻源必须继承此类"""
    name: str = "base"
    source_id: str = "base"
    refresh_interval: int = 1800  # 秒
    
    async def fetch(self, **kwargs) -> List[NewsItem]:
        """获取新闻 — 子类必须实现"""
        raise NotImplementedError
    
    def filter_finance(self, items: List[NewsItem], keywords: List[str]) -> List[NewsItem]:
        """过滤财经相关内容"""
        return [item for item in items 
                if any(kw in item.title for kw in keywords)]
