"""
回测报告生成
"""
from .metrics import MetricsResult


def format_pct(val: float | None) -> str:
    if val is None:
        return "N/A"
    return f"{val:.2%}"


def format_num(val: float | None, fmt: str = ".2f") -> str:
    if val is None:
        return "N/A"
    return f"{val:{fmt}}"


def print_report(metrics: MetricsResult, strategy_name: str = "策略") -> None:
    """打印格式化回测报告"""
    print(f"\n{'='*60}")
    print(f"  回测报告 — {strategy_name}")
    print(f"{'='*60}")
    print(f"  初始资金:     CNY{metrics.start_value:,.0f}")
    print(f"  最终资金:     CNY{metrics.end_value:,.0f}")
    print(f"  累计收益率:   {format_pct(metrics.total_return)}")
    print(f"  年化收益率:   {format_pct(metrics.annual_return)}")
    print(f"  夏普比率:     {format_num(metrics.sharpe_ratio)}")
    print(f"  Calmar 比率:  {format_num(metrics.calmar_ratio)}")
    print(f"  年化波动率:   {format_pct(metrics.annual_volatility)}")
    print(f"  最大回撤:     {format_pct(metrics.max_drawdown)}")
    print(f"  回撤持续天数: {metrics.max_drawdown_duration} 天")
    print(f"  总交易次数:   {metrics.total_trades}")
    print(f"  胜率:         {format_pct(metrics.win_rate)}")
    print(f"  盈亏比:       {format_num(metrics.profit_loss_ratio)}")
    print(f"{'='*60}\n")
