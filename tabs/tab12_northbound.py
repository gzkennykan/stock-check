"""Tab 12: 北向资金 — 沪股通/深股通资金流向分析"""
import streamlit as st
import pandas as pd
from datetime import datetime
from data.northbound import (
    fetch_northbound_flow, fetch_northbound_summary,
    fetch_northbound_individual
)
from utils import fmt_yuan

import plotly.graph_objects as go
from plotly.subplots import make_subplots


@st.cache_data(ttl=600)
def _load_northbound_flow(start: str, end: str):
    try:
        return fetch_northbound_flow(start, end)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=600)
def _load_northbound_summary():
    try:
        return fetch_northbound_summary()
    except Exception:
        return pd.DataFrame()


def _plot_northbound_flow(df: pd.DataFrame) -> go.Figure:
    """北向资金每日总成交额"""
    if df.empty or "deal_amt" not in df.columns:
        return go.Figure()

    deal = df["deal_amt"]
    ma20 = deal.rolling(20).mean()

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        vertical_spacing=0.08, row_heights=[0.55, 0.45],
                        subplot_titles=("北向资金每日总成交额（亿元）", "20日均值（亿元）"))

    fig.add_trace(go.Bar(
        x=deal.index, y=deal.values,
        marker_color="#FF9800", name="日成交额",
        hovertemplate="%{x|%Y-%m-%d}<br>成交额: %{y:.0f}亿<extra></extra>"
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=ma20.index, y=ma20.values, mode="lines",
        name="20日均值", fill="tozeroy",
        fillcolor="rgba(30,136,229,0.1)",
        line=dict(color="#1E88E5", width=2),
        hovertemplate="%{x|%Y-%m-%d}<br>20日均值: %{y:.0f}亿<extra></extra>"
    ), row=2, col=1)

    fig.update_layout(height=500, showlegend=False, template="plotly_white",
                      hovermode="x unified",
                      margin=dict(l=20, r=20, t=40, b=20))
    fig.update_xaxes(rangeslider_visible=False)
    return fig


def render():
    st.title("资金面分析")
    st.caption("北向资金 + 融资融券 — 内外资动向全景（数据源: 东方财富 / 沪深交易所）")

    tab_nb1, tab_nb2, tab_nb3, tab_nb4 = st.tabs([
        "📈 北向趋势", "📋 市场汇总", "🔍 个股持仓", "📊 融资融券"
    ])

    # ── Tab 1: 资金流向趋势 ──
    with tab_nb1:
        st.subheader("北向资金每日总成交额")
        st.caption("沪股通+深股通合计成交额（亿元），反映外资活跃度")

        col1, col2 = st.columns(2)
        with col1:
            nb_start = st.date_input("起始日期", value=datetime(2024, 1, 1), key="nb_start")
        with col2:
            nb_end = st.date_input("结束日期", value=datetime.now(), key="nb_end")

        if st.button("🔄 刷新数据", key="nb_refresh"):
            st.cache_data.clear()

        with st.spinner("加载北向资金数据..."):
            nb_df = _load_northbound_flow(
                nb_start.strftime("%Y-%m-%d"),
                nb_end.strftime("%Y-%m-%d"),
            )

        if nb_df.empty:
            st.warning("所选日期范围内无北向资金数据")
            return

        deal = nb_df["deal_amt"]
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("日均成交额", f"{deal.mean():,.0f} 亿")
        with c2:
            st.metric("最高成交额", f"{deal.max():,.0f} 亿")
        with c3:
            st.metric("最新成交额", f"{deal.iloc[-1]:,.0f} 亿",
                     help=nb_df.index[-1].strftime("%Y-%m-%d"))
        with c4:
            change = deal.iloc[-1] - deal.iloc[-2] if len(deal) >= 2 else 0
            st.metric("较前日变动", f"{change:+,.0f} 亿")

        fig = _plot_northbound_flow(nb_df)
        st.plotly_chart(fig, use_container_width=True)

    # ── Tab 2: 市场汇总 ──
    with tab_nb2:
        st.subheader("当日北向资金市场汇总")
        st.caption("成交净买额 / 资金净流入 / 当日资金余额 单位均为 **亿元**")

        if st.button("🔄 加载汇总", key="nb_summary"):
            st.cache_data.clear()

        with st.spinner("加载北向资金汇总..."):
            summary = _load_northbound_summary()

        if summary.empty:
            st.info("暂无汇总数据")
        else:
            st.caption(f"共 {len(summary)} 条记录")
            # Rename and format key columns
            display = summary.copy()
            display = display.rename(columns={
                "交易日": "交易日",
                "类型": "类型",
                "板块": "板块",
                "资金方向": "资金方向",
                "交易状态": "交易状态",
                "成交净买额": "成交净买额(亿)",
                "资金净流入": "资金净流入(亿)",
                "当日资金余额": "当日资金余额(亿)",
                "上涨数": "上涨数",
                "持平数": "持平数",
                "下跌数": "下跌数",
                "相关指数": "相关指数",
                "指数涨跌幅": "指数涨跌幅(%)",
            })
            st.dataframe(display, use_container_width=True, hide_index=True,
                         column_config={
                             "指数涨跌幅(%)": st.column_config.NumberColumn(format="%.2f"),
                             "成交净买额(亿)": st.column_config.NumberColumn(format="%.2f"),
                             "资金净流入(亿)": st.column_config.NumberColumn(format="%.2f"),
                             "当日资金余额(亿)": st.column_config.NumberColumn(format="%.2f"),
                         })

    # ── Tab 3: 个股北上持仓 ──
    with tab_nb3:
        st.subheader("个股北向资金持仓历史")
        st.caption("港交所合规要求下仅保留近一年数据，按季度披露（数据源: 东方财富 V2）")

        nb_symbol = st.text_input(
            "股票代码", value=st.session_state.get("symbol", "600036"),
            max_chars=6, key="nb_symbol"
        )

        if st.button("🔍 查询北上持仓", key="nb_ind_query"):
            with st.spinner(f"获取 {nb_symbol} 北向持仓数据..."):
                try:
                    ind_df, stock_name = fetch_northbound_individual(nb_symbol)
                    st.session_state["nb_ind_data"] = ind_df
                    st.session_state["nb_ind_name"] = stock_name
                except Exception as e:
                    st.error(f"获取失败: {e}")
                    st.session_state["nb_ind_data"] = pd.DataFrame()
                    st.session_state["nb_ind_name"] = ""
            st.rerun()

        if "nb_ind_data" in st.session_state:
            ind_df = st.session_state["nb_ind_data"]
            stock_name = st.session_state.get("nb_ind_name", "")
            if ind_df is None or isinstance(ind_df, bool) or ind_df.empty:
                st.info(f"{nb_symbol} 暂无北向持仓数据")
            else:
                name_display = f" — {stock_name}" if stock_name else ""
                st.subheader(f"{nb_symbol}{name_display}")
                st.caption(f"共 {len(ind_df)} 条季度记录，截止 {ind_df.index[-1].strftime('%Y-%m-%d')}")

                # 持仓趋势图
                fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                                    vertical_spacing=0.08, row_heights=[0.5, 0.5],
                                    subplot_titles=("持股市值趋势（亿元）", "持股占比趋势（%）"))

                fig.add_trace(go.Bar(
                    x=ind_df.index, y=ind_df["hold_value"].values / 1e8,
                    name="持股市值(亿)", marker_color="#1E88E5",
                    hovertemplate="%{x|%Y-%m-%d}<br>持股市值: %{y:.2f}亿<extra></extra>"
                ), row=1, col=1)

                fig.add_trace(go.Scatter(
                    x=ind_df.index, y=ind_df["hold_pct"].values,
                    mode="lines+markers", name="占总股本比(%)",
                    line=dict(color="#4CAF50", width=2),
                    marker=dict(size=8, color="#4CAF50"),
                    hovertemplate="%{x|%Y-%m-%d}<br>持股占比: %{y:.2f}%<extra></extra>"
                ), row=2, col=1)

                if "free_shares_ratio" in ind_df.columns:
                    fig.add_trace(go.Scatter(
                        x=ind_df.index, y=ind_df["free_shares_ratio"].values,
                        mode="lines+markers", name="占流通股比(%)",
                        line=dict(color="#FF9800", width=2, dash="dash"),
                        marker=dict(size=8, color="#FF9800"),
                        hovertemplate="%{x|%Y-%m-%d}<br>流通股占比: %{y:.2f}%<extra></extra>"
                    ), row=2, col=1)

                fig.update_layout(height=500, showlegend=True,
                                  template="plotly_white", hovermode="x unified",
                                  margin=dict(l=20, r=20, t=40, b=20),
                                  legend=dict(orientation="h", yanchor="bottom", y=1.02))
                fig.update_xaxes(rangeslider_visible=False)
                st.plotly_chart(fig, use_container_width=True)

                # 最新持仓摘要
                latest = ind_df.iloc[-1]
                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    hv = latest.get("hold_value", 0)
                    st.metric("持股市值", fmt_yuan(hv) if hv else "N/A")
                with c2:
                    hp = latest.get("hold_pct", 0)
                    st.metric("占总股本比", f"{hp:.2f}%" if hp else "N/A")
                with c3:
                    fp = latest.get("free_shares_ratio", 0)
                    st.metric("占流通股比", f"{fp:.2f}%" if fp else "N/A")
                with c4:
                    pn = latest.get("participant_num", 0)
                    st.metric("参与机构数", f"{int(pn)}家" if pn else "N/A")

                # 历史明细表
                with st.expander("📋 季度持仓明细"):
                    display_df = ind_df.copy()
                    display_df["持股市值(亿)"] = (display_df["hold_value"] / 1e8).round(2)
                    display_df["持股数(万股)"] = (display_df["hold_shares"] / 1e4).round(0).astype(int)
                    display_df["占总股本比(%)"] = display_df["hold_pct"].round(2)
                    display_df["占流通股比(%)"] = display_df["free_shares_ratio"].round(2)
                    display_df["机构数"] = display_df["participant_num"].astype(int)
                    display_df["收盘价"] = display_df["close"].round(2)
                    st.dataframe(
                        display_df[["持股市值(亿)", "持股数(万股)", "占总股本比(%)", "占流通股比(%)", "机构数", "收盘价"]],
                        use_container_width=True
                    )

    # ══════════════════════════════════════════
    # Tab 4: 融资融券 ✨
    # ══════════════════════════════════════════
    with tab_nb4:
        st.subheader("融资融券分析")
        st.caption("沪深两市融资融券余额趋势 — 市场杠杆情绪温度计（数据源: 沪深交易所）")

        col_m1, col_m2 = st.columns([2, 3])
        with col_m1:
            margin_days = st.selectbox("查看天数", [30, 60, 90, 120], index=1, key="margin_days")
        with col_m2:
            refresh_margin = st.button("🔄 刷新两融数据", use_container_width=True, key="refresh_margin")

        with st.spinner("正在获取融资融券数据..."):
            try:
                from data.margin import get_margin_summary, get_margin_trend
                margin_summary = get_margin_summary(force_refresh=refresh_margin)
                margin_trend = get_margin_trend(days=int(margin_days), force_refresh=refresh_margin)
            except Exception as e:
                st.error(f"获取两融数据失败: {e}")
                margin_summary, margin_trend = {}, pd.DataFrame()

        # ── 概览卡片 ──
        if margin_summary:
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                mb = margin_summary.get("margin_balance", 0)
                mb_chg = margin_summary.get("margin_balance_change", 0)
                st.metric(
                    "融资余额", f"{mb:,.0f} 亿",
                    delta=f"{mb_chg:+,.0f} 亿" if mb_chg else None,
                    help="沪深两市融资总余额"
                )
            with c2:
                mbuy = margin_summary.get("margin_buy", 0)
                st.metric("当日融资买入", f"{mbuy:,.0f} 亿", help="当日融资买入额")
            with c3:
                net = margin_summary.get("net_margin_buy", 0)
                net_chg = margin_summary.get("net_buy_change", 0)
                st.metric(
                    "融资净买入", f"{net:+,.0f} 亿",
                    delta=f"{net_chg:+,.0f} 亿" if net_chg else None,
                    help="融资买入 - 融资偿还"
                )
            with c4:
                sb = margin_summary.get("short_balance", 0)
                sb_chg = margin_summary.get("short_balance_change", 0)
                st.metric(
                    "融券余额", f"{sb:,.0f} 亿",
                    delta=f"{sb_chg:+,.0f} 亿" if sb_chg else None,
                    help="融券做空余额"
                )

            st.caption(f"数据截止: {margin_summary.get('date', 'N/A')}  |  "
                      f"20日均融资余额: {margin_summary.get('margin_balance_ma20', 0):,.0f} 亿")

        # ── 趋势图 ──
        if not margin_trend.empty:
            import plotly.graph_objects as go
            from plotly.subplots import make_subplots

            fig = make_subplots(
                rows=2, cols=1, shared_xaxes=True,
                vertical_spacing=0.06, row_heights=[0.5, 0.5],
                subplot_titles=("融资余额趋势（亿元）", "融资净买入 / 融资买入（亿元）")
            )

            # 融资余额趋势
            if "margin_balance_yi" in margin_trend.columns:
                bal = margin_trend["margin_balance_yi"]
                ma20 = bal.rolling(20, min_periods=5).mean()
                fig.add_trace(go.Scatter(
                    x=margin_trend.index, y=bal.values,
                    mode="lines", name="融资余额",
                    line=dict(color="#1E88E5", width=1.5),
                ), row=1, col=1)
                fig.add_trace(go.Scatter(
                    x=margin_trend.index, y=ma20.values,
                    mode="lines", name="20日均值",
                    line=dict(color="#FF9800", width=1.5, dash="dash"),
                ), row=1, col=1)

            # 融资买入 & 净买入
            if "margin_buy_yi" in margin_trend.columns:
                fig.add_trace(go.Bar(
                    x=margin_trend.index, y=margin_trend["margin_buy_yi"].values,
                    name="融资买入", marker_color="#4CAF50", opacity=0.6,
                ), row=2, col=1)
            if "net_margin_buy_yi" in margin_trend.columns:
                colors = ["#E53935" if v < 0 else "#4CAF50" for v in margin_trend["net_margin_buy_yi"].values]
                fig.add_trace(go.Bar(
                    x=margin_trend.index, y=margin_trend["net_margin_buy_yi"].values,
                    name="融资净买入", marker_color=colors,
                ), row=2, col=1)

            fig.update_layout(
                height=500, showlegend=True,
                template="plotly_white", hovermode="x unified",
                margin=dict(l=20, r=20, t=40, b=20),
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
            )
            fig.update_xaxes(rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)

            # ── 融券余额趋势 ──
            if "short_balance_yi" in margin_trend.columns:
                st.divider()
                st.caption("融券余额趋势（做空力量）")
                fig2 = go.Figure()
                short_bal = margin_trend["short_balance_yi"]
                fig2.add_trace(go.Scatter(
                    x=margin_trend.index, y=short_bal.values,
                    mode="lines", name="融券余额(亿)",
                    fill="tozeroy", fillcolor="rgba(229,57,53,0.08)",
                    line=dict(color="#E53935", width=2),
                ))
                fig2.update_layout(
                    height=250, showlegend=False,
                    template="plotly_white",
                    margin=dict(l=20, r=20, t=20, b=20),
                )
                st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("暂无两融数据（联网获取中...）")

        st.divider()
        st.caption("💡 融资余额上升 → 市场加杠杆做多情绪强；融资余额持续下降 → 去杠杆避险。"
                  "融券余额飙升 → 做空力量积聚，需警惕。"
                  "融资净买入转正且连续放大 → 多头加速入场信号。")
