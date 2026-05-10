"""
RSI 超买超卖策略：RSI < 超卖阈值买入，RSI > 超买阈值卖出
"""
import backtrader as bt
from .base_strategy import BaseStrategy


class RSIStrategy(BaseStrategy):
    params = (
        ("rsi_period", 14),
        ("oversold", 30),         # 超卖阈值
        ("overbought", 70),       # 超买阈值
        ("stop_loss", 0.05),
        ("take_profit", 0.10),
        ("trailing_stop", 0.0),
        ("position_pct", 0.95),
    )

    def __init__(self):
        super().__init__()
        self.rsi = bt.ind.RSI(self.data.close, period=self.params.rsi_period)

    def next(self):
        if self.order:
            return

        if self.position.size > 0 and self.check_stop_loss():
            self.exit_position()
            return

        rsi_val = self.rsi[0]

        # RSI 进入超卖区 -> 买入
        if rsi_val < self.params.oversold and self.position.size == 0:
            s = self.size()
            if s > 0:
                self.buy(size=s)

        # RSI 进入超买区 -> 卖出
        elif rsi_val > self.params.overbought and self.position.size > 0:
            self.exit_position()
