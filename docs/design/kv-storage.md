# Cloudflare KV 存储方案

> 状态: 规划 + 客户端已实现(`cloud/kv_client.py`), Pages 读取端待 Phase ④
> 目标: 预测 + 竞价/盘中实时数据上云, dashboard 只读展示, 死活可观测

## 为什么用 KV(而非 D1/R2)

- 数据是**少量键、高频覆写、只读展示** → KV 的 key-value + 边缘缓存正合适。
- 免费额度充裕(见下预算), 无需数据库。
- 强一致场景(如竞价撮合精确回放)未来可换 R2/D1;当前 dashboard 容忍最终一致。

## 键约定

| 键 | 内容 | 写入方 | 频率 |
|----|------|--------|------|
| `pred:latest` | 今日完整预测记录(v2 `to_kv_payload`) | 盘前 GH Actions | 1 次/日, 收盘更新评估 |
| `pred:{YYYY-MM-DD}` | 按日归档的预测记录 | 盘前 + 收盘 | 2 次/日 |
| `pred:dates` | 历史日期索引 `["2026-07-02", ...]` | 盘前 | 1 次/日 |
| `live:latest` | 竞价/盘中高频小 blob(竞价轨打分、**动态候选+实时涨跌幅**、兑现率、板块强势家数) | 竞价/盘中常驻脚本(`intraday_puller.py`) | **竞价 30s / 盘中 1h** |
| `news:latest` | 相关资讯 feed `{as_of, items:[{title,snippet,url,source,hot_score}]}` | `intraday_puller.py`(盘前 + 每小时) | 低频 |
| `meta:heartbeat` | `{last_update, epoch, phase}` 死活灯 | 每次推送 | 同上 |

`live:latest` 由 `engines/auction_monitor.build_live_blob()` 组装:候选按竞价涨跌幅
**动态重排**(非固定 15)、剔除走弱、并入新晋强势;竞价轨打分复用 `sector_scorer`
(竞价强势家数排名 + 大盘竞价涨幅方向)。数据源 `plugins/auction_source.py` 可插拔。

**关键设计**: 30s 高频只覆写 `live:latest` + `meta:heartbeat` 两个**小** blob,
绝不重写大的 `pred:latest`。既省写入配额, 又不会覆盖盘前预测正本。

## 写入路径(Python 侧)

三个入口共用 `cloud/kv_client.py` 的 `PredictionKV`:

```
盘前 (GH Actions)      pkv.write_prediction(date, record.to_kv_payload())
竞价/盘中 (VPS/本地)   pkv.write_live(live_blob, phase="auction"|"session")
收盘 (GH Actions)      record = attach_evaluation("close", score); write_prediction(...)
```

后端由环境变量自动选择:
- 配了 `CF_ACCOUNT_ID` + `CF_KV_NAMESPACE_ID` + `CF_API_TOKEN` → Cloudflare KV REST
- 没配 / `KV_BACKEND=local` → 本地文件后端(`cloud/_kvstore/`), 满足"本地拉数据"

## 读取路径(dashboard 侧, Phase ④)

Cloudflare KV **不能**从浏览器直接公开读。两种读法:

1. **Cloudflare Pages Function**(推荐): Pages 项目绑定 KV namespace,
   写一个 `/functions/api/[key].js`, 用 `env.ASHARE_KV.get(key)` 返回 JSON。
   静态前端 `fetch('/api/pred:latest')` 轮询。免费、零额外服务。
2. 本地模式: 一个极简 HTTP 服务读 `cloud/_kvstore/` 返回同样 JSON, 前端同构。

死活灯: 前端每次拉 `meta:heartbeat`, `now - epoch > 60s` → 顶部变红。

## 密钥管理(安全)

- `CF_API_TOKEN` 用**范围最小**的 token: 只给目标 namespace 的 KV 写权限。
- 三个变量只放:
  - GitHub Actions → repo **Secrets**
  - VPS/本地 → `.env`(已 gitignore)或 systemd `EnvironmentFile`
- **绝不入库**。`cloud/kv_client.py` 全程从 `os.environ` 读, 代码里无任何明文。

## 免费额度预算(每日写入估算)

| 阶段 | 写入次数 |
|------|---------|
| 盘前 | pred:latest + pred:{date} + pred:dates ≈ 3 |
| 竞价 9:15–9:25 @30s | ~20 × 2 键(live+heartbeat) = 40 |
| 盘中 9:30–15:00 @1h | ~6 × 2 = 12 |
| 收盘 | pred:latest + pred:{date} ≈ 2 |
| **合计** | **≈ 57 写/日** |

Cloudflare KV 免费层: **1000 写/日、100k 读/日、1GB 存储**。
→ 57 写/日 远低于上限, **完全免费**。(注: 单键写入频率上限 ~1 次/秒, 30s 无压力。)

## 一致性与限制

- KV **最终一致**, 跨边缘传播最长 ~60s。个人 dashboard 单区域读通常秒级,
  但"写后立刻全球读到"无保证 → 死活灯用 `epoch` 判断, 容忍轻微延迟。
- 值上限 25 MiB、键上限 512 B: 我们的 blob 都是 KB 级, 无忧。
- 需要**强一致 / 精确竞价回放**时再上 R2(对象存储)或 D1(SQLite)。

## 客户端 API(已实现)

`cloud/kv_client.py`:
- 后端: `LocalKV` / `CloudflareKV`, `_make_backend()` 按 env 自动选。
- 语义层 `PredictionKV`: `write_prediction / write_live / write_heartbeat /
  read_prediction / read_live / read_heartbeat / list_dates`。
- 单测: `test_prediction_record.py` 覆盖本地后端 round-trip + 语义读写。
