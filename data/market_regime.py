"""
大盘择时 / 仓位管理

基于基准指数（默认沪深300 000300）的均线趋势 + 波动率，判断牛/熊/震荡三态，
给出每日建议仓位（0-1），用于回测动态调仓和实盘仓位参考。

行业标准口径（双均线择时）：
  牛市：close > MA20 > MA60  → 仓位 100%
  熊市：close < MA20 < MA60  → 仓位 40%
  震荡：其余情况             → 仓位 60%
  高波动过滤：20日年化波动率 > 40% 时，仓位再 ×0.7
"""
import pandas as pd
import numpy as np

from data.database import get_kline, get_latest_trading_date

# 模块级缓存：回测前 set_regime_series()，策略 size() 里 get_position_for() 读取
_REGIME_SERIES: pd.Series | None = None


def compute_regime_series(end_date: str = None, lookback_days: int = 600,
                          benchmark: str = "000300") -> pd.Series:
    """计算基准指数每日建议仓位（0-1），返回 Series(index=trade_date, values=position)。"""
    if end_date is None:
        end_date = get_latest_trading_date()
        if end_date is None:
            return pd.Series(dtype=float)
    start = (pd.to_datetime(end_date) - pd.Timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    k = get_kline(benchmark, start, end_date)
    if k.empty or len(k) < 60:
        return pd.Series(dtype=float)

    close = k["close"]
    ma20 = close.rolling(20).mean()
    ma60 = close.rolling(60).mean()
    vol = close.pct_change().rolling(20).std() * np.sqrt(252)  # 20日年化波动率

    pos = pd.Series(0.6, index=close.index, dtype=float)      # 默认震荡
    pos[(close > ma20) & (ma20 > ma60)] = 1.0                  # 牛市
    pos[(close < ma20) & (ma20 < ma60)] = 0.4                  # 熊市
    pos[vol > 0.40] = pos[vol > 0.40] * 0.7                    # 高波动减仓
    return pos.clip(0.1, 1.0)


def detect_regime(end_date: str = None, benchmark: str = "000300") -> dict:
    """返回当前大盘状态：regime/position_pct/close/ma20/ma60/volatility。"""
    if end_date is None:
        end_date = get_latest_trading_date()
        if end_date is None:
            return {}
    series = compute_regime_series(end_date=end_date, benchmark=benchmark)
    k = get_kline(benchmark, None, end_date)
    if series.empty or k.empty:
        return {}

    close = k["close"]
    latest_close = float(close.iloc[-1])
    ma20 = float(close.rolling(20).mean().iloc[-1])
    ma60 = float(close.rolling(60).mean().iloc[-1])
    vol = float(close.pct_change().rolling(20).std().iloc[-1] * np.sqrt(252))
    pos = float(series.iloc[-1])

    if latest_close > ma20 > ma60:
        regime = "牛市"
    elif latest_close < ma20 < ma60:
        regime = "熊市"
    else:
        regime = "震荡"

    return {
        "date": close.index[-1].date(),
        "close": round(latest_close, 2),
        "ma20": round(ma20, 2),
        "ma60": round(ma60, 2),
        "regime": regime,
        "position_pct": round(pos * 100, 0),
        "volatility": round(vol * 100, 1),
    }


def set_regime_series(series: pd.Series | None) -> None:
    """回测前设置仓位序列（None = 关闭择时）。"""
    global _REGIME_SERIES
    _REGIME_SERIES = series


def get_position_for(date) -> float | None:
    """回测用：读取指定日期的建议仓位。未启用或无数据返回 None。"""
    if _REGIME_SERIES is None or _REGIME_SERIES.empty:
        return None
    try:
        return float(_REGIME_SERIES.asof(pd.Timestamp(date)))
    except Exception:
        return None
