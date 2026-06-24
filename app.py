"""
WinnerK股票量化系统 — Streamlit 可视化界面
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

st.set_page_config(page_title="WinnerK股票量化系统", page_icon="📈", layout="wide")


def _startup_tdx_sync():
    """
    启动时自动从通达信本地 .day 文件增量同步到 DuckDB。
    每个浏览器会话仅执行一次，增量模式（每只股票只读末尾 160 字节），
    5000+ 只股票约 1-3 秒完成。
    """
    if "_tdx_startup_sync_done" in st.session_state:
        return

    # 先标记完成，防止异常时重复触发
    st.session_state._tdx_startup_sync_done = True

    from config import get_tdx_vipdoc_path
    from data.sync import sync_from_tdx
    from data.database import get_db_stats

    vipdoc_path = get_tdx_vipdoc_path()

    if vipdoc_path is None:
        st.session_state._tdx_startup_result = {
            "status": "not_found",
            "message": "未检测到券商客户端 (通达信) 数据目录"
        }
        return

    try:
        stats_before = get_db_stats()
        result = sync_from_tdx(str(vipdoc_path), full_import=False)

        if result.get("errors") and any(
            "未找到券商客户端目录" in str(e) for e in result["errors"]
        ):
            st.session_state._tdx_startup_result = {
                "status": "no_path",
                "message": "vipdoc 目录为空或不存在 .day 文件"
            }
            return

        stats_after = get_db_stats()
        new_stocks = result.get("imported", 0)
        skipped = result.get("skipped", 0)
        errors = result.get("errors", [])

        st.session_state._tdx_startup_result = {
            "status": "ok",
            "new_stocks": new_stocks,
            "skipped": skipped,
            "errors": errors,
            "vipdoc_path": str(vipdoc_path),
            "stock_count": stats_after.get("stock_count", 0),
            "max_date": stats_after.get("max_date", ""),
        }
    except Exception as e:
        st.session_state._tdx_startup_result = {
            "status": "error",
            "message": str(e)
        }


def _startup_fund_flow_sync():
    """
    启动时自动抓取当日全市场资金流快照（同花顺源）。
    每个浏览器会话仅执行一次，约 8 秒（104页分页抓取）。
    """
    if "_ff_startup_sync_done" in st.session_state:
        return
    st.session_state._ff_startup_sync_done = True

    from data.fund_flow import sync_fund_flow_snapshot
    try:
        result = sync_fund_flow_snapshot()
        st.session_state._ff_startup_result = result
    except Exception as e:
        st.session_state._ff_startup_result = {"status": "error", "message": str(e)}


_startup_tdx_sync()
_startup_fund_flow_sync()


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

st.sidebar.title("📈 WinnerK股票量化系统")

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

    benchmark = st.sidebar.selectbox("对比基准", ["沪深300", "中证500"], index=0)
    st.session_state["benchmark"] = "000300" if benchmark == "沪深300" else "000905"

    if st.sidebar.button("🚀 运行回测", type="primary", use_container_width=True):
        st.session_state["run_backtest"] = True

    st.sidebar.markdown("---")
    # 数据源状态：TDX 本地 + 资金流快照
    sync_result = st.session_state.get("_tdx_startup_result", {})
    if sync_result.get("status") == "ok":
        st.sidebar.success(
            f"📡 券商数据已同步\n"
            f"更新: {sync_result['new_stocks']} 只, 跳过: {sync_result['skipped']} 只\n"
            f"最新: {sync_result.get('max_date', 'N/A')}"
        )
    elif sync_result.get("status") in ("not_found", "no_path"):
        st.sidebar.caption("📡 券商本地: 未检测到 → 在线获取")
    elif sync_result.get("status") == "error":
        st.sidebar.warning(f"⚠️ 券商同步异常: {sync_result.get('message', '')}")
    else:
        st.sidebar.caption("数据源: AKShare (新浪/东方财富)")

    ff_result = st.session_state.get("_ff_startup_result", {})
    if ff_result.get("status") == "ok":
        st.sidebar.caption(f"💰 资金流快照: {ff_result['date']} ({ff_result['count']}只)")
    elif ff_result.get("status") == "error":
        st.sidebar.caption(f"💰 资金流: {ff_result.get('message', '未同步')}")

    st.sidebar.caption("引擎: backtrader")

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
    # 数据源状态
    sync_result = st.session_state.get("_tdx_startup_result", {})
    if sync_result.get("status") == "ok":
        st.sidebar.success(f"📡 券商已同步 | 最新: {sync_result.get('max_date', 'N/A')}")
    elif sync_result.get("status") in ("not_found", "no_path"):
        st.sidebar.caption("📡 券商本地: 未检测到 → 在线获取")
    elif sync_result.get("status") == "error":
        st.sidebar.warning(f"⚠️ 同步异常: {sync_result.get('message', '')}")
    else:
        st.sidebar.caption("数据源: AKShare (新浪/东方财富)")

    ff_result = st.session_state.get("_ff_startup_result", {})
    if ff_result.get("status") == "ok":
        st.sidebar.caption(f"💰 资金流快照: {ff_result['date']} ({ff_result['count']}只)")

    st.sidebar.caption("引擎: backtrader")

# ── 定时任务 & 推送（两侧边栏通用） ──
st.sidebar.markdown("---")
st.sidebar.subheader("🔔 自动日报")

from scheduler import get_config, save_config, run_now, start_scheduler

sched_cfg = get_config()

# 开关
if "sched_enabled" not in st.session_state:
    st.session_state.sched_enabled = sched_cfg.get("enabled", False)
    st.session_state.sched_started = False

enabled = st.sidebar.toggle(
    "启用工作日自动选股",
    value=st.session_state.sched_enabled,
    key="sched_toggle"
)
if enabled != st.session_state.sched_enabled:
    st.session_state.sched_enabled = enabled
    sched_cfg["enabled"] = enabled
    save_config(sched_cfg)
    if enabled and not st.session_state.sched_started:
        start_scheduler()
        st.session_state.sched_started = True

with st.sidebar.expander("⚙️ 推送设置", expanded=False):
    wechat_url = st.text_input(
        "企业微信 Webhook",
        value=sched_cfg.get("wechat_webhook_url", ""),
        type="password",
        placeholder="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...",
        key="sched_wechat",
    )
    dingtalk_url = st.text_input(
        "钉钉 Webhook",
        value=sched_cfg.get("dingtalk_webhook_url", ""),
        type="password",
        placeholder="https://oapi.dingtalk.com/robot/send?access_token=...",
        key="sched_dingtalk",
    )
    run_time = st.text_input(
        "执行时间 (HH:MM)",
        value=sched_cfg.get("run_time", "09:00"),
        key="sched_time",
    )
    desktop = st.checkbox("桌面通知", value=sched_cfg.get("desktop_notify", True), key="sched_desktop")

    if st.button("💾 保存推送设置", key="sched_save"):
        sched_cfg["wechat_webhook_url"] = wechat_url
        sched_cfg["dingtalk_webhook_url"] = dingtalk_url
        sched_cfg["run_time"] = run_time
        sched_cfg["desktop_notify"] = desktop
        save_config(sched_cfg)
        st.success("已保存")

    if st.button("▶️ 立即运行一次", key="sched_run_now"):
        with st.spinner("执行中..."):
            report = run_now()
        st.success("日报已生成")
        with st.expander("查看报告"):
            st.markdown(report)

last_run = sched_cfg.get("last_run", "")
if last_run:
    st.sidebar.caption(f"上次执行: {last_run[:16]}")

# =========================== 主区域 Tab 路由 ===========================

tab_wf, tab_ai, tab1, tab2, tab3, tab_perf, tab_ml, tab4, tab_sc, tab_lhb, tab_wl, tab5, tab6, tab7, tab8, tab9, tab10 = st.tabs([
    "📋 选股工作流",
    "🤖 AI智能分析",
    "📊 单策略回测", "📋 策略对比", "🔧 参数优化",
    "📈 绩效分析",
    "🧠 ML因子研究",
    "💰 资金排名",
    "🧠 智能选股", "🐉 龙虎榜",
    "⭐ 自选股",
    "🧺 组合回测", "🌏 北向&融资", "📊 财务分析", "🏭 市场全景",
    "🗄️ 数据中心", "📊 高级分析",
])

from tabs.tab_workflow import render as render_wf
from tabs.tab_ai import render as render_ai
from tabs.tab1_backtest import render as render_tab1
from tabs.tab2_compare import render as render_tab2
from tabs.tab3_optimize import render as render_tab3
from tabs.tab_performance import render as render_perf
from tabs.tab_ml import render as render_ml
from tabs.tab5_market_rank import render as render_tab4
from tabs.tab_screener import render as render_sc
from tabs.tab9_lhb import render as render_lhb
from tabs.tab_watchlist import render as render_wl
from tabs.tab11_portfolio import render as render_tab8
from tabs.tab12_northbound import render as render_tab9
from tabs.tab13_fundamental import render as render_tab10
from tabs.tab14_industry import render as render_tab11
from tabs.tab15_database import render as render_tab12
from tabs.tab16_advanced import render as render_tab13

with tab_wf:
    render_wf()

with tab_ai:
    render_ai()

with tab1:
    render_tab1()

with tab2:
    render_tab2()

with tab3:
    render_tab3()

with tab_perf:
    render_perf()

with tab_ml:
    render_ml()

with tab4:
    render_tab4()

with tab_sc:
    render_sc()

with tab_lhb:
    render_lhb()

with tab_wl:
    render_wl()

with tab5:
    render_tab8()

with tab6:
    render_tab9()

with tab7:
    render_tab10()

with tab8:
    render_tab11()

with tab9:
    render_tab12()

with tab10:
    render_tab13()
