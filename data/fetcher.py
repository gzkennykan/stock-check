"""
数据获取统一接口：AKShare (A股) 和 yfinance (美股/港股)
仅使用真实数据源，不生成模拟数据
"""
import pandas as pd
from .store import load_from_csv, save_to_csv


def _symbol_to_sina(symbol: str) -> str:
    """将 6 位代码转为新浪格式 sh600036 / sz000001"""
    if symbol.startswith(("6", "5", "9")):
        return f"sh{symbol}"
    elif symbol.startswith(("0", "3", "2")):
        return f"sz{symbol}"
    return symbol


def _fetch_akshare_sina(symbol: str, start: str, end: str) -> pd.DataFrame:
    """通过 AKShare 的 stock_zh_a_daily (新浪源) 获取 A 股日线"""
    import akshare as ak
    raw = ak.stock_zh_a_daily(
        symbol=_symbol_to_sina(symbol),
        start_date=start, end_date=end, adjust="qfq"
    )
    df = raw.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    df = df[["open", "high", "low", "close", "volume"]]
    df = df.sort_index()
    return df


def _fetch_akshare_eastmoney(symbol: str, start: str, end: str) -> pd.DataFrame:
    """通过 AKShare 的 stock_zh_a_hist (东方财富源) 获取 A 股日线（备用）"""
    import akshare as ak
    raw = ak.stock_zh_a_hist(symbol=symbol, period="daily",
                             start_date=start, end_date=end, adjust="qfq")
    rename = {}
    for cn, en in {"日期": "date", "开盘": "open", "最高": "high",
                    "最低": "low", "收盘": "close", "成交量": "volume"}.items():
        if cn in raw.columns:
            rename[cn] = en
    if rename:
        raw = raw.rename(columns=rename)
    date_col = "date" if "date" in raw.columns else raw.columns[0]
    if date_col != "date":
        raw = raw.rename(columns={date_col: "date"})
    raw["date"] = pd.to_datetime(raw["date"])
    raw = raw.set_index("date")
    raw = raw[["open", "high", "low", "close", "volume"]]
    raw = raw.sort_index()
    return raw


def _fetch_akshare(symbol: str, start: str, end: str) -> pd.DataFrame:
    """A 股数据获取：优先新浪源，失败则尝试东方财富源"""
    errors = []

    # 优先使用新浪源（更稳定）
    try:
        return _fetch_akshare_sina(symbol, start, end)
    except Exception as e:
        errors.append(f"新浪源: {e}")

    # 备用东方财富源
    try:
        return _fetch_akshare_eastmoney(symbol, start, end)
    except Exception as e:
        errors.append(f"东方财富源: {e}")

    raise RuntimeError(f"无法获取 {symbol} 的真实行情数据:\n  " + "\n  ".join(errors))


def _fetch_yfinance(symbol: str, start: str, end: str) -> pd.DataFrame:
    """通过 yfinance 获取美股/港股日线"""
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        df = ticker.history(start=start, end=end)
        if df.empty:
            raise ValueError("yfinance 返回空数据")
    except Exception as e:
        # 某些环境下 yfinance 可能受限，尝试调整
        raise RuntimeError(f"yfinance 获取 {symbol} 失败: {e}")

    df = df.rename(columns={
        "Open": "open", "High": "high", "Low": "low",
        "Close": "close", "Volume": "volume",
    })
    df = df[["open", "high", "low", "close", "volume"]]
    return df


def _detect_source(symbol: str) -> str:
    if symbol.isdigit() and len(symbol) == 6:
        return "akshare"
    return "yfinance"


def fetch_data(symbol: str, start: str, end: str, source: str | None = None,
               use_cache: bool = True) -> pd.DataFrame:
    """
    获取股票历史日线数据。先查缓存，未命中则从网络获取并缓存。

    参数:
        symbol: 股票代码 (A股如 "600036", 美股如 "AAPL")
        start: 起始日期 "YYYY-MM-DD"
        end: 结束日期 "YYYY-MM-DD"
        source: 数据源 "akshare"/"yfinance"，为 None 时自动推断
        use_cache: 是否使用本地缓存
    """
    if source is None:
        source = _detect_source(symbol)

    if use_cache:
        cached = load_from_csv(symbol)
        if cached is not None:
            return cached.loc[start:end]

    fetcher = _fetch_akshare if source == "akshare" else _fetch_yfinance
    df = fetcher(symbol, start, end)

    if use_cache:
        save_to_csv(symbol, df)
    return df
