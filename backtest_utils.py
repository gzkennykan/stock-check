"""
回测公共函数：数据加载、指标展示、交易明细
"""
import streamlit as st
import pandas as pd
from data.fetcher import fetch_data, fetch_benchmark
from backtest.engine import run_backtest
from analysis.metrics import compute_metrics, compute_benchmark_metrics
from config import INITIAL_CASH, DEFAULT_BENCHMARK


@st.cache_data(ttl=3600)
def load_data(symbol: str, start: str, end: str) -> pd.DataFrame:
    try:
        return fetch_data(symbol, start, end)
    except Exception:
        return pd.DataFrame()


def get_equity_curve(strat) -> pd.Series | None:
    try:
        ana = strat.analyzers.getbyname("returns")
        if ana is None:
            return None
        rets = ana.get_analysis()
        if not rets or len(rets) < 1:
            return None
        dates = list(rets.keys())
        vals = [INITIAL_CASH]
        for dt in dates:
            vals.append(vals[-1] * (1 + rets[dt]))
        return pd.Series(vals[1:], index=dates)
    except Exception:
        return None


def get_daily_returns(strat) -> list[float]:
    try:
        ana = strat.analyzers.getbyname("returns")
        if ana is None:
            return []
        return list(ana.get_analysis().values())
    except Exception:
        return []


def run_single_backtest(symbol, strategy_cls, params, start, end,
                        benchmark_code: str = DEFAULT_BENCHMARK):
    """运行回测并返回 metrics + charts 数据（含基准对比）"""
    df = load_data(symbol, start, end)
    if df.empty:
        st.error(f"未能获取 {symbol} 的行情数据")
        return None

    result = run_backtest(strategy_cls, df, params)
    if "error" in result:
        st.error(result["error"])
        return None

    strat = result["strategy"]
    equity = get_equity_curve(strat)
    daily_rets = get_daily_returns(strat)

    metrics = compute_metrics(
        returns=daily_rets, equity_curve=equity,
        start_value=result["start_value"], end_value=result["end_value"],
        trades_result=result.get("trades"),
    )

    # 获取基准数据
    benchmark_df = None
    benchmark_metrics = None
    bm_equity = None
    try:
        benchmark_df = fetch_benchmark(benchmark_code, start, end)
        if benchmark_df is not None and not benchmark_df.empty and equity is not None:
            bm_metrics = compute_benchmark_metrics(
                equity, benchmark_df["close"],
                INITIAL_CASH, f"沪深300" if benchmark_code == "000300" else benchmark_code,
            )
            if bm_metrics is not None:
                benchmark_metrics = bm_metrics
                # 构建基准权益曲线用于图表叠加
                common_dates = equity.index.intersection(benchmark_df.index)
                if len(common_dates) >= 2:
                    bm_aligned = benchmark_df["close"].loc[common_dates]
                    bm_equity = INITIAL_CASH * (bm_aligned / bm_aligned.iloc[0])
    except Exception:
        pass

    return {
        "metrics": metrics,
        "equity": equity,
        "df": df,
        "result": result,
        "benchmark_metrics": benchmark_metrics,
        "bm_equity": bm_equity,
    }


def display_metric_cards(metrics):
    """显示指标卡片行"""
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        delta_color = "normal" if metrics.total_return >= 0 else "inverse"
        st.metric("累计收益率", f"{metrics.total_return:.2%}",
                  delta=f"¥{metrics.end_value - metrics.start_value:,.0f}",
                  delta_color=delta_color)
    with c2:
        st.metric("年化收益率", f"{metrics.annual_return:.2%}")
    with c3:
        st.metric("夏普比率", f"{metrics.sharpe_ratio:.2f}" if metrics.sharpe_ratio else "N/A")
    with c4:
        st.metric("最大回撤", f"{-metrics.max_drawdown:.2%}")

    c5, c6, c7, c8 = st.columns(4)
    with c5:
        st.metric("胜率", f"{metrics.win_rate:.2%}" if metrics.win_rate else "N/A")
    with c6:
        st.metric("盈亏比", f"{metrics.profit_loss_ratio:.2f}" if metrics.profit_loss_ratio else "N/A")
    with c7:
        st.metric("交易次数", metrics.total_trades)
    with c8:
        st.metric("卡玛比率", f"{metrics.calmar_ratio:.2f}" if metrics.calmar_ratio else "N/A")


def display_benchmark_metrics(bm):
    """显示基准对比指标卡片行"""
    if bm is None:
        return
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("超额收益 (vs 基准)", f"{bm.excess_return:+.2%}")
    with c2:
        st.metric("Alpha (年化)", f"{bm.alpha:+.2%}")
    with c3:
        st.metric("Beta", f"{bm.beta:.2f}")
    with c4:
        ir_str = f"{bm.information_ratio:.2f}" if bm.information_ratio else "N/A"
        st.metric("信息比率", ir_str)

    c5, c6, c7, c8 = st.columns(4)
    with c5:
        te_str = f"{bm.tracking_error:.2%}" if bm.tracking_error else "N/A"
        st.metric("跟踪误差", te_str)
    with c6:
        st.metric("基准累计收益", f"{bm.benchmark_return:.2%}")
    with c7:
        st.metric("基准年化收益", f"{bm.benchmark_annual_return:.2%}")
    with c8:
        st.caption(f"基准: {bm.benchmark_name}")


def get_trade_list(strat) -> pd.DataFrame:
    """从策略提取交易明细"""
    trades = []
    for t in strat.completed_trades:
        if isinstance(t, dict):
            entry_date = t["entry_date"]
            exit_date = t["exit_date"]
            entry_price = t["entry_price"]
            size = t["size"]
            pnl = t["pnl"]
        else:
            try:
                entry_date = t.open_datetime()
                exit_date = t.close_datetime()
                entry_price = t.price
                size = abs(t.size)
                pnl = t.pnlcomm
            except Exception:
                continue

        exit_price = entry_price + pnl / size if size else entry_price

        trades.append({
            "开仓日": entry_date,
            "平仓日": exit_date,
            "开仓价": round(entry_price, 2),
            "平仓价": round(exit_price, 2),
            "数量(股)": size,
            "盈亏(元)": round(pnl, 2),
            "收益率(%)": round(pnl / (entry_price * size) * 100, 2),
        })
    return pd.DataFrame(trades)


def optuna_objective(trial, strategy_cls, df, param_configs: list[dict], target: str):
    """Optuna 目标函数。param_configs 每项含 name/type/min/max/step"""
    params = {}
    for pc in param_configs:
        if pc["type"] == "float":
            params[pc["name"]] = trial.suggest_float(pc["name"], pc["min"], pc["max"], step=pc.get("step"))
        else:
            params[pc["name"]] = trial.suggest_int(pc["name"], pc["min"], pc["max"], step=pc.get("step", 1))

    from backtest.engine import CerebroBuilder
    builder = CerebroBuilder()
    builder.add_data(df)
    builder.add_strategy(strategy_cls, **params)
    cerebro = builder.build()
    results = cerebro.run()
    if not results:
        return -999

    strat = results[0]
    end_val = strat.broker.getvalue()
    start_val = 1000000.0
    total_ret = (end_val / start_val) - 1

    try:
        sharpe = strat.analyzers.sharpe.get_analysis().get("sharperatio") or 0
    except Exception:
        sharpe = 0

    try:
        dd = strat.analyzers.drawdown.get_analysis().get("max", {}).get("drawdown", 0)
    except Exception:
        dd = 0

    if target == "sharpe":
        return sharpe
    elif target == "drawdown":
        return -dd
    return total_ret
