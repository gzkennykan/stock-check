"""
涨停板数据模块：东方财富涨停板池 + 强势股 + 炸板监控
数据源: 东方财富 (AKShare)
"""
import pandas as pd
from datetime import datetime
from pathlib import Path
from utils import retry, get_cache_ttl

_CACHE_DIR = Path(__file__).parent.parent / "data_cache"
_ZT_CACHE_FILE = _CACHE_DIR / "_zt_pool_cache.csv"
_ZT_STRONG_CACHE = _CACHE_DIR / "_zt_strong_cache.csv"
_ZT_BROKEN_CACHE = _CACHE_DIR / "_zt_broken_cache.csv"
_ZT_PREV_CACHE = _CACHE_DIR / "_zt_prev_cache.csv"
_ZT_TTL_MINUTES = 5


def _today_str() -> str:
    return datetime.now().strftime("%Y%m%d")


def _is_cache_fresh(cache_path: Path, ttl_minutes: int = _ZT_TTL_MINUTES) -> bool:
    if not cache_path.exists():
        return False
    age = (datetime.now() - datetime.fromtimestamp(cache_path.stat().st_mtime)).total_seconds()
    return age < ttl_minutes * 60


@retry(times=2, delay=1.0)
def _fetch_zt_pool(date: str) -> pd.DataFrame:
    """获取当日涨停板池"""
    import akshare as ak
    try:
        raw = ak.stock_zt_pool_em(date=date)
    except Exception as e:
        raise RuntimeError(f"涨停板池接口调用失败: {e}")

    if raw is None or raw.empty:
        return pd.DataFrame()

    df = pd.DataFrame()
    df["code"] = raw.get("代码", raw.iloc[:, 0] if raw.shape[1] > 0 else pd.Series(dtype=str)).astype(str).str.strip()
    df["name"] = raw.get("名称", raw.iloc[:, 1] if raw.shape[1] > 1 else pd.Series(dtype=str)).astype(str).str.strip()

    # 处理可能的列名差异
    col_map = {
        "涨跌幅": "pct_change",
        "最新价": "price",
        "涨停价": "limit_price",
        "封单资金": "seal_fund",
        "封单金额": "seal_fund",
        "封单数量": "seal_vol",
        "换手率": "turnover_rate",
        "流通市值": "float_mktcap",
        "涨停时间": "zt_time",
        "炸板次数": "break_count",
        "所属行业": "industry",
        "成交额": "turnover",
        "成交量": "volume",
        "首次涨停时间": "first_zt_time",
    }

    for cn_name, en_name in col_map.items():
        if cn_name in raw.columns:
            df[en_name] = raw[cn_name]
        elif en_name not in df.columns:
            df[en_name] = pd.NA

    # 数值转换
    for col in ["pct_change", "price", "limit_price", "turnover_rate", "float_mktcap"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 封单资金可能带"亿"/"万"单位
    if "seal_fund" in df.columns:
        df["seal_fund_raw"] = df["seal_fund"].astype(str)
        df["seal_fund_val"] = _parse_seal_fund(df["seal_fund_raw"])

    if "break_count" in df.columns:
        df["break_count"] = pd.to_numeric(df["break_count"], errors="coerce").fillna(0).astype(int)

    if "turnover" in df.columns:
        df["turnover"] = pd.to_numeric(df["turnover"], errors="coerce")

    return df


def _parse_seal_fund(series: pd.Series) -> pd.Series:
    """解析封单资金字符串，如 '1.23亿' '4567万' → 万元"""
    import numpy as np

    def _parse_one(v):
        if pd.isna(v):
            return np.nan
        s = str(v).strip()
        if not s:
            return np.nan
        try:
            if "亿" in s:
                return float(s.replace("亿", "")) * 10000
            elif "万" in s:
                return float(s.replace("万", ""))
            else:
                return float(s) / 10000  # 假设原始是元，转万元
        except (ValueError, TypeError):
            return np.nan

    return series.apply(_parse_one)


@retry(times=2, delay=1.0)
def _fetch_zt_strong() -> pd.DataFrame:
    """获取强势股池（连续涨停）"""
    import akshare as ak
    try:
        raw = ak.stock_zt_pool_strong_em()
    except Exception:
        return pd.DataFrame()

    if raw is None or raw.empty:
        return pd.DataFrame()

    df = pd.DataFrame()
    df["code"] = raw.get("代码", raw.iloc[:, 0] if raw.shape[1] > 0 else pd.Series(dtype=str)).astype(str).str.strip()
    df["name"] = raw.get("名称", raw.iloc[:, 1] if raw.shape[1] > 1 else pd.Series(dtype=str)).astype(str).str.strip()

    for cn_name, en_name in [
        ("涨跌幅", "pct_change"), ("最新价", "price"),
        ("涨停价", "limit_price"), ("换手率", "turnover_rate"),
        ("流通市值", "float_mktcap"), ("所属行业", "industry"),
        ("连续涨停天数", "consecutive_days"),
        ("封单资金", "seal_fund"),
    ]:
        if cn_name in raw.columns:
            df[en_name] = raw[cn_name]

    for col in ["pct_change", "price", "turnover_rate"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "consecutive_days" in df.columns:
        df["consecutive_days"] = pd.to_numeric(df["consecutive_days"], errors="coerce").fillna(1).astype(int)
    if "seal_fund" in df.columns:
        df["seal_fund_val"] = _parse_seal_fund(df["seal_fund"].astype(str))

    return df


@retry(times=2, delay=1.0)
def _fetch_zt_broken() -> pd.DataFrame:
    """获取炸板股池（涨停后打开的股票）"""
    import akshare as ak
    try:
        raw = ak.stock_zt_pool_zbgc_em()
    except Exception:
        return pd.DataFrame()

    if raw is None or raw.empty:
        return pd.DataFrame()

    df = pd.DataFrame()
    df["code"] = raw.get("代码", raw.iloc[:, 0] if raw.shape[1] > 0 else pd.Series(dtype=str)).astype(str).str.strip()
    df["name"] = raw.get("名称", raw.iloc[:, 1] if raw.shape[1] > 1 else pd.Series(dtype=str)).astype(str).str.strip()

    for cn_name, en_name in [
        ("涨跌幅", "pct_change"), ("最新价", "price"),
        ("涨停价", "limit_price"), ("换手率", "turnover_rate"),
        ("所属行业", "industry"), ("炸板次数", "break_count"),
        ("成交额", "turnover"),
    ]:
        if cn_name in raw.columns:
            df[en_name] = raw[cn_name]

    for col in ["pct_change", "price", "turnover_rate"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "break_count" in df.columns:
        df["break_count"] = pd.to_numeric(df["break_count"], errors="coerce").fillna(0).astype(int)

    return df


@retry(times=2, delay=1.0)
def _fetch_zt_previous(date: str) -> pd.DataFrame:
    """获取昨日涨停股今日表现"""
    import akshare as ak
    try:
        raw = ak.stock_zt_pool_previous_em(date=date)
    except Exception:
        return pd.DataFrame()

    if raw is None or raw.empty:
        return pd.DataFrame()

    df = pd.DataFrame()
    df["code"] = raw.get("代码", raw.iloc[:, 0] if raw.shape[1] > 0 else pd.Series(dtype=str)).astype(str).str.strip()
    df["name"] = raw.get("名称", raw.iloc[:, 1] if raw.shape[1] > 1 else pd.Series(dtype=str)).astype(str).str.strip()

    for cn_name, en_name in [
        ("涨跌幅", "pct_change"), ("最新价", "price"),
        ("昨涨停价", "prev_zt_price"), ("所属行业", "industry"),
        ("换手率", "turnover_rate"),
    ]:
        if cn_name in raw.columns:
            df[en_name] = raw[cn_name]

    for col in ["pct_change", "price", "turnover_rate"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def get_zt_pool(date: str | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """获取涨停板池（缓存5分钟）"""
    if date is None:
        date = _today_str()

    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if not force_refresh and _is_cache_fresh(_ZT_CACHE_FILE):
        cached = pd.read_csv(_ZT_CACHE_FILE, dtype={"code": str})
        if "date" in cached.columns and str(cached["date"].iloc[0]) == date:
            return cached

    df = _fetch_zt_pool(date)
    if not df.empty:
        df["date"] = date
        df.to_csv(_ZT_CACHE_FILE, index=False)
    return df


def get_zt_strong(force_refresh: bool = False) -> pd.DataFrame:
    """获取强势股池（连续涨停，缓存5分钟）"""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if not force_refresh and _is_cache_fresh(_ZT_STRONG_CACHE):
        return pd.read_csv(_ZT_STRONG_CACHE, dtype={"code": str})

    df = _fetch_zt_strong()
    if not df.empty:
        df.to_csv(_ZT_STRONG_CACHE, index=False)
    return df


def get_zt_broken(force_refresh: bool = False) -> pd.DataFrame:
    """获取炸板股池（缓存5分钟）"""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if not force_refresh and _is_cache_fresh(_ZT_BROKEN_CACHE):
        return pd.read_csv(_ZT_BROKEN_CACHE, dtype={"code": str})

    df = _fetch_zt_broken()
    if not df.empty:
        df.to_csv(_ZT_BROKEN_CACHE, index=False)
    return df


def get_zt_previous(date: str | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """获取昨日涨停股今日表现（缓存5分钟）"""
    if date is None:
        date = _today_str()

    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if not force_refresh and _is_cache_fresh(_ZT_PREV_CACHE):
        cached = pd.read_csv(_ZT_PREV_CACHE, dtype={"code": str})
        return cached

    df = _fetch_zt_previous(date)
    if not df.empty:
        df["query_date"] = date
        df.to_csv(_ZT_PREV_CACHE, index=False)
    return df


def get_zt_summary(date: str | None = None, force_refresh: bool = False) -> dict:
    """获取涨停板综合摘要：涨停数、炸板数、连板分布、行业分布"""
    zt = get_zt_pool(date, force_refresh)
    broken = get_zt_broken(force_refresh)
    strong = get_zt_strong(force_refresh)

    summary = {
        "zt_count": len(zt),
        "broken_count": len(broken),
        "strong_count": len(strong),
        "broken_rate": round(len(broken) / len(zt) * 100, 1) if len(zt) > 0 else 0,
    }

    # 连板分布 (从强势股池)
    if not strong.empty and "consecutive_days" in strong.columns:
        board_dist = strong["consecutive_days"].value_counts().sort_index().to_dict()
        summary["board_distribution"] = board_dist
    else:
        summary["board_distribution"] = {}

    # 行业分布 (TOP10)
    if not zt.empty and "industry" in zt.columns:
        ind_dist = zt["industry"].value_counts().head(10).to_dict()
        summary["top_industries"] = ind_dist
    else:
        summary["top_industries"] = {}

    return summary
