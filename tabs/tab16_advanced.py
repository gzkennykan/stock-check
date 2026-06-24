"""Tab 16: 高级分析 — 多因子排名 + 行业轮动 + 相关性 + 批量回测 + 量化信号 + 资金流向 + 个股诊断"""
import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime

from data.database import get_latest_trading_date, get_stocks_in_db, get_stock_name_map
from data.factors import compute_composite_ranking
from data.correlation import (
    compute_full_correlation_matrix, find_low_correlation_pairs,
    find_hedge_pairs, compute_stock_distances, cluster_by_correlation,
)
from data.batch_backtest import run_sector_backtest, run_industry_backtest
from data.signals import (
    compute_market_breadth_history, detect_market_extremes,
    backtest_factor_returns,
)
from data.industry_db import (
    populate_stock_industry, get_industry_list_from_db,
    compute_industry_momentum, compute_industry_rotation_heatmap,
    build_industry_index, get_industry_stocks_from_db,
)

import plotly.graph_objects as go
from plotly.subplots import make_subplots


def _add_names(df: pd.DataFrame, sym_col: str = "symbol") -> pd.DataFrame:
    """给 DataFrame 添加股票名称列"""
    if sym_col not in df.columns:
        return df
    names = get_stock_name_map()
    df = df.copy()
    df["名称"] = df[sym_col].map(names).fillna("")
    # 把名称列放到代码列旁边
    cols = df.columns.tolist()
    if "名称" in cols and sym_col in cols:
        cols.remove("名称")
        idx = cols.index(sym_col)
        cols.insert(idx + 1, "名称")
        df = df[cols]
    return df


# ══════════════════════════════════════════════════
# Sub-tab 1: Multi-Factor Ranking
# ══════════════════════════════════════════════════

@st.cache_data(ttl=3600)
def _load_factors(end_date, weights):
    """缓存因子计算（交易日级别）"""
    w = {
        "momentum": weights.get("momentum", 0.30),
        "volatility": weights.get("volatility", 0.15),
        "volume": weights.get("volume", 0.20),
        "trend": weights.get("trend", 0.20),
        "drawdown": weights.get("drawdown", 0.15),
    }
    return compute_composite_ranking(end_date, weights=w)


def _render_factor_ranking():
    st.subheader("多因子选股排名")

    latest_date = get_latest_trading_date()
    if latest_date is None:
        st.info("数据库暂无数据")
        return

    st.caption(f"基于 {latest_date} 全市场 {get_stocks_in_db().shape[0]} 只股票综合评分")

    # 权重配置
    with st.expander("因子权重配置", expanded=False):
        c1, c2, c3, c4, c5 = st.columns(5)
        with c1:
            w_mom = st.slider("动量", 0.0, 1.0, 0.30, 0.05, key="w_mom")
        with c2:
            w_vol = st.slider("波动率", 0.0, 1.0, 0.15, 0.05, key="w_vol")
        with c3:
            w_vol_raw = st.slider("成交量", 0.0, 1.0, 0.20, 0.05, key="w_vol_raw")
        with c4:
            w_trend = st.slider("趋势", 0.0, 1.0, 0.20, 0.05, key="w_trend")
        with c5:
            w_dd = st.slider("回撤", 0.0, 1.0, 0.15, 0.05, key="w_dd")

    if st.button("🔍 运行多因子排名", type="primary", use_container_width=True,
                 key="run_factors"):
        st.cache_data.clear()
        with st.spinner("正在计算全市场因子得分（约 10 秒）..."):
            weights = {"momentum": w_mom, "volatility": w_vol, "volume": w_vol_raw,
                       "trend": w_trend, "drawdown": w_dd}
            df = _load_factors(latest_date, weights)
            st.session_state["factor_results"] = df

    if "factor_results" not in st.session_state:
        st.info("点击上方按钮运行多因子排名")
        return

    df = st.session_state["factor_results"]
    if df.empty:
        st.warning("暂无结果")
        return

    # 指标卡片
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("排行股票数", f"{len(df):,}")
    with c2:
        st.metric("最高分", f"{df['composite'].max():.0f}")
    with c3:
        st.metric("中位数", f"{df['composite'].median():.0f}")
    with c4:
        top10_pct = len(df[df["composite"] >= 90])
        st.metric("评分≥90", top10_pct)

    # 分数分布直方图
    fig = go.Figure(data=[go.Histogram(
        x=df["composite"], nbinsx=50,
        marker_color="#1E88E5", opacity=0.8,
    )])
    fig.update_layout(
        height=200, template="plotly_white",
        margin=dict(l=10, r=10, t=10, b=10),
        xaxis_title="综合得分", yaxis_title="股票数",
    )
    st.plotly_chart(fig, use_container_width=True, key="factor_dist")

    # Top 20 柱状图
    top20 = df.head(20).copy()
    names = get_stock_name_map()
    top20["label"] = top20["symbol"].apply(lambda s: f"{s} {names.get(s, '')}")
    fig_top = go.Figure(data=[go.Bar(
        x=top20["composite"].values,
        y=top20["label"].values,
        orientation="h",
        marker=dict(
            color=top20["composite"].values,
            colorscale="RdYlGn",
            showscale=False,
        ),
        text=top20["composite"].round(1).values,
        textposition="outside",
    )])
    fig_top.update_layout(
        height=400, template="plotly_white",
        margin=dict(l=10, r=50, t=10, b=10),
        yaxis=dict(autorange="reversed"),
    )
    st.plotly_chart(fig_top, use_container_width=True, key="factor_top20")

    # 完整排名表
    with st.expander(f"完整排名（{len(df)} 只）"):
        display = df.copy()
        names = get_stock_name_map()
        display["名称"] = display["symbol"].map(names).fillna("")
        display = display.rename(columns={
            "symbol": "代码", "rank": "排名", "composite": "综合分",
            "mom_score": "动量分", "mom_5d": "5日动量%", "mom_20d": "20日动量%",
            "vol_score": "波动率分", "vol_score_raw": "量能分", "vol5_ratio": "量比",
            "trend_score": "趋势分", "ma20_dist": "MA20偏离%",
            "dd_score": "回撤分", "max_dd_60d": "60日回撤%",
        })
        # 代码+名称排最前面
        cols = [c for c in display.columns]
        priority = ["代码", "名称"]
        ordered = [c for c in priority if c in cols] + [c for c in cols if c not in priority]
        display = display[ordered]
        st.dataframe(display, use_container_width=True, hide_index=True,
                     column_config={
                         "综合分": st.column_config.ProgressColumn(
                             min_value=0, max_value=100, format="%.0f", width="medium"),
                     })

    # 导出
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button("📥 导出 CSV", csv, f"factors_{latest_date}.csv",
                       "text/csv", key="dl_factors")


# ══════════════════════════════════════════════════
# ══════════════════════════════════════════════════
# Sub-tab 2: DB Industry Rotation
# ══════════════════════════════════════════════════

@st.cache_data(ttl=86400)
def _load_industries_db():
    return get_industry_list_from_db()


@st.cache_data(ttl=3600)
def _load_industry_momentum(end_date):
    return compute_industry_momentum(end_date)


@st.cache_data(ttl=3600)
def _load_industry_heatmap(end_date, weeks):
    return compute_industry_rotation_heatmap(end_date, weeks)


def _render_industry_rotation():
    st.subheader("行业轮动分析 (DB驱动)")
    st.caption("基于数据库内全部股票的申万行业分类，构建等权行业指数进行轮动分析")

    # 初始化行业数据
    industries = _load_industries_db()

    col_pop, col_info = st.columns([1, 3])
    with col_pop:
        if st.button("🔄 更新行业分类", use_container_width=True):
            with st.spinner("正在获取申万行业分类..."):
                result = populate_stock_industry()
                st.toast(f"已更新 {result.get('updated', 0)} 只股票行业信息")
                st.cache_data.clear()
            st.rerun()
    with col_info:
        if industries:
            st.caption(f"当前已分类行业: **{len(industries)}** 个")
        else:
            st.warning("尚未填充行业数据，请点击「更新行业分类」按钮")

    if not industries:
        return

    latest_date = get_latest_trading_date()

    # ── 行业动量排名 ──
    st.markdown("### 行业动量排名")
    st.caption(f"基于 {latest_date} 等权行业指数计算")

    if st.button("🔍 计算行业动量", key="run_ind_mom", use_container_width=True):
        st.cache_data.clear()
        with st.spinner("正在计算各行业动量（约 20 秒）..."):
            mom = _load_industry_momentum(latest_date)
            st.session_state["ind_momentum"] = mom

    if "ind_momentum" in st.session_state:
        mom = st.session_state["ind_momentum"]
        if not mom.empty:
            # Top/Bottom 5
            top5 = mom.head(5)
            bot5 = mom.tail(5)
            col_hot, col_cold = st.columns(2)
            with col_hot:
                st.markdown("##### 🔥 最强行业 TOP5")
                for _, r in top5.iterrows():
                    st.metric(
                        r["industry"],
                        f"{r['composite_momentum']:.0f}",
                        delta=f"20日: {r.get('ret_20d', 0):+.1f}%"
                    )
            with col_cold:
                st.markdown("##### ❄️ 最弱行业 BOTTOM5")
                for _, r in bot5.iterrows():
                    st.metric(
                        r["industry"],
                        f"{r['composite_momentum']:.0f}",
                        delta=f"20日: {r.get('ret_20d', 0):+.1f}%"
                    )

            # 柱状图
            plot_df = mom.head(30).copy()
            plot_df = plot_df.sort_values("composite_momentum", ascending=True)
            colors = ["#E53935" if v >= 50 else "#1E8E4A"
                      for v in plot_df["composite_momentum"]]
            fig = go.Figure(data=[go.Bar(
                x=plot_df["composite_momentum"].values,
                y=plot_df["industry"].values,
                orientation="h",
                marker_color=colors,
                text=plot_df["composite_momentum"].round(1).values,
                textposition="outside",
            )])
            fig.update_layout(
                height=600, template="plotly_white",
                margin=dict(l=20, r=50, t=10, b=10),
                xaxis_title="综合动量得分",
            )
            fig.add_vline(x=50, line_dash="dash", line_color="gray", opacity=0.5)
            st.plotly_chart(fig, use_container_width=True, key="ind_mom_chart")

            # 完整表格
            with st.expander(f"完整行业排名 ({len(mom)} 个)"):
                display = mom.rename(columns={
                    "industry": "行业", "rank": "排名",
                    "composite_momentum": "综合动量",
                    "ret_5d": "5日%", "ret_10d": "10日%",
                    "ret_20d": "20日%", "ret_60d": "60日%",
                })
                st.dataframe(display, use_container_width=True, hide_index=True)

    # ── 行业轮动热力图 ──
    st.markdown("---")
    st.markdown("### 行业轮动热力图")

    weeks = st.slider("回溯周数", 4, 26, 12, key="heatmap_weeks")

    if st.button("🔍 生成热力图", key="run_heatmap", use_container_width=True):
        st.cache_data.clear()
        with st.spinner("正在生成热力图（约 30 秒）..."):
            hm = _load_industry_heatmap(latest_date, weeks)
            st.session_state["ind_heatmap"] = hm

    if "ind_heatmap" in st.session_state:
        hm = st.session_state["ind_heatmap"]
        if not hm.empty:
            # 取动量最强的前 20 个行业显示
            if len(hm) > 20:
                # 按最新一周排序取 top20
                latest_col = hm.columns[-1]
                hm = hm.sort_values(latest_col, ascending=False).head(20)

            fig = go.Figure(data=[go.Heatmap(
                z=hm.values,
                x=hm.columns,
                y=hm.index,
                colorscale="RdYlGn",
                zmid=0,
                text=[[f"{v:+.1f}%" if not pd.isna(v) else "" for v in row]
                      for row in hm.values],
                texttemplate="%{text}",
                textfont={"size": 8},
            )])
            fig.update_layout(
                height=max(400, len(hm) * 20),
                template="plotly_white",
                margin=dict(l=20, r=20, t=10, b=10),
                xaxis_title="周结束日期",
                yaxis_title="行业",
            )
            st.plotly_chart(fig, use_container_width=True, key="ind_heatmap_chart")

    # ── 单行业深度分析 ──
    st.markdown("---")
    st.markdown("### 单行业深度分析")

    col_sel, col_btn = st.columns([3, 1])
    with col_sel:
        selected_ind = st.selectbox("选择行业", options=industries, key="ind_deep")
    with col_btn:
        go_btn = st.button("🔍 分析", use_container_width=True, key="ind_deep_btn")

    if go_btn:
        with st.spinner(f"构建「{selected_ind}」行业指数..."):
            end = latest_date
            start = (pd.to_datetime(end) - pd.Timedelta(days=365)).strftime("%Y-%m-%d")
            idx_df = build_industry_index(selected_ind, start, end)
            if not idx_df.empty:
                st.session_state["ind_deep_data"] = idx_df
                st.session_state["ind_deep_name"] = selected_ind
                stocks = get_industry_stocks_from_db(selected_ind)
                st.session_state["ind_deep_stocks"] = stocks
            else:
                st.warning(f"「{selected_ind}」无可用数据")

    if "ind_deep_data" in st.session_state:
        idx = st.session_state["ind_deep_data"]
        name = st.session_state.get("ind_deep_name", "")

        st.caption(f"「{name}」行业指数 — {idx['n_stocks'].iloc[-1]:.0f} 只成分股")

        # 收益率曲线
        close_norm = idx["close"] / idx["close"].iloc[0] * 100
        fig = go.Figure(data=[go.Scatter(
            x=close_norm.index, y=close_norm.values,
            mode="lines", name=name,
            line=dict(color="#1E88E5", width=2),
        )])
        fig.add_hline(y=100, line_dash="dash", line_color="gray", opacity=0.5)
        fig.update_layout(
            height=350, template="plotly_white",
            margin=dict(l=10, r=10, t=10, b=10),
            yaxis_title="基准=100",
            hovermode="x unified",
        )
        st.plotly_chart(fig, use_container_width=True, key="ind_deep_chart")

        # 成分股列表
        stocks = st.session_state.get("ind_deep_stocks", [])
        with st.expander(f"成分股 ({len(stocks)} 只)"):
            st.write(", ".join(stocks[:100]))


# ══════════════════════════════════════════════════
# ══════════════════════════════════════════════════
# Sub-tab 3: Enhanced Correlation Tools
# ══════════════════════════════════════════════════

def _render_correlation():
    st.subheader("🔗 相关性分析")

    latest_date = get_latest_trading_date()
    if latest_date is None:
        st.info("数据库暂无数据"); return

    # 选股
    db_stocks = get_stocks_in_db()
    if db_stocks.empty:
        st.info("数据库为空"); return

    symbols = db_stocks["symbol"].tolist()
    default_sym = ["600036", "000001", "600519", "300750", "002594"]

    c1, c2 = st.columns(2)
    with c1:
        sel = st.multiselect(
            "选择股票（建议5-20只）",
            options=symbols, default=[s for s in default_sym if s in symbols],
            max_selections=50, key="corr_stocks",
        )
    with c2:
        start = st.date_input("起始日期", value=datetime(2025, 1, 1), key="corr_start")
        end = st.date_input("结束日期", value=datetime.today(), key="corr_end")

    if len(sel) < 2:
        st.info("请至少选择2只股票")
        return

    if st.button("🔍 计算相关性", use_container_width=True, key="corr_run"):
        with st.spinner("计算中..."):
            corr = compute_full_correlation_matrix(sel, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
            st.session_state["corr_matrix"] = corr

    if "corr_matrix" not in st.session_state:
        return

    corr = st.session_state["corr_matrix"]
    if corr.empty:
        st.warning("无法计算"); return

    # 热力图
    fig = go.Figure(data=[go.Heatmap(
        z=corr.values, x=corr.columns.tolist(), y=corr.index.tolist(),
        colorscale="RdYlGn", zmin=-1, zmax=1,
        text=[[f"{v:.3f}" for v in row] for row in corr.values],
        texttemplate="%{text}", textfont={"size": 9},
    )])
    fig.update_layout(height=max(350, len(corr) * 30), template="plotly_white",
                      margin=dict(l=20, r=20, t=10, b=10))
    st.plotly_chart(fig, use_container_width=True, key="corr_heatmap")

    # 低相关对 & 对冲对
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**低相关对（最优组合）**")
        low = find_low_correlation_pairs(corr, 10)
        if not low.empty:
            st.dataframe(low.rename(columns={"stock_a": "A", "stock_b": "B", "correlation": "相关度"}),
                         use_container_width=True, hide_index=True)
    with col_b:
        st.markdown("**对冲对（负相关>0.3）**")
        hedge = find_hedge_pairs(corr, 10)
        if not hedge.empty:
            st.dataframe(hedge.rename(columns={"stock_a": "A", "stock_b": "B", "correlation": "负相关"}),
                         use_container_width=True, hide_index=True)

    # 聚类
    if len(corr) >= 5:
        st.markdown("**相关性聚类**")
        clusters = cluster_by_correlation(corr, n_clusters=min(5, len(corr)))
        if not clusters.empty:
            for cid in sorted(clusters["cluster"].unique()):
                members = clusters[clusters["cluster"] == cid]["symbol"].tolist()
                st.caption(f"Cluster {cid}: {', '.join(members)}")


# ══════════════════════════════════════════════════
# Sub-tab 7: Batch Backtest
# ══════════════════════════════════════════════════

def _render_batch_backtest():
    st.subheader("🚀 批量回测")

    from strategies import MACrossStrategy, MACDStrategy, RSIStrategy, BollingerStrategy

    strategies_db = {
        "双均线 (MA Cross)": MACrossStrategy,
        "MACD": MACDStrategy,
        "RSI 超买超卖": RSIStrategy,
        "布林带 (Bollinger)": BollingerStrategy,
    }

    industries = get_industry_list_from_db()
    if not industries:
        st.warning("请先在「🔄 行业轮动」更新行业分类")
        return

    c1, c2, c3 = st.columns(3)
    with c1:
        strat_name = st.selectbox("回测策略", list(strategies_db.keys()), key="bb_strat")
    with c2:
        ind = st.selectbox("行业板块", industries, key="bb_ind")
    with c3:
        max_n = st.slider("最大股票数", 5, 100, 30, 5, key="bb_max")

    col_s, col_e = st.columns(2)
    with col_s:
        start = st.date_input("起始", datetime(2024, 1, 1), key="bb_start")
    with col_e:
        end = st.date_input("结束", datetime.today(), key="bb_end")

    if st.button("🚀 运行批量回测", type="primary", use_container_width=True, key="bb_run"):
        cls = strategies_db[strat_name]
        params = {}
        if strat_name == "双均线 (MA Cross)":
            params = {"fast_period": 5, "slow_period": 20}
        elif strat_name == "MACD":
            params = {"fast_period": 12, "slow_period": 26, "signal_period": 9}
        elif strat_name == "RSI 超买超卖":
            params = {"rsi_period": 14, "oversold": 30, "overbought": 70}
        elif strat_name == "布林带 (Bollinger)":
            params = {"period": 20, "devfactor": 2.0}
        params.update({"stop_loss": 0.05, "take_profit": 0.15, "position_pct": 0.95})

        with st.spinner(f"回测「{ind}」成分股（最多 {max_n} 只）..."):
            result = run_industry_backtest(
                cls, ind, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"),
                params, max_stocks=max_n,
            )
            st.session_state["bb_result"] = result

    if "bb_result" not in st.session_state:
        return

    r = st.session_state["bb_result"]
    if r.empty:
        st.warning("无双结果"); return

    # 摘要
    c1, c2, c3, c4 = st.columns(4)
    with c1: st.metric("回测股票数", len(r))
    with c2: st.metric("平均收益", f"{r['total_return'].mean():+.1f}%")
    with c3: st.metric("胜率>0比例", f"{(r['total_return'] > 0).sum() / len(r) * 100:.0f}%")
    with c4: st.metric("最佳回报", f"{r['total_return'].max():+.1f}%")

    # 柱状图
    top20 = r.head(20).copy()
    names = get_stock_name_map()
    top20["label"] = top20["symbol"].apply(lambda s: f"{s} {names.get(s, '')}")
    colors_r = ["#E53935" if v >= 0 else "#1E8E4A" for v in top20["total_return"]]
    fig = go.Figure(data=[go.Bar(
        x=top20["total_return"].values, y=top20["label"].values, orientation="h",
        marker_color=colors_r,
        text=[f"{v:+.1f}%" for v in top20["total_return"].values],
        textposition="outside",
    )])
    fig.add_vline(x=0, line_dash="dash", line_color="gray", opacity=0.5)
    fig.update_layout(height=400, template="plotly_white", margin=dict(l=20, r=50, t=10, b=10))
    st.plotly_chart(fig, use_container_width=True, key="bb_chart")

    display = _add_names(r)
    display = display.rename(columns={
        "symbol": "代码", "rank": "排名", "total_return": "总收益%",
        "sharpe": "夏普", "max_dd": "最大回撤%", "win_rate": "胜率%", "trades": "交易数",
    })
    st.dataframe(display, use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════
# Sub-tab 8: Quantitative Signals
# ══════════════════════════════════════════════════

@st.cache_data(ttl=3600)
def _load_breadth(date):
    return compute_market_breadth_history(date, lookback_days=500)


def _render_quant_signals():
    st.subheader("📡 量化信号")

    latest_date = get_latest_trading_date()
    if latest_date is None:
        st.info("数据库暂无数据"); return

    # ── Part A: 市场择时信号 ──
    st.markdown("### 市场择时信号")

    if st.button("🔍 计算市场宽度", use_container_width=True, key="breadth_run"):
        st.cache_data.clear()
        with st.spinner("计算中（~1秒）..."):
            st.session_state["breadth_data"] = _load_breadth(latest_date)

    if "breadth_data" in st.session_state:
        bd = st.session_state["breadth_data"]
        if not bd.empty:
            # 当前指标
            last = bd.iloc[-1]
            c1, c2, c3, c4 = st.columns(4)
            with c1: st.metric("60日均线上方%", f"{last['breadth_ma60']:.0f}%")
            with c2: st.metric("20日均线上方%", f"{last['breadth_ma20']:.0f}%")
            with c3: st.metric("涨跌比", f"{last['adv_ratio']:.2f}")
            with c4:
                sig_val = last["signal"]
                label = "🟢 底部区域" if sig_val < 25 else ("🔴 顶部区域" if sig_val > 75 else "↔️ 中性")
                st.metric("市场信号", f"{sig_val:.0f}", delta=label)

            # 信号历史曲线
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=bd.index, y=bd["signal"], mode="lines",
                name="信号", line=dict(color="#1E88E5", width=2),
            ))
            fig.add_hline(y=75, line_dash="dash", line_color="#E53935", opacity=0.5, annotation_text="顶部")
            fig.add_hline(y=25, line_dash="dash", line_color="#4CAF50", opacity=0.5, annotation_text="底部")
            fig.update_layout(height=300, template="plotly_white",
                              margin=dict(l=10, r=10, t=10, b=10),
                              yaxis_range=[0, 100], yaxis_title="择时信号")
            st.plotly_chart(fig, use_container_width=True, key="breadth_chart")

            # 顶底事件
            events = detect_market_extremes(bd)
            if not events.empty:
                with st.expander(f"近期顶底信号 ({len(events)} 次)"):
                    st.dataframe(events, use_container_width=True, hide_index=True)

    st.markdown("---")

    # ── Part B: 因子有效性回测 ──
    st.markdown("### 因子有效性验证")

    if st.button("🔍 验证因子有效性", use_container_width=True, key="btn_factor_bt"):
        with st.spinner("计算因子分组收益（约5秒）..."):
            fbt = backtest_factor_returns("composite", latest_date)
            st.session_state["factor_backtest_result"] = fbt

    if "factor_backtest_result" in st.session_state:
        fbt = st.session_state["factor_backtest_result"]
        if isinstance(fbt, pd.DataFrame) and not fbt.empty:
            st.caption("按综合评分分三组（Top 33% / Mid / Bottom 33%），对比未来收益")
            display = fbt.rename(columns={
                "period": "周期", "top": "高分组%", "bottom": "低分组%",
                "spread": "超额收益%", "factor_valid": "有效",
            })
            st.dataframe(display, use_container_width=True, hide_index=True)
            valid_count = fbt["factor_valid"].sum() if "factor_valid" in fbt.columns else 0
            if valid_count > 0:
                st.success(f"因子在 {valid_count}/{len(fbt)} 个周期有效（高分组合>低分组）")


# ══════════════════════════════════════════════════
# Main Render
# ══════════════════════════════════════════════════
# Sub-tab 9: Individual Stock Fund Flow Analysis
# ══════════════════════════════════════════════════

def _render_fund_flow():
    st.subheader("💰 个股资金流向分析")
    st.caption("同花顺数据 → 本地 DuckDB 快照（每次启动自动抓取当日全市场排名，日积月累形成历史）")

    from data.fund_flow import get_individual_fund_flow, get_fund_flow_summary
    from data.database import get_fund_flow_latest_date

    latest_snapshot = get_fund_flow_latest_date()
    if latest_snapshot:
        st.caption(f"📸 最新快照日期: {latest_snapshot}")

    col_a, col_b, col_c = st.columns([2, 2, 2])
    with col_a:
        code = st.text_input("股票代码", value="600585", key="ff_code",
                             placeholder="如 600585", max_chars=6).strip()
    with col_b:
        days = st.selectbox("统计天数", [5, 10, 20, 30, 60], index=1, key="ff_days")
    with col_c:
        st.write("")
        st.write("")
        refresh = st.button("🔄 查询", use_container_width=True, key="ff_refresh")

    if not code or len(code) < 6:
        st.info("请输入6位股票代码查询个股资金流向（数据源: 同花顺）")
        return

    if not refresh and f"_ff_data_{code}" in st.session_state:
        df = st.session_state[f"_ff_data_{code}"]
        summary = st.session_state.get(f"_ff_summary_{code}")
    else:
        with st.spinner(f"从本地数据库读取 {code} 资金流向历史..."):
            df = get_individual_fund_flow(code, force_refresh=refresh)
            if df is not None and not df.empty:
                summary = get_fund_flow_summary(code, days=days)
            else:
                summary = None
        st.session_state[f"_ff_data_{code}"] = df
        st.session_state[f"_ff_summary_{code}"] = summary
        st.session_state["symbol"] = code

    if df is None or df.empty:
        st.warning(
            f"📭 本地数据库中暂无 {code} 的资金流数据。"
            f"\n\n**原因**: 资金流历史通过每日自动快照积累。"
            f"\n- 如果今天是第一次使用此功能，数据从今天开始记录。"
            f"\n- 东方财富 API 已不可用，改用同花顺源本地缓存。"
            f"\n- 历史越长分析越有价值，请持续使用。"
        )
        return

    # ── DB 列适配：统一命名 ──
    if "main_net" in df.columns and "主力净额" not in df.columns:
        df["主力净额"] = df["main_net"]
    if "price" in df.columns and "close" not in df.columns:
        df["close"] = df["price"]
    if "date" not in df.columns and "trade_date" in df.columns:
        df["date"] = df["trade_date"]

    # ── Part A: 统计摘要 ──
    st.markdown("### 📊 近{}日资金流统计".format(days))

    if summary:
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        today_net = summary["today_main_net_yi"]
        with c1:
            st.metric("最新收盘", f"{summary['close']:.2f}",
                      delta=f"{summary['pct_change']:+.2f}%")
        with c2:
            st.metric("今日净额", f"{today_net:+.4f}亿")
        with c3:
            st.metric("均值", f"{summary['mean']:+.4f}亿")
        with c4:
            st.metric("中位数", f"{summary['median']:+.4f}亿")
        with c5:
            st.metric("最小值", f"{summary['min']:+.4f}亿")
        with c6:
            st.metric("最大值", f"{summary['max']:+.4f}亿")

        # 判断今日 vs 历史
        if abs(today_net) > 0 and abs(summary['mean']) > 0.001:
            ratio = abs(today_net / summary['mean']) if summary['mean'] != 0 else 0
            if ratio > 2:
                direction = "流入" if today_net > 0 else "流出"
                st.warning(f"⚠️ 今日资金{direction}异常：为近{days}日均值的 {ratio:.1f} 倍")

    # ── Part B: 明细表 ──
    st.divider()
    st.markdown("### 📋 近{}日资金流明细".format(days))

    recent = df.tail(days).copy()
    if not recent.empty:
        tbl_cols = ["date", "close", "pct_change", "主力净额"]
        if "capital_inflow" in recent.columns:
            tbl_cols.append("capital_inflow")
        if "capital_outflow" in recent.columns:
            tbl_cols.append("capital_outflow")
        if "turnover" in recent.columns:
            tbl_cols.append("turnover")
        if "turnover_rate" in recent.columns:
            tbl_cols.append("turnover_rate")
        tbl_cols = [c for c in tbl_cols if c in recent.columns]
        tbl = recent[tbl_cols].copy()
        tbl = tbl.sort_values("date", ascending=False)

        for c in ["主力净额", "capital_inflow", "capital_outflow", "turnover"]:
            if c in tbl.columns:
                tbl[c] = (tbl[c] / 1e8).round(4)

        tbl["date"] = tbl["date"].dt.strftime("%m/%d")
        tbl["close"] = tbl["close"].round(2)
        tbl["pct_change"] = tbl["pct_change"].round(2)
        if "turnover_rate" in tbl.columns:
            tbl["turnover_rate"] = tbl["turnover_rate"].round(2)

        tbl = tbl.rename(columns={
            "date": "日期", "close": "收盘价", "pct_change": "涨跌幅(%)",
            "主力净额": "净额(亿)", "capital_inflow": "流入(亿)",
            "capital_outflow": "流出(亿)", "turnover": "成交额(亿)",
            "turnover_rate": "换手率(%)",
        })

        st.dataframe(
            tbl, use_container_width=True, hide_index=True,
            column_config={
                "涨跌幅(%)": st.column_config.NumberColumn(format="%+.2f%%"),
            },
        )

    # ── Part C: 资金流 vs 收盘价 双轴图 ──
    st.divider()
    st.markdown("### 📈 资金净额 vs 收盘价（近32日）")

    chart_data = df.tail(32).copy()
    if not chart_data.empty:
        net_col = "主力净额"
        close_col = "close"
        if net_col not in chart_data.columns:
            net_col = "main_net"

        fig = make_subplots(specs=[[{"secondary_y": True}]])

        net_vals = chart_data[net_col] / 1e8
        colors = ["#ef5350" if v < 0 else "#26a69a" for v in net_vals]
        fig.add_trace(
            go.Bar(
                x=chart_data["date"], y=net_vals,
                name="资金净额(亿)", marker_color=colors,
                opacity=0.85,
            ),
            secondary_y=False,
        )

        fig.add_trace(
            go.Scatter(
                x=chart_data["date"], y=chart_data[close_col],
                name="收盘价(元)", mode="lines+markers",
                line=dict(color="#2196F3", width=2),
                marker=dict(size=4),
            ),
            secondary_y=True,
        )

        fig.update_layout(
            title="资金净额 vs 收盘价",
            hovermode="x unified",
            height=420,
            legend=dict(orientation="h", yanchor="bottom", y=-0.25, xanchor="center", x=0.5),
            margin=dict(l=40, r=40, t=50, b=60),
        )
        fig.update_yaxes(title_text="资金净额(亿元)", secondary_y=False)
        fig.update_yaxes(title_text="收盘价(元)", secondary_y=True)

        st.plotly_chart(fig, use_container_width=True)

        # 辅助判断
        last_5 = chart_data.tail(5)
        price_up = last_5[close_col].iloc[-1] > last_5[close_col].iloc[0]
        fund_in = last_5[net_col].sum()
        if price_up and fund_in < 0:
            st.warning("⚠️ 近5日：股价上涨但资金净流出 → 量价背离，注意风险")
        elif not price_up and fund_in > 0:
            st.info("💡 近5日：股价下跌但资金净流入 → 可能为吸筹")


# ══════════════════════════════════════════════════
# Sub-tab 10: Integrated Stock Diagnostics
# ══════════════════════════════════════════════════

def _render_stock_diagnosis():
    st.subheader("🔬 个股综合诊断")
    st.caption("技术面 + 资金面 + 基本面 + 触发条件 — 四维闭环验证")

    from data.technicals import compute_full_analysis
    from data.fund_flow import get_fund_flow_summary, get_individual_fund_flow
    from data.database import get_fund_flow_latest_date

    col_a, col_b = st.columns([2, 3])
    with col_a:
        code = st.text_input("股票代码", value="600585", key="diag_code",
                             placeholder="如 600585", max_chars=6).strip()
    with col_b:
        st.write("")
        st.write("")
        if st.button("🔍 开始诊断", use_container_width=True, key="diag_run"):
            st.session_state["run_diag"] = True

    if not code or len(code) < 6:
        st.info("请输入6位股票代码，启动综合诊断")
        return

    if not st.session_state.get("run_diag") and f"_diag_{code}" not in st.session_state:
        st.info("👆 点击「开始诊断」运行四维分析")
        # Show quick entry for convenience
        if st.button("🚀 快速诊断", key="diag_quick"):
            st.session_state["run_diag"] = True
            st.rerun()
        return

    # ── 检查缓存 ──
    if st.session_state.get("run_diag") or f"_diag_{code}" not in st.session_state:
        with st.spinner(f"正在对 {code} 进行四维诊断分析..."):
            tech = compute_full_analysis(code)
            ff_summary = get_fund_flow_summary(code, days=20)
            ff_df = get_individual_fund_flow(code)
        st.session_state[f"_diag_{code}"] = {
            "tech": tech,
            "ff_summary": ff_summary,
            "ff_df": ff_df,
        }
        st.session_state["run_diag"] = False
        st.session_state["symbol"] = code

    diag = st.session_state[f"_diag_{code}"]
    tech = diag.get("tech", {})
    ff_summary = diag.get("ff_summary")
    ff_df = diag.get("ff_df")

    if tech.get("error"):
        st.warning(tech["error"])
        return

    # ═══════════════════════════════
    # Part A: 核心指标卡片
    # ═══════════════════════════════
    st.markdown("### 📊 技术面核心指标")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1:
        st.metric("最新收盘", f"{tech['close']:.2f}")
    with c2:
        st.metric("近20日收益", f"{tech.get('ret_20d', 0):+.2f}%")
    with c3:
        st.metric("近60日收益", f"{tech.get('ret_60d', 0):+.2f}%")
    with c4:
        st.metric("近120日收益", f"{tech.get('ret_120d', 0):+.2f}%")
    with c5:
        st.metric("60日年化波动", f"{tech.get('vol_60d_annual', 0):.1f}%")
    with c6:
        rsi = tech.get("rsi14", 50)
        rsi_color = "normal" if 30 <= rsi <= 70 else "off"
        st.metric("RSI(14)", f"{rsi:.1f}", delta="超卖" if rsi < 30 else ("超买" if rsi > 70 else None))

    # ── MACD ──
    st.caption(
        f"MACD: {tech.get('macd', 0):.4f}  |  "
        f"Signal: {tech.get('macd_signal', 0):.4f}  |  "
        f"柱: {tech.get('macd_hist', 0):+.4f}  "
        f"({'🟢 多头' if (tech.get('macd_hist', 0) or 0) > 0 else '🔴 空头'})"
    )

    # ── 均线结构 ──
    st.divider()
    st.markdown("### 📐 均线 & 关键位")
    trend = tech.get("trend", {})
    c_ma1, c_ma2, c_ma3 = st.columns(3)
    for i, (n, col) in enumerate([(20, c_ma1), (60, c_ma2), (120, c_ma3)]):
        ma_val = trend.get(f"ma{n}_val")
        vs = trend.get(f"vs_ma{n}", "无数据")
        with col:
            color = "#26a69a" if vs == "上方" else "#ef5350"
            ma_str = f"¥{ma_val:.2f}" if ma_val else "N/A"
            st.metric(f"MA{n} ({ma_str})", f"价格在{vs}", delta_color="normal")

    # 关键位
    lv_cols = st.columns(2)
    with lv_cols[0]:
        st.caption(
            f"**近20日区间**: {tech.get('level_20d_low', 0):.2f} – {tech.get('level_20d_high', 0):.2f}"
        )
    with lv_cols[1]:
        st.caption(
            f"**近60日区间**: {tech.get('level_60d_low', 0):.2f} – {tech.get('level_60d_high', 0):.2f}"
        )

    # ═══════════════════════════════
    # Part B: 资金面
    # ═══════════════════════════════
    st.divider()
    st.markdown("### 💰 资金面")

    if ff_summary:
        today_net = ff_summary["today_main_net_yi"]
        ff_c1, ff_c2, ff_c3 = st.columns(3)
        with ff_c1:
            st.metric("今日净额", f"{today_net:+.4f}亿")
        with ff_c2:
            st.metric("近20日均值", f"{ff_summary['mean']:+.4f}亿")
        with ff_c3:
            # 计算近20日累计
            recent_total = sum(d["main_net_yi"] for d in ff_summary.get("recent_days", []))
            st.metric("近20日累计", f"{recent_total:+.2f}亿",
                      delta="净流出" if recent_total < 0 else "净流入")
    else:
        st.caption("暂无资金流数据（需每日使用以积累历史）")

    # ═══════════════════════════════
    # Part C: 图表区
    # ═══════════════════════════════
    st.divider()

    chart_t1, chart_t2 = st.tabs(["📈 K线+均线", "💹 资金流+MACD"])

    with chart_t1:
        df_tech = tech.get("df")
        if df_tech is not None and not df_tech.empty:
            recent = df_tech.tail(120)
            fig_kl = go.Figure()
            fig_kl.add_trace(go.Candlestick(
                x=recent.index, open=recent["open"], high=recent["high"],
                low=recent["low"], close=recent["close"], name="K线"
            ))
            for n, color in [(20, "#1f77b4"), (60, "#ff7f0e"), (120, "#2ca02c")]:
                col_name = f"ma{n}"
                if col_name in recent.columns:
                    fig_kl.add_trace(go.Scatter(
                        x=recent.index, y=recent[col_name],
                        mode="lines", name=f"MA{n}",
                        line=dict(width=1, color=color)
                    ))
            fig_kl.update_layout(
                title="K线 + 均线 (MA20/60/120)", height=450,
                xaxis_title="日期", yaxis_title="价格(元)",
                legend=dict(orientation="h", yanchor="bottom", y=-0.3, xanchor="center", x=0.5),
                margin=dict(l=40, r=20, t=50, b=70),
            )
            st.plotly_chart(fig_kl, use_container_width=True)

    with chart_t2:
        if df_tech is not None and not df_tech.empty:
            recent = df_tech.tail(120)
            fig_combo = make_subplots(
                rows=2, cols=1, shared_xaxes=True,
                row_heights=[0.5, 0.5],
                vertical_spacing=0.08,
            )

            # 上: 资金流柱状图
            if ff_df is not None and not ff_df.empty:
                # align dates
                ff_df_idx = ff_df.set_index("date") if "date" in ff_df.columns else ff_df.set_index("trade_date")
                net_col = "main_net" if "main_net" in ff_df_idx.columns else "主力净额"
                if net_col in ff_df_idx.columns:
                    common = recent.index.intersection(ff_df_idx.index)
                    if len(common) > 0:
                        ff_aligned = ff_df_idx.loc[common]
                        net_vals = ff_aligned[net_col] / 1e8
                        colors = ["#ef5350" if v < 0 else "#26a69a" for v in net_vals]
                        fig_combo.add_trace(
                            go.Bar(x=ff_aligned.index, y=net_vals, name="净额(亿)",
                                   marker_color=colors, opacity=0.85),
                            row=1, col=1,
                        )

            fig_combo.update_yaxes(title_text="净额(亿元)", row=1, col=1)

            # 下: MACD
            if "macd" in recent.columns and "macd_signal" in recent.columns:
                fig_combo.add_trace(
                    go.Scatter(x=recent.index, y=recent["macd"], name="MACD",
                               line=dict(color="#1f77b4", width=1.5)), row=2, col=1)
                fig_combo.add_trace(
                    go.Scatter(x=recent.index, y=recent["macd_signal"], name="Signal",
                               line=dict(color="#ff7f0e", width=1)), row=2, col=1)
                # hist as bar
                hist_colors = ["#ef5350" if v < 0 else "#26a69a" for v in recent["macd_hist"].fillna(0)]
                fig_combo.add_trace(
                    go.Bar(x=recent.index, y=recent["macd_hist"], name="Hist",
                           marker_color=hist_colors, opacity=0.6), row=2, col=1)

            fig_combo.update_layout(
                title="资金净额 + MACD", height=450,
                hovermode="x unified",
                legend=dict(orientation="h", yanchor="bottom", y=-0.25, xanchor="center", x=0.5),
                margin=dict(l=40, r=20, t=50, b=70),
            )
            st.plotly_chart(fig_combo, use_container_width=True)

    # ═══════════════════════════════
    # Part D: 基本面快照（从 AKShare）
    # ═══════════════════════════════
    st.divider()
    st.markdown("### 📋 基本面快照")

    try:
        from data.fetcher import _fetch_akshare_sina
        import akshare as ak
        fin_df = ak.stock_financial_abstract_ths(symbol=code, indicator="按报告期")
        if fin_df is not None and not fin_df.empty:
            latest = fin_df.iloc[-1]
            latest_date = fin_df.index[-1] if hasattr(fin_df.index, '__getitem__') else "最新"

            # 动态取列
            fin_cols_map = {}
            for c in fin_df.columns:
                if "营业总收入" in c:
                    fin_cols_map["营收"] = c
                elif "净利润" in c and "归" in c:
                    fin_cols_map["归母净利润"] = c
                elif "净资产收益率" in c:
                    fin_cols_map["ROE"] = c
                elif "资产负债率" in c:
                    fin_cols_map["负债率"] = c
                elif "毛利率" in c:
                    fin_cols_map["毛利率"] = c

            if fin_cols_map:
                fi_c1, fi_c2, fi_c3, fi_c4, fi_c5 = st.columns(5)
                for i, (label, col_name) in enumerate(fin_cols_map.items()):
                    val = latest[col_name]
                    formatted = f"{float(val)/1e8:.2f}亿" if "收入" in label or "利润" in label else f"{float(val):.2f}%"
                    with [fi_c1, fi_c2, fi_c3, fi_c4, fi_c5][i]:
                        st.metric(label, formatted)
            else:
                st.caption("基本面数据列名不匹配，请升级 AKShare")
        else:
            st.caption("⚠️ 同花顺基本面接口返回空（可能非交易时段）")
    except Exception as e:
        st.caption(f"基本面数据获取失败: {str(e)[:60]}")

    # ═══════════════════════════════
    # Part E: 触发条件检查
    # ═══════════════════════════════
    st.divider()
    st.markdown("### 🎯 可执行观察清单（触发条件）")

    vs_ma20 = trend.get("vs_ma20", "无数据")
    close = tech.get("close", 0)
    ma20 = trend.get("ma20_val") or 0
    ret_20 = tech.get("ret_20d") or 0
    rsi = tech.get("rsi14") or 50
    macd_hist = tech.get("macd_hist") or 0

    # 条件1: 价格站上MA20
    cond1 = vs_ma20 == "上方"
    c1_icon = "✅" if cond1 else "❌"
    c1_text = f"价格站上 MA20（约 ¥{ma20:.2f}）" if cond1 else f"价格跌破 MA20（约 ¥{ma20:.2f}），距 MA20 差 ¥{close - ma20:.2f}"

    # 条件2: 资金面转正
    recent_total = 0
    if ff_summary:
        recent_total = sum(d["main_net_yi"] for d in ff_summary.get("recent_days", []))
    cond2 = recent_total > 0
    c2_icon = "✅" if cond2 else "❌"
    c2_text = f"近20日主力累计净流入 +{recent_total:.2f}亿" if cond2 else f"近20日主力累计净流出 {recent_total:.2f}亿"

    # 条件3: 技术面改善
    cond3 = ret_20 > -5 and macd_hist > -0.01 and rsi > 30
    c3_icon = "✅" if cond3 else "⚠️"
    c3_text = "近20日跌幅<5%, MACD未持续恶化, RSI>30" if cond3 else f"技术面偏弱：20日收益{ret_20:+.1f}%, MACD柱{macd_hist:+.4f}, RSI={rsi:.1f}"

    # ── 综合判断 ──
    met = sum([cond1, cond2, cond3])
    if met == 3:
        st.success(f"### {c1_icon} {c2_icon} {c3_icon}  综合评级: 🟢 可趋势关注")
        st.caption("三个条件全部满足，技术面+资金面+动量共振向上。")
    elif met >= 1:
        st.warning(f"### {c1_icon} {c2_icon} {c3_icon}  综合评级: 🟡 继续观察")
        st.caption(f"满足 {met}/3 个条件。需更多信号确认趋势转换。")
    else:
        st.error(f"### {c1_icon} {c2_icon} {c3_icon}  综合评级: 🔴 弱势 — 暂不建议")
        st.caption("三个条件均不满足。价格弱势+资金流出+技术恶化，反弹多为减仓窗口。")

    # 详细条件列表
    st.markdown(f"""
    | 条件 | 状态 | 说明 |
    |------|:----:|------|
    | ① 价格条件：收盘站上 MA20 | {c1_icon} | {c1_text} |
    | ② 资金条件：主力净流入转正 | {c2_icon} | {c2_text} |
    | ③ 技术条件：动量改善 | {c3_icon} | {c3_text} |
    """)

    st.caption("💡 方法论来源: 同花顺 AI 四维闭环分析框架（技术面→资金面→基本面→触发条件）")


# ══════════════════════════════════════════════════

def render():
    st.title("📊 高级分析")
    st.caption("DuckDB 驱动 — 综合诊断 · 多因子 · 形态 · 异动 · 行业轮动 · 蜡烛 · 相关性 · 批量回测 · 量化信号 · 资金流向")

    sub1, sub2, sub3, sub4, sub5, sub6, sub7 = st.tabs([
        "🔬 个股诊断",
        "🎯 多因子排名",
        "🔄 行业轮动",
        "🔗 相关性",
        "🚀 批量回测",
        "📡 量化信号",
        "💰 资金流向",
    ])

    with sub1: _render_stock_diagnosis()
    with sub2: _render_factor_ranking()
    with sub3: _render_industry_rotation()
    with sub4: _render_correlation()
    with sub5: _render_batch_backtest()
    with sub6: _render_quant_signals()
    with sub7: _render_fund_flow()

    st.caption("💡 形态扫描、异动检测、K线形态已整合至「📋 选股工作流」中，提供更完整的选股体验")
