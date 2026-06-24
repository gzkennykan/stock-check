"""
蜡烛图形态识别 — 基于 DuckDB SQL 窗口函数

识别 8 种经典蜡烛图形态：
  - 看涨吞没 (Bullish Engulfing)
  - 看跌吞没 (Bearish Engulfing)
  - 锤子线 (Hammer) / 倒锤子 (Inverted Hammer)
  - 启明之星 (Morning Star)
  - 黄昏之星 (Evening Star)
  - 三白兵 (Three White Soldiers)
  - 三黑鸦 (Three Black Crows)
"""
import pandas as pd
from .database import get_connection, _table_exists


def scan_all_candlestick_patterns(end_date: str = None) -> dict[str, pd.DataFrame]:
    """
    全市场扫描 8 种蜡烛图形态。

    返回:
        {pattern_name: DataFrame(symbol, date, close, ...)}
    """
    from .database import get_latest_trading_date
    if end_date is None:
        end_date = get_latest_trading_date()
        if end_date is None:
            return {}

    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "daily_kline"):
            return {}

        base = (pd.to_datetime(end_date) - pd.Timedelta(days=10)
                ).strftime("%Y-%m-%d")

        df = conn.execute("""
            WITH candles AS (
                SELECT symbol, trade_date, open, high, low, close, volume,
                    close - open as body,
                    ABS(close - open) / NULLIF(high - low, 0) as body_ratio,
                    (high - GREATEST(open, close)) / NULLIF(high - low, 0) as upper_shadow,
                    (LEAST(open, close) - low) / NULLIF(high - low, 0) as lower_shadow,
                    LAG(open, 1)  OVER w as prev_open,
                    LAG(close, 1) OVER w as prev_close,
                    LAG(high, 1)  OVER w as prev_high,
                    LAG(low, 1)   OVER w as prev_low,
                    LAG(open, 2)  OVER w as prev2_open,
                    LAG(close, 2) OVER w as prev2_close,
                    LAG(close, 3) OVER w as prev3_close
                FROM daily_kline
                WHERE trade_date >= ?
                WINDOW w AS (PARTITION BY symbol ORDER BY trade_date)
            )
            SELECT * FROM candles WHERE trade_date = ?
        """, [base, end_date]).df()

        conn.close()

        if df.empty:
            return {}

        df["trade_date"] = pd.to_datetime(df["trade_date"])
        results = {}

        # 1A. 看涨吞没
        bullish = df[
            (df["prev_close"] < df["prev_open"]) &  # 前阴
            (df["close"] > df["open"]) &              # 今阳
            (df["open"] <= df["prev_close"]) &        # 低开于前收
            (df["close"] >= df["prev_open"])          # 收高于前开
        ]
        if not bullish.empty:
            results["看涨吞没"] = bullish[["symbol", "trade_date", "close", "volume"]
                                    ].rename(columns={"trade_date": "date"})

        # 1B. 看跌吞没
        bearish = df[
            (df["prev_close"] > df["prev_open"]) &  # 前阳
            (df["close"] < df["open"]) &              # 今阴
            (df["open"] >= df["prev_close"]) &        # 高于前收
            (df["close"] <= df["prev_open"])          # 收低于前开
        ]
        if not bearish.empty:
            results["看跌吞没"] = bearish[["symbol", "trade_date", "close", "volume"]
                                    ].rename(columns={"trade_date": "date"})

        # 2A. 锤子线 (Hammer)
        hammer = df[
            (df["lower_shadow"] > 0.6) &             # 长下影
            (df["upper_shadow"] < 0.1) &             # 几乎无上影
            (df["body_ratio"] > 0) &                 # 有实体
            (df["body_ratio"] < 0.4) &               # 小实体
            (df["body"] > 0)                         # 阳线更佳
        ]
        if not hammer.empty:
            results["锤子线"] = hammer[["symbol", "trade_date", "close", "volume"]
                                  ].rename(columns={"trade_date": "date"})

        # 2B. 倒锤子 (Inverted Hammer)
        inv_hammer = df[
            (df["upper_shadow"] > 0.6) &
            (df["lower_shadow"] < 0.1) &
            (df["body_ratio"] > 0) &
            (df["body_ratio"] < 0.4)
        ]
        if not inv_hammer.empty:
            results["倒锤子"] = inv_hammer[["symbol", "trade_date", "close", "volume"]
                                     ].rename(columns={"trade_date": "date"})

        # 3. 启明之星 (Morning Star): 阴线→小实体跳空→大阳线
        morning = df[
            (df["prev2_close"] < df["prev2_close"].shift()) &  # 前前阴
            (df["prev_close"].abs() < 0.02 * df["prev_open"]) |  # 中间小实体（简化：跳空）
            (df["close"] > df["open"]) &                          # 今阳
            (df["close"] > (df["prev_open"] + df["prev_close"]) / 2)  # 收复过半
        ]
        # 简化版启明星
        morning = df[
            (df["close"] > df["open"]) &
            (df["prev_close"] < df["prev_open"]) &
            (df["prev2_close"] < df["prev2_open"]) &
            (df["close"] > df["prev_open"])
        ]
        if not morning.empty:
            results["启明之星"] = morning[["symbol", "trade_date", "close", "volume"]
                                     ].rename(columns={"trade_date": "date"})

        # 4. 黄昏之星 (Evening Star)
        evening = df[
            (df["close"] < df["open"]) &
            (df["prev_close"] > df["prev_open"]) &
            (df["prev2_close"] > df["prev2_open"]) &
            (df["close"] < df["prev_open"])
        ]
        if not evening.empty:
            results["黄昏之星"] = evening[["symbol", "trade_date", "close", "volume"]
                                     ].rename(columns={"trade_date": "date"})

        # 5. 三白兵 (Three White Soldiers)
        white = df[
            (df["close"] > df["open"]) &
            (df["prev_close"] > df["prev_open"]) &
            (df["prev2_close"] > df["prev2_open"]) &
            (df["close"] > df["prev_close"]) &
            (df["prev_close"] > df["prev2_close"])
        ]
        if not white.empty:
            results["三白兵"] = white[["symbol", "trade_date", "close", "volume"]
                                  ].rename(columns={"trade_date": "date"})

        # 6. 三黑鸦 (Three Black Crows)
        black = df[
            (df["close"] < df["open"]) &
            (df["prev_close"] < df["prev_open"]) &
            (df["prev2_close"] < df["prev2_open"]) &
            (df["close"] < df["prev_close"]) &
            (df["prev_close"] < df["prev2_close"])
        ]
        if not black.empty:
            results["三黑鸦"] = black[["symbol", "trade_date", "close", "volume"]
                                  ].rename(columns={"trade_date": "date"})

        return results
    finally:
        try: conn.close()
        except Exception: pass


# ══════════════════════════════════════════════════════════
# 扩展形态库：30+ 形态（使用 pandas-ta）
# ══════════════════════════════════════════════════════════

_PATTERNS_TA = {
    "CDLDOJI": "十字星",
    "CDLDRAGONFLYDOJI": "蜻蜓十字星",
    "CDLGRAVESTONEDOJI": "墓碑十字星",
    "CDLLONGLEGGEDDOJI": "长脚十字星",
    "CDLHAMMER": "锤子线",
    "CDLINVERTEDHAMMER": "倒锤子",
    "CDLHANGINGMAN": "上吊线",
    "CDLSHOOTINGSTAR": "射击之星",
    "CDLSPINNINGTOP": "纺锤线",
    "CDLMARUBOZU": "光头光脚",
    "CDLENGULFING": "吞没形态",
    "CDLHARAMI": "孕线",
    "CDLPIERCING": "刺透形态",
    "CDLDARKCLOUDCOVER": "乌云盖顶",
    "CDLMORNINGSTAR": "启明之星(TA)",
    "CDLEVENINGSTAR": "黄昏之星(TA)",
    "CDLMORNINGDOJISTAR": "启明星十字星",
    "CDLEVENINGDOJISTAR": "黄昏星十字星",
    "CDL3WHITESOLDIERS": "红三兵(TA)",
    "CDL3BLACKCROWS": "黑三鸦(TA)",
    "CDL3INSIDE": "三内部上涨下跌",
    "CDL3OUTSIDE": "三外部上涨下跌",
    "CDL3STARSINSOUTH": "南方三星",
    "CDLABANDONEDBABY": "弃婴形态",
    "CDLDOJISTAR": "十字启明星",
    "CDLHARAMICROSS": "十字孕线",
    "CDLRISEFALL3METHODS": "上升/下降三法",
    "CDLUNIQUE3RIVER": "独特三河",
    "CDLSEPARATINGLINES": "分离线",
    "CDLTAKURI": "探水竿",
    "CDL2CROWS": "双乌鸦",
    "CDL3LINESTRIKE": "三线打击",
}

_BULLISH_PATTERNS_TA = {
    "CDLDRAGONFLYDOJI", "CDLHAMMER", "CDLINVERTEDHAMMER",
    "CDLPIERCING", "CDLMORNINGSTAR", "CDLMORNINGDOJISTAR",
    "CDL3WHITESOLDIERS", "CDL3INSIDE", "CDLABANDONEDBABY",
    "CDLDOJISTAR", "CDLUNIQUE3RIVER", "CDLTAKURI",
    "CDLRISEFALL3METHODS", "CDLSEPARATINGLINES",
}

_BEARISH_PATTERNS_TA = {
    "CDLGRAVESTONEDOJI", "CDLHANGINGMAN", "CDLSHOOTINGSTAR",
    "CDLDARKCLOUDCOVER", "CDLEVENINGSTAR", "CDLEVENINGDOJISTAR",
    "CDL3BLACKCROWS", "CDL2CROWS",
}


def scan_pandas_ta_patterns(end_date: str = None) -> dict[str, pd.DataFrame]:
    """
    使用 pandas-ta 扫描 30+ K线形态（全市场）。

    返回:
        {中文名称: DataFrame(symbol, date, close, ...)}
    """
    try:
        import pandas_ta as ta
    except ImportError:
        return {"_error": pd.DataFrame(
            {"msg": ["请安装 pandas-ta: pip install pandas-ta"]})}

    from .database import get_latest_trading_date, get_connection

    if end_date is None:
        end_date = get_latest_trading_date()
        if end_date is None:
            return {}

    conn = get_connection(read_only=True)
    try:
        # 取最近200天数据确保指标有足够历史
        base = pd.to_datetime(end_date) - pd.Timedelta(days=200)
        base = base.strftime("%Y-%m-%d")

        df = conn.execute("""
            SELECT symbol, trade_date, open, high, low, close, volume
            FROM daily_kline
            WHERE trade_date >= ? AND trade_date <= ?
            ORDER BY symbol, trade_date
        """, [base, end_date]).df()

        if df.empty:
            return {}

        results = {}
        grouped = df.groupby("symbol")

        for ta_name, cn_name in _PATTERNS_TA.items():
            matches = []

            for sym, grp in grouped:
                if len(grp) < 10:
                    continue
                ohlcv = grp.set_index("trade_date")[
                    ["open", "high", "low", "close", "volume"]]

                try:
                    pattern_fn = getattr(ta, ta_name, None)
                    if pattern_fn is None:
                        continue
                    result = pattern_fn(
                        ohlcv["open"], ohlcv["high"],
                        ohlcv["low"], ohlcv["close"])
                    if result is None or result.sum() == 0:
                        continue

                    # 取最后一个非零信号
                    last_signals = result[result != 0]
                    if last_signals.empty:
                        continue

                    last_date = last_signals.index[-1]
                    last_val = last_signals.iloc[-1]
                    last_close = ohlcv.loc[last_date, "close"]

                    matches.append({
                        "symbol": sym,
                        "date": str(last_date.date()),
                        "close": round(float(last_close), 2),
                        "signal": int(last_val),
                    })
                except Exception:
                    continue

            if matches:
                results[cn_name] = pd.DataFrame(matches)

        return results
    finally:
        try: conn.close()
        except Exception: pass


def scan_bullish_ta(end_date: str = None) -> dict[str, pd.DataFrame]:
    """仅返回看涨形态（使用 pandas-ta）"""
    all_patterns = scan_pandas_ta_patterns(end_date)
    if "_error" in all_patterns:
        return all_patterns
    bullish = {}
    for cn_name, df in all_patterns.items():
        # 查找对应的 TA 名称
        for ta_name, name in _PATTERNS_TA.items():
            if name == cn_name and ta_name in _BULLISH_PATTERNS_TA:
                bullish[cn_name] = df
                break
    return bullish
