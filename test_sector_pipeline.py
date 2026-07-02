"""板块预测闭环端到端测试（离线，注入涨停家数，无网络）。

证明: 合成预测 → 存盘+KV → 收盘打分 → 结果+KV → 准确率统计 整条串得起来。
运行: ./venv/bin/python3 test_sector_pipeline.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import engines.sector_pipeline as sp
from engines.prediction_record import build_record, STATUS_CLOSED
from cloud.kv_client import PredictionKV, LocalKV


def _isolate(tmp: str):
    """把 pipeline 的读写目录 + KV 指向临时目录，避免污染真实数据。"""
    sp.PRED_DIR = Path(tmp) / "predictions"
    sp.RESULT_DIR = Path(tmp) / "results"
    kv = PredictionKV(backend=LocalKV(base_dir=str(Path(tmp) / "kv")))
    return kv


def test_full_loop_hit():
    with tempfile.TemporaryDirectory() as tmp:
        kv = _isolate(tmp)

        # 1) 盘前: 合成预测(主力板块=人工智能, 方向=up)
        rec = build_record(
            date="2026-07-02",
            main_sectors=["人工智能", "半导体"],
            main_direction="up",
            candidates=[{"code": "600000", "name": "X", "sector": "人工智能"}],
            market_context="AI 主线",
            data_quality={"overall": "ok"},
        )
        sp.save_prediction(rec, kv=kv)
        assert (sp.PRED_DIR / "2026-07-02.json").is_file()
        assert kv.read_prediction()["main_sectors"] == ["人工智能", "半导体"]
        assert kv.list_dates() == ["2026-07-02"]

        # 2) 收盘: 注入涨停家数(人工智能第1) + 方向实际 +3% → 双命中
        counts = {"人工智能": 12, "半导体": 6, "机器人": 4}
        scored = sp.score_close("2026-07-02", sector_counts=counts,
                                direction_ref_pct=3.0, kv=kv)
        assert scored.status == STATUS_CLOSED
        assert scored.evaluation["close"]["sector_outcome"] == "hit"
        assert scored.evaluation["close"]["direction_outcome"] == "hit"
        assert (sp.RESULT_DIR / "2026-07-02.json").is_file()
        # KV 已更新为已复核记录
        assert kv.read_prediction()["status"] == STATUS_CLOSED
        print("✅ 闭环(命中): 预测→存KV→收盘打分→结果+KV")


def test_full_loop_miss_and_stats():
    with tempfile.TemporaryDirectory() as tmp:
        kv = _isolate(tmp)

        # 两条预测: 一条板块命中方向错, 一条板块未中
        sp.save_prediction(build_record(
            "2026-07-01", ["人工智能"], "up", [{"code": "1"}]), kv=kv)
        sp.save_prediction(build_record(
            "2026-07-02", ["地产"], "down", [{"code": "2"}]), kv=kv)

        # 2026-07-01: 人工智能第1(hit) 但实际跌3%(方向 miss)
        sp.score_close("2026-07-01", sector_counts={"人工智能": 10, "军工": 2},
                       direction_ref_pct=-3.0, kv=kv)
        # 2026-07-02: 地产第9(miss), 实际跌4%(方向 down hit)
        sp.score_close("2026-07-02",
                       sector_counts={f"板块{i}": 12 - i for i in range(9)} | {"地产": 1},
                       direction_ref_pct=-4.0, kv=kv)

        stats = sp.aggregate_sector_stats()
        assert stats["evaluated"] == 2
        assert stats["sector"]["hit"] == 1 and stats["sector"]["miss"] == 1
        assert stats["direction"]["hit"] == 1 and stats["direction"]["miss"] == 1
        # 板块准确率 = 1 hit / (1 hit + 1 miss) = 50%
        assert abs(stats["sector"]["accuracy"] - 50.0) < 1e-6
        md = sp.render_sector_stats_md(stats)
        assert "主力板块" in md and "板块判断准确率" in md
        print("✅ 闭环(混合)+ 板块准确率统计")


def test_neutral_not_in_accuracy_denominator():
    with tempfile.TemporaryDirectory() as tmp:
        kv = _isolate(tmp)
        # 板块进第5名 = neutral(不进准确率分母)
        sp.save_prediction(build_record(
            "2026-07-02", ["光伏"], "neutral", [{"code": "1"}]), kv=kv)
        sp.score_close("2026-07-02",
                       sector_counts={f"S{i}": 10 - i for i in range(4)} | {"光伏": 5},
                       direction_ref_pct=0.5, kv=kv)
        stats = sp.aggregate_sector_stats()
        assert stats["sector"]["neutral"] == 1
        assert stats["sector"]["accuracy"] == 0.0   # 无 hit/miss, 分母为0
        print("✅ 中性不计入准确率分母")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(f"运行 {len(tests)} 个闭环测试...\n")
    for t in tests:
        t()
    print(f"\n✅ 全部 {len(tests)} 个测试通过")
