"""预测记录 v2 — 统一承载: 板块预测 + 15 候选 + 双轨评估 + 上云

为什么升级 v1:
  v1 = {date, market_context, picks, created_at} —— 只有个股 picks, 无板块预测、
  无双轨评估槽、无数据质量、不适合直接推 KV 给 dashboard。

v2 一份记录同时服务三方:
  1. sector_scorer  → prediction.main_sectors / main_direction / candidates
  2. 双轨评估       → evaluation.auction(竞价当场) / evaluation.close(收盘复核)
  3. dashboard/KV   → to_kv_payload() 输出干净可序列化 blob + status + 时间戳

向后兼容: from_dict() 自动把 v1 记录升级为 v2(picks→candidates), tracker 不受影响。
不可变: attach_evaluation() 返回新记录, 不原地改。
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field, asdict, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

SCHEMA_VERSION = 2

# status 流转
STATUS_PREDICTED = "predicted"        # 盘前刚产出
STATUS_AUCTION_SCORED = "auction_scored"  # 竞价当场已打分
STATUS_CLOSED = "closed"              # 收盘复核已完成


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


@dataclass(frozen=True)
class Candidate:
    """一只候选涨停股。"""
    code: str
    name: str = ""
    sector: str = ""
    reason: str = ""
    rank: Optional[int] = None

    @staticmethod
    def from_any(d: Any) -> "Candidate":
        if isinstance(d, str):
            return Candidate(code=d)
        return Candidate(
            code=str(d.get("code", "")),
            name=str(d.get("name", "")),
            sector=str(d.get("sector", "")),
            reason=str(d.get("reason", "")),
            rank=d.get("rank"),
        )


@dataclass(frozen=True)
class Prediction:
    """盘前 agent 的板块级预测。"""
    main_sectors: List[str] = field(default_factory=list)   # 主力板块 1–3, [0]首选
    main_direction: str = "neutral"                          # up/down/neutral
    candidates: List[Candidate] = field(default_factory=list)  # 15 候选


@dataclass(frozen=True)
class PredictionRecord:
    """v2 统一预测记录。"""
    date: str
    prediction: Prediction
    market_context: str = ""
    created_at: str = field(default_factory=_now)
    evaluation: Dict[str, Optional[dict]] = field(
        default_factory=lambda: {"auction": None, "close": None})
    data_quality: Dict[str, Any] = field(default_factory=dict)
    status: str = STATUS_PREDICTED
    schema_version: int = SCHEMA_VERSION

    # ── 构造 / 兼容 ──────────────────────────────────────
    @staticmethod
    def from_dict(d: dict) -> "PredictionRecord":
        """从 dict 载入; v1(有 picks 无 prediction)自动升级为 v2。"""
        if d.get("schema_version") == SCHEMA_VERSION and "prediction" in d:
            p = d["prediction"]
            pred = Prediction(
                main_sectors=list(p.get("main_sectors", [])),
                main_direction=(p.get("main_direction") or "neutral").lower(),
                candidates=[Candidate.from_any(c) for c in p.get("candidates", [])],
            )
            return PredictionRecord(
                date=d.get("date", ""),
                prediction=pred,
                market_context=d.get("market_context", ""),
                created_at=d.get("created_at", _now()),
                evaluation=d.get("evaluation") or {"auction": None, "close": None},
                data_quality=d.get("data_quality", {}),
                status=d.get("status", STATUS_PREDICTED),
                schema_version=SCHEMA_VERSION,
            )
        # ── v1 升级路径 ──
        return PredictionRecord._upgrade_v1(d)

    @staticmethod
    def _upgrade_v1(d: dict) -> "PredictionRecord":
        """v1 {date, market_context, picks[], created_at} → v2。

        无板块预测数据, 故 main_sectors/direction 留空; picks 迁到 candidates 以保信息。
        """
        picks = d.get("picks", []) or []
        candidates = [Candidate.from_any(p) for p in picks]
        return PredictionRecord(
            date=d.get("date", ""),
            prediction=Prediction(candidates=candidates),
            market_context=d.get("market_context", ""),
            created_at=d.get("created_at", _now()),
            status=STATUS_PREDICTED,
        )

    # ── 序列化 ───────────────────────────────────────────
    def to_dict(self) -> dict:
        """完整落盘用(含兼容 tracker 的 picks 派生字段)。"""
        d = {
            "schema_version": self.schema_version,
            "date": self.date,
            "created_at": self.created_at,
            "market_context": self.market_context,
            "prediction": {
                "main_sectors": list(self.prediction.main_sectors),
                "main_direction": self.prediction.main_direction,
                "candidates": [asdict(c) for c in self.prediction.candidates],
            },
            "evaluation": self.evaluation,
            "data_quality": self.data_quality,
            "status": self.status,
            # 兼容旧 tracker: picks 由 candidates 派生
            "picks": [self._candidate_to_pick(c) for c in self.prediction.candidates],
        }
        return d

    @staticmethod
    def _candidate_to_pick(c: Candidate) -> dict:
        return {"code": c.code, "name": c.name,
                "strategy": "limit_up_continuation", "sector": c.sector}

    def to_kv_payload(self) -> dict:
        """dashboard/KV 展示用的精简 blob(不含 picks 派生冗余)。"""
        return {
            "date": self.date,
            "status": self.status,
            "created_at": self.created_at,
            "market_context": self.market_context,
            "main_sectors": list(self.prediction.main_sectors),
            "main_direction": self.prediction.main_direction,
            "candidates": [asdict(c) for c in self.prediction.candidates],
            "evaluation": self.evaluation,
            "data_quality_overall": self.data_quality.get("overall", "unknown"),
        }

    # ── 不可变更新 ───────────────────────────────────────
    def attach_evaluation(self, track: str, score: dict, status: Optional[str] = None
                          ) -> "PredictionRecord":
        """把某一轨(auction/close)的评估结果挂上, 返回新记录。

        Args:
            track: "auction" | "close"
            score: SectorScore.to_dict()
            status: 可选新 status(默认按 track 推断)
        """
        if track not in ("auction", "close"):
            raise ValueError(f"未知评估轨: {track}")
        new_eval = dict(self.evaluation)
        new_eval[track] = {"scored_at": _now(), **score}
        new_status = status or (
            STATUS_CLOSED if track == "close" else STATUS_AUCTION_SCORED)
        return replace(self, evaluation=new_eval, status=new_status)


def build_record(
    date: str,
    main_sectors: List[str],
    main_direction: str,
    candidates: List[dict],
    market_context: str = "",
    data_quality: Optional[dict] = None,
) -> PredictionRecord:
    """从 agent 原始产出构造一条 v2 记录。"""
    return PredictionRecord(
        date=date,
        prediction=Prediction(
            main_sectors=list(main_sectors),
            main_direction=(main_direction or "neutral").lower(),
            candidates=[Candidate.from_any(c) for c in candidates],
        ),
        market_context=market_context,
        data_quality=data_quality or {},
    )
