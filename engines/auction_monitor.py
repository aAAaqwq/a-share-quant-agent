"""竞价实时分析 — 用个股竞价涨跌幅当场验证盘前预测

场景: 集合竞价 9:15–9:25(以及盘中), 常驻脚本每 30s 拉一次数据, 干三件事:
  1. 刷新候选     —— 15 候选不固定: 按实时竞价涨跌幅重排 + 合并新晋强势股 + 剔除弱势
  2. 当场验证     —— 竞价强势家数给主力板块打分(复用 sector_scorer), 方向按大盘竞价涨幅
  3. 组装 live blob —— 写 KV(live:latest), dashboard 秒级刷新

纯函数(refresh/strength/score/build)不碰网络, 可离线确定性测试;
竞价数据抓取在 plugins/auction_source.py, 常驻循环在 cloud/intraday_puller.py。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engines.sector_scorer import SectorPrediction, score_prediction

# 阈值
STRONG_PCT = 3.0          # 竞价涨幅 ≥ 3% 视为强势
LIMIT_PCT = 9.5           # 竞价涨幅 ≥ 9.5% 视为竞价一字/接近涨停
WEAK_PCT = -2.0           # 竞价涨幅 ≤ -2% 视为走弱(候选可淘汰)


def _status(pct: Optional[float]) -> str:
    if pct is None:
        return "unknown"
    if pct >= LIMIT_PCT:
        return "limit"      # 竞价涨停/一字
    if pct >= STRONG_PCT:
        return "strong"
    if pct <= WEAK_PCT:
        return "weak"
    return "flat"


def refresh_candidates(
    candidates: List[dict],
    quotes: Dict[str, float],
    extra_movers: Optional[List[dict]] = None,
    drop_weak: bool = True,
) -> List[dict]:
    """按竞价实时涨跌幅刷新候选(动态, 非固定)。

    - 给每个候选贴 live `pct` + `status`
    - 合并 extra_movers(竞价扫出的新晋强势股, 打 `new=True`)
    - drop_weak: 剔除走弱(pct ≤ WEAK_PCT)的候选
    - 按 pct 降序重排, 重新编 rank

    Args:
        candidates: 盘前候选 [{code,name,sector,reason,...}]
        quotes: {code: 竞价涨跌幅%}
        extra_movers: 可选 [{code,name,sector,...}] 新晋强势
    Returns:
        刷新后的候选列表(新对象, 不改入参)
    """
    merged: Dict[str, dict] = {}
    for c in candidates:
        code = str(c.get("code", ""))
        if not code:
            continue
        merged[code] = {**c, "new": False}
    for m in (extra_movers or []):
        code = str(m.get("code", ""))
        if code and code not in merged:
            merged[code] = {**m, "new": True, "reason": m.get("reason", "竞价新晋强势")}

    out = []
    for code, c in merged.items():
        pct = quotes.get(code)
        st = _status(pct)
        if drop_weak and st == "weak":
            continue
        out.append({
            "code": code,
            "name": c.get("name", ""),
            "sector": c.get("sector", ""),
            "reason": c.get("reason", ""),
            "pct": pct,
            "status": st,
            "new": c.get("new", False),
        })

    # 有报价的按 pct 降序排前, 无报价的垫后
    out.sort(key=lambda x: (x["pct"] is not None, x["pct"] if x["pct"] is not None else -999),
             reverse=True)
    for i, c in enumerate(out, 1):
        c["rank"] = i
    return out


def sector_strength(candidates_live: List[dict], strong_pct: float = STRONG_PCT) -> Dict[str, int]:
    """按板块统计竞价强势家数(pct ≥ strong_pct) → {板块: 家数}。

    作为竞价轨的"板块热度"排名依据(替代收盘轨的涨停家数)。
    """
    counts: Dict[str, int] = {}
    for c in candidates_live:
        pct, sec = c.get("pct"), c.get("sector", "")
        if sec and pct is not None and pct >= strong_pct:
            counts[sec] = counts.get(sec, 0) + 1
    return counts


def candidate_hit_rate(candidates_live: List[dict], strong_pct: float = STRONG_PCT) -> Optional[float]:
    """候选竞价兑现率 = 强势家数 / 有报价家数(0–1)。无报价返回 None。"""
    quoted = [c for c in candidates_live if c.get("pct") is not None]
    if not quoted:
        return None
    strong = sum(1 for c in quoted if c["pct"] >= strong_pct)
    return round(strong / len(quoted), 4)


def score_auction(
    main_sectors: List[str],
    main_direction: str,
    candidates_live: List[dict],
    market_pct: Optional[float],
    date: str = "",
) -> dict:
    """竞价轨打分: 主力板块(竞价强势家数排名) + 主力方向(大盘竞价涨幅)。

    复用 sector_scorer 的纯记分函数, track='auction'。
    """
    strength = sector_strength(candidates_live)
    sp = SectorPrediction(date=date, main_sectors=main_sectors, main_direction=main_direction)
    score = score_prediction(sp, strength, market_pct, track="auction")
    return score.to_dict()


def build_live_blob(
    prediction: dict,
    quotes: Dict[str, float],
    as_of: str,
    market_pct: Optional[float] = None,
    extra_movers: Optional[List[dict]] = None,
    phase: str = "auction",
) -> dict:
    """组装写入 KV(live:latest)的实时 blob。

    Args:
        prediction: pred:latest 的 payload(含 main_sectors/main_direction/candidates)
        quotes: {code: 竞价涨跌幅%}
        as_of: 数据时刻 "HH:MM:SS"
        market_pct: 大盘竞价涨幅%(方向判据)
    """
    live = refresh_candidates(prediction.get("candidates", []), quotes,
                              extra_movers=extra_movers)
    auction_score = score_auction(
        prediction.get("main_sectors", []),
        prediction.get("main_direction", "neutral"),
        live, market_pct, date=prediction.get("date", ""))
    return {
        "phase": phase,
        "as_of": as_of,
        "market_pct": market_pct,
        "auction_score": auction_score,
        "candidates_live": live,
        "candidate_hit_rate": candidate_hit_rate(live),
        "sector_strength": sector_strength(live),
    }
