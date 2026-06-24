# A股分析 GitHub 开源项目情报调研报告

> 调研时间: 2026-06-19
> 调研人: 天枢(天问情报Agent)
> 用途: 为 A股分析 Skill 设计提供参考架构

---

## 一、核心项目详细分析

### 1.1 AigcExpert/daily_stock_analysis (DSA) ⭐ 最重要

**仓库**: https://github.com/AigcExpert/daily_stock_analysis
**状态**: 极其活跃, 420+ commits(主库), 大量 fork 持续更新(部分 fork 达 634 commits)
**定位**: LLM驱动的 A/H/美股智能分析器, 零成本, 纯白嫖

#### 架构分层

```
daily_stock_analysis/
├── .claude/skills/      # Claude Agent Skills 定义
├── data_provider/       # 行情数据适配层(多数据源统一接口)
├── sources/             # 新闻搜索数据源配置
├── src/                 # 核心分析引擎
├── bot/                 # 多渠道推送机器人
├── api/                 # FastAPI REST API
├── apps/                # Web前端(React) + 桌面端
├── strategies/          # 投资策略模板
├── templates/           # 报告模板
├── scripts/             # 部署脚本
├── docker/              # Docker部署配置
├── docs/                # 文档
├── tests/               # 测试
├── SKILL.md             # Agent Skill 定义
├── CLAUDE.md            # Claude Code 上下文配置
├── AGENTS.md            # Agent 开发规范(290行)
├── analyzer_service.py  # 核心分析服务
├── main.py              # 入口脚本
├── server.py            # Web服务
└── webui.py             # Web界面
```

#### 技术栈矩阵

| 层次 | 支持选项 | 推荐首选 | 免费可用 |
|------|---------|---------|---------|
| **AI模型** | Gemini, OpenAI兼容, DeepSeek, 通义千问, Claude, Ollama | Gemini(免费额度) | ✅ Gemini |
| **行情数据** | AkShare, Tushare, Pytdx, Baostock, YFinance, Longbridge | AkShare(免费) | ✅ AkShare |
| **新闻搜索** | Tavily, Anspire, SerpAPI, Bocha, Brave, MiniMax | Tavily | ⚠️ 有免费额度 |
| **推送渠道** | 企业微信, 飞书, Telegram, Discord, Slack, 邮件 | Telegram/飞书 | ✅ 均有免费方案 |
| **部署方式** | GitHub Actions, Docker, 本地运行 | GitHub Actions | ✅ GitHub免费额度 |

#### 决策仪表盘报告格式

```
📊 股票智能分析日报
━━━━━━━━━━━━━━━━━━━

🔴 核心结论: [一句话核心判断]

📈 技术面分析:
  - 当前价格与MA5/MA10/MA20关系
  - 成交量变化趋势
  - MACD/RSI等技术指标状态
  - 乖离率(关键买卖信号)
  - 多头/空头排列判断

💰 筹码分布:
  - 北向资金流向
  - 融资融券变化

📰 舆情情报:
  - 相关新闻语义分析
  - 市场情绪指数

🎯 操作建议:
  - 操作方向: 买入/观望/卖出
  - 精确买入价: ¥xxx.xx
  - 止损价: ¥xxx.xx
  - 目标价: ¥xxx.xx
  - 操作检查清单

📊 大盘复盘:
  - 市场概览
  - 板块涨跌排行
  - 北向资金总体流向
```

#### 关键可复用设计模式

1. **多数据源适配器模式**: 每个行情源通过统一接口适配, 支持自动降级
2. **长桥优先策略**: 美股/港股优先使用 Longbridge, 回退到 YFinance
3. **提示词工程化**: 通过 SKILL.md + CLAUDE.md 标准化 AI 分析流程
4. **零成本自动化**: GitHub Actions 定时触发 + Gemini 免费额度
5. **12种策略内建**: 支持多轮策略问答, Web/Bot/API 三端通用

#### 对 Skill 设计的启示

- **必须包含**: SKILL.md + CLAUDE.md/AGENTS.md 的 Agent 上下文配置
- **数据层抽象**: 至少支持 2 个行情数据源做容灾
- **报告结构化**: 三段式(表现/风险/展望)或决策仪表盘格式
- **推送多渠道**: 至少支持 Telegram + 一种国内渠道(飞书/企业微信)
- **零成本优先**: 优先使用免费 API 和 GitHub Actions

---

### 1.2 tel9980/ai_news — AI新闻+板块影响分析

**仓库**: https://github.com/tel9980/ai_news
**状态**: 31 commits, 核心作者: tel9980/hanshousang
**定位**: AI驱动的新闻收集与A股板块影响分析系统

#### 核心流程

```
中国新闻网财经RSS → 新闻抓取 → DeepSeek AI分析 → 0-100评分 → 邮件报告
                                              ↓
                              新闻→板块影响映射(语义理解)
```

#### 技术特点

| 维度 | 实现方式 |
|------|---------|
| **新闻源** | 中国新闻网 财经RSS(权威性高) |
| **AI模型** | DeepSeek 思考模型(最新版支持自驱搜索) |
| **评分机制** | 0-100 分, 基于新闻重要性和市场影响 |
| **并发处理** | 异步/多线程, 性能提升 3-10 倍 |
| **推送方式** | QQ邮箱, 早上8点定时发送 |
| **运行方式** | GitHub Actions 定时触发 |
| **板块映射** | AI 语义理解, 自动识别新闻影响的板块 |

#### 关键可复用设计

- **RSS 作为权威新闻源**: 避免爬虫被封, 数据稳定
- **0-100评分体系**: 标准化新闻影响力度量
- **早8点定时**: 覆盖开盘前信息需求
- **自驱搜索**: 支持 AI 主动搜索补充信息

#### 相关项目(同一作者)

| 项目 | 说明 |
|------|------|
| tel9980/Agu-analysis | A股市场分析系统(更早版本) |
| tel9980/AI-Fund-Master | AI基金大师, 12位投资大师理念集成 |
| tel9980/Wyckoff-Analysis | 威科夫分析法, 292 commits, 较活跃 |
| tel9980/a-stock-picker | OpenClaw Skill: A股选股推送助手(最新) |
| tel9980/USTCB | A股财经新闻日报, RSS→QQ邮箱 |

---

### 1.3 orz-ai/hot_news — 多平台热榜API

**仓库**: https://github.com/orz-ai/hot_news
**状态**: 56 commits, 活跃维护
**定位**: 每日热点新闻 API, 多平台实时热点聚合

#### 技术架构

```
FastAPI REST API
├── 定时爬虫(每30分钟刷新)
├── 多平台热榜采集
├── JSON/RSS 双格式输出
└── Telegram Bot 推送(tg_bot.py)
```

#### API 结构(推断)

```
GET /api/all          → 所有平台热榜汇总
GET /api/{platform}   → 单个平台热榜
  e.g. /api/zhihu, /api/weibo, /api/douyin, /api/bilibili...
```

#### 返回字段(典型)

```json
{
  "platform": "zhihu",
  "update_time": "2026-06-19T10:30:00",
  "items": [
    {
      "title": "热榜标题",
      "url": "原文链接",
      "hot_score": 热度值,
      "rank": 排名
    }
  ]
}
```

#### 关键价值

- **30分钟刷新**: 适合财经信息的时效性需求
- **统一API格式**: 一次调用获取多平台热点
- **Telegram Bot**: 自带推送能力
- **轻量部署**: FastAPI + 少量依赖

#### 参考: 类似项目 TrendRadar

**仓库**: sansan0/TrendRadar (33K+ stars!)

| 维度 | TrendRadar |
|------|-----------|
| 平台数 | 35个平台(抖音、知乎、B站、微博、华尔街见闻、财联社等) |
| 技术 | MCP协议, 支持自然语言分析 |
| 分析工具 | 趋势追踪、情感分析、相似检索等13种 |
| 推送 | 企业微信/个人微信/飞书/钉钉/Telegram/邮件等9种 |
| 特色 | DocMemory Engine, 30秒部署, 无需编程 |

---

### 1.4 frosenwind/capitalfarmer — 东方财富API Python封装

**仓库**: https://github.com/frosenwind/capitalfarmer
**状态**: 10 commits, 轻量工具库
**定位**: 解析东方财富网的API, 包装成Python库

#### API 模块列表

| 模块文件 | 功能 | 说明 |
|---------|------|------|
| `quotation.py` | 交易行情数据 | 实时行情、分钟K线、日K线 |
| `capitalflow.py` | 资金流向 | 主力资金、北向资金 |
| `finance.py` | 财务数据 | 财务报表、估值指标 |
| `longhu.py` | 龙虎榜 | 龙虎榜数据 |
| `margintrade.py` | 融资融券 | 两融数据 |
| `hgst.py` | 沪深港通 | 港股通持股 |
| `network.py` | 网络请求 | 底层HTTP封装 |

#### 关键API函数

```python
import capitalfarmer as cf

# 分时成交数据(每3秒)
cf.time_sharing_trans_3s(code, pos, lang)  # 最近pos个3秒区间
cf.time_sharing_trans(code, lang)           # 当日全部分时

# 行情数据
cf.recent_minutely(code, ndays, lang)       # 近N日分钟K线

# (其他函数从模块名可推断)
# cf.quotation.xxx()     行情相关
# cf.capitalflow.xxx()   资金流向
# cf.finance.xxx()       财务数据
# cf.longhu.xxx()        龙虎榜
# cf.margintrade.xxx()   融资融券
# cf.hgst.xxx()          沪深港通
```

#### 优缺点分析

| 优点 | 缺点 |
|------|------|
| 东方财富数据全面免费 | 10次commit, 维护不活跃 |
| API封装简洁 | 无文档, 需读源码 |
| 轻量无依赖 | 东方财富API可能变化 |
| 覆盖常用数据场景 | 缺乏错误处理 |

#### 使用建议

适合作为**东方财富数据源的参考实现**, 直接 fork 并增强后使用, 或参考其 API 调用方式自行封装。

---

### 1.5 pigfamily/Ashare — 新浪+腾讯双核心行情

**仓库**: https://github.com/pigfamily/Ashare
**状态**: 34 commits, 稳定维护
**定位**: 中国股市A股行情实时数据最简封装API

#### 核心设计

```
Ashare.py (单文件, 核心)
├── 新浪数据核心: hq.sinajs.cn
├── 腾讯数据核心: qt.gtimg.cn
├── 自动故障切换: 新浪不可用时 → 腾讯
└── MyTT.py: 技术指标计算(MA, MACD, KDJ, RSI等)
```

#### 核心API

```python
from Ashare import *

# 一行代码获取行情, 返回 DataFrame
df = get_price('600519', frequency='1d', count=10)
df = get_price('000001', frequency='1m', count=60)  # 分钟线
df = get_price('sh600519', frequency='1d', count=100)  # 历史日K

# 证券代码兼容: 通达信(600519) / 同花顺(SH600519) / 聚宽(600519.XSHG)
# frequency: '1d'(日线), '1m'(1分钟), '5m'(5分钟), '15m', '30m', '60m'
```

#### 返回数据结构

```
DataFrame columns:
  open, high, low, close, volume, amount, ...
```

#### 优缺点

| 优点 | 缺点 |
|------|------|
| 极简, 单文件即可使用 | 仅支持A股 |
| 双核心自动容灾 | 新浪/腾讯接口非官方, 可能变化 |
| 代码兼容性强(通达信/同花顺/聚宽) | 无WebSocket实时推送 |
| 返回标准DataFrame | 频率有限(最快1分钟) |
| 内置 MyTT 技术指标库 | 无历史深度数据 |

#### 作为备用行情源的可行性

**推荐作为第二行情源**, 原因:
1. 新浪/腾讯接口直接HTTP访问, 无认证, 零成本
2. 双核心自动切换, 可用性高
3. 与 daily_stock_analysis 的 AkShare 接口互补(不同数据源)
4. 但需注意: 非官方API, 可能被限流或接口变更

---

## 二、可复用的架构模式总结

### 2.1 多数据源适配器模式(Adapter Pattern)

**来源**: DSA (daily_stock_analysis)
**模式**: 每个行情数据源实现统一接口, 支持优先级配置和自动降级

```python
# 概念代码
class DataProvider:
    def __init__(self, providers: List[BaseProvider]):
        self.providers = sorted(providers, key=lambda p: p.priority)

    def get_realtime_quote(self, code: str) -> Quote:
        for provider in self.providers:
            try:
                return provider.fetch(code)
            except Exception:
                continue  # 自动降级到下一数据源
        raise AllProvidersFailed()
```

### 2.2 新闻→板块影响映射模式

**来源**: tel9980/ai_news
**模式**: 利用 LLM 的语义理解能力, 将新闻自动映射到受影响板块

```
新闻抓取 → LLM语义分析 → {
    "score": 0-100,          // 重要度评分
    "sectors": ["新能源", "AI"],  // 影响板块
    "sentiment": "利好/利空/中性",
    "summary": "一句话摘要",
    "key_points": ["要点1", "要点2"]
}
```

### 2.3 热榜聚合+筛选模式

**来源**: orz-ai/hot_news + TrendRadar
**模式**: 多平台热点统一采集 → 关键词过滤 → 相关性排序

```
┌─────────────────────────────────────────────────┐
│              热榜聚合层                          │
│  知乎 │ 微博 │ 抖音 │ B站 │ 华尔街见闻 │ 财联社 │
└──────────────┬──────────────────────────────────┘
               ↓
        关键词过滤(如: AI, 新能源, 芯片)
               ↓
        去重 + 相关性排序
               ↓
        结构化输出 → LLM 分析 → 报告
```

### 2.4 决策仪表盘报告模式

**来源**: DSA
**模式**: 结构化的分析报告, 包含明确的买卖价位

```
报告结构:
  1. 一句话核心结论
  2. 技术面分析(均线/成交量/MACD/乖离率)
  3. 资金面分析(北向资金/融资融券)
  4. 情绪面分析(新闻舆情)
  5. 操作建议(方向+精确价位+止损+目标)
  6. 大盘复盘(市场概览+板块排行)
```

### 2.5 零成本自动化模式

**来源**: DSA + tel9980/ai_news
**模式**: GitHub Actions 定时触发 + 免费API

```yaml
# .github/workflows/daily_analysis.yml
on:
  schedule:
    - cron: '0 22 * * 1-5'  # 每个交易日下午收盘后(北京时间)
  workflow_dispatch:          # 支持手动触发
```

---

## 三、推荐数据源优先级排序

### 3.1 行情数据源

| 优先级 | 数据源 | 来源项目 | 理由 |
|--------|--------|---------|------|
| 🥇 第一 | **AkShare** | DSA | 免费,覆盖A股全量, 活跃维护, pip安装 |
| 🥈 第二 | **新浪/腾讯 HTTP** | Ashare | 零认证, 双核心容灾, 极简接入 |
| 🥉 第三 | **东方财富 API** | capitalfarmer | 数据最全面(含资金流向/龙虎榜) |
| 备选 | **Tushare** | DSA | 数据质量高, 需注册, 有积分限制 |
| 备选 | **Baostock** | DSA | 免费, 适合历史数据 |
| 备选 | **Pytdx** | DSA | 通达信协议, 实时性好 |

### 3.2 新闻/舆情数据源

| 优先级 | 数据源 | 来源项目 | 理由 |
|--------|--------|---------|------|
| 🥇 第一 | **财联社热榜** | TrendRadar | 最专业的财经快讯平台 |
| 🥈 第二 | **华尔街见闻** | TrendRadar | 深度财经分析 |
| 🥉 第三 | **中国新闻网 RSS** | ai_news | 权威性高, RSS稳定 |
| 第四 | **知乎/微博热榜** | hot_news/TrendRadar | 舆情风向标 |
| 第五 | **Tavily Search** | DSA | AI搜索引擎, 有免费额度 |
| 补充 | **东方财富新闻** | capitalfarmer | 财经专业新闻 |

### 3.3 AI 模型选择

| 优先级 | 模型 | 理由 |
|--------|------|------|
| 🥇 第一 | **DeepSeek** | 国产, 便宜, 中文理解能力强, 有思考模式(ai_news验证) |
| 🥈 第二 | **Gemini** | Google免费额度, 多模态, DSA主力 |
| 🥉 第三 | **通义千问** | 阿里系, 中文好, 有免费额度 |
| 备选 | **Claude** | 分析质量高, API成本较高 |
| 本地 | **Ollama** | 完全私有化, 适合敏感数据 |

---

## 四、对 Skill 设计的具体建议

### 4.1 Skill 文件结构(参考 DSA)

```
skills/a-share-analysis/
├── SKILL.md            # Skill 入口定义
├── CLAUDE.md           # Claude Code 上下文(项目结构/规范)
├── AGENTS.md           # Agent 开发规范(可选)
├── data_provider/      # 行情数据适配
│   ├── __init__.py
│   ├── akshare.py      # AkShare 适配器
│   └── ashare.py       # 新浪/腾讯 适配器(备用)
├── news/               # 新闻采集模块
│   ├── __init__.py
│   ├── hot_news.py     # 热榜聚合
│   ├── rss_feed.py     # RSS源
│   └── sector_map.py   # 新闻→板块映射
├── analyzer/           # 分析引擎
│   ├── __init__.py
│   ├── technical.py    # 技术面分析
│   ├── sentiment.py    # 舆情分析
│   └── decision.py     # 决策生成
├── templates/          # 报告模板
│   ├── daily_report.md
│   ├── sector_report.md
│   └── alert.md
├── push/               # 推送模块
│   ├── telegram.py
│   └── feishu.py
└── scripts/
    └── run_daily.sh
```

### 4.2 SKILL.md 关键内容建议

```markdown
# A股智能分析 Skill

## 能力
- 每日定时分析自选股, 生成决策仪表盘
- 多平台热点新闻采集+板块影响分析
- 技术面/资金面/情绪面三维分析
- Telegram/飞书多渠道推送

## 数据源
- 行情: AkShare(主力) + 新浪/腾讯(备用)
- 新闻: 热榜API(财联社/华尔街见闻) + RSS
- AI: DeepSeek/Gemini

## 运行方式
- GitHub Actions 定时(交易日16:00)
- 支持手动触发
- 零成本运行

## 报告格式
[定义决策仪表盘格式...]
```

### 4.3 架构设计原则

1. **适配器优先**: 每个外部依赖都通过适配器接入, 方便切换
2. **二层容灾**: 主要数据源 + 备用数据源, 自动降级
3. **提示词外置**: 分析Prompt放在独立的模板文件中, 方便调优
4. **增量扩展**: 先做最小可用版本(行情+推送), 逐步加新闻/复盘/策略
5. **零成本运营**: 优先使用免费API + GitHub Actions

### 4.4 分阶段实施建议

**Phase 1 (MVP)**: 
- 单只股票技术面分析 + Telegram推送
- 数据源: AkShare
- AI: DeepSeek
- 部署: GitHub Actions

**Phase 2 (增强)**:
- 加入新闻采集(热榜API)
- 新闻→板块影响分析
- 多只自选股批量分析
- 决策仪表盘完整版

**Phase 3 (完善)**:
- 大盘复盘
- 资金流向(北向资金)
- 多策略支持
- Web UI + API
- 多渠道推送(飞书/企业微信/邮件)

---

## 五、关键发现总结

### 5.1 已验证的可行性

- ✅ **零成本运行**: DSA 项目证明了完全可以用 GitHub Actions + 免费API 实现
- ✅ **AI分析质量**: 三段式报告(表现/风险/展望)已被大量用户验证可用
- ✅ **多数据源容灾**: AkShare + 新浪/腾讯双核心的容灾方案成熟
- ✅ **热榜聚合**: TrendRadar 33K+ stars 证明这类需求巨大

### 5.2 需要注意的风险

- ⚠️ 新浪/腾讯接口非官方, 可能随时变化(AkShare 更可靠)
- ⚠️ 东方财富API同样非官方, capitalfarmer 长期未更新
- ⚠️ 免费API有额度限制, 需做好限流和缓存
- ⚠️ AI分析的金融建议仅供参考, 需要免责声明

### 5.3 推荐技术组合

```
行情数据:  AkShare (主力) + Ashare风格接口 (备用)
新闻采集:  热榜聚合API + 中国新闻网RSS
AI引擎:   DeepSeek (主力) + Gemini (备用)
推送:     Telegram (主力) + 飞书 (备用)
部署:     GitHub Actions (免费定时) + Docker (本地开发)
```

---

*报告完成。供天枢(Skill Workshop)设计参考。*
