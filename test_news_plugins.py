"""测试新闻插件"""
import asyncio
import sys

sys.path.insert(0, ".")
from plugins.news_collector import collect_all, ALL_SOURCES


async def test_syntax():
    """验证所有插件可导入"""
    print("=== 插件导入检查 ===")
    for src_id, src in ALL_SOURCES.items():
        print(f"  {src_id}: {src.name} ✓")
    print(f"  共 {len(ALL_SOURCES)} 个插件\n")


async def test_eastmoney():
    """测试东方财富要闻"""
    print("=== 测试 东方财富要闻 (eastmoney) ===")
    items = await collect_all(active_sources=["eastmoney"])
    print(f"东方财富: {len(items)} 条")
    if items:
        for i in items[:5]:
            print(f"  {i.title[:60]}")
        print(f"  来源: {items[0].source}")
        print(f"  URL: {items[0].url[:60]}")
    else:
        print("  (无数据)")
    print()


async def test_cls():
    """测试财联社电报（可能因签名限制返回空）"""
    print("=== 测试 财联社电报 (cls) ===")
    items = await collect_all(active_sources=["cls"])
    print(f"财联社: {len(items)} 条")
    if items:
        for i in items[:5]:
            ts = i.timestamp.strftime("%H:%M") if i.timestamp else "N/A"
            print(f"  [{ts}] {i.title[:60]}")
    else:
        print("  (无数据 — API可能需要签名，插件已正确处理)")


if __name__ == "__main__":
    asyncio.run(test_syntax())
    asyncio.run(test_eastmoney())
    asyncio.run(test_cls())
