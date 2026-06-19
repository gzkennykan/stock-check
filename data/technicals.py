"""
技术指标计算模块：从 DuckDB 提取 K线数据，就地计算常用指标。

指标: MA20/60/120, RSI(14), MACD(12,26,9), 区间收益, 波动率, 区间高低点
"""
import numpy as np
import pandas as pd
from data.database import get_connection


def get_kline_ohlcv(symbol: str, limit: int = 300) -> pd.DataFrame | None:
    """从 DuckDB 读取单只股票的 OHLCV 数据，按日期升序"""
    conn = get_connection(read_only=True)
    try:
        df = conn.execute("""
            SELECT trade_date, open, high, low, close, volume
            FROM daily_kline
            WHERE symbol = ?
            ORDER BY trade_date ASC
            LIMIT ?
        """, [str(symbol).strip().zfill(6), limit]).df()
        if df.empty:
            return None
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df = df.set_index("trade_date").sort_index()
        return df
    finally:
        conn.close()


def compute_technicals(df: pd.DataFrame) -> pd.DataFrame:
    """
    输入 OHLCV DataFrame（index=date），在原 DataFrame 上新增技术指标列。

    新增列:
        ma20, ma60, ma120, rsi14,
        macd, macd_signal, macd_hist,
        pct_change(daily return)
    """
    if df.empty:
        return df

    result = df.copy()
    close = result["close"]

    # ── 均线 ──
    for n in [20, 60, 120]:
        result[f"ma{n}"] = close.rolling(n).mean()

    # ── RSI(14) ──
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    # 使用 Wilder 平滑（EMA）更精确
    avg_gain_w = gain.ewm(alpha=1/14, adjust=False).mean()
    avg_loss_w = loss.ewm(alpha=1/14, adjust=False).mean()
    rs = avg_gain_w / avg_loss_w.replace(0, np.nan)
    result["rsi14"] = 100 - (100 / (1 + rs))

    # ── MACD(12, 26, 9) ──
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    result["macd"] = ema12 - ema26
    result["macd_signal"] = result["macd"].ewm(span=9, adjust=False).mean()
    result["macd_hist"] = result["macd"] - result["macd_signal"]

    # ── 日收益率 ──
    result["pct_change"] = close.pct_change()

    return result


def get_period_return(df: pd.DataFrame, days: int) -> float:
    """计算近 N 日收益率（基于收盘价）"""
    if len(df) < days + 1:
        return np.nan
    close = df["close"]
    return float(close.iloc[-1] / close.iloc[-(days + 1)] - 1)


def get_annualized_volatility(df: pd.DataFrame, days: int = 60) -> float:
    """计算近 N 日年化波动率"""
    if len(df) < days:
        return np.nan
    returns = df["close"].pct_change().iloc[-days:]
    return float(returns.std() * np.sqrt(252))


def get_price_levels(df: pd.DataFrame, days: int = 20) -> dict:
    """返回近 N 日价格区间（最高、最低、收盘、均线位置）"""
    if len(df) < days:
        return {}
    recent = df.iloc[-days:]
    return {
        "high": float(recent["high"].max()),
        "low": float(recent["low"].min()),
        "close": float(recent["close"].iloc[-1]),
    }


def get_trend_status(df: pd.DataFrame) -> dict:
    """
    判断当前趋势状态：收盘价相对于 MA20/60/120 的位置。
    返回: { "vs_ma20": "上方"/"下方", "vs_ma60": ..., "vs_ma120": ...,
            "ma20_val", "ma60_val", "ma120_val", "close" }
    """
    close = float(df["close"].iloc[-1])
    status = {"close": close}
    for n in [20, 60, 120]:
        col = f"ma{n}"
        if col in df.columns and pd.notna(df[col].iloc[-1]):
            ma_val = float(df[col].iloc[-1])
            status[f"ma{n}_val"] = ma_val
            status[f"vs_ma{n}"] = "上方" if close > ma_val else "下方"
        else:
            status[f"ma{n}_val"] = None
            status[f"vs_ma{n}"] = "无数据"
    return status


def compute_full_analysis(symbol: str) -> dict:
    """
    单只股票完整技术分析。
    返回 dict，包含技术指标摘要、区间收益、趋势判断、关键位。
    """
    df = get_kline_ohlcv(symbol, limit=300)
    if df is None or df.empty:
        return {"error": f"数据库中无 {symbol} 的K线数据"}

    df = compute_technicals(df)
    last = df.iloc[-1]

    # 区间收益
    ret_20 = get_period_return(df, 20)
    ret_60 = get_period_return(df, 60)
    ret_120 = get_period_return(df, 120)
    vol_60 = get_annualized_volatility(df, 60)

    # 趋势状态
    trend = get_trend_status(df)

    # 关键位
    levels_20 = get_price_levels(df, 20)
    levels_60 = get_price_levels(df, 60)

    return {
        "symbol": symbol,
        "latest_date": str(df.index[-1].date()),
        "close": float(last["close"]),
        "ret_20d": round(ret_20 * 100, 2) if not np.isnan(ret_20) else None,
        "ret_60d": round(ret_60 * 100, 2) if not np.isnan(ret_60) else None,
        "ret_120d": round(ret_120 * 100, 2) if not np.isnan(ret_120) else None,
        "vol_60d_annual": round(vol_60 * 100, 2) if not np.isnan(vol_60) else None,
        "trend": trend,
        "rsi14": round(float(last["rsi14"]), 1) if pd.notna(last.get("rsi14")) else None,
        "macd": round(float(last["macd"]), 4) if pd.notna(last.get("macd")) else None,
        "macd_signal": round(float(last["macd_signal"]), 4) if pd.notna(last.get("macd_signal")) else None,
        "macd_hist": round(float(last["macd_hist"]), 4) if pd.notna(last.get("macd_hist")) else None,
        "ma20": round(float(last["ma20"]), 2) if pd.notna(last.get("ma20")) else None,
        "ma60": round(float(last["ma60"]), 2) if pd.notna(last.get("ma60")) else None,
        "ma120": round(float(last["ma120"]), 2) if pd.notna(last.get("ma120")) else None,
        "level_20d_high": round(levels_20.get("high", 0), 2),
        "level_20d_low": round(levels_20.get("low", 0), 2),
        "level_60d_high": round(levels_60.get("high", 0), 2),
        "level_60d_low": round(levels_60.get("low", 0), 2),
        "df": df,  # 完整 DataFrame，用于画图
    }
