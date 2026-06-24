#!/usr/bin/env python3
"""A股投资分析 — 总编排器

整合 情报采集(Module1) → 盘面分析(Module2) → 个股精选(Module3) 全流程。
非交易时段数据为空时优雅降级，不报错。
"""
import json
import sys
import os
import traceback
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from plugins.news_collector import collect_sync
from engines.module2_market import run_module2
from engines.module3_stocks import run_module3


def run_full_pipeline() -> dict:
    """执行完整三模块流水线，返回整合 dict"""
    today = datetime.now().strftime('%Y-%m-%d')
    report = {
        'date': today,
        'generated_at': datetime.now().isoformat(),
        'module1_news': {},
        'module2_market': {},
        'module3_stocks': {},
        'errors': [],
    }

    # ── 模块一：情报采集 ──
    try:
        news_items = collect_sync()
        report['module1_news'] = {
            'total': len(news_items),
            'sources': {},
            'top_items': [_news_to_dict(n) for n in news_items[:30]],
        }
        # 统计各来源
        src_counts: dict = {}
        for n in news_items:
            src_counts[n.source] = src_counts.get(n.source, 0) + 1
        report['module1_news']['sources'] = src_counts
    except Exception as e:
        err_msg = f'模块一(情报采集)失败: {e}'
        report['errors'].append(err_msg)
        report['module1_news'] = {'error': str(e), 'total': 0}

    # ── 模块二：盘面分析 ──
    try:
        report['module2_market'] = run_module2()
    except Exception as e:
        err_msg = f'模块二(盘面分析)失败: {e}'
        report['errors'].append(err_msg)
        report['module2_market'] = {'error': str(e)}

    # ── 模块三：个股精选 ──
    try:
        report['module3_stocks'] = run_module3()
    except Exception as e:
        err_msg = f'模块三(个股精选)失败: {e}'
        report['errors'].append(err_msg)
        report['module3_stocks'] = {'error': str(e)}

    return report


def _news_to_dict(news_item) -> dict:
    """将 NewsItem dataclass 转为普通 dict，处理 datatime 序列化"""
    try:
        d = asdict(news_item)
    except Exception:
        d = {}
        for f in ('source', 'title', 'content', 'url', 'timestamp', 'tags', 'hot_score'):
            d[f] = getattr(news_item, f, '')
    # 确保 timestamp 可序列化
    if d.get('timestamp'):
        d['timestamp'] = d['timestamp'].isoformat() if hasattr(d['timestamp'], 'isoformat') else str(d['timestamp'])
    return d


if __name__ == '__main__':
    print("🐉 A股投资分析引擎 — 总编排器启动")
    print(f"   时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 60)

    result = run_full_pipeline()

    errors = result.get('errors', [])
    if errors:
        print(f"\n⚠️  {len(errors)} 个模块出现异常:")
        for e in errors:
            print(f"   - {e}")

    print(f"\n📡 模块一(情报): {result['module1_news'].get('total', 0)} 条")
    m2 = result['module2_market']
    print(f"📊 模块二(盘面): {'✅' if 'error' not in m2 else '⚠️'} {m2.get('summary', m2.get('error', ''))}")
    m3 = result['module3_stocks']
    print(f"🎯 模块三(个股): {'✅' if 'error' not in m3 else '⚠️'} 分析 {m3.get('total_analyzed', 0)} 只")

    print("-" * 60)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
