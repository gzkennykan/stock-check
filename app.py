"""
股票量化回测系统 — Streamlit 可视化界面
运行: streamlit run app.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st
import pandas as pd
from datetime import datetime

from config import INITIAL_CASH
from data.fetcher import fetch_data
from data.screener import get_stock_list, screen_stocks, get_industry_list
from data.screener import get_top_capital_inflow, get_top_capital_outflow, get_top_turnover, get_fund_flow_data
from data.screener import get_combined_data, smart_screen
from data.lhb import get_lhb_daily, get_lhb_seat_detail
from strategies import MACrossStrategy, MACDStrategy, RSIStrategy
from strategies import BollingerStrategy, TripleMAStrategy, KDJStrategy
from strategies import DonchianStrategy, ATRStrategy
from backtest.engine import run_backtest, run_multi_backtest
from analysis.metrics import compute_metrics
from visualization.plotly_charts import (
    plot_equity_drawdown, plot_kline,
    plot_comparison_chart, plot_comparison_curves, plot_optimization_history
)

st.set_page_config(page_title="股票量化回测系统", page_icon="📈", layout="wide")

STRATEGY_MAP = {
    "双均线 (MA Cross)": MACrossStrategy,
    "MACD": MACDStrategy,
    "RSI 超买超卖": RSIStrategy,
    "布林带 (Bollinger)": BollingerStrategy,
    "三均线 (Triple MA)": TripleMAStrategy,
    "KDJ": KDJStrategy,
    "唐奇安通道 (Donchian)": DonchianStrategy,
    "ATR动态跟踪": ATRStrategy,
}

HOT_STOCKS = {
    "招商银行": "600036",
    "贵州茅台": "600519",
    "宁德时代": "300750",
    "平安银行": "000001",
    "比亚迪": "002594",
}

# =========================== 辅助函数 ===========================

@st.cache_data(ttl=3600)
def load_data(symbol: str, start: str, end: str) -> pd.DataFrame:
    return fetch_data(symbol, start, end)


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


def run_single_backtest(symbol, strategy_cls, params, start, end):
    """运行回测并返回 metrics + charts 数据"""
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
    return {
        "metrics": metrics,
        "equity": equity,
        "df": df,
        "result": result,
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
        st.metric("Calmar", f"{metrics.calmar_ratio:.2f}" if metrics.calmar_ratio else "N/A")


def get_trade_list(strat) -> pd.DataFrame:
    """从策略提取交易明细 — 返回买入/卖出日期、价格、盈亏等"""
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


# =========================== 侧边栏 ===========================

st.sidebar.title("📈 股票量化回测系统")

# 快捷选股
st.sidebar.subheader("快捷选股")
cols = st.sidebar.columns(5)
for i, (name, code) in enumerate(HOT_STOCKS.items()):
    with cols[i]:
        if st.button(name, key=f"hot_{code}", use_container_width=True):
            st.session_state["symbol"] = code

symbol = st.sidebar.text_input(
    "股票代码", value=st.session_state.get("symbol", "600036"),
    help="输入6位代码，如 600036（沪深A股）"
)
if symbol:
    st.session_state["symbol"] = symbol

# 策略选择
strategy_name = st.sidebar.selectbox("交易策略", list(STRATEGY_MAP.keys()))
strategy_cls = STRATEGY_MAP[strategy_name]

# 动态策略参数
st.sidebar.subheader("策略参数")
params = {}
if strategy_name == "双均线 (MA Cross)":
    params["fast_period"] = st.sidebar.number_input("快线周期", 2, 30, 5, step=1)
    params["slow_period"] = st.sidebar.number_input("慢线周期", 10, 60, 20, step=1)
elif strategy_name == "MACD":
    params["fast_period"] = st.sidebar.number_input("快线", 6, 20, 12, step=1)
    params["slow_period"] = st.sidebar.number_input("慢线", 20, 40, 26, step=1)
    params["signal_period"] = st.sidebar.number_input("信号线", 5, 15, 9, step=1)
elif strategy_name == "RSI 超买超卖":
    params["rsi_period"] = st.sidebar.number_input("RSI 周期", 5, 30, 14, step=1)
    params["oversold"] = st.sidebar.number_input("超卖阈值", 15, 40, 30, step=1)
    params["overbought"] = st.sidebar.number_input("超买阈值", 60, 90, 70, step=1)
elif strategy_name == "布林带 (Bollinger)":
    params["period"] = st.sidebar.number_input("布林带周期", 5, 50, 20, step=1)
    params["devfactor"] = st.sidebar.number_input("标准差倍数", 1.0, 4.0, 2.0, step=0.5)
elif strategy_name == "三均线 (Triple MA)":
    params["fast_period"] = st.sidebar.number_input("快线周期", 2, 15, 5, step=1)
    params["mid_period"] = st.sidebar.number_input("中线周期", 10, 30, 20, step=1)
    params["slow_period"] = st.sidebar.number_input("慢线周期", 30, 90, 60, step=1)
elif strategy_name == "KDJ":
    params["period"] = st.sidebar.number_input("KDJ周期", 5, 20, 9, step=1)
    params["period_dfast"] = st.sidebar.number_input("K值平滑", 2, 5, 3, step=1)
    params["upper"] = st.sidebar.number_input("超买区", 60, 90, 80, step=1)
    params["lower"] = st.sidebar.number_input("超卖区", 10, 40, 20, step=1)
elif strategy_name == "唐奇安通道 (Donchian)":
    params["period"] = st.sidebar.number_input("通道周期", 10, 60, 20, step=1)
elif strategy_name == "ATR动态跟踪":
    params["fast_period"] = st.sidebar.number_input("快线周期", 5, 20, 10, step=1)
    params["slow_period"] = st.sidebar.number_input("慢线周期", 20, 60, 30, step=1)
    params["atr_period"] = st.sidebar.number_input("ATR周期", 7, 21, 14, step=1)
    params["atr_mult"] = st.sidebar.number_input("ATR倍数", 1.0, 6.0, 3.0, step=0.5)

# 风险管理
st.sidebar.subheader("风控参数")
params["stop_loss"] = st.sidebar.number_input("止损比例 (%)", 0, 20, 5, step=1) / 100
params["take_profit"] = st.sidebar.number_input("止盈比例 (%)", 0, 50, 15, step=1) / 100
params["position_pct"] = st.sidebar.number_input("仓位比例 (%)", 10, 100, 95, step=1) / 100

# 日期范围
st.sidebar.subheader("回测日期")
start_date = st.sidebar.date_input("起始日期", value=datetime(2024, 1, 1))
end_date = st.sidebar.date_input("结束日期", value=datetime(2025, 5, 8))

# 初始资金
initial_cash = st.sidebar.number_input("初始资金 (元)", value=1000000, step=100000)

st.sidebar.markdown("---")
st.sidebar.caption("数据源: AKShare (新浪/东方财富)")
st.sidebar.caption("引擎: backtrader + optuna")

# =========================== 主区域 ===========================

tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9, tab10 = st.tabs([
    "📊 单策略回测", "📋 策略对比", "🔧 参数优化", "🔍 选股池",
    "💰 资金流入TOP50", "💸 资金流出TOP50", "📈 成交额TOP50",
    "🧠 智能选股", "🐉 龙虎榜", "🔥 值博率",
])

# ---- Tab 1: 单策略回测 ----
with tab1:
    st.title(f"{strategy_name} — {symbol or '请选择股票'}")

    run_btn = st.sidebar.button("🚀 运行回测", type="primary", use_container_width=True)

    if run_btn and symbol:
        start_s = start_date.strftime("%Y-%m-%d")
        end_s = end_date.strftime("%Y-%m-%d")
        with st.spinner(f"获取 {symbol} 行情数据并运行回测..."):
            data = run_single_backtest(symbol, strategy_cls, params, start_s, end_s)

        if data:
            st.session_state["backtest_data"] = data
            st.success(f"回测完成 — {symbol} ({start_s} ~ {end_s})")
        else:
            st.stop()

        # 指标卡片
        display_metric_cards(data["metrics"])

        # 图表区
        st.subheader("资金曲线 & 回撤")
        fig1 = plot_equity_drawdown(data["equity"])
        st.plotly_chart(fig1, use_container_width=True)

        st.subheader("K线图")
        fig2 = plot_kline(data["df"].tail(120))
        st.plotly_chart(fig2, use_container_width=True)

        # 交易明细
        st.subheader("交易明细")
        trade_df = get_trade_list(data["result"]["strategy"])
        if not trade_df.empty:
            st.dataframe(trade_df, use_container_width=True, hide_index=True)
        else:
            st.info("该时段内无交易记录")


# ---- Tab 2: 策略对比 ----
with tab2:
    st.title("多策略对比")

    compare_btn = st.button("🔍 开始对比", key="compare_btn")
    if compare_btn and symbol:
        start_s = start_date.strftime("%Y-%m-%d")
        end_s = end_date.strftime("%Y-%m-%d")

        df = load_data(symbol, start_s, end_s)
        if df.empty:
            st.error(f"未能获取 {symbol} 的行情数据")
            st.stop()

        strategy_map = {}
        for name, cls in STRATEGY_MAP.items():
            strategy_map[name] = (cls, {})

        with st.spinner("运行三个策略..."):
            results = run_multi_backtest(strategy_map, df)

        # 汇总表
        rows = []
        curves = {}
        for name, r in results.items():
            if "error" in r:
                continue
            strat = r["strategy"]
            eq = get_equity_curve(strat)
            curves[name] = eq
            daily_rets = get_daily_returns(strat)
            m = compute_metrics(daily_rets, eq, r["start_value"], r["end_value"], r.get("trades"))
            rows.append({
                "策略": name.split(" ")[0],
                "累计收益": f"{m.total_return:.2%}",
                "年化收益": f"{m.annual_return:.2%}",
                "夏普比率": f"{m.sharpe_ratio:.2f}" if m.sharpe_ratio else "N/A",
                "最大回撤": f"{-m.max_drawdown:.2%}",
                "胜率": f"{m.win_rate:.2%}" if m.win_rate else "N/A",
                "盈亏比": f"{m.profit_loss_ratio:.2f}" if m.profit_loss_ratio else "N/A",
                "交易次数": m.total_trades,
                "_annual": m.annual_return,
                "_sharpe": m.sharpe_ratio or 0,
                "_dd": m.max_drawdown,
            })

        if rows:
            # 对比柱状图
            chart_data = {}
            for r in rows:
                chart_data[r["策略"]] = {
                    "annual_return": r["_annual"],
                    "sharpe_ratio": r["_sharpe"],
                    "max_drawdown": r["_dd"],
                }
            st.subheader("指标对比")
            fig_bar = plot_comparison_chart(chart_data)
            st.plotly_chart(fig_bar, use_container_width=True)

            # 资金曲线叠加
            st.subheader("资金曲线叠加")
            fig_curve = plot_comparison_curves(curves)
            st.plotly_chart(fig_curve, use_container_width=True)

            # 对比表
            st.subheader("详细对比")
            display_rows = [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]
            st.dataframe(pd.DataFrame(display_rows), use_container_width=True, hide_index=True)

            # 各策略交易明细
            st.subheader("各策略交易明细")
            for name, r in results.items():
                if "error" in r:
                    continue
                td = get_trade_list(r["strategy"])
                trade_count = len(td)
                label = f"{name}（{trade_count} 笔交易）"
                with st.expander(label, expanded=(trade_count > 0 and trade_count <= 10)):
                    if not td.empty:
                        st.dataframe(td, use_container_width=True, hide_index=True)
                    else:
                        st.caption("该策略在当前周期内无交易记录")
        else:
            st.warning("未产生策略结果")


def _optuna_objective(trial, strategy_cls, df, param_ranges, target):
    """Optuna 目标函数"""
    params = {}
    for name, (lo, hi) in param_ranges.items():
        params[name] = trial.suggest_int(name, lo, hi)

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


# ---- Tab 3: 参数优化 ----
with tab3:
    st.title("参数优化")

    st.subheader("优化设置")
    col1, col2, col3 = st.columns(3)
    with col1:
        opt_target = st.selectbox("优化目标", ["夏普比率", "年化收益", "最小回撤"])
        target_map = {"夏普比率": "sharpe", "年化收益": "return", "最小回撤": "drawdown"}
    with col2:
        n_trials = st.number_input("试验次数", min_value=10, max_value=500, value=50, step=10)
    with col3:
        st.write("")
        st.caption("次数越多越精确，但耗时更长")

    st.subheader("优化参数范围")
    if strategy_name == "双均线 (MA Cross)":
        p1_name, p1_lo, p1_hi = "fast_period", 2, 30
        p2_name, p2_lo, p2_hi = "slow_period", 10, 60
    elif strategy_name == "MACD":
        p1_name, p1_lo, p1_hi = "fast_period", 6, 24
        p2_name, p2_lo, p2_hi = "slow_period", 20, 52
    else:  # RSI
        p1_name, p1_lo, p1_hi = "rsi_period", 5, 30
        p2_name, p2_lo, p2_hi = "oversold", 15, 45

    c1, c2 = st.columns(2)
    with c1:
        p1_lo_val = st.number_input(f"{p1_name} 最小值", value=p1_lo, key=f"{p1_name}_lo")
        p1_hi_val = st.number_input(f"{p1_name} 最大值", value=p1_hi, key=f"{p1_name}_hi")
    with c2:
        p2_lo_val = st.number_input(f"{p2_name} 最小值", value=p2_lo, key=f"{p2_name}_lo")
        p2_hi_val = st.number_input(f"{p2_name} 最大值", value=p2_hi, key=f"{p2_name}_hi")

    optimize_btn = st.button("⚡ 开始优化", type="primary", key="optimize_btn")

    if optimize_btn and symbol:
        start_s = start_date.strftime("%Y-%m-%d")
        end_s = end_date.strftime("%Y-%m-%d")
        param_ranges = {
            p1_name: (p1_lo_val, p1_hi_val),
            p2_name: (p2_lo_val, p2_hi_val),
        }

        from optimizer.grid_search import optuna_search
        import optuna

        df = load_data(symbol, start_s, end_s)
        if df.empty:
            st.error(f"未能获取 {symbol} 的行情数据")
            st.stop()

        # 进度显示
        progress_bar = st.progress(0)
        status_text = st.empty()

        # 回调函数更新 Streamlit 进度
        class StreamlitCallback:
            def __init__(self, n):
                self.n = n
                self.pb = progress_bar
                self.st = status_text

            def __call__(self, study, trial):
                self.pb.progress(trial.number / self.n)
                if trial.value is not None:
                    self.st.text(f"第 {trial.number}/{self.n} 次试验 | 当前最优: {study.best_value:.4f}")

        with st.spinner(f"运行 optuna 优化... 共 {n_trials} 次试验"):
            optuna.logging.set_verbosity(optuna.logging.WARNING)
            study = optuna.create_study(direction="maximize")
            study.optimize(
                lambda trial: _optuna_objective(trial, strategy_cls, df, param_ranges, target_map[opt_target]),
                n_trials=n_trials,
                callbacks=[StreamlitCallback(n_trials)],
            )

        progress_bar.progress(1.0)
        status_text.text("优化完成!")
        st.success(f"最佳参数: {study.best_params} | 最佳值: {study.best_value:.4f}")

        # 优化历史图表
        trials_df = study.trials_dataframe()
        names = [p1_name, p2_name]
        fig_opt = plot_optimization_history(trials_df, names)
        st.plotly_chart(fig_opt, use_container_width=True)

        # 最优参数卡片
        st.subheader("最优参数组合")
        best_cols = st.columns(len(study.best_params))
        for i, (k, v) in enumerate(study.best_params.items()):
            with best_cols[i]:
                st.metric(k, v)

        st.dataframe(trials_df.head(10), use_container_width=True, hide_index=True)


# ---- Tab 4: 选股池 ----
with tab4:
    st.title("选股池")

    col_btn, col_info = st.columns([2, 3])
    with col_btn:
        refresh = st.button("🔄 刷新行情数据", use_container_width=True)
    with col_info:
        st.caption("数据每5分钟缓存一次，点击刷新获取最新行情")

    # 获取全市场数据
    with st.spinner("正在获取全 A 股行情数据..."):
        try:
            full_df = get_stock_list(force_refresh=refresh)
        except Exception as e:
            st.error(f"获取行情数据失败: {e}")
            st.stop()

    if full_df.empty:
        st.warning("未能获取到股票数据，请检查网络后刷新重试")
        st.stop()

    st.caption(f"共 {len(full_df)} 只股票，数据时间: {datetime.now().strftime('%H:%M:%S')}")

    # 筛选条件
    st.subheader("筛选条件")
    with st.expander("展开筛选", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            market = st.selectbox("市场板块", ["全部", "上海", "深圳", "北交所"])
        with c2:
            keyword = st.text_input("代码/名称搜索", placeholder="输入代码或名称关键字")
        with c3:
            price_min = st.number_input("最低价", 0.0, None, 0.0, step=0.1)
        with c4:
            price_max = st.number_input("最高价", 0.0, None, 0.0, step=0.1)

        # 行业板块筛选
        with st.spinner("加载行业分类..."):
            industry_options = get_industry_list()
        selected_industries = st.multiselect(
            "行业板块（可多选，留空=全部）",
            options=industry_options,
            default=[],
            placeholder="选择行业板块，如 半导体、银行、军工...",
        )

        c5, c6 = st.columns(2)
        with c5:
            pct_min = st.number_input("最低涨跌幅 (%)", -20.0, 20.0, -20.0, step=0.1)
        with c6:
            pct_max = st.number_input("最高涨跌幅 (%)", -20.0, 20.0, 20.0, step=0.1)

        c7, c8 = st.columns(2)
        with c7:
            vol_min = st.number_input("最低成交量 (手)", 0, None, 0, step=10000)
        with c8:
            turnover_min = st.number_input("最低成交额 (元)", 0.0, None, 0.0, step=100000.0)

    # 执行筛选
    result = screen_stocks(
        full_df,
        price_min=price_min if price_min > 0 else None,
        price_max=price_max if price_max > 0 else None,
        pct_min=pct_min if pct_min > -20 else None,
        pct_max=pct_max if pct_max < 20 else None,
        vol_min=vol_min if vol_min > 0 else None,
        turnover_min=turnover_min if turnover_min > 0 else None,
        keyword=keyword.strip(),
        market=market,
        industries=selected_industries if selected_industries else None,
    )

    st.subheader(f"筛选结果 ({len(result)} 只)")
    if result.empty:
        st.info("没有符合条件的股票，请放宽筛选条件")
    else:
        display_df = result.copy()
        # 只保留展示列，去掉内部字段
        show_cols = ["code", "name", "price", "change", "pct_change",
                     "open", "high", "low", "prev_close", "volume", "turnover",
                     "pe", "pb", "market_cap", "circulating_cap", "turnover_rate",
                     "buy", "sell", "ticktime"]
        show_cols = [c for c in show_cols if c in display_df.columns]
        display_df = display_df[show_cols]
        display_df["price"] = display_df["price"].round(2)
        display_df["pct_change"] = display_df["pct_change"].round(2)
        display_df["change"] = display_df["change"].round(2)
        display_df["volume"] = display_df["volume"].astype(int)
        display_df["turnover"] = display_df["turnover"].astype(int)
        if "pe" in display_df.columns:
            display_df["pe"] = display_df["pe"].round(1)
        if "pb" in display_df.columns:
            display_df["pb"] = display_df["pb"].round(2)
        if "market_cap" in display_df.columns:
            display_df["market_cap"] = display_df["market_cap"].fillna(0).astype(int)
        if "circulating_cap" in display_df.columns:
            display_df["circulating_cap"] = display_df["circulating_cap"].fillna(0).astype(int)
        if "turnover_rate" in display_df.columns:
            display_df["turnover_rate"] = display_df["turnover_rate"].round(2)
        display_df = display_df.rename(columns={
            "code": "代码", "name": "名称", "price": "最新价",
            "pct_change": "涨跌幅(%)", "change": "涨跌额",
            "open": "今开", "high": "最高", "low": "最低",
            "prev_close": "昨收", "volume": "成交量(手)", "turnover": "成交额(元)",
            "pe": "市盈率", "pb": "市净率",
            "market_cap": "总市值(元)", "circulating_cap": "流通市值(元)",
            "turnover_rate": "换手率(%)",
            "buy": "买入价", "sell": "卖出价",
            "ticktime": "更新时间",
        })
        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "代码": st.column_config.TextColumn(width="small"),
                "名称": st.column_config.TextColumn(width="small"),
                "涨跌幅(%)": st.column_config.NumberColumn(format="%.2f%%"),
            },
        )

        st.caption("💡 点击表头可排序，筛选条件同时生效以缩小范围")


# ---- Tab 5: 资金流向TOP50 ----
with tab5:
    st.title("资金净流入 TOP50")
    st.caption("主力资金净流入最多的50只个股（数据源: 同花顺）")

    col_btn5, col_info5 = st.columns([2, 3])
    with col_btn5:
        refresh_flow = st.button("🔄 刷新资金流向", use_container_width=True, key="refresh_flow")
    with col_info5:
        st.caption("数据每5分钟缓存一次，首次加载需等待30秒左右")

    flow_search = st.text_input("🔍 搜索代码/名称", key="search_inflow", placeholder="输入股票代码或名称，从全市场搜索...")

    with st.spinner("正在获取资金流向数据..."):
        try:
            if flow_search:
                full_data = get_fund_flow_data()
                kw = flow_search.lower()
                display_flow = full_data[
                    full_data["code"].astype(str).str.contains(kw) |
                    full_data["name"].astype(str).str.lower().str.contains(kw)
                ].copy()
            else:
                display_flow = get_top_capital_inflow(50).copy()
        except Exception as e:
            st.error(f"获取资金流向失败: {e}")
            st.stop()

    if not display_flow.empty:
        display_flow["price"] = display_flow["price"].round(2)
        display_flow["pct_change"] = display_flow["pct_change"].round(2)
        def fmt_money(val):
            if abs(val) >= 1e8:
                return f"{val/1e8:.2f}亿"
            elif abs(val) >= 1e4:
                return f"{val/1e4:.2f}万"
            return f"{val:.0f}"
        display_flow["主力净流入"] = display_flow["main_capital"].apply(fmt_money)
        def fmt_retail(val):
            if abs(val) >= 1e8:
                return f"{val/1e8:.2f}亿"
            elif abs(val) >= 1e4:
                return f"{val/1e4:.2f}万"
            return f"{val:.0f}"
        display_flow["散户资金"] = display_flow["retail_money"].apply(fmt_retail)
        display_flow = display_flow.rename(columns={
            "code": "代码", "name": "名称", "price": "最新价",
            "pct_change": "涨跌幅(%)", "main_capital": "主力净流入(元)",
            "retail_money": "散户资金(元)",
        })
        st.dataframe(
            display_flow,
            use_container_width=True,
            hide_index=True,
            column_config={
                "涨跌幅(%)": st.column_config.NumberColumn(format="%.2f%%"),
            },
        )
    else:
        st.info("暂无资金流向数据" if not flow_search else f"未找到匹配 '{flow_search}' 的股票")


# ---- Tab 6: 资金流出TOP50 ----
with tab6:
    st.title("资金净流出 TOP50")
    st.caption("主力资金净流出最多的50只个股（数据源: 同花顺）")

    col_btn6, col_info6 = st.columns([2, 3])
    with col_btn6:
        refresh_out = st.button("🔄 刷新资金流向", use_container_width=True, key="refresh_outflow")
    with col_info6:
        st.caption("数据每5分钟缓存一次，与流入数据共享缓存")

    out_search = st.text_input("🔍 搜索代码/名称", key="search_outflow", placeholder="输入股票代码或名称，从全市场搜索...")

    with st.spinner("正在获取资金流出排行..."):
        try:
            if out_search:
                full_data = get_fund_flow_data()
                kw = out_search.lower()
                display_out = full_data[
                    full_data["code"].astype(str).str.contains(kw) |
                    full_data["name"].astype(str).str.lower().str.contains(kw)
                ].copy()
            else:
                display_out = get_top_capital_outflow(50).copy()
        except Exception as e:
            st.error(f"获取资金流出排行失败: {e}")
            st.stop()

    if not display_out.empty:
        display_out["price"] = display_out["price"].round(2)
        display_out["pct_change"] = display_out["pct_change"].round(2)
        def fmt_money3(val):
            if abs(val) >= 1e8:
                return f"{val/1e8:.2f}亿"
            elif abs(val) >= 1e4:
                return f"{val/1e4:.2f}万"
            return f"{val:.0f}"
        display_out["主力净流出"] = display_out["main_capital"].apply(fmt_money3)
        def fmt_retail_out(val):
            if abs(val) >= 1e8:
                return f"{val/1e8:.2f}亿"
            elif abs(val) >= 1e4:
                return f"{val/1e4:.2f}万"
            return f"{val:.0f}"
        display_out["散户资金"] = display_out["retail_money"].apply(fmt_retail_out)
        display_out = display_out.rename(columns={
            "code": "代码", "name": "名称", "price": "最新价",
            "pct_change": "涨跌幅(%)", "main_capital": "主力净流出(元)",
            "retail_money": "散户资金(元)",
        })
        st.dataframe(
            display_out,
            use_container_width=True,
            hide_index=True,
            column_config={
                "涨跌幅(%)": st.column_config.NumberColumn(format="%.2f%%"),
            },
        )
    else:
        st.info("暂无资金流出数据" if not out_search else f"未找到匹配 '{out_search}' 的股票")


# ---- Tab 7: 成交额TOP50 ----
with tab7:
    st.title("成交额 TOP50")
    st.caption("当日成交额最多的50只个股（数据源: 新浪行情）")

    col_btn6, col_info6 = st.columns([2, 3])
    with col_btn6:
        refresh_turn = st.button("🔄 刷新行情", use_container_width=True, key="refresh_turn")
    with col_info6:
        st.caption("数据每5分钟缓存一次")

    turn_search = st.text_input("🔍 搜索代码/名称", key="search_turnover", placeholder="输入股票代码或名称，从全市场搜索...")

    with st.spinner("正在获取成交额排行..."):
        try:
            if turn_search:
                full_data = get_stock_list()
                kw = turn_search.lower()
                display_turn = full_data[
                    full_data["code"].astype(str).str.contains(kw) |
                    full_data["name"].astype(str).str.lower().str.contains(kw)
                ].copy()
            else:
                display_turn = get_top_turnover(50).copy()
        except Exception as e:
            st.error(f"获取成交额排行失败: {e}")
            st.stop()

    if not display_turn.empty:
        display_turn["price"] = display_turn["price"].round(2)
        display_turn["pct_change"] = display_turn["pct_change"].round(2)
        display_turn["turnover"] = display_turn["turnover"].astype(int)
        def fmt_money2(val):
            if abs(val) >= 1e8:
                return f"{val/1e8:.2f}亿"
            elif abs(val) >= 1e4:
                return f"{val/1e4:.0f}万"
            return f"{val:.0f}"
        display_turn["成交额显示"] = display_turn["turnover"].apply(fmt_money2)
        display_turn = display_turn.rename(columns={
            "code": "代码", "name": "名称", "price": "最新价",
            "pct_change": "涨跌幅(%)", "turnover": "成交额(元)",
        })
        st.dataframe(
            display_turn,
            use_container_width=True,
            hide_index=True,
            column_config={
                "涨跌幅(%)": st.column_config.NumberColumn(format="%.2f%%"),
            },
        )
    else:
        st.info("暂无成交额数据" if not turn_search else f"未找到匹配 '{turn_search}' 的股票")


# ---- Tab 8: 智能选股 ----
with tab8:
    st.title("智能选股")
    st.caption("多维度筛选：行情 + 资金流 + 行业，支持组合条件与自定义排序")

    col_btn8, col_info8 = st.columns([2, 3])
    with col_btn8:
        refresh_combined = st.button("🔄 刷新数据", use_container_width=True, key="refresh_smart")
    with col_info8:
        st.caption("首次加载约30秒（含资金流），之后5分钟缓存")

    with st.spinner("正在加载多维度数据..."):
        try:
            combined = get_combined_data(force_refresh=refresh_combined)
        except Exception as e:
            st.error(f"数据加载失败: {e}")
            st.stop()

    st.caption(f"共 {len(combined)} 只股票已加载")

    # ─── 筛选条件区 ───
    with st.expander("🔍 多维度筛选条件", expanded=True):
        tab_dim1, tab_dim2, tab_dim3, tab_dim4 = st.tabs([
            "📊 行情维度", "📈 估值维度", "💰 资金维度", "🏭 行业维度"
        ])

        with tab_dim1:
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                market_s = st.selectbox("市场板块", ["全部", "上海", "深圳", "北交所"], key="smart_market")
            with c2:
                price_min_s = st.number_input("最低价", 0.0, None, 0.0, step=0.1, key="smart_pmin")
            with c3:
                price_max_s = st.number_input("最高价", 0.0, None, 0.0, step=0.1, key="smart_pmax")
            with c4:
                keyword_s = st.text_input("代码/名称", placeholder="搜索", key="smart_kw")

            c5, c6, c7 = st.columns(3)
            with c5:
                pct_min_s = st.number_input("最低涨跌幅(%)", -20.0, 20.0, -20.0, step=0.1, key="smart_pct_min")
            with c6:
                pct_max_s = st.number_input("最高涨跌幅(%)", -20.0, 20.0, 20.0, step=0.1, key="smart_pct_max")
            with c7:
                vol_min_s = st.number_input("最低成交量(手)", 0, None, 0, step=10000, key="smart_vol")

        with tab_dim2:
            vc1, vc2, vc3 = st.columns(3)
            with vc1:
                pe_min_s = st.number_input(
                    "PE(TTM) ≥", 0.0, None, 0.0, step=1.0,
                    help="市盈率下限，0=不限制", key="smart_pe_min"
                )
                pe_max_s = st.number_input(
                    "PE(TTM) ≤", 0.0, None, 0.0, step=1.0,
                    help="市盈率上限，0=不限制", key="smart_pe_max"
                )
            with vc2:
                pb_min_s = st.number_input(
                    "PB ≥", 0.0, None, 0.0, step=0.1,
                    help="市净率下限，0=不限制", key="smart_pb_min"
                )
                pb_max_s = st.number_input(
                    "PB ≤", 0.0, None, 0.0, step=0.1,
                    help="市净率上限，0=不限制", key="smart_pb_max"
                )
            with vc3:
                mktcap_min_s = st.number_input(
                    "总市值≥(亿)", 0.0, None, 0.0, step=1.0,
                    help="总市值下限（亿元），0=不限制", key="smart_mktcap"
                )
                turnover_rate_min_s = st.number_input(
                    "换手率≥(%)", 0.0, None, 0.0, step=0.1,
                    help="换手率下限，0=不限制", key="smart_tr"
                )

        with tab_dim3:
            cc1, cc2, cc3 = st.columns(3)
            with cc1:
                flow_min_s = st.number_input(
                    "主力净流入≥(万)", None, None, value=None, step=100,
                    help="主力资金净流入下限（万元），留空=不限制"
                )
            with cc2:
                flow_pct_min_s = st.number_input(
                    "净流入占比≥(%)", -100.0, 100.0, -100.0, step=0.1,
                    help="净流量占比下限"
                )
            with cc3:
                flow_pct_max_s = st.number_input(
                    "净流入占比≤(%)", -100.0, 100.0, 100.0, step=0.1,
                    help="净流量占比上限"
                )

        with tab_dim4:
            industry_options = get_industry_list()
            selected_inds = st.multiselect(
                "选择行业板块（留空=全部）",
                options=industry_options,
                default=[],
                placeholder="如：半导体、银行、白酒...",
                key="smart_inds",
            )

        # 排序
        st.divider()
        sc1, sc2, sc3 = st.columns(3)
        with sc1:
            sort_options = {
                "": "默认(不排序)",
                "pct_change": "涨跌幅",
                "price": "最新价",
                "volume": "成交量",
                "turnover": "成交额",
                "main_capital": "主力净流入",
                "hot_money": "游资金额",
                "net_flow_pct": "净流入占比",
                "pe": "市盈率(PE)",
                "pb": "市净率(PB)",
                "market_cap": "总市值",
                "turnover_rate": "换手率",
            }
            sort_choice = st.selectbox("排序字段", list(sort_options.keys()),
                                       format_func=lambda x: sort_options[x], key="smart_sort")
        with sc2:
            sort_order = st.radio("排序方向", ["降序", "升序"], horizontal=True, key="smart_order")
        with sc3:
            top_n = st.number_input("取前N只", 0, 500, 200, step=50,
                                    help="0=返回全部匹配股票")

    # ─── 执行筛选 ───
    flow_min_val = flow_min_s * 10000 if flow_min_s is not None and flow_min_s > 0 else None
    mktcap_min_val = mktcap_min_s * 10000 if mktcap_min_s > 0 else None  # 亿→万元
    result = smart_screen(
        combined,
        price_min=price_min_s if price_min_s > 0 else None,
        price_max=price_max_s if price_max_s > 0 else None,
        pct_change_min=pct_min_s if pct_min_s > -20 else None,
        pct_change_max=pct_max_s if pct_max_s < 20 else None,
        volume_min=vol_min_s if vol_min_s > 0 else None,
        market=market_s,
        pe_min=pe_min_s if pe_min_s > 0 else None,
        pe_max=pe_max_s if pe_max_s > 0 else None,
        pb_min=pb_min_s if pb_min_s > 0 else None,
        pb_max=pb_max_s if pb_max_s > 0 else None,
        mktcap_min=mktcap_min_val,
        turnover_rate_min=turnover_rate_min_s if turnover_rate_min_s > 0 else None,
        main_capital_min=flow_min_val,
        net_flow_pct_min=flow_pct_min_s if flow_pct_min_s > -100 else None,
        net_flow_pct_max=flow_pct_max_s if flow_pct_max_s < 100 else None,
        industries=selected_inds if selected_inds else None,
        keyword=keyword_s.strip(),
        sort_by=sort_choice,
        ascending=(sort_order == "升序"),
        top_n=int(top_n) if top_n > 0 else None,
    )

    # ─── 结果展示 ───
    st.subheader(f"筛选结果 ({len(result)} 只)")

    if result.empty:
        st.info("没有符合条件的股票，请放宽筛选条件")
    else:
        # 格式化显示
        display = result.copy()
        cols_show = ["code", "name", "price", "pct_change",
                     "pe", "pb", "market_cap", "turnover_rate",
                     "volume", "turnover",
                     "main_capital", "hot_money", "net_flow_pct", "industry"]
        cols_show = [c for c in cols_show if c in display.columns]
        display = display[cols_show]

        display["price"] = display["price"].round(2)
        display["pct_change"] = display["pct_change"].round(2)
        if "pe" in display.columns:
            display["pe"] = display["pe"].round(1)
        if "pb" in display.columns:
            display["pb"] = display["pb"].round(2)
        if "turnover_rate" in display.columns:
            display["turnover_rate"] = display["turnover_rate"].round(2)
        if "volume" in display.columns:
            display["volume"] = display["volume"].fillna(0).astype(int)
        if "turnover" in display.columns:
            display["turnover"] = display["turnover"].fillna(0).astype(int)

        def _fmt_flow(val):
            if val == 0:
                return "0"
            if abs(val) >= 1e8:
                return f"{val/1e8:+.2f}亿"
            elif abs(val) >= 1e4:
                return f"{val/1e4:+.0f}万"
            return f"{val:+.0f}"

        if "main_capital" in display.columns:
            display["主力净流入"] = display["main_capital"].apply(_fmt_flow)
        if "hot_money" in display.columns:
            display["游资"] = display["hot_money"].apply(_fmt_flow)
        if "net_flow_pct" in display.columns:
            display["净流入占比"] = display["net_flow_pct"].apply(lambda x: f"{x:+.2f}%" if x != 0 else "0%")
        if "market_cap" in display.columns:
            display["总市值(亿)"] = display["market_cap"].apply(
                lambda x: f"{x/10000:.1f}" if pd.notna(x) and x > 0 else "-"
            )

        display = display.rename(columns={
            "code": "代码", "name": "名称", "price": "最新价",
            "pct_change": "涨跌幅(%)", "pe": "PE", "pb": "PB",
            "turnover_rate": "换手率(%)", "volume": "成交量(手)",
            "turnover": "成交额(元)", "industry": "行业",
        })

        # 去掉原始数值列避免重复
        drop_cols = ["main_capital", "hot_money", "net_flow_pct", "market_cap"]
        display = display[[c for c in display.columns if c not in drop_cols]]

        st.dataframe(
            display,
            use_container_width=True,
            hide_index=True,
            column_config={
                "涨跌幅(%)": st.column_config.NumberColumn(format="%.2f%%"),
                "代码": st.column_config.TextColumn(width="small"),
                "名称": st.column_config.TextColumn(width="small"),
            },
        )

        # 快速导出
        csv_data = result.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "📥 导出 CSV",
            data=csv_data,
            file_name=f"smart_screen_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
        )


# ---- Tab 9: 龙虎榜 ----
with tab9:
    st.title("🐉 龙虎榜")
    st.caption("当日上榜个股，含席位买卖明细、上榜天数、机构动向（数据源: 新浪财经）")

    col_lhb1, col_lhb2, col_lhb3 = st.columns([2, 2, 2])
    with col_lhb1:
        lhb_date = st.date_input("上榜日期", value=datetime.now())
    with col_lhb2:
        st.write("")
        st.write("")
        refresh_lhb = st.button("🔄 刷新数据", use_container_width=True, key="refresh_lhb")
    with col_lhb3:
        st.write("")
        st.caption("数据每5分钟缓存一次")

    lhb_date_str = lhb_date.strftime("%Y%m%d")
    lhb_date_dash = lhb_date.strftime("%Y-%m-%d")

    with st.spinner("正在获取龙虎榜数据..."):
        try:
            lhb_df = get_lhb_daily(date=lhb_date_str, force_refresh=refresh_lhb)
        except Exception as e:
            st.error(f"获取龙虎榜数据失败: {e}")
            st.stop()

    if lhb_df.empty:
        st.warning(f"{lhb_date_str} 暂无龙虎榜上榜数据（可能非交易日或数据未更新）")
        st.stop()

    st.caption(f"共 {len(lhb_df)} 只上榜股票")

    search_lhb = st.text_input("🔍 搜索代码/名称", key="search_lhb", placeholder="输入股票代码或名称过滤...")

    df_display = lhb_df.copy()
    if search_lhb:
        kw = search_lhb.lower()
        df_display = df_display[
            df_display["code"].astype(str).str.contains(kw) |
            df_display["name"].astype(str).str.lower().str.contains(kw)
        ]
        if df_display.empty:
            st.info(f"未找到匹配 '{search_lhb}' 的上榜股票")
            st.stop()

    # 格式化主表格
    tbl = df_display.copy()
    tbl["close"] = tbl["close"].round(2)
    tbl["pct_change"] = tbl["pct_change"].round(2)
    tbl["turnover"] = tbl["turnover"].fillna(0).astype(int)

    def _to_yi(val):
        """万元 → 亿元"""
        if abs(val) >= 1e4:
            return f"{val/1e4:.2f}亿"
        return f"{val/1e4:.4f}亿"

    tbl["成交额"] = tbl["turnover"].apply(_to_yi)
    tbl["净买入"] = tbl["net_buy"].apply(lambda x: f"{x/1e4:+.2f}亿" if x else "0")
    tbl["机构买入"] = tbl["inst_buy"].apply(_to_yi)
    tbl["机构卖出"] = tbl["inst_sell"].apply(_to_yi)
    tbl["5日累计买"] = tbl["accum_buy"].apply(_to_yi)
    tbl["5日累计卖"] = tbl["accum_sell"].apply(_to_yi)

    tbl_display = tbl.rename(columns={
        "code": "代码", "name": "名称", "close": "收盘价",
        "pct_change": "涨跌幅(%)", "onboard_days": "上榜天数",
        "buy_seat_count": "买入席位", "sell_seat_count": "卖出席位",
        "reason": "上榜原因",
    })

    show_cols = ["代码", "名称", "收盘价", "涨跌幅(%)", "成交额", "净买入",
                 "上榜天数", "机构买入", "机构卖出",
                 "5日累计买", "5日累计卖",
                 "买入席位", "卖出席位", "上榜原因"]
    show_cols = [c for c in show_cols if c in tbl_display.columns]

    st.dataframe(
        tbl_display[show_cols],
        use_container_width=True,
        hide_index=True,
        column_config={
            "涨跌幅(%)": st.column_config.NumberColumn(format="%.2f%%"),
            "代码": st.column_config.TextColumn(width="small"),
            "名称": st.column_config.TextColumn(width="small"),
        },
    )

    # ─── 席位明细（可展开） ───
    st.divider()
    st.subheader("🔍 查看个股席位明细")
    lhb_codes = list(df_display["code"].unique())
    lhb_code_options = [f"{c} — {df_display[df_display['code']==c]['name'].values[0]}" for c in lhb_codes]
    selected_lhb = st.selectbox(
        "选择上榜股票",
        options=lhb_codes,
        format_func=lambda c: f"{c} — {df_display[df_display['code']==c]['name'].values[0]}",
        key="lhb_select",
    )

    if selected_lhb:
        with st.spinner(f"获取 {selected_lhb} 席位明细..."):
            try:
                seat_df = get_lhb_seat_detail(selected_lhb, lhb_date_dash,
                                              force_refresh=refresh_lhb)
            except Exception as e:
                st.error(f"获取席位明细失败: {e}")
                seat_df = pd.DataFrame()

        if seat_df.empty:
            st.info(f"{selected_lhb} 席位明细暂无数据")
        else:
            buy_seats = seat_df[seat_df["side"] == "买入"].sort_values("buy_amount", ascending=False)
            sell_seats = seat_df[seat_df["side"] == "卖出"].sort_values("sell_amount", ascending=False)

            c_left, c_right = st.columns(2)
            with c_left:
                st.markdown("### 🟢 买入前5席位")
                if buy_seats.empty:
                    st.caption("无买入数据")
                else:
                    buy_show = buy_seats[["seat_name", "buy_amount", "sell_amount", "net_amount"]].copy()
                    buy_show.columns = ["营业部", "买入(万)", "卖出(万)", "净额(万)"]
                    for c in ["买入(万)", "卖出(万)", "净额(万)"]:
                        buy_show[c] = buy_show[c].round(1)
                    st.dataframe(buy_show, use_container_width=True, hide_index=True)

            with c_right:
                st.markdown("### 🔴 卖出前5席位")
                if sell_seats.empty:
                    st.caption("无卖出数据")
                else:
                    sell_show = sell_seats[["seat_name", "buy_amount", "sell_amount", "net_amount"]].copy()
                    sell_show.columns = ["营业部", "买入(万)", "卖出(万)", "净额(万)"]
                    for c in ["买入(万)", "卖出(万)", "净额(万)"]:
                        sell_show[c] = sell_show[c].round(1)
                    st.dataframe(sell_show, use_container_width=True, hide_index=True)


# ---- Tab 10: 值博率 ----
with tab10:
    from data.screener import get_combined_data, _compute_upside_score

    st.title("🔥 上涨值博率")
    st.caption("多因子评分模型：综合资金流、涨跌幅、换手率、估值，筛选高上涨潜力的股票")

    col_v1, col_v2, col_v3 = st.columns([2, 2, 2])
    with col_v1:
        v_market = st.selectbox("市场板块", ["全部", "上海", "深圳", "北交所"], key="v_market")
    with col_v2:
        v_topn = st.selectbox("显示数量", [30, 50, 100, 200], index=1, key="v_topn")
    with col_v3:
        v_refresh = st.button("🔄 刷新数据", use_container_width=True, key="v_refresh")

    with st.spinner("正在加载全市场数据并计算值博率..."):
        try:
            v_data = get_combined_data(force_refresh=v_refresh)
        except Exception as e:
            st.error(f"数据加载失败: {e}")
            st.stop()

    # 市场筛选
    if v_market == "上海":
        v_data = v_data[v_data["code"].str.startswith("6")]
    elif v_market == "深圳":
        v_data = v_data[v_data["code"].str.startswith(("0", "3"))]
    elif v_market == "北交所":
        v_data = v_data[v_data["code"].str.startswith(("8", "4", "9"))]

    # 剔除ST、退市等
    if "name" in v_data.columns:
        v_data = v_data[~v_data["name"].astype(str).str.contains("ST|退")]

    # 计算值博率
    v_data["upside_score"] = _compute_upside_score(v_data)
    v_data = v_data.sort_values("upside_score", ascending=False).head(int(v_topn))

    st.subheader(f"值博率 TOP {len(v_data)}")

    # 格式化显示
    v_display = v_data.copy()
    show_cols = ["code", "name", "price", "pct_change", "upside_score",
                 "main_capital", "net_flow_pct", "turnover_rate", "pe", "industry"]
    show_cols = [c for c in show_cols if c in v_display.columns]
    v_display = v_display[show_cols]

    v_display["price"] = v_display["price"].round(2)
    v_display["pct_change"] = v_display["pct_change"].round(2)
    v_display["upside_score"] = v_display["upside_score"].round(0).astype(int)
    if "turnover_rate" in v_display.columns:
        v_display["turnover_rate"] = v_display["turnover_rate"].round(2)
    if "pe" in v_display.columns:
        v_display["pe"] = v_display["pe"].round(1)

    def _v_fmt_flow(val):
        if val == 0:
            return "0"
        if abs(val) >= 1e8:
            return f"{val/1e8:+.2f}亿"
        elif abs(val) >= 1e4:
            return f"{val/1e4:+.0f}万"
        return f"{val:+.0f}"

    if "main_capital" in v_display.columns:
        v_display["主力净流入"] = v_display["main_capital"].apply(_v_fmt_flow)
    if "net_flow_pct" in v_display.columns:
        v_display["净流入占比"] = v_display["net_flow_pct"].apply(lambda x: f"{x:+.2f}%" if x != 0 else "0%")

    v_display = v_display.rename(columns={
        "code": "代码", "name": "名称", "price": "最新价",
        "pct_change": "涨跌幅(%)", "upside_score": "值博率",
        "turnover_rate": "换手率(%)", "pe": "PE",
        "industry": "行业",
    })

    drop_cols = ["main_capital", "net_flow_pct"]
    v_display = v_display[[c for c in v_display.columns if c not in drop_cols]]

    # 值博率颜色渐变
    st.dataframe(
        v_display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "涨跌幅(%)": st.column_config.NumberColumn(format="%.2f%%"),
            "值博率": st.column_config.ProgressColumn(
                format="%d", min_value=0, max_value=100,
            ),
            "代码": st.column_config.TextColumn(width="small"),
            "名称": st.column_config.TextColumn(width="small"),
        },
    )

    st.caption("💡 值博率综合评分：资金流入强度(35%) + 净流入占比(25%) + 涨幅合理性(20%) + 换手活跃度(15%) + 估值合理(5%)")
