"""
筹码分布（换手成本分布）模块 — 三角形分布法

原理:
  每个交易日，当日成交的筹码在 [最低价, 最高价] 区间内按三角形分布，
  峰值位于收盘价附近；以当日换手率加权，且每日按 (1 - 当日换手率) 衰减
  （老筹码被新成交"洗掉"）。叠加最近 N 个交易日即可得到
  「价格 → 筹码占比」的成本分布曲线。

数据源:
  - 前复权日线 (daily_kline)：价格 + 成交量 + 成交额
  - 换手率 (fund_flow_daily.turnover_rate)：仅约 11 天快照，
    用于估算流通股本并反推整段历史换手率；无数据时退化为按成交量加权。

输出:
  - cost_df:   (price_bin, chip_pct, cum_pct) 分布曲线
  - 平均成本 / 获利盘% / 90%成本区(低,高) / 峰值成本 / 套牢盘%
"""
import numpy as np
import pandas as pd

from .database import get_connection, _table_exists


def _fetch_kline(symbol: str, days: int) -> pd.DataFrame:
    """取单只股票最近 N 个交易日的前复权日线（含成交额），按日期升序。"""
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "daily_kline"):
            return pd.DataFrame()
        df = conn.execute("""
            SELECT trade_date, open, high, low, close, volume, amount
            FROM daily_kline
            WHERE symbol = ?
            ORDER BY trade_date DESC
            LIMIT ?
        """, [str(symbol).strip().zfill(6), days]).df()
        if df.empty:
            return df
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df = df.sort_values("trade_date").reset_index(drop=True)
        return df
    finally:
        conn.close()


def _estimate_float_shares(symbol: str) -> float | None:
    """
    用资金流快照的换手率估算流通股本（股）。

    流通股本 ≈ 当日成交量(股) / (当日换手率% / 100)，取中位数。
    返回 None 表示无可用数据。
    """
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "fund_flow_daily"):
            return None
        df = conn.execute("""
            SELECT volume, turnover_rate FROM fund_flow_daily
            WHERE symbol = ? AND turnover_rate IS NOT NULL AND turnover_rate > 0
        """, [str(symbol).strip().zfill(6)]).df()
        if df is None or df.empty:
            return None
        fs = pd.to_numeric(df["volume"], errors="coerce") / (
            pd.to_numeric(df["turnover_rate"], errors="coerce") / 100.0
        )
        fs = fs.replace([np.inf, -np.inf], np.nan).dropna()
        if fs.empty or fs.median() <= 0:
            return None
        return float(fs.median())
    finally:
        conn.close()


def compute_chip_distribution(symbol: str, days: int = 210, bins: int = 100) -> dict | None:
    """
    计算单只股票的筹码分布（三角形换手成本分布）。

    参数:
        symbol: 6位股票代码
        days:   回看交易日数（默认 210 ≈ 一年）
        bins:   价格分箱数

    返回:
        {
          "cost_df": DataFrame(price_bin, chip_pct, cum_pct),
          "current_price": float,
          "avg_cost": float,           # 筹码加权平均成本
          "profit_ratio": float,       # 获利盘 %
          "loss_ratio": float,         # 套牢盘 %
          "p90_low": float,            # 90%成本区下沿
          "p90_high": float,           # 90%成本区上沿
          "peak_price": float,         # 筹码最集中的价格
          "note": str,                 # 换手率数据来源说明
        }
        数据不足返回 None。
    """
    df = _fetch_kline(symbol, days)
    if df is None or len(df) < 20:
        return None

    open_ = df["open"].to_numpy(float)
    high = df["high"].to_numpy(float)
    low = df["low"].to_numpy(float)
    close = df["close"].to_numpy(float)
    volume = df["volume"].to_numpy(float)
    n = len(df)

    # ── 换手率权重 ──
    note = "换手率反推(基于资金流快照估算流通股本)"
    float_shares = _estimate_float_shares(symbol)
    if float_shares is None or float_shares <= 0:
        # 无换手率数据：退化为按成交量加权，无衰减
        note = "无换手率数据，按成交量加权(无衰减)"
        frac = np.clip(volume / np.maximum(volume.sum() / n, 1e-9), 0, 1)
        effective = volume.astype(float)
    else:
        frac = np.clip(volume / float_shares, 0.0, 1.0)  # 当日换手率(比例)
        # 每日衰减：第 i 天筹码留存率 = ∏_{j=i+1..n} (1 - frac[j])
        surv = np.ones(n)
        acc = 1.0
        for i in range(n - 1, -1, -1):
            surv[i] = acc
            acc *= (1.0 - frac[i])
        effective = frac * surv

    # ── 价格分箱 ──
    lo_all, hi_all = float(np.nanmin(low)), float(np.nanmax(high))
    if not np.isfinite(lo_all) or not np.isfinite(hi_all) or hi_all <= lo_all:
        return None
    edges = np.linspace(lo_all, hi_all, bins + 1)
    centers = (edges[:-1] + edges[1:]) / 2.0

    # ── 逐日三角形分布并聚合 ──
    chip = np.zeros(bins)
    for i in range(n):
        lo, hi, cl = low[i], high[i], close[i]
        if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo or effective[i] <= 0:
            continue
        # 三角形：峰值在 close，线性衰减到 low / high
        t = np.where(
            centers < cl,
            (centers - lo) / (cl - lo),
            (hi - centers) / (hi - cl),
        )
        t = np.clip(t, 0.0, 1.0)
        chip += effective[i] * t

    total = chip.sum()
    if total <= 0:
        return None
    chip_pct = chip / total * 100.0
    cum = np.cumsum(chip_pct)

    cur = float(df["close"].iloc[-1])
    cost_df = pd.DataFrame({
        "price_bin": centers,
        "chip_pct": np.round(chip_pct, 3),
        "cum_pct": np.round(cum, 3),
    })

    # ── 指标 ──
    avg_cost = float((centers * chip_pct).sum() / 100.0)
    profit_ratio = float(chip_pct[centers <= cur].sum())      # 现价下方筹码 = 获利盘
    peak_idx = int(np.argmax(chip_pct))
    p90_low = float(centers[np.argmax(cum >= 5.0)])
    p90_high = float(centers[np.argmax(cum >= 95.0)])

    return {
        "cost_df": cost_df,
        "current_price": round(cur, 2),
        "avg_cost": round(avg_cost, 2),
        "profit_ratio": round(profit_ratio, 1),
        "loss_ratio": round(100.0 - profit_ratio, 1),
        "p90_low": round(p90_low, 2),
        "p90_high": round(p90_high, 2),
        "peak_price": round(float(centers[peak_idx]), 2),
        "note": note,
    }
