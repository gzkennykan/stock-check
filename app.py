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

from strategies import MACrossStrategy, MACDStrategy, RSIStrategy
from strategies import BollingerStrategy, TripleMAStrategy, KDJStrategy
from strategies import DonchianStrategy, ATRStrategy

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

# =========================== 侧边栏 ===========================

st.sidebar.title("📈 股票量化回测系统")

# ── 工作模式切换 ──
if "work_mode" not in st.session_state:
    st.session_state.work_mode = "回测"
if "symbol" not in st.session_state:
    st.session_state.symbol = "600036"

mode_idx = 0 if st.session_state.work_mode == "回测" else 1
work_mode_label = st.sidebar.radio(
    "工作模式",
    ["📊 回测工作台", "📈 市场分析"],
    index=mode_idx,
    key="work_mode_radio",
)
st.session_state.work_mode = "回测" if "回测" in work_mode_label else "市场分析"

if st.session_state.work_mode == "回测":
    # ═══════════════ 回测工作台侧边栏 ═══════════════

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

    strategy_name = st.sidebar.selectbox("交易策略", list(STRATEGY_MAP.keys()))
    strategy_cls = STRATEGY_MAP[strategy_name]
    st.session_state["strategy_name"] = strategy_name
    st.session_state["strategy_cls"] = strategy_cls

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

    st.sidebar.subheader("风控参数")
    params["stop_loss"] = st.sidebar.number_input("止损比例 (%)", 0, 20, 5, step=1) / 100
    params["take_profit"] = st.sidebar.number_input("止盈比例 (%)", 0, 50, 15, step=1) / 100
    params["position_pct"] = st.sidebar.number_input("仓位比例 (%)", 10, 100, 95, step=1) / 100
    st.session_state["params"] = params

    st.sidebar.subheader("回测日期")
    start_date = st.sidebar.date_input("起始日期", value=datetime(2024, 1, 1))
    end_date = st.sidebar.date_input("结束日期", value=datetime(2025, 5, 8))
    st.session_state["start_date"] = start_date
    st.session_state["end_date"] = end_date

    initial_cash = st.sidebar.number_input("初始资金 (元)", value=1000000, step=100000)
    st.session_state["initial_cash"] = initial_cash

    if st.sidebar.button("🚀 运行回测", type="primary", use_container_width=True):
        st.session_state["run_backtest"] = True

    st.sidebar.markdown("---")
    st.sidebar.caption("数据源: AKShare (新浪/东方财富)")
    st.sidebar.caption("引擎: backtrader + optuna")

else:
    # ═══════════════ 市场分析侧边栏（极简） ═══════════════
    st.sidebar.subheader("快捷选股")
    cols = st.sidebar.columns(5)
    for i, (name, code) in enumerate(HOT_STOCKS.items()):
        with cols[i]:
            if st.button(name, key=f"hot_mkt_{code}", use_container_width=True):
                st.session_state["symbol"] = code
                st.session_state.work_mode = "回测"

    st.sidebar.markdown("---")
    st.sidebar.caption("当前模式：市场分析")
    st.sidebar.caption("切换至「回测工作台」可运行策略回测")
    st.sidebar.markdown("---")
    st.sidebar.caption("数据源: AKShare (新浪/东方财富)")
    st.sidebar.caption("引擎: backtrader + optuna")

# =========================== 主区域 Tab 路由 ===========================

tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9, tab10 = st.tabs([
    "📊 单策略回测", "📋 策略对比", "🔧 参数优化", "🔍 选股池",
    "💰 资金流入TOP50", "💸 资金流出TOP50", "📈 成交额TOP50",
    "🧠 智能选股", "🐉 龙虎榜", "🔥 值博率",
])

from tabs.tab1_backtest import render as render_tab1
from tabs.tab2_compare import render as render_tab2
from tabs.tab3_optimize import render as render_tab3
from tabs.tab4_screener import render as render_tab4
from tabs.tab5_inflow import render as render_tab5
from tabs.tab6_outflow import render as render_tab6
from tabs.tab7_turnover import render as render_tab7
from tabs.tab8_smart import render as render_tab8
from tabs.tab9_lhb import render as render_tab9
from tabs.tab10_upside import render as render_tab10

with tab1:
    render_tab1()

with tab2:
    render_tab2()

with tab3:
    render_tab3()

with tab4:
    render_tab4()

with tab5:
    render_tab5()

with tab6:
    render_tab6()

with tab7:
    render_tab7()

with tab8:
    render_tab8()

with tab9:
    render_tab9()

with tab10:
    render_tab10()
