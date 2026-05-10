"""
三均线策略：快线 > 中线 > 慢线 多头排列买入，快线下穿慢线卖出
"""
import backtrader as bt
from .base_strategy import BaseStrategy


class TripleMAStrategy(BaseStrategy):
    params = (
        ("fast_period", 5),
        ("mid_period", 20),
        ("slow_period", 60),
        ("stop_loss", 0.05),
        ("take_profit", 0.15),
        ("trailing_stop", 0.0),
        ("position_pct", 0.95),
    )

    def __init__(self):
        super().__init__()
        self.fast_ma = bt.ind.SMA(self.data.close, period=self.params.fast_period)
        self.mid_ma = bt.ind.SMA(self.data.close, period=self.params.mid_period)
        self.slow_ma = bt.ind.SMA(self.data.close, period=self.params.slow_period)
        self.cross_fast_mid = bt.ind.CrossOver(self.fast_ma, self.mid_ma)

    def next(self):
        if self.order:
            return

        if self.position.size > 0 and self.check_stop_loss():
            self.exit_position()
            return

        # 快线 > 中线 > 慢线 且 快线上穿中线 → 买入
        aligned = (self.fast_ma[0] > self.mid_ma[0] > self.slow_ma[0])
        if self.cross_fast_mid > 0 and aligned and self.position.size == 0:
            s = self.size()
            if s > 0:
                self.buy(size=s)
        # 快线下穿中线 → 卖出
        elif self.cross_fast_mid < 0 and self.position.size > 0:
            self.exit_position()
