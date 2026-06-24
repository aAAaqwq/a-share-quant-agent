#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backtester.py — A股选股次日验证引擎

CLI:
  python backtester.py verify --date 2026-06-24 [--no-overwrite]
  python backtester.py verify-all [--no-overwrite]
  python backtester.py show --date 2026-06-24

数据源（自动降级）:
  1. akshare  stock_zh_a_hist        — 偶尔因代理问题失败
  2. 腾讯      web.ifzq.gtimg.cn      — 稳定，无需代理（首选）
  3. 新浪      quotes.sina.cn         — 备用

成本模型:
  买入: 价格 * 1.00035  (滑点 0.01% + 佣金 0.025%)
  卖出: 价格 * 0.99915  (滑点 0.01% + 佣金 0.025% + 印花税 0.05%)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests

# ──────────────────────────────────────────────────────────────────────────────
# 路径与常量
# ──────────────────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent
PRED_DIR = ROOT / "predictions"
RES_DIR = ROOT / "results"

# 成本模型常量
BUY_FACTOR = 1.00035    # 滑点 0.01% + 佣金 0.025%
SELL_FACTOR = 0.99915   # 滑点 0.01% + 佣金 0.025% + 印花税 0.05%

# 数据源超时 / 重试
HTTP_TIMEOUT = 10
RETRY_TIMES = 2
RETRY_BACKOFF = 1.5

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("backtester")


# ──────────────────────────────────────────────────────────────────────────────
# 数据模型
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class KLine:
    date: str       # YYYY-MM-DD
    open: float
    close: float
    high: float
    low: float
    volume: float = 0.0

    def as_dict(self) -> dict:
        return {
            "date": self.date,
            "open": round(self.open, 4),
            "close": round(self.close, 4),
            "high": round(self.high, 4),
            "low": round(self.low, 4),
            "volume": round(self.volume, 2),
        }


@dataclass
class PickResult:
    code: str
    name: str
    entry_price: float
    exit_reason: str       # target_hit / stop_loss / hold_expired / data_missing
    exit_price: float
    pnl_pct: float
    actual_high: float
    actual_low: float
    hold_days: int
    logic: str = ""
    target_price: float = 0.0
    stop_loss_price: float = 0.0
    source: str = ""       # 数据源

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "name": self.name,
            "entry_price": round(self.entry_price, 4),
            "exit_reason": self.exit_reason,
            "exit_price": round(self.exit_price, 4),
            "pnl_pct": round(self.pnl_pct, 4),
            "actual_high": round(self.actual_high, 4),
            "actual_low": round(self.actual_low, 4),
            "hold_days": self.hold_days,
            "logic": self.logic,
            "target_price": round(self.target_price, 4),
            "stop_loss_price": round(self.stop_loss_price, 4),
            "source": self.source,
        }


# ──────────────────────────────────────────────────────────────────────────────
# 数据源: 腾讯（首选）/ 新浪 / akshare
# ──────────────────────────────────────────────────────────────────────────────

def _market_prefix(code: str) -> str:
    """根据股票代码判断市场前缀: sh (6开头), sz (0/3开头), bj (8/4开头)"""
    if code.startswith(("6", "9")):
        return "sh"
    if code.startswith(("0", "3")):
        return "sz"
    if code.startswith(("8", "4", "2")):
        return "bj"
    # 默认 sh
    return "sh"


def _http_get_json(url: str, timeout: int = HTTP_TIMEOUT) -> Optional[dict]:
    """带重试的 HTTP GET，返回 JSON 或 None"""
    last_err = None
    for i in range(RETRY_TIMES):
        try:
            r = requests.get(url, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            log.debug("HTTP try %d/%d failed: %s", i + 1, RETRY_TIMES, e)
            if i < RETRY_TIMES - 1:
                time.sleep(RETRY_BACKOFF * (i + 1))
    log.warning("HTTP failed after %d tries: %s — %s", RETRY_TIMES, url[:80], last_err)
    return None


def fetch_kline_tencent(code: str, days: int = 30) -> list[KLine]:
    """腾讯日K线 — 稳定，无需代理（首选）"""
    market = _market_prefix(code)
    url = (
        f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        f"?param={market}{code},day,,,{days},qfq"
    )
    data = _http_get_json(url)
    if not data:
        return []
    key = f"{market}{code}"
    node = data.get("data", {}).get(key, {})
    klines_raw = node.get("day") or node.get("qfqday") or []
    out: list[KLine] = []
    for k in klines_raw:
        try:
            out.append(KLine(
                date=str(k[0]),
                open=float(k[1]),
                close=float(k[2]),
                high=float(k[3]),
                low=float(k[4]),
                volume=float(k[5]) if len(k) > 5 else 0.0,
            ))
        except (IndexError, ValueError, TypeError) as e:
            log.debug("tencent: skip row %s: %s", k, e)
            continue
    return out


def fetch_kline_sina(code: str, days: int = 30) -> list[KLine]:
    """新浪日K线 — 备用"""
    market = _market_prefix(code)
    url = (
        f"https://quotes.sina.cn/cn/api/jsonp.php/var_/"
        f"CN_MarketDataService.getKLineData"
        f"?symbol={market}{code}&scale=240&ma=no&datalen={days}"
    )
    try:
        r = requests.get(url, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        text = r.text
        # JSONP 包裹: var_xxx([...]) 或 xxx([...])
        start = text.find("[")
        end = text.rfind("]")
        if start < 0 or end < 0:
            log.warning("sina: no json array in response")
            return []
        data = json.loads(text[start:end + 1])
    except Exception as e:
        log.warning("sina: parse failed: %s", e)
        return []
    out: list[KLine] = []
    for row in data:
        try:
            out.append(KLine(
                date=str(row[0]),
                open=float(row[1]),
                close=float(row[2]),
                high=float(row[3]),
                low=float(row[4]),
                volume=float(row[5]) if len(row) > 5 else 0.0,
            ))
        except (IndexError, ValueError, TypeError) as e:
            log.debug("sina: skip row %s: %s", row, e)
            continue
    return out


def fetch_kline_akshare(code: str, days: int = 30) -> list[KLine]:
    """akshare — 偶尔因代理失败，最后降级"""
    try:
        import akshare as ak
    except ImportError:
        return []
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")
    try:
        df = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust="qfq",
        )
    except Exception as e:
        log.debug("akshare: fetch failed: %s", e)
        return []
    if df is None or df.empty:
        return []
    # akshare 列名: 日期/开盘/收盘/最高/最低/成交量 等
    out: list[KLine] = []
    for _, row in df.iterrows():
        try:
            out.append(KLine(
                date=str(row["日期"])[:10],
                open=float(row["开盘"]),
                close=float(row["收盘"]),
                high=float(row["最高"]),
                low=float(row["最低"]),
                volume=float(row.get("成交量", 0) or 0),
            ))
        except Exception as e:
            log.debug("akshare: skip row: %s", e)
            continue
    return out


def fetch_kline(code: str, days: int = 30) -> tuple[list[KLine], str]:
    """自动降级获取 K 线: 腾讯 → 新浪 → akshare"""
    # 1. 腾讯（首选，稳）
    k = fetch_kline_tencent(code, days)
    if k:
        return k, "tencent"
    log.info("tencent failed for %s, fallback to sina", code)
    # 2. 新浪
    k = fetch_kline_sina(code, days)
    if k:
        return k, "sina"
    log.info("sina failed for %s, fallback to akshare", code)
    # 3. akshare
    k = fetch_kline_akshare(code, days)
    if k:
        return k, "akshare"
    return [], "none"


# ──────────────────────────────────────────────────────────────────────────────
# 验证逻辑
# ──────────────────────────────────────────────────────────────────────────────

def _next_trading_day(klines: list[KLine], target_date: str) -> Optional[KLine]:
    """找到 target_date 之后的下一个交易日 K 线"""
    for k in klines:
        if k.date > target_date:
            return k
    return None


def _pnl_with_cost(entry: float, exit_: float) -> float:
    """含交易成本的 pnl %"""
    buy_cost = entry * BUY_FACTOR
    sell_rev = exit_ * SELL_FACTOR
    return (sell_rev - buy_cost) / buy_cost * 100.0


def verify_pick(pick: dict, klines: list[KLine], source: str,
                pick_date: str = "") -> PickResult:
    """对一个 pick 执行验证，返回 PickResult。

    pick_date 来自 predictions/ 顶层 date 字段（pick 本身不含 date）。
    """
    code = str(pick["code"])
    name = str(pick.get("name", ""))
    target_pct = float(pick.get("target_pct", 5.0))
    stop_pct = float(pick.get("stop_loss_pct", -3.0))
    hold_days = int(pick.get("hold_days", 1))
    logic = str(pick.get("logic", ""))

    # 找次日 K 线作为入场日
    entry_day = _next_trading_day(klines, pick_date)
    if not entry_day:
        return PickResult(
            code=code, name=name, entry_price=0.0,
            exit_reason="data_missing", exit_price=0.0,
            pnl_pct=0.0, actual_high=0.0, actual_low=0.0,
            hold_days=0, logic=logic, source=source,
        )

    entry_price = entry_day.open
    target_price = entry_price * (1.0 + target_pct / 100.0)
    stop_loss_price = entry_price * (1.0 + stop_pct / 100.0)

    # 从 entry_day 开始取 hold_days 根 K 线
    idx = next((i for i, k in enumerate(klines) if k.date == entry_day.date), None)
    if idx is None:
        idx = -1
    # 直接切片 hold_days 根
    held = klines[idx: idx + hold_days]
    if not held:
        held = [entry_day]

    actual_high = max(k.high for k in held)
    actual_low = min(k.low for k in held)

    exit_reason = "hold_expired"
    exit_price = held[-1].close

    # 逐日检查（止损优先，止盈次之）
    for k in held:
        # 止损: 当日最低价触及或跌破
        if k.low <= stop_loss_price:
            exit_reason = "stop_loss"
            exit_price = stop_loss_price
            break
        # 止盈: 当日最高价触及或突破
        if k.high >= target_price:
            exit_reason = "target_hit"
            exit_price = target_price
            break

    pnl_pct = _pnl_with_cost(entry_price, exit_price)

    return PickResult(
        code=code, name=name,
        entry_price=entry_price,
        exit_reason=exit_reason,
        exit_price=exit_price,
        pnl_pct=pnl_pct,
        actual_high=actual_high,
        actual_low=actual_low,
        hold_days=len(held),
        logic=logic,
        target_price=target_price,
        stop_loss_price=stop_loss_price,
        source=source,
    )


# ──────────────────────────────────────────────────────────────────────────────
# 文件 I/O
# ──────────────────────────────────────────────────────────────────────────────

def load_predictions(date: str) -> Optional[dict]:
    path = PRED_DIR / f"{date}.json"
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.error("Failed to load predictions %s: %s", path, e)
        return None


def save_results(date: str, payload: dict, overwrite: bool = True) -> Path:
    RES_DIR.mkdir(parents=True, exist_ok=True)
    path = RES_DIR / f"{date}.json"
    if path.exists() and not overwrite:
        log.warning("results %s exists, skip (no-overwrite)", path)
        return path
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def list_unverified_dates() -> list[str]:
    """列出有 predictions 但没有 results 的日期"""
    if not PRED_DIR.exists():
        return []
    dates = sorted(
        p.stem for p in PRED_DIR.glob("*.json") if len(p.stem) == 10
    )
    out = []
    for d in dates:
        r = RES_DIR / f"{d}.json"
        if not r.exists():
            out.append(d)
    return out


# ──────────────────────────────────────────────────────────────────────────────
# 核心命令
# ──────────────────────────────────────────────────────────────────────────────

def cmd_verify(date: str, overwrite: bool = True) -> int:
    pred = load_predictions(date)
    if pred is None:
        log.error("predictions/%s.json not found", date)
        return 1

    picks_all = pred.get("picks", [])
    picks = [p for p in picks_all if str(p.get("action", "")).lower() == "buy"]
    n_skipped = len(picks_all) - len(picks)
    if n_skipped:
        log.info("skipped %d non-buy picks (watch/etc.)", n_skipped)
    if not picks:
        log.warning("no buy picks in %s", date)
        # 仍然写一个空 results（标记已验证）
        save_results(date, {
            "date": date,
            "verified_at": datetime.now().isoformat(timespec="seconds"),
            "results": [],
            "note": "no buy picks",
        }, overwrite=overwrite)
        return 0

    log.info("verifying %d picks for %s", len(picks), date)
    results: list[dict] = []
    for pick in picks:
        code = str(pick["code"])
        klines, source = fetch_kline(code, days=30)
        if not klines:
            log.warning("  ✗ %s: no kline data", code)
            results.append(PickResult(
                code=code, name=str(pick.get("name", "")),
                entry_price=0.0, exit_reason="data_missing", exit_price=0.0,
                pnl_pct=0.0, actual_high=0.0, actual_low=0.0,
                hold_days=0, logic=str(pick.get("logic", "")),
                source="none",
            ).as_dict())
            continue
        pr = verify_pick(pick, klines, source, pick_date=date)
        emoji = "🟢" if pr.pnl_pct > 0 else ("🔴" if pr.pnl_pct < 0 else "⚪")
        log.info(
            "  %s %s %s: entry=%.2f exit=%.2f %s pnl=%.2f%%",
            emoji, code, pr.name,
            pr.entry_price, pr.exit_price, pr.exit_reason, pr.pnl_pct,
        )
        results.append(pr.as_dict())

    payload = {
        "date": date,
        "verified_at": datetime.now().isoformat(timespec="seconds"),
        "results": results,
    }
    out = save_results(date, payload, overwrite=overwrite)
    log.info("✅ saved %s", out.relative_to(ROOT))
    return 0


def cmd_verify_all(overwrite: bool = True) -> int:
    dates = list_unverified_dates()
    if not dates:
        log.info("no unverified predictions found")
        return 0
    log.info("found %d unverified dates: %s", len(dates), ", ".join(dates))
    rc = 0
    for d in dates:
        log.info("=" * 50)
        rc |= cmd_verify(d, overwrite=overwrite)
    return rc


def cmd_show(date: str) -> int:
    path = RES_DIR / f"{date}.json"
    if not path.exists():
        log.error("results/%s.json not found", date)
        return 1
    data = json.loads(path.read_text(encoding="utf-8"))
    results = data.get("results", [])
    print(f"\n📊 验证结果 — {date} (verified_at: {data.get('verified_at', '?')})")
    print(f"共 {len(results)} 条")
    if not results:
        return 0
    print("-" * 92)
    print(f"{'代码':<8}{'名称':<14}{'入场':>9}{'出场':>9}{'原因':<14}{'pnl%':>9}{'止盈':>8}{'止损':>8}")
    print("-" * 92)
    for r in results:
        reason_cn = {
            "target_hit": "🎯止盈",
            "stop_loss": "🛑止损",
            "hold_expired": "⏱持有到期",
            "data_missing": "❌数据缺失",
        }.get(r["exit_reason"], r["exit_reason"])
        print(
            f"{r['code']:<8}{r['name']:<14}"
            f"{r['entry_price']:>9.2f}{r['exit_price']:>9.2f}"
            f"{reason_cn:<14}{r['pnl_pct']:>9.2f}"
            f"{r.get('target_price', 0):>8.2f}{r.get('stop_loss_price', 0):>8.2f}"
        )
    print("-" * 92)
    valid = [r for r in results if r["exit_reason"] != "data_missing"]
    if valid:
        wins = [r for r in valid if r["pnl_pct"] > 0]
        avg = sum(r["pnl_pct"] for r in valid) / len(valid)
        win_rate = len(wins) / len(valid) * 100
        print(f"胜率: {win_rate:.1f}% ({len(wins)}/{len(valid)})   均价: {avg:+.2f}%\n")
    return 0


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(
        description="A股选股次日验证引擎",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("verify", help="验证单个日期的预测")
    p1.add_argument("--date", required=True, help="YYYY-MM-DD")
    p1.add_argument("--no-overwrite", action="store_true",
                    help="已存在 results 时不覆盖")

    p2 = sub.add_parser("verify-all", help="批量验证所有未验证的预测")
    p2.add_argument("--no-overwrite", action="store_true")

    p3 = sub.add_parser("show", help="显示某日验证结果")
    p3.add_argument("--date", required=True, help="YYYY-MM-DD")

    args = p.parse_args()
    PRED_DIR.mkdir(parents=True, exist_ok=True)
    RES_DIR.mkdir(parents=True, exist_ok=True)

    if args.cmd == "verify":
        return cmd_verify(args.date, overwrite=not args.no_overwrite)
    if args.cmd == "verify-all":
        return cmd_verify_all(overwrite=not args.no_overwrite)
    if args.cmd == "show":
        return cmd_show(args.date)
    return 2


if __name__ == "__main__":
    sys.exit(main())