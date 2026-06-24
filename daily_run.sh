#!/bin/bash
# A股投资分析 — 一键运行脚本
# 用法: ./daily_run.sh
# 自动激活 venv → 运行编排器+报告生成 → 输出报告路径
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "╔══════════════════════════════════════════════════╗"
echo "║     🐉 A股投资分析引擎 — 一键运行                 ║"
echo "╠══════════════════════════════════════════════════╣"
echo "║  时间: $(date '+%Y-%m-%d %H:%M:%S')                  ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# 激活虚拟环境
if [ -f venv/bin/activate ]; then
    source venv/bin/activate
    echo "✅ 虚拟环境已激活: $(python3 --version)"
else
    echo "❌ 未找到 venv/bin/activate，请先运行: python3 -m venv venv && pip install -r requirements.txt"
    exit 1
fi

echo ""

# 运行 reporter（内部自动调用 orchestrator → 生成报告）
python3 reporter.py

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║  ✅ 运行完成！                                   ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""
echo "📁 报告文件:"
ls -lh reports/$(date +%Y-%m-%d).* 2>/dev/null || echo "  (报告已生成于 reports/ 目录)"
