"""统一情报采集器 — 并发拉取所有已激活的新闻源"""
import asyncio
import json
import os
from typing import List
from .base import NewsItem, EventSignal

# 动态导入所有source
from .orz_hot import OrzHotSource
from .cls_flash import ClsFlashSource
from .eastmoney_news import EastmoneyNewsSource
from .wallstreetcn import WallstreetcnSource
from .rss_source import RssNewsSource
from .jiucaigongshe import JiucaigongsheSource

ALL_SOURCES = {
    'orz_hot': OrzHotSource(),
    'cls': ClsFlashSource(),
    'eastmoney': EastmoneyNewsSource(),
    'wallstreetcn': WallstreetcnSource(),
    'rss': RssNewsSource(),
    'jiucaigongshe': JiucaigongsheSource(),
}

async def collect_all(active_sources=None, finance_keywords=None):
    """并发采集所有激活的新闻源"""
    if active_sources is None:
        active_sources = ['orz_hot', 'cls', 'eastmoney', 'wallstreetcn']
    
    tasks = []
    for src_id in active_sources:
        if src_id in ALL_SOURCES:
            kwargs = {}
            if finance_keywords and src_id == 'orz_hot':
                kwargs['finance_keywords'] = finance_keywords
            tasks.append(ALL_SOURCES[src_id].fetch(**kwargs))
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    all_items = []
    for r in results:
        if isinstance(r, list):
            all_items.extend(r)
    
    # 去重
    seen = set()
    deduped = []
    for item in all_items:
        key = item.dedup_key()
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    
    return deduped

def collect_sync(active_sources=None):
    """同步包装器"""
    return asyncio.run(collect_all(active_sources))
