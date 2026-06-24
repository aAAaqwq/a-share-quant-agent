"""
模块三：个股精选引擎

对候选个股进行五维深度分析：
1. 产业逻辑核实 — 是否真正受益于概念
2. K线形态8分类 — 突破平台/趋势新高/连板等
3. 盘口分析 — 龙虎榜 + 内外盘比
4. 题材涨幅排名 — 是否处于强势板块
5. 综合评分 — 满分100分排序

用法:
    ./venv/bin/python3 engines/module3_stocks.py
"""

import os
import sys
import json
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import warnings

# 必须在导入 akshare 前设置
os.environ["no_proxy"] = "*"
os.environ["NO_PROXY"] = "*"
for k in list(os.environ.keys()):
    if "proxy" in k.lower():
        del os.environ[k]

import pandas as pd
import numpy as np

# Monkey-patch requests to avoid proxy
try:
    import requests as _requests
    _original_session = _requests.Session

    class _NoProxySession(_original_session):
        def __init__(self):
            super().__init__()
            self.trust_env = False

    _requests.Session = _NoProxySession
except Exception:
    pass

warnings.filterwarnings("ignore")

# 确保项目根目录在 sys.path
_workdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _workdir not in sys.path:
    sys.path.insert(0, _workdir)

from plugins.data_layer import dl

# ── 加载板块关键词 ──────────────────────────────────────────
_KEYWORDS_PATH = os.path.join(_workdir, "config", "sector_keywords.json")
_SECTOR_CACHE_PATH = os.path.join(_workdir, "config", "sector_stocks_cache.json")

def _load_sector_keywords() -> Dict[str, Any]:
    try:
        with open(_KEYWORDS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

SECTOR_KEYWORDS = _load_sector_keywords()


def _load_sector_cache() -> Dict[str, List[Dict]]:
    try:
        with open(_SECTOR_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _is_trade_day() -> bool:
    """简单判断是否为交易日（周一至周五，非假日）"""
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    if now.hour < 9:
        return False
    return True


# ═══════════════════════════════════════════════════════════════
#  1. 产业逻辑核实
# ═══════════════════════════════════════════════════════════════

def check_industry_logic(stock_code: str, sector_name: str = "") -> dict:
    """核实个股是否真正受益于概念

    通过 F10 基本信息中的「主营业务」字段，搜索概念关键词，
    判断该股与题材的关联紧密度。

    Args:
        stock_code: 股票代码，如 '000001'
        sector_name: 板块/概念名称，用于精确匹配关键词表

    Returns:
        {
            'code': 股票代码,
            'sector': 板块名,
            'logic_rating': '逻辑正' | '部分相关' | '蹭概念',
            'main_business': 主营描述,
            'matched_keywords': 匹配到的关键词列表,
        }
    """
    try:
        info = dl.get_stock_info(stock_code)
    except Exception:
        info = pd.DataFrame()

    result = {
        "code": stock_code,
        "sector": sector_name or "未知",
        "logic_rating": "蹭概念",
        "main_business": "",
        "matched_keywords": [],
    }

    if info.empty:
        result["logic_rating"] = "蹭概念"
        result["main_business"] = "(数据获取失败)"
        return result

    # 尝试从 stock_info DataFrame 中提取主营业务文本
    main_biz = ""
    try:
        # stock_individual_info_em 返回两列: item / value
        if "item" in info.columns and "value" in info.columns:
            info_dict = dict(zip(info["item"].astype(str), info["value"].astype(str)))
            main_biz = info_dict.get("主营业务", "")
            if not main_biz:
                main_biz = info_dict.get("主营", "")
        else:
            # fallback: 将所有内容拼接成文本
            main_biz = " ".join(info.astype(str).values.flatten().tolist())
    except Exception:
        main_biz = " ".join(info.astype(str).values.flatten().tolist())

    result["main_business"] = main_biz[:300] if main_biz else "(未找到主营信息)"

    if not main_biz or main_biz.startswith("(未找到"):
        result["logic_rating"] = "蹭概念"
        return result

    # 获取该板块/全板块的关键词
    all_keywords: List[str] = []
    if sector_name and sector_name in SECTOR_KEYWORDS:
        all_keywords = SECTOR_KEYWORDS[sector_name].get("keywords", [])
    else:
        for _sector, data in SECTOR_KEYWORDS.items():
            all_keywords.extend(data.get("keywords", []))

    all_keywords = list(set(all_keywords))
    main_biz_lower = main_biz.lower()

    matched = []
    for kw in all_keywords:
        if kw.lower() in main_biz_lower:
            if kw not in matched:
                matched.append(kw)

    result["matched_keywords"] = matched

    if not matched:
        result["logic_rating"] = "蹭概念"
    elif len(matched) >= 3:
        result["logic_rating"] = "逻辑正"
    else:
        # 有匹配但不多 → 部分相关
        result["logic_rating"] = "部分相关"

    return result


# ═══════════════════════════════════════════════════════════════
#  2. K线形态8分类
# ═══════════════════════════════════════════════════════════════

def classify_pattern(stock_code: str) -> dict:
    """用最近90日K线检测8种形态

    检测逻辑参考 docs/AI-STOCKS-DESIGN.md 中的定义。

    Returns:
        {
            'patterns': [...],
            'consecutive_boards': 0,
            'details': {...},
        }
    """
    try:
        hist = dl.get_hist(stock_code, days=90)
    except Exception as e:
        return {"patterns": [], "consecutive_boards": 0, "error": str(e)}

    if hist.empty or len(hist) < 5:
        return {"patterns": [], "consecutive_boards": 0, "error": "K线数据不足"}

    # 统一列名
    col_map = {
        "日期": "date",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
        "成交额": "amount",
        "涨跌幅": "pct_chg",
    }
    hist = hist.rename(columns=col_map)

    required = ["close", "high", "volume", "pct_chg"]
    for c in required:
        if c not in hist.columns:
            return {"patterns": [], "consecutive_boards": 0, "error": f"缺少列: {c}"}

    hist["close"] = pd.to_numeric(hist["close"], errors="coerce")
    hist["high"] = pd.to_numeric(hist["high"], errors="coerce")
    hist["low"] = pd.to_numeric(hist["low"], errors="coerce")
    hist["open"] = pd.to_numeric(hist["open"], errors="coerce") if "open" in hist.columns else hist["close"]
    hist["volume"] = pd.to_numeric(hist["volume"], errors="coerce")
    hist["pct_chg"] = pd.to_numeric(hist["pct_chg"], errors="coerce")

    hist = hist.dropna(subset=["close", "volume"])
    if len(hist) < 5:
        return {"patterns": [], "consecutive_boards": 0}

    # 排序（旧→新）
    hist = hist.sort_values("date" if "date" in hist.columns else hist.columns[0]).reset_index(drop=True)
    n = len(hist)

    today = hist.iloc[-1]
    yesterday = hist.iloc[-2]
    today_close = float(today["close"])
    today_high = float(today["high"])
    today_pct = float(today["pct_chg"]) if pd.notna(today.get("pct_chg")) else 0
    today_vol = float(today["volume"])

    yesterday_close = float(yesterday["close"])
    yesterday_high = float(yesterday["high"])
    yesterday_open = float(yesterday["open"]) if pd.notna(yesterday.get("open")) else yesterday_close

    patterns: List[str] = []
    consecutive_boards = 0
    details: Dict[str, Any] = {}

    # ── 辅助：涨停判断 ──
    def is_limit_up(pct: float) -> bool:
        return pct >= 9.8

    # ── 计算均量 ──
    if n >= 5:
        vol_5ma = float(hist["volume"].iloc[-6:-1].mean())  # 不含当日
    else:
        vol_5ma = float(hist["volume"].mean())

    if n >= 20:
        vol_20ma = float(hist["volume"].iloc[-21:-1].mean())
    else:
        vol_20ma = vol_5ma

    # ── N连板检测 ──
    board_count = 0
    for i in range(n - 1, -1, -1):
        pct = float(hist["pct_chg"].iloc[i])
        if is_limit_up(pct):
            board_count += 1
        else:
            break
    consecutive_boards = board_count
    if board_count >= 2:
        patterns.append("N连板")
    details["consecutive_boards"] = board_count

    # ── 1. 突破平台 ──
    # max今日最高 > 30日最高价 AND 量 > 20日均量 × 1.5
    lookback_30 = min(30, n - 1)
    if lookback_30 > 0 and today_vol > 0:
        max_30_high = float(hist["high"].iloc[-(lookback_30 + 1):-1].max())
        if today_high > max_30_high and today_vol > vol_20ma * 1.5:
            patterns.append("突破平台")

    # ── 2. 趋势新高 ──
    all_time_high = float(hist["close"].max())
    if today_close >= all_time_high:
        patterns.append("趋势新高")
    details["all_time_high"] = round(all_time_high, 2)

    # ── 3. 新高附近 ──
    if all_time_high > 0:
        dist_from_high = (all_time_high - today_close) / all_time_high
        details["dist_from_high"] = round(dist_from_high, 4)
        if 0 < dist_from_high < 0.05:
            patterns.append("新高附近")

    # ── 4. 老龙二波 ──
    # 60日内有过3+连板 AND 高位回调>15% AND 今日涨停
    if is_limit_up(today_pct) and n >= 60:
        lookback_60 = hist.iloc[-60:]
        # 找到60日内的连板段
        max_consecutive_60 = 0
        current_run = 0
        for i in range(len(lookback_60)):
            pct = float(lookback_60["pct_chg"].iloc[i])
            if is_limit_up(pct):
                current_run += 1
                max_consecutive_60 = max(max_consecutive_60, current_run)
            else:
                current_run = 0
        if max_consecutive_60 >= 3:
            # 最高点（不含今日）
            max_close_before = float(lookback_60["close"].iloc[:-1].max())
            if max_close_before > 0:
                drawdown = (max_close_before - yesterday_close) / max_close_before
                if drawdown > 0.15:
                    patterns.append("老龙二波")
                    details["max_drawdown"] = round(drawdown * 100, 1)

    # ── 5. 分歧转一致 ──
    # 今日涨停 AND 开盘价 < 昨日收盘 × 0.97
    today_open = float(today["open"]) if pd.notna(today.get("open")) else today_close
    if is_limit_up(today_pct) and today_open < yesterday_close * 0.97:
        patterns.append("分歧转一致")

    # ── 6. 反包板 ──
    # T-2 涨停 AND T-1 长上影(最高/开盘>1.05且涨幅<5%) AND T日涨停
    if n >= 3:
        t2 = hist.iloc[-3]  # T-2
        t1 = hist.iloc[-2]  # T-1
        t2_pct = float(t2["pct_chg"])
        t1_high = float(t1["high"])
        t1_open = float(t1["open"]) if pd.notna(t1.get("open")) else float(t1["close"])
        t1_pct = float(t1["pct_chg"])

        if (
            is_limit_up(t2_pct)
            and t1_open > 0
            and (t1_high / t1_open) > 1.05
            and t1_pct < 5.0
            and is_limit_up(today_pct)
        ):
            patterns.append("反包板")

    # ── 7. 放量首板 ──
    # 20日涨幅<15% AND 今日涨停 AND 量 > 5日均量 × 3
    if n >= 20:
        close_20d_ago = float(hist["close"].iloc[-21])
        chg_20d = (today_close - close_20d_ago) / close_20d_ago * 100
        if chg_20d < 15 and is_limit_up(today_pct) and today_vol > vol_5ma * 3:
            patterns.append("放量首板")
    elif n >= 5:
        # 数据不足20天时放宽
        if is_limit_up(today_pct) and today_vol > vol_5ma * 3:
            patterns.append("放量首板")

    return {
        "patterns": patterns,
        "consecutive_boards": consecutive_boards,
        "details": details,
    }


# ═══════════════════════════════════════════════════════════════
#  3. 盘口分析
# ═══════════════════════════════════════════════════════════════

def analyze_orderbook(stock_code: str) -> dict:
    """盘口分析：龙虎榜 + 内外盘比

    Returns:
        {
            'code': 股票代码,
            'lhb_net_buy': 龙虎榜净买入(万元),
            'lhb_on_list': 是否上龙虎榜,
            'outer_vol': 外盘量,
            'inner_vol': 内盘量,
            'outer_inner_ratio': 外盘/内盘比,
            'order_force': '强'|'中'|'弱',
        }
    """
    today_str = datetime.now().strftime("%Y%m%d")
    result = {
        "code": stock_code,
        "lhb_net_buy": 0,
        "lhb_on_list": False,
        "outer_vol": 0,
        "inner_vol": 0,
        "outer_inner_ratio": 0,
        "order_force": "弱",
    }

    # ── 1. 龙虎榜 ──
    try:
        lhb = dl.get_lhb_detail(today_str)
    except Exception:
        lhb = pd.DataFrame()

    if not lhb.empty and "代码" in lhb.columns:
        stock_lhb = lhb[lhb["代码"].astype(str).str.strip() == str(stock_code).strip()]
        result["lhb_on_list"] = not stock_lhb.empty

        if not stock_lhb.empty:
            # 尝试计算净买入
            net = 0.0
            if "净买额" in lhb.columns:
                net_vals = pd.to_numeric(stock_lhb["净买额"], errors="coerce")
                net = float(net_vals.sum())
            elif "买入金额" in lhb.columns and "卖出金额" in lhb.columns:
                buy = pd.to_numeric(stock_lhb["买入金额"], errors="coerce").sum()
                sell = pd.to_numeric(stock_lhb["卖出金额"], errors="coerce").sum()
                net = float(buy - sell)
            result["lhb_net_buy"] = round(net, 2)
    else:
        # 如果列名不匹配，尝试通用列名
        result["lhb_on_list"] = False

    # ── 2. 内外盘比 ──
    try:
        spot = dl.get_spot()
        if not spot.empty and "代码" in spot.columns:
            stock_spot = spot[spot["代码"].astype(str).str.strip() == str(stock_code).strip()]
            if not stock_spot.empty:
                row = stock_spot.iloc[0]
                outer = pd.to_numeric(row.get("外盘", 0), errors="coerce")
                inner = pd.to_numeric(row.get("内盘", 0), errors="coerce")
                result["outer_vol"] = float(outer) if pd.notna(outer) else 0
                result["inner_vol"] = float(inner) if pd.notna(inner) else 0
                inner_val = result["inner_vol"]
                outer_val = result["outer_vol"]
                if inner_val > 0:
                    result["outer_inner_ratio"] = round(outer_val / inner_val, 2)
                elif outer_val > 0:
                    result["outer_inner_ratio"] = 99.0  # 内盘为0
    except Exception:
        pass

    # ── 判定买盘力度 ──
    ratio = result["outer_inner_ratio"]
    if ratio > 1.5:
        result["order_force"] = "强"
    elif ratio >= 1.0:
        result["order_force"] = "中"
    else:
        result["order_force"] = "弱"

    return result


# ═══════════════════════════════════════════════════════════════
#  4. 题材涨幅排名
# ═══════════════════════════════════════════════════════════════

def rank_sector_strength(stock_code: str) -> dict:
    """计算个股的题材强度

    1. 获取涨幅前10行业板块 + 前10概念板块
    2. 检查该股是否在前10板块成分股中
    3. 命中次数 → 题材强度

    Returns:
        {
            'code': 股票代码,
            'sector_hits': 命中次数,
            'sector_strength': '极强'|'强'|'中'|'弱',
            'matched_sectors': [...],
            'industry_top10': [...],
            'concept_top10': [...],
        }
    """
    result = {
        "code": stock_code,
        "sector_hits": 0,
        "sector_strength": "弱",
        "matched_sectors": [],
        "industry_top10": [],
        "concept_top10": [],
    }

    # 加载板块缓存
    sector_cache = _load_sector_cache()

    # ── 获取前10行业板块 ──
    try:
        industries = dl.get_industry_boards()
    except Exception:
        industries = pd.DataFrame()

    top_industries: List[Dict] = []
    if not industries.empty and "板块名称" in industries.columns:
        ind_sorted = industries.sort_values("涨跌幅", ascending=False).head(10)
        for _, row in ind_sorted.iterrows():
            top_industries.append({
                "name": str(row.get("板块名称", "")),
                "code": str(row.get("板块代码", "")),
                "pct": float(row.get("涨跌幅", 0)),
            })
    result["industry_top10"] = [x["name"] for x in top_industries]

    # ── 获取前10概念板块 ──
    try:
        concepts = dl.get_concept_boards()
    except Exception:
        concepts = pd.DataFrame()

    top_concepts: List[Dict] = []
    if not concepts.empty and "板块名称" in concepts.columns:
        con_sorted = concepts.sort_values("涨跌幅", ascending=False).head(10)
        for _, row in con_sorted.iterrows():
            top_concepts.append({
                "name": str(row.get("板块名称", "")),
                "code": str(row.get("板块代码", "")),
                "pct": float(row.get("涨跌幅", 0)),
            })
    result["concept_top10"] = [x["name"] for x in top_concepts]

    # ── 检查该股是否在前10板块成分股中 ──
    all_top = top_industries + top_concepts
    matched_sectors = []

    for board in all_top:
        board_name = board["name"]
        board_code = board["code"]

        # 先从缓存查
        if board_name in sector_cache:
            cached_stocks = sector_cache[board_name]
            stock_codes = {s.get("code", "") for s in cached_stocks}
            if str(stock_code) in stock_codes:
                matched_sectors.append({"name": board_name, "pct": board["pct"], "source": "cache"})
                continue

        # 缓存未命中 → 调API
        if board_code:
            try:
                stocks_df = dl.get_board_stocks(board_code)
                if not stocks_df.empty and "代码" in stocks_df.columns:
                    if str(stock_code) in stocks_df["代码"].astype(str).values:
                        matched_sectors.append({"name": board_name, "pct": board["pct"], "source": "api"})
            except Exception:
                pass

    result["matched_sectors"] = matched_sectors
    hits = len(matched_sectors)
    result["sector_hits"] = hits

    if hits >= 5:
        result["sector_strength"] = "极强"
    elif hits >= 3:
        result["sector_strength"] = "强"
    elif hits >= 1:
        result["sector_strength"] = "中"
    else:
        result["sector_strength"] = "弱"

    return result


# ═══════════════════════════════════════════════════════════════
#  5. 综合评分
# ═══════════════════════════════════════════════════════════════

# 形态权重分
_PATTERN_SCORE_MAP = {
    "趋势新高": 25,
    "突破平台": 22,
    "放量首板": 20,
    "分歧转一致": 18,
    "N连板": 16,
    "反包板": 15,
    "新高附近": 12,
    "老龙二波": 10,
}


def score_stock(analysis: dict) -> dict:
    """综合评分（满分100）

    权重:
    - 题材强度 30分 (命中数×8，上限30)
    - 形态     25分 (取最高分形态)
    - 盘口     20分 (龙虎榜净买10分 + 内外盘10分)
    - 逻辑     15分 (逻辑正15/部分8/蹭概念0)
    - 事件     10分 (有事件匹配+10)

    Args:
        analysis: 包含 code, patterns, sector_hits, lhb_net_buy,
                  outer_inner_ratio, logic_rating 等字段的字典

    Returns:
        原字典 + score + score_detail 字段
    """
    score_detail: Dict[str, float] = {}

    # ── 题材强度 30分 ──
    sector_hits = analysis.get("sector_hits", 0)
    sector_score = min(sector_hits * 8, 30)
    score_detail["题材强度"] = sector_score

    # ── 形态 25分 ──
    patterns = analysis.get("patterns", [])
    best_pattern_score = 0
    for p in patterns:
        ps = _PATTERN_SCORE_MAP.get(p, 0)
        if ps > best_pattern_score:
            best_pattern_score = ps
    score_detail["形态"] = best_pattern_score

    # ── 盘口 20分 ──
    lhb_score = 0
    lhb_net = analysis.get("lhb_net_buy", 0) or 0
    if lhb_net > 0:
        if lhb_net > 10000:
            lhb_score = 10
        elif lhb_net > 5000:
            lhb_score = 8
        elif lhb_net > 1000:
            lhb_score = 6
        elif lhb_net > 0:
            lhb_score = 4
    # 龙虎榜净卖出仍可给基础分（上榜即关注）
    if analysis.get("lhb_on_list") and lhb_score == 0:
        lhb_score = 2

    order_score = 0
    force = analysis.get("order_force", "弱")
    ratio = analysis.get("outer_inner_ratio", 0) or 0
    if force == "强":
        order_score = 10
    elif force == "中":
        order_score = 6
    elif force == "弱" and ratio > 0:
        order_score = 2
    score_detail["盘口_龙虎榜"] = lhb_score
    score_detail["盘口_内外盘"] = order_score

    # ── 逻辑 15分 ──
    logic_map = {"逻辑正": 15, "部分相关": 8, "蹭概念": 0}
    logic_rating = analysis.get("logic_rating", "蹭概念")
    logic_score = logic_map.get(logic_rating, 0)
    score_detail["逻辑"] = logic_score

    # ── 事件 10分 ──
    event_score = 10 if analysis.get("event_match") else 0
    score_detail["事件"] = event_score

    total = sum(score_detail.values())

    return {
        **analysis,
        "score": round(total, 1),
        "score_detail": score_detail,
    }


# ── v2 多空对称评分 ──────────────────────────────────────────

def score_stock_v2(analysis: dict, indicators: dict = None) -> dict:
    """多空对称评分系统 v2.0

    加分项: 最多 +100
    减分项: 最多 -80
    最终分数范围: [-80, 100]

    Args:
        analysis: 包含 sector_hit_count, patterns, lhb_net_buy,
                  outer_inner_ratio, logic_rating, has_event_match 等字段
        indicators: 量化指标字典 (来自 engines.indicators.get_full_indicators)
                    包含 rsi_14, valuation.pe_ttm, pctile_52w, ma5, ma20,
                    macd.trend, atr_14, current_price 等

    Returns:
        原字典 + score + score_v2 + bull_reasons + bear_reasons
                + stop_loss + position + risk_warnings + excluded
    """
    score = 0
    bull_reasons: List[str] = []
    bear_reasons: List[str] = []

    # ── 加分项（利好）──

    # 1. 题材强度 (最多 +30)
    sector_hits = analysis.get('sector_hit_count', 0)
    sector_pts = min(sector_hits * 8, 30)
    score += sector_pts
    if sector_pts > 0:
        bull_reasons.append(f"题材命中{sector_hits}个热门板块 (+{sector_pts})")

    # 2. 形态 (最多 +25)
    patterns = analysis.get('patterns', [])
    pattern_scores = {
        '趋势新高': 25, '突破平台': 22, '放量首板': 20,
        '分歧转一致': 18, 'N连板': 16, '反包板': 15,
        '新高附近': 12, '老龙二波': 10,
    }
    pattern_pts = max([pattern_scores.get(p, 0) for p in patterns], default=0)
    score += pattern_pts
    if pattern_pts > 0:
        bull_reasons.append(f"形态: {', '.join(patterns[:2])} (+{pattern_pts})")

    # 3. 盘口 (最多 +20)
    lhb_net = analysis.get('lhb_net_buy', 0) or 0
    if lhb_net > 0:
        lhb_pts = min(int(lhb_net / 1000), 10)
        score += lhb_pts
        bull_reasons.append(f"龙虎榜净买入{lhb_net:.0f}万 (+{lhb_pts})")

    order_ratio = analysis.get('outer_inner_ratio', 1.0) or 0
    if order_ratio > 1.5:
        score += 10
        bull_reasons.append(f"外盘/内盘={order_ratio:.1f} (+10)")
    elif order_ratio > 1.0:
        score += 5

    # 4. 逻辑 (最多 +15)
    logic = analysis.get('logic_rating', '')
    if logic == '逻辑正':
        score += 15
        bull_reasons.append("产业逻辑验证 (+15)")
    elif logic == '部分相关':
        score += 8

    # 5. 事件 (最多 +10)
    if analysis.get('has_event_match'):
        score += 10
        bull_reasons.append("有事件催化 (+10)")

    # ── 减分项（利空）──

    stop_loss = {}
    position = {}
    warnings: List[Dict] = []

    if indicators:
        from engines.risk_manager import risk_mgr

        # 1. RSI超买 (-15)
        rsi = indicators.get('rsi_14', 50) or 50
        if rsi > 85:
            score -= 15
            bear_reasons.append(f"RSI={rsi:.0f}严重超买 (-15)")
        elif rsi > 70:
            score -= 8
            bear_reasons.append(f"RSI={rsi:.0f}偏高 (-8)")

        # 2. 估值泡沫 (-15)
        pe = indicators.get('valuation', {}).get('pe_ttm', 0) or 0
        if pe > 200:
            score -= 15
            bear_reasons.append(f"PE={pe:.0f}估值泡沫 (-15)")
        elif pe > 100:
            score -= 8
            bear_reasons.append(f"PE={pe:.0f}估值偏高 (-8)")

        # 3. 52周高位 (-10)
        pctile = indicators.get('pctile_52w', 50) or 50
        if pctile > 95:
            score -= 10
            bear_reasons.append(f"52周{pctile:.0f}%分位 (-10)")

        # 4. 近期累计涨幅过大 (-10)
        ma5 = indicators.get('ma5', 0) or 0
        ma20 = indicators.get('ma20', 0) or 0
        if ma20 > 0:
            short_term_gain = (ma5 - ma20) / ma20 * 100
            if short_term_gain > 20:
                score -= 10
                bear_reasons.append(f"短期偏离均线{short_term_gain:.0f}% (-10)")

        # 5. MACD死叉 (-8)
        macd = indicators.get('macd', {})
        if macd.get('trend') == '空头':
            score -= 8
            bear_reasons.append("MACD空头排列 (-8)")

        # 计算止损位 + 建议仓位
        atr = indicators.get('atr_14', 0) or 0
        price = indicators.get('current_price', 0) or 0
        stop_loss = risk_mgr.calculate_stop_loss(price, atr)
        position = risk_mgr.calculate_position(atr, price)

        # 超买检测
        warnings = risk_mgr.check_overbought(
            rsi, pe, pctile,
            analysis.get('consecutive_boards', 0) or 0
        )

    return {
        **analysis,
        'score': round(score, 1),
        'score_v2': True,
        'bull_reasons': bull_reasons,
        'bear_reasons': bear_reasons,
        'stop_loss': stop_loss,
        'position': position,
        'risk_warnings': warnings,
        'excluded': len(warnings) >= 2 and sum(1 for w in warnings if w['level'] == '🔴') >= 2,
    }


# ═══════════════════════════════════════════════════════════════
#  6. 主函数
# ═══════════════════════════════════════════════════════════════

def run_module3(stock_list: Optional[List[Dict]] = None) -> dict:
    """模块三主入口：对候选个股进行五维深度分析并排序

    Args:
        stock_list: [{'代码': '000001', '名称': '平安银行'}, ...]
                    为 None 时自动分析当日涨停池前20只（非ST/非新股）

    Returns:
        {
            'stocks': [{...分析结果...}, ...],
            'analysis_time': 'YYYY-MM-DD HH:MM:SS',
        }
    """
    # ── 自动选股 ──
    if stock_list is None:
        try:
            zt = dl.get_limit_up_pool()
        except Exception:
            return {"error": "无法获取涨停池数据", "stocks": [], "analysis_time": datetime.now().isoformat()}

        if zt.empty:
            return {"error": "今日无涨停数据", "stocks": [], "analysis_time": datetime.now().isoformat()}

        # 过滤 ST/*ST/新股(N/C开头/T+0新股)
        try:
            mask_st = ~zt["名称"].str.contains(r"ST|\*ST|N|C", na=False, regex=True)
            zt = zt[mask_st]
        except Exception:
            pass

        if zt.empty:
            return {"error": "过滤后无有效涨停股", "stocks": [], "analysis_time": datetime.now().isoformat()}

        # 取前20
        zt_top = zt.head(20)
        stock_list = []
        for _, row in zt_top.iterrows():
            stock_list.append({
                "代码": str(row.get("代码", "")),
                "名称": str(row.get("名称", "")),
            })

    # ── 逐个分析 ──
    results: List[Dict] = []
    total = len(stock_list)

    for idx, stock in enumerate(stock_list):
        code = stock.get("代码", "")
        name = stock.get("名称", "")
        sector = stock.get("sector", "")

        print(f"[{idx+1}/{total}] 分析 {code} {name} ...", end=" ", flush=True)

        try:
            logic = check_industry_logic(code, sector)
        except Exception as e:
            logic = {"code": code, "logic_rating": "蹭概念", "error": str(e)}

        try:
            patterns = classify_pattern(code)
        except Exception as e:
            patterns = {"patterns": [], "consecutive_boards": 0, "error": str(e)}

        try:
            orderbook = analyze_orderbook(code)
        except Exception as e:
            orderbook = {"code": code, "order_force": "弱", "error": str(e)}

        try:
            sector_rank = rank_sector_strength(code)
        except Exception as e:
            sector_rank = {"code": code, "sector_strength": "弱", "error": str(e)}

        # 合并分析结果
        analysis = {
            "code": code,
            "name": name,
            "logic_rating": logic.get("logic_rating", "蹭概念"),
            "main_business": logic.get("main_business", ""),
            "matched_keywords": logic.get("matched_keywords", []),
            "patterns": patterns.get("patterns", []),
            "consecutive_boards": patterns.get("consecutive_boards", 0),
            "pattern_details": patterns.get("details", {}),
            "lhb_net_buy": orderbook.get("lhb_net_buy", 0),
            "lhb_on_list": orderbook.get("lhb_on_list", False),
            "outer_inner_ratio": orderbook.get("outer_inner_ratio", 0),
            "order_force": orderbook.get("order_force", "弱"),
            "sector_hits": sector_rank.get("sector_hits", 0),
            "sector_strength": sector_rank.get("sector_strength", "弱"),
            "matched_sectors": sector_rank.get("matched_sectors", []),
            "industry_top10": sector_rank.get("industry_top10", []),
            "concept_top10": sector_rank.get("concept_top10", []),
        }

        # 综合评分
        analysis = score_stock(analysis)
        results.append(analysis)

        pattern_str = ", ".join(analysis.get("patterns", [])) or "无"
        print(f"得分 {analysis['score']:.0f} | 形态: {pattern_str} | 题材: {analysis['sector_strength']}")

        # 避免API限流
        if idx < total - 1:
            time.sleep(0.3)

    # 按评分降序
    results.sort(key=lambda x: x.get("score", 0), reverse=True)

    return {
        "stocks": results,
        "analysis_time": datetime.now().isoformat(),
        "total_analyzed": len(results),
    }


# ═══════════════════════════════════════════════════════════════
#  7. 便捷查询函数
# ═══════════════════════════════════════════════════════════════

def analyze_single(stock_code: str, sector_name: str = "") -> dict:
    """快速分析单只个股"""
    logic = check_industry_logic(stock_code, sector_name)
    patterns = classify_pattern(stock_code)
    orderbook = analyze_orderbook(stock_code)
    sector_rank = rank_sector_strength(stock_code)

    analysis = {
        "code": stock_code,
        "name": "",
        "logic_rating": logic.get("logic_rating", "蹭概念"),
        "main_business": logic.get("main_business", ""),
        "matched_keywords": logic.get("matched_keywords", []),
        "patterns": patterns.get("patterns", []),
        "consecutive_boards": patterns.get("consecutive_boards", 0),
        "lhb_net_buy": orderbook.get("lhb_net_buy", 0),
        "lhb_on_list": orderbook.get("lhb_on_list", False),
        "outer_inner_ratio": orderbook.get("outer_inner_ratio", 0),
        "order_force": orderbook.get("order_force", "弱"),
        "sector_hits": sector_rank.get("sector_hits", 0),
        "sector_strength": sector_rank.get("sector_strength", "弱"),
        "matched_sectors": sector_rank.get("matched_sectors", []),
    }
    return score_stock(analysis)


# ═══════════════════════════════════════════════════════════════
#  8. main 验证入口
# ═══════════════════════════════════════════════════════════════

def _print_result(result: dict):
    """格式化打印分析结果"""
    stocks = result.get("stocks", [])
    if not stocks:
        print(f"\n{'='*70}")
        print(f"  ⚠️ {result.get('error', '无结果')}")
        print(f"{'='*70}")
        return

    print(f"\n{'='*80}")
    print(f"  模块三：个股精选分析结果")
    print(f"  分析时间: {result.get('analysis_time', '')}")
    print(f"  共分析: {result.get('total_analyzed', len(stocks))} 只")
    print(f"{'='*80}")

    # 表头
    print(f"\n{'排名':<4} {'代码':<8} {'名称':<10} {'得分':>5} {'题材':<6} {'形态':<16} {'盘口':<5} {'逻辑':<8}")
    print("-" * 80)

    for rank, s in enumerate(stocks, 1):
        code = s.get("code", "")
        name = s.get("name", "")
        score = s.get("score", 0)
        sector = s.get("sector_strength", "弱")
        patterns = ", ".join(s.get("patterns", []))
        if len(patterns) > 16:
            patterns = patterns[:14] + ".."
        force = s.get("order_force", "弱")
        logic = s.get("logic_rating", "蹭概念")

        print(f"{rank:<4} {code:<8} {name:<10} {score:>5.0f} {sector:<6} {patterns:<16} {force:<5} {logic:<8}")

    print("-" * 80)
    print(f"\n🏆 TOP 3:")
    for rank, s in enumerate(stocks[:3], 1):
        sd = s.get("score_detail", {})
        print(f"  #{rank} {s.get('code')} {s.get('name')} 总分 {s.get('score'):.0f}")
        print(f"      题材{sd.get('题材强度',0):.0f} + 形态{sd.get('形态',0):.0f} + "
              f"盘口{sd.get('盘口_龙虎榜',0)+sd.get('盘口_内外盘',0):.0f} + "
              f"逻辑{sd.get('逻辑',0):.0f} + 事件{sd.get('事件',0):.0f}")
        if s.get("matched_keywords"):
            print(f"      关键词: {', '.join(s['matched_keywords'][:5])}")
        if s.get("matched_sectors"):
            names = [m["name"] for m in s["matched_sectors"]]
            print(f"      强势板块: {', '.join(names[:5])}")


if __name__ == "__main__":
    print("📊 模块三：个股精选引擎 — 启动测试")
    print("-" * 60)

    if not _is_trade_day():
        print("⚠️  当前非交易时段，数据可能不完整")
        print("   将尝试分析当前行情数据…")
        print()

    start = time.time()

    # ── 方式1: 自动分析涨停池前20 ──
    print("🔍 自动获取涨停池前20（非ST/非新股）进行五维分析…\n")
    result = run_module3()

    elapsed = time.time() - start

    _print_result(result)

    print(f"\n⏱ 总耗时: {elapsed:.1f}s")
    print("✅ 模块三测试完成")
