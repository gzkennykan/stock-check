"""
风险指标计算：年化收益率、夏普比率、最大回撤、波动率、胜率、Calmar比率
"""
from dataclasses import dataclass
import numpy as np
import pandas as pd


@dataclass
class MetricsResult:
    total_return: float
    annual_return: float
    sharpe_ratio: float | None
    max_drawdown: float
    max_drawdown_duration: int
    annual_volatility: float
    win_rate: float | None
    profit_loss_ratio: float | None
    calmar_ratio: float | None
    total_trades: int
    start_value: float
    end_value: float


def _compute_drawdowns(equity: pd.Series) -> tuple[float, int]:
    """计算最大回撤比例和最长回撤持续时间"""
    rolling_max = equity.cummax()
    drawdown = (equity - rolling_max) / rolling_max
    max_dd = drawdown.min()

    # 计算最长回撤持续时间
    in_dd = drawdown < 0
    max_duration = 0
    current_duration = 0
    for val in in_dd:
        if val:
            current_duration += 1
            max_duration = max(max_duration, current_duration)
        else:
            current_duration = 0

    return abs(max_dd), max_duration


def compute_metrics(returns: list[float] | None,
                    equity_curve: pd.Series | None,
                    start_value: float,
                    end_value: float,
                    trades_result: dict | None = None) -> MetricsResult:
    """从回测结果计算所有风险指标"""
    total_return = (end_value / start_value) - 1

    # 年化收益率
    if equity_curve is not None and len(equity_curve) > 1:
        days = (equity_curve.index[-1] - equity_curve.index[0]).days
        years = max(days / 365.0, 1 / 252)
        annual_ret = (1 + total_return) ** (1.0 / years) - 1
    else:
        annual_ret = total_return

    # 夏普比率
    daily_returns = None
    if returns and len(returns) > 1:
        arr = np.array(returns)
        if arr.std() != 0:
            sharpe = float(arr.mean() / arr.std() * np.sqrt(252))
        else:
            sharpe = None
        daily_returns = arr
    else:
        sharpe = None

    # 最大回撤
    if equity_curve is not None and len(equity_curve) > 0:
        max_dd, max_dd_duration = _compute_drawdowns(equity_curve)
    else:
        max_dd, max_dd_duration = 0.0, 0

    # 年化波动率
    if daily_returns is not None and len(daily_returns) > 1:
        annual_vol = float(daily_returns.std() * np.sqrt(252))
    else:
        annual_vol = 0.0

    # 交易分析
    win_rate = None
    pl_ratio = None
    total_trades = 0
    if trades_result:
        total = trades_result.get("total", {})
        total_trades = total.get("total", 0) if isinstance(total, dict) else 0
        won = trades_result.get("won", {})
        lost = trades_result.get("lost", {})
        won_total = won.get("total", 0) if isinstance(won, dict) else 0
        lost_total = lost.get("total", 0) if isinstance(lost, dict) else 0
        if total_trades > 0:
            win_rate = won_total / total_trades
        if lost_total > 0 and isinstance(won, dict) and isinstance(lost, dict):
            avg_win = won.get("pnl", {}).get("average", 0) if isinstance(won.get("pnl"), dict) else 0
            avg_loss = abs(lost.get("pnl", {}).get("average", 0)) if isinstance(lost.get("pnl"), dict) else 0
            if avg_loss > 0:
                pl_ratio = avg_win / avg_loss

    # Calmar 比率
    calmar = (annual_ret / max_dd) if max_dd > 0 else None

    return MetricsResult(
        total_return=total_return,
        annual_return=annual_ret,
        sharpe_ratio=sharpe,
        max_drawdown=max_dd,
        max_drawdown_duration=max_dd_duration,
        annual_volatility=annual_vol,
        win_rate=win_rate,
        profit_loss_ratio=pl_ratio,
        calmar_ratio=calmar,
        total_trades=total_trades,
        start_value=start_value,
        end_value=end_value,
    )


@dataclass
class BenchmarkResult:
    benchmark_return: float
    benchmark_annual_return: float
    alpha: float
    beta: float
    information_ratio: float | None
    tracking_error: float | None
    excess_return: float
    benchmark_name: str


def compute_benchmark_metrics(
    strategy_equity: pd.Series,
    benchmark_close: pd.Series,
    initial_cash: float,
    benchmark_name: str = "基准",
) -> BenchmarkResult | None:
    if strategy_equity is None or benchmark_close is None:
        return None
    if len(strategy_equity) < 2 or len(benchmark_close) < 2:
        return None

    common_dates = strategy_equity.index.intersection(benchmark_close.index)
    if len(common_dates) < 2:
        return None

    eq_aligned = strategy_equity.loc[common_dates]
    bm_aligned = benchmark_close.loc[common_dates]

    bm_equity = initial_cash * (bm_aligned / bm_aligned.iloc[0])

    strat_rets = eq_aligned.pct_change().dropna()
    bm_rets = bm_equity.pct_change().dropna()

    common = strat_rets.index.intersection(bm_rets.index)
    if len(common) < 2:
        return None
    strat_rets = strat_rets.loc[common]
    bm_rets = bm_rets.loc[common]

    cov_matrix = np.cov(strat_rets, bm_rets)
    beta = cov_matrix[0, 1] / cov_matrix[1, 1] if cov_matrix[1, 1] > 0 else 1.0

    days = (common[-1] - common[0]).days
    years = max(days / 365.0, 1 / 252)

    strat_total = eq_aligned.iloc[-1] / eq_aligned.iloc[0] - 1
    bm_total = bm_equity.iloc[-1] / bm_equity.iloc[0] - 1
    strat_annual = (1 + strat_total) ** (1.0 / years) - 1
    bm_annual = (1 + bm_total) ** (1.0 / years) - 1

    alpha = strat_annual - beta * bm_annual

    excess_rets = strat_rets - bm_rets
    tracking_error = float(excess_rets.std() * np.sqrt(252)) if len(excess_rets) > 1 else None

    information_ratio = None
    if tracking_error and tracking_error > 0:
        excess_annual = strat_annual - bm_annual
        information_ratio = excess_annual / tracking_error

    return BenchmarkResult(
        benchmark_return=bm_total,
        benchmark_annual_return=bm_annual,
        alpha=alpha,
        beta=beta,
        information_ratio=information_ratio,
        tracking_error=tracking_error,
        excess_return=strat_total - bm_total,
        benchmark_name=benchmark_name,
    )
