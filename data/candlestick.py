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
