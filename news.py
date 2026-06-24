#!/usr/bin/env python3
"""📰 股票影响信息分类浏览器

专门展示影响股票的热门信息。**源信息不做任何修改**——
- 标题直接来自数据源
- 正文直接来自数据源
- 链接、时间戳、来源都保留原始值

只做两件事：
  1) 分类（按板块/事件类型）
  2) 去重（按标题前30字符+来源）

不做任何 LLM 改写、总结、截断、润色。

用法:
  python news.py                    # 所有源，按板块分类
  python news.py --source cls      # 只看财联社
  python news.py --sector AI       # 只看人工智能板块
  python news.py --keyword "黄金"  # 关键词搜索
  python news.py --no-group        # 不分类，按时间排序
  python news.py --format json     # JSON 输出（程序调用）
  python news.py --format md       # Markdown 表格输出
  python news.py --limit 5         # 每板块/每源最多 N 条
  python news.py --show-content    # 显示正文（默认只看标题）
"""
import argparse
import json
import sys
import os
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from plugins.news_collector import collect_sync, ALL_SOURCES


# ─────────────────────────────────────────────
# 板块分类（纯字符串匹配，不做语义分析）
# ─────────────────────────────────────────────
def load_sector_keywords():
    config_path = PROJECT_ROOT / "config" / "sector_keywords.json"
    if not config_path.exists():
        return {}
    with open(config_path, encoding="utf-8") as f:
        return json.load(f)


def classify_by_sector(title: str, content: str, sector_map: dict) -> list:
    """匹配标题+正文，返回命中的板块列表（按重要性降序）
    
    纯关键词匹配，**不做任何语义改写**。
    """
    text = (title or "") + " " + (content or "")
    hits = []
    for sector, info in sector_map.items():
        keywords = info.get("keywords", [])
        matched = [kw for kw in keywords if kw and kw in text]
        if matched:
            hits.append({
                "sector": sector,
                "importance": info.get("importance", 5),
                "matched_keywords": matched,
            })
    hits.sort(key=lambda x: (-x["importance"], -len(x["matched_keywords"])))
    return hits


# ─────────────────────────────────────────────
# 输出格式化（结构化展示，不改源文）
# ─────────────────────────────────────────────
SOURCE_LABELS = {
    "orz_hot": "orz热点",
    "cls": "财联社",
    "eastmoney": "东财",
    "wallstreetcn": "华尔街见闻",
    "rss": "RSS",
    "jiucaigongshe": "韭菜公社",
}


def fmt_time(ts):
    if not ts:
        return "—"
    if isinstance(ts, str):
        return ts
    try:
        return ts.strftime("%m-%d %H:%M")
    except Exception:
        return str(ts)


def render_terminal_grouped(items, sector_map, show_content=False, limit=None):
    """终端输出：按板块分组"""
    # 分类
    classified = {item: classify_by_sector(item.title, item.content, sector_map) for item in items}
    
    # 按板块聚合
    by_sector = {}
    for item, hits in classified.items():
        if hits:
            for h in hits:
                by_sector.setdefault(h["sector"], []).append((item, h["matched_keywords"]))
        else:
            by_sector.setdefault("未分类", []).append((item, []))
    
    # 排序板块（按数量+重要性）
    def sector_sort_key(name):
        if name == "未分类":
            return (0, 0)
        info = sector_map.get(name, {})
        count = len(by_sector.get(name, []))
        return (1, -info.get("importance", 0), -count)
    
    sorted_sectors = sorted(by_sector.keys(), key=sector_sort_key)
    
    print(f"\n📰 股票影响信息分类 — 共 {len(items)} 条 / {len(by_sector)} 个分类\n")
    print("=" * 80)
    
    for sector in sorted_sectors:
        sector_items = by_sector[sector]
        if limit:
            sector_items = sector_items[:limit]
        importance = sector_map.get(sector, {}).get("importance", "—")
        print(f"\n## {sector} (重要性={importance}, {len(sector_items)} 条)")
        print("-" * 80)
        for item, matched_kws in sector_items:
            src = SOURCE_LABELS.get(item.source, item.source)
            t = fmt_time(item.timestamp)
            hot = f"🔥{item.hot_score:.0f}" if item.hot_score else ""
            kw_str = f" [匹配: {','.join(matched_kws[:3])}]" if matched_kws else ""
            print(f"\n  [{src}] {t} {hot}")
            print(f"  📌 {item.title}{kw_str}")
            if show_content and item.content:
                content = item.content.strip()
                # 仅按用户字数限制截断（不算改写）
                if len(content) > 200:
                    content = content[:200] + "..."
                print(f"  📝 {content}")
            if item.url:
                print(f"  🔗 {item.url}")
    print("\n" + "=" * 80)


def render_terminal_chronological(items, show_content=False, limit=None):
    """终端输出：按时间倒序"""
    sorted_items = sorted(items, key=lambda x: x.timestamp or datetime.min, reverse=True)
    if limit:
        sorted_items = sorted_items[:limit]
    
    print(f"\n📰 股票影响信息 — 共 {len(items)} 条（按时间排序）\n")
    print("=" * 80)
    for item in sorted_items:
        src = SOURCE_LABELS.get(item.source, item.source)
        t = fmt_time(item.timestamp)
        hot = f"🔥{item.hot_score:.0f}" if item.hot_score else ""
        print(f"\n  [{src}] {t} {hot}")
        print(f"  📌 {item.title}")
        if show_content and item.content:
            content = item.content.strip()
            if len(content) > 200:
                content = content[:200] + "..."
            print(f"  📝 {content}")
        if item.url:
            print(f"  🔗 {item.url}")
    print("\n" + "=" * 80)


def render_markdown(items, sector_map, show_content=False, limit=None):
    """Markdown 输出：分类表格"""
    classified = {item: classify_by_sector(item.title, item.content, sector_map) for item in items}
    
    by_sector = {}
    for item, hits in classified.items():
        if hits:
            for h in hits:
                by_sector.setdefault(h["sector"], []).append((item, h))
        else:
            by_sector.setdefault("未分类", []).append((item, None))
    
    lines = [f"# 📰 股票影响信息 — {datetime.now().strftime('%Y-%m-%d %H:%M')}", ""]
    lines.append(f"> 共 {len(items)} 条新闻 / {len(by_sector)} 个分类")
    lines.append(f"> **源信息未经任何修改**（标题/正文/链接均为源数据原样）")
    lines.append("")
    
    for sector in sorted(by_sector.keys()):
        if sector == "未分类":
            lines.append(f"## {sector}")
        else:
            importance = sector_map.get(sector, {}).get("importance", "—")
            lines.append(f"## {sector} (重要性: {importance})")
        lines.append("")
        lines.append("| 时间 | 来源 | 标题 | 热度 | 链接 |")
        lines.append("|------|------|------|------|------|")
        for item, hit in by_sector[sector][:limit] if limit else by_sector[sector]:
            src = SOURCE_LABELS.get(item.source, item.source)
            t = fmt_time(item.timestamp)
            hot = f"{item.hot_score:.0f}" if item.hot_score else "—"
            title = item.title.replace("|", "\\|")
            url = item.url or "—"
            lines.append(f"| {t} | {src} | {title} | {hot} | [🔗]({url}) |")
        lines.append("")
        if show_content:
            lines.append("<details><summary>展开正文</summary>\n")
            for item, hit in by_sector[sector][:limit] if limit else by_sector[sector]:
                if item.content:
                    content = item.content.replace("|", "\\|").replace("\n", "<br>")
                    lines.append(f"**{item.title}**")
                    lines.append(f"\n> {content}\n")
            lines.append("\n</details>\n")
    
    return "\n".join(lines)


def render_json(items, sector_map):
    """JSON 输出（结构化，程序调用）"""
    classified = {item: classify_by_sector(item.title, item.content, sector_map) for item in items}
    out = []
    for item, hits in classified.items():
        out.append({
            "source": item.source,
            "source_label": SOURCE_LABELS.get(item.source, item.source),
            "title": item.title,           # 原文标题
            "content": item.content,       # 原文内容
            "url": item.url,               # 原文链接
            "timestamp": item.timestamp.isoformat() if item.timestamp else None,
            "hot_score": item.hot_score,   # 原始热度
            "tags": item.tags,             # 原始标签
            "sectors": [h["sector"] for h in hits],  # 分类结果
            "matched_keywords": [h["matched_keywords"] for h in hits],
        })
    return json.dumps(out, ensure_ascii=False, indent=2)


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(
        description="📰 股票影响信息分类浏览器（源信息不做任何修改）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--source", "-s", help="指定数据源 (cls/orz_hot/eastmoney/wallstreetcn/rss/jiucaigongshe)")
    p.add_argument("--sector", help="只显示某板块 (如 人工智能/半导体/机器人)")
    p.add_argument("--keyword", "-k", help="关键词过滤 (在标题+正文中查找)")
    p.add_argument("--no-group", action="store_true", help="不分类，按时间排序")
    p.add_argument("--format", "-f", choices=["terminal", "md", "json"], default="terminal")
    p.add_argument("--limit", "-n", type=int, help="每分类/每源最多 N 条")
    p.add_argument("--show-content", "-c", action="store_true", help="显示正文 (默认只看标题)")
    p.add_argument("--save", help="保存到文件 (路径)")
    p.add_argument("--list-sources", action="store_true", help="列出可用数据源")
    p.add_argument("--no-finance-filter", action="store_true", help="关闭财经关键词过滤（默认开启）")
    args = p.parse_args()
    
    if args.list_sources:
        print("可用数据源:")
        for sid, src in ALL_SOURCES.items():
            print(f"  {sid:15} {src.name}")
        return
    
    # 加载财经关键词
    finance_keywords = []
    if not args.no_finance_filter:
        fk_path = PROJECT_ROOT / "config" / "finance_keywords.json"
        if fk_path.exists():
            with open(fk_path, encoding="utf-8") as f:
                finance_keywords = json.load(f).get("keywords", [])

    # 采集（传 finance_keywords 用于 orz_hot 内部过滤）
    if args.source:
        if args.source not in ALL_SOURCES:
            print(f"❌ 未知数据源: {args.source}")
            print(f"可用: {', '.join(ALL_SOURCES.keys())}")
            sys.exit(1)
        # 单源采集需要走 asyncio 才能传 kwargs
        if finance_keywords and args.source == "orz_hot":
            items = collect_sync([args.source], finance_keywords=finance_keywords)
        else:
            items = collect_sync([args.source])
    else:
        items = collect_sync(finance_keywords=finance_keywords if finance_keywords else None)

    # 二次过滤：剔除标题中无任何财经关键词的非财经热点
    if finance_keywords and not args.no_finance_filter:
        def is_finance(item):
            text = (item.title or "") + " " + (item.content or "")
            return any(kw in text for kw in finance_keywords)
        before = len(items)
        items = [i for i in items if is_finance(i)]
        after = len(items)
        if args.format == "terminal":
            print(f"📡 财经过滤: {before} → {after} 条（剔除 {before-after} 条非财经热点）")
    
    # 过滤
    if args.keyword:
        kw = args.keyword
        items = [i for i in items if kw in (i.title or "") or kw in (i.content or "")]
    
    if args.sector:
        sector_map = load_sector_keywords()
        sector_kws = sector_map.get(args.sector, {}).get("keywords", [])
        if not sector_kws:
            print(f"❌ 未知板块: {args.sector}")
            print("可用板块:", ", ".join(sector_map.keys()))
            sys.exit(1)
        # 匹配任一关键词即保留
        items = [i for i in items if any(kw in (i.title + " " + (i.content or "")) for kw in sector_kws)]
    
    if not items:
        print("⚠️ 无匹配新闻")
        return
    
    # 渲染
    sector_map = load_sector_keywords()
    
    if args.format == "json":
        output = render_json(items, sector_map)
    elif args.format == "md":
        output = render_markdown(items, sector_map, show_content=args.show_content, limit=args.limit)
    else:
        output = None
        if args.no_group:
            render_terminal_chronological(items, show_content=args.show_content, limit=args.limit)
        else:
            render_terminal_grouped(items, sector_map, show_content=args.show_content, limit=args.limit)
    
    if output is not None:
        if args.save:
            Path(args.save).write_text(output, encoding="utf-8")
            print(f"✅ 已保存到: {args.save}")
        else:
            print(output)


if __name__ == "__main__":
    main()
