"""
选股信号后验证闭环

- record_signals: 把选股/信号结果落库
- validate_signals: 逐信号计算 T+N 交易日后的前向收益 & 超额收益（vs 基准）
- summarize_validation: 按「来源 × 周期」汇总命中率 / 平均收益 / 平均超额 / 超额胜率

行业标准口径：
  信号日 D 的收盘价为基准，T+N 表示 D 之后第 N 个交易日的收盘，
  前向收益 = close[D+N] / close[D] - 1，超额收益 = 前向收益 - 基准同期收益。
"""
import pandas as pd
from datetime import datetime, timedelta

from data.database import (
    insert_signal_records, get_signal_records,
    get_kline_batch, get_kline,
)


def record_signals(df: pd.DataFrame, source: str, signal_date: str = None,
                   price_col: str = "price", name_col: str = "name",
                   score_col: str = None, symbol_col: str = "code",
                   top_n: int = None) -> int:
    """从选股结果 df 记录信号，返回记录条数。"""
    if df is None or df.empty:
        return 0
    if signal_date is None:
        signal_date = datetime.now().strftime("%Y-%m-%d")
    if top_n:
        df = df.head(top_n)
    records = []
    for _, row in df.iterrows():
        sym = str(row.get(symbol_col, "")).strip().zfill(6)
        if not sym or len(sym) != 6:
            continue
        name = str(row.get(name_col, "")) if name_col in df.columns else ""
        price = row.get(price_col)
        records.append({
            "signal_date": signal_date,
            "symbol": sym,
            "name": name,
            "source": source,
            "signal_price": float(price) if pd.notna(price) else None,
            "score": float(row.get(score_col)) if score_col and score_col in df.columns and pd.notna(row.get(score_col)) else None,
        })
    return insert_signal_records(records)


def _series_fwd_return(kline: pd.DataFrame, signal_date, T: int):
    """基于序列自身收盘价：signal_date（或其后最近交易日）之后第 T 个交易日的收益。"""
    if kline is None or kline.empty:
        return None
    kline = kline.sort_index()
    idx = kline.index
    pos = idx.searchsorted(pd.Timestamp(signal_date), side="left")
    if pos >= len(idx):
        return None
    base_close = kline["close"].iloc[pos]
    fwd_pos = pos + T
    if fwd_pos >= len(idx) or base_close <= 0:
        return None
    return float(kline["close"].iloc[fwd_pos] / base_close - 1.0)


def validate_signals(forward_days=(1, 5, 20), benchmark: str = "000300",
                     source: str = None) -> pd.DataFrame:
    """逐信号验证，返回明细 DataFrame（signal_date/symbol/name/source/forward_days/fwd_return/bench_return/excess_return）。"""
    recs = get_signal_records(source=source)
    if recs.empty:
        return pd.DataFrame()

    symbols = recs["symbol"].unique().tolist()
    start = recs["signal_date"].min().strftime("%Y-%m-%d")
    # 拉取到最晚信号日后 max(T)*2+15 天，确保有足够前向数据
    end = (recs["signal_date"].max() + timedelta(days=max(forward_days) * 2 + 15)).strftime("%Y-%m-%d")

    klines = get_kline_batch(symbols, start, end)
    bm = get_kline(benchmark, start, end)

    # 基准前向收益按信号日缓存（同一日多只股票共用）
    bm_cache = {}

    def _bm_ret(d):
        if d not in bm_cache:
            bm_cache[d] = {T: _series_fwd_return(bm, d, T) for T in forward_days}
        return bm_cache[d]

    rows = []
    for _, r in recs.iterrows():
        k = klines.get(r["symbol"])
        bmrets = _bm_ret(r["signal_date"])
        for T in forward_days:
            fr = _series_fwd_return(k, r["signal_date"], T)
            bmr = bmrets[T]
            exc = (fr - bmr) if (fr is not None and bmr is not None) else None
            rows.append({
                "signal_date": r["signal_date"].date(),
                "symbol": r["symbol"],
                "name": r["name"],
                "source": r["source"],
                "forward_days": f"T+{T}",
                "fwd_return": fr,
                "bench_return": bmr,
                "excess_return": exc,
            })
    return pd.DataFrame(rows)


def summarize_validation(forward_days=(1, 5, 20), benchmark: str = "000300",
                         source: str = None) -> pd.DataFrame:
    """按「来源 × 周期」汇总命中率 / 平均收益 / 平均超额 / 超额胜率。"""
    detail = validate_signals(forward_days, benchmark, source)
    if detail.empty:
        return pd.DataFrame()

    rows = []
    for (src, T), g in detail.groupby(["source", "forward_days"]):
        fwd = g["fwd_return"].dropna()
        exc = g["excess_return"].dropna()
        rows.append({
            "来源": src,
            "周期": T,
            "样本数": int(len(g)),
            "命中率%": round(float((fwd > 0).mean() * 100), 1) if len(fwd) else None,
            "平均收益%": round(float(fwd.mean() * 100), 2) if len(fwd) else None,
            "中位收益%": round(float(fwd.median() * 100), 2) if len(fwd) else None,
            "平均超额%": round(float(exc.mean() * 100), 2) if len(exc) else None,
            "超额胜率%": round(float((exc > 0).mean() * 100), 1) if len(exc) else None,
        })
    return pd.DataFrame(rows)
