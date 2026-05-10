"""
参数优化：backtrader 内置网格搜索 + optuna 贝叶斯优化
"""
import backtrader as bt
import pandas as pd

from backtest.engine import CerebroBuilder


def grid_search(strategy_cls, df: pd.DataFrame, param_grid: dict[str, list]) -> pd.DataFrame:
    """
    网格搜索：遍历所有参数组合，返回排序后的结果表。

    参数:
        strategy_cls: 策略类
        df: 行情数据
        param_grid: 参数搜索空间 e.g. {"fast_period": [3,5,10], "slow_period": [15,20,30]}

    返回:
        按年化收益率降序排列的 DataFrame
    """
    builder = CerebroBuilder()
    builder.add_data(df)
    builder.add_strategy(strategy_cls)
    cerebro = builder.build()
    cerebro.optstrategy(strategy_cls, **param_grid)

    print(f"开始网格搜索... 共 {_count_combinations(param_grid)} 组参数")
    results = cerebro.run(maxcpus=1)

    rows = []
    for r in results:
        strat = r[0]
        params = {}
        for k in param_grid:
            params[k] = getattr(strat.params, k)

        end_val = strat.broker.getvalue()
        start_val = 1000000.0
        total_ret = (end_val / start_val) - 1
        sharpe = _get_sharpe(strat)
        dd = _get_max_drawdown(strat)

        rows.append({**params, "total_return": total_ret, "sharpe": sharpe, "max_drawdown": dd})

    result_df = pd.DataFrame(rows)
    result_df = result_df.sort_values("total_return", ascending=False)
    return result_df


def optuna_search(strategy_cls, df: pd.DataFrame, param_ranges: dict,
                  n_trials: int = 100, target: str = "sharpe") -> pd.DataFrame:
    """
    使用 optuna 进行贝叶斯优化。

    参数:
        strategy_cls: 策略类
        df: 行情数据
        param_ranges: 参数范围 e.g. {"fast_period": (3, 20), "slow_period": (15, 60)}
        n_trials: 优化试验次数
        target: 优化目标 "sharpe" 或 "return"

    返回:
        按目标排序的 trial 结果表
    """
    try:
        import optuna
    except ImportError:
        print("optuna 未安装，使用 pip install optuna")
        return pd.DataFrame()

    def objective(trial):
        params = {}
        for name, (lo, hi) in param_ranges.items():
            params[name] = trial.suggest_int(name, lo, hi)

        builder = CerebroBuilder()
        builder.add_data(df)
        builder.add_strategy(strategy_cls, **params)
        cerebro = builder.build()
        results = cerebro.run()
        if not results:
            return -999

        strat = results[0]
        end_val = strat.broker.getvalue()
        start_val = 1000000.0
        total_ret = (end_val / start_val) - 1
        sharpe = _get_sharpe(strat)

        if target == "sharpe":
            return sharpe if sharpe is not None else -999
        return total_ret

    print(f"开始 optuna 优化... {n_trials} 次试验, 目标={target}")
    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=n_trials, show_progress_bar=True)

    print(f"\n最佳参数: {study.best_params}")
    print(f"最佳值: {study.best_value:.4f}")

    # 转为 DataFrame
    trials_df = study.trials_dataframe()
    cols = ["number", "value"] + [f"params_{k}" for k in param_ranges]
    cols = [c for c in cols if c in trials_df.columns]
    return trials_df[cols].sort_values("value", ascending=False)


def _get_sharpe(strat):
    """从策略实例获取夏普比率"""
    try:
        return strat.analyzers.sharpe.get_analysis().get("sharperatio")
    except Exception:
        return None


def _get_max_drawdown(strat):
    """从策略实例获取最大回撤"""
    try:
        return strat.analyzers.drawdown.get_analysis().get("max", {}).get("drawdown", 0)
    except Exception:
        return 0


def _count_combinations(param_grid: dict) -> int:
    count = 1
    for v in param_grid.values():
        count *= len(v)
    return count
