"""数据质量层单元测试（纯逻辑，无网络）。

运行: ./venv/bin/python3 test_data_quality.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from plugins.data_quality import (
    CircuitBreaker,
    DataQuality,
    assess_freshness,
    QUALITY_STALE,
    QUALITY_OK,
)


def test_breaker_opens_after_threshold():
    cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=999)
    src = "dead_source"
    assert cb.is_available(src) is True          # 初始 CLOSED
    for _ in range(3):
        cb.record_failure(src, "boom")
    assert cb.is_available(src) is False         # 达阈值 → OPEN，跳过
    assert cb.get_status()[src] == CircuitBreaker.OPEN
    print("✅ 连续失败达阈值后熔断")


def test_breaker_recovers_after_cooldown():
    cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=0.0)  # 冷却0秒
    src = "flaky"
    cb.record_failure(src)
    cb.record_failure(src)
    assert cb.get_status()[src] == CircuitBreaker.OPEN
    # 冷却已到期 → 半开放行一次
    assert cb.is_available(src) is True
    assert cb.get_status()[src] == CircuitBreaker.HALF_OPEN
    cb.record_success(src)                        # 半开试探成功 → 恢复
    assert cb.get_status()[src] == CircuitBreaker.CLOSED
    print("✅ 冷却到期半开试探成功后恢复")


def test_breaker_halfopen_failure_reopens():
    cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=0.0)
    src = "still_dead"
    cb.record_failure(src)
    assert cb.is_available(src) is True           # 半开放行
    cb.record_failure(src)                        # 半开又失败
    assert cb.get_status()[src] == CircuitBreaker.OPEN
    print("✅ 半开试探失败后继续熔断")


def test_breaker_isolates_sources():
    cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=999)
    cb.record_failure("bad")
    assert cb.is_available("bad") is False
    assert cb.is_available("good") is True        # 一个源熔断不影响其他源
    print("✅ 数据源之间熔断相互隔离")


def test_freshness_stale_and_fresh():
    now = 1_000_000.0
    # 数据时刻比 now 早 120 秒，TTL=60 → 过期
    from datetime import datetime
    old_ts = datetime.fromtimestamp(now - 120).astimezone().isoformat()
    is_stale, age = assess_freshness(old_ts, ttl_seconds=60, now=now)
    assert is_stale is True and age == 120
    # 早 10 秒，TTL=60 → 新鲜
    fresh_ts = datetime.fromtimestamp(now - 10).astimezone().isoformat()
    is_stale2, age2 = assess_freshness(fresh_ts, ttl_seconds=60, now=now)
    assert is_stale2 is False and age2 == 10
    # 无时间戳 → 无法判断，不误报过期
    assert assess_freshness(None, 60, now=now) == (False, None)
    print("✅ 时效判断: 过期/新鲜/无时间戳")


def test_dataquality_mark_stale_immutable():
    dq = DataQuality(source="cls", data_quality=QUALITY_OK)
    dq2 = dq.mark_stale(300)
    assert dq.data_quality == QUALITY_OK          # 原对象不变
    assert dq2.data_quality == QUALITY_STALE and dq2.is_stale is True
    assert dq2.stale_seconds == 300
    assert dq2.label_zh == "过期"
    assert "label_zh" in dq2.to_dict()
    print("✅ 质量标签不可变更新 + 中文标签")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(f"运行 {len(tests)} 个数据质量测试...\n")
    for t in tests:
        t()
    print(f"\n✅ 全部 {len(tests)} 个测试通过")
