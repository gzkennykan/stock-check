#!/usr/bin/env python
"""
股票量化回测系统 — 命令行入口

使用示例:
  python main.py --symbol 600036 --strategy ma_cross --start 2023-01-01 --end 2024-12-31 --plot
  python main.py --symbol 000001 --strategy macd --optimize --plot
  python main.py --symbols 600036,000001 --strategy ma_cross --compare
"""
import argparse
import sys
from datetime import datetime

from config import DEFAULT_START, DEFAULT_END, INITIAL_CASH
from data.fetcher import fetch_data
from strategies import MACrossStrategy, MACDStrategy, RSIStrategy
from backtest.engine import run_backtest, run_multi_backtest
from analysis.report import print_report
from analysis.metrics import compute_metrics
from visualization.charts import plot_backtest, plot_kline_with_signals

STRATEGY_MAP = {
    "ma_cross": MACrossStrategy,
    "macd": MACDStrategy,
    "rsi": RSIStrategy,
}


def parse_args():
    p = argparse.ArgumentParser(description="股票量化回测系统")
    p.add_argument("--symbol", type=str, default="600036", help="股票代码 (默认 600036)")
    p.add_argument("--symbols", type=str, default=None, help="多股票对比, 逗号分隔 e.g. 600036,000001")
    p.add_argument("--strategy", type=str, default="ma_cross",
                   choices=list(STRATEGY_MAP), help="策略名称")
    p.add_argument("--start", type=str, default=DEFAULT_START, help="起始日期")
    p.add_argument("--end", type=str, default=DEFAULT_END, help="结束日期")
    p.add_argument("--cash", type=float, default=INITIAL_CASH, help="初始资金")
    p.add_argument("--plot", action="store_true", help="输出图表")
    p.add_argument("--compare", action="store_true", help="多策略对比模式")
    p.add_argument("--optimize", action="store_true", help="参数优化模式")
    p.add_argument("--trials", type=int, default=50, help="optuna 优化次数 (默认50)")
    return p.parse_args()


def get_equity_curve(strat) -> "pd.Series | None":
    """从 TimeReturn 分析器重建资金曲线"""
    import pandas as pd
    try:
        ana = strat.analyzers.getbyname("returns")
        if ana is None:
            return None
        rets = ana.get_analysis()
        # TimeReturn 返回 {datetime: return_pct} (已经是小数格式)
        if not rets or len(rets) < 1:
            return None
        dates = list(rets.keys())
        vals = [INITIAL_CASH]
        for dt in dates:
            vals.append(vals[-1] * (1 + rets[dt]))
        return pd.Series(vals[1:], index=dates)
    except Exception:
        return None


def get_daily_returns(strat) -> list[float]:
    """从 TimeReturn 分析器获取日收益率列表"""
    try:
        ana = strat.analyzers.getbyname("returns")
        if ana is None:
            return []
        rets = ana.get_analysis()
        return list(rets.values())
    except Exception:
        return []


def run_single(args):
    """单股票单策略回测"""
    print(f"\n获取数据: {args.symbol} ({args.start} ~ {args.end})")
    df = fetch_data(args.symbol, args.start, args.end)
    if df.empty:
        print("错误: 未获取到数据")
        sys.exit(1)
    print(f"数据量: {len(df)} 条")

    strategy_cls = STRATEGY_MAP[args.strategy]

    result = run_backtest(strategy_cls, df)
    if "error" in result:
        print(result["error"])
        return

    # 构建指标
    strat = result["strategy"]
    equity = get_equity_curve(strat)
    daily_rets = get_daily_returns(strat)

    metrics = compute_metrics(
        returns=daily_rets,
        equity_curve=equity,
        start_value=result["start_value"],
        end_value=result["end_value"],
        trades_result=result.get("trades"),
    )
    print_report(metrics, f"{args.strategy} @ {args.symbol}")

    if args.plot:
        plot_backtest({
            "equity_curve": equity,
            "daily_returns": daily_rets,
        })
        # K线图+信号 (取最近120根K线)
        plot_kline_with_signals(df.tail(120))


def run_compare(args):
    """多策略对比：同一股票运行所有策略"""
    df = fetch_data(args.symbol, args.start, args.end)
    print(f"数据: {args.symbol}, 共 {len(df)} 条\n")

    strategy_map = {}
    for name, cls in STRATEGY_MAP.items():
        strategy_map[name] = (cls, {})

    results = run_multi_backtest(strategy_map, df)

    print(f"\n{'='*60}")
    print("  策略对比汇总")
    print(f"{'='*60}")
    print(f"{'策略':<15} {'累计收益':>10} {'年化收益':>10} {'夏普':>8} {'最大回撤':>10} {'胜率':>8}")
    print("-" * 61)

    rows = []
    for name, r in results.items():
        if "error" in r:
            continue
        strat = r["strategy"]
        equity = get_equity_curve(strat)
        daily_rets = get_daily_returns(strat)
        m = compute_metrics(daily_rets, equity, r["start_value"], r["end_value"], r.get("trades"))
        rows.append((name, m))

    # 按年化收益排序
    rows.sort(key=lambda x: x[1].annual_return, reverse=True)
    for name, m in rows:
        print(f"{name:<15} {m.total_return:>10.2%} {m.annual_return:>10.2%} "
              f"{m.sharpe_ratio or 0:>8.2f} {m.max_drawdown:>10.2%} "
              f"{m.win_rate or 0:>8.2%}")


def run_optimize(args):
    """参数优化模式"""
    from optimizer.grid_search import optuna_search

    print(f"\n获取数据: {args.symbol} ({args.start} ~ {args.end})")
    df = fetch_data(args.symbol, args.start, args.end)
    if df.empty:
        print("错误: 未获取到数据")
        return
    print(f"数据量: {len(df)} 条")

    strategy_cls = STRATEGY_MAP[args.strategy]

    # 根据策略定义优化参数范围
    if args.strategy == "ma_cross":
        param_ranges = {"fast_period": (3, 20), "slow_period": (15, 60)}
    elif args.strategy == "macd":
        param_ranges = {"fast_period": (6, 24), "slow_period": (20, 52), "signal_period": (5, 15)}
    else:  # rsi
        param_ranges = {"rsi_period": (7, 28), "oversold": (20, 40), "overbought": (60, 80)}

    result_df = optuna_search(strategy_cls, df, param_ranges, n_trials=args.trials, target="sharpe")

    if not result_df.empty:
        print("\nTop 10 参数组合:")
        print(result_df.head(10).to_string(index=False))


def main():
    args = parse_args()

    if args.compare:
        run_compare(args)
    elif args.optimize:
        run_optimize(args)
    else:
        run_single(args)


if __name__ == "__main__":
    main()
