"""
双均线交叉策略：短期均线上穿长期均线买入，下穿卖出
"""
import backtrader as bt
from .base_strategy import BaseStrategy


class MACrossStrategy(BaseStrategy):
    params = (
        ("fast_period", 5),
        ("slow_period", 20),
        ("stop_loss", 0.05),
        ("take_profit", 0.15),
        ("trailing_stop", 0.0),
        ("position_pct", 0.95),
    )

    def __init__(self):
        super().__init__()
        self.fast_ma = bt.ind.SMA(self.data.close, period=self.params.fast_period)
        self.slow_ma = bt.ind.SMA(self.data.close, period=self.params.slow_period)
        self.crossover = bt.ind.CrossOver(self.fast_ma, self.slow_ma)

    def next(self):
        if self.order:
            return

        # 止损/止盈检查
        if self.position.size > 0 and self.check_stop_loss():
            self.exit_position()
            return

        # 金叉买入
        if self.crossover > 0 and self.position.size == 0:
            s = self.size()
            if s > 0:
                self.buy(size=s)

        # 死叉卖出
        elif self.crossover < 0 and self.position.size > 0:
            self.exit_position()
