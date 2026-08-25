"""
ui/sidebar.py — 全局侧边栏控制区。

三区分流：
  ① 导航区（st.navigation 自带）
  ② 全局控制区：工作模式 + 全局搜索 + 快捷选股 + 数据状态
  ③ 页内上下文：回测参数/风控/日期 收进一个折叠的「回测参数」expander，
     不挤占导航空间，但仍在每次重跑时求值以保持共享状态新鲜。
"""
import streamlit as st
import pandas as pd
from datetime import datetime

from .theme import UP, DOWN, MUTED


def _retry_startup_sync() -> None:
    """清除同步标记并重跑，回到顶部后再触发 _startup_tdx_sync。"""
    st.session_state.pop("_tdx_startup_sync_done", None)
    st.rerun()


def _data_status() -> None:
    """数据源状态 + 资金流快照，收敛成一行；错误/锁定时给出友好提示 + 重试按钮。"""
    sync = st.session_state.get("_tdx_startup_result", {})
    st_s = sync.get("status")
    if st_s == "ok":
        st.sidebar.caption(
            f"📡 券商已同步 {sync.get('new_stocks', 0)} 只 · 最新 {sync.get('max_date', 'N/A')}")
    elif st_s in ("not_found", "no_path"):
        st.sidebar.caption("📡 券商本地未检测到 → 在线获取")
    elif st_s == "locked":
        with st.sidebar:
            st.caption("📡 数据库暂被占用")
            if st.button("🔄 重试同步", key="sync_retry_locked", width='stretch'):
                _retry_startup_sync()
    elif st_s == "error":
        with st.sidebar:
            st.warning("⚠️ 券商同步失败")
            if st.button("🔄 重试同步", key="sync_retry", width='stretch'):
                _retry_startup_sync()
    else:
        st.sidebar.caption("数据源: AKShare (新浪/东方财富)")

    ff = st.session_state.get("_ff_startup_result", {})
    if ff.get("status") == "ok":
        st.sidebar.caption(f"💰 资金流快照 {ff['date']} · {ff['count']}只")
    elif ff.get("status") == "error":
        st.sidebar.caption(f"💰 资金流 {ff.get('message', '未同步')[:60]}")

    st.sidebar.caption("引擎: backtrader")


def _record_recent(code: str) -> None:
    """把最近看过的股票写入 session_state.recent（去重，最多 8 只）。"""
    st.session_state.setdefault("recent", [])
    lst = [c for c in st.session_state.recent if c != code]
    lst.insert(0, code)
    st.session_state.recent = lst[:8]


def render_title() -> None:
    """程序名标题，置于侧边栏导航之上。"""
    st.sidebar.title("📈 WinnerK股票查询系统")
    st.sidebar.markdown("---")


def render_page_nav(pages: dict) -> None:
    """自定义分组的侧边栏导航（配合 st.navigation(position='hidden')）。

    pages: 与 st.navigation 相同的 {分组: [st.Page, ...]} 结构。
    """
    for group, page_list in pages.items():
        st.sidebar.markdown(f"**{group}**")
        for page in page_list:
            st.sidebar.page_link(page, use_container_width=True)


def render_global_controls(hot_stocks: dict) -> None:
    """全局控制区：工作模式 + 全局搜索 + 快捷选股 + 最近访问 + 数据状态。"""
    # ── 工作模式 ──
    st.session_state.setdefault("work_mode", "回测")
    st.session_state.setdefault("symbol", "600036")
    mode_idx = 0 if st.session_state.work_mode == "回测" else 1
    label = st.sidebar.radio(
        "工作模式", ["📊 回测工作台", "📈 市场分析"],
        index=mode_idx, key="work_mode_radio")
    st.session_state.work_mode = "回测" if "回测" in label else "市场分析"

    # ── 全局搜索（代码/名称，模糊匹配） ──
    st.sidebar.subheader("🔎 全局搜索")
    kw = st.sidebar.text_input(
        "股票代码/名称", value="", key="global_search_kw",
        placeholder="如 600519 / 贵州茅台", label_visibility="collapsed")
    if kw:
        from data.database import search_stocks
        hits = search_stocks(kw, limit=6)
        for h in hits:
            if st.sidebar.button(f"{h['name']} {h['code']}",
                                 key=f"gs_{h['code']}", width='stretch'):
                st.session_state["symbol"] = h["code"]
                _record_recent(h["code"])
                st.rerun()
        if not hits:
            st.sidebar.caption("未匹配到股票")

    # ── 快捷选股 ──
    st.sidebar.subheader("⭐ 快捷选股")
    cols = st.sidebar.columns(5)
    for i, (name, code) in enumerate(hot_stocks.items()):
        with cols[i]:
            if st.button(name, key=f"hot_{code}", width='stretch'):
                st.session_state["symbol"] = code
                _record_recent(code)

    # ── 最近访问 ──
    recent = st.session_state.get("recent", [])
    recent = [c for c in recent if not c.startswith("hot")][:8]
    if recent:
        name_map = {}
        try:
            from data.database import get_stock_name_map
            name_map = get_stock_name_map()
        except Exception:
            pass
        st.sidebar.subheader("🕘 最近访问")
        rcols = st.sidebar.columns(len(recent))
        for i, c in enumerate(recent):
            lbl = name_map.get(c, c)
            with rcols[i]:
                if st.button(lbl, key=f"recent_{c}", width='stretch'):
                    st.session_state["symbol"] = c

    st.sidebar.markdown("---")
    _data_status()


def render_backtest_params(strategy_map: dict) -> None:
    """
    折叠的回测参数区：策略 + 策略参数 + 风控 + 回测日期。
    内容每次重跑都会求值（expander 仅视觉折叠），保证 backtest 各 tab 的
    session_state（params/start_date/end_date...）始终新鲜。
    """
    with st.sidebar.expander("⚙️ 回测参数", expanded=False):
        strategy_name = st.selectbox("交易策略", list(strategy_map.keys()))
        strategy_cls = strategy_map[strategy_name]
        st.session_state["strategy_name"] = strategy_name
        st.session_state["strategy_cls"] = strategy_cls

        st.subheader("策略参数")
        params = {}
        if strategy_name == "双均线 (MA Cross)":
            params["fast_period"] = st.number_input("快线周期", 2, 30, 5, step=1)
            params["slow_period"] = st.number_input("慢线周期", 10, 60, 20, step=1)
        elif strategy_name == "MACD":
            params["fast_period"] = st.number_input("快线", 6, 20, 12, step=1)
            params["slow_period"] = st.number_input("慢线", 20, 40, 26, step=1)
            params["signal_period"] = st.number_input("信号线", 5, 15, 9, step=1)
        elif strategy_name == "RSI 超买超卖":
            params["rsi_period"] = st.number_input("RSI 周期", 5, 30, 14, step=1)
            params["oversold"] = st.number_input("超卖阈值", 15, 40, 30, step=1)
            params["overbought"] = st.number_input("超买阈值", 60, 90, 70, step=1)
        elif strategy_name == "布林带 (Bollinger)":
            params["period"] = st.number_input("布林带周期", 5, 50, 20, step=1)
            params["devfactor"] = st.number_input("标准差倍数", 1.0, 4.0, 2.0, step=0.5)
        elif strategy_name == "三均线 (Triple MA)":
            params["fast_period"] = st.number_input("快线周期", 2, 15, 5, step=1)
            params["mid_period"] = st.number_input("中线周期", 10, 30, 20, step=1)
            params["slow_period"] = st.number_input("慢线周期", 30, 90, 60, step=1)
        elif strategy_name == "KDJ":
            params["period"] = st.number_input("KDJ周期", 5, 20, 9, step=1)
            params["period_dfast"] = st.number_input("K值平滑", 2, 5, 3, step=1)
            params["upper"] = st.number_input("超买区", 60, 90, 80, step=1)
            params["lower"] = st.number_input("超卖区", 10, 40, 20, step=1)
        elif strategy_name == "唐奇安通道 (Donchian)":
            params["period"] = st.number_input("通道周期", 10, 60, 20, step=1)
        elif strategy_name == "ATR动态跟踪":
            params["fast_period"] = st.number_input("快线周期", 5, 20, 10, step=1)
            params["slow_period"] = st.number_input("慢线周期", 20, 60, 30, step=1)
            params["atr_period"] = st.number_input("ATR周期", 7, 21, 14, step=1)
            params["atr_mult"] = st.number_input("ATR倍数", 1.0, 6.0, 3.0, step=0.5)

        st.subheader("风控参数")
        params["stop_loss"] = st.number_input("止损比例 (%)", 0, 20, 5, step=1) / 100
        params["take_profit"] = st.number_input("止盈比例 (%)", 0, 50, 15, step=1) / 100
        params["position_pct"] = st.number_input("仓位比例 (%)", 10, 100, 95, step=1) / 100
        st.session_state["market_timing"] = st.toggle(
            "启用大盘择时（牛熊自动调仓）",
            value=st.session_state.get("market_timing", False),
            help="基于沪深300均线趋势，牛市满仓/震荡60%/熊市40%，高波动再减仓")
        st.session_state["params"] = params

        st.subheader("回测日期")
        start_date = st.date_input("起始日期", value=datetime(2024, 1, 1), key="bt_start")
        end_date = st.date_input("结束日期", value=datetime(2025, 5, 8), key="bt_end")
        st.session_state["start_date"] = start_date
        st.session_state["end_date"] = end_date

        initial_cash = st.number_input("初始资金 (元)", value=1000000, step=100000)
        st.session_state["initial_cash"] = initial_cash

        benchmark = st.selectbox("对比基准", ["沪深300", "中证500"], index=0)
        st.session_state["benchmark"] = "000300" if benchmark == "沪深300" else "000905"

        if st.button("🚀 运行回测", type="primary", width='stretch'):
            st.session_state["run_backtest"] = True


def render_settings() -> None:
    """🔔 自动日报 + 推送设置（折叠，两侧边栏通用）。"""
    from scheduler import get_config, save_config, run_now, start_scheduler

    sched_cfg = get_config()
    st.session_state.setdefault("sched_enabled", sched_cfg.get("enabled", False))
    st.session_state.setdefault("sched_started", False)

    with st.sidebar.expander("🔔 自动日报 & 推送", expanded=False):
        enabled = st.toggle("启用工作日自动选股", value=st.session_state.sched_enabled,
                            key="sched_toggle")
        if enabled != st.session_state.sched_enabled:
            st.session_state.sched_enabled = enabled
            sched_cfg["enabled"] = enabled
            save_config(sched_cfg)
            if enabled and not st.session_state.sched_started:
                start_scheduler()
                st.session_state.sched_started = True

        wechat_url = st.text_input(
            "企业微信 Webhook", value=sched_cfg.get("wechat_webhook_url", ""),
            type="password",
            placeholder="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...",
            key="sched_wechat")
        dingtalk_url = st.text_input(
            "钉钉 Webhook", value=sched_cfg.get("dingtalk_webhook_url", ""),
            type="password",
            placeholder="https://oapi.dingtalk.com/robot/send?access_token=...",
            key="sched_dingtalk")
        run_time = st.text_input("执行时间 (HH:MM)", value=sched_cfg.get("run_time", "09:00"),
                                 key="sched_time")
        desktop = st.checkbox("桌面通知", value=sched_cfg.get("desktop_notify", True),
                              key="sched_desktop")

        if st.button("💾 保存推送设置", key="sched_save"):
            sched_cfg.update({"wechat_webhook_url": wechat_url, "dingtalk_webhook_url": dingtalk_url,
                              "run_time": run_time, "desktop_notify": desktop})
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
