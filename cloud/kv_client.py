"""云端 KV 客户端 — Cloudflare KV / 本地文件 双后端

一份代码, 两种宿主(满足"同时支持本地拉数据"):
  - 配了 Cloudflare 凭据(环境变量) → 走 Cloudflare KV REST API
  - 没配 → 本地文件后端(cloud/_kvstore/*.json), dev/本地 dashboard 直接可用

盘前(GH Actions)、竞价/盘中(VPS 或本地常驻)都用同一个 client 推数据;
dashboard 通过 Cloudflare Pages Function(绑定 KV)或本地 HTTP 读同样的键。

环境变量(生产):
  CF_ACCOUNT_ID        Cloudflare 账户 ID
  CF_KV_NAMESPACE_ID   KV 命名空间 ID
  CF_API_TOKEN         API Token(需 KV 写权限) —— 只放 env/secret, 绝不入库
  KV_BACKEND           可选: 强制 "local" / "cloudflare"
  KV_LOCAL_DIR         可选: 本地后端目录(默认 cloud/_kvstore)

键约定见 docs/design/kv-storage.md。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── 键名约定 ──────────────────────────────────────────────
KEY_PRED_LATEST = "pred:latest"      # 今日完整预测记录(盘前写, 收盘更新评估)
KEY_LIVE_LATEST = "live:latest"      # 竞价/盘中高频小 blob(30s/1h 覆写)
KEY_HEARTBEAT = "meta:heartbeat"     # 死活灯 {last_update, phase}
KEY_DATES = "pred:dates"             # 历史日期索引 []


def key_pred_date(date: str) -> str:
    return f"pred:{date}"


# ══════════════════════════════════════════════════════════
#  后端
# ══════════════════════════════════════════════════════════

class LocalKV:
    """本地文件后端 —— 键名 sanitize 后存为 JSON 文件。"""

    def __init__(self, base_dir: Optional[str] = None):
        self.base = Path(base_dir or os.environ.get(
            "KV_LOCAL_DIR", str(PROJECT_ROOT / "cloud" / "_kvstore")))
        self.base.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        safe = key.replace(":", "__").replace("/", "_")
        return self.base / f"{safe}.json"

    def put(self, key: str, value: Any) -> None:
        p = self._path(key)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(p)

    def get(self, key: str) -> Optional[Any]:
        p = self._path(key)
        if not p.is_file():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    @property
    def name(self) -> str:
        return f"local({self.base})"


class CloudflareKV:
    """Cloudflare KV REST 后端。"""

    def __init__(self, account_id: str, namespace_id: str, api_token: str,
                 timeout: int = 10):
        self.account_id = account_id
        self.namespace_id = namespace_id
        self.api_token = api_token
        self.timeout = timeout
        self._base = (f"https://api.cloudflare.com/client/v4/accounts/"
                      f"{account_id}/storage/kv/namespaces/{namespace_id}")

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_token}"}

    def put(self, key: str, value: Any) -> None:
        import requests
        url = f"{self._base}/values/{quote(key, safe='')}"
        resp = requests.put(
            url, headers=self._headers(),
            data=json.dumps(value, ensure_ascii=False).encode("utf-8"),
            timeout=self.timeout)
        resp.raise_for_status()

    def get(self, key: str) -> Optional[Any]:
        import requests
        url = f"{self._base}/values/{quote(key, safe='')}"
        resp = requests.get(url, headers=self._headers(), timeout=self.timeout)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        try:
            return resp.json()
        except ValueError:
            return resp.text

    @property
    def name(self) -> str:
        return f"cloudflare(ns={self.namespace_id[:8]}…)"


def _make_backend():
    """按环境变量选择后端。缺凭据则回退本地。"""
    forced = os.environ.get("KV_BACKEND", "").lower()
    acct = os.environ.get("CF_ACCOUNT_ID")
    ns = os.environ.get("CF_KV_NAMESPACE_ID")
    token = os.environ.get("CF_API_TOKEN")

    if forced == "local":
        return LocalKV()
    if forced == "cloudflare" or (acct and ns and token):
        if not (acct and ns and token):
            raise RuntimeError(
                "KV_BACKEND=cloudflare 但缺少 CF_ACCOUNT_ID/CF_KV_NAMESPACE_ID/CF_API_TOKEN")
        return CloudflareKV(acct, ns, token)
    return LocalKV()


# ══════════════════════════════════════════════════════════
#  语义层 —— 业务只调这一层
# ══════════════════════════════════════════════════════════

class PredictionKV:
    """把预测/实时/心跳的读写封装成语义方法。"""

    def __init__(self, backend=None):
        self.backend = backend or _make_backend()

    # ── 写 ──
    def write_prediction(self, date: str, kv_payload: dict) -> None:
        """盘前: 写今日预测(latest + 按日归档 + 更新日期索引)。"""
        self.backend.put(KEY_PRED_LATEST, kv_payload)
        self.backend.put(key_pred_date(date), kv_payload)
        dates = self.backend.get(KEY_DATES) or []
        if date not in dates:
            dates = sorted(set(dates) | {date})
            self.backend.put(KEY_DATES, dates)
        self.write_heartbeat(phase="premarket")

    def write_live(self, live_blob: dict, phase: str = "auction") -> None:
        """竞价/盘中: 覆写高频小 blob + 心跳。30s/1h 只动这个, 不碰大预测记录。"""
        self.backend.put(KEY_LIVE_LATEST, live_blob)
        self.write_heartbeat(phase=phase)

    def write_heartbeat(self, phase: str = "") -> None:
        self.backend.put(KEY_HEARTBEAT, {
            "last_update": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "epoch": int(time.time()),
            "phase": phase,
        })

    # ── 读(dashboard/复核用) ──
    def read_prediction(self, date: Optional[str] = None) -> Optional[dict]:
        return self.backend.get(key_pred_date(date) if date else KEY_PRED_LATEST)

    def read_live(self) -> Optional[dict]:
        return self.backend.get(KEY_LIVE_LATEST)

    def read_heartbeat(self) -> Optional[dict]:
        return self.backend.get(KEY_HEARTBEAT)

    def list_dates(self) -> List[str]:
        return self.backend.get(KEY_DATES) or []

    @property
    def backend_name(self) -> str:
        return self.backend.name
