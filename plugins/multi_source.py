"""多源数据引擎 — 东方财富/新浪/腾讯三源自动降级"""
import requests
import json
import time
import random
from datetime import datetime
from typing import Optional, List, Dict

class MultiSourceData:
    """统一数据接口，自动降级：东财 → 新浪 → 腾讯"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Accept': '*/*',
        })
        self._source_status = {'eastmoney': 'unknown', 'sina': 'unknown', 'tencent': 'unknown'}
    
    def _try_sources(self, fetchers: list) -> tuple:
        """按优先级尝试多个数据源，返回 (source_name, data)"""
        for source_name, fetcher in fetchers:
            try:
                data = fetcher()
                if data is not None and not (isinstance(data, (list, dict)) and len(data) == 0):
                    self._source_status[source_name] = 'ok'
                    return source_name, data
                else:
                    self._source_status[source_name] = 'empty'
            except Exception as e:
                self._source_status[source_name] = f'error: {str(e)[:50]}'
                continue
        return None, None
    
    # ── 指数行情 ──
    def get_indices(self) -> dict:
        """获取上证/深证/创业板/科创50等指数"""
        fetchers = [
            ('sina', self._indices_sina),
            ('tencent', self._indices_tencent),
        ]
        source, data = self._try_sources(fetchers)
        return {'source': source, 'data': data, 'time': datetime.now().isoformat()}
    
    def _indices_sina(self) -> dict:
        """新浪指数源"""
        codes = 'sh000001,sz399001,sz399006,sh000688,sh000016,sh000905'
        r = self.session.get(
            f'https://hq.sinajs.cn/list={codes}',
            headers={'Referer': 'https://finance.sina.com.cn'},
            timeout=10
        )
        result = {}
        names_map = {'sh000001':'上证指数','sz399001':'深证成指','sz399006':'创业板指',
                     'sh000688':'科创50','sh000016':'上证50','sh000905':'中证500'}
        for line in r.text.strip().split('\n'):
            parts = line.split('=')
            if len(parts) < 2: continue
            code = parts[0].split('_')[-1]
            data = parts[1].strip('";\n"')
            fields = data.split(',')
            if len(fields) < 10: continue
            name = names_map.get(code, fields[0])
            pre_close = float(fields[2]) if fields[2] else 0
            price = float(fields[3]) if fields[3] else 0
            vol = float(fields[8]) / 1e8 if fields[8] else 0
            pct = (price - pre_close) / pre_close * 100 if pre_close else 0
            result[code] = {
                'name': name, 'price': price, 'pre_close': pre_close,
                'pct': round(pct, 2), 'volume_yi': round(vol, 0)
            }
        return result
    
    def _indices_tencent(self) -> dict:
        """腾讯指数源"""
        codes = 's_sh000001,s_sz399001,s_sz399006,s_sh000688,s_sh000016,s_sh000905'
        r = self.session.get(f'https://qt.gtimg.cn/q={codes}', timeout=10)
        result = {}
        names_map = {'sh000001':'上证指数','sz399001':'深证成指','sz399006':'创业板指',
                     'sh000688':'科创50','sh000016':'上证50','sh000905':'中证500'}
        for line in r.text.strip().split(';'):
            if '~' not in line: continue
            f = line.split('~')
            if len(f) < 35: continue
            code = f[2]
            name = names_map.get(code, f[1])
            price = float(f[3]) if f[3] else 0
            pre = float(f[4]) if f[4] else 0
            pct = float(f[32]) if f[32] else 0
            result[code] = {
                'name': name, 'price': price, 'pre_close': pre,
                'pct': round(pct, 2), 'volume_yi': 0
            }
        return result
    
    # ── 个股实时行情 ──
    def get_stock(self, code: str) -> dict:
        """获取单只股票实时行情"""
        # 判断 sh/sz 前缀
        prefix = 'sh' if code.startswith('6') or code.startswith('688') else 'sz'
        if code.startswith('8') or code.startswith('4'):
            prefix = 'bj'
        
        fetchers = [
            ('sina', lambda: self._stock_sina(f'{prefix}{code}')),
            ('tencent', lambda: self._stock_tencent(f'{prefix}{code}')),
        ]
        source, data = self._try_sources(fetchers)
        return {'source': source, 'data': data}
    
    def batch_stocks(self, codes: List[str]) -> dict:
        """批量获取多只股票"""
        sina_codes = []
        for code in codes:
            prefix = 'sh' if code.startswith('6') or code.startswith('688') else 'sz'
            sina_codes.append(f'{prefix}{code}')
        
        try:
            return self._batch_sina(sina_codes)
        except:
            return {}
    
    def _stock_sina(self, sina_code: str) -> dict:
        r = self.session.get(
            f'https://hq.sinajs.cn/list={sina_code}',
            headers={'Referer': 'https://finance.sina.com.cn'},
            timeout=10
        )
        data = r.text.split('"')[1].split(',')
        if len(data) < 10: return {}
        return {
            'name': data[0], 'open': float(data[1]), 'pre_close': float(data[2]),
            'price': float(data[3]), 'high': float(data[4]), 'low': float(data[5]),
            'volume': float(data[8]), 'amount': float(data[9]),
        }
    
    def _stock_tencent(self, tq_code: str) -> dict:
        r = self.session.get(f'https://qt.gtimg.cn/q={tq_code}', timeout=10)
        f = r.text.split('~')
        if len(f) < 35: return {}
        return {
            'name': f[1], 'open': float(f[5]), 'pre_close': float(f[4]),
            'price': float(f[3]), 'high': float(f[33]), 'low': float(f[34]),
            'volume': float(f[6]), 'amount': float(f[37]),
        }
    
    def _batch_sina(self, sina_codes: List[str]) -> dict:
        codes_str = ','.join(sina_codes)
        r = self.session.get(
            f'https://hq.sinajs.cn/list={codes_str}',
            headers={'Referer': 'https://finance.sina.com.cn'},
            timeout=15
        )
        result = {}
        for line in r.text.strip().split('\n'):
            if '=' not in line: continue
            parts = line.split('=')
            code = parts[0].split('_')[-1]
            data = parts[1].strip('";\n"').split(',')
            if len(data) < 10: continue
            result[code[2:]] = {
                'name': data[0], 'price': float(data[3]) if data[3] else 0,
                'pre_close': float(data[2]) if data[2] else 0,
                'pct': round((float(data[3]) - float(data[2])) / float(data[2]) * 100, 2) if data[2] else 0,
            }
        return result
    
    # ── 历史K线 ──
    def get_hist(self, code: str, days: int = 90) -> list:
        """获取历史K线数据"""
        try:
            return self._hist_akshare(code, days)
        except:
            try:
                return self._hist_tencent(code, days)
            except:
                return []
    
    def _hist_akshare(self, code: str, days: int) -> list:
        import akshare as ak
        df = ak.stock_zh_a_hist(symbol=code, period='daily', 
                                start_date=(datetime.now().replace(year=datetime.now().year-1)).strftime('%Y%m%d'),
                                adjust='qfq')
        df = df.tail(days)
        return df.to_dict('records')
    
    def _hist_tencent(self, code: str, days: int) -> list:
        prefix = 'sh' if code.startswith('6') else 'sz'
        r = self.session.get(
            f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={prefix}{code},day,,,{days},qfq',
            timeout=10
        )
        data = r.json().get('data', {}).get(f'{prefix}{code}', {})
        klines = data.get('qfqday', data.get('day', []))
        return [{'date': k[0], 'open': float(k[1]), 'close': float(k[2]),
                 'high': float(k[3]), 'low': float(k[4]), 'volume': float(k[5])}
                for k in klines[-days:]]
    
    def source_status(self) -> dict:
        return self._source_status


# 全局单例
msd = MultiSourceData()
