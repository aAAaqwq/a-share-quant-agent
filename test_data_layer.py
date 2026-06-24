#!/usr/bin/env python3
"""data_layer.py 验证脚本

测试各数据获取方法的可用性和返回格式。
交易日运行以获得有意义的输出。
"""

import sys
import os

# 确保可以从项目根目录导入
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from plugins.data_layer import dl, AShareDataLayer


def test_basic():
    """基础数据获取测试"""
    print("=" * 60)
    print("📊 测试1: 大盘快照")
    print("=" * 60)
    snap = dl.get_market_snapshot()
    if 'error' in snap:
        print(f"  ❌ {snap['error']}")
    else:
        for k, v in snap.items():
            print(f"  {k}: {v}")

    print("\n" + "=" * 60)
    print("🔥 测试2: 涨停池")
    print("=" * 60)
    zt = dl.get_limit_up_pool()
    print(f"  涨停数: {len(zt)}")
    if not zt.empty:
        cols = [c for c in ['代码', '名称', '涨跌幅'] if c in zt.columns]
        print(zt[cols].head(5).to_string())

    print("\n" + "=" * 60)
    print("🧱 测试3: 概念板块 TOP5")
    print("=" * 60)
    boards = dl.get_concept_boards()
    if not boards.empty:
        top5 = boards.sort_values('涨跌幅', ascending=False).head(5)
        cols = [c for c in ['板块名称', '涨跌幅', '板块代码'] if c in top5.columns]
        print(top5[cols].to_string())
    else:
        print("  无法获取概念板块数据")


def test_extended():
    """扩展功能测试"""
    print("\n" + "=" * 60)
    print("📈 测试4: 个股历史K线 (000001 平安银行)")
    print("=" * 60)
    hist = dl.get_hist('000001', days=5)
    if not hist.empty:
        cols = [c for c in ['日期', '开盘', '收盘', '涨跌幅'] if c in hist.columns]
        print(hist[cols].tail(3).to_string())
    else:
        print("  无法获取历史数据")

    print("\n" + "=" * 60)
    print("🌍 测试5: 全球指数")
    print("=" * 60)
    indices = dl.get_global_indices()
    if not indices.empty:
        print(f"  指数数量: {len(indices)}")
        cols = [c for c in ['代码', '名称', '最新价', '涨跌幅'] if c in indices.columns]
        if cols:
            print(indices[cols].head(8).to_string())
    else:
        print("  无法获取全球指数")

    print("\n" + "=" * 60)
    print("💰 测试6: 北向资金")
    print("=" * 60)
    north = dl.get_north_flow()
    if not north.empty:
        print(f"  数据条数: {len(north)}")
        print(north.tail(3).to_string())
    else:
        print("  无法获取北向资金数据")

    print("\n" + "=" * 60)
    print("🏦 测试7: 龙虎榜")
    print("=" * 60)
    lhb = dl.get_lhb_detail()
    if not lhb.empty:
        print(f"  上榜个股数: {len(lhb)}")
        cols = [c for c in ['代码', '名称'] if c in lhb.columns]
        if cols:
            print(lhb[cols].head(5).to_string())
    else:
        print("  今日无龙虎榜数据（可能非交易日）")

    print("\n" + "=" * 60)
    print("🚀 测试8: 热门题材分析 (涨幅>9%个股)")
    print("=" * 60)
    themes = dl.analyze_hot_themes(min_pct=9.0)
    if 'error' in themes:
        print(f"  ❌ {themes['error']}")
    elif themes.get('message'):
        print(f"  ℹ️  {themes['message']}")
    else:
        print(f"  热门股数量: {themes['hot_stock_count']}")
        print(f"  前10题材分布:")
        for name, count in themes['themes'][:10]:
            print(f"    - {name}: {count}")


def test_top_boards():
    """板块汇总测试"""
    print("\n" + "=" * 60)
    print("🏗️ 测试9: 涨幅前5概念板块+成分股")
    print("=" * 60)
    top = dl.get_top_n_boards(n=5, board_type='concept')
    for i, board in enumerate(top):
        print(f"\n  #{i+1} {board['name']} ({board['code']}) "
              f"涨{board['change_pct']:.2f}% 成分股{board['stock_count']}只")
        for s in board['stocks'][:5]:
            print(f"      {s['代码']} {s['名称']}")
        if board['stock_count'] > 5:
            print(f"      ... 共{board['stock_count']}只")


def test_error_handling():
    """错误处理测试"""
    print("\n" + "=" * 60)
    print("🛡️ 测试10: 错误处理(无效代码)")
    print("=" * 60)
    result = dl.get_hist('INVALID', days=5)
    if result.empty:
        print("  ✅ 正确返回空DataFrame（不抛异常）")
    else:
        print(f"  ⚠️ 意外返回了 {len(result)} 条数据")

    result2 = dl.get_board_stocks('INVALID_CODE')
    if result2.empty:
        print("  ✅ 无效板块代码正确返回空DataFrame")


def test_retry_mechanism():
    """重试机制测试"""
    print("\n" + "=" * 60)
    print("🔄 测试11: 重试机制")
    print("=" * 60)
    tester = AShareDataLayer(retry=3, delay=0.1)
    # 调用一个正常函数验证不会误触发重试
    spot = tester.get_spot()
    print(f"  正常调用: {'✅ 成功' if not spot.empty else '❌ 失败'}")


def main():
    print("\n🧪 A股数据访问层 验证测试")
    print(f"   时间: {__import__('datetime').datetime.now()}")
    print(f"   数据层重试配置: retry={dl.retry}, delay={dl.delay}s")
    print()

    test_basic()
    test_extended()
    test_top_boards()
    test_error_handling()
    test_retry_mechanism()

    print("\n" + "=" * 60)
    print("✅ 全部测试完成")
    print("=" * 60)


if __name__ == '__main__':
    main()
