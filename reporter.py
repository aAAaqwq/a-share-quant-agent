#!/usr/bin/env python3
"""A股投资分析 — 反偏见日报生成器 v2.0"""
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

def generate_markdown_v2(report: dict) -> str:
    """生成反偏见Markdown日报"""
    today = report.get('date', datetime.now().strftime('%Y-%m-%d'))
    
    lines = [
        f"# 🐉 A股投资分析日报 — {today}",
        f"",
        f"> ⚠️ **免责声明**: AI自动生成，不构成投资建议。据此操作风险自担。",
        f"> 生成时间: {report.get('generated_at', '')}",
        f"",
        f"---",
        f"",
    ]
    
    # ═══════════════════════════════════════
    # Part 1: 📋 事实层（已确认的数据和事件）
    # ═══════════════════════════════════════
    lines.extend([
        f"## 📋 事实层（已确认数据）",
        f"",
    ])
    
    # 大盘数据
    market = report.get('module2_market', {})
    if not market.get('error'):
        mp = market.get('market_report', {})
        if mp:
            lines.extend([
                f"### 大盘指数",
                f"",
                f"| 指数 | 点位 | 涨跌幅 | 成交额 |",
                f"|------|------|--------|--------|",
            ])
            for idx_name in ['上证指数', '深证成指', '创业板指', '科创50']:
                for key, val in mp.items():
                    if isinstance(val, dict) and val.get('name') == idx_name:
                        lines.append(f"| {idx_name} | {val.get('price','?')} | {val.get('pct','?')}% | {val.get('volume_yi','?')}亿 |")
            
            sentiment = mp.get('sentiment', '未知')
            lines.append(f"\n**市场情绪**: {sentiment}")
        
        # 主线题材
        themes = market.get('main_themes', [])
        if themes:
            lines.extend([f"", f"### 涨停板块分布", f""])
            for t in themes[:8]:
                if isinstance(t, dict):
                    lines.append(f"- **{t.get('theme','?')}**: {t.get('hot_count','?')}只涨停")
    
    # 新闻事实
    news = report.get('module1_news', {})
    if not news.get('error'):
        lines.extend([
            f"",
            f"### 今日情报（共{news.get('total', 0)}条）",
            f"",
        ])
        for item in news.get('top_items', [])[:10]:
            title = item.get('title', '')[:50]
            source = item.get('source', '')
            lines.append(f"- [{source}] {title}")
    
    # ═══════════════════════════════════════
    # Part 2: 🧠 推测层（逻辑推演，标注置信度）
    # ═══════════════════════════════════════
    lines.extend([
        f"",
        f"---",
        f"",
        f"## 🧠 推测层（逻辑推演）",
        f"",
        f"> 以下内容基于事实层的逻辑推演，**非确定性预测**。",
        f"",
    ])
    
    # 美股映射
    us_map = market.get('us_mapping', [])
    if us_map:
        lines.extend([f"### 美股映射信号", f""])
        for u in us_map[:5]:
            if isinstance(u, dict):
                signal = u.get('signal', '')
                emoji = '🟢' if '利好' in signal else '🔴' if '利空' in signal else '⚪'
                lines.append(f"{emoji} **{u.get('us_sector','?')}** {u.get('us_pct','?')}% → A股{u.get('cn_sectors','?')} ({signal})")
    
    # ═══════════════════════════════════════
    # Part 3: 🎯 个股分析（含量化指标+风控）
    # ═══════════════════════════════════════
    stocks_data = report.get('module3_stocks', {})
    stocks = stocks_data.get('stocks', [])
    
    if stocks:
        lines.extend([
            f"",
            f"---",
            f"",
            f"## 🎯 个股分析",
            f"",
        ])
        
        for i, s in enumerate(stocks[:10], 1):
            name = s.get('name', '?')
            code = s.get('code', '?')
            score = s.get('score', '?')
            excluded = s.get('excluded', False)
            
            if excluded:
                lines.append(f"### {i}. ~~{name}({code})~~ ⛔ 已排除（风险过高）")
                for w in s.get('risk_warnings', []):
                    lines.append(f"   {w['level']} {w['type']}: {w['detail']}")
                lines.append("")
                continue
            
            lines.append(f"### {i}. {name}({code}) — 评分 {score}/100")
            
            # 多头逻辑
            bull = s.get('bull_reasons', [])
            if bull:
                lines.append(f"**🐂 多头逻辑**:")
                for r in bull:
                    lines.append(f"- {r}")
            
            # 空头逻辑
            bear = s.get('bear_reasons', [])
            if bear:
                lines.append(f"\n**🐻 空头逻辑**:")
                for r in bear:
                    lines.append(f"- {r}")
            else:
                lines.append(f"\n**🐻 空头逻辑**: 无明显利空信号")
            
            # 风控
            sl = s.get('stop_loss', {})
            pos = s.get('position', {})
            if sl:
                lines.append(f"\n**⚡ 风控建议**:")
                lines.append(f"- 止损位: ¥{sl.get('stop_loss','?')} ({sl.get('stop_loss_pct','?')}%)")
                lines.append(f"- 止盈位: ¥{sl.get('take_profit_1','?')} / ¥{sl.get('take_profit_2','?')}")
                lines.append(f"- 建议仓位: {pos.get('position_pct','?')}% ({pos.get('shares','?')}股)")
            
            # 风险标记
            warnings = s.get('risk_warnings', [])
            if warnings:
                lines.append(f"\n**⚠️ 风险标记**:")
                for w in warnings:
                    lines.append(f"- {w['level']} {w['type']}: {w['detail']}")
            
            lines.append("")
    
    # ═══════════════════════════════════════
    # Part 4: 📊 数据源声明
    # ═══════════════════════════════════════
    lines.extend([
        f"---",
        f"",
        f"## 📊 数据源声明",
        f"",
    ])
    
    errors = report.get('errors', [])
    if errors:
        lines.append(f"**本次运行的错误**:")
        for e in errors:
            lines.append(f"- ⚠️ {e}")
    
    lines.extend([
        f"",
        f"| 数据类型 | 来源 | 状态 |",
        f"|----------|------|------|",
        f"| 行情数据 | 新浪/腾讯/AKShare | 自动降级 |",
        f"| 新闻情报 | 财联社/orz.ai/东财 | 7源并发 |",
        f"| 量化指标 | 自研引擎 | RSI/MACD/ATR |",
        f"| 风控计算 | 自研引擎 | ATR止损+仓位 |",
        f"",
        f"---",
        f"",
        f"*⚠️ 本报告由AI自动生成，所有推测层内容均标注置信度，不构成投资建议。*",
        f"*数据可能有延迟，请以实际行情为准。*",
    ])
    
    return '\n'.join(lines)


def save_report_v2(report: dict):
    """保存报告"""
    today = report.get('date', datetime.now().strftime('%Y-%m-%d'))
    reports_dir = PROJECT_ROOT / 'reports'
    reports_dir.mkdir(exist_ok=True)
    
    # JSON
    json_path = reports_dir / f'{today}.json'
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    
    # Markdown
    md_path = reports_dir / f'{today}.md'
    md_path.write_text(generate_markdown_v2(report))
    
    return {'json': str(json_path), 'markdown': str(md_path)}


if __name__ == '__main__':
    from orchestrator import run_full_pipeline
    print("⚙️ 运行完整流水线（v2.0 反偏见模板）...")
    report = run_full_pipeline()
    paths = save_report_v2(report)
    print(f"✅ JSON: {paths['json']}")
    print(f"✅ 日报: {paths['markdown']}")
    print(generate_markdown_v2(report))
