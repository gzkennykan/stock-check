"""Tab 2: 多策略对比"""
import streamlit as st
import pandas as pd
from backtest_utils import load_data, get_equity_curve, get_daily_returns, get_trade_list
from backtest.engine import run_multi_backtest
from analysis.metrics import compute_metrics
from visualization.plotly_charts import plot_comparison_chart, plot_comparison_curves


def render():
    if st.session_state.get("work_mode", "回测") != "回测":
        st.info("请先在侧边栏切换到「📊 回测工作台」模式")
        return

    symbol = st.session_state.get("symbol", "")
    start_date = st.session_state.get("start_date")
    end_date = st.session_state.get("end_date")

    st.title("多策略对比")

    # 导入策略映射
    from strategies import (
        MACrossStrategy, MACDStrategy, RSIStrategy,
        BollingerStrategy, TripleMAStrategy, KDJStrategy,
        DonchianStrategy, ATRStrategy,
    )
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

        with st.spinner("运行所有策略..."):
            results = run_multi_backtest(strategy_map, df)

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

            st.subheader("资金曲线叠加")
            fig_curve = plot_comparison_curves(curves)
            st.plotly_chart(fig_curve, use_container_width=True)

            st.subheader("详细对比")
            display_rows = [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]
            st.dataframe(pd.DataFrame(display_rows), use_container_width=True, hide_index=True)

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
