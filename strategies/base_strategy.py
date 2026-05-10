"""
策略基类：提供止损/止盈/仓位管理等通用能力
"""
import backtrader as bt


class BaseStrategy(bt.Strategy):
    params = (
        ("stop_loss", 0.05),      # 止损比例 (5%)
        ("take_profit", 0.15),    # 止盈比例 (15%)
        ("trailing_stop", 0.0),   # 跟踪止损比例 (0=禁用)
        ("position_pct", 0.95),   # 仓位使用比例
    )

    def __init__(self):
        super().__init__()
        self.order = None
        self.buy_price = None
        self.max_price = None     # 持仓期间最高价 (用于跟踪止损)
        self._buy_size = 0        # 记录最近买入数量，用于交易明细
        self._sell_price = None   # 记录最近卖出价格
        self.completed_trades = []  # 记录已完成交易，供 UI 展示用

    def notify_order(self, order):
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_price = order.executed.price
                self.max_price = self.buy_price
                self._buy_size = order.executed.size
                self.log(f"买入 价格={order.executed.price:.2f} 数量={order.executed.size}")
            else:
                self._sell_price = order.executed.price
                self.buy_price = None
                self.max_price = None
                self.log(f"卖出 价格={order.executed.price:.2f} 数量={order.executed.size}")
        self.order = None

    def notify_trade(self, trade):
        if trade.isclosed:
            self.completed_trades.append({
                "entry_date": trade.open_datetime(),
                "exit_date": trade.close_datetime(),
                "entry_price": trade.price,
                "exit_price": self._sell_price,
                "size": self._buy_size,
                "pnl": trade.pnlcomm,
            })
            self.log(f"交易盈亏: {trade.pnl:.2f} 净盈亏: {trade.pnlcomm:.2f}")

    def log(self, txt: str) -> None:
        dt = self.datas[0].datetime.date(0)
        print(f"[{dt.isoformat()}] {txt}")

    def check_stop_loss(self) -> bool:
        """检查是否触发止损/止盈/跟踪止损"""
        if self.position.size <= 0 or self.buy_price is None:
            return False

        current = self.data.close[0]
        pnl_pct = (current - self.buy_price) / self.buy_price

        # 固定止损
        if self.params.stop_loss > 0 and pnl_pct <= -self.params.stop_loss:
            self.log(f"触发止损 pnl={pnl_pct:.2%}")
            return True

        # 固定止盈
        if self.params.take_profit > 0 and pnl_pct >= self.params.take_profit:
            self.log(f"触发止盈 pnl={pnl_pct:.2%}")
            return True

        # 跟踪止损
        if self.params.trailing_stop > 0 and self.max_price is not None:
            self.max_price = max(self.max_price, current)
            if current <= self.max_price * (1 - self.params.trailing_stop):
                self.log(f"触发跟踪止损 price={current:.2f}")
                return True

        return False

    def exit_position(self) -> None:
        """清仓"""
        if self.position.size > 0:
            self.close()

    def size(self) -> int:
        """计算每次买入的股数 (按可用资金和仓位比例)"""
        cash = self.broker.get_cash()
        price = self.data.close[0]
        target_value = cash * self.params.position_pct
        size = int(target_value / price)
        return max(size, 0)
