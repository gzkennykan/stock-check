"""Tab ML: 🧠 ML因子研究 — 因子IC分析 + LightGBM排序 + 分层回测"""
import streamlit as st
import pandas as pd
import numpy as np

from data.ml_factors import (
    compute_all_factors, compute_factor_ic, compute_factor_correlation,
    train_lightgbm_ranker, stratified_backtest,
)
from data.database import get_latest_trading_date

import plotly.graph_objects as go
from plotly.subplots import make_subplots


def render():
    st.title("🧠 ML 因子研究")
    st.caption("对标 Qlib — 因子 IC 分析 · 相关性矩阵 · LightGBM 排序 · 分层回测")

    # ── 日期选择 ──
    col1, col2 = st.columns([2, 3])
    with col1:
        end_date = st.date_input(
            "分析日期",
            value=pd.to_datetime(get_latest_trading_date() or "2025-01-01"),
            key="ml_date",
        )
    with col2:
        st.caption("基于该日期全市场截面数据，计算因子 → 预测未来收益")

    end_str = end_date.strftime("%Y-%m-%d")

    # ── 数据加载 ──
    if "ml_factors_df" not in st.session_state:
        st.session_state.ml_factors_df = None
        st.session_state.ml_factor_cols = None

    if st.button("📊 加载/刷新因子数据", use_container_width=True, type="primary", key="ml_load"):
        with st.spinner("计算全市场20+因子（约需10-20秒）..."):
            df = compute_all_factors(end_str)
        if df.empty:
            st.error(f"日期 {end_str} 无足够数据")
        else:
            exclude = {"symbol", "trade_date", "daily_ret"}
            factor_cols = [c for c in df.columns if c not in exclude]
            st.session_state.ml_factors_df = df
            st.session_state.ml_factor_cols = factor_cols
            st.success(f"已加载 {len(df)} 只股票 × {len(factor_cols)} 个因子")

    df = st.session_state.ml_factors_df
    factor_cols = st.session_state.ml_factor_cols

    if df is None or df.empty:
        st.info("👆 点击加载因子数据")
        return

    st.divider()

    # ══════════════════════════════════════════
    # Tab 1: 因子IC分析
    # ══════════════════════════════════════════
    tab_ic, tab_corr, tab_ml, tab_strat = st.tabs([
        "📊 因子IC", "🔗 相关性", "🤖 ML排序", "📈 分层回测"
    ])

    with tab_ic:
        st.subheader("因子 IC（信息系数）分析")
        st.caption("IC = 因子值与未来N日收益的 Pearson 相关系数。|IC| > 0.03 有预测力，|IC| > 0.05 优秀。")

        forward_days = st.multiselect(
            "前向周期", [1, 5, 20],
            default=[5, 20], key="ml_ic_periods",
            format_func=lambda x: f"{x}日",
        )

        if st.button("计算 IC", key="ml_ic_go"):
            with st.spinner("计算因子 IC（含未来收益查询）..."):
                ic_df = compute_factor_ic(df, forward_periods=forward_days, factor_cols=factor_cols)

            if ic_df.empty:
                st.warning("IC 计算失败，数据不足")
            else:
                st.session_state.ml_ic_result = ic_df

                # IC 柱状图
                ic_col = f"IC_{forward_days[0]}d" if forward_days else "IC_5d"
                if ic_col in ic_df.columns:
                    fig = go.Figure()
                    colors = ["#00C853" if v > 0 else "#FF1744"
                              for v in ic_df[ic_col].fillna(0)]
                    fig.add_trace(go.Bar(
                        x=ic_df["Factor"], y=ic_df[ic_col],
                        marker_color=colors,
                        text=[f"{v:.4f}" for v in ic_df[ic_col]],
                        textposition="outside",
                    ))
                    fig.add_hline(y=0.03, line_dash="dash", line_color="#888",
                                  annotation_text="IC=0.03 阈值")
                    fig.add_hline(y=-0.03, line_dash="dash", line_color="#888")
                    fig.update_layout(
                        title=f"因子 IC 柱状图 ({ic_col})",
                        height=400, margin=dict(l=20, r=20, t=40, b=80),
                    )
                    st.plotly_chart(fig, use_container_width=True)

                st.dataframe(ic_df, use_container_width=True, hide_index=True)
                st.caption("💡 IC_IR > 0.5 = 良好，IC_IR > 1.0 = 优秀")

    # ══════════════════════════════════════════
    # Tab 2: 相关性矩阵
    # ══════════════════════════════════════════
    with tab_corr:
        st.subheader("因子相关性矩阵")
        st.caption("高相关性(>0.7)的因子可合并，避免冗余。")

        # 选择因子
        selected_factors = st.multiselect(
            "选择因子（建议8-12个）",
            options=factor_cols,
            default=[c for c in factor_cols if c in ["mom_5d","mom_20d","mom_60d","rev_5d",
                                                      "ma20_dev","ma60_dev","vol_20d",
                                                      "vol_ratio_5d","rsi_14","dist_20d_high"]][:10],
            key="ml_corr_sel",
        )

        if selected_factors and st.button("计算相关性", key="ml_corr_go"):
            corr_df = compute_factor_correlation(df, factor_cols=selected_factors)
            if not corr_df.empty:
                st.session_state.ml_corr_result = corr_df

                # 热力图
                fig = go.Figure(data=go.Heatmap(
                    z=corr_df.values,
                    x=corr_df.columns.tolist(),
                    y=corr_df.index.tolist(),
                    colorscale="RdBu_r",
                    zmid=0,
                    zmin=-1, zmax=1,
                    text=[[f"{v:.2f}" for v in row] for row in corr_df.values],
                    texttemplate="%{text}",
                    textfont={"size": 9},
                ))
                fig.update_layout(
                    height=500, margin=dict(l=20, r=20, t=20, b=80),
                )
                st.plotly_chart(fig, use_container_width=True)

                # 高相关性对
                high_corr = []
                for i, fi in enumerate(corr_df.columns):
                    for j, fj in enumerate(corr_df.columns):
                        if i < j and abs(corr_df.iloc[i, j]) > 0.7:
                            high_corr.append({
                                "因子A": fi, "因子B": fj,
                                "相关系数": round(corr_df.iloc[i, j], 3),
                            })
                if high_corr:
                    st.warning(f"⚠️ 发现 {len(high_corr)} 对高相关因子(>0.7)，建议合并")
                    st.dataframe(pd.DataFrame(high_corr), use_container_width=True, hide_index=True)

    # ══════════════════════════════════════════
    # Tab 3: LightGBM 排序模型
    # ══════════════════════════════════════════
    with tab_ml:
        st.subheader("🤖 LightGBM 排序模型")
        st.caption("用 ML 学习因子非线性组合 → 预测未来收益排序")

        ml_factors = st.multiselect(
            "训练因子",
            options=factor_cols,
            default=[c for c in factor_cols if c not in ["daily_ret"]][:10],
            key="ml_train_factors",
        )
        forward = st.selectbox("预测周期", [5, 10, 20], index=2,
                               format_func=lambda x: f"未来{x}日收益", key="ml_fwd")

        if st.button("🚀 训练 LightGBM", type="primary", key="ml_train"):
            with st.spinner(f"训练中（{len(df)} 样本 × {len(ml_factors)} 因子）..."):
                result = train_lightgbm_ranker(
                    df, factor_cols=ml_factors, forward_days=forward)

            if "error" in result:
                st.error(result["error"])
            else:
                st.session_state.ml_model_result = result
                st.session_state.ml_model_df = df
                st.session_state.ml_model_factors = ml_factors
                st.success(f"训练完成！验证集相关性: {result['train_score']:.4f}  |  "
                          f"样本: {result['n_samples']} 条")

                # 特征重要性
                imp = result["feature_importance"]
                fig = go.Figure(data=go.Bar(
                    x=imp["factor"], y=imp["importance"],
                    marker_color="#42A5F5",
                    text=[f"{v:.0f}" for v in imp["importance"]],
                    textposition="outside",
                ))
                fig.update_layout(
                    title="特征重要性",
                    height=350, margin=dict(l=20, r=20, t=40, b=80),
                )
                st.plotly_chart(fig, use_container_width=True)
                st.dataframe(imp, use_container_width=True, hide_index=True)

    # ══════════════════════════════════════════
    # Tab 4: 分层回测
    # ══════════════════════════════════════════
    with tab_strat:
        st.subheader("📈 分层回测（验证单调性）")
        st.caption("将股票按评分分5组 → 计算每组未来收益 → 高分组的收益是否显著高于低分组？")

        cs1, cs2 = st.columns(2)
        with cs1:
            score_source = st.radio(
                "评分来源", ["单因子", "ML模型预测"],
                horizontal=True, key="ml_strat_source",
            )

        if score_source == "单因子":
            with cs2:
                strat_factor = st.selectbox("选择因子", factor_cols, key="ml_strat_factor")
            if st.button("运行分层回测", key="ml_strat_go1"):
                with st.spinner("计算中..."):
                    strat_df = stratified_backtest(
                        df, score_col=strat_factor,
                        forward_days=20, n_groups=5)
                _render_stratified(strat_df, strat_factor)

        else:
            if "ml_model_result" not in st.session_state:
                st.info("请先在「ML排序」 Tab 训练模型")
            else:
                if st.button("运行分层回测（ML模型）", key="ml_strat_go2"):
                    model = st.session_state.ml_model_result["model"]
                    ml_df = st.session_state.ml_model_df
                    ml_facs = st.session_state.ml_model_factors
                    X = ml_df[ml_facs].astype(float)
                    scores = pd.Series(model.predict(X), index=X.index)
                    with st.spinner("计算中..."):
                        strat_df = stratified_backtest(
                            ml_df, scores=scores, forward_days=20, n_groups=5)
                    _render_stratified(strat_df, "LightGBM预测")


def _render_stratified(strat_df: pd.DataFrame, source_name: str):
    """渲染分层回测结果"""
    if strat_df.empty:
        st.error("分层回测数据不足")
        return

    if "error" in strat_df.columns:
        st.error(strat_df["error"].iloc[0])
        return

    # 条形图：每组平均收益
    fig = make_subplots(rows=1, cols=2, subplot_titles=("各组平均收益(%)", "各组胜率(%)"))

    colors = ["#FF1744", "#FF9100", "#FFF176", "#81C784", "#00C853"]
    fig.add_trace(
        go.Bar(x=strat_df["group"].astype(str), y=strat_df["avg_fwd_return"],
               marker_color=colors[:len(strat_df)],
               text=[f"{v:.1f}%" for v in strat_df["avg_fwd_return"]],
               textposition="outside", name="平均收益"),
        row=1, col=1,
    )
    fig.add_trace(
        go.Bar(x=strat_df["group"].astype(str), y=strat_df["win_rate"],
               marker_color=colors[:len(strat_df)],
               text=[f"{v:.0f}%" for v in strat_df["win_rate"]],
               textposition="outside", name="胜率"),
        row=1, col=2,
    )

    fig.update_layout(height=350, showlegend=False,
                      margin=dict(l=20, r=20, t=40, b=20))
    st.plotly_chart(fig, use_container_width=True)

    # 单调性检查
    spread = strat_df.get("_monotonic")
    if spread is not None and len(spread) > 0:
        s = spread.iloc[0] if hasattr(spread, 'iloc') else spread
        if s > 2:
            st.success(f"✅ 单调性良好：Top-Bottom spread = {s:.1f}%（评分有效）")
        elif s > 0:
            st.warning(f"⚠️ 单调性一般：Top-Bottom spread = {s:.1f}%")
        else:
            st.error(f"❌ 无单调性：Top-Bottom spread = {s:.1f}%（因子无效）")

    st.dataframe(strat_df, use_container_width=True, hide_index=True)
    st.caption(f"排序因子: {source_name} | 预测周期: 20日")
