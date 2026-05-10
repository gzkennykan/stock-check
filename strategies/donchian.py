"""
唐奇安通道策略：价格突破N日最高价买入，跌破N日最低价卖出
"""
import backtrader as bt
from .base_strategy import BaseStrategy


class DonchianStrategy(BaseStrategy):
    params = (
        ("period", 20),
        ("stop_loss", 0.05),
        ("take_profit", 0.15),
        ("trailing_stop", 0.0),
        ("position_pct", 0.95),
    )

    def __init__(self):
        super().__init__()
        self.donchian_h = bt.ind.Highest(self.data.high, period=self.params.period)
        self.donchian_l = bt.ind.Lowest(self.data.low, period=self.params.period)
        self.donchian_mid = (self.donchian_h + self.donchian_l) / 2

    def next(self):
        if self.order:
            return

        if self.position.size > 0 and self.check_stop_loss():
            self.exit_position()
            return

        close = self.data.close[0]
        # 价格突破N日最高价 → 买入
        if close > self.donchian_h[-1] and self.position.size == 0:
            s = self.size()
            if s > 0:
                self.buy(size=s)
        # 价格跌破通道中线 → 卖出
        elif close < self.donchian_mid[0] and self.position.size > 0:
            self.exit_position()
