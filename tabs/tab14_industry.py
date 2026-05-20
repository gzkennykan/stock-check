"""Tab 14: 行业轮动 — 行业板块热度排名 & 轮动趋势分析"""
import streamlit as st
import pandas as pd

from data.industry import (
    fetch_industry_spot, fetch_industry_list,
    fetch_industry_index, analyze_industry_rotation,
    fetch_industry_stocks,
)

import plotly.graph_objects as go
from plotly.subplots import make_subplots


@st.cache_data(ttl=300)
def _load_industry_spot():
    try:
        return fetch_industry_spot()
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def _load_industry_list():
    try:
        return fetch_industry_list()
    except Exception:
        return []


@st.cache_data(ttl=300)
def _load_industry_rotation():
    try:
        result = analyze_industry_rotation()
        if result is None:
            return pd.DataFrame()
        return result
    except Exception:
        return pd.DataFrame()


def _plot_industry_heatmap(spot_df: pd.DataFrame) -> go.Figure:
    """行业涨跌幅热力条"""
    if spot_df.empty:
        return go.Figure()

    # 确定列名
    name_col = None
    pct_col = None
    for c in spot_df.columns:
        if "名称" in str(c) or "name" in str(c).lower():
            name_col = c
        if "涨跌幅" in str(c) or "pct" in str(c).lower():
            pct_col = c

    if name_col is None or pct_col is None:
        return go.Figure()

    df_sorted = spot_df.sort_values(pct_col, ascending=True)
    pct_vals = pd.to_numeric(df_sorted[pct_col], errors="coerce").values
    names = df_sorted[name_col].values

    colors = ["#E53935" if v >= 0 else "#1E8E4A" for v in pct_vals]

    fig = go.Figure(data=[go.Bar(
        x=pct_vals, y=names, orientation="h",
        marker_color=colors,
        text=[f"{v:+.2f}%" for v in pct_vals],
        textposition="outside",
        hovertemplate="%{y}<br>涨跌幅: %{x:+.2f}%<extra></extra>",
    )])

    fig.add_vline(x=0, line_dash="dash", line_color="gray", opacity=0.5)
    fig.update_layout(
        height=max(400, len(names) * 22),
        template="plotly_white",
        margin=dict(l=20, r=50, t=20, b=20),
        xaxis_title="涨跌幅 (%)",
    )
    return fig


def _plot_industry_trend(industries: list[str], lookback: int = 90) -> go.Figure:
    """多行业叠加走势对比（同花顺 10jqka 实时数据）"""
    if not industries:
        return go.Figure()

    from datetime import datetime
    end_date = datetime.now().strftime("%Y%m%d")

    fig = go.Figure()
    colors = ["#1E88E5", "#E53935", "#4CAF50", "#FF9800", "#9C27B0",
              "#00BCD4", "#FF5722", "#795548", "#607D8B", "#E91E63"]

    for i, ind_name in enumerate(industries[:8]):
        try:
            df = fetch_industry_index(ind_name, end_date=end_date)
            if df.empty or len(df) < 2:
                continue
            df_slice = df.tail(lookback) if len(df) > lookback else df
            close_col = "close" if "close" in df.columns else df.columns[-1]
            pct = (df_slice[close_col] / df_slice[close_col].iloc[0] - 1) * 100
            fig.add_trace(go.Scatter(
                x=pct.index, y=pct.values, mode="lines",
                name=ind_name, line=dict(color=colors[i % len(colors)], width=1.5),
                hovertemplate=f"{ind_name}<br>%{{x|%Y-%m-%d}}<br>%{{y:.2f}}%<extra></extra>"
            ))
        except Exception:
            continue

    fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
    fig.update_layout(
        height=500, template="plotly_white",
        hovermode="x unified",
        margin=dict(l=20, r=20, t=20, b=20),
        legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01, font=dict(size=9)),
        yaxis_title="累计涨跌幅 (%)",
    )
    return fig


def render():
    st.title("行业轮动分析")
    st.caption("行业板块热度排名 & 轮动趋势")

    tab_i1, tab_i2, tab_i3 = st.tabs([
        "🔥 行业热度排名", "📈 轮动趋势", "🔬 行业成分股"
    ])

    # ── Tab 1: 行业热度排名 ──
    with tab_i1:
        st.subheader("实时行业涨跌幅排名")

        if st.button("🔄 刷新", key="ind_refresh"):
            st.cache_data.clear()

        with st.spinner("加载行业行情..."):
            spot = _load_industry_spot()

        if spot.empty:
            st.info("暂无行业数据")
        else:
            # 确定列名
            name_col = None
            pct_col = None
            for c in spot.columns:
                cn = str(c)
                if "名称" in cn or "name" in cn.lower():
                    name_col = c
                if "涨跌幅" in cn or "pct" in cn.lower():
                    pct_col = c

            # 统计摘要
            if pct_col is not None:
                pct_vals = pd.to_numeric(spot[pct_col], errors="coerce")
                up_count = (pct_vals > 0).sum()
                down_count = (pct_vals < 0).sum()

                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    st.metric("行业总数", len(spot))
                with c2:
                    st.metric("上涨行业", up_count)
                with c3:
                    st.metric("下跌行业", down_count)
                with c4:
                    if len(pct_vals) > 0:
                        st.metric("平均涨幅", f"{pct_vals.mean():+.2f}%")

            # 热力图
            fig_bar = _plot_industry_heatmap(spot)
            st.plotly_chart(fig_bar, use_container_width=True, key="ind_heatmap")

            # 表格
            with st.expander("📋 查看原始数据"):
                st.dataframe(spot, use_container_width=True, hide_index=True)

    # ── Tab 2: 轮动趋势 ──
    with tab_i2:
        st.subheader("行业轮动分析")
        st.caption("基于同花顺行业资金流向实时排名，反映当日资金轮动方向")

        if st.button("🔍 执行轮动分析", key="ind_rotation_btn"):
            st.cache_data.clear()
            with st.spinner("获取行业资金流向并进行轮动分析..."):
                rotation = _load_industry_rotation()
                if rotation is not None and not isinstance(rotation, bool) and not rotation.empty:
                    st.session_state["ind_rotation_cache"] = rotation
            st.rerun()

        if "ind_rotation_cache" in st.session_state:
            rotation = st.session_state["ind_rotation_cache"]
            if isinstance(rotation, bool) or rotation.empty:
                pass
            else:
                top5 = rotation.head(5)
                bottom5 = rotation.tail(5)

                col_a, col_b = st.columns(2)
                with col_a:
                    st.markdown("##### 🔥 资金净流入 TOP5")
                    for _, r in top5.iterrows():
                        st.metric(r["行业"], f"{r['净额(亿)']:+,.2f} 亿")
                with col_b:
                    st.markdown("##### ❄️ 资金净流出 BOTTOM5")
                    for _, r in bottom5.iterrows():
                        st.metric(r["行业"], f"{r['净额(亿)']:+,.2f} 亿")

                # 资金流向柱状图
                plot_df = rotation.head(30).copy()
                plot_df = plot_df.sort_values("净额(亿)", ascending=True)
                colors = ["#E53935" if v >= 0 else "#1E8E4A" for v in plot_df["净额(亿)"]]
                fig_flow = go.Figure(data=[go.Bar(
                    x=plot_df["净额(亿)"].values,
                    y=plot_df["行业"].values, orientation="h",
                    marker_color=colors,
                    text=[f"{v:+,.2f}亿" for v in plot_df["净额(亿)"].values],
                    textposition="outside",
                    hovertemplate="%{y}<br>净额: %{x:+,.2f}亿<extra></extra>",
                )])
                fig_flow.add_vline(x=0, line_dash="dash", line_color="gray", opacity=0.5)
                fig_flow.update_layout(
                    height=max(500, len(plot_df) * 20),
                    template="plotly_white",
                    margin=dict(l=20, r=60, t=20, b=20),
                    xaxis_title="资金净额（亿元）",
                )
                st.plotly_chart(fig_flow, use_container_width=True, key="ind_fund_flow")

                st.dataframe(rotation, use_container_width=True, hide_index=True,
                             column_config={
                                 "涨跌幅(%)": st.column_config.NumberColumn(format="%+.2f"),
                                 "净额(亿)": st.column_config.NumberColumn(format="%+.2f"),
                                 "流入资金(亿)": st.column_config.NumberColumn(format="%.2f"),
                                 "流出资金(亿)": st.column_config.NumberColumn(format="%.2f"),
                                 "领涨股涨幅(%)": st.column_config.NumberColumn(format="%+.2f"),
                             })

        # 自定义行业对比
        st.subheader("自定义行业走势对比")
        st.caption("同花顺行业指数历史走势（实时数据）")
        industry_list = _load_industry_list()
        if industry_list:
            selected_inds = st.multiselect(
                "选择行业进行走势对比（最多8个）",
                options=industry_list,
                default=[],
                max_selections=8,
                placeholder="如：半导体及元件、银行、白酒...",
                key="ind_compare",
            )
            if selected_inds:
                fig_trend = _plot_industry_trend(selected_inds, 365)
                st.plotly_chart(fig_trend, use_container_width=True, key="ind_trend")

    # ── Tab 3: 行业成分股 ──
    with tab_i3:
        st.subheader("行业成分股查询")

        industry_list = _load_industry_list()
        if industry_list:
            selected_ind = st.selectbox(
                "选择行业", options=industry_list, key="ind_detail"
            )

            if st.button("🔍 查询成分股", key="ind_stocks_btn"):
                with st.spinner(f"获取「{selected_ind}」成分股..."):
                    try:
                        stocks = fetch_industry_stocks(selected_ind)
                        st.session_state["ind_stocks_data"] = stocks
                        st.session_state["ind_stocks_name"] = selected_ind
                    except Exception as e:
                        st.error(f"获取失败: {e}")
                st.rerun()

            if "ind_stocks_data" in st.session_state:
                stocks_data = st.session_state["ind_stocks_data"]
                if not isinstance(stocks_data, bool) and hasattr(stocks_data, '__len__'):
                    st.caption(f"「{st.session_state.get('ind_stocks_name', '')}」成分股 — "
                               f"共 {len(stocks_data)} 只")
                    st.dataframe(stocks_data, use_container_width=True, hide_index=True)
