"""
组合回测引擎：多股票等权/自定义权重组合回测
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass

from .engine import run_backtest
from config import INITIAL_CASH


@dataclass
class PortfolioResult:
    combined_equity: pd.Series
    individual_equities: dict[str, pd.Series]   # {symbol: equity_series}
    weights: dict[str, float]
    total_return: float
    annual_return: float
    sharpe_ratio: float | None
    max_drawdown: float
    annual_volatility: float
    calmar_ratio: float | None
    corr_matrix: pd.DataFrame | None
    individual_returns: dict[str, float]        # {symbol: total_return}
    start_value: float
    end_value: float
    win_rate: float | None = None
    profit_loss_ratio: float | None = None
    total_trades: int = 0


def _equity_from_result(result: dict) -> pd.Series | None:
    """从单票回测结果中提取资金曲线"""
    if "error" in result:
        return None
    strat = result["strategy"]
    try:
        ana = strat.analyzers.getbyname("returns")
        if ana is None:
            return None
        rets = ana.get_analysis()
        if not rets or len(rets) < 1:
            return None
        dates = list(rets.keys())
        vals = [INITIAL_CASH]
        for dt in dates:
            vals.append(vals[-1] * (1 + rets[dt]))
        return pd.Series(vals[1:], index=dates)
    except Exception:
        return None


def _align_equities(equities: dict[str, pd.Series]) -> tuple[dict[str, pd.Series], pd.DatetimeIndex]:
    """对齐所有资金曲线到共同日期"""
    if not equities:
        return {}, pd.DatetimeIndex([])
    common = None
    for eq in equities.values():
        if common is None:
            common = set(eq.index)
        else:
            common = common.intersection(eq.index)
    if not common:
        return {}, pd.DatetimeIndex([])
    dates = sorted(common)
    aligned = {}
    for sym, eq in equities.items():
        aligned[sym] = eq.loc[dates]
    return aligned, pd.DatetimeIndex(dates)


def _aggregate_trade_stats(results: list[dict]) -> tuple[float | None, float | None, int]:
    """汇总多只股票的交易统计，返回 (胜率, 盈亏比, 总交易次数)"""
    total_won = 0
    total_lost = 0
    won_pnl_sum = 0.0
    lost_pnl_sum = 0.0
    for r in results:
        trades = r.get("trades")
        if not trades or not isinstance(trades, dict):
            continue
        won = trades.get("won", {})
        lost = trades.get("lost", {})
        if isinstance(won, dict):
            total_won += won.get("total", 0) or 0
            pnl_w = won.get("pnl", {})
            if isinstance(pnl_w, dict):
                won_pnl_sum += (pnl_w.get("total", 0) or 0)
        if isinstance(lost, dict):
            total_lost += lost.get("total", 0) or 0
            pnl_l = lost.get("pnl", {})
            if isinstance(pnl_l, dict):
                lost_pnl_sum += abs(pnl_l.get("total", 0) or 0)

    total_trades = total_won + total_lost
    if total_trades == 0:
        return None, None, 0

    win_rate = total_won / total_trades
    avg_win = won_pnl_sum / total_won if total_won > 0 else 0
    avg_loss = lost_pnl_sum / total_lost if total_lost > 0 else 0
    profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else None

    return win_rate, profit_loss_ratio, total_trades


def run_portfolio_backtest(
    strategy_cls,
    symbols: list[str],
    stock_data: dict[str, pd.DataFrame],
    weights: dict[str, float] | None = None,
    strategy_params: dict | None = None,
) -> PortfolioResult | None:
    """
    运行组合回测。

    参数:
        strategy_cls: 策略类（所有股票使用同一策略）
        symbols: 股票代码列表
        stock_data: {symbol: DataFrame} 每只股票的行情数据
        weights: {symbol: weight} 权重分配，None 则等权
        strategy_params: 策略参数字典
    """
    if not symbols or not stock_data:
        return None

    n = len(symbols)
    if weights is None:
        weights = {s: 1.0 / n for s in symbols}

    params = strategy_params or {}

    # 逐票回测
    equities = {}
    individual_returns = {}
    all_results = []
    for sym in symbols:
        df = stock_data.get(sym)
        if df is None or df.empty:
            continue
        result = run_backtest(strategy_cls, df, params)
        all_results.append(result)
        eq = _equity_from_result(result)
        if eq is not None:
            equities[sym] = eq
            individual_returns[sym] = result.get("total_return", 0)

    # 汇总交易统计
    win_rate, profit_loss_ratio, total_trades = _aggregate_trade_stats(all_results)

    if not equities:
        return None

    # 对齐日期
    aligned, dates = _align_equities(equities)
    if not aligned:
        return None

    # 构建组合资金曲线（按权重叠加日收益）
    # 先归一化为收益率曲线
    pct_curves = {}
    for sym, eq in aligned.items():
        pct_curves[sym] = eq / eq.iloc[0]

    # 组合收益率 = sum(weight_i * return_i)
    combined_pct = pd.Series(0.0, index=dates)
    for sym, pct in pct_curves.items():
        w = weights.get(sym, 0)
        combined_pct = combined_pct + w * pct
    combined_equity = combined_pct * INITIAL_CASH

    # 计算组合指标
    start_val = combined_equity.iloc[0]
    end_val = combined_equity.iloc[-1]
    total_ret = end_val / start_val - 1

    days = (dates[-1] - dates[0]).days
    years = max(days / 365.0, 1 / 252)
    annual_ret = (1 + total_ret) ** (1.0 / years) - 1

    # 日收益率
    daily_rets = combined_equity.pct_change().dropna()
    sharpe = None
    annual_vol = 0.0
    if len(daily_rets) > 1 and daily_rets.std() > 0:
        sharpe = float(daily_rets.mean() / daily_rets.std() * np.sqrt(252))
        annual_vol = float(daily_rets.std() * np.sqrt(252))

    # 最大回撤
    rolling_max = combined_equity.cummax()
    drawdown = (combined_equity - rolling_max) / rolling_max
    max_dd = abs(drawdown.min())

    calmar = (annual_ret / max_dd) if max_dd > 0 else None

    # 相关性矩阵
    corr_matrix = None
    daily_curves = {}
    for sym, eq in aligned.items():
        daily_curves[sym] = eq.pct_change().dropna()
    if len(daily_curves) >= 2:
        corr_df = pd.DataFrame(daily_curves)
        common_idx = corr_df.dropna().index
        if len(common_idx) > 1:
            corr_matrix = corr_df.loc[common_idx].corr()

    return PortfolioResult(
        combined_equity=combined_equity,
        individual_equities=aligned,
        weights=weights,
        total_return=total_ret,
        annual_return=annual_ret,
        sharpe_ratio=sharpe,
        max_drawdown=max_dd,
        annual_volatility=annual_vol,
        calmar_ratio=calmar,
        corr_matrix=corr_matrix,
        individual_returns=individual_returns,
        start_value=start_val,
        end_value=end_val,
        win_rate=win_rate,
        profit_loss_ratio=profit_loss_ratio,
        total_trades=total_trades,
    )
