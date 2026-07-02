"""竞价实时分析单元测试（离线，注入报价，无网络）。

运行: ./venv/bin/python3 test_auction_monitor.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from engines.auction_monitor import (
    refresh_candidates, sector_strength, candidate_hit_rate,
    score_auction, build_live_blob, STRONG_PCT,
)

CANDS = [
    {"code": "688256", "name": "寒武纪", "sector": "人工智能"},
    {"code": "300308", "name": "中际旭创", "sector": "CPO"},
    {"code": "002415", "name": "海康威视", "sector": "人工智能"},
    {"code": "300474", "name": "景嘉微", "sector": "GPU"},
]


def test_refresh_reranks_by_pct():
    quotes = {"688256": 8.5, "300308": 2.0, "002415": 5.1, "300474": -0.5}
    live = refresh_candidates(CANDS, quotes)
    # 按 pct 降序: 寒武纪(8.5) > 海康(5.1) > 中际旭创(2.0) > 景嘉微(-0.5)
    assert [c["code"] for c in live] == ["688256", "002415", "300308", "300474"]
    assert live[0]["rank"] == 1 and live[0]["status"] == "strong"
    assert live[0]["pct"] == 8.5
    print("✅ 候选按竞价涨跌幅动态重排")


def test_refresh_drops_weak_and_tags_limit():
    quotes = {"688256": 10.0, "300308": -3.0, "002415": 5.1, "300474": 1.0}
    live = refresh_candidates(CANDS, quotes, drop_weak=True)
    codes = [c["code"] for c in live]
    assert "300308" not in codes            # -3% 走弱被剔除
    assert live[0]["status"] == "limit"      # 10% = 竞价涨停
    print("✅ 走弱候选剔除 + 竞价涨停标记")


def test_refresh_adds_new_movers():
    quotes = {"688256": 6.0, "600000": 9.0}
    extra = [{"code": "600000", "name": "新晋股", "sector": "人工智能"}]
    live = refresh_candidates(CANDS, quotes, extra_movers=extra)
    new = [c for c in live if c["code"] == "600000"][0]
    assert new["new"] is True and new["rank"] == 1   # 新晋且最强排第1
    print("✅ 竞价新晋强势股动态并入")


def test_missing_quote_sinks_to_bottom():
    quotes = {"688256": 5.0}  # 其余无报价
    live = refresh_candidates(CANDS, quotes, drop_weak=False)
    assert live[0]["code"] == "688256"
    assert live[-1]["pct"] is None and live[-1]["status"] == "unknown"
    print("✅ 无报价候选垫底")


def test_sector_strength_and_hit_rate():
    quotes = {"688256": 8.0, "300308": 4.0, "002415": 5.0, "300474": 1.0}
    live = refresh_candidates(CANDS, quotes)
    strength = sector_strength(live)
    # 人工智能: 寒武纪8 + 海康5 = 2 强势; CPO: 中际旭创4 = 1; GPU: 景嘉微1% 不算
    assert strength["人工智能"] == 2 and strength["CPO"] == 1
    assert "GPU" not in strength
    # 兑现率: 3/4 强势
    assert candidate_hit_rate(live) == 0.75
    print("✅ 板块竞价强势家数 + 候选兑现率")


def test_score_auction_reuses_sector_scorer():
    quotes = {"688256": 8.0, "002415": 6.0, "300308": 4.0, "300474": 5.0}
    live = refresh_candidates(CANDS, quotes)
    # 人工智能 2 强势(第1), 预测人工智能 → hit; 方向 up 实际大盘 +2.5% → hit
    score = score_auction(["人工智能"], "up", live, market_pct=2.5)
    assert score["sector_outcome"] == "hit"
    assert score["direction_outcome"] == "hit"
    assert score["track"] == "auction"
    print("✅ 竞价轨复用 sector_scorer 打分")


def test_build_live_blob():
    pred = {"date": "2026-07-02", "main_sectors": ["人工智能"],
            "main_direction": "up", "candidates": CANDS}
    quotes = {"688256": 9.0, "002415": 6.0, "300308": 3.0, "300474": 4.0}
    blob = build_live_blob(pred, quotes, as_of="09:18:30", market_pct=2.1)
    assert blob["phase"] == "auction" and blob["as_of"] == "09:18:30"
    assert blob["auction_score"]["sector_outcome"] == "hit"
    assert len(blob["candidates_live"]) == 4
    assert blob["candidates_live"][0]["code"] == "688256"   # 最强排首
    assert blob["candidate_hit_rate"] == 1.0
    print("✅ live blob 组装(含竞价打分+动态候选+兑现率)")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(f"运行 {len(tests)} 个竞价分析测试...\n")
    for t in tests:
        t()
    print(f"\n✅ 全部 {len(tests)} 个测试通过")
