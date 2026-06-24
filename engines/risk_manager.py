"""风控引擎 — 止损/仓位/超买过滤"""
from engines.indicators import calc_rsi, calc_atr, get_valuation, calc_52w_percentile


class RiskManager:
    """个股风控计算"""

    # 板块总仓位上限
    MAX_SECTOR_EXPOSURE = 0.30  # 30%
    # 单只最大仓位
    MAX_SINGLE_POSITION = 0.10  # 10%
    # 单笔交易风险占账户比例
    RISK_PER_TRADE = 0.02  # 2%

    def calculate_stop_loss(self, entry_price: float, atr: float) -> dict:
        """计算止损止盈 (ATR * 1.5 止损，ATR * 2/3 分批止盈)"""
        if atr <= 0:
            atr = entry_price * 0.05  # 默认5%波动

        return {
            'entry': round(entry_price, 2),
            'stop_loss': round(entry_price - atr * 1.5, 2),
            'stop_loss_pct': round(-atr * 1.5 / entry_price * 100, 1),
            'take_profit_1': round(entry_price + atr * 2, 2),
            'take_profit_2': round(entry_price + atr * 3, 2),
            'max_drawdown': -8.0,  # 强制清仓线
        }

    def calculate_position(self, atr: float, price: float, account_size: float = 100000) -> dict:
        """基于波动率计算建议仓位 (波动越大仓位越轻)"""
        if atr <= 0 or price <= 0:
            return {'position_pct': 0, 'shares': 0, 'risk_amount': 0, 'position_value': 0}

        # 每股风险 = ATR * 1.5
        risk_per_share = atr * 1.5
        # 总风险 = 账户的 2%
        total_risk = account_size * self.RISK_PER_TRADE
        # 建议股数 (整手: 100股)
        shares = int(total_risk / risk_per_share / 100) * 100
        position_value = shares * price
        position_pct = round(position_value / account_size * 100, 1)

        # 不超过单只上限
        if position_pct > self.MAX_SINGLE_POSITION * 100:
            position_pct = self.MAX_SINGLE_POSITION * 100
            position_value = account_size * self.MAX_SINGLE_POSITION
            shares = int(position_value / price / 100) * 100

        return {
            'position_pct': position_pct,
            'shares': shares,
            'risk_amount': round(total_risk, 0),
            'position_value': round(position_value, 0),
        }

    def check_overbought(self, rsi: float, pe: float, pctile_52w: float,
                         consecutive_boards: int = 0, sector_20d_pct: float = 0) -> list:
        """超买/泡沫检测，返回风险标记列表

        Returns:
            [{'level': '🔴'/'🟡', 'type': str, 'detail': str}, ...]
        """
        warnings = []

        if rsi > 85:
            warnings.append({'level': '🔴', 'type': 'RSI超买', 'detail': f'RSI={rsi:.0f}，严重超买'})
        elif rsi > 70:
            warnings.append({'level': '🟡', 'type': 'RSI偏高', 'detail': f'RSI={rsi:.0f}，注意回调风险'})

        if pe > 200:
            warnings.append({'level': '🔴', 'type': '估值泡沫', 'detail': f'PE={pe:.0f}，严重高估'})
        elif pe > 100:
            warnings.append({'level': '🟡', 'type': '估值偏高', 'detail': f'PE={pe:.0f}'})

        if pctile_52w > 95:
            warnings.append({'level': '🔴', 'type': '历史高位', 'detail': f'52周分位{pctile_52w:.0f}%'})

        if consecutive_boards >= 5:
            warnings.append({'level': '🔴', 'type': '高位连板', 'detail': f'{consecutive_boards}连板'})

        if sector_20d_pct > 40:
            warnings.append({'level': '🟡', 'type': '板块过热', 'detail': f'板块20日涨幅{sector_20d_pct:.0f}%'})

        return warnings

    def should_exclude(self, warnings: list) -> bool:
        """根据风险标记决定是否排除

        规则: 2个以上红旗 (🔴) → 排除
        """
        red_count = sum(1 for w in warnings if w['level'] == '🔴')
        return red_count >= 2


# 全局实例
risk_mgr = RiskManager()
