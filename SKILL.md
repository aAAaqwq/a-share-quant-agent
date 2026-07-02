# A股板块预测研究 Skill (v2)

> **定位**: 找到"主力板块/主力方向"判断 edge 的研究系统
> **触发词**: 分析A股 | 主力板块 | 主力方向 | 板块预测 | 盘前情报 | 竞价验证 | A股复盘
> **数据引擎**: AKShare + 多源新闻 + Python
> **更新**: 2026-07-02

> ⚠️ 旧版(个股 P&L 回测 / reporter / orchestrator / module2-3)已整体弃用并删除,
> 历史数据归档在 `_archive/`。本文件描述 v2 新架构;详见 [README](README.md) 与
> [意图书](docs/intent/a-share-v2.md)。

## 系统四层

```
① 数据生产层  plugins/   脚本批量获取新闻+行情+涨停, 带熔断+质量打标
② 分析层      (Phase ②)  盘前 agent 批量分析 → 主力板块+方向+15候选
③ 验证层      engines/sector_scorer.py + sector_pipeline.py  竞价+收盘双轨记分
④ 存储/展示   cloud/kv_client.py → Cloudflare KV → Pages 看板
```

## 记分口径(找 edge 的标尺)

- **主力板块**: 预测板块按次日【涨停家数】排名, Top 3 = hit, 4–8 = neutral, >8 = miss
- **主力方向**: 预测方向 vs 次日涨幅, ±2% 中性带
- 准确率 = hit /(hit+miss), 中性不计入分母

## 当前可用能力(Phase ① 已完成)

### 数据准确度(`plugins/data_quality.py`)
- `CircuitBreaker`: 数据源连续失败熔断, 冷却期跳过, 治接口硬捶
- `DataQuality`: 每份数据打标 source/fetched_at/is_stale/fallback_from/data_quality
- 已接入 `data_layer._call_with_retry`

### 板块记分闭环(`engines/sector_pipeline.py`)
```bash
# 保存 v2 预测
./venv/bin/python3 engines/sector_pipeline.py save --record @pred.json
# 收盘复核(实时抓 / --counts 注入离线)
./venv/bin/python3 engines/sector_pipeline.py score --date YYYY-MM-DD --direction-pct 3.1
# 板块准确率
./venv/bin/python3 engines/sector_pipeline.py stats --days 20
```

### 预测记录 schema(`engines/prediction_record.py`)
```json
{
  "schema_version": 2,
  "date": "YYYY-MM-DD",
  "prediction": {
    "main_sectors": ["人工智能", "半导体"],
    "main_direction": "up",
    "candidates": [{"code","name","sector","reason","rank"}, "...15"]
  },
  "evaluation": {"auction": null, "close": null},
  "data_quality": {"overall": "ok"},
  "status": "predicted"
}
```

### KV 存储(`cloud/kv_client.py`)
- Cloudflare / 本地双后端, env 自动选(见 `docs/design/kv-storage.md`)
- 键: `pred:latest` / `pred:{date}` / `live:latest` / `meta:heartbeat` / `pred:dates`

## Agent 盘前分析协议(Phase ② 建设中)

目标流程(待实现):
```
Step 1 脚本批量拉取: 新闻(plugins/news_collector) + 行情/涨停(plugins/data_layer)
Step 2 组装数据包: 每块附数据质量标签(可用/降级/过期/部分/缺失)
Step 3 agent 分析: 去重 → 因果分析 → 剔除旧/虚假/无效 → 输出主力板块+方向+15候选
Step 4 落库: build_record() → sector_pipeline.save_prediction() → 推 KV
```

## 环境检查

```bash
python3 -c "import akshare, pandas, numpy, aiohttp; print('OK')" 2>/dev/null || \
pip3 install -r requirements.txt
```

## 数据源 API 速查(AKShare 核心)

| 函数 | 说明 |
|------|------|
| `stock_zh_a_spot_em()` | 全A实时行情 |
| `stock_zt_pool_em(date)` | 涨停池(含"所属行业", 板块记分依据) |
| `stock_board_industry_name_em()` | 行业板块排名 |
| `stock_board_concept_name_em()` | 概念板块排名 |
| `stock_zh_a_hist(...)` | 历史K线 |
| `index_global_spot_em()` | 全球指数(美股映射) |

## 扩展指南

- 新增新闻源: 继承 `plugins/base.NewsSourcePlugin`, 实现 `fetch()`, 在 config 注册
- 新增竞价数据源(Phase ③): 做成可插拔 source, 复用 `sector_scorer` 纯记分函数
