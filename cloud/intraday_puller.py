"""竞价/盘中常驻拉数据脚本 —— 写 KV(live:latest / news:latest / heartbeat)

一份代码, 本地或 VPS 都能跑(KV 后端由环境变量自动选)。
  竞价 9:15–9:25 → 每 30s 一轮; 盘中 9:30–15:00 → 每 1h 一轮。

每轮干:
  1. 读 pred:latest(盘前预测)
  2. 拉候选竞价涨跌幅 + 大盘方向(plugins/auction_source, 可插拔)
  3. auction_monitor 动态刷新候选 + 竞价轨打分 → 写 live:latest
  4. 采集相关资讯 → 写 news:latest
  5. 写 heartbeat(死活灯)

用法:
  python cloud/intraday_puller.py --once          # 单轮(测试 / GH Actions)
  python cloud/intraday_puller.py --loop          # 常驻(VPS systemd / 本地)
  python cloud/intraday_puller.py --once --news-only
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from cloud.kv_client import PredictionKV
from engines.auction_monitor import build_live_blob
from plugins.auction_source import get_source

# 时段与刷新频率(config.json 也有, 这里给默认)
AUCTION_START, AUCTION_END = "09:15", "09:26"
SESSION_START, SESSION_END = "09:30", "15:00"
AUCTION_REFRESH = 30
SESSION_REFRESH = 3600
NEWS_LIMIT = 8


# ── 资讯整形 ──────────────────────────────────────────────

def shape_news(items, limit: int = NEWS_LIMIT) -> List[dict]:
    """NewsItem 列表 → KV 资讯项, 按热度降序取前 N。"""
    def ts(n):
        t = getattr(n, "timestamp", None)
        return t.isoformat() if hasattr(t, "isoformat") else ""
    ranked = sorted(items, key=lambda n: getattr(n, "hot_score", 0.0), reverse=True)
    out = []
    for n in ranked[:limit]:
        content = (getattr(n, "content", "") or "").strip()
        out.append({
            "title": getattr(n, "title", "").strip(),
            "snippet": content[:120],
            "url": getattr(n, "url", ""),
            "source": getattr(n, "source", ""),
            "hot_score": round(float(getattr(n, "hot_score", 0.0)), 1),
            "time": ts(n),
        })
    return out


# ── 各轮任务 ──────────────────────────────────────────────

def run_news(kv: PredictionKV, limit: int = NEWS_LIMIT) -> int:
    """采集资讯写 news:latest。返回条数。"""
    from plugins.news_collector import collect_sync
    try:
        items = collect_sync()
    except Exception as e:  # noqa: BLE001
        print(f"[puller] 资讯采集失败: {e}")
        return 0
    shaped = shape_news(items, limit)
    kv.write_news(shaped)
    print(f"[puller] 资讯已更新: {len(shaped)} 条")
    return len(shaped)


def run_auction(kv: PredictionKV, source_name: str = "spot", phase: str = "auction") -> bool:
    """拉竞价/盘中数据 → 写 live:latest。返回是否成功。"""
    pred = kv.read_prediction()
    if not pred:
        print("[puller] 无 pred:latest, 跳过竞价轮(等盘前预测)")
        kv.write_heartbeat(phase=phase)
        return False
    codes = [str(c.get("code")) for c in pred.get("candidates", []) if c.get("code")]
    src = get_source(source_name)
    if hasattr(src, "refresh"):
        try:
            src.refresh()
        except Exception as e:  # noqa: BLE001
            print(f"[puller] 行情拉取失败: {e}")
    quotes = src.fetch_quotes(codes)
    market_pct = src.fetch_market_pct()
    as_of = time.strftime("%H:%M:%S")
    blob = build_live_blob(pred, quotes, as_of, market_pct=market_pct, phase=phase)
    kv.write_live(blob, phase=phase)
    sc = blob["auction_score"]
    print(f"[puller] live 更新 {as_of} | 报价 {len(quotes)}/{len(codes)} "
          f"| 板块={sc['sector_outcome']} 方向={sc['direction_outcome']} "
          f"| 兑现率={blob['candidate_hit_rate']}")
    return True


# ── 时段判断 ──────────────────────────────────────────────

def _hm(now: Optional[datetime] = None) -> str:
    return (now or datetime.now()).strftime("%H:%M")


def current_phase(now: Optional[datetime] = None) -> str:
    hm = _hm(now)
    if AUCTION_START <= hm <= AUCTION_END:
        return "auction"
    if SESSION_START <= hm <= SESSION_END:
        return "session"
    return "closed"


def cadence_for(phase: str) -> int:
    return AUCTION_REFRESH if phase == "auction" else SESSION_REFRESH


# ── 入口 ──────────────────────────────────────────────────

def run_once(kv: PredictionKV, news_only: bool = False, source: str = "spot") -> None:
    phase = current_phase()
    if not news_only:
        run_auction(kv, source_name=source, phase=phase if phase != "closed" else "session")
    run_news(kv)


def run_loop(kv: PredictionKV, source: str = "spot") -> None:
    print("[puller] 常驻启动 (Ctrl+C 退出)")
    last_news = 0.0
    while True:
        phase = current_phase()
        if phase == "closed":
            time.sleep(60)
            continue
        run_auction(kv, source_name=source, phase=phase)
        # 资讯每小时刷一次即可
        if time.time() - last_news > 3600:
            run_news(kv)
            last_news = time.time()
        time.sleep(cadence_for(phase))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="竞价/盘中常驻拉数据 → KV")
    p.add_argument("--once", action="store_true", help="单轮")
    p.add_argument("--loop", action="store_true", help="常驻循环")
    p.add_argument("--news-only", action="store_true", help="只刷资讯")
    p.add_argument("--source", default="spot", help="竞价数据源(默认 spot)")
    args = p.parse_args(argv)

    kv = PredictionKV()
    print(f"[puller] KV 后端: {kv.backend_name}")
    if args.loop:
        run_loop(kv, source=args.source)
    else:
        run_once(kv, news_only=args.news_only, source=args.source)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
