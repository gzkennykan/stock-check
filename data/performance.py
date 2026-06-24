"""
绩效分析模块：核心指标计算 + 专业可视化

指标:
  - 收益类: 累计收益、年化收益、月度收益
  - 风险类: 年化波动率、最大回撤、回撤持续期、VaR(95%)
  - 风险调整: Sharpe比率、Calmar比率、Sortino比率、信息比率
  - 交易类: 胜率、盈亏比、平均持仓天数、换手率

输入: Backtrader Cerebro 结果 或 纯 pandas 净值序列
"""
import numpy as np
import pandas as pd
from datetime import datetime


# ══════════════════════════════════════════════════════════
# 从 backtrader Cerebro 提取数据
# ══════════════════════════════════════════════════════════

def extract_from_cerebro(cerebro, benchmark_returns: pd.Series = None) -> dict:
    """
    从 backtrader Cerebro 实例提取回测绩效数据。

    返回 dict 包含:
        equity_curve:     pd.Series (index=date, values=账户净值)
        trades:           list[dict]
        daily_returns:    pd.Series
        monthly_returns:  pd.DataFrame
        metrics:          dict{ 各项指标 }
    """
    import backtrader as bt

    # 获取首个 strategy
    strats = cerebro.runstrats
    if not strats:
        return {"error": "回测未产生策略实例"}
    strat = strats[0]

    # ── 权益曲线 ──
    equity_curve = None
    try:
        # 方法1: TimeReturn analyzer
        from backtrader.analyzers import TimeReturn
        for analyzer in strat.analyzers:
            if isinstance(analyzer, TimeReturn):
                tr = analyzer.get_analysis()
                if tr:
                    equity_curve = pd.Series(tr)
    except Exception:
        pass

    if equity_curve is None:
        # 方法2: 手动从 observer 提取
        try:
            vals = []
            dates = []
            for observer in strat.getobservers():
                if hasattr(observer, 'lines') and hasattr(observer.lines, 'value'):
                    for i in range(len(observer)):
                        vals.append(observer.lines.value[i])
                        dates.append(observer.lines.datetime.datetime(i))
            if vals:
                equity_curve = pd.Series(vals, index=dates)
        except Exception:
            return {"error": "无法提取权益曲线"}

    if equity_curve.empty:
        return {"error": "权益曲线为空"}

    equity_curve = pd.Series(equity_curve)
    equity_curve.index = pd.to_datetime(equity_curve.index)

    # ── 日收益率 ──
    daily_returns = equity_curve.pct_change().dropna()

    # ── 交易记录 ──
    trades_list = []
    try:
        for t in strat.trades:
            if t.isclosed:
                trades_list.append({
                    "ref": t.ref,
                    "entry": t.dtopen,
                    "exit": t.dtclose,
                    "size": t.size,
                    "entry_price": t.price,
                    "exit_price": t.price + t.pnl / t.size if t.size else 0,
                    "pnl": t.pnl,
                    "pnl_pct": t.pnlcomm / (t.price * t.size) if t.price and t.size else 0,
                    "bars": t.baropen - t.barclose if hasattr(t, 'baropen') and hasattr(t, 'barclose') else 0,
                })
    except Exception:
        pass

    # ── 核心指标 ──
    metrics = compute_metrics(equity_curve, daily_returns, trades_list, benchmark_returns)

    # ── 月度收益 ──
    monthly_returns = _compute_monthly_returns(equity_curve)

    return {
        "equity_curve": equity_curve,
        "daily_returns": daily_returns,
        "trades": trades_list,
        "monthly_returns": monthly_returns,
        "metrics": metrics,
    }


# ══════════════════════════════════════════════════════════
# 核心指标计算（纯 pandas，不依赖 backtrader）
# ══════════════════════════════════════════════════════════

def compute_metrics(
    equity: pd.Series,
    daily_returns: pd.Series = None,
    trades: list = None,
    benchmark_returns: pd.Series = None,
    risk_free_rate: float = 0.03,
) -> dict:
    """
    从权益曲线和交易记录计算全套绩效指标。

    参数:
        equity:             权益曲线 (index=datetime, values=净值)
        daily_returns:      日收益率序列（None 时自动计算）
        trades:             交易记录 list[dict]
        benchmark_returns:  基准日收益（用于IR计算）
        risk_free_rate:     无风险利率（年化，默认3%）

    返回:
        dict with keys:
            total_return, cagr, volatility, sharpe, calmar, sortino,
            max_drawdown, max_dd_duration, var_95, information_ratio,
            win_rate, profit_factor, avg_win, avg_loss, avg_bars,
            total_trades, best_trade, worst_trade, n_months_positive
    """
    if daily_returns is None:
        daily_returns = equity.pct_change().dropna()

    if len(daily_returns) == 0:
        return {"error": "数据不足"}

    # 交易日数
    n_days = len(daily_returns)
    n_years = n_days / 252

    # ── 收益 ──
    initial = equity.iloc[0]
    final = equity.iloc[-1]
    total_return = (final / initial - 1) if initial > 0 else 0
    cagr = (final / initial) ** (1 / n_years) - 1 if n_years > 0 and initial > 0 else 0

    # ── 风险 ──
    volatility = daily_returns.std() * np.sqrt(252) if len(daily_returns) > 1 else 0
    downside = daily_returns[daily_returns < 0]
    downside_std = downside.std() * np.sqrt(252) if len(downside) > 1 else 0
    var_95 = np.percentile(daily_returns, 5) if len(daily_returns) > 0 else 0

    # 最大回撤
    cummax = equity.expanding().max()
    drawdown = (equity - cummax) / cummax
    max_dd = drawdown.min()

    # 回撤持续期（最长水下天数）
    underwater = drawdown < 0
    max_dd_duration = 0
    current_duration = 0
    for uw in underwater:
        if uw:
            current_duration += 1
            max_dd_duration = max(max_dd_duration, current_duration)
        else:
            current_duration = 0

    # ── 风险调整收益 ──
    daily_rf = risk_free_rate / 252
    excess_mean = daily_returns.mean() - daily_rf
    sharpe = excess_mean / daily_returns.std() * np.sqrt(252) if daily_returns.std() > 0 else 0
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0
    sortino = excess_mean / (downside_std / np.sqrt(252)) if downside_std > 0 else 0

    # 信息比率
    information_ratio = None
    if benchmark_returns is not None and len(benchmark_returns) == len(daily_returns):
        diff = daily_returns.values - benchmark_returns.values
        ir_mean = diff.mean()
        ir_std = diff.std()
        information_ratio = ir_mean / ir_std * np.sqrt(252) if ir_std > 0 else 0

    # ── 交易统计 ──
    total_trades = len(trades) if trades else 0
    win_rate = 0.0
    profit_factor = 0.0
    avg_win = 0.0
    avg_loss = 0.0
    avg_bars = 0
    best_trade = 0.0
    worst_trade = 0.0

    if trades:
        pnls = [t.get("pnl", 0) for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        win_rate = len(wins) / len(pnls) if pnls else 0
        total_wins = sum(wins)
        total_losses = abs(sum(losses))
        profit_factor = total_wins / total_losses if total_losses > 0 else (999 if total_wins > 0 else 0)

        avg_win = sum(wins) / len(wins) if wins else 0
        avg_loss = sum(losses) / len(losses) if losses else 0
        best_trade = max(pnls)
        worst_trade = min(pnls)

        bars_list = [t.get("bars", 0) for t in trades if t.get("bars", 0)]
        avg_bars = sum(bars_list) / len(bars_list) if bars_list else 0

    # ── 月度正收益比例 ──
    monthly = _compute_monthly_returns(equity)
    n_months_positive = int((monthly["return"] > 0).sum()) if not monthly.empty else 0

    return {
        "total_return": round(total_return * 100, 2),
        "cagr": round(cagr * 100, 2),
        "volatility": round(volatility * 100, 2),
        "sharpe": round(sharpe, 2),
        "calmar": round(calmar, 2),
        "sortino": round(sortino, 2),
        "max_drawdown": round(max_dd * 100, 2),
        "max_dd_duration": max_dd_duration,
        "var_95": round(var_95 * 100, 2),
        "information_ratio": round(information_ratio, 2) if information_ratio is not None else None,
        "win_rate": round(win_rate * 100, 2),
        "profit_factor": round(profit_factor, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "total_trades": total_trades,
        "best_trade": round(best_trade, 2),
        "worst_trade": round(worst_trade, 2),
        "avg_bars": round(avg_bars, 1),
        "n_months_positive": n_months_positive,
        "n_years": round(n_years, 2),
        "n_days": n_days,
    }


def _compute_monthly_returns(equity: pd.Series) -> pd.DataFrame:
    """计算月度收益表"""
    if len(equity) < 2:
        return pd.DataFrame()

    monthly = equity.resample("ME").last().dropna()
    if len(monthly) < 2:
        return pd.DataFrame()

    monthly_ret = monthly.pct_change().dropna() * 100
    months = []
    for dt, ret in monthly_ret.items():
        months.append({
            "year": dt.year,
            "month": dt.month,
            "return": round(ret, 2),
        })

    df = pd.DataFrame(months)
    if df.empty:
        return df

    # 转成 year × month 透视表
    pivot = df.pivot(index="year", columns="month", values="return")
    pivot.columns = [f"{m}月" for m in pivot.columns]
    pivot = pivot.fillna("—")

    # 年度汇总
    pivot["年度收益%"] = df.groupby("year")["return"].sum().round(2).values

    return pivot


def compute_rolling_metrics(
    equity: pd.Series, window: int = 60
) -> dict[str, pd.Series]:
    """
    计算滚动指标（滑动窗口）。

    返回:
        { "sharpe": Series, "volatility": Series, "returns": Series, "drawdown": Series }
    """
    daily = equity.pct_change().dropna()
    if len(daily) < window:
        return {}

    rolling_ret = daily.rolling(window).mean() * 252
    rolling_vol = daily.rolling(window).std() * np.sqrt(252)
    rolling_sharpe = rolling_ret / rolling_vol

    cummax = equity.rolling(window).max()
    rolling_dd = (equity - cummax) / cummax

    return {
        "sharpe": rolling_sharpe.dropna(),
        "volatility": rolling_vol.dropna(),
        "annual_return": rolling_ret.dropna(),
        "drawdown": rolling_dd.dropna(),
    }


def compute_trade_distribution(trades: list) -> dict:
    """
    交易分布分析。

    返回:
        { "pnl_bins": pd.Series, "duration_bins": pd.Series, "monthly_trades": pd.Series }
    """
    if not trades:
        return {}

    pnls = pd.Series([t.get("pnl", 0) for t in trades])
    bars = pd.Series([t.get("bars", 0) for t in trades])

    # PnL 分桶
    pnl_bins = pd.cut(
        pnls,
        bins=[-np.inf, -5000, -2000, -500, 0, 500, 2000, 5000, np.inf],
        labels=["<-5000", "-5000~-2000", "-2000~-500", "-500~0",
                "0~500", "500~2000", "2000~5000", ">5000"],
    ).value_counts().sort_index()

    # 持仓天数分桶
    dur_bins = pd.cut(
        bars,
        bins=[0, 1, 3, 5, 10, 20, 50, np.inf],
        labels=["1天", "1-3天", "3-5天", "5-10天", "10-20天", "20-50天", ">50天"],
    ).value_counts().sort_index()

    return {
        "pnl_distribution": pnl_bins,
        "duration_distribution": dur_bins,
    }
