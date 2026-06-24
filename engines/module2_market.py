"""
模块二：盘面分析引擎
──────────────────────────
包含3个子分析器：
1. 美股映射分析  → analyze_us_mapping()
2. 大盘综合指标  → get_market_report()
3. 实时主线分析  → analyze_main_themes()

主入口：run_module2() → 整合输出统一字典
"""

import json
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from plugins.data_layer import dl
import pandas as pd


# ── 工具函数 ────────────────────────────────────────────

def _load_json(path: str) -> dict:
    """加载JSON配置文件"""
    full = os.path.join(_PROJECT_ROOT, path) if not os.path.isabs(path) else path
    try:
        with open(full, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _round_pct(val) -> Optional[float]:
    """安全地将数值四舍五入到2位小数"""
    try:
        return round(float(val), 2)
    except (TypeError, ValueError):
        return None


# ── 1. 美股映射分析器 ──────────────────────────────────

def analyze_us_mapping() -> List[Dict]:
    """美股映射分析

    获取美股指数/龙头表现，映射A股板块，输出信号。

    规则:
        - 美股板块前一日涨跌幅 > 2%   → 强映射利好
        - 美股板块前一日涨跌幅 > 0.5%  → 弱映射利好
        - 美股板块前一日涨跌幅 < -2%   → 强映射利空
        - 其他                         → 无信号

    Returns:
        [
            {
                "us_sector": "SOX",
                "us_name": "费城半导体",
                "us_pct": 3.2,
                "cn_sectors": ["半导体", "芯片"],
                "signal": "强利好"
            },
            ...
        ]
    """
    mapping = _load_json('config/us_mapping.json')
    if not mapping:
        return [{"error": "无法加载 us_mapping.json"}]

    # 构建 tracking ticker → config entry 的映射
    # 同时分离 ETF/指数 ticker (以.开头) vs 个股
    tracking_map: Dict[str, dict] = {}
    for key, val in mapping.items():
        t = val.get('tracking', '').strip()
        if t:
            tracking_map[t.upper()] = {
                'us_sector': key,
                'cn_sectors': val.get('cn_sectors', []),
            }

    # ── 获取全球指数 ──
    global_idx = dl.get_global_indices()
    global_lookup: Dict[str, Dict] = {}
    if not global_idx.empty:
        for _, row in global_idx.iterrows():
            name = str(row.get('名称', '')).strip()
            pct = _round_pct(row.get('涨跌幅', 0))
            price = _round_pct(row.get('最新价', 0))
            global_lookup[name] = {'pct': pct, 'price': price}

    # ── 获取美股知名个股 ──
    us_stocks: Dict[str, dict] = {}
    try:
        import akshare as ak
        us_spot = dl._call_with_retry(ak.stock_us_famous_spot_em)
        if not us_spot.empty:
            for _, row in us_spot.iterrows():
                code = str(row.get('代码', '')).strip().upper()
                pct = _round_pct(row.get('涨跌幅', 0))
                name = str(row.get('名称', ''))
                us_stocks[code] = {'pct': pct, 'name': name, 'price': _round_pct(row.get('最新价', 0))}
    except Exception:
        pass

    # ── 尝试获取美股指数（新浪源） ──
    try:
        import akshare as ak
        us_idx = dl._call_with_retry(ak.index_us_stock_sina)
        if not us_idx.empty:
            for _, row in us_idx.iterrows():
                code = str(row.get('代码', '')).strip().upper().lstrip('.')
                name = str(row.get('名称', '')).strip()
                pct = _round_pct(row.get('涨跌幅', 0))
                price = _round_pct(row.get('最新价', 0))
                us_stocks[code] = {'pct': pct, 'name': name, 'price': price}
    except Exception:
        pass

    # ── 合并数据源：优先 us_stocks，回退 global_lookup ──
    all_data: Dict[str, dict] = {}
    # 先把 global_lookup 填进去（按名称模糊匹配）
    index_name_map = {
        '道琼斯': 'DJI', '纳斯达克': 'IXIC', '标普500': 'SPX',
        '费城半导体': 'SOX', '费城半导体指数': 'SOX',
        '英国富时': 'FTSE', '法国CAC': 'CAC', '德国DAX': 'DAX',
        '日经225': 'N225', '恒生指数': 'HSI',
    }
    for name, data in global_lookup.items():
        for keyword, ticker in index_name_map.items():
            if keyword in name:
                all_data[ticker] = {
                    'pct': data['pct'], 'price': data['price'], 'name': name
                }

    # 美股个股数据直接合并
    for code, data in us_stocks.items():
        all_data[code] = data

    # ── 组装结果 ──
    results: List[Dict] = []
    for tracking, config in tracking_map.items():
        data = all_data.get(tracking)
        if data is None:
            # 尝试部分匹配
            for k, v in all_data.items():
                if tracking in k or k in tracking:
                    data = v
                    break

        if data is None or data.get('pct') is None:
            results.append({
                'us_sector': config['us_sector'],
                'cn_sectors': config['cn_sectors'],
                'us_pct': None,
                'signal': '无数据',
            })
            continue

        pct = data['pct']
        if pct > 2:
            signal = '强利好'
        elif pct > 0.5:
            signal = '弱利好'
        elif pct < -2:
            signal = '强利空'
        elif pct < -0.5:
            signal = '弱利空'
        else:
            signal = '中性'

        results.append({
            'us_sector': config['us_sector'],
            'us_name': data.get('name', tracking),
            'us_pct': pct,
            'cn_sectors': config['cn_sectors'],
            'signal': signal,
        })

    return results


# ── 2. 大盘综合指标 ────────────────────────────────────

def get_market_report() -> Dict:
    """大盘综合报告

    补充量能同比（与前5日平均成交额对比）和涨停集中度。

    Returns:
        {
            '涨家数', '跌家数', '平家数', '涨跌比',
            '成交额(亿)', '涨停数', '跌停数',
            '市场风格', '情绪', '量能判断',
            '量能同比': str,          # 新增
            '涨停集中度': [...],      # 新增
            '时间',
        }
    """
    snapshot = dl.get_market_snapshot()
    if 'error' in snapshot:
        return snapshot

    # ── 量能同比：与前5日平均成交额对比 ──
    try:
        import akshare as ak
        end = datetime.now().strftime('%Y%m%d')
        start = (datetime.now() - timedelta(days=30)).strftime('%Y%m%d')
        sh_idx = dl._call_with_retry(
            ak.stock_zh_index_daily_em, symbol="sh000001"
        )
        vol_comparison = "无历史数据"
        if not sh_idx.empty and 'amount' in sh_idx.columns:
            sh_idx_sorted = sh_idx.sort_values('date', ascending=False)
            recent = sh_idx_sorted.head(6)  # 今天+N日前5天
            if len(recent) >= 6:
                today_amt = float(recent.iloc[0]['amount'])
                avg_5d = float(recent.iloc[1:6]['amount'].mean())
                if avg_5d > 0:
                    ratio = (today_amt / avg_5d - 1) * 100
                    if ratio > 30:
                        vol_comparison = f"放量{ratio:.0f}%（较5日均值）"
                    elif ratio > 10:
                        vol_comparison = f"温和放量{ratio:.0f}%"
                    elif ratio > -10:
                        vol_comparison = f"平量{ratio:+.0f}%"
                    elif ratio > -30:
                        vol_comparison = f"缩量{ratio:+.0f}%"
                    else:
                        vol_comparison = f"大幅缩量{ratio:.0f}%"
    except Exception:
        vol_comparison = "获取失败"

    # ── 涨停集中度 ──
    concentration: List[Dict] = []
    try:
        zt_pool = dl.get_limit_up_pool()
        if not zt_pool.empty:
            zt_codes = set(zt_pool['代码'].values)
            concepts_df = dl.get_concept_boards()
            if not concepts_df.empty:
                top_concepts = concepts_df.sort_values('涨跌幅', ascending=False).head(50)
                board_counts: List[tuple] = []
                for _, board in top_concepts.iterrows():
                    board_code = board.get('板块代码', '')
                    board_name = board.get('板块名称', '')
                    if not board_code:
                        continue
                    try:
                        stocks = dl.get_board_stocks(board_code)
                        if stocks.empty:
                            continue
                        board_codes = set(stocks['代码'].values)
                        zt_in_board = zt_codes & board_codes
                        if zt_in_board:
                            board_counts.append((board_name, len(zt_in_board)))
                    except Exception:
                        pass
                board_counts.sort(key=lambda x: x[1], reverse=True)
                concentration = [
                    {'板块': name, '涨停数': cnt}
                    for name, cnt in board_counts[:5]
                ]
    except Exception:
        pass

    snapshot['量能同比'] = vol_comparison
    snapshot['涨停集中度'] = concentration
    return snapshot


# ── 3. 实时主线分析 ──────────────────────────────────────

def analyze_main_themes(min_pct: float = 9.0) -> Dict:
    """实时主线分析

    对涨幅>min_pct%的个股题材分布进行分析，增强：
    - 匹配 sector_keywords 识别题材驱动事件
    - 主线持续性判断（需历史缓存）
    - 涨停数 > 10 标记为"强主线"

    Args:
        min_pct: 涨幅阈值，默认9.0%

    Returns:
        {
            'main_themes': [
                {
                    'theme': str,
                    'hot_count': int,
                    'signal': '强主线' | '主线' | '弱主线',
                    'persistence': str,   # 持续性描述
                    'matched_events': [...],  # 匹配的新闻事件关键词
                },
                ...
            ],
            'hot_stock_count': int,
            'total_limit_up': int,
            'market_sentiment': str,
            'analysis_time': str,
        }
    """
    raw = dl.analyze_hot_themes(min_pct=min_pct)
    if 'error' in raw:
        return raw

    # 加载板块关键词
    sector_kw = _load_json('config/sector_keywords.json')
    # 加载历史主线缓存
    history = _load_theme_history()

    themes = raw.get('themes', [])
    hot_stock_count = raw.get('hot_stock_count', 0)
    total_zt = 0
    try:
        zt_pool = dl.get_limit_up_pool()
        total_zt = len(zt_pool) if not zt_pool.empty else 0
    except Exception:
        pass

    # ── 市场情绪 ──
    if total_zt >= 80:
        sentiment = "🔥 情绪高涨 — 适合接力"
    elif total_zt >= 50:
        sentiment = "😊 情绪良好"
    elif total_zt >= 30:
        sentiment = "😐 情绪一般 — 首板为主"
    elif total_zt >= 15:
        sentiment = "😟 情绪偏弱 — 低吸策略"
    else:
        sentiment = "❄️ 情绪冰点 — 观望为主"

    # ── 处理每个主线题材 ──
    main_themes: List[Dict] = []
    for theme_name, hot_count in themes:
        entry: Dict = {
            'theme': theme_name,
            'hot_count': hot_count,
            'signal': '主线',
            'persistence': '首次出现',
            'matched_events': [],
        }

        # 信号等级
        if hot_count >= 10:
            entry['signal'] = '强主线'
        elif hot_count >= 5:
            entry['signal'] = '主线'
        else:
            entry['signal'] = '弱主线'

        # 匹配板块关键词 — 识别可能驱动事件
        entry['matched_events'] = _match_theme_events(theme_name, sector_kw)

        # 持续性判断
        entry['persistence'] = _check_persistence(theme_name, history)

        main_themes.append(entry)

    # ── 更新历史缓存 ──
    _save_theme_history(themes)

    return {
        'main_themes': main_themes,
        'hot_stock_count': hot_stock_count,
        'total_limit_up': total_zt,
        'market_sentiment': sentiment,
        'analysis_time': datetime.now().strftime('%Y-%m-%d %H:%M'),
    }


def _match_theme_events(theme_name: str, sector_kw: dict) -> List[str]:
    """将主题名称匹配到 sector_keywords 中的事件关键词"""
    matched = []
    theme_lower = theme_name.lower()
    for sector, info in sector_kw.items():
        if not isinstance(info, dict):
            continue
        keywords = info.get('keywords', [])
        # 直接匹配：主题名本身是否与sector名匹配
        if sector in theme_name or theme_name in sector:
            # 取前3个最相关关键词作为"驱动事件"
            matched.extend(keywords[:3])
        # 关键词匹配
        for kw in keywords:
            if kw.lower() in theme_lower:
                if kw not in matched:
                    matched.append(kw)
    return matched[:5]  # 最多返回5个


def _get_theme_cache_path() -> str:
    return os.path.join(_PROJECT_ROOT, 'cache', 'theme_history.json')


def _load_theme_history() -> Dict[str, list]:
    """加载历史主线缓存

    Returns:
        {'YYYY-MM-DD': ['半导体', 'AI', ...], ...}
    """
    p = _get_theme_cache_path()
    try:
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _save_theme_history(themes: list):
    """保存今日主线到缓存"""
    p = _get_theme_cache_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    history = _load_theme_history()
    today = datetime.now().strftime('%Y-%m-%d')
    theme_names = [t[0] if isinstance(t, (tuple, list)) else t for t in themes]
    history[today] = theme_names
    # 只保留最近30天
    keys = sorted(history.keys(), reverse=True)[:30]
    history = {k: history[k] for k in keys}
    try:
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _check_persistence(theme_name: str, history: Dict[str, list]) -> str:
    """检查主线持续性"""
    if not history:
        return '首次出现'
    today = datetime.now()
    consecutive = 0
    for i in range(7):
        d = (today - timedelta(days=i)).strftime('%Y-%m-%d')
        if d in history and theme_name in history[d]:
            consecutive += 1
        else:
            break
    if consecutive >= 5:
        return f'连续{consecutive}天主线'
    elif consecutive >= 3:
        return f'连续{consecutive}天'
    elif consecutive >= 2:
        return f'连续{consecutive}天'
    else:
        return '今日新晋'


# ── 4. 主函数 ──────────────────────────────────────────

def run_module2(
    us_mapping: bool = True,
    market_report: bool = True,
    main_themes: bool = True,
    min_pct: float = 9.0,
) -> Dict:
    """模块二主入口：依次调用3个子分析器，整合输出

    Args:
        us_mapping: 是否执行美股映射分析
        market_report: 是否执行大盘综合报告
        main_themes: 是否执行实时主线分析
        min_pct: 主线分析涨幅阈值

    Returns:
        {
            'module': 'module2_market',
            'timestamp': str,
            'us_mapping': [...],
            'market_report': {...},
            'main_themes': {...},
            'summary': str,  # 一句话总结
        }
    """
    result = {
        'module': 'module2_market',
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }

    # 1. 美股映射
    if us_mapping:
        result['us_mapping'] = analyze_us_mapping()

    # 2. 大盘综合报告
    if market_report:
        result['market_report'] = get_market_report()

    # 3. 实时主线
    if main_themes:
        result['main_themes'] = analyze_main_themes(min_pct=min_pct)

    # ── 生成一句话总结 ──
    summary_parts = []

    # 从大盘快照取风格和情绪
    mr = result.get('market_report', {})
    if mr and 'error' not in mr:
        style = mr.get('市场风格', '')
        vol = mr.get('量能判断', '')
        zt = mr.get('涨停数', 0)
        dt = mr.get('跌停数', 0)
        summary_parts.append(f"大盘{style}，{vol}，涨停{zt}跌停{dt}")

    # 从主线取核心题材
    mt = result.get('main_themes', {})
    if isinstance(mt, dict) and mt.get('main_themes'):
        top_themes = [t['theme'] for t in mt['main_themes'][:3]]
        if top_themes:
            summary_parts.append(f"主线: {'、'.join(top_themes)}")

    # 从美股映射取信号
    um = result.get('us_mapping', [])
    if isinstance(um, list):
        signals = [
            m['us_sector'] for m in um
            if m.get('signal') in ('强利好', '强利空')
        ]
        if signals:
            summary_parts.append(f"美股信号: {'、'.join(signals[:3])}")

    result['summary'] = ' | '.join(summary_parts) if summary_parts else '数据获取中'

    return result


# ── 验证测试 ─────────────────────────────────────────────

if __name__ == '__main__':
    print("=" * 60)
    print("  模块二：盘面分析引擎 — 验证测试")
    print("=" * 60)

    # ── 测试1: 美股映射分析 ──
    print("\n[1/3] 美股映射分析...")
    us = analyze_us_mapping()
    print(f"  → 获取到 {len(us)} 条映射记录")
    if us:
        for item in us[:5]:
            us_pct = item.get('us_pct')
            pct_str = f'{us_pct:+.2f}%' if us_pct is not None else 'N/A'
            print(f"    {item.get('us_sector', '?'):20s} "
                  f"pct={pct_str:>8s}  "
                  f"→ {item.get('cn_sectors', [])[:3]}  "
                  f"[{item.get('signal', '?')}]")

    # ── 测试2: 大盘综合报告 ──
    print("\n[2/3] 大盘综合报告...")
    mr = get_market_report()
    if 'error' in mr:
        print(f"  ⚠️ 错误: {mr['error']}")
    else:
        keys = ['涨家数', '跌家数', '涨跌比', '成交额(亿)', '涨停数', '跌停数',
                '市场风格', '情绪', '量能判断', '量能同比']
        for k in keys:
            print(f"  {k}: {mr.get(k, 'N/A')}")
        conc = mr.get('涨停集中度', [])
        if conc:
            print(f"  涨停集中度TOP3:")
            for c in conc:
                print(f"    {c['板块']}: {c['涨停数']}只")

    # ── 测试3: 实时主线分析 ──
    print("\n[3/3] 实时主线分析...")
    mt = analyze_main_themes(min_pct=9.0)
    if 'error' in mt:
        print(f"  ⚠️ 错误: {mt['error']}")
    else:
        print(f"  热度股总数: {mt.get('hot_stock_count', 0)}")
        print(f"  涨停总数: {mt.get('total_limit_up', 0)}")
        print(f"  市场情绪: {mt.get('market_sentiment', '?')}")
        themes = mt.get('main_themes', [])
        print(f"  主线题材 TOP5:")
        for t in themes[:5]:
            print(f"    [{t['signal']}] {t['theme']}: {t['hot_count']}只 "
                  f"| 持续性: {t['persistence']} "
                  f"| 事件: {t['matched_events'][:3]}")

    # ── 完整整合输出 ──
    print(f"\n{'=' * 60}")
    print("  整合输出 JSON")
    print("=" * 60)
    result = run_module2()
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

    print(f"\n{'=' * 60}")
    print("  ✅ 模块二验证完成")
    print(f"{'=' * 60}")
