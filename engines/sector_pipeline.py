"""板块预测闭环 v2 — save → score → stats，并推送 KV

串起 Phase ① 的测量闭环:
  盘前  save_prediction()  → predictions/{date}.json + KV(pred:latest)
  收盘  score_close()      → 拉涨停家数 → sector_scorer 打分 → attach close 评估
                           → results/{date}.json + KV 更新
  复盘  aggregate_sector_stats() → 板块判断准确率(找 edge 的标尺)

与 tracker.py 关系: tracker 保留旧个股 P&L 口径不动; 本模块是 v2 板块判断新口径,
共用 predictions/ 与 results/ 目录(v2 记录), 读时自动兼容 v1。

离线可测: score_close 接受注入的 sector_counts/direction_ref_pct, 无网络也能跑通闭环。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engines.prediction_record import PredictionRecord, build_record
from engines.sector_scorer import (
    SectorPrediction, score_prediction, fetch_sector_limitup_counts,
    HIT, MISS, NEUTRAL,
)

PRED_DIR = PROJECT_ROOT / "predictions"
RESULT_DIR = PROJECT_ROOT / "results"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    tmp.replace(path)


def _get_kv():
    """惰性构造 KV client(避免离线测试强依赖)。失败则返回 None。"""
    try:
        from cloud.kv_client import PredictionKV
        return PredictionKV()
    except Exception as e:  # noqa: BLE001
        print(f"[sector_pipeline] KV 不可用, 跳过推送: {e}")
        return None


# ══════════════════════════════════════════════════════════
#  save / load
# ══════════════════════════════════════════════════════════

def save_prediction(record: PredictionRecord, push_kv: bool = True, kv=None) -> Path:
    """盘前: 落盘 v2 预测 + 推 KV(pred:latest / pred:{date})。"""
    path = PRED_DIR / f"{record.date}.json"
    _write_json(path, record.to_dict())
    if push_kv:
        kv = kv or _get_kv()
        if kv:
            kv.write_prediction(record.date, record.to_kv_payload())
    print(f"✅ 预测已存: {path} | 主力板块={record.prediction.main_sectors} "
          f"方向={record.prediction.main_direction} "
          f"候选={len(record.prediction.candidates)}")
    return path


def load_prediction(date: str) -> PredictionRecord:
    """读预测记录(v1 自动升级 v2)。"""
    path = PRED_DIR / f"{date}.json"
    if not path.is_file():
        raise FileNotFoundError(f"找不到预测: {path}")
    return PredictionRecord.from_dict(_read_json(path))


# ══════════════════════════════════════════════════════════
#  score (收盘复核轨)
# ══════════════════════════════════════════════════════════

def score_close(
    date: str,
    sector_counts: Optional[Dict[str, int]] = None,
    direction_ref_pct: Optional[float] = None,
    push_kv: bool = True,
    kv=None,
) -> PredictionRecord:
    """收盘复核: 打分 → 挂 close 评估 → 存 results → 推 KV。

    sector_counts=None 时实时抓取当日涨停家数(网络);
    传入则离线打分(测试/回放)。
    """
    record = load_prediction(date)
    if sector_counts is None:
        sector_counts = fetch_sector_limitup_counts(date)

    sp = SectorPrediction(
        date=record.date,
        main_sectors=record.prediction.main_sectors,
        main_direction=record.prediction.main_direction,
    )
    score = score_prediction(sp, sector_counts, direction_ref_pct, track="close")
    scored = record.attach_evaluation("close", score.to_dict())

    out = RESULT_DIR / f"{date}.json"
    _write_json(out, scored.to_dict())
    if push_kv:
        kv = kv or _get_kv()
        if kv:
            kv.write_prediction(date, scored.to_kv_payload())
    print(f"✅ 收盘复核: {date} | 板块={score.sector_outcome}"
          f"(首选 {score.primary_sector} 第{score.primary_sector_rank}名) "
          f"方向={score.direction_outcome} → {out}")
    return scored


# ══════════════════════════════════════════════════════════
#  aggregate (板块判断准确率 — 找 edge 的标尺)
# ══════════════════════════════════════════════════════════

def _iter_closed_results(days: Optional[int] = None) -> List[dict]:
    if not RESULT_DIR.is_dir():
        return []
    files = sorted(RESULT_DIR.glob("*.json"), key=lambda p: p.stem)
    recs = []
    for p in files:
        try:
            d = _read_json(p)
        except (ValueError, OSError):
            continue
        close = (d.get("evaluation") or {}).get("close")
        if close and close.get("sector_outcome"):
            recs.append(d)
    if days is not None:
        recs = recs[-days:]
    return recs


def aggregate_sector_stats(days: Optional[int] = None) -> dict:
    """汇总板块判断 + 方向判断准确率。"""
    recs = _iter_closed_results(days)

    def tally(field: str) -> dict:
        c = {HIT: 0, MISS: 0, NEUTRAL: 0}
        for d in recs:
            o = d["evaluation"]["close"].get(field)
            if o in c:
                c[o] += 1
        total = sum(c.values())
        # 准确率: hit / (hit+miss), 中性不计入分母(未证伪也未证实)
        decided = c[HIT] + c[MISS]
        acc = (c[HIT] / decided * 100.0) if decided else 0.0
        hit_rate = (c[HIT] / total * 100.0) if total else 0.0
        return {**c, "total": total, "accuracy": acc, "hit_rate": hit_rate}

    return {
        "days_window": days or "全部",
        "evaluated": len(recs),
        "sector": tally("sector_outcome"),
        "direction": tally("direction_outcome"),
    }


def render_sector_stats_md(stats: dict) -> str:
    s, d = stats["sector"], stats["direction"]
    lines = [
        f"## 🎯 板块判断准确率 (近{stats['days_window']}日, 共 {stats['evaluated']} 次已复核)",
        "",
        "| 维度 | 命中 | 中性 | 未中 | 准确率(hit/决出) | 命中率(hit/全部) |",
        "|------|------|------|------|------------------|------------------|",
        f"| 主力板块 | {s[HIT]} | {s[NEUTRAL]} | {s[MISS]} | {s['accuracy']:.1f}% | {s['hit_rate']:.1f}% |",
        f"| 主力方向 | {d[HIT]} | {d[NEUTRAL]} | {d[MISS]} | {d['accuracy']:.1f}% | {d['hit_rate']:.1f}% |",
        "",
        "> 准确率分母剔除中性(未证伪);命中率含中性做分母。板块 Top3=命中, 方向 ±2% 中性带。",
    ]
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════

def _cmd_save(args) -> int:
    data = json.loads(Path(args.record[1:]).read_text(encoding="utf-8")) \
        if args.record.startswith("@") else json.loads(args.record)
    record = build_record(
        date=args.date or data["date"],
        main_sectors=data.get("main_sectors", []),
        main_direction=data.get("main_direction", "neutral"),
        candidates=data.get("candidates", []),
        market_context=data.get("market_context", ""),
        data_quality=data.get("data_quality", {}),
    )
    save_prediction(record, push_kv=not args.no_kv)
    return 0


def _cmd_score(args) -> int:
    counts = None
    if args.counts:
        counts = json.loads(Path(args.counts[1:]).read_text(encoding="utf-8")) \
            if args.counts.startswith("@") else json.loads(args.counts)
    score_close(args.date, sector_counts=counts,
                direction_ref_pct=args.direction_pct, push_kv=not args.no_kv)
    return 0


def _cmd_stats(args) -> int:
    stats = aggregate_sector_stats(days=args.days)
    print(render_sector_stats_md(stats))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="板块预测闭环 v2 (save/score/stats)")
    sub = p.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("save", help="保存 v2 板块预测")
    ps.add_argument("--date", help="YYYY-MM-DD (缺省用 record.date)")
    ps.add_argument("--record", required=True, help="JSON 或 @文件路径")
    ps.add_argument("--no-kv", action="store_true", help="不推送 KV")
    ps.set_defaults(func=_cmd_save)

    pc = sub.add_parser("score", help="收盘复核打分")
    pc.add_argument("--date", required=True)
    pc.add_argument("--counts", help="注入涨停家数 JSON/@文件(缺省实时抓取)")
    pc.add_argument("--direction-pct", type=float, help="方向判据实际涨幅%")
    pc.add_argument("--no-kv", action="store_true")
    pc.set_defaults(func=_cmd_score)

    pt = sub.add_parser("stats", help="板块判断准确率")
    pt.add_argument("--days", type=int, help="近 N 日(缺省全部)")
    pt.set_defaults(func=_cmd_stats)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
