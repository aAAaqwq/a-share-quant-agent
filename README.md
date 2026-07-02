# 📈 A股板块预测研究系统 v2

> 研究目标:**找到"主力板块 / 主力方向"判断的 edge**。
> 盘前 agent 批量分析 → 竞价双轨验证 → KV 实时看板 → **人工决策**。

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![AKShare](https://img.shields.io/badge/Data-AKShare-orange.svg)](https://akshare.akfamily.xyz/)

> ⚠️ **诚实声明**:这是一个**研究项目,目前没有已证实的 edge**。旧的"个股开盘买收盘卖"
> P&L 回测(累计 -5.98%)已弃用并归档 —— 它衡量的不是我们要找的东西。现在的标尺是
> **板块判断准确率**。本项目仅供研究学习,不构成任何投资建议。

## 🎯 系统定位(v2)

```
① 脚本批量获取数据(新闻/行情/涨停)   —— 确定性管道, 带数据质量打标
        ↓
② 盘前 agent 批量分析                 —— 去重 + 因果分析, 剔除旧/虚假/无效信息
   产出: 主力板块 + 主力方向 + 15 候选涨停(附逻辑)
        ↓
③ 竞价(9:15–9:25 @30s)+ 盘中(@1h)双轨验证  —— 确定性脚本, 非 agent 实时
        ↓
④ Cloudflare KV + Pages 实时看板       —— 预测 vs 实况, 顶部死活灯
        ↓
⑤ 人工决策(系统不自动下单)
```

设计意图与逐条决策见 [`docs/intent/a-share-v2.md`](docs/intent/a-share-v2.md)。

## 🏗️ 建设进度

| 阶段 | 内容 | 状态 |
|------|------|------|
| **①** | 数据准确度层(熔断器/质量标签)+ 板块判断双轨记分 + v2 预测记录 + KV 客户端 + 闭环 | ✅ 已完成(26 单测) |
| ② | agent 盘前分析流程 + SKILL.md 手册 + prediction schema | ⏳ |
| ③ | 竞价双轨验证 + 可插拔竞价数据源 | ⏳ |
| ④ | Cloudflare KV + Pages 实时看板 | ⏳ |
| ⑤ | 部署:VPS/本地 systemd + 心跳 | ⏳ |

## 📊 板块判断记分口径

> 不再以个股 P&L 为主指标。**D 双轨**:竞价当场 + 收盘复核。

| 维度 | 命中规则 |
|------|---------|
| **主力板块** | 预测板块按【次日涨停家数】排名,**Top 3 = hit**,4–8 = neutral,>8 = miss |
| **主力方向** | 预测方向 vs 次日实际涨幅,**±2% 中性带** |

准确率 = hit /(hit + miss),中性(未证伪)不计入分母。

## 📁 目录结构

```
a-share-quant-agent/
├── config.json                  # 全局配置 (数据源 / 竞价窗口 / 刷新频率)
├── requirements.txt
├── plugins/                     # ① 数据生产层 (脚本批量获取)
│   ├── data_layer.py           # AKShare 封装 (重试 + 熔断 + 降级)
│   ├── data_quality.py         # 熔断器 + 数据质量标签 + 时效判断
│   ├── news_collector.py       # 多源并发新闻采集
│   ├── cls_flash.py / orz_hot.py / eastmoney_news.py / ...  # 各新闻源插件
│   ├── multi_source.py         # 新浪/腾讯容灾行情
│   └── validator.py            # 数据校验层
├── engines/                     # 板块预测闭环 (v2 核心)
│   ├── sector_scorer.py        # 板块判断双轨记分 (找 edge 的标尺)
│   ├── prediction_record.py    # v2 统一预测记录 (板块+候选+双轨评估+上云)
│   └── sector_pipeline.py      # save → score → stats + 推 KV
├── cloud/
│   └── kv_client.py            # Cloudflare KV / 本地文件 双后端
├── config/                      # 板块关键词 / 美股映射 / 财经过滤词
├── docs/
│   ├── intent/a-share-v2.md    # 意图确认书
│   └── design/kv-storage.md    # KV 存储方案
├── test_*.py                    # 单元测试 (data_quality / sector_scorer / prediction_record / sector_pipeline)
├── predictions/  (运行时生成)   # v2 预测记录
└── results/      (运行时生成)   # 收盘复核结果
```

## 🚀 快速开始

```bash
# 安装
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 运行测试(离线, 无网络)
./venv/bin/python3 test_data_quality.py
./venv/bin/python3 test_sector_scorer.py
./venv/bin/python3 test_prediction_record.py
./venv/bin/python3 test_sector_pipeline.py
```

## 🔧 板块预测闭环 CLI(`engines/sector_pipeline.py`)

```bash
# 保存 v2 板块预测(agent 产出后)
./venv/bin/python3 engines/sector_pipeline.py save --record @pred.json

# 收盘复核打分(实时抓涨停家数; 或 --counts 注入离线回放)
./venv/bin/python3 engines/sector_pipeline.py score --date 2026-07-02 --direction-pct 3.1

# 板块判断准确率
./venv/bin/python3 engines/sector_pipeline.py stats --days 20
```

KV 后端由环境变量自动选择:配了 `CF_ACCOUNT_ID`/`CF_KV_NAMESPACE_ID`/`CF_API_TOKEN`
走 Cloudflare,否则落本地文件(`cloud/_kvstore/`)—— 本地和 VPS 同一份代码。

## ⚠️ 风险声明

- 本项目仅供学习研究,**不构成任何投资建议**,目前无已证实 edge。
- A 股 T+1,所有"开盘买收盘卖"策略不可直接执行。
- 最终决策由人工判断,系统不自动下单。

## 📜 License

MIT © 2026 Daniel Li
