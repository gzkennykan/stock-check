"""
技术形态全市场扫描 — 基于 DuckDB SQL 窗口函数
单次 CTE 计算全部均线，各形态检测分支查询
"""
import pandas as pd
from .database import get_connection, _table_exists


def _build_ma_cte(end_date: str, lookback_days: int = 90) -> tuple:
    """
    构建通用 CTE：计算所有品种的 MA5/10/20/60 + 成交量均线 + 极值。
    返回 (conn, cte_name, base_date) 以便各扫描函数复用。
    """
    base = (pd.to_datetime(end_date) - pd.Timedelta(days=lookback_days)
            ).strftime("%Y-%m-%d")
    return base


def scan_golden_cross(end_date: str, lookback_days: int = 10) -> pd.DataFrame:
    """
    金叉扫描：MA5 上穿 MA20（最近 N 日内发生的交叉）。
    """
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "daily_kline"):
            return pd.DataFrame()
        base = _build_ma_cte(end_date, 100)

        df = conn.execute("""
            WITH ma AS (
                SELECT symbol, trade_date, close,
                    AVG(close) OVER (PARTITION BY symbol ORDER BY trade_date
                        ROWS 4 PRECEDING) as ma5,
                    AVG(close) OVER (PARTITION BY symbol ORDER BY trade_date
                        ROWS 19 PRECEDING) as ma20
                FROM daily_kline
                WHERE trade_date >= ?
            ),
            lagged AS (
                SELECT symbol, trade_date, close, ma5, ma20,
                    LAG(ma5, 1) OVER (PARTITION BY symbol ORDER BY trade_date
                        ) as prev_ma5,
                    LAG(ma20, 1) OVER (PARTITION BY symbol ORDER BY trade_date
                        ) as prev_ma20
                FROM ma
            )
            SELECT symbol, trade_date as cross_date,
                ROUND(ma5, 2) as ma5_val, ROUND(ma20, 2) as ma20_val,
                ROUND(close, 2) as close
            FROM lagged
            WHERE trade_date >= ?
              AND prev_ma5 <= prev_ma20
              AND ma5 > ma20
              AND ma5 > 0 AND ma20 > 0
            ORDER BY trade_date DESC, symbol
        """, [base, (pd.to_datetime(end_date) - pd.Timedelta(days=lookback_days)
                     ).strftime("%Y-%m-%d")]).df()

        if not df.empty and "cross_date" in df.columns:
            df["cross_date"] = pd.to_datetime(df["cross_date"])
        return df
    finally:
        conn.close()


def scan_death_cross(end_date: str, lookback_days: int = 10) -> pd.DataFrame:
    """
    死叉扫描：MA5 下穿 MA20。
    """
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "daily_kline"):
            return pd.DataFrame()
        base = _build_ma_cte(end_date, 100)

        df = conn.execute("""
            WITH ma AS (
                SELECT symbol, trade_date, close,
                    AVG(close) OVER (PARTITION BY symbol ORDER BY trade_date
                        ROWS 4 PRECEDING) as ma5,
                    AVG(close) OVER (PARTITION BY symbol ORDER BY trade_date
                        ROWS 19 PRECEDING) as ma20
                FROM daily_kline
                WHERE trade_date >= ?
            ),
            lagged AS (
                SELECT symbol, trade_date, close, ma5, ma20,
                    LAG(ma5, 1) OVER (PARTITION BY symbol ORDER BY trade_date
                        ) as prev_ma5,
                    LAG(ma20, 1) OVER (PARTITION BY symbol ORDER BY trade_date
                        ) as prev_ma20
                FROM ma
            )
            SELECT symbol, trade_date as cross_date,
                ROUND(ma5, 2) as ma5_val, ROUND(ma20, 2) as ma20_val,
                ROUND(close, 2) as close
            FROM lagged
            WHERE trade_date >= ?
              AND prev_ma5 >= prev_ma20
              AND ma5 < ma20
              AND ma5 > 0 AND ma20 > 0
            ORDER BY trade_date DESC, symbol
        """, [base, (pd.to_datetime(end_date) - pd.Timedelta(days=lookback_days)
                     ).strftime("%Y-%m-%d")]).df()

        if not df.empty and "cross_date" in df.columns:
            df["cross_date"] = pd.to_datetime(df["cross_date"])
        return df
    finally:
        conn.close()


def scan_ma_consolidation(end_date: str, threshold_pct: float = 3.0) -> pd.DataFrame:
    """
    均线粘合扫描：MA5/10/20/60 相互偏离度 < threshold_pct%。
    粘合意味着即将变盘。
    """
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "daily_kline"):
            return pd.DataFrame()
        base = _build_ma_cte(end_date, 120)

        df = conn.execute("""
            WITH ma AS (
                SELECT symbol, trade_date, close,
                    AVG(close) OVER w5  as ma5,
                    AVG(close) OVER w10 as ma10,
                    AVG(close) OVER w20 as ma20,
                    AVG(close) OVER w60 as ma60
                FROM daily_kline
                WHERE trade_date >= ?
                WINDOW
                    w5  AS (PARTITION BY symbol ORDER BY trade_date ROWS 4 PRECEDING),
                    w10 AS (PARTITION BY symbol ORDER BY trade_date ROWS 9 PRECEDING),
                    w20 AS (PARTITION BY symbol ORDER BY trade_date ROWS 19 PRECEDING),
                    w60 AS (PARTITION BY symbol ORDER BY trade_date ROWS 59 PRECEDING)
            )
            SELECT symbol,
                ROUND(close, 2) as close,
                ROUND(ma5, 2) as ma5,
                ROUND(ma10, 2) as ma10,
                ROUND(ma20, 2) as ma20,
                ROUND(ma60, 2) as ma60,
                ROUND((GREATEST(ma5,ma10,ma20,ma60) /
                       NULLIF(LEAST(ma5,ma10,ma20,ma60), 0) - 1) * 100, 2
                ) as spread_pct
            FROM ma
            WHERE trade_date = ?
              AND ma60 > 0
              AND GREATEST(ma5,ma10,ma20,ma60) /
                  NULLIF(LEAST(ma5,ma10,ma20,ma60), 0) - 1 <= ? / 100.0
            ORDER BY spread_pct, symbol
        """, [base, end_date, threshold_pct]).df()

        return df
    finally:
        conn.close()


def scan_volume_breakout(end_date: str, vol_multiplier: float = 2.0) -> pd.DataFrame:
    """
    放量突破扫描：价格突破 MA60 且成交量 > N 倍 20 日均量。
    """
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "daily_kline"):
            return pd.DataFrame()
        base = _build_ma_cte(end_date, 120)

        df = conn.execute("""
            WITH mav AS (
                SELECT symbol, trade_date, close, volume,
                    AVG(close) OVER w60 as ma60,
                    AVG(volume) OVER (PARTITION BY symbol ORDER BY trade_date
                        ROWS 19 PRECEDING) as avg_vol_20d
                FROM daily_kline
                WHERE trade_date >= ?
                WINDOW w60 AS (PARTITION BY symbol ORDER BY trade_date
                    ROWS 59 PRECEDING)
            )
            SELECT symbol,
                ROUND(close, 2) as close,
                ROUND(ma60, 2) as ma60,
                ROUND((close / NULLIF(ma60, 0) - 1) * 100, 2) as above_ma60_pct,
                ROUND(volume, 0) as volume,
                ROUND(avg_vol_20d, 0) as avg_vol_20d,
                ROUND(volume / NULLIF(avg_vol_20d, 0), 2) as vol_ratio
            FROM mav
            WHERE trade_date = ?
              AND close > ma60
              AND volume > avg_vol_20d * ?
              AND avg_vol_20d > 0 AND ma60 > 0
            ORDER BY vol_ratio DESC
        """, [base, end_date, vol_multiplier]).df()

        return df
    finally:
        conn.close()


def scan_new_high(end_date: str, n_days: int = 60) -> pd.DataFrame:
    """
    N 日新高扫描：当日收盘价 = N 日内最高收盘价。
    """
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "daily_kline"):
            return pd.DataFrame()
        base = (pd.to_datetime(end_date) - pd.Timedelta(days=n_days + 30)
                ).strftime("%Y-%m-%d")

        df = conn.execute("""
            WITH highs AS (
                SELECT symbol, trade_date, close,
                    MAX(close) OVER (PARTITION BY symbol ORDER BY trade_date
                        ROWS ? PRECEDING) as n_day_high
                FROM daily_kline
                WHERE trade_date >= ?
            )
            SELECT symbol,
                ROUND(close, 2) as close,
                ROUND(n_day_high, 2) as n_day_high
            FROM highs
            WHERE trade_date = ?
              AND close = n_day_high
              AND n_day_high > 0
            ORDER BY symbol
        """, [n_days - 1, base, end_date]).df()

        return df
    finally:
        conn.close()


def scan_new_low(end_date: str, n_days: int = 60) -> pd.DataFrame:
    """
    N 日新低扫描。
    """
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "daily_kline"):
            return pd.DataFrame()
        base = (pd.to_datetime(end_date) - pd.Timedelta(days=n_days + 30)
                ).strftime("%Y-%m-%d")

        df = conn.execute("""
            WITH lows AS (
                SELECT symbol, trade_date, close,
                    MIN(close) OVER (PARTITION BY symbol ORDER BY trade_date
                        ROWS ? PRECEDING) as n_day_low
                FROM daily_kline
                WHERE trade_date >= ?
            )
            SELECT symbol,
                ROUND(close, 2) as close,
                ROUND(n_day_low, 2) as n_day_low
            FROM lows
            WHERE trade_date = ?
              AND close = n_day_low
              AND n_day_low > 0
            ORDER BY symbol
        """, [n_days - 1, base, end_date]).df()

        return df
    finally:
        conn.close()


def run_all_patterns(end_date: str = None, **params) -> dict[str, pd.DataFrame]:
    """
    运行全部形态扫描。

    参数:
        end_date: 截止日期，None=最新交易日
        params: 透传给各扫描函数的参数，如 golden_cross_days=5, n_days=60

    返回:
        {"golden_cross": df, "death_cross": df, "ma_consolidation": df,
         "volume_breakout": df, "new_high": df, "new_low": df}
    """
    from .database import get_latest_trading_date

    if end_date is None:
        end_date = get_latest_trading_date()
        if end_date is None:
            return {}

    cat_names = {
        "golden_cross": "金叉",
        "death_cross": "死叉",
        "ma_consolidation": "均线粘合",
        "volume_breakout": "放量突破",
        "new_high": "N日新高",
        "new_low": "N日新低",
    }

    results = {}

    # 金叉
    try:
        gd = params.get("golden_cross_days", 10)
        df = scan_golden_cross(end_date, lookback_days=gd)
        if not df.empty:
            results[cat_names["golden_cross"]] = df
    except Exception:
        pass

    # 死叉
    try:
        dd = params.get("death_cross_days", 10)
        df = scan_death_cross(end_date, lookback_days=dd)
        if not df.empty:
            results[cat_names["death_cross"]] = df
    except Exception:
        pass

    # 均线粘合
    try:
        th = params.get("consolidation_threshold", 3.0)
        df = scan_ma_consolidation(end_date, threshold_pct=th)
        if not df.empty:
            results[cat_names["ma_consolidation"]] = df
    except Exception:
        pass

    # 放量突破
    try:
        vm = params.get("volume_multiplier", 2.0)
        df = scan_volume_breakout(end_date, vol_multiplier=vm)
        if not df.empty:
            results[cat_names["volume_breakout"]] = df
    except Exception:
        pass

    # 新高
    try:
        nd = params.get("n_days", 60)
        df = scan_new_high(end_date, n_days=nd)
        if not df.empty:
            label = f"N日新高({nd}d)"
            results[cat_names["new_high"]] = df
    except Exception:
        pass

    # 新低
    try:
        nd = params.get("n_days", 60)
        df = scan_new_low(end_date, n_days=nd)
        if not df.empty:
            results[cat_names["new_low"]] = df
    except Exception:
        pass

    return results
