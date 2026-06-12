"""
批量回测：对板块/行业全部成分股并行回测，横向对比策略表现
"""
import pandas as pd
import numpy as np
from pathlib import Path
from .database import get_kline, get_latest_trading_date
from .industry_db import get_industry_list_from_db, get_industry_stocks_from_db


def run_sector_backtest(
    strategy_cls,
    symbols: list[str],
    start: str,
    end: str,
    params: dict,
    max_stocks: int = 50,
) -> pd.DataFrame:
    """
    对一组股票批量运行回测，返回排名结果。

    参数:
        strategy_cls: 回测策略类
        symbols: 股票代码列表
        start/end: 回测日期
        params: 策略参数 dict
        max_stocks: 单次最多回测股票数（防止超时）

    返回:
        DataFrame: symbol, total_return, annual_return, sharpe, max_dd, win_rate, trades
    """
    from backtest.engine import run_backtest

    results = []
    syms = symbols[:max_stocks]

    for sym in syms:
        try:
            df = get_kline(sym, start, end)
            if df.empty or len(df) < 50:
                continue

            result = run_backtest(strategy_cls, df, params)
            if "error" in result:
                continue

            strat = result["strategy"]
            start_val = result.get("start_value", 1_000_000)
            end_val = result.get("end_value", start_val)
            total_ret = (end_val / start_val - 1) if start_val > 0 else 0

            # 提取夏普和回撤
            try:
                sharpe = strat.analyzers.sharpe.get_analysis().get("sharperatio") or 0
            except Exception:
                sharpe = 0

            try:
                dd_info = strat.analyzers.drawdown.get_analysis().get("max", {})
                max_dd = dd_info.get("drawdown", 0)
            except Exception:
                max_dd = 0

            # 交易统计
            trades = strat.completed_trades if hasattr(strat, "completed_trades") else []
            win_count = sum(1 for t in trades if (
                t.get("pnl", t.pnlcomm if hasattr(t, "pnlcomm") else 0) > 0
            ))
            total_trades = len(trades)
            win_rate = win_count / total_trades if total_trades > 0 else 0

            results.append({
                "symbol": sym,
                "total_return": round(total_ret * 100, 2),
                "annual_return": round(total_ret * 100, 2),  # simplified
                "sharpe": round(sharpe, 2),
                "max_dd": round(max_dd * 100, 2),
                "win_rate": round(win_rate * 100, 1),
                "trades": total_trades,
            })
        except Exception:
            continue

    if not results:
        return pd.DataFrame()

    result = pd.DataFrame(results)
    result["rank"] = result["total_return"].rank(ascending=False).astype(int)
    result = result.sort_values("rank")
    return result.reset_index(drop=True)


def run_industry_backtest(
    strategy_cls,
    industry_name: str,
    start: str,
    end: str,
    params: dict,
    max_stocks: int = 30,
) -> pd.DataFrame:
    """
    对某个行业的所有成分股进行批量回测。

    返回:
        同 run_sector_backtest
    """
    symbols = get_industry_stocks_from_db(industry_name)
    if not symbols:
        return pd.DataFrame()
    return run_sector_backtest(strategy_cls, symbols, start, end, params, max_stocks)
