"""Tab 1: 单策略回测"""
import streamlit as st
from datetime import datetime
from backtest_utils import run_single_backtest, display_metric_cards, get_trade_list
from visualization.plotly_charts import plot_equity_drawdown, plot_kline


def _store_backtest_meta(symbol, strategy_name, params, start_date, end_date):
    """保存回测元信息到 session_state"""
    st.session_state["bt_symbol"] = symbol
    st.session_state["bt_strategy"] = strategy_name
    st.session_state["bt_params"] = dict(params)
    st.session_state["bt_start"] = start_date.strftime("%Y-%m-%d")
    st.session_state["bt_end"] = end_date.strftime("%Y-%m-%d")
    st.session_state["bt_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def render():
    if st.session_state.get("work_mode", "回测") != "回测":
        st.info("请先在侧边栏切换到「📊 回测工作台」模式")
        return

    symbol = st.session_state.get("symbol", "")
    strategy_name = st.session_state.get("strategy_name", "")
    strategy_cls = st.session_state.get("strategy_cls")
    params = st.session_state.get("params", {})
    start_date = st.session_state.get("start_date")
    end_date = st.session_state.get("end_date")

    st.title(f"{strategy_name} — {symbol or '请选择股票'}")

    # ── 触发回测（侧边栏按钮 或 Tab 内按钮） ──
    run_triggered = st.session_state.pop("run_backtest", False)
    tab_rerun = st.button("🔄 重新运行回测", key="rerun_bt", use_container_width=True)

    if run_triggered or tab_rerun:
        if not symbol or not strategy_cls:
            st.warning("请先在侧边栏选择股票和策略")
        else:
            start_s = start_date.strftime("%Y-%m-%d")
            end_s = end_date.strftime("%Y-%m-%d")
            with st.spinner(f"获取 {symbol} 行情数据并运行回测..."):
                data = run_single_backtest(symbol, strategy_cls, params, start_s, end_s)

            if data:
                st.session_state["backtest_data"] = data
                _store_backtest_meta(symbol, strategy_name, params, start_date, end_date)
                st.success(f"回测完成 — {symbol} ({start_s} ~ {end_s})")
                st.rerun()
            else:
                st.stop()

    # ── 显示结果 ──
    if "backtest_data" not in st.session_state:
        st.info("请先在侧边栏配置参数并点击「🚀 运行回测」，或点击上方按钮重跑上次回测")
        return

    data = st.session_state["backtest_data"]

    # 回测元信息
    if "bt_time" in st.session_state:
        meta_cols = st.columns(4)
        with meta_cols[0]:
            st.caption(f"股票: {st.session_state.get('bt_symbol', '-')}")
        with meta_cols[1]:
            st.caption(f"策略: {st.session_state.get('bt_strategy', '-')}")
        with meta_cols[2]:
            st.caption(f"区间: {st.session_state.get('bt_start', '-')} ~ {st.session_state.get('bt_end', '-')}")
        with meta_cols[3]:
            st.caption(f"运行时间: {st.session_state.get('bt_time', '-')}")

    display_metric_cards(data["metrics"])

    st.subheader("资金曲线 & 回撤")
    fig1 = plot_equity_drawdown(data["equity"])
    st.plotly_chart(fig1, use_container_width=True)

    st.subheader("K线图")
    fig2 = plot_kline(data["df"].tail(120))
    st.plotly_chart(fig2, use_container_width=True)

    st.subheader("交易明细")
    trade_df = get_trade_list(data["result"]["strategy"])
    if not trade_df.empty:
        st.dataframe(trade_df, use_container_width=True, hide_index=True)
    else:
        st.info("该时段内无交易记录")
