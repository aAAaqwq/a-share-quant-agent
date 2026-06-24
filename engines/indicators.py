"""
量化指标引擎 — engines/indicators.py
====================================
RSI, MACD, ATR, 量比, 估值, 52周分位, MA均线, 综合面板

依赖: akshare (可选, 仅 get_valuation 需要)
"""

import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────

def calc_ema(values: list, period: int) -> float:
    """计算指数移动平均 (EMA)"""
    if not values or period <= 0:
        return 0.0
    if len(values) < period:
        # 数据不足时用全部数据做简单平均
        return sum(values) / len(values)

    multiplier = 2 / (period + 1)
    ema = sum(values[:period]) / period  # 初始SMA
    for price in values[period:]:
        ema = (price - ema) * multiplier + ema
    return ema


def calc_sma(values: list, period: int) -> float:
    """简单移动平均"""
    if not values or period <= 0:
        return 0.0
    if len(values) < period:
        return sum(values) / len(values)
    return sum(values[-period:]) / period


# ──────────────────────────────────────────────
# 1. RSI — 相对强弱指标
# ──────────────────────────────────────────────

def calc_rsi(closes: list, period: int = 14) -> float:
    """计算RSI
    RSI > 70: 超买
    RSI > 80: 严重超买
    RSI < 30: 超卖
    """
    if len(closes) < period + 1:
        return 50.0

    gains = []
    losses = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))

    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


# ──────────────────────────────────────────────
# 2. MACD — 移动平均收敛发散
# ──────────────────────────────────────────────

def calc_macd(closes: list, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    """计算MACD
    返回: {macd_line, signal_line, histogram, trend: '多头'|'空头'}
    """
    if len(closes) < slow:
        return {'macd_line': 0, 'signal_line': 0, 'histogram': 0, 'trend': '数据不足'}

    ema_fast = calc_ema(closes, fast)
    ema_slow = calc_ema(closes, slow)
    macd_line = ema_fast - ema_slow

    # 构建MACD历史序列用于signal line计算
    macd_history = []
    for i in range(slow - 1, len(closes)):
        chunk = closes[:i + 1]
        ef = calc_ema(chunk, fast)
        es = calc_ema(chunk, slow)
        macd_history.append(ef - es)

    signal_line = calc_ema(macd_history, signal) if len(macd_history) >= signal else 0
    histogram = macd_line - signal_line

    return {
        'macd_line': round(macd_line, 4),
        'signal_line': round(signal_line, 4),
        'histogram': round(histogram, 4),
        'trend': '多头' if histogram > 0 else '空头'
    }


# ──────────────────────────────────────────────
# 3. 量比
# ──────────────────────────────────────────────

def calc_volume_ratio(volumes: list, current_vol: float) -> float:
    """量比 = 当前成交量 / 前5日平均成交量"""
    if len(volumes) < 5:
        return 1.0
    avg = sum(volumes[-5:]) / 5
    return round(current_vol / avg, 2) if avg > 0 else 1.0


# ──────────────────────────────────────────────
# 4. ATR — 真实波幅 (用于止损计算)
# ──────────────────────────────────────────────

def calc_atr(highs: list, lows: list, closes: list, period: int = 14) -> float:
    """计算ATR"""
    if len(closes) < period + 1:
        return 0.0

    true_ranges = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1])
        )
        true_ranges.append(tr)

    return round(sum(true_ranges[-period:]) / period, 4)


# ──────────────────────────────────────────────
# 5. 估值指标获取 (PE/PB/PS等)
# ──────────────────────────────────────────────

def get_valuation(code: str) -> dict:
    """获取PE/PB/PS等估值指标
    使用 akshare stock_a_indicator_lg(symbol=code)
    """
    try:
        import akshare as ak
        df = ak.stock_a_indicator_lg(symbol=code)
        if df is not None and not df.empty:
            latest = df.iloc[-1]
            return {
                'pe_ttm': float(latest.get('pe_ttm', 0) or 0),
                'pb': float(latest.get('pb', 0) or 0),
                'ps_ttm': float(latest.get('ps_ttm', 0) or 0),
                'dv_ratio': float(latest.get('dv_ratio', 0) or 0),
                'total_mv': float(latest.get('total_mv', 0) or 0),
            }
    except Exception as e:
        logger.debug(f"获取估值失败 {code}: {e}")
    return {'pe_ttm': 0, 'pb': 0, 'ps_ttm': 0, 'dv_ratio': 0, 'total_mv': 0}


# ──────────────────────────────────────────────
# 6. 52周分位
# ──────────────────────────────────────────────

def calc_52w_percentile(closes: list) -> float:
    """当前价格在52周高低区间的分位 (0-100)
    0 = 52周最低, 100 = 52周最高
    """
    if len(closes) < 60:
        return 50.0

    window = closes[-252:] if len(closes) >= 252 else closes
    high_52w = max(window)
    low_52w = min(window)
    current = closes[-1]

    if high_52w == low_52w:
        return 50.0
    return round((current - low_52w) / (high_52w - low_52w) * 100, 1)


# ──────────────────────────────────────────────
# 7. MA均线
# ──────────────────────────────────────────────

def calc_ma(closes: list, period: int) -> float:
    """计算MA均线"""
    if len(closes) < period:
        return 0.0
    return round(sum(closes[-period:]) / period, 2)


# ──────────────────────────────────────────────
# 8. KDJ (额外加分项)
# ──────────────────────────────────────────────

def calc_kdj(highs: list, lows: list, closes: list, period: int = 9) -> dict:
    """计算KDJ指标"""
    if len(closes) < period:
        return {'k': 50.0, 'd': 50.0, 'j': 50.0}

    k, d = 50.0, 50.0
    for i in range(period - 1, len(closes)):
        window_high = max(highs[i - period + 1:i + 1])
        window_low = min(lows[i - period + 1:i + 1])
        if window_high == window_low:
            rsv = 50.0
        else:
            rsv = (closes[i] - window_low) / (window_high - window_low) * 100
        k = 2 / 3 * k + 1 / 3 * rsv
        d = 2 / 3 * d + 1 / 3 * k

    j = 3 * k - 2 * d
    return {'k': round(k, 2), 'd': round(d, 2), 'j': round(j, 2)}


# ──────────────────────────────────────────────
# 9. 布林带 (额外加分项)
# ──────────────────────────────────────────────

def calc_boll(closes: list, period: int = 20, num_std: float = 2.0) -> dict:
    """计算布林带
    返回: {upper, mid, lower, width, pct}
    """
    if len(closes) < period:
        return {'upper': 0, 'mid': 0, 'lower': 0, 'width': 0, 'pct': 0.5}

    import math
    window = closes[-period:]
    mid = sum(window) / period
    variance = sum((x - mid) ** 2 for x in window) / period
    std = math.sqrt(variance)

    upper = mid + num_std * std
    lower = mid - num_std * std
    width = upper - lower
    current = closes[-1]
    pct = (current - lower) / width if width > 0 else 0.5

    return {
        'upper': round(upper, 2),
        'mid': round(mid, 2),
        'lower': round(lower, 2),
        'width': round(width, 2),
        'pct': round(pct, 2),
    }


# ──────────────────────────────────────────────
# 10. 综合指标面板
# ──────────────────────────────────────────────

def get_full_indicators(code: str, hist_data: list = None) -> dict:
    """获取单只股票的完整指标面板

    Args:
        code: 股票代码 (如 '000001')
        hist_data: 历史数据列表, 每项为dict (含close/high/low/volume或中文键名)
                   如果为None则自动从多源获取

    Returns:
        包含所有指标的字典
    """
    # 如果没有历史数据，从多源获取
    if hist_data is None:
        try:
            from plugins.multi_source import msd
            hist_data = msd.get_hist(code, days=90)
        except Exception as e:
            logger.warning(f"获取历史数据失败 {code}: {e}")
            return {'error': f'获取历史数据失败: {e}'}

    if not hist_data or len(hist_data) < 15:
        return {'error': '历史数据不足'}

    # 兼容中英文键名
    closes = [d.get('close', d.get('收盘', 0)) for d in hist_data]
    highs = [d.get('high', d.get('最高', 0)) for d in hist_data]
    lows = [d.get('low', d.get('最低', 0)) for d in hist_data]
    volumes = [d.get('volume', d.get('成交量', 0)) for d in hist_data]

    # 过滤无效数据
    if any(c <= 0 for c in closes):
        bad = [i for i, c in enumerate(closes) if c <= 0]
        logger.warning(f"{code} 存在无效收盘价: indices={bad}")

    result = {
        'code': code,
        'current_price': round(closes[-1], 4) if closes else 0,

        # 动量指标
        'rsi_14': calc_rsi(closes),
        'macd': calc_macd(closes),
        'kdj': calc_kdj(highs, lows, closes),

        # 波动指标
        'atr_14': calc_atr(highs, lows, closes),
        'boll': calc_boll(closes),

        # 量能指标
        'volume_ratio': calc_volume_ratio(volumes[:-1], volumes[-1]) if len(volumes) > 1 else 1.0,

        # 位置指标
        'pctile_52w': calc_52w_percentile(closes),

        # 均线
        'ma5': calc_ma(closes, 5),
        'ma10': calc_ma(closes, 10),
        'ma20': calc_ma(closes, 20),
        'ma60': calc_ma(closes, 60),

        # 均线多空排列
        'ma_trend': _ma_trend(closes),

        # 估值
        'valuation': get_valuation(code),
    }

    # 生成信号摘要
    result['signal'] = _generate_signal(result)

    return result


def _ma_trend(closes: list) -> str:
    """判断均线多空排列"""
    if len(closes) < 60:
        return '数据不足'
    ma5 = calc_ma(closes, 5)
    ma10 = calc_ma(closes, 10)
    ma20 = calc_ma(closes, 20)
    ma60 = calc_ma(closes, 60)

    if ma5 > ma10 > ma20 > ma60:
        return '多头排列'
    elif ma5 < ma10 < ma20 < ma60:
        return '空头排列'
    else:
        return '交织'


def _generate_signal(indicators: dict) -> dict:
    """根据指标生成综合交易信号"""
    signals = []

    rsi = indicators.get('rsi_14', 50)
    if rsi > 80:
        signals.append(('RSI严重超买', 'bearish'))
    elif rsi > 70:
        signals.append(('RSI超买', 'bearish'))
    elif rsi < 20:
        signals.append(('RSI严重超卖', 'bullish'))
    elif rsi < 30:
        signals.append(('RSI超卖', 'bullish'))

    macd = indicators.get('macd', {})
    if macd.get('trend') == '多头':
        signals.append(('MACD多头', 'bullish'))
    elif macd.get('trend') == '空头':
        signals.append(('MACD空头', 'bearish'))

    ma_trend = indicators.get('ma_trend', '')
    if ma_trend == '多头排列':
        signals.append(('均线多头排列', 'bullish'))
    elif ma_trend == '空头排列':
        signals.append(('均线空头排列', 'bearish'))

    pctile = indicators.get('pctile_52w', 50)
    if pctile > 90:
        signals.append(('接近52周高点', 'bearish'))
    elif pctile < 10:
        signals.append(('接近52周低点', 'bullish'))

    vol_ratio = indicators.get('volume_ratio', 1.0)
    if vol_ratio > 2.0:
        signals.append((f'放量 (量比{vol_ratio})', 'notice'))

    boll = indicators.get('boll', {})
    if boll.get('pct', 0.5) > 0.95:
        signals.append(('触及布林上轨', 'bearish'))
    elif boll.get('pct', 0.5) < 0.05:
        signals.append(('触及布林下轨', 'bullish'))

    # 统计多空
    bullish = sum(1 for _, s in signals if s == 'bullish')
    bearish = sum(1 for _, s in signals if s == 'bearish')

    if bullish > bearish + 1:
        overall = '偏多'
    elif bearish > bullish + 1:
        overall = '偏空'
    elif bullish > bearish:
        overall = '中性偏多'
    elif bearish > bullish:
        overall = '中性偏空'
    else:
        overall = '中性'

    return {
        'overall': overall,
        'bullish_count': bullish,
        'bearish_count': bearish,
        'details': [s[0] for s in signals],
    }


# ──────────────────────────────────────────────
# 模块自测
# ──────────────────────────────────────────────

if __name__ == '__main__':
    print('=' * 50)
    print('量化指标引擎 自测')
    print('=' * 50)

    # RSI
    test_closes = [1, 2, 3, 4, 5, 4, 3, 2, 1, 2, 3, 4, 5, 6, 7, 8]
    rsi = calc_rsi(test_closes)
    print(f'RSI({len(test_closes)}点): {rsi}')

    # MACD
    macd = calc_macd(test_closes)
    print(f'MACD: {macd}')

    # ATR
    atr = calc_atr([10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20,
                    21, 22, 23, 24, 25],
                   [9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19,
                    20, 21, 22, 23, 24],
                   [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20,
                    21, 22, 23, 24, 25])
    print(f'ATR: {atr}')

    # 52周分位
    pctile = calc_52w_percentile(list(range(1, 101)) + [95])
    print(f'52w分位(100点序列,当前95): {pctile}')

    # 量比
    vr = calc_volume_ratio([100, 120, 80, 90, 110], 200)
    print(f'量比(前5日均100, 当前200): {vr}')

    # KDJ
    kdj = calc_kdj([10, 11, 12, 13, 14, 15, 16, 17, 18, 19],
                   [9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
                   [10, 11, 12, 13, 14, 15, 16, 17, 18, 19])
    print(f'KDJ: {kdj}')

    # 布林带
    boll = calc_boll(list(range(1, 31)))
    print(f'布林带: {boll}')

    # MA
    print(f'MA5: {calc_ma(list(range(1, 21)), 5)}')
    print(f'MA20: {calc_ma(list(range(1, 21)), 20)}')

    print('\n✅ 指标引擎全部通过')
