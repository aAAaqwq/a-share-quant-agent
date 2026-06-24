"""数据校验层 — 确保数据质量和时间一致性"""
from datetime import datetime, timedelta
from typing import Optional

class DataValidator:
    """校验数据完整性和时间一致性"""
    
    TRADING_HOURS = (9, 30, 15, 0)  # 9:30 - 15:00
    
    @staticmethod
    def validate_market_data(data: dict, expected_date: str = None) -> dict:
        """校验行情数据"""
        issues = []
        
        # 时间校验
        if expected_date:
            data_date = data.get('date', '')
            if data_date and not data_date.startswith(expected_date):
                issues.append(f"⚠️ 日期不匹配: 期望 {expected_date}, 实际 {data_date}")
        
        # 完整性校验
        required_fields = ['name', 'price', 'pct']
        for field in required_fields:
            if field not in data or data[field] is None:
                issues.append(f"⚠️ 缺失字段: {field}")
        
        # 异常值检测
        pct = data.get('pct', 0)
        if abs(pct) > 20:
            issues.append(f"🔴 异常涨跌幅: {pct}%（需人工确认）")
        
        price = data.get('price', 0)
        if price <= 0:
            issues.append(f"🔴 无效价格: {price}")
        
        return {
            'valid': len([i for i in issues if '🔴' in i]) == 0,
            'warnings': [i for i in issues if '⚠️' in i],
            'errors': [i for i in issues if '🔴' in i],
        }
    
    @staticmethod
    def cross_validate(source1: dict, source2: dict, tolerance: float = 0.02) -> dict:
        """交叉验证两个数据源"""
        discrepancies = []
        
        for key in set(list(source1.keys()) + list(source2.keys())):
            v1 = source1.get(key, {})
            v2 = source2.get(key, {})
            
            if isinstance(v1, dict) and isinstance(v2, dict):
                p1 = v1.get('price', 0)
                p2 = v2.get('price', 0)
                if p1 > 0 and p2 > 0:
                    diff = abs(p1 - p2) / max(p1, p2)
                    if diff > tolerance:
                        discrepancies.append(f"{key}: 价格差异 {diff*100:.1f}% (源1={p1}, 源2={p2})")
        
        return {
            'consistent': len(discrepancies) == 0,
            'discrepancies': discrepancies,
        }
    
    @staticmethod
    def is_trading_hours() -> bool:
        now = datetime.now()
        if now.weekday() >= 5:  # 周末
            return False
        hour, minute = now.hour, now.minute
        time_min = hour * 60 + minute
        return 570 <= time_min <= 900  # 9:30 - 15:00
    
    @staticmethod
    def get_last_trading_date() -> str:
        now = datetime.now()
        if now.weekday() == 5:  # 周六
            now -= timedelta(days=1)
        elif now.weekday() == 6:  # 周日
            now -= timedelta(days=2)
        elif now.hour < 15:  # 收盘前
            now -= timedelta(days=1 if now.weekday() == 0 else 0)
        return now.strftime('%Y-%m-%d')

validator = DataValidator()
