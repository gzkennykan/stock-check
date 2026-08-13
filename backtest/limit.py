"""
A 股涨跌停规则：按板块计算涨跌停幅度

板块规则（注册制全面落地后）:
  主板(60/00)      ±10%
  创业板(300/301)  ±20%
  科创板(688/689)  ±20%
  北交所(8/4)      ±30%

ST 股说明：2026-07-06 起主板 ST 涨跌幅由 ±5% 放宽至 ±10%，与所在板块普通股一致；
创业板/科创板/北交所 ST 历来与板块一致。故 ST 不再单独区分涨跌停幅度。
"""


def limit_pct(symbol: str = "", name: str = "") -> float:
    """
    返回单日涨跌停幅度（小数，如 0.10 表示 ±10%）。
    name 参数保留（当前 ST 已不单独区分幅度，留作未来扩展用）。
    """
    s = str(symbol).strip().zfill(6)
    if s.startswith(("300", "301", "688", "689")):
        return 0.20
    elif s.startswith(("8", "4")):
        return 0.30
    return 0.10


def limit_up_price(prev_close: float, symbol: str = "", name: str = "") -> float:
    """涨停价 = 昨收 × (1 + 幅度)，四舍五入到分。"""
    return round(prev_close * (1 + limit_pct(symbol, name)), 2)


def limit_down_price(prev_close: float, symbol: str = "", name: str = "") -> float:
    """跌停价 = 昨收 × (1 - 幅度)，四舍五入到分。"""
    return round(prev_close * (1 - limit_pct(symbol, name)), 2)
