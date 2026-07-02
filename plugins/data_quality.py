"""数据质量层 — 熔断器 + 数据质量打标

两个可复用原语，用于保证"数据准确度"（本项目 top 优先级）：

1. CircuitBreaker  熔断器
   连续失败 N 次的数据源自动熔断，冷却期内直接跳过，避免像东财 502 时
   那样对着死源反复硬捶（每个方法调用都重试 3 次 × 指数退避）。
   状态机: CLOSED --失败N次--> OPEN --冷却到期--> HALF_OPEN --成功--> CLOSED

2. DataQuality  数据质量标签
   每份数据附带来源、抓取时间、时效、降级来源、质量等级、缺失字段，
   让下游（尤其是 agent）能"看到"数据是新鲜/降级/过期/部分可用，
   而不是把脏数据当真值。

移植自参考项目 ZhuLinsen/daily_stock_analysis 的 realtime_types.py，
按本项目需要精简（用标准 logging，去掉行情专用字段）。
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Dict, List, Optional

logger = logging.getLogger("data_quality")


# ══════════════════════════════════════════════════════════════
#  1. 熔断器
# ══════════════════════════════════════════════════════════════

class CircuitBreaker:
    """按数据源管理熔断/冷却状态（线程安全）。

    - 连续失败达阈值 → 熔断（OPEN），冷却期内 is_available() 返回 False
    - 冷却到期 → 半开（HALF_OPEN），放行有限次试探
    - 试探成功 → 恢复（CLOSED）；试探失败 → 继续熔断
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(
        self,
        failure_threshold: int = 3,
        cooldown_seconds: float = 300.0,
        half_open_max_calls: int = 1,
    ):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.half_open_max_calls = half_open_max_calls
        self._states: Dict[str, Dict[str, Any]] = {}
        self._lock = RLock()

    def _get_state_locked(self, source: str) -> Dict[str, Any]:
        if source not in self._states:
            self._states[source] = {
                "state": self.CLOSED,
                "failures": 0,
                "last_failure_time": 0.0,
                "half_open_calls": 0,
            }
        return self._states[source]

    def is_available(self, source: str) -> bool:
        """返回 True 可尝试请求；False 表示熔断中应跳过。"""
        with self._lock:
            state = self._get_state_locked(source)
            now = time.time()

            if state["state"] == self.CLOSED:
                return True

            if state["state"] == self.OPEN:
                if now - state["last_failure_time"] >= self.cooldown_seconds:
                    state["state"] = self.HALF_OPEN
                    state["half_open_calls"] = 0
                    state["last_failure_time"] = now
                    logger.info("[熔断器] %s 冷却完成，进入半开", source)
                    # 落入下方 HALF_OPEN 分支
                else:
                    return False

            if state["state"] == self.HALF_OPEN:
                if state["half_open_calls"] < self.half_open_max_calls:
                    state["half_open_calls"] += 1
                    return True
                # 名额用尽但冷却又到期，重置试探避免永久卡死
                if now - state["last_failure_time"] >= self.cooldown_seconds:
                    state["half_open_calls"] = 1
                    state["last_failure_time"] = now
                    return True
                return False

            return True

    def record_success(self, source: str) -> None:
        with self._lock:
            state = self._get_state_locked(source)
            if state["state"] == self.HALF_OPEN:
                logger.info("[熔断器] %s 半开试探成功，恢复正常", source)
            state["state"] = self.CLOSED
            state["failures"] = 0
            state["half_open_calls"] = 0

    def record_failure(self, source: str, error: Optional[str] = None) -> None:
        with self._lock:
            state = self._get_state_locked(source)
            state["failures"] += 1
            state["last_failure_time"] = time.time()

            if state["state"] == self.HALF_OPEN:
                state["state"] = self.OPEN
                state["half_open_calls"] = 0
                logger.warning("[熔断器] %s 半开试探失败，继续熔断 %ss",
                               source, self.cooldown_seconds)
            elif state["failures"] >= self.failure_threshold:
                state["state"] = self.OPEN
                logger.warning("[熔断器] %s 连续失败 %d 次，熔断 %ss (最后错误: %s)",
                               source, state["failures"], self.cooldown_seconds, error)

    def record_inconclusive(self, source: str) -> None:
        """探测结果不确定（如返回 None/空）：半开转回熔断，冷却后重探。"""
        with self._lock:
            state = self._get_state_locked(source)
            if state["state"] == self.HALF_OPEN:
                state["state"] = self.OPEN
                state["half_open_calls"] = 0
                state["last_failure_time"] = time.time()

    def get_status(self) -> Dict[str, str]:
        with self._lock:
            return {src: info["state"] for src, info in self._states.items()}

    def reset(self, source: Optional[str] = None) -> None:
        with self._lock:
            if source:
                self._states.pop(source, None)
            else:
                self._states.clear()


# ══════════════════════════════════════════════════════════════
#  2. 数据质量标签
# ══════════════════════════════════════════════════════════════

# 质量等级
QUALITY_OK = "ok"                    # 主源正常返回
QUALITY_PARTIAL = "partial"          # 部分字段缺失
QUALITY_FALLBACK = "fallback"        # 主源失败，降级到备源
QUALITY_STALE = "stale"              # 数据超过时效阈值
QUALITY_UNAVAILABLE = "unavailable"  # 所有源都失败

# 中文标签（喂给 agent 的 prompt 用，让它"看到"数据成色）
QUALITY_LABELS_ZH = {
    QUALITY_OK: "可用",
    QUALITY_PARTIAL: "部分可用",
    QUALITY_FALLBACK: "降级",
    QUALITY_STALE: "过期",
    QUALITY_UNAVAILABLE: "不可用",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


@dataclass
class DataQuality:
    """一份数据的质量元信息。附在任何数据 payload 旁边。"""
    source: str                                  # 实际提供数据的源
    fetched_at: str = field(default_factory=_now_iso)  # 本系统抓取时刻
    provider_timestamp: Optional[str] = None     # 数据源自报的数据时刻
    is_stale: bool = False                        # 是否超过时效阈值
    stale_seconds: Optional[int] = None           # 数据年龄（秒）
    fallback_from: Optional[str] = None           # 首选源（失败后降级而来）
    data_quality: str = QUALITY_OK                # 质量等级
    missing_fields: List[str] = field(default_factory=list)

    @property
    def label_zh(self) -> str:
        return QUALITY_LABELS_ZH.get(self.data_quality, self.data_quality)

    def mark_stale(self, age_seconds: int) -> "DataQuality":
        """按数据年龄标记时效（返回新对象，不原地改）。"""
        return DataQuality(
            source=self.source,
            fetched_at=self.fetched_at,
            provider_timestamp=self.provider_timestamp,
            is_stale=True,
            stale_seconds=age_seconds,
            fallback_from=self.fallback_from,
            data_quality=QUALITY_STALE,
            missing_fields=list(self.missing_fields),
        )

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["label_zh"] = self.label_zh
        return d


def assess_freshness(
    provider_timestamp: Optional[str],
    ttl_seconds: int,
    now: Optional[float] = None,
) -> tuple[bool, Optional[int]]:
    """按数据源自报时刻判断是否过期。

    Args:
        provider_timestamp: ISO 时间字符串；None 表示无法判断
        ttl_seconds: 超过此秒数视为过期
        now: 当前 epoch 秒（便于测试注入）

    Returns:
        (is_stale, age_seconds)。无法解析时间时返回 (False, None)。
    """
    if not provider_timestamp:
        return False, None
    try:
        dt = datetime.fromisoformat(provider_timestamp)
        if dt.tzinfo is None:
            dt = dt.astimezone()
        age = int((now if now is not None else time.time()) - dt.timestamp())
    except (ValueError, TypeError):
        return False, None
    return age > ttl_seconds, max(age, 0)


# 全局熔断器：数据层所有 AKShare 调用共用
data_source_breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=300.0)
