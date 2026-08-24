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
                                    ].rename(columns={"trade_date": "date"}).assign(signal=1)

        # 1B. 看跌吞没
        bearish = df[
            (df["prev_close"] > df["prev_open"]) &  # 前阳
            (df["close"] < df["open"]) &              # 今阴
            (df["open"] >= df["prev_close"]) &        # 高于前收
            (df["close"] <= df["prev_open"])          # 收低于前开
        ]
        if not bearish.empty:
            results["看跌吞没"] = bearish[["symbol", "trade_date", "close", "volume"]
                                    ].rename(columns={"trade_date": "date"}).assign(signal=-1)

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
                                  ].rename(columns={"trade_date": "date"}).assign(signal=1)

        # 2B. 倒锤子 (Inverted Hammer)
        inv_hammer = df[
            (df["upper_shadow"] > 0.6) &
            (df["lower_shadow"] < 0.1) &
            (df["body_ratio"] > 0) &
            (df["body_ratio"] < 0.4)
        ]
        if not inv_hammer.empty:
            results["倒锤子"] = inv_hammer[["symbol", "trade_date", "close", "volume"]
                                     ].rename(columns={"trade_date": "date"}).assign(signal=1)

        # 3. 启明之星 (Morning Star): 前前阴 → 前阴 → 今大阳且收复前阴实体一半以上
        morning = df[
            (df["prev2_close"] < df["prev2_open"]) &  # 前前阴
            (df["prev_close"] < df["prev_open"]) &    # 前阴
            (df["close"] > df["open"]) &              # 今阳
            (df["close"] > (df["prev_open"] + df["prev_close"]) / 2)  # 收复过半
        ]
        if not morning.empty:
            results["启明之星"] = morning[["symbol", "trade_date", "close", "volume"]
                                     ].rename(columns={"trade_date": "date"}).assign(signal=1)

        # 4. 黄昏之星 (Evening Star)
        evening = df[
            (df["close"] < df["open"]) &
            (df["prev_close"] > df["prev_open"]) &
            (df["prev2_close"] > df["prev2_open"]) &
            (df["close"] < df["prev_open"])
        ]
        if not evening.empty:
            results["黄昏之星"] = evening[["symbol", "trade_date", "close", "volume"]
                                     ].rename(columns={"trade_date": "date"}).assign(signal=-1)

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
                                  ].rename(columns={"trade_date": "date"}).assign(signal=1)

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
                                  ].rename(columns={"trade_date": "date"}).assign(signal=-1)

        return results
    finally:
        try: conn.close()
        except Exception: pass


def scan_extended_patterns(end_date: str = None) -> dict[str, pd.DataFrame]:
    """
    自研扩展形态库：16 种补充形态（十字星族/孕线/刺透/乌云盖顶等）。

    不依赖 pandas-ta / TA-Lib，纯 pandas 判定，全市场一次 SQL 扫描。

    返回:
        {形态中文名: DataFrame(symbol, date, close, volume, signal)}，signal=+1 看涨 / -1 看跌
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
                    LAG(high, 2)  OVER w as prev2_high,
                    LAG(low, 2)   OVER w as prev2_low
                FROM daily_kline
                WHERE trade_date >= ?
                WINDOW w AS (PARTITION BY symbol ORDER BY trade_date)
            )
            SELECT * FROM candles WHERE trade_date = ?
        """, [base, end_date]).df()

        if df.empty:
            return {}

        df["trade_date"] = pd.to_datetime(df["trade_date"])
        return _detect_extended_patterns(df)
    finally:
        try: conn.close()
        except Exception: pass


def _detect_extended_patterns(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """
    在特征 DataFrame 上检测 16 种扩展形态（纯 pandas，可独立单测）。

    入参 df 需含列: symbol, trade_date, open, high, low, close, volume,
        body, body_ratio, upper_shadow, lower_shadow,
        prev_open, prev_close, prev_high, prev_low,
        prev2_open, prev2_close, prev2_high, prev2_low

    返回: {形态中文名: DataFrame(symbol, date, close, volume, signal)}
    """
    df = df.copy()
    df["body_ratio"] = df["body_ratio"].fillna(0.0)
    df["upper_shadow"] = df["upper_shadow"].fillna(0.0)
    df["lower_shadow"] = df["lower_shadow"].fillna(0.0)

    DOJI = df["body_ratio"] <= 0.15
    results = {}

    def _store(name, mask, signal):
        sub = df[mask]
        if not sub.empty:
            results[name] = sub[["symbol", "trade_date", "close", "volume"]
                                ].rename(columns={"trade_date": "date"}).assign(signal=signal)

    # ── 看涨 (+1) ──
    _store("蜻蜓十字星",
           DOJI & (df["lower_shadow"] > 0.6) & (df["upper_shadow"] < 0.1), 1)
    _store("刺透形态",
           (df["prev_close"] < df["prev_open"]) &          # 前阴
           (df["close"] > df["open"]) &                     # 今阳
           (df["open"] <= df["prev_low"]) &                 # 低开于前低
           (df["close"] > (df["prev_open"] + df["prev_close"]) / 2) &  # 收复过半
           (df["close"] < df["prev_open"]), 1)              # 未创新高
    _store("看涨孕线",
           (df["prev_close"] < df["prev_open"]) &           # 前阴
           (df["high"] <= df["prev_high"]) & (df["low"] >= df["prev_low"]) &
           (df["body_ratio"] > 0.15) & (df["body_ratio"] < 0.6), 1)
    _store("十字孕线看涨",
           (df["prev_close"] < df["prev_open"]) & DOJI &
           (df["high"] <= df["prev_high"]) & (df["low"] >= df["prev_low"]), 1)
    _store("早晨十字星",
           (df["prev2_close"] < df["prev2_open"]) &         # 前前阴
           (df["body_ratio"] <= 0.15) &                     # 前十字(今日视作星)简化
           (df["close"] > df["open"]) &
           (df["close"] > (df["prev2_open"] + df["prev2_close"]) / 2), 1)
    _store("看涨弃婴",
           (df["prev2_close"] < df["prev2_open"]) &         # 前前阴
           (df["prev_high"] < df["prev2_low"]) &            # 前跳空低开
           (df["low"] > df["prev_high"]) &                  # 今跳空高开
           (df["close"] > df["open"]), 1)                    # 今阳
    _store("三内部上涨",
           (df["prev2_close"] < df["prev2_open"]) &         # 前前阴
           (df["prev_high"] < df["prev2_open"]) & (df["prev_low"] > df["prev2_close"]) &
           (df["close"] > df["open"]) & (df["close"] > df["prev2_open"]), 1)
    _store("光头光脚阳线",
           (df["close"] > df["open"]) &
           (df["upper_shadow"] < 0.05) & (df["lower_shadow"] < 0.05) &
           (df["body_ratio"] > 0.6), 1)

    # ── 看跌 (-1) ──
    _store("墓碑十字星",
           DOJI & (df["upper_shadow"] > 0.6) & (df["lower_shadow"] < 0.1), -1)
    _store("上吊线",
           (df["lower_shadow"] > 0.6) & (df["upper_shadow"] < 0.1) &
           (df["body_ratio"] > 0) & (df["body_ratio"] < 0.4) &
           (df["body"] < 0), -1)                              # 阴线长下影
    _store("射击之星",
           (df["upper_shadow"] > 0.6) & (df["lower_shadow"] < 0.1) &
           (df["body_ratio"] > 0) & (df["body_ratio"] < 0.4), -1)
    _store("乌云盖顶",
           (df["prev_close"] > df["prev_open"]) &           # 前阳
           (df["close"] < df["open"]) &                      # 今阴
           (df["open"] > df["prev_high"]) &                  # 高开于前高
           (df["close"] < (df["prev_open"] + df["prev_close"]) / 2) &
           (df["close"] > df["prev_open"]), -1)
    _store("看跌孕线",
           (df["prev_close"] > df["prev_open"]) &           # 前阳
           (df["high"] <= df["prev_high"]) & (df["low"] >= df["prev_low"]) &
           (df["body_ratio"] > 0.15) & (df["body_ratio"] < 0.6), -1)
    _store("十字孕线看跌",
           (df["prev_close"] > df["prev_open"]) & DOJI &
           (df["high"] <= df["prev_high"]) & (df["low"] >= df["prev_low"]), -1)
    _store("黄昏十字星",
           (df["prev2_close"] > df["prev2_open"]) &         # 前前阳
           (df["body_ratio"] <= 0.15) &
           (df["close"] < df["open"]) &
           (df["close"] < (df["prev2_open"] + df["prev2_close"]) / 2), -1)
    _store("光头光脚阴线",
           (df["close"] < df["open"]) &
           (df["upper_shadow"] < 0.05) & (df["lower_shadow"] < 0.05) &
           (df["body_ratio"] > 0.6), -1)

    return results


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

    依赖: pandas_ta + TA-Lib（TA-Lib 未安装时大部分形态不可用，返回空字典，
          由原生 8+16 种形态兜底）。

    返回:
        {中文名称: DataFrame(symbol, date, close, signal)}
    """
    try:
        import pandas_ta as ta
    except ImportError:
        return {"_error": pd.DataFrame(
            {"msg": ["请安装 pandas-ta: pip install pandas-ta"]})}
    try:
        import talib  # noqa: F401  检测 TA-Lib C 库
    except ImportError:
        return {}  # 无 TA-Lib → 大多数形态不可用，降级为原生形态

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

        # cdl_pattern 用小写名（如 'hammer'），_PATTERNS_TA 键是大写（如 CDLHAMMER）
        names_list = [k.replace("CDL", "").lower() for k in _PATTERNS_TA.keys()]
        results = {}
        grouped = df.groupby("symbol")

        for sym, grp in grouped:
            if len(grp) < 10:
                continue
            ohlcv = grp.set_index("trade_date")
            try:
                # cdl_pattern 一次计算所有指定形态，返回 DataFrame
                res = ta.cdl_pattern(
                    ohlcv["open"], ohlcv["high"],
                    ohlcv["low"], ohlcv["close"], name=names_list)
            except Exception:
                continue
            if res is None or res.empty:
                continue

            for col in res.columns:
                # 列名形如 CDL_DOJI_10_0.1 / CDL_3WHITESOLDIERS_10_0.1
                if not str(col).startswith("CDL_"):
                    continue
                ta_name = "CDL" + str(col).split("_")[1]
                cn_name = _PATTERNS_TA.get(ta_name)
                if cn_name is None:
                    continue
                series = res[col].dropna()
                nz = series[series != 0]
                if nz.empty:
                    continue
                last_date = nz.index[-1]
                last_val = int(nz.iloc[-1])
                try:
                    last_close = float(ohlcv.loc[last_date, "close"])
                except Exception:
                    continue
                row = {
                    "symbol": sym,
                    "date": str(pd.Timestamp(last_date).date()),
                    "close": round(last_close, 2),
                    "signal": last_val,
                }
                results.setdefault(cn_name, []).append(row)

        return {cn: pd.DataFrame(rows) for cn, rows in results.items() if rows}
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
