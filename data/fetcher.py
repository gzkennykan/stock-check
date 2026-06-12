"""
数据获取统一接口：AKShare (A股) 和 yfinance (美股/港股)
仅使用真实数据源，不生成模拟数据

缓存优先级: DuckDB 数据库 > CSV 文件 > 网络请求
获取数据后同时写入 DuckDB 和 CSV（双写）
"""
import pandas as pd
from .store import load_from_csv, save_to_csv
from .database import get_kline, insert_kline


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


def _fetch_akshare(symbol: str, start: str, end: str) -> pd.DataFrame:
    """A 股数据获取：新浪源（东方财富 push2 已被封禁，不再回退）"""
    return _fetch_akshare_sina(symbol, start, end)


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


def fetch_benchmark(symbol: str, start: str, end: str, use_cache: bool = True) -> pd.DataFrame:
    """
    获取基准指数日线数据（如沪深300=000300, 中证500=000905）。

    返回的 DataFrame 包含 close 列，用于计算基准收益率曲线。
    """
    import akshare as ak
    try:
        raw = ak.stock_zh_a_daily(
            symbol=_symbol_to_sina(symbol),
            start_date=start, end_date=end, adjust="qfq"
        )
        df = raw.copy()
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
        df = df[["close"]].sort_index()
        return df
    except Exception as e:
        raise RuntimeError(f"获取基准指数 {symbol} 失败: {e}")


def _detect_source(symbol: str) -> str:
    if symbol.isdigit() and len(symbol) == 6:
        return "akshare"
    return "yfinance"


def fetch_data(symbol: str, start: str, end: str, source: str | None = None,
               use_cache: bool = True) -> pd.DataFrame:
    """
    获取股票历史日线数据。缓存优先级: DuckDB > CSV > 网络。
    从网络获取后会同时写入 DuckDB 和 CSV（双写）。

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
        # 1) 优先从 DuckDB 读取
        db_data = get_kline(symbol, start, end)
        if not db_data.empty:
            return db_data

        # 2) 回退到 CSV
        cached = load_from_csv(symbol)
        if cached is not None:
            # 把 CSV 数据回写到 DB，方便后续查询
            try:
                insert_kline(symbol, cached, source=source)
            except Exception:
                pass  # DB 写入失败不影响主流程
            return cached.loc[start:end]

    # 3) 从网络获取
    fetcher = _fetch_akshare if source == "akshare" else _fetch_yfinance
    df = fetcher(symbol, start, end)

    if use_cache:
        # 双写: CSV + DuckDB
        save_to_csv(symbol, df)
        try:
            insert_kline(symbol, df, source=source)
        except Exception:
            pass  # DB 写入失败不影响主流程
    return df
