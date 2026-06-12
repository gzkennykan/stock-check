"""
量化信号模块：因子有效性回测 + 大盘择时信号 + 市场宽度增强
"""
import pandas as pd
import numpy as np
from .database import get_connection, _table_exists, get_latest_trading_date


def compute_market_breadth_history(end_date: str, lookback_days: int = 500) -> pd.DataFrame:
    """
    计算历史市场宽度指标，用于判断大盘顶底信号。

    指标:
      - 60日均线上方个股占比 (breadth_ma60)
      - 20日均线上方个股占比 (breadth_ma20)
      - 上涨/下跌比 (advance_decline)
      - 腾落线 (ADL - cumulative)
      - 新高/新低比 (NHNL)

    返回:
        DataFrame: trade_date, breadth_ma60, breadth_ma20, adv_ratio, adl, nh_nl, signal
    """
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "daily_kline"):
            return pd.DataFrame()

        base = (pd.to_datetime(end_date) - pd.Timedelta(days=lookback_days * 2)
                ).strftime("%Y-%m-%d")

        df = conn.execute(f"""
            WITH ma AS (
                SELECT symbol, trade_date, close,
                    AVG(close) OVER (PARTITION BY symbol ORDER BY trade_date
                        ROWS 19 PRECEDING) as ma20,
                    AVG(close) OVER (PARTITION BY symbol ORDER BY trade_date
                        ROWS 59 PRECEDING) as ma60,
                    MAX(close) OVER (PARTITION BY symbol ORDER BY trade_date
                        ROWS 59 PRECEDING) as high_60d,
                    MIN(close) OVER (PARTITION BY symbol ORDER BY trade_date
                        ROWS 59 PRECEDING) as low_60d
                FROM daily_kline
                WHERE trade_date >= '{base}'
            ),
            daily AS (
                SELECT trade_date,
                    AVG(CASE WHEN close > ma20 THEN 1.0 ELSE 0.0 END) as breadth_ma20,
                    AVG(CASE WHEN close > ma60 THEN 1.0 ELSE 0.0 END) as breadth_ma60,
                    AVG(CASE WHEN close > ma20 THEN 1.0 ELSE 0.0 END) -
                    AVG(CASE WHEN close < ma20 THEN 1.0 ELSE 0.0 END) as adv_ratio,
                    AVG(CASE WHEN close = high_60d THEN 1.0 ELSE 0.0 END) as nh_pct,
                    AVG(CASE WHEN close = low_60d THEN 1.0 ELSE 0.0 END) as nl_pct
                FROM ma
                WHERE trade_date >= '{base}'
                GROUP BY trade_date
            )
            SELECT * FROM daily ORDER BY trade_date
        """).df()

        conn.close()

        if df.empty:
            return pd.DataFrame()

        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df = df.set_index("trade_date").sort_index()

        # 腾落线（累计）
        df["adl"] = (df["adv_ratio"] * 1000).cumsum()

        # 新高新低比
        df["nh_nl"] = np.where(
            df["nl_pct"] > 0,
            df["nh_pct"] / df["nl_pct"],
            np.where(df["nh_pct"] > 0, 100, 1)
        )

        # 宽度百分比
        df["breadth_ma20"] = (df["breadth_ma20"] * 100).round(1)
        df["breadth_ma60"] = (df["breadth_ma60"] * 100).round(1)
        df["adv_ratio"] = df["adv_ratio"].round(3)

        # ── 市场信号评分 (0-100) ──
        df["signal"] = _compute_market_signal(df)

        return df
    except Exception:
        return pd.DataFrame()
    finally:
        try: conn.close()
        except Exception: pass


def _compute_market_signal(df: pd.DataFrame) -> pd.Series:
    """综合市场信号：越低越接近底部，越高越过热"""
    signal = pd.Series(50.0, index=df.index)

    # 60日宽度偏离
    signal += (df["breadth_ma60"] - 50) * 0.5

    # 涨跌比极端值
    signal += (df["adv_ratio"] * 20).clip(-10, 10)

    # 新高新低比
    if "nh_nl" in df.columns:
        nh_signal = np.where(df["nh_nl"] > 5, 15,
                             np.where(df["nh_nl"] > 2, 5,
                                      np.where(df["nh_nl"] < 0.5, -10, 0)))
        if isinstance(nh_signal, np.ndarray):
            signal = signal + pd.Series(nh_signal, index=signal.index).fillna(0)
        else:
            signal += nh_signal

    return signal.clip(0, 100)


def detect_market_extremes(df: pd.DataFrame) -> pd.DataFrame:
    """
    从市场宽度 DataFrame 检测顶部/底部信号。

    返回:
        DataFrame: date, signal_type (top/bottom), signal_score, indicators
    """
    if df.empty or "signal" not in df.columns:
        return pd.DataFrame()

    events = []

    # 底部信号：信号 < 20 且从下方回升
    bottom = df[df["signal"] < 20].copy()
    if not bottom.empty:
        for idx in bottom.index:
            prev = df.loc[:idx, "signal"].max() if len(df.loc[:idx]) > 1 else 50
            events.append({
                "date": idx.strftime("%Y-%m-%d"),
                "type": "🟢 底部信号",
                "signal": round(bottom.loc[idx, "signal"], 1),
            })

    # 顶部信号：信号 > 80
    top = df[df["signal"] > 80].copy()
    if not top.empty:
        for idx in top.index:
            events.append({
                "date": idx.strftime("%Y-%m-%d"),
                "type": "🔴 顶部信号",
                "signal": round(top.loc[idx, "signal"], 1),
            })

    if not events:
        return pd.DataFrame()

    result = pd.DataFrame(events)
    result = result.sort_values("date", ascending=False).head(30)
    return result.reset_index(drop=True)


def backtest_factor_returns(
    factor_name: str,
    end_date: str = None,
    periods: list[int] = [5, 10, 20],
) -> pd.DataFrame:
    """
    验证因子有效性：将股票按因子分3组，对比各组未来收益。

    返回:
        DataFrame: period, top_group_ret, bottom_group_ret, spread
    """
    from .database import get_latest_trading_date
    from .factors import compute_composite_ranking, compute_momentum

    if end_date is None:
        end_date = get_latest_trading_date()
        if end_date is None:
            return pd.DataFrame()

    # 获取排名
    df = compute_composite_ranking(end_date)
    if df.empty or "composite" not in df.columns:
        return pd.DataFrame()

    # 分三组
    n = len(df)
    top_n = max(1, n // 3)
    df["group"] = "mid"
    df.iloc[:top_n, df.columns.get_loc("group")] = "top"
    df.iloc[-top_n:, df.columns.get_loc("group")] = "bottom"

    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "daily_kline"):
            return pd.DataFrame()

        results = []
        for period in periods:
            p = (pd.to_datetime(end_date) + pd.Timedelta(days=1)
                 ).strftime("%Y-%m-%d")
            e = (pd.to_datetime(end_date) + pd.Timedelta(days=period + 10)
                 ).strftime("%Y-%m-%d")

            for group in ["top", "bottom"]:
                symbols = df[df["group"] == group]["symbol"].tolist()
                if not symbols:
                    continue
                placeholders = ",".join(["?"] * len(symbols))
                try:
                    r = conn.execute(f"""
                        WITH prices AS (
                            SELECT symbol, trade_date, close,
                                FIRST_VALUE(close) OVER (PARTITION BY symbol
                                    ORDER BY trade_date
                                    ROWS BETWEEN CURRENT ROW AND {period} FOLLOWING
                                ) as future_close
                            FROM daily_kline
                            WHERE symbol IN ({placeholders})
                              AND trade_date >= ?
                              AND trade_date <= ?
                        )
                        SELECT
                            AVG((future_close / NULLIF(close, 0) - 1) * 100) as avg_ret
                        FROM prices
                        WHERE trade_date = ?
                          AND future_close IS NOT NULL
                    """, symbols + [p, e, p]).fetchone()
                    if r and r[0] is not None:
                        results.append({
                            "period": f"{period}d",
                            "group": group,
                            "avg_return": round(r[0], 2),
                        })
                except Exception:
                    continue

        conn.close()

        if not results:
            return pd.DataFrame()

        result = pd.DataFrame(results)
        pivot = result.pivot(index="period", columns="group", values="avg_return")
        if "top" in pivot.columns and "bottom" in pivot.columns:
            pivot["spread"] = (pivot["top"] - pivot["bottom"]).round(2)
            pivot["factor_valid"] = pivot["spread"] > 0
        return pivot.reset_index()
    except Exception:
        return pd.DataFrame()
    finally:
        try:
            conn.close()
        except Exception:
            pass
