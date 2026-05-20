"""Tab 11: 组合回测 — 多股票组合 + 权重分配"""
import streamlit as st
import pandas as pd
from data.fetcher import fetch_data
from backtest.portfolio import run_portfolio_backtest
from visualization.plotly_charts import plot_equity_drawdown
from backtest_utils import display_metric_cards
from analysis.metrics import compute_metrics
from config import INITIAL_CASH

import plotly.graph_objects as go
from plotly.subplots import make_subplots

HOT_STOCKS = {
    "招商银行": "600036",
    "贵州茅台": "600519",
    "宁德时代": "300750",
    "平安银行": "000001",
    "比亚迪": "002594",
    "工商银行": "601398",
    "中国平安": "601318",
}


def _plot_portfolio_curves(
    combined_equity: pd.Series,
    individual_equities: dict[str, pd.Series],
    weights: dict[str, float],
) -> go.Figure:
    """组合资金曲线 + 个股收益率对比"""
    n_individual = len(individual_equities)
    row_heights = [0.6] + [0.4] if n_individual <= 6 else [0.5, 0.5]
    subtitles = ["组合资金曲线"] + (["个股累计收益率 (%)"] if n_individual <= 6 else [])

    if len(subtitles) == 2:
        fig = make_subplots(
            rows=2, cols=1, shared_xaxes=True,
            vertical_spacing=0.08,
            row_heights=[0.55, 0.45],
            subplot_titles=subtitles,
        )
    else:
        fig = make_subplots(
            rows=1, cols=1,
            subplot_titles=subtitles,
        )

    # 组合资金曲线
    fig.add_trace(go.Scatter(
        x=combined_equity.index, y=combined_equity.values,
        mode="lines", name="组合资金",
        fill="tozeroy", fillcolor="rgba(30,136,229,0.1)",
        line=dict(color="#1E88E5", width=2.5),
        hovertemplate="%{x|%Y-%m-%d}<br>组合: ¥%{y:,.0f}<extra></extra>"
    ), row=1, col=1)
    fig.add_hline(y=combined_equity.values[0], line_dash="dash", line_color="gray",
                  opacity=0.5, row=1, col=1)

    # 个股收益率
    colors = ["#FF9800", "#4CAF50", "#E53935", "#9C27B0", "#00BCD4",
              "#FF5722", "#795548"]
    if n_individual <= 6:
        for i, (sym, eq) in enumerate(individual_equities.items()):
            pct = (eq / eq.iloc[0] - 1) * 100
            w = weights.get(sym, 0)
            fig.add_trace(go.Scatter(
                x=pct.index, y=pct.values, mode="lines",
                name=f"{sym} ({w:.0%})",
                line=dict(color=colors[i % len(colors)], width=1.2),
                hovertemplate=f"{sym}<br>%{{x|%Y-%m-%d}}<br>收益率: %{{y:.2f}}%<extra></extra>"
            ), row=2, col=1)
        fig.add_hline(y=0, line_dash="dash", line_color="gray",
                      opacity=0.5, row=2, col=1)

    fig.update_layout(
        height=550 if n_individual <= 6 else 400,
        showlegend=True,
        hovermode="x unified",
        margin=dict(l=20, r=20, t=40, b=20),
        template="plotly_white",
        legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01, font=dict(size=10)),
    )
    fig.update_xaxes(rangeslider_visible=False)
    return fig


def _plot_correlation_heatmap(corr_matrix: pd.DataFrame) -> go.Figure:
    """相关性矩阵热力图"""
    labels = list(corr_matrix.columns)
    fig = go.Figure(data=go.Heatmap(
        z=corr_matrix.values,
        x=labels,
        y=labels,
        zmin=-1, zmax=1,
        colorscale="RdBu",
        text=[[f"{v:.2f}" for v in row] for row in corr_matrix.values],
        texttemplate="%{text}",
        textfont=dict(size=12),
        hoverongaps=False,
    ))
    fig.update_layout(
        height=350,
        template="plotly_white",
        margin=dict(l=20, r=20, t=20, b=20),
        xaxis=dict(tickangle=45),
    )
    return fig


def render():
    if st.session_state.get("work_mode", "回测") != "回测":
        st.info("请先在侧边栏切换到「📊 回测工作台」模式")
        return

    st.title("组合回测")
    st.caption("选择多只股票组成投资组合，按权重分配资金，运行统一策略回测")

    # ── 选股 ──
    st.subheader("选择成分股")
    cols = st.columns(len(HOT_STOCKS))
    selected_symbols = []
    for i, (name, code) in enumerate(HOT_STOCKS.items()):
        with cols[i]:
            if st.checkbox(name, value=(code in ["600036", "600519"]), key=f"pf_{code}"):
                selected_symbols.append(code)

    custom = st.text_input(
        "自定义股票代码", placeholder="输入6位代码并用逗号分隔，如 600036,000001,000858",
        key="pf_custom"
    )
    if custom:
        for c in custom.replace("，", ",").split(","):
            c = c.strip()
            if c.isdigit() and len(c) == 6 and c not in selected_symbols:
                selected_symbols.append(c)

    if not selected_symbols:
        st.info("请至少选择2只股票组成组合")
        return

    st.caption(f"已选 {len(selected_symbols)} 只: {' / '.join(selected_symbols)}")

    # ── 权重分配 ──
    st.subheader("权重分配")
    weight_mode = st.radio("分配方式", ["等权重", "自定义权重"], horizontal=True, key="pf_wmode")

    weights = {}
    if weight_mode == "等权重":
        w = 1.0 / len(selected_symbols)
        for s in selected_symbols:
            weights[s] = w
        st.caption(f"每只股票权重: {w:.1%}")
    else:
        w_cols = st.columns(min(len(selected_symbols), 6))
        w_inputs = {}
        for i, s in enumerate(selected_symbols):
            with w_cols[i % 6]:
                w_inputs[s] = st.number_input(
                    f"{s}", 0, 100, int(100 / len(selected_symbols)),
                    step=1, key=f"pf_w_{s}",
                )

        total_w = sum(w_inputs.values())
        if total_w == 0:
            st.warning("权重总和不能为0")
            return
        for s, w_val in w_inputs.items():
            weights[s] = w_val / total_w
        st.caption(f"归一化后权重: {' | '.join(f'{s}: {v:.1%}' for s, v in weights.items())}")

    # ── 策略 ──
    st.subheader("交易策略")
    strategy_name = st.session_state.get("strategy_name", "")
    strategy_cls = st.session_state.get("strategy_cls")
    params = st.session_state.get("params", {}).copy()
    if strategy_cls is None:
        st.warning("请先在侧边栏选择策略")
        return
    st.caption(f"当前策略: {strategy_name}")

    # 回测日期
    start_date = st.session_state.get("start_date")
    end_date = st.session_state.get("end_date")
    start_s = start_date.strftime("%Y-%m-%d") if start_date else "2024-01-01"
    end_s = end_date.strftime("%Y-%m-%d") if end_date else "2025-05-08"

    # ── 运行 ──
    if st.button("🚀 运行组合回测", type="primary", use_container_width=True):
        with st.spinner(f"获取 {len(selected_symbols)} 只股票数据并回测..."):
            stock_data = {}
            fetch_errors = []
            for sym in selected_symbols:
                try:
                    df = fetch_data(sym, start_s, end_s)
                    if df.empty:
                        fetch_errors.append(sym)
                    else:
                        stock_data[sym] = df
                except Exception as e:
                    fetch_errors.append(f"{sym}: {e}")

            if fetch_errors:
                st.warning(f"以下股票数据获取失败: {', '.join(str(e) for e in fetch_errors)}")

            if len(stock_data) < 2:
                st.error("至少需要2只有效股票数据才能构建组合")
                return

            result = run_portfolio_backtest(
                strategy_cls,
                list(stock_data.keys()),
                stock_data,
                weights={s: weights.get(s, 1.0 / len(stock_data))
                         for s in stock_data},
                strategy_params=params,
            )

        if result is None:
            st.error("组合回测失败，请检查数据")
            return

        st.session_state["pf_result"] = result
        st.session_state["pf_symbols"] = list(stock_data.keys())
        st.session_state["pf_weights"] = weights
        st.rerun()

    # ── 显示结果 ──
    if "pf_result" not in st.session_state:
        return

    result = st.session_state["pf_result"]
    pf_symbols = st.session_state.get("pf_symbols", [])

    st.markdown("---")
    st.subheader("组合指标")

    # 构建 MetricsResult 用于 display_metric_cards
    from analysis.metrics import MetricsResult
    metrics = MetricsResult(
        total_return=result.total_return,
        annual_return=result.annual_return,
        sharpe_ratio=result.sharpe_ratio,
        max_drawdown=result.max_drawdown,
        max_drawdown_duration=0,
        annual_volatility=result.annual_volatility,
        win_rate=result.win_rate,
        profit_loss_ratio=result.profit_loss_ratio,
        calmar_ratio=result.calmar_ratio,
        total_trades=result.total_trades,
        start_value=result.start_value,
        end_value=result.end_value,
    )
    display_metric_cards(metrics)

    # 组合资金曲线
    st.subheader("组合资金曲线 & 个股走势")
    fig1 = _plot_portfolio_curves(
        result.combined_equity,
        result.individual_equities,
        result.weights,
    )
    st.plotly_chart(fig1, use_container_width=True)

    # 个股贡献
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("个股收益贡献")
        contrib_data = []
        for sym in pf_symbols:
            if sym in result.individual_returns:
                r = result.individual_returns[sym]
                w = result.weights.get(sym, 0)
                contrib_data.append({
                    "股票": sym,
                    "权重": f"{w:.1%}",
                    "个股收益": f"{r:.2%}",
                    "加权贡献": f"{r * w:.2%}",
                })
        if contrib_data:
            st.dataframe(pd.DataFrame(contrib_data), use_container_width=True, hide_index=True)

    with col_b:
        if result.corr_matrix is not None and len(result.corr_matrix.columns) >= 2:
            st.subheader("个股相关性矩阵")
            fig_corr = _plot_correlation_heatmap(result.corr_matrix)
            st.plotly_chart(fig_corr, use_container_width=True)
        else:
            st.info("相关性数据不足")

    # 权重分布饼图
    st.subheader("权重分布")
    pie_fig = go.Figure(data=[go.Pie(
        labels=list(result.weights.keys()),
        values=list(result.weights.values()),
        textinfo="label+percent",
        hole=0.3,
        marker=dict(colors=["#1E88E5", "#FF9800", "#4CAF50", "#E53935",
                            "#9C27B0", "#00BCD4", "#FF5722", "#795548"]),
    )])
    pie_fig.update_layout(height=350, template="plotly_white",
                          margin=dict(l=20, r=20, t=20, b=20))
    st.plotly_chart(pie_fig, use_container_width=True)
