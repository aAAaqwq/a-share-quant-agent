#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股选股预测落库 + 统计工具
==========================

纯标准库实现，零外部依赖（不依赖 akshare / pandas / numpy）。

CLI:
    python tracker.py save --date YYYY-MM-DD --picks '<JSON 或 @file.json>'
    python tracker.py stats --days N [--json]
    python tracker.py result --date YYYY-MM-DD [--picks '<JSON>' | @file.json]

数据落点:
    predictions/YYYY-MM-DD.json   # 选股预测
    results/YYYY-MM-DD.json       # 验证结果

成本模型（统计时应用）:
    buy_cost  = entry_price * 1.0001    # 滑点 0.01% + 佣金 0.025% 单边
    sell_recv = exit_price  * 0.99885   # 滑点 0.01% + 佣金 0.025% + 印花税 0.05%
    pnl%      = (sell_recv - buy_cost) / buy_cost * 100
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# 路径常量
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
PRED_DIR = BASE_DIR / "predictions"
RESULT_DIR = BASE_DIR / "results"

# 成本模型常量
BUY_FACTOR = 1.0001   # 买入侧：滑点 0.01% + 佣金 0.025%
SELL_FACTOR = 0.99885 # 卖出侧：滑点 0.01% + 佣金 0.025% + 印花税 0.05%


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def ensure_dirs() -> None:
    """确保 predictions/ 与 results/ 目录存在。"""
    PRED_DIR.mkdir(parents=True, exist_ok=True)
    RESULT_DIR.mkdir(parents=True, exist_ok=True)


def load_picks_arg(picks_arg: str) -> dict:
    """
    解析 --picks 参数：
      - 以 '@' 开头视为文件路径
      - 否则视为 JSON 字符串
    """
    if picks_arg.startswith("@"):
        path = Path(picks_arg[1:]).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"找不到 picks 文件: {path}")
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    return json.loads(picks_arg)


def write_json(path: Path, data: dict) -> None:
    """UTF-8 写入 JSON，ensure_ascii=False，indent=2。"""
    ensure_dirs()
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp.replace(path)


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def list_date_files(directory: Path) -> list:
    """按日期排序返回目录下所有 YYYY-MM-DD.json。"""
    if not directory.is_dir():
        return []
    files = []
    for p in directory.glob("*.json"):
        name = p.stem
        try:
            datetime.strptime(name, "%Y-%m-%d")
            files.append(p)
        except ValueError:
            continue
    return sorted(files, key=lambda p: p.stem)


# ---------------------------------------------------------------------------
# 成本 / pnl 计算
# ---------------------------------------------------------------------------
def apply_cost_model(entry_price: float, exit_price: float) -> float:
    """按成本模型计算 pnl%（百分比数值）。"""
    buy_cost = entry_price * BUY_FACTOR
    sell_recv = exit_price * SELL_FACTOR
    return (sell_recv - buy_cost) / buy_cost * 100.0


def build_pnl_map(predictions_dir: Path, results_dir: Path) -> dict:
    """
    把 predictions/ 与 results/ 关联起来：code + date -> strategy + pnl%。

    返回:
        {
            (date, code): {
                "strategy": str,
                "name": str,
                "pnl_pct": float,   # 应用成本模型后的真实 pnl
                "exit_reason": str,
            }
        }
    """
    pnl_map: dict = {}

    for pred_file in list_date_files(predictions_dir):
        date = pred_file.stem
        try:
            pred = read_json(pred_file)
        except Exception as e:
            print(f"[WARN] 无法读取预测文件 {pred_file.name}: {e}", file=sys.stderr)
            continue

        result_file = results_dir / f"{date}.json"
        result_by_code: dict = {}
        if result_file.is_file():
            try:
                res_doc = read_json(result_file)
                for r in res_doc.get("results", []):
                    result_by_code[str(r.get("code"))] = r
            except Exception as e:
                print(f"[WARN] 无法读取结果文件 {result_file.name}: {e}", file=sys.stderr)

        for pick in pred.get("picks", []):
            code = str(pick.get("code"))
            strategy = pick.get("strategy", "unknown")
            name = pick.get("name", "")
            res = result_by_code.get(code)
            if res is None:
                # 尚未验证
                pnl_map[(date, code)] = {
                    "strategy": strategy,
                    "name": name,
                    "pnl_pct": None,
                    "exit_reason": None,
                }
                continue

            entry = res.get("entry_price")
            exit_p = res.get("exit_price")
            if entry and exit_p:
                pnl = apply_cost_model(float(entry), float(exit_p))
            else:
                # 退化：使用结果中已有的 pnl_pct
                pnl = float(res.get("pnl_pct", 0.0))

            pnl_map[(date, code)] = {
                "strategy": strategy,
                "name": name,
                "pnl_pct": pnl,
                "exit_reason": res.get("exit_reason", ""),
            }

    return pnl_map


# ---------------------------------------------------------------------------
# 统计聚合
# ---------------------------------------------------------------------------
def filter_by_window(pnl_map: dict, days: int) -> list:
    """只保留近 N 个交易日（按文件日期排序后取最后 N 天）。"""
    if days <= 0 or not pnl_map:
        return []

    dates = sorted({d for (d, _) in pnl_map.keys()})
    if days < len(dates):
        dates = dates[-days:]
    return [(d, c) for (d, c) in pnl_map.keys() if d in dates]


def calc_streaks(pnls: list) -> int:
    """计算从尾部向前数的最大连续亏损次数。"""
    streak = 0
    for p in reversed(pnls):
        if p is None:
            break
        if p < 0:
            streak += 1
        else:
            break
    return streak


def calc_max_streak(pnls: list) -> int:
    """全序列中的最大连续亏损次数。"""
    max_s = cur = 0
    for p in pnls:
        if p is None:
            continue
        if p < 0:
            cur += 1
            max_s = max(max_s, cur)
        else:
            cur = 0
    return max_s


def aggregate_stats(pnl_map: dict, days: int = 20) -> dict:
    """
    聚合统计：
      - 总数 / 胜 / 负 / 胜率
      - 平均收益 / 累计收益
      - 最大单笔盈 / 最大单笔亏
      - 最大连续亏损
      - 按策略分组
    """
    keys = filter_by_window(pnl_map, days)
    rows = [pnl_map[k] for k in keys]

    # 全部 pnl（含 None），但统计只对非 None 计算
    pnls_all = [r["pnl_pct"] for r in rows]
    pnls = [p for p in pnls_all if p is not None]

    total_picks = len(rows)
    verified = len(pnls)
    wins = sum(1 for p in pnls if p > 0)
    losses = sum(1 for p in pnls if p <= 0)
    win_rate = (wins / verified * 100.0) if verified else 0.0

    avg_pnl = (sum(pnls) / verified) if verified else 0.0
    cum_pnl = sum(pnls)

    max_win = max(pnls) if pnls else 0.0
    max_loss = min(pnls) if pnls else 0.0
    max_streak = calc_max_streak(pnls)

    # 按策略分组
    by_strategy: dict = {}
    for r in rows:
        s = r["strategy"]
        if s not in by_strategy:
            by_strategy[s] = {"count": 0, "pnls": []}
        by_strategy[s]["count"] += 1
        if r["pnl_pct"] is not None:
            by_strategy[s]["pnls"].append(r["pnl_pct"])

    strat_rows = []
    for s, v in by_strategy.items():
        ps = v["pnls"]
        sw = sum(1 for p in ps if p > 0)
        sr = (sw / len(ps) * 100.0) if ps else 0.0
        sa = (sum(ps) / len(ps)) if ps else 0.0
        strat_rows.append({
            "strategy": s,
            "count": v["count"],
            "win_rate": sr,
            "avg_pnl": sa,
        })
    # 按 count 降序
    strat_rows.sort(key=lambda x: x["count"], reverse=True)

    return {
        "days_window": days,
        "total_picks": total_picks,
        "verified": verified,
        "unverified": total_picks - verified,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "avg_pnl": avg_pnl,
        "cum_pnl": cum_pnl,
        "max_win": max_win,
        "max_loss": max_loss,
        "max_loss_streak": max_streak,
        "by_strategy": strat_rows,
    }


# ---------------------------------------------------------------------------
# 格式化输出
# ---------------------------------------------------------------------------
def fmt_pct(p: float) -> str:
    return f"{p:+.2f}%"


def render_markdown(stats: dict) -> str:
    lines = []
    lines.append(f"## 📊 选股胜率报告 (近{stats['days_window']}交易日)")
    lines.append(f"- 总预测: {stats['total_picks']} 次"
                 + (f" (已验证: {stats['verified']})" if stats['unverified'] else ""))
    lines.append(f"- 胜: {stats['wins']} | 负: {stats['losses']}"
                 f" | 胜率: {stats['win_rate']:.1f}%")
    lines.append(f"- 平均收益: {fmt_pct(stats['avg_pnl'])}")
    lines.append(f"- 累计收益: {fmt_pct(stats['cum_pnl'])}")
    lines.append(f"- 最大单笔盈利: {fmt_pct(stats['max_win'])}")
    lines.append(f"- 最大单笔亏损: {fmt_pct(stats['max_loss'])}")
    lines.append(f"- 最大连续亏损: {stats['max_loss_streak']} 次")

    if stats["by_strategy"]:
        lines.append("")
        lines.append("### 按策略分组")
        lines.append("| 策略 | 次数 | 胜率 | 平均收益 |")
        lines.append("|------|------|------|---------|")
        for s in stats["by_strategy"]:
            lines.append(
                f"| {s['strategy']} | {s['count']} | {s['win_rate']:.0f}% | "
                f"{fmt_pct(s['avg_pnl'])} |"
            )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI 子命令
# ---------------------------------------------------------------------------
def cmd_save(args: argparse.Namespace) -> int:
    """保存某天的选股预测到 predictions/YYYY-MM-DD.json"""
    ensure_dirs()
    data = load_picks_arg(args.picks)

    date = args.date
    # 兼容两种入参：
    #   1) {"date":"...", "market_context":"...", "picks":[...]}
    #   2) {"picks":[...]}  ← 此时 date 用 --date 补齐
    if "picks" not in data:
        raise ValueError("picks JSON 必须包含 'picks' 字段")

    if "date" not in data or not data["date"]:
        data["date"] = date
    if "created_at" not in data:
        data["created_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    out_path = PRED_DIR / f"{date}.json"
    write_json(out_path, data)
    print(f"✅ 已保存预测: {out_path}  ({len(data.get('picks', []))} 条)")
    if args.json:
        print(json.dumps({"saved": str(out_path), "count": len(data.get("picks", []))},
                         ensure_ascii=False))
    return 0


def cmd_result(args: argparse.Namespace) -> int:
    """
    单日验证结果录入。

    两种用法：
      a) 提供 --picks: 视为完整 results doc 写入 results/YYYY-MM-DD.json
      b) 不提供 --picks: 进入交互式录入（stdin 读取 JSON 字符串）
    """
    ensure_dirs()
    date = args.date
    out_path = RESULT_DIR / f"{date}.json"

    if args.picks:
        data = load_picks_arg(args.picks)
        if "results" not in data:
            raise ValueError("results JSON 必须包含 'results' 字段")
        if "date" not in data or not data["date"]:
            data["date"] = date
        if "verified_at" not in data:
            data["verified_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        write_json(out_path, data)
        print(f"✅ 已保存结果: {out_path}  ({len(data.get('results', []))} 条)")
        if args.json:
            print(json.dumps({"saved": str(out_path), "count": len(data["results"])},
                             ensure_ascii=False))
        return 0

    # 交互模式
    print(f"=== 录入 {date} 验证结果 ===")
    print("请输入 results JSON (含 'results' 数组)，Ctrl-D 结束：")
    try:
        raw = sys.stdin.read()
    except KeyboardInterrupt:
        print("\n[取消]", file=sys.stderr)
        return 130
    if not raw.strip():
        print("[错误] 未输入任何内容", file=sys.stderr)
        return 1
    data = json.loads(raw)
    if "results" not in data:
        raise ValueError("results JSON 必须包含 'results' 字段")
    data["date"] = date
    data["verified_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    write_json(out_path, data)
    print(f"✅ 已保存结果: {out_path}  ({len(data['results'])} 条)")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    """聚合统计报告。"""
    ensure_dirs()
    pnl_map = build_pnl_map(PRED_DIR, RESULT_DIR)
    if not pnl_map:
        if args.json:
            print(json.dumps({"warning": "no predictions found",
                              "predictions_dir": str(PRED_DIR)}, ensure_ascii=False))
        else:
            print("⚠️  predictions/ 下没有任何 YYYY-MM-DD.json 文件")
        return 0

    stats = aggregate_stats(pnl_map, days=args.days)

    if args.json:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(stats))
    return 0


# ---------------------------------------------------------------------------
# argparse
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tracker.py",
        description="A股选股预测落库 + 统计工具（纯标准库）",
    )
    sub = p.add_subparsers(dest="command", required=True)

    p_save = sub.add_parser("save", help="保存某天选股预测")
    p_save.add_argument("--date", required=True, help="交易日 YYYY-MM-DD")
    p_save.add_argument("--picks", required=True,
                        help="picks JSON 字符串 或 @file.json")
    p_save.add_argument("--json", action="store_true", help="输出 JSON 摘要")
    p_save.set_defaults(func=cmd_save)

    p_stats = sub.add_parser("stats", help="统计报告")
    p_stats.add_argument("--days", type=int, default=20, help="近 N 日（默认 20）")
    p_stats.add_argument("--json", action="store_true", help="输出原始 JSON")
    p_stats.set_defaults(func=cmd_stats)

    p_res = sub.add_parser("result", help="录入某天验证结果")
    p_res.add_argument("--date", required=True, help="交易日 YYYY-MM-DD")
    p_res.add_argument("--picks", required=False, default=None,
                       help="results JSON 字符串 或 @file.json（缺省进入交互）")
    p_res.add_argument("--json", action="store_true", help="输出 JSON 摘要")
    p_res.set_defaults(func=cmd_result)

    return p


def main(argv: list = None) -> int:
    # 强制 UTF-8 输出（兼容 Windows / 部分 IDE）
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as e:
        print(f"[错误] {e}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as e:
        print(f"[错误] JSON 解析失败: {e}", file=sys.stderr)
        return 3
    except ValueError as e:
        print(f"[错误] {e}", file=sys.stderr)
        return 4
    except Exception as e:  # pragma: no cover
        print(f"[异常] {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())