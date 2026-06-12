"""
行业板块数据分析模块 — 基于 DuckDB 的 DB 驱动行业轮动分析
"""
import pandas as pd
from .database import get_connection, _table_exists, upsert_stock_info


def populate_stock_industry() -> dict:
    """
    将申万行业分类填充到 stock_info.industry 列。
    通过 data.screener._load_industry_mapping() 获取映射。

    返回:
        {"updated": int, "total": int}
    """
    from data.screener import _load_industry_mapping

    mapping = _load_industry_mapping()
    if not mapping:
        return {"updated": 0, "total": 0, "error": "无法获取行业分类"}

    conn = get_connection()
    updated = 0
    try:
        # 确保 stock_info 表存在
        conn.execute("""
            CREATE TABLE IF NOT EXISTS stock_info (
                symbol      VARCHAR(10)   PRIMARY KEY,
                name        VARCHAR(50),
                market      VARCHAR(10),
                industry    VARCHAR(100),
                listed_date DATE,
                updated_at  TIMESTAMP     DEFAULT CURRENT_TIMESTAMP
            )
        """)
        for symbol, industries in mapping.items():
            if not isinstance(industries, list) or len(industries) == 0:
                continue
            # 第一项为申万一级行业，后续为细分。仅存一级行业。
            level1 = industries[0] if isinstance(industries[0], str) else str(industries[0])
            if not level1:
                continue
            try:
                conn.execute("""
                    INSERT OR REPLACE INTO stock_info (symbol, industry, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                """, [symbol, level1])
                updated += 1
            except Exception:
                continue
    finally:
        conn.close()

    return {"updated": updated, "total": len(mapping)}


def get_industry_list_from_db() -> list[str]:
    """从 stock_info 表获取所有唯一行业（一级）"""
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "stock_info"):
            return []
        r = conn.execute("""
            SELECT DISTINCT industry FROM stock_info
            WHERE industry IS NOT NULL AND industry != ''
            ORDER BY industry
        """).fetchall()
        return [row[0] for row in r if row[0]]
    finally:
        conn.close()


def get_industry_stocks_from_db(industry_name: str) -> list[str]:
    """获取某行业的所有成分股代码（模糊匹配）"""
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "stock_info"):
            return []
        r = conn.execute("""
            SELECT symbol FROM stock_info
            WHERE industry LIKE ?
            ORDER BY symbol
        """, [f"%{industry_name}%"]).fetchall()
        return [row[0] for row in r]
    finally:
        conn.close()


def build_industry_index(
    industry_name: str, start_date: str, end_date: str
) -> pd.DataFrame:
    """
    构建行业等权指数：对该行业所有成分股的 OHLCV 等权平均。

    返回:
        DataFrame: index=trade_date, columns=[open, high, low, close, volume, n_stocks]
    """
    stocks = get_industry_stocks_from_db(industry_name)
    if not stocks:
        return pd.DataFrame()

    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "daily_kline"):
            return pd.DataFrame()

        placeholders = ",".join(["?"] * len(stocks))
        df = conn.execute(f"""
            SELECT k.trade_date,
                AVG(k.open) as open,
                AVG(k.high) as high,
                AVG(k.low) as low,
                AVG(k.close) as close,
                SUM(k.volume) as volume,
                COUNT(DISTINCT k.symbol) as n_stocks
            FROM daily_kline k
            JOIN stock_info s ON k.symbol = s.symbol
            WHERE s.industry LIKE ?
              AND k.trade_date >= ?
              AND k.trade_date <= ?
            GROUP BY k.trade_date
            ORDER BY k.trade_date
        """, [f"%{industry_name}%", start_date, end_date]).df()

        if df.empty:
            return df

        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df = df.set_index("trade_date").sort_index()
        return df
    finally:
        conn.close()


def compute_industry_momentum(
    end_date: str = None, periods: list[int] | None = None
) -> pd.DataFrame:
    """
    计算全部行业的多周期动量排名。

    返回:
        DataFrame: industry, ret_5d, ret_10d, ret_20d, ret_60d, composite_momentum, rank
    """
    from .database import get_latest_trading_date

    if end_date is None:
        end_date = get_latest_trading_date()

    if periods is None:
        periods = [5, 10, 20, 60]

    industries = get_industry_list_from_db()
    if not industries:
        return pd.DataFrame()

    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "daily_kline"):
            return pd.DataFrame()

        base = (pd.to_datetime(end_date) - pd.Timedelta(days=120)
                ).strftime("%Y-%m-%d")

        # 对每个行业计算等权日线
        results = []
        for ind_name in industries:
            try:
                stocks = get_industry_stocks_from_db(ind_name)
                if len(stocks) < 3:
                    continue

                placeholders = ",".join(["?"] * len(stocks))
                df = conn.execute(f"""
                    WITH daily AS (
                        SELECT k.trade_date,
                            AVG(k.close) as close
                        FROM daily_kline k
                        JOIN stock_info s ON k.symbol = s.symbol
                        WHERE s.industry LIKE ?
                          AND k.trade_date >= ?
                        GROUP BY k.trade_date
                    ),
                    priced AS (
                        SELECT trade_date, close,
                            LAG(close, 5)  OVER (ORDER BY trade_date) as c_5d,
                            LAG(close, 10) OVER (ORDER BY trade_date) as c_10d,
                            LAG(close, 20) OVER (ORDER BY trade_date) as c_20d,
                            LAG(close, 60) OVER (ORDER BY trade_date) as c_60d
                        FROM daily
                    )
                    SELECT
                        ROUND((close / NULLIF(c_5d, 0) - 1) * 100, 2) as ret_5d,
                        ROUND((close / NULLIF(c_10d, 0) - 1) * 100, 2) as ret_10d,
                        ROUND((close / NULLIF(c_20d, 0) - 1) * 100, 2) as ret_20d,
                        ROUND((close / NULLIF(c_60d, 0) - 1) * 100, 2) as ret_60d
                    FROM priced
                    WHERE trade_date = ?
                """, [f"%{ind_name}%", base, end_date]).df()

                if not df.empty:
                    row = df.iloc[0].to_dict()
                    row["industry"] = ind_name
                    results.append(row)
            except Exception:
                continue

    finally:
        conn.close()

    if not results:
        return pd.DataFrame()

    result = pd.DataFrame(results)

    # 综合动量：等权各周期百分位排名
    for p in periods:
        col = f"ret_{p}d"
        if col in result.columns:
            rank_col = f"rank_{p}d"
            result[rank_col] = result[col].rank(pct=True) * 100

    rank_cols = [f"rank_{p}d" for p in periods if f"rank_{p}d" in result.columns]
    if rank_cols:
        result["composite_momentum"] = result[rank_cols].mean(axis=1).round(1)
    else:
        result["composite_momentum"] = 0

    result["rank"] = result["composite_momentum"].rank(ascending=False).astype(int)
    result = result.sort_values("rank")

    out_cols = ["industry", "rank", "composite_momentum"]
    for p in periods:
        if f"ret_{p}d" in result.columns:
            out_cols.append(f"ret_{p}d")
    return result[out_cols].reset_index(drop=True)


def compute_industry_rotation_heatmap(
    end_date: str = None, lookback_weeks: int = 12
) -> pd.DataFrame:
    """
    行业轮动热力图：每周各行业收益率矩阵。

    返回:
        DataFrame: index=industry_name, columns=week_ending_date, values=weekly_return%
    """
    from .database import get_latest_trading_date

    if end_date is None:
        end_date = get_latest_trading_date()

    industries = get_industry_list_from_db()
    if not industries:
        return pd.DataFrame()

    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "daily_kline"):
            return pd.DataFrame()

        # 取 lookback_weeks*7+5 天数据
        base = (pd.to_datetime(end_date) - pd.Timedelta(days=lookback_weeks * 7 + 5)
                ).strftime("%Y-%m-%d")

        all_data = []
        for ind_name in industries:
            try:
                stocks = get_industry_stocks_from_db(ind_name)
                if len(stocks) < 3:
                    continue

                placeholders = ",".join(["?"] * len(stocks))
                df = conn.execute(f"""
                    SELECT k.trade_date AS date, AVG(k.close) as close
                    FROM daily_kline k
                    JOIN stock_info s ON k.symbol = s.symbol
                    WHERE s.industry LIKE ?
                      AND k.trade_date >= ?
                    GROUP BY k.trade_date
                    ORDER BY k.trade_date
                """, [f"%{ind_name}%", base]).df()

                if df.empty or len(df) < 5:
                    continue

                df["date"] = pd.to_datetime(df["date"])
                df = df.set_index("date").sort_index()

                # 周线: 每周五的收盘价 → 周收益率
                weekly = df["close"].resample("W-FRI").last().dropna()
                if len(weekly) < 2:
                    continue
                weekly_ret = weekly.pct_change().dropna() * 100

                for d, v in weekly_ret.items():
                    if not pd.isna(v):
                        all_data.append({
                            "industry": ind_name,
                            "week": d.strftime("%Y-%m-%d"),
                            "return": round(v, 2),
                        })
            except Exception:
                continue

    finally:
        conn.close()

    if not all_data:
        return pd.DataFrame()

    heatmap = pd.DataFrame(all_data)
    pivot = heatmap.pivot(index="industry", columns="week", values="return")
    return pivot.sort_index()
