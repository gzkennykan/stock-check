"""
多因子选股评分模块 — 基于 DuckDB 的 SQL 窗口函数，在全市场股票上计算因子得分
此外包含实时快照维度的上涨值博率评分 _compute_upside_score
"""
import numpy as np
import pandas as pd
from .database import get_connection, _table_exists


def compute_momentum(end_date: str) -> pd.DataFrame:
    """
    计算全市场动量因子（5日/10日/20日/60日收益率）。

    返回:
        DataFrame: symbol, mom_5d, mom_10d, mom_20d, mom_60d
    """
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "daily_kline"):
            return pd.DataFrame()

        # 取 100 个日历日之前的数据，确保覆盖 60 个交易日
        base_date = (
            pd.to_datetime(end_date) - pd.Timedelta(days=100)
        ).strftime("%Y-%m-%d")

        df = conn.execute("""
            WITH priced AS (
                SELECT symbol, trade_date, close,
                    LAG(close, 5)  OVER (PARTITION BY symbol ORDER BY trade_date) as c_5d,
                    LAG(close, 10) OVER (PARTITION BY symbol ORDER BY trade_date) as c_10d,
                    LAG(close, 20) OVER (PARTITION BY symbol ORDER BY trade_date) as c_20d,
                    LAG(close, 60) OVER (PARTITION BY symbol ORDER BY trade_date) as c_60d
                FROM daily_kline
                WHERE trade_date >= ?
            )
            SELECT symbol,
                ROUND((close / NULLIF(c_5d, 0) - 1) * 100, 2) as mom_5d,
                ROUND((close / NULLIF(c_10d, 0) - 1) * 100, 2) as mom_10d,
                ROUND((close / NULLIF(c_20d, 0) - 1) * 100, 2) as mom_20d,
                ROUND((close / NULLIF(c_60d, 0) - 1) * 100, 2) as mom_60d
            FROM priced
            WHERE trade_date = ?
              AND c_5d IS NOT NULL
              AND c_20d IS NOT NULL
        """, [base_date, end_date]).df()

        return df
    finally:
        conn.close()


def compute_volatility(end_date: str, window: int = 20) -> pd.DataFrame:
    """
    计算全市场波动率因子（滚动 std × 年化 √252）。

    返回:
        DataFrame: symbol, vol_20d (年化波动率 %), vol_rank_score (0-100)
    """
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "daily_kline"):
            return pd.DataFrame()

        base = pd.to_datetime(end_date) - pd.Timedelta(days=60)
        base = base.strftime("%Y-%m-%d")

        df = conn.execute("""
            WITH rets AS (
                SELECT symbol, trade_date,
                    (close - LAG(close, 1) OVER (PARTITION BY symbol ORDER BY trade_date))
                    / NULLIF(LAG(close, 1) OVER (PARTITION BY symbol ORDER BY trade_date), 0) as daily_ret
                FROM daily_kline
                WHERE trade_date >= ?
            )
            SELECT symbol, ROUND(STDDEV_SAMP(daily_ret) * SQRT(252) * 100, 2) as vol_20d
            FROM rets
            WHERE trade_date <= ?
            GROUP BY symbol
            HAVING COUNT(*) >= 15
        """, [base, end_date]).df()

        if not df.empty:
            df["vol_rank_score"] = (
                (1 - df["vol_20d"].rank(pct=True)) * 100
            ).round(1)
        return df
    finally:
        conn.close()


def compute_volume_score(end_date: str) -> pd.DataFrame:
    """
    计算成交量/流动性因子（最近 5 日平均相对 20 日平均的比值）。

    返回:
        DataFrame: symbol, vol5_ratio (0-200 range), volume_rank_score
    """
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "daily_kline"):
            return pd.DataFrame()

        base = (pd.to_datetime(end_date) - pd.Timedelta(days=60)
                ).strftime("%Y-%m-%d")
        vol5_start = (pd.to_datetime(end_date) - pd.Timedelta(days=7)
                      ).strftime("%Y-%m-%d")

        df = conn.execute("""
            WITH vol_avg AS (
                SELECT symbol, trade_date, volume,
                    AVG(volume) OVER (PARTITION BY symbol ORDER BY trade_date
                        ROWS 19 PRECEDING) as avg_vol_20d
                FROM daily_kline
                WHERE trade_date >= ?
            ),
            rel_vol AS (
                SELECT symbol, trade_date, volume, avg_vol_20d,
                    volume / NULLIF(avg_vol_20d, 0) as rel_vol
                FROM vol_avg
                WHERE trade_date <= ?
                  AND avg_vol_20d > 0
            )
            SELECT symbol,
                ROUND(AVG(rel_vol), 2) as vol5_ratio
            FROM rel_vol
            WHERE trade_date >= ?
            GROUP BY symbol
            HAVING COUNT(*) >= 3
        """, [base, end_date, vol5_start]).df()

        if not df.empty:
            # 活跃度得分: 成交量适中最优 (0.5-2.0 区间给高分)
            df["volume_rank_score"] = df["vol5_ratio"].apply(
                lambda x: max(0, min(100, 100 - abs(1.5 - x) * 60))
            ).round(1)
        return df
    finally:
        conn.close()


def compute_trend_score(end_date: str) -> pd.DataFrame:
    """
    计算趋势强度因子（收盘价距 MA20/MA60 的偏离度）。

    返回:
        DataFrame: symbol, ma20_dist (%), ma60_dist (%), trend_score
    """
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "daily_kline"):
            return pd.DataFrame()

        base = (pd.to_datetime(end_date) - pd.Timedelta(days=120)
                ).strftime("%Y-%m-%d")

        df = conn.execute("""
            WITH ma_data AS (
                SELECT symbol, trade_date, close,
                    AVG(close) OVER w20 as ma20,
                    AVG(close) OVER w60 as ma60
                FROM daily_kline
                WHERE trade_date >= ?
                WINDOW
                    w20 AS (PARTITION BY symbol ORDER BY trade_date ROWS 19 PRECEDING),
                    w60 AS (PARTITION BY symbol ORDER BY trade_date ROWS 59 PRECEDING)
            )
            SELECT symbol,
                ROUND((close / NULLIF(ma20, 0) - 1) * 100, 2) as ma20_dist,
                ROUND((close / NULLIF(ma60, 0) - 1) * 100, 2) as ma60_dist
            FROM ma_data
            WHERE trade_date = ?
              AND ma20 > 0 AND ma60 > 0
        """, [base, end_date]).df()

        if not df.empty:
            # 趋势得分：价格在均线上方给高分，下方给低分
            df["trend_score"] = df.apply(
                lambda r: round(
                    min(100, max(0, 50 + r["ma20_dist"] * 3 + r["ma60_dist"] * 1.5)),
                    1
                ), axis=1
            )
        return df
    finally:
        conn.close()


def compute_drawdown_score(end_date: str) -> pd.DataFrame:
    """
    计算回撤因子（最近 60 日最大回撤）。

    返回:
        DataFrame: symbol, max_dd_60d (%), dd_rank_score
    """
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "daily_kline"):
            return pd.DataFrame()

        base = (pd.to_datetime(end_date) - pd.Timedelta(days=120)
                ).strftime("%Y-%m-%d")

        df = conn.execute("""
            WITH rolling_max AS (
                SELECT symbol, trade_date, close,
                    MAX(close) OVER (PARTITION BY symbol ORDER BY trade_date
                        ROWS 59 PRECEDING) as peak
                FROM daily_kline
                WHERE trade_date >= ?
            ),
            drawdowns AS (
                SELECT symbol, trade_date,
                    (close / NULLIF(peak, 0) - 1) * 100 as dd
                FROM rolling_max
            ),
            max_dd AS (
                SELECT symbol, MIN(dd) as max_dd_60d
                FROM drawdowns
                WHERE trade_date <= ?
                GROUP BY symbol
                HAVING COUNT(*) >= 30
            )
            SELECT symbol, ROUND(max_dd_60d, 2) as max_dd_60d
            FROM max_dd
        """, [base, end_date]).df()

        if not df.empty:
            # 回撤越小分越高
            df["dd_rank_score"] = (
                (1 - (-df["max_dd_60d"]).rank(pct=True)) * 100
            ).round(1)
        return df
    finally:
        conn.close()


def compute_composite_ranking(
    end_date: str = None,
    weights: dict = None,
) -> pd.DataFrame:
    """
    综合多因子排名：动量、波动率、成交量、趋势、回撤。

    参数:
        end_date:    截止日期，None=最新交易日
        weights:     因子权重 dict，默认:
                      momentum=0.30, volatility=0.15, volume=0.20,
                      trend=0.20, drawdown=0.15

    返回:
        DataFrame: symbol, mom_score, vol_score, vol_raw, trend_score,
                   dd_score, composite, rank
    """
    from .database import get_latest_trading_date

    if end_date is None:
        end_date = get_latest_trading_date()
        if end_date is None:
            return pd.DataFrame()

    if weights is None:
        weights = {
            "momentum": 0.30,
            "volatility": 0.15,
            "volume": 0.20,
            "trend": 0.20,
            "drawdown": 0.15,
        }

    # 并行计算各因子
    mom = compute_momentum(end_date)
    vol = compute_volatility(end_date)
    vol_s = compute_volume_score(end_date)
    trend = compute_trend_score(end_date)
    dd = compute_drawdown_score(end_date)

    # 合并
    merged = mom[["symbol", "mom_5d", "mom_10d", "mom_20d", "mom_60d"]].copy()

    # 动量得分 = 多周期平均收益率的百分位排名
    if not mom.empty:
        # 综合动量: 5d*0.4 + 10d*0.3 + 20d*0.2 + 60d*0.1
        merged["mom_raw"] = (
            mom["mom_5d"].fillna(0) * 0.4 +
            mom["mom_10d"].fillna(0) * 0.3 +
            mom["mom_20d"].fillna(0) * 0.2 +
            mom["mom_60d"].fillna(0) * 0.1
        )
        merged["mom_score"] = merged["mom_raw"].rank(pct=True).clip(0, 1) * 100

    # 波动率得分
    if not vol.empty:
        merged = merged.merge(
            vol[["symbol", "vol_rank_score"]].rename(columns={"vol_rank_score": "vol_score"}),
            on="symbol", how="left"
        )

    # 成交量得分
    if not vol_s.empty:
        merged = merged.merge(
            vol_s[["symbol", "vol5_ratio", "volume_rank_score"]].rename(
                columns={"vol5_ratio": "vol5_ratio", "volume_rank_score": "vol_score_raw"}
            ),
            on="symbol", how="left"
        )

    # 趋势得分
    if not trend.empty:
        merged = merged.merge(
            trend[["symbol", "ma20_dist", "ma60_dist", "trend_score"]],
            on="symbol", how="left"
        )

    # 回撤得分
    if not dd.empty:
        merged = merged.merge(
            dd[["symbol", "max_dd_60d", "dd_rank_score"]].rename(
                columns={"dd_rank_score": "dd_score"}
            ),
            on="symbol", how="left"
        )

    # 统一填充缺失得分
    for col in ["mom_score", "vol_score", "vol_score_raw", "trend_score", "dd_score"]:
        if col in merged.columns:
            merged[col] = merged[col].fillna(50)  # 中庸分

    # 综合得分
    merged["composite"] = (
        merged.get("mom_score", 50) * weights["momentum"] +
        merged.get("vol_score", 50) * weights["volatility"] +
        merged.get("vol_score_raw", 50) * weights["volume"] +
        merged.get("trend_score", 50) * weights["trend"] +
        merged.get("dd_score", 50) * weights["drawdown"]
    ).round(1)

    merged["rank"] = merged["composite"].rank(ascending=False).astype(int)
    merged = merged.sort_values("rank")

    # 精简输出列
    out_cols = [
        "symbol", "rank", "composite",
        "mom_score", "mom_5d", "mom_20d",
        "vol_score", "vol_score_raw", "vol5_ratio",
        "trend_score", "ma20_dist", "ma60_dist",
        "dd_score", "max_dd_60d",
    ]
    out_cols = [c for c in out_cols if c in merged.columns]
    return merged[out_cols].reset_index(drop=True)


def compute_upside_score(df: pd.DataFrame) -> pd.Series:
    """上涨值博率评分（0-100），基于实时快照多因子。
    因子: 资金流入(27%) + 净流入占比(17%) + 涨幅合理性(16%) + 技术面(15%) +
          换手(10%) + 盈利能力(10%) + 估值(5%)
    """
    idx = df.index

    # 1. 资金流入强度 (0-27)
    total_inflow = df.get("main_capital", pd.Series(0, index=idx)).fillna(0) + \
                   df.get("hot_money", pd.Series(0, index=idx)).fillna(0)
    inflow_score = (np.log10(total_inflow.clip(lower=0) + 1) / 9.0 * 27).clip(0, 27)

    # 2. 净流入占比 (0-17)
    net_pct = df.get("net_flow_pct", pd.Series(0, index=idx)).fillna(0).clip(0, 20)
    pct_score = (net_pct / 20 * 17).clip(0, 17)

    # 3. 涨幅合理性 (0-16)
    pct_change = df.get("pct_change", pd.Series(0, index=idx)).fillna(0)
    chg_score = pd.Series(0.0, index=idx)
    chg_score[(pct_change >= 0) & (pct_change < 3)] = 16
    chg_score[(pct_change >= 3) & (pct_change < 5)] = 12
    chg_score[(pct_change >= -2) & (pct_change < 0)] = 9
    chg_score[(pct_change >= 5) & (pct_change < 8)] = 6
    chg_score[(pct_change >= -5) & (pct_change < -2)] = 4
    chg_score[pct_change >= 8] = 2
    chg_score[pct_change < -5] = 2

    # 4. 技术面 (0-15)
    high = df.get("high", pd.Series(0, index=idx)).fillna(0)
    low = df.get("low", pd.Series(0, index=idx)).fillna(0)
    price = df.get("price", pd.Series(0, index=idx)).fillna(0)
    prev_close = df.get("prev_close", pd.Series(0, index=idx)).fillna(0)
    tr = df.get("turnover_rate", pd.Series(0, index=idx)).fillna(0)
    main_cap = df.get("main_capital", pd.Series(0, index=idx)).fillna(0)

    hl_range = (high - low).replace(0, np.nan)
    intraday_strength = ((price - low) / hl_range * 4).fillna(2).clip(0, 4)

    amplitude = ((high - low) / prev_close.replace(0, np.nan) * 100).fillna(0)
    amp_score = pd.Series(0.0, index=idx)
    amp_score[amplitude.between(2, 8)] = 3
    amp_score[amplitude.between(1, 2) | amplitude.between(8, 12)] = 2
    amp_score[amplitude.between(0.5, 1)] = 1

    is_up = pct_change >= 0
    is_down = pct_change < 0
    high_tr = tr >= 3
    mid_tr = (tr >= 1) & (tr < 3)
    low_tr = tr < 1
    vp_score = pd.Series(1.0, index=idx)
    vp_score[is_up & high_tr] = 4
    vp_score[is_up & mid_tr] = 3
    vp_score[is_up & low_tr] = 1
    vp_score[is_down & low_tr] = 2
    vp_score[is_down & mid_tr] = 1
    vp_score[is_down & high_tr] = 0

    main_in = main_cap > 0
    main_out = main_cap < 0
    div_score = pd.Series(2.0, index=idx)
    div_score[is_up & main_in] = 4
    div_score[is_up & main_out] = 0
    div_score[is_down & main_in] = 3
    div_score[is_down & main_out] = 1

    # 5. 换手活跃度 (0-10)
    tr_score = pd.Series(0.0, index=idx)
    tr_score[tr.between(2, 5)] = 10
    tr_score[tr.between(1, 2) | tr.between(5, 8)] = 7
    tr_score[tr.between(0.5, 1) | tr.between(8, 12)] = 4
    tr_score[tr.between(0.2, 0.5) | tr.between(12, 20)] = 1

    # 6. 盈利能力 (0-10)
    roe = df.get("roe", pd.Series(0, index=idx)).fillna(0)
    profit_growth = df.get("profit_growth", pd.Series(0, index=idx)).fillna(0)
    gross_margin = df.get("gross_margin", pd.Series(0, index=idx)).fillna(0)
    roe_score = pd.Series(0.0, index=idx)
    roe_score[roe > 15] = 4
    roe_score[roe.between(10, 15)] = 3
    roe_score[roe.between(5, 10)] = 2
    roe_score[roe.between(0, 5)] = 1
    growth_score = pd.Series(0.0, index=idx)
    growth_score[profit_growth > 50] = 3
    growth_score[profit_growth.between(20, 50)] = 2
    growth_score[profit_growth.between(0, 20)] = 1
    margin_score = pd.Series(0.0, index=idx)
    margin_score[gross_margin > 40] = 3
    margin_score[gross_margin.between(20, 40)] = 2
    margin_score[gross_margin.between(10, 20)] = 1

    # 7. 估值 (0-5)
    pe = df.get("pe", pd.Series(0, index=idx)).fillna(0)
    pe_score = pd.Series(0.0, index=idx)
    pe_score[(pe > 0) & (pe < 30)] = 5
    pe_score[(pe >= 30) & (pe < 60)] = 3
    pe_score[(pe >= 60) & (pe < 100)] = 1

    total = (inflow_score + pct_score + chg_score + intraday_strength +
             amp_score + vp_score + div_score + tr_score + roe_score + growth_score +
             margin_score + pe_score)
    return total.round(1)
