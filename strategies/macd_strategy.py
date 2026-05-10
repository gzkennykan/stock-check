"""
MACD 策略：DIF 上穿 DEA 买入，DIF 下穿 DEA 卖出
"""
import backtrader as bt
from .base_strategy import BaseStrategy


class MACDStrategy(BaseStrategy):
    params = (
        ("fast_period", 12),
        ("slow_period", 26),
        ("signal_period", 9),
        ("stop_loss", 0.05),
        ("take_profit", 0.10),
        ("trailing_stop", 0.0),
        ("position_pct", 0.95),
    )

    def __init__(self):
        super().__init__()
        self.macd = bt.ind.MACD(
            self.data.close,
            period_me1=self.params.fast_period,
            period_me2=self.params.slow_period,
            period_signal=self.params.signal_period,
        )
        self.crossover = bt.ind.CrossOver(self.macd.macd, self.macd.signal)

    def next(self):
        if self.order:
            return

        if self.position.size > 0 and self.check_stop_loss():
            self.exit_position()
            return

        # DIF 上穿 DEA (金叉) 买入
        if self.crossover > 0 and self.position.size == 0:
            s = self.size()
            if s > 0:
                self.buy(size=s)

        # DIF 下穿 DEA (死叉) 卖出
        elif self.crossover < 0 and self.position.size > 0:
            self.exit_position()
