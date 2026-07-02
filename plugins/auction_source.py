"""竞价数据源 — 可插拔

拉个股竞价/实时涨跌幅 + 大盘方向。集合竞价 9:15–9:25 期间, 全A实时快照的
"涨跌幅"即竞价撮合涨跌幅; 盘中则为实时涨跌幅。

可插拔: 现用东财 spot 快照(经 data_layer 熔断保护); 后续可换 L1 竞价专用源,
只要实现 AuctionSource 接口即可, 上层 auction_monitor / intraday_puller 不动。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class AuctionSource:
    """竞价数据源接口。"""

    name = "base"

    def fetch_quotes(self, codes: List[str]) -> Dict[str, float]:
        """{code: 涨跌幅%}。取不到的 code 直接不在返回里。"""
        raise NotImplementedError

    def fetch_market_pct(self) -> Optional[float]:
        """大盘竞价/实时方向涨幅%(方向判据)。取不到返回 None。"""
        raise NotImplementedError


class SpotAuctionSource(AuctionSource):
    """默认源: 全A实时快照(东财, 经 data_layer 熔断/降级)。

    竞价期间快照的"涨跌幅"= 竞价撮合涨跌幅; 全市场涨跌幅均值作大盘方向代理。
    一次拉全市场快照, 复用给个股 + 大盘, 省请求。
    """

    name = "spot"

    def __init__(self):
        self._cache_df = None

    def _spot(self):
        from plugins.data_layer import dl
        df = dl.get_spot()
        self._cache_df = df
        return df

    def fetch_quotes(self, codes: List[str]) -> Dict[str, float]:
        df = self._cache_df if self._cache_df is not None else self._spot()
        if not hasattr(df, "columns") or len(df) == 0:
            return {}
        code_col = "代码" if "代码" in df.columns else None
        pct_col = "涨跌幅" if "涨跌幅" in df.columns else None
        if not code_col or not pct_col:
            return {}
        want = set(str(c) for c in codes)
        out: Dict[str, float] = {}
        for _, row in df.iterrows():
            code = str(row[code_col])
            if code in want:
                try:
                    out[code] = float(row[pct_col])
                except (TypeError, ValueError):
                    continue
        return out

    def fetch_market_pct(self) -> Optional[float]:
        df = self._cache_df if self._cache_df is not None else self._spot()
        if not hasattr(df, "columns") or len(df) == 0 or "涨跌幅" not in df.columns:
            return None
        try:
            series = df["涨跌幅"].astype(float)
            return round(float(series.mean()), 3)   # 全市场涨跌幅均值 = 大盘方向代理
        except (TypeError, ValueError):
            return None

    def refresh(self) -> None:
        """强制重新拉快照(下一轮 30s 循环调用)。"""
        self._spot()


# 源注册表(可插拔)
_SOURCES = {"spot": SpotAuctionSource}


def get_source(name: str = "spot") -> AuctionSource:
    cls = _SOURCES.get(name, SpotAuctionSource)
    return cls()
