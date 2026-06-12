"""
每日异动检测 — 基于 DuckDB SQL 窗口函数
检测跳空、异常放量、逼近涨跌停、连续涨跌等
"""
import pandas as pd
from .database import get_connection, _table_exists


def detect_gap_openings(end_date: str, threshold_pct: float = 3.0) -> pd.DataFrame:
    """
    跳空缺口检测：当日开盘价 vs 前日收盘价偏差 > threshold_pct%。

    返回:
        DataFrame: symbol, gap_pct, direction (up/down), prev_close, today_open
    """
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "daily_kline"):
            return pd.DataFrame()
        base = (pd.to_datetime(end_date) - pd.Timedelta(days=10)
                ).strftime("%Y-%m-%d")

        df = conn.execute("""
            WITH gaps AS (
                SELECT symbol, trade_date, open, close,
                    LAG(close, 1) OVER (PARTITION BY symbol ORDER BY trade_date
                        ) as prev_close,
                    (open - LAG(close, 1) OVER (PARTITION BY symbol
                        ORDER BY trade_date))
                    / NULLIF(LAG(close, 1) OVER (PARTITION BY symbol
                        ORDER BY trade_date), 0) * 100 as gap_pct
                FROM daily_kline
                WHERE trade_date >= ?
            )
            SELECT symbol,
                ROUND(prev_close, 2) as prev_close,
                ROUND(open, 2) as today_open,
                ROUND(gap_pct, 2) as gap_pct,
                CASE WHEN gap_pct > 0 THEN 'up' ELSE 'down' END as direction
            FROM gaps
            WHERE trade_date = ?
              AND prev_close > 0
              AND ABS(gap_pct) >= ?
            ORDER BY ABS(gap_pct) DESC
        """, [base, end_date, threshold_pct]).df()

        return df
    finally:
        conn.close()


def detect_volume_spikes(end_date: str, multiplier: float = 3.0) -> pd.DataFrame:
    """
    异常放量检测：当日成交量 > N 倍 20 日均量。

    返回:
        DataFrame: symbol, volume, avg_vol_20d, vol_ratio, close, pct_change
    """
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "daily_kline"):
            return pd.DataFrame()
        base = (pd.to_datetime(end_date) - pd.Timedelta(days=60)
                ).strftime("%Y-%m-%d")

        df = conn.execute("""
            WITH vol AS (
                SELECT symbol, trade_date, close, volume,
                    AVG(volume) OVER (PARTITION BY symbol ORDER BY trade_date
                        ROWS 19 PRECEDING) as avg_vol_20d,
                    LAG(close, 1) OVER (PARTITION BY symbol
                        ORDER BY trade_date) as prev_close
                FROM daily_kline
                WHERE trade_date >= ?
            )
            SELECT symbol,
                ROUND(close, 2) as close,
                ROUND(volume, 0) as volume,
                ROUND(avg_vol_20d, 0) as avg_vol_20d,
                ROUND(volume / NULLIF(avg_vol_20d, 0), 2) as vol_ratio,
                ROUND((close / NULLIF(prev_close, 0) - 1) * 100, 2) as pct_change
            FROM vol
            WHERE trade_date = ?
              AND avg_vol_20d > 0
              AND volume > avg_vol_20d * ?
            ORDER BY vol_ratio DESC
        """, [base, end_date, multiplier]).df()

        return df
    finally:
        conn.close()


def detect_limit_approaching(end_date: str, threshold_pct: float = 9.0) -> pd.DataFrame:
    """
    涨跌停逼近检测：当日涨跌幅绝对值 > threshold_pct%。
    默认 9% 覆盖主板（±10%）和创业板/科创板（±20%）的极端行情。

    返回:
        DataFrame: symbol, close, prev_close, pct_change, direction
    """
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "daily_kline"):
            return pd.DataFrame()
        base = (pd.to_datetime(end_date) - pd.Timedelta(days=5)
                ).strftime("%Y-%m-%d")

        df = conn.execute("""
            WITH chg AS (
                SELECT symbol, trade_date, close,
                    LAG(close, 1) OVER (PARTITION BY symbol
                        ORDER BY trade_date) as prev_close
                FROM daily_kline
                WHERE trade_date >= ?
            )
            SELECT symbol,
                ROUND(prev_close, 2) as prev_close,
                ROUND(close, 2) as close,
                ROUND((close / NULLIF(prev_close, 0) - 1) * 100, 2) as pct_change,
                CASE WHEN close >= prev_close THEN 'up' ELSE 'down' END as direction
            FROM chg
            WHERE trade_date = ?
              AND prev_close > 0
              AND ABS((close / NULLIF(prev_close, 0) - 1) * 100) >= ?
            ORDER BY ABS(pct_change) DESC
        """, [base, end_date, threshold_pct]).df()

        return df
    finally:
        conn.close()


def detect_consecutive_days(end_date: str, n_days: int = 3) -> pd.DataFrame:
    """
    连续涨/跌天检测：最近 N 天连续同方向。

    返回:
        DataFrame: symbol, direction, streak_length, cumulative_pct
    """
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "daily_kline"):
            return pd.DataFrame()
        # 需要 N+5 天数据
        base = (pd.to_datetime(end_date) - pd.Timedelta(days=n_days + 10)
                ).strftime("%Y-%m-%d")

        # DuckDB 中用窗口函数检测连续方向
        df = conn.execute("""
            WITH directions AS (
                SELECT symbol, trade_date, close,
                    LAG(close, 1) OVER (PARTITION BY symbol ORDER BY trade_date
                        ) as prev_close,
                    CASE WHEN close > LAG(close, 1) OVER (PARTITION BY symbol
                        ORDER BY trade_date) THEN 1
                         WHEN close < LAG(close, 1) OVER (PARTITION BY symbol
                        ORDER BY trade_date) THEN -1
                         ELSE 0 END as dir
                FROM daily_kline
                WHERE trade_date >= ?
            ),
            -- 检测方向变化的断点
            groups AS (
                SELECT *,
                    SUM(CASE WHEN dir != LAG(dir, 1)
                            OVER (PARTITION BY symbol ORDER BY trade_date)
                        THEN 1 ELSE 0 END)
                    OVER (PARTITION BY symbol ORDER BY trade_date
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                    ) as grp
                FROM directions
                WHERE dir != 0
            ),
            streaks AS (
                SELECT symbol, dir, grp,
                    COUNT(*) as streak_len,
                    MIN(trade_date) as streak_start,
                    MAX(trade_date) as streak_end,
                    FIRST(close) as first_close,
                    LAST(close) as last_close
                FROM groups
                GROUP BY symbol, dir, grp
            )
            SELECT symbol,
                CASE WHEN dir = 1 THEN 'up' ELSE 'down' END as direction,
                streak_len as streak_length,
                ROUND((last_close / NULLIF(first_close, 0) - 1) * 100, 2
                    ) as cumulative_pct,
                MIN(streak_end) as end_date
            FROM streaks
            WHERE streak_end = ?
              AND streak_len >= ?
            GROUP BY symbol, dir, streak_len, first_close, last_close
            ORDER BY streak_len DESC, cumulative_pct DESC
        """, [base, end_date, n_days]).df()

        if not df.empty:
            df["end_date"] = pd.to_datetime(df["end_date"])
        return df
    finally:
        conn.close()


def run_all_anomalies(end_date: str = None, **params) -> dict[str, pd.DataFrame]:
    """
    运行全部异动检测。

    参数:
        end_date: 截止日期，None=最新交易日
        params:   gap_threshold=3.0, volume_multiplier=3.0,
                  limit_threshold=9.0, consecutive_days=3

    返回:
        {category: DataFrame, ...}
    """
    from .database import get_latest_trading_date

    if end_date is None:
        end_date = get_latest_trading_date()
        if end_date is None:
            return {}

    results = {}

    try:
        gt = params.get("gap_threshold", 3.0)
        df = detect_gap_openings(end_date, threshold_pct=gt)
        if not df.empty:
            results["跳空缺口"] = df
    except Exception:
        pass

    try:
        vm = params.get("volume_multiplier", 3.0)
        df = detect_volume_spikes(end_date, multiplier=vm)
        if not df.empty:
            results["异常放量"] = df
    except Exception:
        pass

    try:
        lt = params.get("limit_threshold", 9.0)
        df = detect_limit_approaching(end_date, threshold_pct=lt)
        if not df.empty:
            results["涨跌停逼近"] = df
    except Exception:
        pass

    try:
        cd = params.get("consecutive_days", 3)
        df = detect_consecutive_days(end_date, n_days=cd)
        if not df.empty:
            results["连续涨/跌"] = df
    except Exception:
        pass

    return results
