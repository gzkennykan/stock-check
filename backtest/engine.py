"""
回测引擎封装
"""
import backtrader as bt
import pandas as pd
from datetime import datetime

from config import INITIAL_CASH
from .broker import set_a_share_broker


class CerebroBuilder:
    """封装 cerebro 的创建和配置"""

    def __init__(self, initial_cash: float = INITIAL_CASH):
        self.cerebro = bt.Cerebro()
        self.cerebro.broker.setcash(initial_cash)
        set_a_share_broker(self.cerebro)

    def add_data(self, df: pd.DataFrame, name: str = "data") -> None:
        """添加行情数据"""
        data = bt.feeds.PandasData(dataname=df, name=name)
        self.cerebro.adddata(data)

    def add_strategy(self, strategy_cls, **params) -> None:
        self.cerebro.addstrategy(strategy_cls, **params)

    def add_analyzers(self) -> None:
        self.cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe",
                                 timeframe=bt.TimeFrame.Days, annualize=True)
        self.cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
        self.cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
        self.cerebro.addanalyzer(bt.analyzers.TimeReturn, _name="returns",
                                 timeframe=bt.TimeFrame.Days)

    def build(self) -> bt.Cerebro:
        self.add_analyzers()
        return self.cerebro


def run_backtest(strategy_cls, df: pd.DataFrame, strategy_params: dict | None = None) -> dict:
    """
    运行单次回测，返回结果字典。

    参数:
        strategy_cls: 策略类
        df: 行情数据 DataFrame (需包含 open/high/low/close/volume)
        strategy_params: 策略参数字典
    返回:
        包含策略实例、分析器结果、最终资金的字典
    """
    builder = CerebroBuilder()
    builder.add_data(df)
    kwargs = strategy_params or {}
    builder.add_strategy(strategy_cls, **kwargs)
    cerebro = builder.build()

    start_val = cerebro.broker.getvalue()
    results = cerebro.run()
    end_val = cerebro.broker.getvalue()

    if not results:
        return {"error": "回测未产生结果"}

    strat = results[0]
    return {
        "strategy": strat,
        "start_value": start_val,
        "end_value": end_val,
        "total_return": (end_val / start_val) - 1,
        "sharpe": _safe_analyzer(strat, "sharpe", "sharperatio"),
        "drawdown": _safe_analyzer(strat, "drawdown"),
        "trades": _safe_analyzer(strat, "trades"),
        "returns": _safe_analyzer(strat, "returns"),
    }


def run_multi_backtest(strategy_map: dict, df: pd.DataFrame) -> dict[str, dict]:
    """
    运行多策略回测对比。

    参数:
        strategy_map: {"策略名": (策略类, 参数字典)}  e.g. {"MACross": (MACrossStrategy, {"fast": 5} ...)}
        df: 行情数据
    返回:
        {"策略名": 结果字典, ...}
    """
    results = {}
    for name, (cls, params) in strategy_map.items():
        print(f"\n{'='*50}\n运行策略: {name}\n{'='*50}")
        results[name] = run_backtest(cls, df, params)
    return results


def _safe_analyzer(strat, name: str, key: str | None = None):
    """安全获取分析器结果"""
    try:
        ana = strat.analyzers.getbyname(name)
        if ana is None:
            return None
        result = ana.get_analysis()
        if key and isinstance(result, dict):
            return result.get(key)
        return result
    except Exception:
        return None
