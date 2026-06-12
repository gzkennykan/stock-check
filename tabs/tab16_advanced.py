"""Tab 16: 高级分析 — 多因子排名 + 形态扫描 + 异动检测 + 行业轮动 + K线形态 + 相关性 + 批量回测 + 量化信号"""
import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime

from data.database import get_latest_trading_date, get_stocks_in_db, get_stock_name_map
from data.factors import compute_composite_ranking
from data.patterns import run_all_patterns
from data.anomaly import run_all_anomalies
from data.candlestick import scan_all_candlestick_patterns
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
# Sub-tab 2: Pattern Scanning
# ══════════════════════════════════════════════════

@st.cache_data(ttl=1800)
def _load_patterns(end_date, params):
    return run_all_patterns(end_date, **params)


def _render_pattern_scanning():
    st.subheader("技术形态全市场扫描")

    latest_date = get_latest_trading_date()
    if latest_date is None:
        st.info("数据库暂无数据")
        return

    st.caption(f"扫描日期: {latest_date}")

    with st.expander("扫描参数", expanded=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            gc_days = st.slider("金叉/死叉 回溯天数", 3, 30, 10, key="gc_days")
            n_days = st.slider("新高/新低 N日", 20, 250, 60, 10, key="n_days")
        with c2:
            consol_th = st.slider("均线粘合 阈值(%)", 1.0, 8.0, 3.0, 0.5, key="consol_th")
        with c3:
            vol_mult = st.slider("放量突破 量比", 1.5, 5.0, 2.0, 0.5, key="vol_mult")

        patterns_enabled = st.multiselect(
            "启用形态类型（留空=全部）",
            options=["金叉", "死叉", "均线粘合", "放量突破", "N日新高", "N日新低"],
            default=[],
            key="patterns_enabled",
        )

    if st.button("🔍 扫描全市场形态", type="primary", use_container_width=True,
                 key="run_patterns"):
        st.cache_data.clear()
        with st.spinner("正在扫描技术形态（约 5 秒）..."):
            params = {
                "golden_cross_days": gc_days,
                "death_cross_days": gc_days,
                "consolidation_threshold": consol_th,
                "volume_multiplier": vol_mult,
                "n_days": n_days,
            }
            results = _load_patterns(latest_date, params)
            st.session_state["pattern_results"] = results

    if "pattern_results" not in st.session_state:
        st.info("点击上方按钮开始扫描")
        return

    results = st.session_state["pattern_results"]
    if not results:
        st.warning("未发现任何形态信号")
        return

    # 统计卡片
    cols = st.columns(len(results))
    for i, (name, df) in enumerate(results.items()):
        with cols[i]:
            st.metric(name, len(df))

    # 逐类展示
    for name, df in results.items():
        if patterns_enabled and name not in patterns_enabled:
            continue
        with st.expander(f"{name} ({len(df)} 只)", expanded=len(df) < 50):
            display = _add_names(df)
            display = display.rename(columns={
                "symbol": "代码", "cross_date": "交叉日期",
                "close": "收盘价", "ma5_val": "MA5", "ma20_val": "MA20",
                "spread_pct": "偏离度%",
            })
            st.dataframe(display, use_container_width=True, hide_index=True)

        # 导出
        if len(df) > 0:
            csv = df.to_csv(index=False).encode("utf-8")
            safe_name = name.replace("/", "_")
            st.download_button(
                f"📥 导出 {name}", csv,
                f"{safe_name}_{latest_date}.csv",
                "text/csv", key=f"dl_{safe_name}"
            )


# ══════════════════════════════════════════════════
# Sub-tab 3: Anomaly Detection
# ══════════════════════════════════════════════════

@st.cache_data(ttl=1800)
def _load_anomalies(end_date, params):
    return run_all_anomalies(end_date, **params)


def _render_anomaly_detection():
    st.subheader("每日异动检测")

    latest_date = get_latest_trading_date()
    if latest_date is None:
        st.info("数据库暂无数据")
        return

    st.caption(f"检测日期: {latest_date}")

    with st.expander("检测参数", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            gap_th = st.slider("跳空阈值 (%)", 1.0, 10.0, 3.0, 0.5, key="gap_th")
        with c2:
            vspike_mult = st.slider("放量倍数", 2.0, 10.0, 3.0, 0.5, key="vspike_mult")
        with c3:
            limit_th = st.slider("涨跌停阈值 (%)", 5.0, 10.0, 9.0, 0.5, key="limit_th")
        with c4:
            cons_days = st.slider("连续涨跌天数", 2, 8, 3, 1, key="cons_days")

    if st.button("🔍 检测异动", type="primary", use_container_width=True,
                 key="run_anomalies"):
        st.cache_data.clear()
        with st.spinner("正在检测异动（约 3 秒）..."):
            params = {
                "gap_threshold": gap_th,
                "volume_multiplier": vspike_mult,
                "limit_threshold": limit_th,
                "consecutive_days": cons_days,
            }
            results = _load_anomalies(latest_date, params)
            st.session_state["anomaly_results"] = results

    if "anomaly_results" not in st.session_state:
        st.info("点击上方按钮开始检测")
        return

    results = st.session_state["anomaly_results"]
    if not results:
        st.warning("未发现异动信号")
        return

    # 统计卡片
    cols = st.columns(len(results))
    for i, (name, df) in enumerate(results.items()):
        with cols[i]:
            up_count = len(df[df.get("direction", "") == "up"]) if "direction" in df.columns else 0
            down_count = len(df[df.get("direction", "") == "down"]) if "direction" in df.columns else 0
            delta_str = f"↑{up_count} ↓{down_count}" if up_count or down_count else None
            st.metric(name, len(df), delta=delta_str)

    # 逐类展示
    for name, df in results.items():
        with st.expander(f"{name} ({len(df)} 只)", expanded=True):
            display = _add_names(df)
            display = display.rename(columns={
                "symbol": "代码", "gap_pct": "跳空%", "direction": "方向",
                "prev_close": "前收", "today_open": "今开",
                "close": "收盘价", "volume": "成交量",
                "avg_vol_20d": "20日均量", "vol_ratio": "量比",
                "pct_change": "涨跌幅%", "streak_length": "连续天数",
                "cumulative_pct": "累计涨跌%",
            })
            st.dataframe(display, use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════
# Sub-tab 4: DB Industry Rotation
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
# Sub-tab 5: Candlestick Patterns
# ══════════════════════════════════════════════════

@st.cache_data(ttl=3600)
def _load_candlestick(date):
    return scan_all_candlestick_patterns(date)


def _render_candlestick():
    st.subheader("🕯️ K线形态识别")

    latest_date = get_latest_trading_date()
    if latest_date is None:
        st.info("数据库暂无数据"); return
    st.caption(f"扫描日期: {latest_date} — 8种经典蜡烛图形态")

    if st.button("🔍 扫描蜡烛形态", type="primary", use_container_width=True, key="candle_scan"):
        st.cache_data.clear()
        with st.spinner("扫描中（约1秒）..."):
            st.session_state["candle_results"] = _load_candlestick(latest_date)

    if "candle_results" not in st.session_state:
        st.info("点击扫描按钮检测当日蜡烛形态")
        return

    results = st.session_state["candle_results"]
    cols = st.columns(len(results)) if results else []
    for i, (name, df) in enumerate(results.items()):
        with cols[i]:
            st.metric(name, len(df))

    for name, df in results.items():
        with st.expander(f"{name} ({len(df)} 只)"):
            display = _add_names(df)
            display = display.rename(columns={"symbol": "代码", "date": "日期", "close": "收盘"})
            st.dataframe(display, use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════
# Sub-tab 6: Enhanced Correlation Tools
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

def render():
    st.title("📊 高级分析")
    st.caption("DuckDB 驱动 — 多因子 · 形态 · 异动 · 蜡烛 · 相关性 · 批量回测 · 量化信号")

    sub1, sub2, sub3, sub4, sub5, sub6, sub7, sub8 = st.tabs([
        "🎯 多因子排名",
        "📐 形态扫描",
        "⚡ 异动检测",
        "🔄 行业轮动",
        "🕯️ K线形态",
        "🔗 相关性",
        "🚀 批量回测",
        "📡 量化信号",
    ])

    with sub1: _render_factor_ranking()
    with sub2: _render_pattern_scanning()
    with sub3: _render_anomaly_detection()
    with sub4: _render_industry_rotation()
    with sub5: _render_candlestick()
    with sub6: _render_correlation()
    with sub7: _render_batch_backtest()
    with sub8: _render_quant_signals()
