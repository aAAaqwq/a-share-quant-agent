# 部署记录 — Cloudflare 实时看板

> 状态: ✅ Worker 已上线(2026-07-02)
> **看板地址: https://a-share-dashboard.2067089451.workers.dev**

## 已部署资源

| 资源 | 值 | 备注 |
|------|-----|------|
| Cloudflare 账户 | `2067089451@qq.com` (ID `18d49872…664d5`) | OAuth 登录 |
| KV Namespace | `ASHARE_KV` (ID `bd504a3293d84c51beeb62c2fa126c4a`) | 预测/实时/心跳存储 |
| Worker | `a-share-dashboard` | 看板页 + KV 读 API |
| 看板 URL | https://a-share-dashboard.2067089451.workers.dev | workers.dev 免费子域 |

## 架构

```
Python 写入 (盘前/竞价/收盘)          Cloudflare 边缘
  cloud/kv_client.py ── REST 写 ──►  KV: ASHARE_KV
                                       ▲
                                       │ KV binding(读, 无需 token)
  浏览器 ── GET / ──► Worker(a-share-dashboard) ──┘
           GET /api/state ──► 聚合 pred:latest / live:latest / meta:heartbeat → JSON
```

- **Worker**(`worker/src/index.js`): `GET /` 返回内嵌看板 HTML;`GET /api/state`
  用 KV binding 读三个键聚合成 JSON。前端每 15s 轮询,顶部死活灯(心跳 >60s 变红)。
- **KV binding**(读)无需凭据,部署时绑定;**Python 写**走 REST 需 API Token。

## 键与写入方(见 kv-storage.md)

| 键 | 写入方 | 频率 |
|----|--------|------|
| `pred:latest` / `pred:{date}` / `pred:dates` | 盘前 GH Actions + 收盘复核 | 低频 |
| `live:latest` / `meta:heartbeat` | 竞价/盘中常驻脚本(VPS/本地) | 竞价 30s / 盘中 1h |

## 重新部署 / 更新看板

```bash
cd worker
npx wrangler deploy          # 改 src/index.js 后重新部署
```

## 手动写/读 KV(调试)

```bash
NS=bd504a3293d84c51beeb62c2fa126c4a
npx wrangler kv key put --namespace-id $NS "pred:latest" --path pred.json --remote
npx wrangler kv key get --namespace-id $NS "pred:latest" --remote
```

## 生产化 Python 写入(待 Phase ⑤)

Python 侧 `cloud/kv_client.py` 走 REST,需要一个**最小权限 API Token**(仅
`ASHARE_KV` 的 KV 写),放到:
- GitHub Actions → repo Secrets: `CF_ACCOUNT_ID` / `CF_KV_NAMESPACE_ID` / `CF_API_TOKEN`
- VPS/本地 → `.env`(已 gitignore)

创建 Token: Cloudflare 控制台 → My Profile → API Tokens → Create Token →
模板 "Edit Cloudflare Workers KV Storage" → 限定到本 namespace。

```bash
export CF_ACCOUNT_ID=18d4987277f33a09ba9a7b850fc664d5
export CF_KV_NAMESPACE_ID=bd504a3293d84c51beeb62c2fa126c4a
export CF_API_TOKEN=<你创建的最小权限 token>
# 之后 PredictionKV() 自动走 Cloudflare 后端
```

## 注意

- workers.dev 域对**非浏览器 UA**(curl/脚本默认 UA)可能返回 403(Cloudflare bot
  拦截),浏览器访问正常。脚本探活加浏览器 UA 即可。
- KV 最终一致(全球传播 ~60s),个人看板单区域读通常秒级。
- 免费额度: 1000 写/日、100k 读/日 —— 实际约 57 写/日,完全免费。
