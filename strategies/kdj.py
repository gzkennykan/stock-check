"""
KDJ 策略：K线上穿D线且处于超卖区买入，K线下穿D线且处于超买区卖出
"""
import backtrader as bt
from .base_strategy import BaseStrategy


class KDJStrategy(BaseStrategy):
    params = (
        ("period", 9),
        ("period_dfast", 3),
        ("period_dslow", 3),
        ("upper", 80),
        ("lower", 20),
        ("stop_loss", 0.05),
        ("take_profit", 0.10),
        ("trailing_stop", 0.0),
        ("position_pct", 0.95),
    )

    def __init__(self):
        super().__init__()
        self.kdj = bt.ind.StochasticFull(
            self.data,
            period=self.params.period,
            period_dfast=self.params.period_dfast,
            period_dslow=self.params.period_dslow,
        )
        self.k = self.kdj.lines.percK
        self.d = self.kdj.lines.percD
        self.cross_kd = bt.ind.CrossOver(self.k, self.d)

    def next(self):
        if self.order:
            return

        if self.position.size > 0 and self.check_stop_loss():
            self.exit_position()
            return

        # K线上穿D线 且 K值处于超卖区 → 买入
        if self.cross_kd > 0 and self.k[0] < self.params.lower and self.position.size == 0:
            s = self.size()
            if s > 0:
                self.buy(size=s)
        # K线下穿D线 且 K值处于超买区 → 卖出
        elif self.cross_kd < 0 and self.k[0] > self.params.upper and self.position.size > 0:
            self.exit_position()
