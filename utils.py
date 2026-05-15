"""
通用工具函数：金额格式化、交易时段检测、API 重试
"""
import time
import functools
from datetime import datetime, time as dt_time
import pandas as pd


# ════════════════ 交易时段检测 ════════════════

# A股交易时段: 周一至周五 9:30-11:30, 13:00-15:00
_MORNING_START = dt_time(9, 30)
_MORNING_END = dt_time(11, 30)
_AFTERNOON_START = dt_time(13, 0)
_AFTERNOON_END = dt_time(15, 0)


def is_trading_time() -> bool:
    """判断当前是否处于 A 股连续竞价时段（周一至周五 9:30-15:00）"""
    now = datetime.now()
    if now.weekday() >= 5:  # 周六日
        return False
    t = now.time()
    return (_MORNING_START <= t <= _MORNING_END) or (_AFTERNOON_START <= t <= _AFTERNOON_END)


def get_cache_ttl(short_minutes: int = 5, long_minutes: int = 30) -> int:
    """根据是否交易时段返回合适的缓存 TTL（分钟）"""
    return short_minutes if is_trading_time() else long_minutes


def latest_trading_day() -> datetime:
    """返回最近的交易日（周一至周五，排除周六日）"""
    from datetime import timedelta
    d = datetime.now()
    while d.weekday() >= 5:  # 周六=5, 周日=6
        d -= timedelta(days=1)
    return d


def is_weekend(dt: datetime | None = None) -> bool:
    """判断是否为周六或周日"""
    if dt is None:
        dt = datetime.now()
    return dt.weekday() >= 5


# ════════════════ API 重试 ════════════════

def retry(times: int = 2, delay: float = 1.0):
    """装饰器：函数失败后自动重试（仅捕获 Exception）"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(times + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exc = e
                    if attempt < times:
                        time.sleep(delay)
            raise last_exc
        return wrapper
    return decorator


def retry_call(func, *args, times: int = 2, delay: float = 1.0, **kwargs):
    """调用 func，失败时自动重试。所有重试失败返回 None。"""
    for attempt in range(times + 1):
        try:
            return func(*args, **kwargs)
        except Exception:
            if attempt == times:
                return None
            time.sleep(delay)
    return None


# ════════════════ 金额格式化 ════════════════

def fmt_yuan(val: float, signed: bool = False) -> str:
    """格式化「元」金额，自动选择亿/万/元单位"""
    if pd.isna(val) or val == 0:
        return "0"
    prefix = ""
    if signed:
        prefix = "+" if val > 0 else "-"
    v = abs(val)
    if v >= 1e8:
        return f"{prefix}{v / 1e8:.2f}亿"
    elif v >= 1e4:
        return f"{prefix}{v / 1e4:.2f}万"
    return f"{prefix}{v:.0f}"


def fmt_wan(val: float, signed: bool = False) -> str:
    """格式化「万元」金额，输出统一用亿"""
    if pd.isna(val) or val == 0:
        return "0"
    prefix = ""
    if signed:
        prefix = "+" if val > 0 else "-"
    v = abs(val)
    if v >= 1e4:
        return f"{prefix}{v / 1e4:.2f}亿"
    return f"{prefix}{v / 1e4:.4f}亿"
