"""预测记录 v2 + KV 存储层单元测试（纯逻辑 + 本地 KV，无网络）。

运行: ./venv/bin/python3 test_prediction_record.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from engines.prediction_record import (
    PredictionRecord, Prediction, Candidate, build_record,
    STATUS_PREDICTED, STATUS_AUCTION_SCORED, STATUS_CLOSED, SCHEMA_VERSION,
)
from engines.sector_scorer import score_prediction, SectorPrediction
from cloud.kv_client import (
    LocalKV, PredictionKV, KEY_PRED_LATEST, KEY_HEARTBEAT, KEY_DATES,
)


def test_v1_upgrade():
    """v1 {picks} 记录能无损升级到 v2。"""
    v1 = {"date": "2026-06-24", "market_context": "test",
          "picks": [{"code": "600000", "name": "浦发银行"}],
          "created_at": "2026-06-24T11:02:07"}
    rec = PredictionRecord.from_dict(v1)
    assert rec.schema_version == SCHEMA_VERSION
    assert rec.date == "2026-06-24"
    assert rec.prediction.candidates[0].code == "600000"
    assert rec.prediction.main_sectors == []      # v1 无板块预测
    assert rec.status == STATUS_PREDICTED
    print("✅ v1→v2 无损升级")


def test_v2_roundtrip():
    rec = build_record(
        date="2026-07-02",
        main_sectors=["人工智能", "半导体"],
        main_direction="up",
        candidates=[{"code": "600000", "name": "X", "sector": "人工智能", "rank": 1}],
        market_context="AI 主线",
        data_quality={"overall": "ok"},
    )
    d = rec.to_dict()
    rec2 = PredictionRecord.from_dict(d)
    assert rec2.prediction.main_sectors == ["人工智能", "半导体"]
    assert rec2.prediction.main_direction == "up"
    assert rec2.prediction.candidates[0].sector == "人工智能"
    # 兼容旧 tracker: to_dict 派生 picks
    assert d["picks"][0]["code"] == "600000"
    assert d["picks"][0]["strategy"] == "limit_up_continuation"
    print("✅ v2 round-trip + 兼容 picks 派生")


def test_kv_payload_shape():
    rec = build_record("2026-07-02", ["机器人"], "up",
                       [{"code": "300024"}], data_quality={"overall": "partial"})
    kv = rec.to_kv_payload()
    assert kv["main_sectors"] == ["机器人"]
    assert kv["data_quality_overall"] == "partial"
    assert "picks" not in kv          # KV blob 不含冗余派生
    assert kv["evaluation"] == {"auction": None, "close": None}
    print("✅ KV payload 精简且含双轨槽")


def test_attach_evaluation_immutable():
    rec = build_record("2026-07-02", ["人工智能"], "up", [{"code": "600000"}])
    counts = {"人工智能": 12, "半导体": 5}
    score = score_prediction(
        SectorPrediction(date="2026-07-02", main_sectors=["人工智能"],
                         main_direction="up"),
        counts, direction_ref_pct=3.0, track="close").to_dict()

    rec2 = rec.attach_evaluation("close", score)
    # 原记录不变(不可变)
    assert rec.evaluation["close"] is None and rec.status == STATUS_PREDICTED
    # 新记录挂上评估 + 状态流转
    assert rec2.evaluation["close"]["sector_outcome"] == "hit"
    assert "scored_at" in rec2.evaluation["close"]
    assert rec2.status == STATUS_CLOSED

    rec3 = rec.attach_evaluation("auction", score)
    assert rec3.status == STATUS_AUCTION_SCORED
    print("✅ 双轨评估不可变挂载 + 状态流转")


def test_attach_unknown_track_raises():
    rec = build_record("2026-07-02", ["X"], "up", [])
    try:
        rec.attach_evaluation("bogus", {})
        assert False, "应拒绝未知轨"
    except ValueError:
        print("✅ 未知评估轨被拒绝")


def test_local_kv_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        kv = LocalKV(base_dir=tmp)
        kv.put("pred:2026-07-02", {"a": 1, "中文": "值"})
        assert kv.get("pred:2026-07-02") == {"a": 1, "中文": "值"}
        assert kv.get("missing:key") is None      # 不存在返回 None
        print("✅ 本地 KV 读写 round-trip + 缺键返回 None")


def test_prediction_kv_semantics():
    with tempfile.TemporaryDirectory() as tmp:
        pkv = PredictionKV(backend=LocalKV(base_dir=tmp))
        rec = build_record("2026-07-02", ["人工智能"], "up", [{"code": "600000"}])

        pkv.write_prediction("2026-07-02", rec.to_kv_payload())
        latest = pkv.read_prediction()
        assert latest["date"] == "2026-07-02"
        assert pkv.read_prediction("2026-07-02")["main_sectors"] == ["人工智能"]
        assert pkv.list_dates() == ["2026-07-02"]

        pkv.write_live({"竞价强度": 0.8}, phase="auction")
        assert pkv.read_live()["竞价强度"] == 0.8

        hb = pkv.read_heartbeat()
        assert hb["phase"] == "auction" and "last_update" in hb
        print("✅ PredictionKV 语义读写(预测/实时/心跳/日期索引)")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(f"运行 {len(tests)} 个预测记录+KV测试...\n")
    for t in tests:
        t()
    print(f"\n✅ 全部 {len(tests)} 个测试通过")
