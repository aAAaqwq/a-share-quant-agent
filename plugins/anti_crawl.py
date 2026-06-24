"""东方财富反爬绕过 — 模拟浏览器指纹"""
import requests
import time
import random
import json
from typing import Optional


class EastMoneySession:
    """带浏览器指纹的东方财富 API 会话"""

    # 真实浏览器 headers
    BROWSER_HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                       'AppleWebKit/537.36 (KHTML, like Gecko) '
                       'Chrome/125.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Referer': 'https://quote.eastmoney.com/',
        'Origin': 'https://quote.eastmoney.com',
        'Connection': 'keep-alive',
        'Sec-Ch-Ua': '"Google Chrome";v="125", "Chromium";v="125", '
                     '"Not.A/Brand";v="24"',
        'Sec-Ch-Ua-Mobile': '?0',
        'Sec-Ch-Ua-Platform': '"macOS"',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-site',
    }

    # 东方财富 API token（公开参数）
    TOKEN = 'bd1d9ddb04089700cf9c27f6f7426281'

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(self.BROWSER_HEADERS)
        self.session.trust_env = False  # 不使用系统代理
        self._last_request_time = 0
        self._min_interval = 0.5  # 最小请求间隔

    def _wait(self):
        """随机延迟，模拟人工"""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed + random.uniform(0.1, 0.5))
        self._last_request_time = time.time()

    def get(self, url: str, params: dict = None,
            timeout: int = 15) -> Optional[dict]:
        """带重试的 GET 请求"""
        max_retries = 3
        for attempt in range(max_retries):
            self._wait()
            try:
                r = self.session.get(url, params=params, timeout=timeout)
                if r.status_code == 200:
                    return r.json()
                elif r.status_code == 502:
                    # 502 = 代理问题，等待更久重试
                    time.sleep(random.uniform(2, 4))
                else:
                    return None
            except requests.exceptions.ConnectionError:
                time.sleep(random.uniform(1, 3))
            except Exception:
                if attempt == max_retries - 1:
                    return None
                time.sleep(random.uniform(1, 2))
        return None

    # ── 涨停池 ──
    def get_limit_up_pool(self, date: str = None) -> Optional[list]:
        """获取涨停池"""
        from datetime import datetime
        if date is None:
            date = datetime.now().strftime('%Y%m%d')

        url = 'https://push2ex.eastmoney.com/getTopicZTPool'
        params = {
            'ut': self.TOKEN,
            'dpt': 'wz.ztzt',
            'Pageindex': 0,
            'pagesize': 100,
            'sort': 'fbt:asc',
            'date': date,
        }
        data = self.get(url, params)
        if data and isinstance(data, dict) and 'data' in data and isinstance(data['data'], dict) and 'pool' in data['data']:
            return data['data']['pool']
        return None

    # ── 全A实时行情 ──
    def get_spot_em(self, page: int = 1,
                    size: int = 100) -> Optional[list]:
        """获取全A股实时行情（分页）"""
        url = 'https://82.push2.eastmoney.com/api/qt/clist/get'
        params = {
            'pn': page,
            'pz': size,
            'po': 1,
            'np': 1,
            'ut': self.TOKEN,
            'fltt': 2,
            'invt': 2,
            'fid': 'f3',
            'fs': 'm:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048',
            'fields': 'f2,f3,f4,f5,f6,f7,f8,f9,f12,f14,f15,f16,f17,f18',
        }
        data = self.get(url, params)
        if data and isinstance(data, dict) and 'data' in data and data['data']:
            return data['data'].get('diff', {}).get('diff', [])
        return None

    # ── 龙虎榜 ──
    def get_lhb(self, date: str = None) -> Optional[list]:
        """获取龙虎榜数据"""
        from datetime import datetime
        if date is None:
            date = datetime.now().strftime('%Y%m%d')

        url = 'https://datacenter-web.eastmoney.com/api/data/v1/get'
        params = {
            'sortColumns': 'SECURITY_CODE',
            'sortTypes': 1,
            'pageSize': 100,
            'pageNumber': 1,
            'reportName': 'RPT_DAILYBILLBOARD_DETAILS',
            'columns': 'ALL',
            'source': 'WEB',
            'client': 'WEB',
            'tradeDate': date,
        }
        data = self.get(url, params)
        if data and isinstance(data, dict) and 'result' in data and data['result']:
            return data['result'].get('data', [])
        return None

    # ── 北向资金 ──
    def get_north_flow(self) -> Optional[dict]:
        """获取北向资金流入"""
        url = 'https://push2.eastmoney.com/api/qt/kamtbs.wpt'
        params = {'fields1': 'f1,f2,f3',
                  'fields2': 'f51,f52,f53,f54,f55'}
        data = self.get(url, params)
        if data and isinstance(data, dict) and 'data' in data:
            return data['data']
        return None


# 全局单例
em = EastMoneySession()
