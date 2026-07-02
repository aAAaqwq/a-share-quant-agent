"""板块判断记分 — 本项目"找 edge"的核心标尺

不再以个股 P&L 为主指标（用户明确否定），改为量化"主力板块 / 主力方向判断准确率"。
记分口径（用户拍板）:
  - 主力板块命中: 预测板块按【次日涨停家数】排名, Top 3 = hit, 4–8 = neutral, >8 = miss
  - 主力方向命中: 预测方向 vs 次日实际涨幅, 带 ±2% 中性带
双轨(用户确认的 D 方案):
  - 收盘复核 (本模块): 用次日全天数据
  - 竞价当场 (Phase ③): 用 9:25 集合竞价数据, 复用同一套纯记分函数

设计: 纯记分函数(rank/score_*)与数据抓取(fetch_*)分离, 前者可离线确定性测试。
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ── outcome 常量 ──────────────────────────────────────────
HIT = "hit"
MISS = "miss"
NEUTRAL = "neutral"

# ── 记分阈值(用户拍板) ────────────────────────────────────
HIT_RANK = 3          # 涨停家数排名 Top 3 = 命中
NEUTRAL_RANK = 8      # 4–8 名 = 中性, 8 名外 = miss
DIRECTION_BAND_PCT = 2.0   # 方向判断中性带 ±2%


# ══════════════════════════════════════════════════════════
#  预测 / 记分 数据结构
# ══════════════════════════════════════════════════════════

@dataclass(frozen=True)
class SectorPrediction:
    """盘前 agent 产出的预测(板块级)。"""
    date: str
    main_sectors: List[str]              # 主力板块 1–3 个, [0] 为首选
    main_direction: str                  # "up" / "down" / "neutral"
    candidates: List[dict] = field(default_factory=list)  # 15 候选个股

    @staticmethod
    def from_dict(d: dict) -> "SectorPrediction":
        return SectorPrediction(
            date=d.get("date", ""),
            main_sectors=list(d.get("main_sectors", [])),
            main_direction=(d.get("main_direction") or "neutral").lower(),
            candidates=list(d.get("candidates", [])),
        )


@dataclass(frozen=True)
class SectorScore:
    """一次预测的板块判断得分(单轨: 收盘复核 或 竞价当场)。"""
    track: str                           # "close" | "auction"
    sector_outcome: str                  # hit/miss/neutral — 板块判断
    direction_outcome: str               # hit/miss/neutral — 方向判断
    primary_sector: Optional[str] = None
    primary_sector_rank: Optional[int] = None   # 首选板块的涨停家数排名(1-based)
    sector_detail: Dict[str, Optional[int]] = field(default_factory=dict)  # 每个预测板块→排名
    direction_ref_pct: Optional[float] = None   # 方向判据的实际涨幅

    def to_dict(self) -> dict:
        return asdict(self)


# ══════════════════════════════════════════════════════════
#  纯记分函数(可离线确定性测试)
# ══════════════════════════════════════════════════════════

def rank_by_count(sector_counts: Dict[str, int]) -> Dict[str, int]:
    """按涨停家数降序给板块排名(1-based, 并列同名次)。

    排名 = 1 + 严格大于自己的板块数(competition ranking)。
    """
    ranks: Dict[str, int] = {}
    for sec, cnt in sector_counts.items():
        higher = sum(1 for c in sector_counts.values() if c > cnt)
        ranks[sec] = higher + 1
    return ranks


def _match_rank(sector: str, ranks: Dict[str, int]) -> Optional[int]:
    """在排名表里找板块名次: 先精确, 再子串双向匹配(概念/行业命名差异容错)。"""
    if sector in ranks:
        return ranks[sector]
    for name, r in ranks.items():
        if sector and (sector in name or name in sector):
            return r
    return None


def score_sector_call(
    predicted_sectors: List[str],
    sector_counts: Dict[str, int],
    hit_rank: int = HIT_RANK,
    neutral_rank: int = NEUTRAL_RANK,
) -> tuple[str, Optional[str], Optional[int], Dict[str, Optional[int]]]:
    """给"主力板块判断"打分。

    以【预测板块里名次最好的那个】决定 outcome(命中一个主力即算抓对方向)。

    Returns:
        (outcome, primary_sector, primary_rank, detail)
        detail: 每个预测板块 → 其涨停家数排名(None=当日无涨停/未上榜)
    """
    if not predicted_sectors or not sector_counts:
        return NEUTRAL, None, None, {s: None for s in predicted_sectors}

    ranks = rank_by_count(sector_counts)
    detail: Dict[str, Optional[int]] = {
        s: _match_rank(s, ranks) for s in predicted_sectors
    }

    matched = [(s, r) for s, r in detail.items() if r is not None]
    if not matched:
        # 预测板块当日一个涨停都没有 → 明确判错
        return MISS, predicted_sectors[0], None, detail

    best_sector, best_rank = min(matched, key=lambda x: x[1])
    if best_rank <= hit_rank:
        outcome = HIT
    elif best_rank <= neutral_rank:
        outcome = NEUTRAL
    else:
        outcome = MISS
    return outcome, best_sector, best_rank, detail


def score_direction(
    predicted_direction: str,
    actual_pct: Optional[float],
    band_pct: float = DIRECTION_BAND_PCT,
) -> str:
    """给"主力方向判断"打分, 带 ±band 中性带。

    predicted_direction: up/down/neutral
    actual_pct: 次日实际涨幅(%)。None → 无法判断, 返回 neutral。
    """
    if actual_pct is None:
        return NEUTRAL
    pred = (predicted_direction or "neutral").lower()

    if actual_pct > band_pct:
        actual = "up"
    elif actual_pct < -band_pct:
        actual = "down"
    else:
        actual = "neutral"

    if pred == "neutral" or actual == "neutral":
        # 预测震荡且实际在带内 = 命中; 一方震荡一方明确 = 中性
        return HIT if pred == actual else NEUTRAL
    return HIT if pred == actual else MISS


def score_prediction(
    pred: SectorPrediction,
    sector_counts: Dict[str, int],
    direction_ref_pct: Optional[float],
    track: str = "close",
) -> SectorScore:
    """合成一次预测的板块判断得分。"""
    outcome, primary, rank, detail = score_sector_call(pred.main_sectors, sector_counts)
    dir_outcome = score_direction(pred.main_direction, direction_ref_pct)
    return SectorScore(
        track=track,
        sector_outcome=outcome,
        direction_outcome=dir_outcome,
        primary_sector=primary,
        primary_sector_rank=rank,
        sector_detail=detail,
        direction_ref_pct=direction_ref_pct,
    )


# ══════════════════════════════════════════════════════════
#  数据抓取(网络) — 薄适配层, 记分逻辑不依赖它
# ══════════════════════════════════════════════════════════

def fetch_sector_limitup_counts(date: Optional[str] = None) -> Dict[str, int]:
    """按【所属行业】统计当日涨停家数 → {行业名: 家数}。

    robust 路径: 直接分组 stock_zt_pool_em 的"所属行业"列, 不依赖成分股缓存。
    非交易时段 / 接口失败时返回空 dict(记分层据此判 neutral, 不崩)。
    """
    import akshare as ak
    from plugins.data_layer import dl

    kwargs = {"date": date} if date else {}
    df = dl._call_with_retry(ak.stock_zt_pool_em, **kwargs)
    if not hasattr(df, "columns") or len(df) == 0 or "所属行业" not in df.columns:
        return {}
    counts = df["所属行业"].value_counts().to_dict()
    return {str(k): int(v) for k, v in counts.items()}
