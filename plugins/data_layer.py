"""A股数据访问层 — 统一封装AKShare核心函数

提供带重试机制、统一错误处理的AKShare数据调用封装。
所有方法返回pandas.DataFrame或结构化dict。
"""

# DNS 修复补丁（必须在 akshare 之前导入）
from plugins.dns_fix import *  # noqa: F401,F403

import akshare as ak
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import time

# 多源容灾 + 数据校验
from plugins.multi_source import msd
from plugins.validator import validator
# 熔断器：死源自动跳过，避免反复硬捶
from plugins.data_quality import data_source_breaker


class AShareDataLayer:
    """A股数据访问层

    封装AKShare的核心数据获取函数，提供：
    - 自动重试 + 指数退避
    - 统一空DataFrame返回（失败时不抛异常）
    - 大盘快照、热点分析等高阶聚合方法
    """

    def get_indices_multi(self):
        """多源容灾获取指数（新浪→腾讯自动降级）"""
        return msd.get_indices()

    def __init__(self, retry: int = 3, delay: float = 1.0):
        """初始化数据层

        Args:
            retry: 网络错误最大重试次数
            delay: 基础退避延迟（秒），第i次重试延迟为 delay * (i+1)
        """
        self.retry = retry
        self.delay = delay

    def _call_with_retry(self, fn, *args, **kwargs):
        """带重试和指数退避的AKShare调用

        所有对外暴露的方法都应通过此方法调用AKShare API，
        确保网络抖动时能自动恢复。

        Args:
            fn: AKShare函数对象
            *args, **kwargs: 传给fn的参数

        Returns:
            fn的返回值；若全部重试失败则返回空DataFrame
        """
        fn_name = getattr(fn, '__name__', str(fn))

        # 熔断器：该源近期连续失败则直接跳过，避免对死源反复硬捶
        if not data_source_breaker.is_available(fn_name):
            print(f"[DataLayer] {fn_name} 熔断中，跳过（冷却后自动重试）")
            return pd.DataFrame()

        for attempt in range(self.retry):
            try:
                result = fn(*args, **kwargs)
                data_source_breaker.record_success(fn_name)
                return result
            except Exception as e:
                if attempt == self.retry - 1:
                    data_source_breaker.record_failure(fn_name, str(e))
                    print(
                        f"[DataLayer] {fn_name} failed after "
                        f"{self.retry} attempts: {e}"
                    )
                    return pd.DataFrame()
                wait = self.delay * (attempt + 1)
                print(f"[DataLayer] {fn_name} retry {attempt+1}/{self.retry} "
                      f"after {wait:.1f}s: {e}")
                time.sleep(wait)
        return pd.DataFrame()

    # ── 行情数据 ──────────────────────────────────────────

    def get_spot(self) -> pd.DataFrame:
        """全A股实时行情快照

        Returns:
            沪深京全部A股的实时行情DataFrame，
            包含代码、名称、最新价、涨跌幅、成交量、成交额等
        """
        return self._call_with_retry(ak.stock_zh_a_spot_em)

    def get_hist(
        self,
        symbol: str,
        period: str = 'daily',
        days: int = 60,
    ) -> pd.DataFrame:
        """个股历史K线数据

        Args:
            symbol: 股票代码，如 '000001'
            period: K线周期 ('daily'/'weekly'/'monthly')
            days: 回溯天数（会额外加10天buffer保证完整）

        Returns:
            历史行情DataFrame，含开/高/低/收/量/额
        """
        end = datetime.now().strftime('%Y%m%d')
        start = (datetime.now() - timedelta(days=days + 10)).strftime('%Y%m%d')
        return self._call_with_retry(
            ak.stock_zh_a_hist,
            symbol=symbol,
            period=period,
            start_date=start,
            end_date=end,
        )

    # ── 板块数据 ──────────────────────────────────────────

    def get_industry_boards(self) -> pd.DataFrame:
        """申万行业板块排名（含涨跌幅）

        Returns:
            行业板块DataFrame，按涨跌幅降序
        """
        return self._call_with_retry(ak.stock_board_industry_name_em)

    def get_concept_boards(self) -> pd.DataFrame:
        """概念板块排名（含涨跌幅）

        Returns:
            概念板块DataFrame，按涨跌幅降序
        """
        return self._call_with_retry(ak.stock_board_concept_name_em)

    def get_board_stocks(self, board_code: str) -> pd.DataFrame:
        """获取某板块下的成分股列表

        Args:
            board_code: 板块代码，如 'BK1111'

        Returns:
            成分股DataFrame，含代码、名称等
        """
        return self._call_with_retry(
            ak.stock_board_concept_cons_em, symbol=board_code
        )

    def get_top_n_boards(
        self, n: int = 10, board_type: str = 'concept'
    ) -> List[Dict]:
        """涨幅前N板块及成分股汇总

        Args:
            n: 返回前N个板块
            board_type: 'concept' 概念板块 / 'industry' 行业板块

        Returns:
            [{'code','name','change_pct','stock_count','stocks':[...]}, ...]
        """
        if board_type == 'concept':
            df = self.get_concept_boards()
        else:
            df = self.get_industry_boards()

        if df.empty:
            return []

        df = df.sort_values('涨跌幅', ascending=False).head(n)
        results: List[Dict] = []
        for _, row in df.iterrows():
            code = row.get('板块代码', '')
            name = row.get('板块名称', '')
            pct = row.get('涨跌幅', 0)
            stocks_df = pd.DataFrame()
            if code:
                stocks_df = self.get_board_stocks(code)
            results.append({
                'code': code,
                'name': name,
                'change_pct': float(pct),
                'stock_count': len(stocks_df),
                'stocks': (
                    stocks_df[['代码', '名称']].to_dict('records')
                    if not stocks_df.empty
                    else []
                ),
            })
        return results

    # ── 涨停 / 跌停 ──────────────────────────────────────

    def get_limit_up_pool(self, date: Optional[str] = None) -> pd.DataFrame:
        """涨停板股票池

        Args:
            date: 日期 YYYYMMDD，默认今天

        Returns:
            DataFrame，含代码、名称、封板时间、封单额等
        """
        if date is None:
            date = datetime.now().strftime('%Y%m%d')
        return self._call_with_retry(ak.stock_zt_pool_em, date=date)

    def get_limit_down_pool(self, date: Optional[str] = None) -> pd.DataFrame:
        """跌停板股票池

        Args:
            date: 日期 YYYYMMDD，默认今天

        Returns:
            DataFrame，含代码、名称、跌停价等
        """
        if date is None:
            date = datetime.now().strftime('%Y%m%d')
        return self._call_with_retry(ak.stock_zt_pool_dtgc_em, date=date)

    # ── 龙虎榜 ───────────────────────────────────────────

    def get_lhb_detail(self, date: Optional[str] = None) -> pd.DataFrame:
        """龙虎榜详情

        Args:
            date: 日期 YYYYMMDD，默认今天

        Returns:
            DataFrame，含上榜个股、营业部买卖等
        """
        if date is None:
            date = datetime.now().strftime('%Y%m%d')
        return self._call_with_retry(
            ak.stock_lhb_detail_em, start_date=date, end_date=date
        )

    # ── 资金流向 ──────────────────────────────────────────

    def get_stock_fund_flow(
        self, symbol: str, market: str = 'sh'
    ) -> pd.DataFrame:
        """个股资金流向

        Args:
            symbol: 股票代码
            market: 'sh'(上海) / 'sz'(深圳)

        Returns:
            DataFrame，含主力/超大单/大单/中单/小单净流入
        """
        return self._call_with_retry(
            ak.stock_individual_fund_flow, stock=symbol, market=market
        )

    def get_north_flow(self) -> pd.DataFrame:
        """北向资金（沪深股通）历史净流入

        注意: 东方财富自 2024-08 起停止实时披露北向资金分钟级净流入，
        原 `stock_hsgt_north_net_flow_in_em` 已从 AKShare 移除。此处改用
        `stock_hsgt_hist_em` 拉取历史日级数据（近端数值可能为空）。

        Returns:
            DataFrame，含每日北向资金净买额等字段
        """
        return self._call_with_retry(ak.stock_hsgt_hist_em, symbol="北向资金")

    # ── 全球指数 ──────────────────────────────────────────

    def get_global_indices(self) -> pd.DataFrame:
        """全球主要指数实时行情

        Returns:
            DataFrame，含道琼斯/纳斯达克/恒生/日经等
        """
        return self._call_with_retry(ak.index_global_spot_em)

    # ── 个股信息 ──────────────────────────────────────────

    def get_stock_info(self, symbol: str) -> pd.DataFrame:
        """个股F10基本信息

        Args:
            symbol: 股票代码

        Returns:
            DataFrame，含总市值/流通市值/行业/市盈率等
        """
        return self._call_with_retry(ak.stock_individual_info_em, symbol=symbol)

    # ── 大盘指标计算 ─────────────────────────────────────

    def get_market_snapshot(self) -> Dict:
        """大盘综合快照

        汇总当前市场的关键情绪指标：
        - 涨/跌/平家数
        - 涨跌比 → 市场风格
        - 成交额 → 量能判断
        - 涨停/跌停数 → 情绪判断

        Returns:
            {
                '涨家数', '跌家数', '平家数',
                '涨跌比', '成交额(亿)',
                '涨停数', '跌停数',
                '市场风格', '情绪', '量能判断',
                '时间',
            }
        """
        spot = self.get_spot()
        if spot.empty:
            return {'error': '无法获取行情数据'}

        up_count = len(spot[spot['涨跌幅'] > 0])
        down_count = len(spot[spot['涨跌幅'] < 0])
        flat_count = len(spot[spot['涨跌幅'] == 0])

        ratio = up_count / down_count if down_count > 0 else float('inf')
        total_amount = spot['成交额'].sum() / 1e8  # 转亿

        # 涨停/跌停
        today = datetime.now().strftime('%Y%m%d')
        zt = self.get_limit_up_pool(today)
        dt = self.get_limit_down_pool(today)

        # ── 风格判断 ──
        if ratio > 4:
            style = "强势多头"
        elif ratio > 2:
            style = "偏多震荡"
        elif ratio > 1:
            style = "震荡偏多"
        elif ratio > 0.67:
            style = "震荡平衡"
        elif ratio > 0.33:
            style = "偏空震荡"
        elif ratio > 0:
            style = "空头市场"
        else:
            style = "极端空头"

        # ── 情绪判断 ──
        zt_count = len(zt)
        if zt_count >= 80:
            sentiment = "🔥 情绪高涨"
        elif zt_count >= 50:
            sentiment = "😊 情绪良好"
        elif zt_count >= 30:
            sentiment = "😐 情绪一般"
        elif zt_count >= 15:
            sentiment = "😟 情绪偏弱"
        else:
            sentiment = "❄️ 情绪冰点"

        # ── 量能判断 ──
        if total_amount > 12000:
            volume = "放量"
        elif total_amount > 8000:
            volume = "正常偏多"
        elif total_amount > 5000:
            volume = "正常"
        elif total_amount > 3000:
            volume = "缩量"
        else:
            volume = "极度缩量"

        return {
            '涨家数': up_count,
            '跌家数': down_count,
            '平家数': flat_count,
            '涨跌比': round(ratio, 2),
            '成交额(亿)': round(total_amount, 0),
            '涨停数': zt_count,
            '跌停数': len(dt),
            '市场风格': style,
            '情绪': sentiment,
            '量能判断': volume,
            '时间': datetime.now().strftime('%Y-%m-%d %H:%M'),
        }

    # ── 实时主线分析 ─────────────────────────────────────

    def analyze_hot_themes(self, min_pct: float = 9.0) -> Dict:
        """涨幅>min_pct%的个股题材分布分析

        统计当前强势个股所属的概念板块，识别市场主线。

        Args:
            min_pct: 涨幅阈值，默认9.0%

        Returns:
            {
                'themes': [(板块名, 热门股数量), ...],
                'hot_stock_count': int,
                'hot_stocks': [{...}, ...],
                'analysis_time': str,
            }
        """
        spot = self.get_spot()
        if spot.empty:
            return {'error': '无法获取行情数据'}

        hot = spot[spot['涨跌幅'] > min_pct].copy()
        if hot.empty:
            return {
                'themes': [],
                'hot_stock_count': 0,
                'message': f'无涨幅>{min_pct}%个股',
                'analysis_time': datetime.now().strftime('%Y-%m-%d %H:%M'),
            }

        # 获取概念板块
        concepts = self.get_concept_boards()
        if concepts.empty:
            return {
                'themes': [],
                'hot_stock_count': len(hot),
                'message': '无法获取概念板块数据',
                'analysis_time': datetime.now().strftime('%Y-%m-%d %H:%M'),
            }

        concepts_sorted = concepts.sort_values('涨跌幅', ascending=False)

        # 统计热门股的题材分布
        from collections import Counter
        theme_counter: Counter = Counter()
        stock_theme_map: Dict[str, List[str]] = {}

        top_concepts = concepts_sorted.head(30)
        for _, stock in hot.iterrows():
            code = stock['代码']
            stock_theme_map[code] = []

        for _, board in top_concepts.iterrows():
            board_code = board.get('板块代码', '')
            board_name = board.get('板块名称', '')
            if not board_code or not board_name:
                continue
            try:
                stocks = self.get_board_stocks(board_code)
                if stocks.empty:
                    continue
                board_stock_codes = set(stocks['代码'].values)
                for code in stock_theme_map:
                    if code in board_stock_codes:
                        theme_counter[str(board_name)] += 1
                        stock_theme_map[code].append(str(board_name))
            except Exception:
                pass

        return {
            'themes': theme_counter.most_common(15),
            'hot_stock_count': len(hot),
            'hot_stocks': (
                hot[['代码', '名称', '涨跌幅']].to_dict('records')
            ),
            'stock_theme_map': stock_theme_map,
            'analysis_time': datetime.now().strftime('%Y-%m-%d %H:%M'),
        }


# ── 全局单例 ────────────────────────────────────────────
dl = AShareDataLayer()
