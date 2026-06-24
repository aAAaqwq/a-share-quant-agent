"""财联社电报 — 支持多种获取方式"""
import aiohttp
from .base import NewsItem, NewsSourcePlugin
from datetime import datetime


class ClsFlashSource(NewsSourcePlugin):
    name = "财联社电报"
    source_id = "cls"
    refresh_interval = 60  # 最快1分钟刷新

    API_URL = "https://www.cls.cn/v1/roll/get_roll_list"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        "Referer": "https://www.cls.cn/telegraph",
    }

    async def fetch(self, count=50, **kwargs):
        """获取财联社电报 — 先尝试API，失败则降级"""
        items = await self._fetch_api(count)
        if not items:
            items = await self._fetch_via_curl_cffi(count)
        return items

    async def _fetch_api(self, count):
        """直接API调用（可能需要签名）"""
        params = {
            "app": "CailianpressWeb",
            "os": "web",
            "rn": count,
            "sv": "8.4.6",
        }
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(
                    self.API_URL,
                    params=params,
                    headers=self.HEADERS,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    data = await resp.json()
            except Exception as e:
                print(f"[cls] API error: {e}")
                return []

        if data.get("errno") != "0" and "data" not in data:
            print(f"[cls] API sign required: {data.get('msg', '')}")
            return []

        return self._parse_items(data)

    async def _fetch_via_curl_cffi(self, count):
        """使用 curl_cffi 模拟浏览器绕过WAF"""
        try:
            from curl_cffi import requests as curl_requests
        except ImportError:
            print("[cls] curl_cffi not available")
            return []

        params = {
            "app": "CailianpressWeb",
            "os": "web",
            "rn": count,
            "sv": "8.4.6",
        }
        try:
            s = curl_requests.Session()
            s.get("https://www.cls.cn/telegraph", impersonate="chrome120", timeout=10)
            r = s.get(
                self.API_URL,
                params=params,
                impersonate="chrome120",
                headers={"Referer": "https://www.cls.cn/telegraph"},
                timeout=10,
            )
            data = r.json()
            if data.get("errno") != "0" and "data" not in data:
                print(f"[cls] curl_cffi sign required: {data.get('msg', '')}")
                return []
            return self._parse_items(data)
        except Exception as e:
            print(f"[cls] curl_cffi error: {e}")
            return []

    def _parse_items(self, data):
        items = []
        for item in data.get("data", {}).get("roll_data", []):
            ctime = item.get("ctime", 0)
            items.append(
                NewsItem(
                    source=self.source_id,
                    title=item.get("title", ""),
                    content=item.get("brief", item.get("content", "")),
                    url=f"https://www.cls.cn/detail/{item.get('id', '')}",
                    timestamp=datetime.fromtimestamp(ctime) if ctime else None,
                    hot_score=float(item.get("level", 0)) * 20
                    if item.get("level")
                    else 0,
                    tags=[item.get("subject", "")],
                )
            )
        return items
