#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股历史数据回填脚本

对最近 20 个交易日:
1. 获取每日涨停池 (akshare stock_zt_pool_em)
2. 选取 TOP 5 (连板数降序, 成交额降序)
3. 生成 predictions/D.json
4. 获取 D+1 K 线 (Tencent) 验证结果 → results/D.json
"""
import os
import sys
import json
import time
from datetime import datetime
from pathlib import Path

import requests
import akshare as ak

# ============== 路径 ==============
PROJECT_ROOT = Path(__file__).parent.resolve()
PRED_DIR = PROJECT_ROOT / "predictions"
RES_DIR = PROJECT_ROOT / "results"
PRED_DIR.mkdir(exist_ok=True)
RES_DIR.mkdir(exist_ok=True)

# ============== 成本模型 ==============
BUY_FEE = 1.00035   # 买入: 印花税 + 佣金
SELL_FEE = 0.99915  # 卖出: 印花税 + 佣金
TARGET_PCT = 5.0
STOP_LOSS_PCT = -3.0
HOLD_DAYS = 1
TOP_N = 5
N_TRADING_DAYS = 20
N_TRADING_DAYS_BUFFER = 25  # 取最近25个, 用后20个

# ============== HTTP ==============
TIMEOUT = 10
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0 Safari/537.36",
    "Referer": "https://gu.qq.com/",
}


def http_get_json(url, retries=3, sleep=0.5):
    """带重试的 GET, 返回 JSON dict."""
    last_err = None
    for i in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            time.sleep(sleep * (i + 1))
    raise last_err


def get_trading_days_via_tencent(n=30):
    """用腾讯接口取上证指数最近 n 个交易日."""
    url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh000001,day,,,%d,qfq" % (n * 2)
    data = http_get_json(url)
    klines = data.get("data", {}).get("sh000001", {}).get("day", [])
    dates = [k[0] for k in klines if k and k[0]]
    return dates


def get_zt_pool(date_yyyymmdd):
    """获取某日涨停池. 返回 DataFrame 或 None."""
    try:
        df = ak.stock_zt_pool_em(date=date_yyyymmdd)
        if df is None or len(df) == 0:
            return None
        return df
    except Exception as e:
        print(f"  [WARN] stock_zt_pool_em({date_yyyymmdd}) failed: {e}", file=sys.stderr)
        return None


def pick_top_n(df, n=5):
    """从涨停池 DataFrame 中选 TOP N: 连板数 desc, 成交额 desc."""
    if df is None or len(df) == 0:
        return []

    # 需要的列
    needed = ["代码", "名称", "连板数", "成交额", "涨停统计"]
    for c in needed:
        if c not in df.columns:
            print(f"  [WARN] missing column {c}", file=sys.stderr)
            return []

    # 规范化: 连板数 → int, 成交额 → float (单位: 元)
    work = df[needed].copy()
    work["连板数"] = pd.to_numeric(work["连板数"], errors="coerce").fillna(0).astype(int)
    work["成交额"] = pd.to_numeric(work["成交额"], errors="coerce").fillna(0.0)

    # 排序
    work = work.sort_values(by=["连板数", "成交额"], ascending=[False, False]).head(n)
    return work.to_dict("records")


def get_kline_tencent(code, days=10):
    """腾讯日 K 线 (前复权)."""
    if not code:
        return []
    market = "sh" if str(code).startswith("6") else "sz"
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={market}{code},day,,,{days},qfq"
    try:
        data = http_get_json(url)
        key = f"{market}{code}"
        klines = (
            data.get("data", {}).get(key, {}).get("day", [])
            or data.get("data", {}).get(key, {}).get("qfqday", [])
            or []
        )
        result = []
        for k in klines:
            if not k or len(k) < 6:
                continue
            try:
                result.append({
                    "date": k[0],
                    "open": float(k[1]),
                    "close": float(k[2]),
                    "high": float(k[3]),
                    "low": float(k[4]),
                    "volume": float(k[5]),
                })
            except (ValueError, TypeError):
                continue
        return result
    except Exception as e:
        print(f"  [WARN] kline {code} failed: {e}", file=sys.stderr)
        return []


def verify_pick(code, name, D_date, D1_date):
    """根据 D+1 日 K 线验证结果.

    返回 dict (result 元素) 或 None (无数据).
    """
    # Tencent K-line 默认从 today 往前推, 旧日期需要更大窗口
    klines = get_kline_tencent(code, days=60)
    if not klines:
        return None

    # 找到 D+1 日的 K 线
    k_d1 = next((k for k in klines if k["date"] == D1_date), None)
    if not k_d1:
        return None

    entry_price = k_d1["open"]
    if entry_price <= 0:
        return None

    target_price = entry_price * (1 + TARGET_PCT / 100.0)
    stop_loss_price = entry_price * (1 + STOP_LOSS_PCT / 100.0)

    actual_high = k_d1["high"]
    actual_low = k_d1["low"]
    actual_close = k_d1["close"]

    # 优先级: 止损 > 止盈 (保守优先) — 实际同一天内如两者都触达,
    # 我们按先止损后止盈, 这是常见回测保守口径
    if actual_low <= stop_loss_price:
        exit_reason = "stop_loss"
        exit_price = stop_loss_price
    elif actual_high >= target_price:
        exit_reason = "target_hit"
        exit_price = target_price
    else:
        exit_reason = "hold_close"
        exit_price = actual_close

    # 含成本
    buy_cost = entry_price * BUY_FEE
    sell_revenue = exit_price * SELL_FEE
    pnl_pct = (sell_revenue - buy_cost) / buy_cost * 100

    return {
        "code": code,
        "name": name,
        "entry_price": round(entry_price, 4),
        "exit_reason": exit_reason,
        "exit_price": round(exit_price, 4),
        "pnl_pct": round(pnl_pct, 4),
        "actual_high": actual_high,
        "actual_low": actual_low,
        "actual_close": actual_close,
        "hold_days": HOLD_DAYS,
        "logic": f"回填: D日龙头",
    }


def next_trading_day(trading_days, D_date):
    """返回 D 的下一个交易日 (在 trading_days 列表中)."""
    try:
        idx = trading_days.index(D_date)
    except ValueError:
        return None
    if idx + 1 >= len(trading_days):
        return None
    return trading_days[idx + 1]


# pandas 懒加载 (脚本顶层)
import pandas as pd


# ============== 主流程 ==============
def main():
    print(f"[{datetime.now().isoformat(timespec='seconds')}] A股回填启动")
    print(f"  PROJECT_ROOT = {PROJECT_ROOT}")
    print(f"  PRED_DIR     = {PRED_DIR}")
    print(f"  RES_DIR      = {RES_DIR}")

    # 1) 取交易日
    print("\n[1/3] 获取最近交易日 (Tencent)...")
    trading_days_all = get_trading_days_via_tencent(N_TRADING_DAYS_BUFFER)
    print(f"  腾讯返回 {len(trading_days_all)} 个交易日")
    if len(trading_days_all) < N_TRADING_DAYS:
        print(f"  [WARN] 交易日数不足 {N_TRADING_DAYS}, 实际 {len(trading_days_all)}")

    # 取最后 N_TRADING_DAYS 个
    trading_days = trading_days_all[-N_TRADING_DAYS:]
    print(f"  本次回填: {trading_days[0]} ~ {trading_days[-1]} (共 {len(trading_days)} 个)")

    # 2) 逐日处理
    print("\n[2/3] 逐日回填...")
    summary = {
        "dates_processed": 0,
        "dates_skipped": 0,
        "predictions": 0,
        "results": 0,
        "result_items": 0,
        "wins": 0,
        "losses": 0,
        "breakeven": 0,
        "pnl_list": [],
    }

    for D in trading_days:
        D_yyyymmdd = D.replace("-", "")
        print(f"\n--- D = {D} ---")

        # a) 涨停池
        df = get_zt_pool(D_yyyymmdd)
        if df is None:
            print(f"  [SKIP] 涨停池为空 (非交易日?): {D}")
            summary["dates_skipped"] += 1
            continue

        picks = pick_top_n(df, TOP_N)
        if not picks:
            print(f"  [SKIP] 未选出 TOP {TOP_N}: {D}")
            summary["dates_skipped"] += 1
            continue

        # b) D+1
        D1 = next_trading_day(trading_days_all, D)
        if D1 is None:
            print(f"  [WARN] D 没有 D+1 (已经是最近一天): {D}")

        # c) 写 prediction
        pred_obj = {
            "date": D,
            "market_context": "回填校准 - 涨停龙头策略",
            "created_at": f"{D}T09:30:00",
            "picks": [],
        }
        for p in picks:
            try:
                n_board = int(p.get("连板数", 0))
            except (ValueError, TypeError):
                n_board = 0
            pred_obj["picks"].append({
                "code": str(p["代码"]),
                "name": str(p["名称"]),
                "action": "buy",
                "strategy": "limit_up_continuation",
                "entry": "open",
                "target_pct": TARGET_PCT,
                "stop_loss_pct": STOP_LOSS_PCT,
                "hold_days": HOLD_DAYS,
                "logic": f"回填: {D}日{n_board}板龙头",
            })

        pred_file = PRED_DIR / f"{D}.json"
        pred_file.write_text(json.dumps(pred_obj, ensure_ascii=False, indent=2))
        summary["predictions"] += 1
        summary["dates_processed"] += 1
        print(f"  [PRED] {pred_file.name} (picks={len(pred_obj['picks'])})")

        # d) 验证 (如果有 D+1)
        if D1 is None:
            print(f"  [NO-RESULT] 无 D+1 数据")
            continue

        results = []
        for p in picks:
            r = verify_pick(str(p["代码"]), str(p["名称"]), D, D1)
            if r is None:
                print(f"  [SKIP-PICK] {p['代码']} {p['名称']}: 缺 D+1={D1} 数据")
                continue
            # 还原连板数描述
            try:
                n_board = int(p.get("连板数", 0))
            except (ValueError, TypeError):
                n_board = 0
            r["logic"] = f"回填: {D}日{n_board}板龙头"
            results.append(r)

        res_obj = {
            "date": D,
            "verified_at": datetime.now().isoformat(timespec="seconds"),
            "results": results,
        }
        res_file = RES_DIR / f"{D}.json"
        res_file.write_text(json.dumps(res_obj, ensure_ascii=False, indent=2))
        summary["results"] += 1
        summary["result_items"] += len(results)
        for r in results:
            pnl = r["pnl_pct"]
            summary["pnl_list"].append(pnl)
            if r["exit_reason"] == "stop_loss":
                summary["losses"] += 1
            elif r["exit_reason"] == "target_hit":
                summary["wins"] += 1
            else:
                summary["breakeven"] += 1
        print(f"  [RES]  {res_file.name} (results={len(results)})")

    # 3) 汇总
    print("\n" + "=" * 60)
    print("[3/3] 汇总")
    print("=" * 60)
    n_days = summary["dates_processed"]
    n_pred = summary["predictions"]
    n_res = summary["results"]
    n_items = summary["result_items"]
    print(f"回填天数 (有预测): {n_days}")
    print(f"跳过天数 (涨停池空): {summary['dates_skipped']}")
    print(f"预测文件数: {n_pred}")
    print(f"结果文件数: {n_res}")
    print(f"验证标的数: {n_items}")

    if n_items > 0:
        wins = summary["wins"]
        losses = summary["losses"]
        breakeven = summary["breakeven"]
        pnls = summary["pnl_list"]
        win_rate = wins / n_items * 100
        avg_pnl = sum(pnls) / len(pnls)
        max_win = max(pnls)
        max_loss = min(pnls)
        print(f"\n--- 交易统计 ---")
        print(f"胜 (target_hit):  {wins}")
        print(f"负 (stop_loss):   {losses}")
        print(f"平 (hold_close):  {breakeven}")
        print(f"胜率:             {win_rate:.2f}%")
        print(f"平均收益:         {avg_pnl:+.3f}%")
        print(f"最大盈利:         {max_win:+.3f}%")
        print(f"最大亏损:         {max_loss:+.3f}%")
    else:
        print("\n[NOTE] 没有验证结果 (D+1 数据不足)")

    print(f"\n[{datetime.now().isoformat(timespec='seconds')}] 全部完成.")


if __name__ == "__main__":
    main()