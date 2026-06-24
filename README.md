# 📈 A-股量化投资分析 Agent

> AI 驱动的 A 股投资分析系统 — 涨停池采集 / 盘面阅读 / 个股精选 / 实盘验证 全链路自动化

[![Python](https://img.shields.io/badge/Python-3.14+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![AKShare](https://img.shields.io/badge/Data-AKShare-orange.svg)](https://akshare.akfamily.xyz/)

## ✨ 核心能力

| 模块 | 功能 | 状态 |
|------|------|------|
| 🔍 **情报采集** | 7 路并发新闻源 (财联社/华尔街见闻/东方财富/新浪/orz.ai/RSS/搜索) | ✅ |
| 📊 **盘面分析** | 美股映射 + 大盘多空 + 实时主线 (9% 涨幅以上题材) | ✅ |
| 🎯 **个股精选** | 五维评分: 产业逻辑 + K 线形态 + 盘口 + 板块排名 + 事件 | ✅ |
| 📝 **日报生成** | Markdown 报告 + TOP3 深度分析 | ✅ |
| 💾 **预测落库** | JSON 格式 predictions/results 分日管理 | ✅ |
| ✅ **实盘验证** | 次日开盘买入 + 止盈止损模拟 + 成本模型 | ✅ |
| 📈 **基线校准** | 历史回填 15 天 70 样本,生成胜率/盈亏比统计 | ✅ |

## 🚀 快速开始

```bash
# 1. 克隆
git clone https://github.com/aAAaqwq/a-share-quant-agent.git
cd a-share-quant-agent

# 2. 安装依赖
python3 -m venv venv
source venv/bin/activate
pip install akshare pandas numpy aiohttp feedparser openpyxl

# 3. 一键运行 (盘前情报)
./daily_run.sh

# 4. 实盘验证 (15:30 自动 / 手动)
python backtester.py verify-all
```

## 🧠 系统架构

```
┌─────────────────────────────────────────────────────┐
│              📈 A股量化分析系统                        │
├─────────────────────────────────────────────────────┤
│                                                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐           │
│  │ 模块一   │  │ 模块二   │  │ 模块三   │           │
│  │ 情报采集 │→│ 盘面阅读 │→│ 个股精选 │           │
│  │          │  │          │  │          │           │
│  │ 7源并发  │  │ 美股映射  │  │ 5维评分  │           │
│  │ 去重匹配  │  │ 大盘多空  │  │ 8形态    │           │
│  └──────────┘  └──────────┘  └──────────┘           │
│        ↓              ↓             ↓                │
│        └──────────────┴─────────────┘                │
│                       ↓                              │
│              ┌──────────────┐                        │
│              │  编排 + 报告  │                        │
│              └──────────────┘                        │
│                       ↓                              │
│              ┌──────────────┐                        │
│              │ 预测落库 + 验证│ ← 实盘日志闭环         │
│              └──────────────┘                        │
│                                                       │
└─────────────────────────────────────────────────────┘
```

## 📊 8 种 K 线形态识别

| 形态 | 信号 | 期望收益 |
|------|------|----------|
| 突破平台 | 横盘蓄势向上 | +5% ~ +15% |
| 趋势新高 | 沿 5/10 日均线持续新高 | +3% ~ +8% |
| 新高附近 | 距 60 日新高 < 3% | +2% ~ +6% |
| N 连板 | 连续涨停追板 | 高波动/高风险 |
| 老龙二波 | 前期龙头回踩启动 | +10% ~ +30% |
| 分歧转一致 | 烂板次日转强 | +5% ~ +10% |
| 反包板 | 阴包阳形态修复 | +3% ~ +8% |
| 放量首板 | 首次涨停 + 巨量 | +5% ~ +12% |

## 💰 成本模型

```python
# 买入
buy_cost = entry_price × 1.00035
  # = 滑点 0.01% + 佣金 0.025% (单边)

# 卖出
sell_revenue = exit_price × 0.99915
  # = 滑点 0.01% + 佣金 0.025% + 印花税 0.05%

# 实际收益
pnl_pct = (sell_revenue - buy_cost) / buy_cost × 100
```

## 📁 目录结构

```
a-share-quant-agent/
├── SKILL.md                     # 项目文档
├── orchestrator.py              # 三模块编排器
├── reporter.py                  # 日报生成器
├── daily_run.sh                 # 一键运行
├── tracker.py                   # 预测落库 + 统计
├── backtester.py                # 次日验证引擎
├── backfill.py                  # 历史回填
├── config/                      # 配置文件
│   ├── sector_keywords.json    # 板块关键词映射 (30+ 板块)
│   ├── us_mapping.json         # 美股 → A 股映射
│   └── finance_keywords.json   # 财经过滤词
├── engines/                     # 分析引擎
│   ├── module2_market.py       # 盘面分析
│   ├── module3_stocks.py       # 个股精选
│   └── indicators.py           # 技术指标
├── plugins/                     # 数据源
│   ├── news_collector.py       # 7 源新闻采集
│   ├── data_layer.py           # A 股数据层
│   └── base.py                 # 插件基类
├── predictions/                 # 历史预测 (YYYY-MM-DD.json)
└── results/                     # 验证结果 (YYYY-MM-DD.json)
```

## 🔧 CLI 命令

```bash
# 盘前情报
./daily_run.sh

# 落库预测
python tracker.py save --date 2026-06-24 --picks '<JSON>'

# 统计胜率 (近 N 日)
python tracker.py stats --days 20

# 次日验证
python backtester.py verify --date 2026-06-24
python backtester.py verify-all
python backtester.py show --date 2026-06-24

# 历史回填
python backfill.py
```

## 📈 基线校准结果

> 15 个交易日 / 70 个样本 / 策略: 涨停龙头 +5% / -3% / 1 日持仓

| 指标 | 数值 |
|------|------|
| 胜率 | 32.86% |
| 止损率 | 57.14% |
| 平均收益 | -0.08% |
| 最大单笔盈利 | +4.87% |
| 最大单笔亏损 | -3.12% |

⚠️ 简单策略勉强盈亏平衡,需要根据板块 / 板数 / 持仓期做策略优化。

## ⚠️ 风险声明

- **本项目仅供学习研究使用,不构成任何投资建议**
- A 股 T+1 制度,所有"开盘买收盘卖"策略均不可直接执行
- 历史回测不代表未来收益,实盘请谨慎
- 涉及金额请根据个人风险承受能力严格控制

## 📜 License

MIT © 2026 Daniel Li
