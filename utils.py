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

def parse_cn_money(val: str) -> float:
    """解析带中文单位的金额字符串，如 '18.47亿' → 1847000000, '1.27万' → 12700"""
    if isinstance(val, (int, float)):
        return float(val)
    val = str(val).strip()
    if not val:
        return 0.0
    num_str = val.rstrip("亿万千百")
    unit = val[len(num_str):]
    try:
        num = float(num_str)
    except ValueError:
        return 0.0
    if "亿" in unit:
        num *= 100_000_000
    elif "万" in unit:
        num *= 10_000
    return num


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


# ════════════════ 指标卡片 ════════════════

import streamlit as st


def display_kpi_row(items: list[tuple[str, str | int | float, str | None]]) -> None:
    """
    渲染一行等宽 KPI 指标卡片。

    参数:
        items: [(label, value, delta), ...] 每项一个三元组，delta 可为 None
    """
    if not items:
        return
    cols = st.columns(len(items))
    for i, (label, val, delta) in enumerate(items):
        with cols[i]:
            st.metric(label, val, delta=delta)


# ════════════════ 数据展示辅助 ════════════════

def search_stocks(df: pd.DataFrame, kw: str) -> pd.DataFrame:
    """在 DataFrame 中按 code/name 模糊搜索，返回匹配行"""
    if not kw:
        return df
    kw_lower = kw.lower()
    mask = (df["code"].astype(str).str.contains(kw_lower) |
            df["name"].astype(str).str.lower().str.contains(kw_lower))
    return df[mask]


# 通用的列名映射：英文 → 中文
_STOCK_COLUMN_MAP = {
    "code": "代码", "name": "名称", "price": "最新价",
    "pct_change": "涨跌幅(%)", "volume": "成交量(手)", "turnover": "成交额(元)",
    "pe": "市盈率", "pb": "市净率",
    "market_cap": "总市值", "circulating_cap": "流通市值",
    "turnover_rate": "换手率(%)", "industry": "行业",
}


def format_stock_display(df: pd.DataFrame,
                         money_cols: list[str] = None,
                         pct_cols: list[str] = None,
                         extra_rename: dict = None,
                         drop_after: list[str] = None) -> pd.DataFrame:
    """
    统一格式化股票展示 DataFrame：
    - price/pct_change 保留2位
    - 可选金额列格式化（fmt_yuan）
    - 列名中文化
    - 自动补充 _STOCK_COLUMN_MAP 中存在的列

    返回新的展示用 DataFrame（不修改原 df）。
    """
    display = df.copy()

    # round
    if "price" in display.columns:
        display["price"] = display["price"].round(2)
    if "pct_change" in display.columns:
        display["pct_change"] = display["pct_change"].round(2)
    if "turnover_rate" in display.columns:
        display["turnover_rate"] = display["turnover_rate"].round(2)
    if "pe" in display.columns:
        display["pe"] = display["pe"].round(1)
    if "pb" in display.columns:
        display["pb"] = display["pb"].round(2)

    # money formatting
    if money_cols:
        for mc in money_cols:
            if mc in display.columns:
                display[mc] = display[mc].apply(lambda x: fmt_yuan(x, signed=True))

    # pct formatting
    if pct_cols:
        for pc in pct_cols:
            if pc in display.columns:
                display[pc] = display[pc].apply(lambda x: f"{x:+.1f}%" if x != 0 else "0%")

    # rename
    rename_dict = {k: v for k, v in _STOCK_COLUMN_MAP.items() if k in display.columns}
    if extra_rename:
        rename_dict.update({k: v for k, v in extra_rename.items() if k in display.columns})
    display = display.rename(columns=rename_dict)

    # drop
    if drop_after:
        display = display[[c for c in display.columns if c not in drop_after]]

    return display
