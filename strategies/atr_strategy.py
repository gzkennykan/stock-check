"""
ATR动态跟踪策略：短线上穿长线买入，使用ATR动态跟踪止损
"""
import backtrader as bt
from .base_strategy import BaseStrategy


class ATRStrategy(BaseStrategy):
    params = (
        ("fast_period", 10),
        ("slow_period", 30),
        ("atr_period", 14),
        ("atr_mult", 3.0),
        ("stop_loss", 0.05),
        ("take_profit", 0.20),
        ("trailing_stop", 0.0),
        ("position_pct", 0.95),
    )

    def __init__(self):
        super().__init__()
        self.fast_ma = bt.ind.SMA(self.data.close, period=self.params.fast_period)
        self.slow_ma = bt.ind.SMA(self.data.close, period=self.params.slow_period)
        self.atr = bt.ind.ATR(self.data, period=self.params.atr_period)
        self.crossover = bt.ind.CrossOver(self.fast_ma, self.slow_ma)
        # ATR 动态跟踪止损的最高价
        self.trailing_high = None
        self.entry_atr = None

    def next(self):
        if self.order:
            return

        # ATR 跟踪止损
        if self.position.size > 0 and self.buy_price is not None:
            if self.trailing_high is None:
                self.trailing_high = self.data.close[0]
                self.entry_atr = self.atr[0]
            self.trailing_high = max(self.trailing_high, self.data.close[0])
            stop_price = self.trailing_high - self.params.atr_mult * self.atr[0]
            if self.data.close[0] <= stop_price:
                self.log(f"ATR跟踪止损 price={self.data.close[0]:.2f} atr={self.atr[0]:.2f}")
                self.exit_position()
                return

        # 固定止损/止盈
        if self.position.size > 0 and self.check_stop_loss():
            self.exit_position()
            return

        # 金叉买入
        if self.crossover > 0 and self.position.size == 0:
            s = self.size()
            if s > 0:
                self.buy(size=s)
                self.trailing_high = None
                self.entry_atr = None

        # 死叉卖出
        elif self.crossover < 0 and self.position.size > 0:
            self.exit_position()
