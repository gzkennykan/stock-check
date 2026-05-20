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


# ════════════════ 加固 HTTP 请求 ════════════════

import random
import requests as _requests

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
]


def _random_ua() -> str:
    return random.choice(_USER_AGENTS)


def resilient_session() -> _requests.Session:
    """创建带 UA 轮换和基础请求头的 Session"""
    s = _requests.Session()
    s.headers.update({
        "User-Agent": _random_ua(),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "no-cache",
    })
    return s


def resilient_get(url: str, params: dict = None, timeout: int = 30,
                  max_retries: int = 3, base_delay: float = 1.0,
                  session: _requests.Session | None = None,
                  **kwargs) -> _requests.Response:
    """
    带指数退避和 UA 轮换的 GET 请求。

    Args:
        max_retries: 最大重试次数（不含首次）
        base_delay: 基础退避延迟（秒），每次重试翻倍
        session: 可选，共用 Session 以复用连接
    """
    s = session or resilient_session()
    for attempt in range(max_retries + 1):
        try:
            if attempt > 0:
                s.headers["User-Agent"] = _random_ua()
            return s.get(url, params=params, timeout=timeout, **kwargs)
        except Exception:
            if attempt == max_retries:
                raise
            time.sleep(base_delay * (2 ** attempt) + random.uniform(0, 0.5))


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
