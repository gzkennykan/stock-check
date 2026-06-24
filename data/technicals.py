"""
技术指标计算模块：从 DuckDB 提取 K线数据，就地计算常用指标。

指标: MA20/60/120, RSI(14), MACD(12,26,9), 区间收益, 波动率, 区间高低点
"""
import numpy as np
import pandas as pd
from data.database import get_connection


def get_kline_ohlcv(symbol: str, limit: int = 300) -> pd.DataFrame | None:
    """从 DuckDB 读取单只股票的 OHLCV 数据，按日期升序"""
    conn = get_connection(read_only=True)
    try:
        df = conn.execute("""
            SELECT trade_date, open, high, low, close, volume
            FROM daily_kline
            WHERE symbol = ?
            ORDER BY trade_date DESC
            LIMIT ?
        """, [str(symbol).strip().zfill(6), limit]).df()
        if df.empty:
            return None
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df = df.set_index("trade_date").sort_index()
        return df
    finally:
        conn.close()


def compute_technicals(df: pd.DataFrame) -> pd.DataFrame:
    """
    输入 OHLCV DataFrame（index=date），在原 DataFrame 上新增技术指标列。

    新增列:
        ma20, ma60, ma120, rsi14,
        macd, macd_signal, macd_hist,
        pct_change(daily return)
    """
    if df.empty:
        return df

    result = df.copy()
    close = result["close"]

    # ── 均线 ──
    for n in [20, 60, 120]:
        result[f"ma{n}"] = close.rolling(n).mean()

    # ── RSI(14) ──
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    # 使用 Wilder 平滑（EMA）更精确
    avg_gain_w = gain.ewm(alpha=1/14, adjust=False).mean()
    avg_loss_w = loss.ewm(alpha=1/14, adjust=False).mean()
    rs = avg_gain_w / avg_loss_w.replace(0, np.nan)
    result["rsi14"] = 100 - (100 / (1 + rs))

    # ── MACD(12, 26, 9) ──
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    result["macd"] = ema12 - ema26
    result["macd_signal"] = result["macd"].ewm(span=9, adjust=False).mean()
    result["macd_hist"] = result["macd"] - result["macd_signal"]

    # ── 日收益率 ──
    result["pct_change"] = close.pct_change()

    return result


def get_period_return(df: pd.DataFrame, days: int) -> float:
    """计算近 N 日收益率（基于收盘价）"""
    if len(df) < days + 1:
        return np.nan
    close = df["close"]
    return float(close.iloc[-1] / close.iloc[-(days + 1)] - 1)


def get_annualized_volatility(df: pd.DataFrame, days: int = 60) -> float:
    """计算近 N 日年化波动率"""
    if len(df) < days:
        return np.nan
    returns = df["close"].pct_change().iloc[-days:]
    return float(returns.std() * np.sqrt(252))


def get_price_levels(df: pd.DataFrame, days: int = 20) -> dict:
    """返回近 N 日价格区间（最高、最低、收盘、均线位置）"""
    if len(df) < days:
        return {}
    recent = df.iloc[-days:]
    return {
        "high": float(recent["high"].max()),
        "low": float(recent["low"].min()),
        "close": float(recent["close"].iloc[-1]),
    }


def get_trend_status(df: pd.DataFrame) -> dict:
    """
    判断当前趋势状态：收盘价相对于 MA20/60/120 的位置。
    返回: { "vs_ma20": "上方"/"下方", "vs_ma60": ..., "vs_ma120": ...,
            "ma20_val", "ma60_val", "ma120_val", "close" }
    """
    close = float(df["close"].iloc[-1])
    status = {"close": close}
    for n in [20, 60, 120]:
        col = f"ma{n}"
        if col in df.columns and pd.notna(df[col].iloc[-1]):
            ma_val = float(df[col].iloc[-1])
            status[f"ma{n}_val"] = ma_val
            status[f"vs_ma{n}"] = "上方" if close > ma_val else "下方"
        else:
            status[f"ma{n}_val"] = None
            status[f"vs_ma{n}"] = "无数据"
    return status


def compute_full_analysis(symbol: str) -> dict:
    """
    单只股票完整技术分析。
    返回 dict，包含技术指标摘要、区间收益、趋势判断、关键位。
    """
    df = get_kline_ohlcv(symbol, limit=300)
    if df is None or df.empty:
        return {"error": f"数据库中无 {symbol} 的K线数据"}

    df = compute_technicals(df)
    last = df.iloc[-1]

    # 区间收益
    ret_20 = get_period_return(df, 20)
    ret_60 = get_period_return(df, 60)
    ret_120 = get_period_return(df, 120)
    vol_60 = get_annualized_volatility(df, 60)

    # 趋势状态
    trend = get_trend_status(df)

    # 关键位
    levels_20 = get_price_levels(df, 20)
    levels_60 = get_price_levels(df, 60)

    return {
        "symbol": symbol,
        "latest_date": str(df.index[-1].date()),
        "close": float(last["close"]),
        "ret_20d": round(ret_20 * 100, 2) if not np.isnan(ret_20) else None,
        "ret_60d": round(ret_60 * 100, 2) if not np.isnan(ret_60) else None,
        "ret_120d": round(ret_120 * 100, 2) if not np.isnan(ret_120) else None,
        "vol_60d_annual": round(vol_60 * 100, 2) if not np.isnan(vol_60) else None,
        "trend": trend,
        "rsi14": round(float(last["rsi14"]), 1) if pd.notna(last.get("rsi14")) else None,
        "macd": round(float(last["macd"]), 4) if pd.notna(last.get("macd")) else None,
        "macd_signal": round(float(last["macd_signal"]), 4) if pd.notna(last.get("macd_signal")) else None,
        "macd_hist": round(float(last["macd_hist"]), 4) if pd.notna(last.get("macd_hist")) else None,
        "ma20": round(float(last["ma20"]), 2) if pd.notna(last.get("ma20")) else None,
        "ma60": round(float(last["ma60"]), 2) if pd.notna(last.get("ma60")) else None,
        "ma120": round(float(last["ma120"]), 2) if pd.notna(last.get("ma120")) else None,
        "level_20d_high": round(levels_20.get("high", 0), 2),
        "level_20d_low": round(levels_20.get("low", 0), 2),
        "level_60d_high": round(levels_60.get("high", 0), 2),
        "level_60d_low": round(levels_60.get("low", 0), 2),
        "df": df,  # 完整 DataFrame，用于画图
    }


# ══════════════════════════════════════════════════════════
# 多周期分析（对标 CZSC 缠论多周期联动）
# ══════════════════════════════════════════════════════════

def _get_kline_period(symbol: str, period: str = "daily", limit: int = 300) -> pd.DataFrame | None:
    """获取指定周期的K线"""
    if period == "daily":
        return get_kline_ohlcv(symbol, limit=limit)

    conn = get_connection(read_only=True)
    try:
        # 从日线聚合生成周线/月线
        df = conn.execute("""
            SELECT trade_date, open, high, low, close, volume
            FROM daily_kline
            WHERE symbol = ?
            ORDER BY trade_date DESC
            LIMIT ?
        """, [str(symbol).strip().zfill(6), limit * 30]).df()  # 取更多日线用于聚合

        if df.empty:
            return None

        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df = df.sort_values("trade_date").set_index("trade_date")

        if period == "weekly":
            resampled = df.resample("W")
        elif period == "monthly":
            resampled = df.resample("ME")
        else:
            return df

        agg = pd.DataFrame({
            "open": resampled["open"].first(),
            "high": resampled["high"].max(),
            "low": resampled["low"].min(),
            "close": resampled["close"].last(),
            "volume": resampled["volume"].sum(),
        }).dropna()

        return agg.tail(limit)
    finally:
        conn.close()


def compute_multitimeframe(symbol: str) -> dict:
    """
    多周期技术分析：日线 + 周线 + 月线。

    返回:
        {
            "daily": {日线指标 dict},
            "weekly": {周线指标 dict},
            "monthly": {月线指标 dict},
            "resonance_signals": [共振信号列表],
            "mtf_score": 多周期综合评分 0-100,
        }
    """
    results = {}
    for period, label, limit in [("daily", "日线", 300), ("weekly", "周线", 120), ("monthly", "月线", 60)]:
        df = _get_kline_period(symbol, period=period, limit=limit)
        if df is None or df.empty or len(df) < 20:
            results[label] = {"error": f"{label}数据不足"}
            continue

        df = compute_technicals(df)
        last = df.iloc[-1]

        results[label] = {
            "close": round(float(last["close"]), 2),
            "ma20": round(float(last["ma20"]), 2) if pd.notna(last.get("ma20")) else None,
            "ma60": round(float(last["ma60"]), 2) if pd.notna(last.get("ma60")) else None,
            "ma120": round(float(last["ma120"]), 2) if pd.notna(last.get("ma120")) else None,
            "rsi14": round(float(last["rsi14"]), 1) if pd.notna(last.get("rsi14")) else None,
            "macd": round(float(last["macd"]), 4) if pd.notna(last.get("macd")) else None,
            "macd_signal": round(float(last["macd_signal"]), 4) if pd.notna(last.get("macd_signal")) else None,
            "macd_hist": round(float(last["macd_hist"]), 4) if pd.notna(last.get("macd_hist")) else None,
            "ret_20": round(get_period_return(df, min(20, len(df)-1)) * 100, 2),
            "trend": get_trend_status(df),
            "n_bars": len(df),
            "date_range": f"{df.index[0].date()} ~ {df.index[-1].date()}",
        }

    # ── 共振信号检测 ──
    resonance = _detect_resonance(results)
    results["resonance_signals"] = resonance
    results["mtf_score"] = _compute_mtf_score(results, resonance)

    return results


def _detect_resonance(mtf: dict) -> list[dict]:
    """
    检测多周期共振信号：
      - MACD 金叉共振：日线+周线同时金叉 → 强信号
      - 均线多头共振：日线+周线同时站上 MA20 → 中期转强
      - RSI 共振：日线+周线都在健康区间(40-70)
      - 关键位共振：日线支撑位 = 周线支撑位 → 更强支撑
    """
    signals = []

    daily = mtf.get("日线", {})
    weekly = mtf.get("周线", {})
    monthly = mtf.get("月线", {})

    # MACD 金叉共振
    if daily and weekly and "error" not in daily and "error" not in weekly:
        d_macd = daily.get("macd") or 0
        d_signal = daily.get("macd_signal") or 0
        w_macd = weekly.get("macd") or 0
        w_signal = weekly.get("macd_signal") or 0

        d_golden = d_macd > d_signal
        w_golden = w_macd > w_signal

        if d_golden and w_golden:
            signals.append({
                "type": "MACD金叉共振",
                "strength": "strong" if d_macd > 0 and w_macd > 0 else "medium",
                "desc": "日线+周线 MACD 同时处于多头，中期上涨信号明确",
            })
        elif d_golden:
            signals.append({
                "type": "日线MACD金叉",
                "strength": "medium",
                "desc": "仅日线 MACD 金叉，等待周线确认",
            })

    # 均线多头共振
    if daily and weekly and "error" not in daily and "error" not in weekly:
        d_close = daily.get("close", 0)
        d_ma20 = daily.get("ma20") or 0
        w_close = weekly.get("close", 0)
        w_ma20 = weekly.get("ma20") or 0

        d_above = d_close > d_ma20 > 0
        w_above = w_close > w_ma20 > 0

        if d_above and w_above:
            signals.append({
                "type": "均线多头共振",
                "strength": "strong",
                "desc": "日线+周线同时站上 MA20，短中期趋势共振向上",
            })
        elif d_above:
            signals.append({
                "type": "日线站上MA20",
                "strength": "medium",
                "desc": "日线站上 MA20，短期偏多，关注周线能否跟上",
            })
        elif w_above:
            signals.append({
                "type": "周线站上MA20",
                "strength": "medium",
                "desc": "周线站上 MA20，中期趋势健康，日线回调或是布局机会",
            })

    # RSI 共振
    if daily and weekly:
        d_rsi = daily.get("rsi14")
        w_rsi = weekly.get("rsi14")
        if d_rsi and w_rsi:
            if 40 <= d_rsi <= 70 and 40 <= w_rsi <= 70:
                signals.append({
                    "type": "RSI健康共振",
                    "strength": "medium",
                    "desc": f"日线RSI={d_rsi}，周线RSI={w_rsi}，均处于健康区间",
                })
            elif d_rsi < 30 and w_rsi < 40:
                signals.append({
                    "type": "超卖共振",
                    "strength": "medium",
                    "desc": f"日线RSI={d_rsi} + 周线RSI={w_rsi}，双双超卖，反弹概率升高",
                })

    # 月线确认
    if monthly and "error" not in monthly:
        m_close = monthly.get("close", 0)
        m_ma20 = monthly.get("ma20") or 0
        if m_close > m_ma20 > 0:
            signals.append({
                "type": "月线多头",
                "strength": "strong",
                "desc": "月线站上 MA20，长期趋势向好，日周线信号可信度提升",
            })

    return signals


def _compute_mtf_score(mtf: dict, signals: list) -> int:
    """
    多周期综合评分 0-100：
      - 日线趋势: 0-30
      - 周线趋势: 0-30
      - 月线趋势: 0-20
      - 共振加分: 0-20
    """
    score = 0
    for label, max_s in [("日线", 30), ("周线", 30), ("月线", 20)]:
        d = mtf.get(label, {})
        if not d or "error" in d:
            continue
        close = d.get("close", 0)
        ma20 = d.get("ma20") or 0
        ma60 = d.get("ma60") or 0
        rsi = d.get("rsi14")

        if close > ma20 > 0:
            score += max_s * 0.5
        if close > ma60 > 0:
            score += max_s * 0.3
        if rsi and 40 <= rsi <= 70:
            score += max_s * 0.2

    # 共振加分
    strong_signals = [s for s in signals if s.get("strength") == "strong"]
    medium_signals = [s for s in signals if s.get("strength") == "medium"]
    score += min(20, len(strong_signals) * 8 + len(medium_signals) * 3)

    return min(100, score)

