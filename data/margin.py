"""
融资融券数据模块：沪深两市融资融券余额、融资买入、融券卖出
数据源: 上交所/深交所 (AKShare)
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from utils import retry, get_cache_ttl

_CACHE_DIR = Path(__file__).parent.parent / "data_cache"
_MARGIN_SSE_CACHE = _CACHE_DIR / "_margin_sse_cache.csv"
_MARGIN_SZSE_CACHE = _CACHE_DIR / "_margin_szse_cache.csv"
_MARGIN_MERGED_CACHE = _CACHE_DIR / "_margin_merged_cache.csv"
_MARGIN_TTL_MINUTES = 30  # 两融数据每日更新一次，缓存30分钟即可


def _is_fresh(path: Path, ttl: int = _MARGIN_TTL_MINUTES) -> bool:
    if not path.exists():
        return False
    age = (datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)).total_seconds()
    return age < ttl * 60


@retry(times=2, delay=1.5)
def _fetch_margin_sse() -> pd.DataFrame:
    """获取上交所融资融券每日汇总数据"""
    import akshare as ak
    try:
        raw = ak.stock_margin_sse_daily()
    except Exception as e:
        raise RuntimeError(f"上交所两融接口调用失败: {e}")

    if raw is None or raw.empty:
        return pd.DataFrame()

    df = pd.DataFrame()
    # 列名映射（处理可能的列名差异）
    col_map = {
        "信用交易日期": "date", "日期": "date",
        "融资余额": "margin_balance", "融资余额(元)": "margin_balance",
        "融资买入额": "margin_buy", "融资买入额(元)": "margin_buy",
        "融券余量": "short_vol", "融券余量(股)": "short_vol",
        "融券余额": "short_balance", "融券余额(元)": "short_balance",
        "融券卖出量": "short_sell", "融券卖出量(股)": "short_sell",
        "融资偿还额": "margin_repay", "融资偿还额(元)": "margin_repay",
    }

    for cn_name, en_name in col_map.items():
        if cn_name in raw.columns:
            df[en_name] = raw[cn_name]

    # Convert to standard format
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"])
        df = df.set_index("date").sort_index()

    # Ensure numeric
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["exchange"] = "上交所"
    return df


@retry(times=2, delay=1.5)
def _fetch_margin_szse() -> pd.DataFrame:
    """获取深交所融资融券每日汇总数据"""
    import akshare as ak
    try:
        raw = ak.stock_margin_szse_daily()
    except Exception as e:
        raise RuntimeError(f"深交所两融接口调用失败: {e}")

    if raw is None or raw.empty:
        return pd.DataFrame()

    df = pd.DataFrame()
    col_map = {
        "信用交易日期": "date", "日期": "date",
        "融资余额": "margin_balance", "融资余额(元)": "margin_balance",
        "融资买入额": "margin_buy", "融资买入额(元)": "margin_buy",
        "融券余量": "short_vol", "融券余量(股)": "short_vol",
        "融券余额": "short_balance", "融券余额(元)": "short_balance",
        "融券卖出量": "short_sell", "融券卖出量(股)": "short_sell",
        "融资偿还额": "margin_repay", "融资偿还额(元)": "margin_repay",
    }

    for cn_name, en_name in col_map.items():
        if cn_name in raw.columns:
            df[en_name] = raw[cn_name]

    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"])
        df = df.set_index("date").sort_index()

    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["exchange"] = "深交所"
    return df


def get_margin_market(force_refresh: bool = False) -> pd.DataFrame:
    """
    获取沪深两市合并的两融汇总数据（按日）。
    返回 DataFrame: date索引, margin_balance(亿), margin_buy(亿),
                    short_balance(亿), short_sell(亿股), net_margin(亿)
    """
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if not force_refresh and _is_fresh(_MARGIN_MERGED_CACHE):
        cached = pd.read_csv(_MARGIN_MERGED_CACHE, index_col=0, parse_dates=True)
        if not cached.empty:
            return cached

    try:
        sse = _fetch_margin_sse()
    except Exception:
        sse = pd.DataFrame()
    try:
        szse = _fetch_margin_szse()
    except Exception:
        szse = pd.DataFrame()

    # 合并逻辑：按日期加总两市
    pieces = []
    for df in [sse, szse]:
        if not df.empty:
            pieces.append(df)

    if not pieces:
        # 尝试从缓存恢复
        if _MARGIN_MERGED_CACHE.exists():
            return pd.read_csv(_MARGIN_MERGED_CACHE, index_col=0, parse_dates=True)
        return pd.DataFrame()

    # 按日期合并（有些日期可能只有单市数据）
    all_dates = pd.DatetimeIndex([])
    for p in pieces:
        all_dates = all_dates.union(p.index)

    result = pd.DataFrame(index=all_dates.sort_values())
    agg_cols = ["margin_balance", "margin_buy", "margin_repay",
                "short_balance", "short_vol", "short_sell"]

    for col in agg_cols:
        series_list = [p[col] for p in pieces if col in p.columns]
        if series_list:
            combined = pd.concat(series_list, axis=1).sum(axis=1, min_count=1)
            result[col] = combined

    # 转换为亿元便于阅读
    for col in ["margin_balance", "margin_buy", "margin_repay", "short_balance"]:
        if col in result.columns:
            result[f"{col}_yi"] = result[col] / 1e8

    if "short_vol" in result.columns:
        result["short_vol_yi"] = result["short_vol"] / 1e8  # 亿股

    # 融资净买入 = 融资买入 - 融资偿还
    if "margin_buy" in result.columns and "margin_repay" in result.columns:
        result["net_margin_buy"] = result["margin_buy"] - result["margin_repay"]
        result["net_margin_buy_yi"] = result["net_margin_buy"] / 1e8

    result = result.dropna(how="all")
    result.to_csv(_MARGIN_MERGED_CACHE)
    return result


def get_margin_summary(force_refresh: bool = False) -> dict:
    """获取最新两融市场摘要"""
    df = get_margin_market(force_refresh)
    if df.empty:
        return {}

    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else None

    summary = {
        "date": latest.name.strftime("%Y-%m-%d") if hasattr(latest.name, "strftime") else str(latest.name),
        "margin_balance": latest.get("margin_balance_yi", 0),      # 融资余额(亿)
        "margin_buy": latest.get("margin_buy_yi", 0),              # 融资买入额(亿)
        "net_margin_buy": latest.get("net_margin_buy_yi", 0),      # 融资净买入(亿)
        "short_balance": latest.get("short_balance_yi", 0),        # 融券余额(亿)
    }

    if prev is not None:
        summary["margin_balance_change"] = summary["margin_balance"] - prev.get("margin_balance_yi", 0)
        summary["net_buy_change"] = summary["net_margin_buy"] - prev.get("net_margin_buy_yi", 0)
        summary["short_balance_change"] = summary["short_balance"] - prev.get("short_balance_yi", 0)

    # 最近20日均值
    recent = df.tail(20)
    summary["margin_balance_ma20"] = recent["margin_balance_yi"].mean() if "margin_balance_yi" in recent.columns else 0
    summary["margin_buy_ma5"] = recent["margin_buy_yi"].tail(5).mean() if "margin_buy_yi" in recent.columns else 0

    return summary


def get_margin_trend(days: int = 60, force_refresh: bool = False) -> pd.DataFrame:
    """获取最近N日两融趋势数据（用于绘图）"""
    df = get_margin_market(force_refresh)
    if df.empty:
        return df
    return df.tail(days)
