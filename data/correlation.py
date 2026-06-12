"""
股票相关性分析：聚类、低相关组合推荐、对冲匹配
"""
import numpy as np
import pandas as pd
from .database import get_connection, _table_exists, get_latest_trading_date


def compute_full_correlation_matrix(
    symbols: list[str], start: str, end: str, min_days: int = 100
) -> pd.DataFrame:
    """
    计算全市场相关性矩阵（日收益率 Spearman 相关）。

    返回:
        DataFrame, index/columns = symbols, values = correlation
    """
    if len(symbols) < 2:
        return pd.DataFrame()

    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "daily_kline"):
            return pd.DataFrame()

        placeholders = ",".join(["?"] * len(symbols))
        df = conn.execute(f"""
            SELECT symbol, trade_date, close
            FROM daily_kline
            WHERE symbol IN ({placeholders})
              AND trade_date >= ?
              AND trade_date <= ?
            ORDER BY symbol, trade_date
        """, symbols + [start, end]).df()

        if df.empty:
            return pd.DataFrame()

        df["trade_date"] = pd.to_datetime(df["trade_date"])

        # Pivot to returns
        pivot = df.pivot(index="trade_date", columns="symbol", values="close")
        pivot = pivot.sort_index()

        # Filter columns with enough data
        valid = pivot.columns[pivot.notna().sum() >= min_days]
        returns = pivot[valid].pct_change().dropna(how="all")

        if len(returns.columns) < 2:
            return pd.DataFrame()

        return returns.corr(method="spearman")
    finally:
        conn.close()


def find_low_correlation_pairs(
    corr_matrix: pd.DataFrame, top_n: int = 20
) -> pd.DataFrame:
    """
    从相关性矩阵找出相关性最低的股票对。

    返回:
        DataFrame: stock_a, stock_b, correlation, rank
    """
    if corr_matrix.empty:
        return pd.DataFrame()

    symbols = corr_matrix.columns.tolist()
    pairs = []
    for i in range(len(symbols)):
        for j in range(i + 1, len(symbols)):
            corr_val = corr_matrix.iloc[i, j]
            if not pd.isna(corr_val):
                pairs.append({
                    "stock_a": symbols[i],
                    "stock_b": symbols[j],
                    "correlation": round(corr_val, 4),
                })

    pairs.sort(key=lambda x: x["correlation"])
    result = pd.DataFrame(pairs[:top_n])
    if not result.empty:
        result["rank"] = range(1, len(result) + 1)
    return result


def find_hedge_pairs(
    corr_matrix: pd.DataFrame, top_n: int = 10
) -> pd.DataFrame:
    """
    找出高负相关的对冲标的对（相关性 < -0.3）。

    返回:
        DataFrame: stock_a, stock_b, correlation, rank
    """
    if corr_matrix.empty:
        return pd.DataFrame()

    symbols = corr_matrix.columns.tolist()
    pairs = []
    for i in range(len(symbols)):
        for j in range(i + 1, len(symbols)):
            corr_val = corr_matrix.iloc[i, j]
            if not pd.isna(corr_val) and corr_val < -0.3:
                pairs.append({
                    "stock_a": symbols[i],
                    "stock_b": symbols[j],
                    "correlation": round(corr_val, 4),
                    "abs_corr": abs(corr_val),
                })

    pairs.sort(key=lambda x: x["abs_corr"], reverse=True)
    result = pd.DataFrame(pairs[:top_n])
    if not result.empty:
        result["rank"] = range(1, len(result) + 1)
        result = result.drop(columns=["abs_corr"])
    return result


def cluster_by_correlation(
    corr_matrix: pd.DataFrame, n_clusters: int = 5
) -> pd.DataFrame:
    """
    基于相关性矩阵进行层次聚类。

    返回:
        DataFrame: symbol, cluster_id
    """
    if corr_matrix.empty or len(corr_matrix) < n_clusters:
        return pd.DataFrame()

    from scipy.cluster.hierarchy import linkage, fcluster

    # 将相关性转为距离 (1 - |r|)
    dist = 1 - corr_matrix.abs()
    # 避免对角线 NaN
    np.fill_diagonal(dist.values, 0)

    linkage_matrix = linkage(dist, method="ward")
    clusters = fcluster(linkage_matrix, n_clusters, criterion="maxclust")

    result = pd.DataFrame({
        "symbol": corr_matrix.index.tolist(),
        "cluster": clusters,
    })
    return result.sort_values("cluster").reset_index(drop=True)


def compute_stock_distances(
    symbols: list[str], start: str, end: str, target: str
) -> pd.DataFrame:
    """
    计算目标股票与其他股票的相关性排名。

    返回:
        DataFrame: symbol, correlation, rank (按相关度升序，低相关排前面)
    """
    corr = compute_full_correlation_matrix(
        [target] + symbols, start, end
    )
    if corr.empty or target not in corr.columns:
        return pd.DataFrame()

    series = corr[target].dropna().drop(target, errors="ignore")
    series = series.sort_values()
    result = pd.DataFrame({
        "symbol": series.index,
        "correlation": series.values.round(4),
    })
    result["rank"] = range(1, len(result) + 1)
    return result.reset_index(drop=True)
