"""
A 股交易成本模型：佣金、印花税、过户费
"""
import backtrader as bt
from config import COMMISSION_RATE, STAMP_TAX, SLIPPAGE


class AShareCommission(bt.CommInfoBase):
    params = (
        ("commission", COMMISSION_RATE),  # 佣金万三
        ("stamp_duty", STAMP_TAX),        # 印花税千一 (卖出)
        ("stamp_duty_side", "sell"),      # 只在卖出时收印花税
    )

    def _getcommission(self, size, price, pseudoexec):
        value = abs(size) * price
        comm = max(value * self.params.commission, 5.0)  # 最低5元
        if self.params.stamp_duty_side == "sell" and size < 0:
            comm += value * self.params.stamp_duty
        elif self.params.stamp_duty_side == "buy" and size > 0:
            comm += value * self.params.stamp_duty
        return comm


def set_a_share_broker(cerebro: bt.Cerebro) -> None:
    """为 cerebro 配置 A 股交易成本"""
    comm_info = AShareCommission()
    cerebro.broker.addcommissioninfo(comm_info)
    cerebro.broker.set_slippage_perc(SLIPPAGE)
