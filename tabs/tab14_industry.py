"""Tab 11: 市场全景 — 行业热度 & 成分股 & 市场宽度"""
import streamlit as st
import pandas as pd

from data.industry import (
    fetch_industry_spot, fetch_industry_list,
    fetch_industry_stocks,
)

import plotly.graph_objects as go
from visualization.plotly_charts import plot_horizontal_bars


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


def _plot_industry_heatmap(spot_df: pd.DataFrame) -> go.Figure:
    """行业涨跌幅热力条（使用通用横向柱状图）"""
    if spot_df.empty:
        return go.Figure()
    name_col = pct_col = None
    for c in spot_df.columns:
        if "名称" in str(c) or "name" in str(c).lower():
            name_col = c
        if "涨跌幅" in str(c) or "pct" in str(c).lower():
            pct_col = c
    if name_col is None or pct_col is None:
        return go.Figure()
    df_sorted = spot_df.sort_values(pct_col, ascending=True)
    return plot_horizontal_bars(
        pd.to_numeric(df_sorted[pct_col], errors="coerce").values,
        df_sorted[name_col].values,
        xaxis_title="涨跌幅 (%)",
        text_format="{:+0.2f}%",
    )


def render():
    st.title("市场全景")
    st.caption("行业热度 + 成分股 + 市场宽度 — 全方位感知市场温度")
    st.info("💡 **行业轮动分析**已整合至「📊 高级分析 → 🔄 行业轮动」子页，基于 DuckDB 历史数据提供更全面的多周期动量分析")

    tab_i1, tab_i2, tab_i3 = st.tabs([
        "🔥 行业热度", "🔬 成分股", "📊 市场宽度"
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

    # ── Tab 2: 行业成分股 ──
    with tab_i2:
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

    # ══════════════════════════════════════════
    # Tab 3: 市场宽度 ✨
    # ══════════════════════════════════════════
    with tab_i3:
        st.subheader("市场宽度仪表盘")
        st.caption("基于全市场 ~5200 只股票的实时统计，感知整体市场温度（数据源: 新浪行情 + 同花顺资金流）")

        if st.button("🔄 刷新市场宽度", use_container_width=True, key="breadth_refresh"):
            st.cache_data.clear()

        with st.spinner("正在计算市场宽度指标..."):
            try:
                from data.screener import get_stock_list, get_fund_flow_data
                spot_df = get_stock_list()
                try:
                    fund_df = get_fund_flow_data()
                except Exception:
                    fund_df = pd.DataFrame()
            except Exception as e:
                st.error(f"数据加载失败: {e}")
                spot_df, fund_df = pd.DataFrame(), pd.DataFrame()

        if spot_df.empty:
            st.info("暂无行情数据")
        else:
            # ── 基础统计 ──
            total_stocks = len(spot_df)
            pct_col = "pct_change" if "pct_change" in spot_df.columns else None

            if pct_col and pct_col in spot_df.columns:
                pct_vals = pd.to_numeric(spot_df[pct_col], errors="coerce").dropna()
                up_count = (pct_vals > 0).sum()
                down_count = (pct_vals < 0).sum()
                flat_count = (pct_vals == 0).sum()
                up_ratio = up_count / len(pct_vals) * 100 if len(pct_vals) > 0 else 0

                # 涨停/跌停近似 (A股 ±10% 涨跌停，创业板/科创板 ±20%)
                zt_approx = (pct_vals >= 9.5).sum()
                dt_approx = (pct_vals <= -9.5).sum()

                # 强/弱势股比例 (>5% / <-5%)
                strong_up = (pct_vals >= 5).sum()
                strong_down = (pct_vals <= -5).sum()

                avg_pct = pct_vals.mean()
                median_pct = pct_vals.median()

            # ── 概览卡片 ──
            st.caption("### 涨跌宽度")
            c1, c2, c3, c4, c5 = st.columns(5)
            if pct_col and pct_col in spot_df.columns:
                with c1:
                    st.metric("上涨家数", up_count, delta=f"{up_ratio:.0f}%")
                with c2:
                    st.metric("下跌家数", down_count)
                with c3:
                    st.metric("平盘", flat_count)
                with c4:
                    st.metric("涨停≈", zt_approx, help="涨跌幅≥9.5%的股票数")
                with c5:
                    st.metric("跌停≈", dt_approx, help="涨跌幅≤-9.5%的股票数")

                c6, c7, c8, c9, c10 = st.columns(5)
                with c6:
                    st.metric("平均涨幅", f"{avg_pct:+.2f}%")
                with c7:
                    st.metric("涨幅中位数", f"{median_pct:+.2f}%")
                with c8:
                    st.metric("强势股(≥5%)", strong_up)
                with c9:
                    st.metric("弱势股(≤-5%)", strong_down)
                with c10:
                    ratio = f"{up_count/down_count:.2f}" if down_count > 0 else "∞"
                    st.metric("涨跌比", ratio, help="上涨/下跌家数比，>2=强势市场，<0.5=弱势市场")

            # ── 资金宽度 ──
            if not fund_df.empty and "main_capital" in fund_df.columns:
                st.divider()
                st.caption("### 资金宽度")
                fund_cap = pd.to_numeric(fund_df["main_capital"], errors="coerce").dropna()
                fund_positive = (fund_cap > 0).sum()
                fund_total = len(fund_cap)
                fund_breadth = fund_positive / fund_total * 100 if fund_total > 0 else 0

                total_main = fund_cap.sum()
                total_main_inflow = fund_cap[fund_cap > 0].sum()
                total_main_outflow = abs(fund_cap[fund_cap < 0].sum())

                cc1, cc2, cc3, cc4 = st.columns(4)
                with cc1:
                    st.metric("主力净流入家数", fund_positive, delta=f"{fund_breadth:.0f}%")
                with cc2:
                    st.metric("资金宽度", f"{fund_breadth:.0f}%",
                              help="主力净流入为正的股票占比。>50%=资金面偏暖，<30%=资金面偏冷")
                with cc3:
                    from utils import fmt_yuan
                    st.metric("全市场主力净流入", fmt_yuan(total_main_inflow, signed=False),
                              help="所有主力净流入股票的资金总和")
                with cc4:
                    st.metric("全市场主力净流出", fmt_yuan(total_main_outflow, signed=False),
                              help="所有主力净流出股票的资金总和(绝对值)")

                # 资金宽度进度条
                width_color = "#4CAF50" if fund_breadth >= 50 else ("#FF9800" if fund_breadth >= 30 else "#E53935")
                st.progress(min(fund_breadth / 100, 1.0),
                            text=f"资金宽度: {fund_breadth:.0f}% (净流入为正的股票占比)")

            # ── 成交额集中度 ──
            if "turnover" in spot_df.columns:
                st.divider()
                st.caption("### 成交额集中度")
                turnover_vals = pd.to_numeric(spot_df["turnover"], errors="coerce").dropna().sort_values(ascending=False)
                total_turnover = turnover_vals.sum()

                if total_turnover > 0:
                    top10_pct = turnover_vals.head(10).sum() / total_turnover * 100
                    top50_pct = turnover_vals.head(50).sum() / total_turnover * 100
                    top100_pct = turnover_vals.head(100).sum() / total_turnover * 100

                    tc1, tc2, tc3 = st.columns(3)
                    with tc1:
                        st.metric("TOP10 成交占比", f"{top10_pct:.1f}%",
                                  help="成交额最大的10只股票占总成交的比例，越高=资金越集中")
                    with tc2:
                        st.metric("TOP50 成交占比", f"{top50_pct:.1f}%")
                    with tc3:
                        st.metric("TOP100 成交占比", f"{top100_pct:.1f}%")

            # ── 涨跌分布直方图 ──
            if pct_col and pct_col in spot_df.columns:
                st.divider()
                st.caption("### 涨跌幅分布")

                # 分段统计
                bins = [-100, -10, -8, -5, -3, -1, 0, 1, 3, 5, 8, 10, 100]
                labels = ["跌停", "-10~-8%", "-8~-5%", "-5~-3%", "-3~-1%", "-1~0%",
                          "0~1%", "1~3%", "3~5%", "5~8%", "8~10%", "涨停"]
                pct_binned = pd.cut(pct_vals, bins=bins, labels=labels, right=True)
                dist = pct_binned.value_counts().reindex(labels, fill_value=0)

                colors_bar = ["#B71C1C"] + ["#E57373"] * 4 + ["#BDBDBD"] + \
                             ["#81C784"] * 4 + ["#2E7D32"]

                fig_dist = go.Figure(data=[go.Bar(
                    x=labels, y=dist.values,
                    marker_color=colors_bar,
                    text=[f"{v}只" if v > 0 else "" for v in dist.values],
                    textposition="outside",
                )])
                fig_dist.update_layout(
                    height=350, template="plotly_white",
                    margin=dict(l=20, r=20, t=20, b=60),
                    xaxis_tickangle=-45,
                    yaxis_title="股票数量",
                )
                st.plotly_chart(fig_dist, use_container_width=True)

            # ── 市场温度总结 ──
            st.divider()
            st.caption("### 市场温度评估")

            # 综合评估
            temp_score = 0
            temp_reasons = []

            if pct_col and pct_col in spot_df.columns:
                if up_ratio > 65:
                    temp_score += 30
                    temp_reasons.append(f"✅ 上涨占比{up_ratio:.0f}%，市场普涨")
                elif up_ratio > 45:
                    temp_score += 20
                    temp_reasons.append(f"↔️ 上涨占比{up_ratio:.0f}%，多空均衡")
                else:
                    temp_score += 5
                    temp_reasons.append(f"⚠️ 上涨仅{up_ratio:.0f}%，空头主导")

                if zt_approx > 50:
                    temp_score += 25
                    temp_reasons.append(f"🔥 涨停≈{zt_approx}只，投机情绪高涨")
                elif zt_approx > 20:
                    temp_score += 15
                    temp_reasons.append(f"✅ 涨停≈{zt_approx}只，正常偏强")
                else:
                    temp_score += 5
                    temp_reasons.append(f"❄️ 涨停≈{zt_approx}只，投机情绪低迷")

            if not fund_df.empty and "main_capital" in fund_df.columns:
                if fund_breadth > 55:
                    temp_score += 25
                    temp_reasons.append(f"💰 资金宽度{fund_breadth:.0f}%，资金面充裕")
                elif fund_breadth > 35:
                    temp_score += 15
                    temp_reasons.append(f"↔️ 资金宽度{fund_breadth:.0f}%，资金面一般")
                else:
                    temp_score += 5
                    temp_reasons.append(f"💸 资金宽度{fund_breadth:.0f}%，资金面紧张")

            temp_label = "🔥 高温" if temp_score >= 60 else ("🌤️ 温和" if temp_score >= 35 else "❄️ 低温")
            temp_color = "#E53935" if temp_score >= 60 else ("#FF9800" if temp_score >= 35 else "#4CAF50")

            col_temp1, col_temp2 = st.columns([1, 3])
            with col_temp1:
                st.markdown(f"<h1 style='text-align:center;color:{temp_color}'>{temp_label}</h1>",
                           unsafe_allow_html=True)
                st.caption(f"评分: {temp_score}/80")
            with col_temp2:
                for reason in temp_reasons:
                    st.write(reason)

            st.caption("💡 **市场宽度**通过全市场涨跌比例、资金流向分布、成交额集中度等指标综合判断市场温度。"
                      "宽度>65%上涨为普涨格局（适合追涨），<35%为普跌（适合防守）。"
                      "涨停数反映游资活跃度，资金宽度反映主力意愿。")
