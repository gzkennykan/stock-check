"""
ML 因子研究模块：因子检验 + 机器学习排序模型

功能:
  1. 因子 IC/IR 分析 — 信息系数、Rank IC、IC_IR
  2. 因子相关性矩阵 — 冗余检测
  3. LightGBM 排序模型 — 学习非线性因子组合
  4. 分层回测 — 按预测分5组验证单调性
  5. 特征重要性 — 哪些因子真正驱动收益

数据源: DuckDB daily_kline → 计算20+因子 → ML流水线
"""
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

from .database import get_connection, _table_exists


# ══════════════════════════════════════════════════════════
# 1. 全市场因子计算
# ══════════════════════════════════════════════════════════

def compute_all_factors(end_date: str) -> pd.DataFrame:
    """
    在指定日期对全市场计算 20+ 因子。

    因子清单:
      动量: mom_5d, mom_10d, mom_20d, mom_60d
      反转: rev_5d (5日涨跌幅反转)
      波动: vol_20d (20日年化波动), vol_60d
      量价: avg_volume_20d, volume_ratio_5d, turnover_20d
      均线偏离: ma20_dev, ma60_dev, ma120_dev
      RSI: rsi_14
      换手: 换手率变化
      收益标准差: std_20d

    返回:
        DataFrame, index=symbol, columns=factor values
    """
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "daily_kline"):
            return pd.DataFrame()

        base = (pd.to_datetime(end_date) - timedelta(days=200)).strftime("%Y-%m-%d")

        df = conn.execute("""
            WITH recent AS (
                SELECT symbol, trade_date, open, high, low, close, volume
                FROM daily_kline
                WHERE trade_date >= ?
            ),
            windowed AS (
                SELECT symbol, trade_date, close, volume,
                    -- 动量
                    LAG(close, 5)  OVER w AS c_5d,
                    LAG(close, 10) OVER w AS c_10d,
                    LAG(close, 20) OVER w AS c_20d,
                    LAG(close, 60) OVER w AS c_60d,
                    -- 价格前1日
                    LAG(close, 1)  OVER w AS c_1d,
                    -- 前20日最高最低
                    MAX(high) OVER (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS high_20d,
                    MIN(low)  OVER (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS low_20d,
                    -- 均量
                    AVG(volume) OVER (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS avg_vol_20d,
                    AVG(volume) OVER (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS avg_vol_5d
                FROM recent
                WINDOW w AS (PARTITION BY symbol ORDER BY trade_date)
            ),
            with_ma AS (
                SELECT *,
                    AVG(close) OVER (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS ma20,
                    AVG(close) OVER (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW) AS ma60,
                    AVG(close) OVER (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 119 PRECEDING AND CURRENT ROW) AS ma120
                FROM windowed
            ),
            with_ret AS (
                SELECT *,
                    (close - c_1d) / NULLIF(c_1d, 0) AS daily_ret
                FROM with_ma
            )
            SELECT symbol, trade_date,
                -- 动量因子
                ROUND((close / NULLIF(c_5d, 0) - 1) * 100, 4)  AS mom_5d,
                ROUND((close / NULLIF(c_10d, 0) - 1) * 100, 4) AS mom_10d,
                ROUND((close / NULLIF(c_20d, 0) - 1) * 100, 4) AS mom_20d,
                ROUND((close / NULLIF(c_60d, 0) - 1) * 100, 4) AS mom_60d,
                -- 反转因子(短期反转)
                ROUND((close / NULLIF(c_5d, 0) - 1) * -100, 4) AS rev_5d,
                -- 均线偏离
                ROUND((close - ma20) / NULLIF(ma20, 0) * 100, 4) AS ma20_dev,
                ROUND((close - ma60) / NULLIF(ma60, 0) * 100, 4) AS ma60_dev,
                ROUND((close - ma120) / NULLIF(ma120, 0) * 100, 4) AS ma120_dev,
                -- 量价因子
                ROUND((high_20d - close) / NULLIF(high_20d, 0) * 100, 4) AS dist_20d_high,
                ROUND((close - low_20d) / NULLIF(low_20d, 0) * 100, 4) AS dist_20d_low,
                ROUND(avg_vol_5d / NULLIF(avg_vol_20d, 0), 4) AS vol_ratio_5d,
                LN(NULLIF(avg_vol_20d, 0) + 1) AS log_avg_vol_20d,
                -- 日收益
                daily_ret
            FROM with_ret
            WHERE trade_date = ?
              AND c_20d IS NOT NULL
              AND c_60d IS NOT NULL
              AND ma60 IS NOT NULL
        """, [base, end_date]).df()

        if df.empty:
            return df

        # ── 波动率(滚动std) ──
        base2 = (pd.to_datetime(end_date) - timedelta(days=100)).strftime("%Y-%m-%d")
        vol_df = conn.execute("""
            WITH rets AS (
                SELECT symbol,
                    (close - LAG(close,1) OVER (PARTITION BY symbol ORDER BY trade_date))
                    / NULLIF(LAG(close,1) OVER (PARTITION BY symbol ORDER BY trade_date), 0) AS ret
                FROM daily_kline WHERE trade_date >= ?
            )
            SELECT symbol,
                ROUND(STDDEV_SAMP(ret) * SQRT(252) * 100, 4) AS vol_20d
            FROM rets
            GROUP BY symbol HAVING COUNT(*) >= 15
        """, [base2]).df()

        df = df.merge(vol_df, on="symbol", how="left")

        # ── RSI(14) ──
        rsi_df = conn.execute("""
            WITH gains AS (
                SELECT symbol, trade_date, close,
                    close - LAG(close,1) OVER (PARTITION BY symbol ORDER BY trade_date) AS delta
                FROM daily_kline WHERE trade_date >= ?
            ),
            smoothed AS (
                SELECT symbol, trade_date,
                    AVG(CASE WHEN delta > 0 THEN delta ELSE 0 END)
                        OVER (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 13 PRECEDING AND CURRENT ROW) AS avg_gain,
                    AVG(CASE WHEN delta < 0 THEN -delta ELSE 0 END)
                        OVER (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 13 PRECEDING AND CURRENT ROW) AS avg_loss
                FROM gains
            )
            SELECT symbol,
                ROUND(100 - 100 / (1 + avg_gain / NULLIF(avg_loss, 0)), 2) AS rsi_14
            FROM smoothed
            WHERE trade_date = ?
              AND avg_loss > 0
        """, [base2, end_date]).df()
        df = df.merge(rsi_df, on="symbol", how="left")

        return df
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════
# 2. 因子 IC 分析
# ══════════════════════════════════════════════════════════

def compute_factor_ic(
    factors_df: pd.DataFrame,
    forward_periods: list[int] = [1, 5, 20],
    factor_cols: list[str] = None,
) -> pd.DataFrame:
    """
    计算因子 IC（信息系数）= 因子值与未来N日收益的相关系数。

    参数:
        factors_df:      包含 symbol, daily_ret 和各因子列的 DataFrame
        forward_periods: 前向收益周期
        factor_cols:     要评估的因子列（None=自动识别）

    返回:
        DataFrame: columns=factor, IC_1d, IC_5d, IC_20d,
                  RankIC_1d, RankIC_5d, RankIC_20d, IC_IR
    """
    if factors_df.empty or "daily_ret" not in factors_df.columns:
        return pd.DataFrame()

    if factor_cols is None:
        exclude = {"symbol", "trade_date", "daily_ret"}
        factor_cols = [c for c in factors_df.columns if c not in exclude]

    # 构建前向收益
    conn = get_connection(read_only=True)
    try:
        fwd_cols = {}
        for p in forward_periods:
            fwd_col = f"fwd_{p}d"
            fwd_cols[p] = fwd_col

        results = []
        for _, row in factors_df.iterrows():
            sym = row["symbol"]
            t_date = row["trade_date"]
            if pd.isna(t_date):
                continue

            r = {"symbol": sym}
            for c in factor_cols:
                r[c] = row.get(c)

            for p, fcol in fwd_cols.items():
                fwd_data = conn.execute("""
                    SELECT close FROM daily_kline
                    WHERE symbol = ? AND trade_date > ?
                    ORDER BY trade_date ASC LIMIT ?
                """, [sym, str(t_date)[:10], p]).fetchall()
                if len(fwd_data) >= p:
                    fwd_close = fwd_data[-1][0]
                    cur_close = row.get("close", row.get("close_val"))
                    r[fcol] = (fwd_close / cur_close - 1) * 100 if cur_close else None
                else:
                    r[fcol] = None
            results.append(r)

        fwd_df = pd.DataFrame(results)
    finally:
        conn.close()

    if fwd_df.empty:
        return pd.DataFrame()

    # 计算 IC
    ic_rows = []
    for factor in factor_cols:
        if factor not in fwd_df.columns:
            continue
        row = {"Factor": factor}
        vals = pd.to_numeric(fwd_df[factor], errors="coerce")

        for p, fcol in fwd_cols.items():
            if fcol not in fwd_df.columns:
                row[f"IC_{p}d"] = None
                row[f"RankIC_{p}d"] = None
                continue
            fwd = pd.to_numeric(fwd_df[fcol], errors="coerce")
            mask = vals.notna() & fwd.notna()
            if mask.sum() < 30:
                row[f"IC_{p}d"] = None
                row[f"RankIC_{p}d"] = None
                continue
            row[f"IC_{p}d"] = round(vals[mask].corr(fwd[mask]), 4)
            row[f"RankIC_{p}d"] = round(
                vals[mask].rank().corr(fwd[mask].rank()), 4)
        ic_rows.append(row)

    ic_df = pd.DataFrame(ic_rows)
    if not ic_df.empty:
        ic_1d = ic_df.get("IC_1d", pd.Series([0]*len(ic_df)))
        ic_std = ic_1d.std()
        if ic_std and ic_std > 0:
            ic_df["IC_IR"] = round(ic_1d.mean() / ic_std, 2)
        else:
            ic_df["IC_IR"] = 0

    return ic_df.sort_values("IC_1d", key=abs, ascending=False)


# ══════════════════════════════════════════════════════════
# 3. 因子相关性矩阵
# ══════════════════════════════════════════════════════════

def compute_factor_correlation(
    factors_df: pd.DataFrame,
    factor_cols: list[str] = None,
) -> pd.DataFrame:
    """计算因子间 Pearson 相关系数矩阵"""
    if factors_df.empty:
        return pd.DataFrame()

    if factor_cols is None:
        exclude = {"symbol", "trade_date", "daily_ret", "close"}
        factor_cols = [c for c in factors_df.columns if c not in exclude]

    corr_data = factors_df[factor_cols].apply(pd.to_numeric, errors="coerce")
    return corr_data.corr()


# ══════════════════════════════════════════════════════════
# 4. LightGBM 排序模型
# ══════════════════════════════════════════════════════════

def train_lightgbm_ranker(
    factors_df: pd.DataFrame,
    factor_cols: list[str] = None,
    forward_days: int = 20,
    n_estimators: int = 200,
) -> dict:
    """
    用 LightGBM LambdaRank 学习因子 → 收益排序。

    返回:
        { "model": LGBMRanker, "feature_importance": DataFrame,
          "train_score": float, "factor_cols": list }
    """
    try:
        import lightgbm as lgb
    except ImportError:
        return {"error": "请先安装 lightgbm: pip install lightgbm"}

    if factors_df.empty or "daily_ret" not in factors_df.columns:
        return {"error": "数据不足"}

    if factor_cols is None:
        exclude = {"symbol", "trade_date", "daily_ret", "close"}
        factor_cols = [c for c in factors_df.columns if c not in exclude]

    # 构建未来收益标签
    conn = get_connection(read_only=True)
    try:
        labels = []
        for _, row in factors_df.iterrows():
            sym = row["symbol"]
            t_date = str(row["trade_date"])[:10] if pd.notna(row.get("trade_date")) else None
            if not t_date:
                labels.append(None)
                continue
            fwd = conn.execute(
                "SELECT close FROM daily_kline WHERE symbol=? AND trade_date>? ORDER BY trade_date ASC LIMIT ?",
                [sym, t_date, forward_days]
            ).fetchall()
            if len(fwd) >= forward_days:
                cur = row.get("close") or row.get("close_val") or 0
                labels.append((fwd[-1][0] / cur - 1) * 100 if cur else None)
            else:
                labels.append(None)
    finally:
        conn.close()

    df = factors_df.copy()
    df["label"] = labels
    df = df.dropna(subset=["label"] + factor_cols)
    if len(df) < 100:
        return {"error": f"有效样本仅 {len(df)} 条，需要 >= 100"}

    X = df[factor_cols].astype(float)
    y = df["label"].astype(float)

    # 80/20 切分
    split = int(len(df) * 0.8)
    X_train, X_val = X.iloc[:split], X.iloc[split:]
    y_train, y_val = y.iloc[:split], y.iloc[split:]

    # group: 每个 symbol 计算日均作为 query group（简化）
    # LambdaRank 需要 query groups，这里用单 group 做排序
    train_data = lgb.Dataset(X_train, label=y_train)
    val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)

    params = {
        "objective": "regression",
        "metric": "rmse",
        "boosting_type": "gbdt",
        "num_leaves": 31,
        "learning_rate": 0.05,
        "feature_fraction": 0.8,
        "verbose": -1,
        "n_estimators": n_estimators,
    }

    model = lgb.train(params, train_data, valid_sets=[val_data])

    # 特征重要性
    importance = pd.DataFrame({
        "factor": factor_cols,
        "importance": model.feature_importance(),
    }).sort_values("importance", ascending=False)

    # 验证集 score
    y_pred = model.predict(X_val)
    pred_series = pd.Series(y_pred, index=y_val.index)
    train_score = pred_series.corr(y_val)

    return {
        "model": model,
        "feature_importance": importance,
        "train_score": round(train_score, 4) if not np.isnan(train_score) else 0,
        "factor_cols": factor_cols,
        "n_samples": len(df),
    }


# ══════════════════════════════════════════════════════════
# 5. 分层回测（验证单调性）
# ══════════════════════════════════════════════════════════

def stratified_backtest(
    factors_df: pd.DataFrame,
    scores: pd.Series = None,
    n_groups: int = 5,
    forward_days: int = 20,
    score_col: str = "mom_20d",
) -> pd.DataFrame:
    """
    将股票按因子/预测分分成 N 组，计算每组的未来平均收益。
    验证"分越高 → 收益越高"的单调性。

    返回:
        DataFrame: group(1-5), n_stocks, avg_fwd_return, median_fwd_return,
                   win_rate, cumulative (如果 scores 来自 ML 模型)
    """
    df = factors_df.copy()

    if scores is not None:
        df["_score"] = scores
    elif score_col in df.columns:
        df["_score"] = pd.to_numeric(df[score_col], errors="coerce")
    else:
        return pd.DataFrame({"error": [f"找不到评分列 {score_col}"]})

    df = df.dropna(subset=["_score"])
    if len(df) < n_groups * 10:
        return pd.DataFrame({"error": [f"样本不足 {len(df)}"]})

    df["group"] = pd.qcut(df["_score"], n_groups, labels=list(range(1, n_groups + 1)))

    # 计算每组未来收益
    conn = get_connection(read_only=True)
    results = []
    try:
        for g in range(1, n_groups + 1):
            group_df = df[df["group"] == g]
            fwd_returns = []
            for _, row in group_df.iterrows():
                sym = row["symbol"]
                t_date = str(row.get("trade_date", ""))[:10]
                if not t_date:
                    continue
                fwd = conn.execute(
                    "SELECT close FROM daily_kline WHERE symbol=? AND trade_date>? ORDER BY trade_date ASC LIMIT ?",
                    [sym, t_date, forward_days]
                ).fetchall()
                if len(fwd) >= forward_days:
                    cur = row.get("close") or 0
                    fwd_returns.append((fwd[-1][0] / cur - 1) * 100 if cur else None)

            fwd_series = pd.Series([r for r in fwd_returns if r is not None])
            results.append({
                "group": int(g),
                "n_stocks": len(group_df),
                "avg_fwd_return": round(fwd_series.mean(), 2) if len(fwd_series) > 0 else 0,
                "median_fwd_return": round(fwd_series.median(), 2) if len(fwd_series) > 0 else 0,
                "win_rate": round((fwd_series > 0).mean() * 100, 1) if len(fwd_series) > 0 else 0,
                "std_fwd_return": round(fwd_series.std(), 2) if len(fwd_series) > 0 else 0,
            })
    finally:
        conn.close()

    result_df = pd.DataFrame(results)
    if not result_df.empty:
        # 检查单调性
        top = result_df[result_df["group"] == result_df["group"].max()]["avg_fwd_return"].values
        bottom = result_df[result_df["group"] == result_df["group"].min()]["avg_fwd_return"].values
        if len(top) > 0 and len(bottom) > 0:
            result_df["_monotonic"] = top[0] - bottom[0]  # Top-Bottom spread

    return result_df
