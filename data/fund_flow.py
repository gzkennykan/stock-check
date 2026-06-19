"""
个股资金流向模块：东方财富 (East Money) 按订单大小分层的资金流

数据源: 东方财富 → AKShare stock_individual_fund_flow()
提供: 近120日 超大单/大单/中单/小单 净额 & 净占比
     主力净额 = 超大单 + 大单
"""
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from utils import retry

_CACHE_DIR = Path(__file__).parent.parent / "data_cache"
_CACHE_TTL_HOURS = 2  # 个股资金流缓存2小时


def _norm_symbol(symbol: str) -> tuple[str, str]:
    """标准化股票代码 → (market, code)"""
    s = str(symbol).strip().zfill(6)
    if s.startswith(("6", "5", "9")):
        return "sh", s
    elif s.startswith(("0", "3", "2")):
        return "sz", s
    elif s.startswith(("8", "4")):
        return "bj", s
    return "sh", s


@retry(times=2, delay=1.0)
def _fetch_from_eastmoney(symbol: str, market: str) -> pd.DataFrame | None:
    """从东方财富获取个股资金流（120个交易日）"""
    import akshare as ak
    try:
        df = ak.stock_individual_fund_flow(stock=symbol, market=market)
    except Exception:
        return None
    if df is None or df.empty:
        return None
    return df


def get_individual_fund_flow(symbol: str, force_refresh: bool = False) -> pd.DataFrame | None:
    """
    获取个股资金流明细（近120日）。

    返回 DataFrame 列:
        date, close, pct_change,
        主力净额, 主力净占比,           ← 超大单 + 大单
        超大单净额, 超大单净占比,
        大单净额, 大单净占比,
        中单净额, 中单净占比,
        小单净额, 小单净占比
    """
    market, code = _norm_symbol(symbol)

    # 缓存
    cache_file = _CACHE_DIR / f"_ff_{code}.csv"
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if not force_refresh and cache_file.exists():
        age = (datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime))
        if age < timedelta(hours=_CACHE_TTL_HOURS):
            df = pd.read_csv(cache_file)
            if not df.empty:
                df["date"] = pd.to_datetime(df["date"])
                return df

    raw = _fetch_from_eastmoney(symbol, market)
    if raw is None:
        # 尝试从缓存返回旧数据
        if cache_file.exists():
            df = pd.read_csv(cache_file)
            if not df.empty:
                df["date"] = pd.to_datetime(df["date"])
                return df
        return None

    # ── 列名映射 ──
    # AKShare 返回的列名（中文）
    col_map = {
        "日期": "date",
        "收盘价": "close",
        "涨跌幅": "pct_change",
        "超大单净流入-净额": "超大单净额",
        "超大单净流入-净占比": "超大单净占比",
        "大单净流入-净额": "大单净额",
        "大单净流入-净占比": "大单净占比",
        "中单净流入-净额": "中单净额",
        "中单净流入-净占比": "中单净占比",
        "小单净流入-净额": "小单净额",
        "小单净流入-净占比": "小单净占比",
    }

    df = raw.copy()
    df = df.rename(columns=col_map)

    # 类型转换
    df["date"] = pd.to_datetime(df["date"])
    for c in ["close", "pct_change", "超大单净额", "大单净额", "中单净额", "小单净额"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in ["超大单净占比", "大单净占比", "中单净占比", "小单净占比"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    # 计算主力 = 超大单 + 大单
    super_large = df.get("超大单净额", pd.Series(0, index=df.index)).fillna(0)
    large = df.get("大单净额", pd.Series(0, index=df.index)).fillna(0)
    df["主力净额"] = super_large + large

    # 主力净占比
    total_abs = (
        super_large.abs() + large.abs() +
        df.get("中单净额", pd.Series(0, index=df.index)).fillna(0).abs() +
        df.get("小单净额", pd.Series(0, index=df.index)).fillna(0).abs()
    )
    df["主力净占比"] = np.where(total_abs > 0, (df["主力净额"] / total_abs * 100).round(2), 0)

    df = df.sort_values("date").reset_index(drop=True)

    # 只保留需要的列
    keep = ["date", "close", "pct_change",
            "主力净额", "主力净占比",
            "超大单净额", "超大单净占比",
            "大单净额", "大单净占比",
            "中单净额", "中单净占比",
            "小单净额", "小单净占比"]
    df = df[[c for c in keep if c in df.columns]]

    # 写缓存
    df.to_csv(cache_file, index=False)
    return df


def get_fund_flow_summary(symbol: str, days: int = 10) -> dict | None:
    """
    获取个股资金流统计摘要（近 N 日）。

    返回:
        { "latest_date", "close", "pct_change",
          "today_main_net", "today_main_net_yi",
          "mean", "median", "min", "max",
          "recent_days": [{date, main_net_yi, close}, ...] }
    """
    df = get_individual_fund_flow(symbol)
    if df is None or df.empty:
        return None

    recent = df.tail(days).copy()
    main_net = recent["主力净额"].dropna()

    if main_net.empty:
        return None

    latest = recent.iloc[-1]

    # 最近10日明细
    recent_list = []
    for _, r in recent.iterrows():
        recent_list.append({
            "date": r["date"].strftime("%Y-%m-%d") if pd.notna(r["date"]) else "",
            "main_net_yi": round(float(r["主力净额"]) / 1e8, 4) if pd.notna(r.get("主力净额")) else 0,
            "close": round(float(r["close"]), 2) if pd.notna(r.get("close")) else 0,
        })

    return {
        "latest_date": latest["date"].strftime("%Y-%m-%d") if pd.notna(latest["date"]) else "",
        "close": round(float(latest.get("close", 0)), 2),
        "pct_change": round(float(latest.get("pct_change", 0)), 2),
        "today_main_net": float(main_net.iloc[-1]) if len(main_net) > 0 else 0,
        "today_main_net_yi": round(float(main_net.iloc[-1]) / 1e8, 4) if len(main_net) > 0 else 0,
        "mean": round(float(main_net.mean()) / 1e8, 4),
        "median": round(float(main_net.median()) / 1e8, 4),
        "min": round(float(main_net.min()) / 1e8, 4),
        "max": round(float(main_net.max()) / 1e8, 4),
        "recent_days": recent_list,
    }
