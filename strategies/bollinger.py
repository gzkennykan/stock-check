"""
布林带策略：价格突破下轨后回升买入，突破上轨后回落卖出
"""
import backtrader as bt
from .base_strategy import BaseStrategy


class BollingerStrategy(BaseStrategy):
    params = (
        ("period", 20),
        ("devfactor", 2.0),
        ("stop_loss", 0.05),
        ("take_profit", 0.15),
        ("trailing_stop", 0.0),
        ("position_pct", 0.95),
    )

    def __init__(self):
        super().__init__()
        self.bb = bt.ind.BollingerBands(
            self.data.close, period=self.params.period,
            devfactor=self.params.devfactor
        )

    def next(self):
        if self.order:
            return

        if self.position.size > 0 and self.check_stop_loss():
            self.exit_position()
            return

        close = self.data.close[0]
        # 收盘价上穿上轨 → 买入
        if close > self.bb.lines.top[0] and self.position.size == 0:
            s = self.size()
            if s > 0:
                self.buy(size=s)
        # 收盘价下穿下轨 → 卖出
        elif close < self.bb.lines.mid[0] and self.position.size > 0:
            self.exit_position()
