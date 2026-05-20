"""Tab 13: 财务分析 — 基本面指标查询 & 业绩预告"""
import streamlit as st
import pandas as pd
from data.fundamental import fetch_financial_indicators, fetch_performance_forecast
from utils import fmt_yuan

import plotly.graph_objects as go
from plotly.subplots import make_subplots


def _plot_financial_radar(data: dict) -> go.Figure:
    """财务指标雷达图"""
    categories = []
    values = []
    thresholds = []

    metrics = [
        ("ROE(%)", "roe", 20),
        ("毛利率(%)", "gross_margin", 50),
        ("净利率(%)", "net_margin", 30),
        ("营收增速(%)", "revenue_yoy", 50),
        ("利润增速(%)", "profit_yoy", 50),
    ]
    for label, key, ref in metrics:
        v = data.get(key)
        if v is not None:
            categories.append(label)
            values.append(v)
            thresholds.append(ref)

    if len(categories) < 2:
        return go.Figure()

    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=values, theta=categories, fill="toself",
        name="当前值", line=dict(color="#1E88E5", width=2),
        fillcolor="rgba(30,136,229,0.3)",
        hovertemplate="%{theta}: %{r:.2f}%<extra></extra>"
    ))
    # 参考线
    fig.add_trace(go.Scatterpolar(
        r=thresholds, theta=categories, fill="none",
        name="参考线", line=dict(color="#BDBDBD", width=1, dash="dot"),
        hovertemplate="%{theta}参考: %{r:.2f}%<extra></extra>"
    ))

    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, max(max(values), max(thresholds)) * 1.2])),
        height=400, template="plotly_white",
        margin=dict(l=40, r=40, t=20, b=20),
        legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01),
    )
    return fig


def render():
    st.title("财务分析")
    st.caption("基本面指标查询 & 业绩预告")

    tab_f1, tab_f2 = st.tabs(["🔬 个股财务指标", "📋 业绩预告"])

    # ── Tab 1: 个股财务指标 ──
    with tab_f1:
        fin_symbol = st.text_input(
            "股票代码", value=st.session_state.get("symbol", "600036"),
            max_chars=6, key="fin_symbol"
        )

        if st.button("🔍 查询财务指标", key="fin_query"):
            with st.spinner(f"获取 {fin_symbol} 财务指标..."):
                data = fetch_financial_indicators(fin_symbol)

            if data is None:
                st.error(f"未能获取 {fin_symbol} 的财务数据")
            else:
                st.session_state["fin_data"] = data
                st.rerun()

        if "fin_data" in st.session_state:
            data = st.session_state["fin_data"]
            name = data.get("name", "")
            name_display = f" — {name}" if name else ""
            st.subheader(f"{data.get('symbol', '')}{name_display}")

            # 盈利能力
            st.subheader("盈利能力")
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                roe = data.get("roe")
                st.metric("ROE (净资产收益率)",
                          f"{roe:.2f}%" if roe is not None else "N/A")
            with c2:
                roa = data.get("roa")
                st.metric("ROA (总资产收益率)",
                          f"{roa:.2f}%" if roa is not None else "N/A")
            with c3:
                gm = data.get("gross_margin")
                st.metric("毛利率", f"{gm:.2f}%" if gm is not None else "N/A")
            with c4:
                nm = data.get("net_margin")
                st.metric("净利率", f"{nm:.2f}%" if nm is not None else "N/A")

            # 成长性
            st.subheader("成长性")
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                ry = data.get("revenue_yoy")
                st.metric("营收同比增速", f"{ry:+.2f}%" if ry is not None else "N/A")
            with c2:
                py = data.get("profit_yoy")
                st.metric("净利润同比增速", f"{py:+.2f}%" if py is not None else "N/A")
            with c3:
                eps = data.get("eps")
                st.metric("每股收益(EPS)", f"{eps:.2f}" if eps is not None else "N/A")
            with c4:
                bps = data.get("bps")
                st.metric("每股净资产(BPS)", f"{bps:.2f}" if bps is not None else "N/A")

            # 偿债能力
            st.subheader("偿债能力 & 现金流")
            c1, c2, c3 = st.columns(3)
            with c1:
                dr = data.get("debt_ratio")
                st.metric("资产负债率", f"{dr:.2f}%" if dr is not None else "N/A")
            with c2:
                cr = data.get("current_ratio")
                st.metric("流动比率", f"{cr:.2f}" if cr is not None else "N/A")
            with c3:
                qr = data.get("quick_ratio")
                st.metric("速动比率", f"{qr:.2f}" if qr is not None else "N/A")

            # 规模
            st.subheader("规模")
            c1, c2 = st.columns(2)
            with c1:
                tr = data.get("total_revenue")
                st.metric("营业总收入", fmt_yuan(tr) if tr is not None else "N/A")
            with c2:
                np_val = data.get("net_profit")
                st.metric("净利润", fmt_yuan(np_val) if np_val is not None else "N/A")

            # 雷达图
            st.subheader("关键指标雷达图")
            fig_radar = _plot_financial_radar(data)
            st.plotly_chart(fig_radar, use_container_width=True, key="fin_radar")

    # ── Tab 2: 业绩预告 ──
    with tab_f2:
        st.subheader("A股业绩预告")

        use_latest = st.checkbox("使用最新报告期", value=True, key="ff_latest")
        if not use_latest:
            report_date = st.text_input(
                "报告期", value="2024-12-31",
                placeholder="YYYY-MM-DD格式，如 2024-12-31",
                key="ff_date",
            )
        else:
            report_date = None

        if st.button("🔍 查询业绩预告", key="ff_query"):
            with st.spinner("获取业绩预告数据..."):
                try:
                    forecast_df = fetch_performance_forecast(report_date)
                    if not forecast_df.empty:
                        # 数值转为亿元显示
                        for col in ["预测净利润下限", "预测净利润上限", "上年同期值"]:
                            if col in forecast_df.columns:
                                forecast_df[col + "(亿)"] = (forecast_df[col] / 1e8).round(2)
                        forecast_df = forecast_df.drop(columns=["预测净利润下限", "预测净利润上限", "上年同期值"], errors="ignore")
                    st.session_state["forecast_df"] = forecast_df
                except Exception as e:
                    st.error(f"获取失败: {e}")
            st.rerun()

        if "forecast_df" in st.session_state:
            fdf = st.session_state["forecast_df"]
            st.caption(f"共 {len(fdf)} 条业绩预告")

            if not fdf.empty:
                # 统计
                c1, c2, c3 = st.columns(3)
                if "业绩变动" in fdf.columns:
                    good = fdf[fdf["业绩变动"].str.contains("预增|预盈|略增|扭亏", na=False)]
                    bad = fdf[fdf["业绩变动"].str.contains("预减|预亏|略减|首亏|续亏", na=False)]
                    with c1:
                        st.metric("预喜", len(good))
                    with c2:
                        st.metric("预忧", len(bad))
                    with c3:
                        st.metric("其他", len(fdf) - len(good) - len(bad))

                # 完整显示业绩变动原因（CSS 自动换行，不影响其他列）
                st.html("""
                <style>
                .stDataFrame td:last-child {
                    max-width: 260px;
                    white-space: normal;
                    word-break: break-all;
                    font-size: 0.85em;
                }
                </style>
                """)
                st.dataframe(fdf.head(100), use_container_width=True, hide_index=True)
