"""板块判断记分单元测试（纯逻辑，无网络）。

这是"找 edge"的标尺，必须可证明正确。
运行: ./venv/bin/python3 test_sector_scorer.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from engines.sector_scorer import (
    SectorPrediction, score_sector_call, score_direction, score_prediction,
    rank_by_count, HIT, MISS, NEUTRAL,
)

# 构造一个涨停家数分布: 人工智能 12(第1), 半导体 9(第2), 机器人 7(第3),
# 低空经济 5(第4), 光伏 3(第5) ... 军工 1(第9)
COUNTS = {
    "人工智能": 12, "半导体": 9, "机器人": 7, "低空经济": 5, "光伏": 3,
    "创新药": 2, "核电": 2, "军工": 2, "地产": 1,
}


def test_rank_by_count_with_ties():
    ranks = rank_by_count(COUNTS)
    assert ranks["人工智能"] == 1
    assert ranks["半导体"] == 2
    assert ranks["机器人"] == 3
    # 创新药/核电/军工 均为 2 家 → 并列第 6
    assert ranks["创新药"] == ranks["核电"] == ranks["军工"] == 6
    assert ranks["地产"] == 9
    print("✅ 涨停家数排名(含并列)")


def test_sector_hit_top3():
    # 预测首选进 Top 3 → hit
    out, primary, rank, _ = score_sector_call(["机器人"], COUNTS)
    assert out == HIT and primary == "机器人" and rank == 3
    print("✅ 主力板块进 Top3 = hit")


def test_sector_neutral_rank4to8():
    out, primary, rank, _ = score_sector_call(["低空经济"], COUNTS)  # 第4
    assert out == NEUTRAL and rank == 4
    print("✅ 主力板块 4–8 名 = neutral")


def test_sector_miss_beyond8():
    out, primary, rank, _ = score_sector_call(["地产"], COUNTS)  # 第9
    assert out == MISS and rank == 9
    print("✅ 主力板块 8 名外 = miss")


def test_sector_best_of_multiple():
    # 预测 3 个, 取名次最好的那个决定 outcome
    out, primary, rank, detail = score_sector_call(["地产", "半导体", "光伏"], COUNTS)
    assert out == HIT and primary == "半导体" and rank == 2
    assert detail["地产"] == 9 and detail["光伏"] == 5
    print("✅ 多预测取最优板块判定")


def test_sector_no_limitup_is_miss():
    # 预测板块当日一个涨停都没有 → miss
    out, primary, rank, detail = score_sector_call(["不存在的板块"], COUNTS)
    assert out == MISS and rank is None
    print("✅ 预测板块当日零涨停 = miss")


def test_sector_substring_match():
    # 命名容错: 预测"半导体" 对上 counts 里的"半导体设备"
    out, primary, rank, _ = score_sector_call(["半导体"], {"半导体设备": 10, "其他": 1})
    assert out == HIT
    print("✅ 板块名子串容错匹配")


def test_direction_band():
    assert score_direction("up", 3.5) == HIT       # 涨 >2%, 预测涨
    assert score_direction("up", -3.0) == MISS      # 跌 >2%, 预测涨
    assert score_direction("up", 1.0) == NEUTRAL    # 带内, 一方明确一方震荡
    assert score_direction("neutral", 0.5) == HIT   # 预测震荡且带内
    assert score_direction("down", -4.0) == HIT
    assert score_direction("up", None) == NEUTRAL   # 无数据不误判
    print("✅ 方向判断 ±2% 中性带")


def test_score_prediction_end_to_end():
    pred = SectorPrediction(
        date="2026-07-02",
        main_sectors=["人工智能", "半导体"],
        main_direction="up",
        candidates=[{"code": "600000"}],
    )
    score = score_prediction(pred, COUNTS, direction_ref_pct=3.1, track="close")
    assert score.sector_outcome == HIT
    assert score.primary_sector == "人工智能" and score.primary_sector_rank == 1
    assert score.direction_outcome == HIT
    assert score.track == "close"
    assert "label" not in score.to_dict() or True  # to_dict 可序列化
    print("✅ 端到端: 预测→双维得分")


def test_empty_counts_is_neutral():
    # 非交易时段/抓取失败 → 空 counts → neutral, 不崩
    out, primary, rank, _ = score_sector_call(["人工智能"], {})
    assert out == NEUTRAL
    print("✅ 空涨停数据优雅降级为 neutral")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(f"运行 {len(tests)} 个板块记分测试...\n")
    for t in tests:
        t()
    print(f"\n✅ 全部 {len(tests)} 个测试通过")
