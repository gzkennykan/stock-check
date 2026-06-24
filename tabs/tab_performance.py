"""Tab 📊 绩效分析 — 专业回测报告"""
import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime

from data.performance import (
    compute_metrics, compute_rolling_metrics, compute_trade_distribution,
    _compute_monthly_returns,
)

import plotly.graph_objects as go
from plotly.subplots import make_subplots


def render():
    st.title("📊 绩效分析")
    st.caption("专业回测绩效报告 — Sharpe/Calmar/最大回撤/月度热力图/交易分布")

    # ── 数据源选择 ──
    src_col1, src_col2 = st.columns([2, 3])
    with src_col1:
        data_source = st.radio(
            "数据来源",
            ["📈 最近一次回测结果", "📂 上传权益曲线 CSV"],
            horizontal=True,
            key="perf_source",
        )

    equity = None
    trades_data = None

    if "最近" in data_source:
        # 从 session_state 获取上次回测结果
        bt_result = st.session_state.get("_last_backtest_result")
        if bt_result and "equity_curve" in bt_result:
            equity = bt_result["equity_curve"]
            trades_data = bt_result.get("trades", [])
        elif bt_result and "metrics" in bt_result:
            # 旧格式: 只有指标没有曲线
            equity = None
            st.info("旧版回测结果不含权益曲线，请重新运行回测")
        else:
            st.info("👈 请先在「单策略回测」Tab 中运行一次回测，或上传 CSV 文件")

    else:
        uploaded = st.file_uploader("上传权益曲线 CSV（列: date, equity）", type="csv", key="perf_upload")
        if uploaded:
            df = pd.read_csv(uploaded)
            if "date" in df.columns and "equity" in df.columns:
                df["date"] = pd.to_datetime(df["date"])
                equity = pd.Series(df["equity"].values, index=df["date"])
                st.success(f"已加载 {len(equity)} 个交易日数据")
            else:
                st.error("CSV 需要包含 date 和 equity 两列")

    if equity is None or len(equity) < 5:
        return

    # ── 核心指标计算 ──
    daily_returns = equity.pct_change().dropna()
    metrics = compute_metrics(equity, daily_returns, trades_data or [])

    st.divider()

    # ══════════════════════════════════════════
    # 1. 核心指标卡片
    # ══════════════════════════════════════════
    st.subheader("📈 核心指标")

    r1c1, r1c2, r1c3, r1c4, r1c5 = st.columns(5)
    with r1c1:
        st.metric("累计收益", f"{metrics.get('total_return', 0):.2f}%")
    with r1c2:
        st.metric("年化收益 (CAGR)", f"{metrics.get('cagr', 0):.2f}%")
    with r1c3:
        st.metric("年化波动率", f"{metrics.get('volatility', 0):.2f}%")
    with r1c4:
        st.metric("最大回撤", f"{metrics.get('max_drawdown', 0):.2f}%")
    with r1c5:
        st.metric("回撤持续", f"{metrics.get('max_dd_duration', 0)} 天")

    r2c1, r2c2, r2c3, r2c4, r2c5 = st.columns(5)
    with r2c1:
        sharpe = metrics.get("sharpe", 0)
        st.metric("Sharpe 比率", f"{sharpe:.2f}", help=">1=良好, >2=优秀, >3=极佳")
    with r2c2:
        calmar = metrics.get("calmar", 0)
        st.metric("Calmar 比率", f"{calmar:.2f}", help="年化收益÷最大回撤，越高越好")
    with r2c3:
        sortino = metrics.get("sortino", 0)
        st.metric("Sortino 比率", f"{sortino:.2f}", help="仅惩罚下行波动")
    with r2c4:
        ir = metrics.get("information_ratio")
        st.metric("信息比率", f"{ir:.2f}" if ir is not None else "N/A",
                  help="超额收益÷跟踪误差")
    with r2c5:
        st.metric("VaR(95%)", f"{metrics.get('var_95', 0):.2f}%",
                  help="95%置信度下日最大亏损")

    r3c1, r3c2, r3c3, r3c4, r3c5 = st.columns(5)
    with r3c1:
        st.metric("胜率", f"{metrics.get('win_rate', 0):.1f}%")
    with r3c2:
        st.metric("盈亏比", f"{metrics.get('profit_factor', 0):.2f}",
                  help="总盈利÷总亏损，>1.5=良好")
    with r3c3:
        st.metric("交易次数", metrics.get("total_trades", 0))
    with r3c4:
        st.metric("最佳交易", f"{metrics.get('best_trade', 0):.0f}")
    with r3c5:
        st.metric("最差交易", f"{metrics.get('worst_trade', 0):.0f}")

    st.divider()

    # ══════════════════════════════════════════
    # 2. 权益曲线 + 回撤
    # ══════════════════════════════════════════
    st.subheader("📉 权益曲线 & 回撤分析")

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.06,
        row_heights=[0.65, 0.35],
        subplot_titles=("权益曲线", "回撤 (%)"),
    )

    # 权益曲线
    fig.add_trace(
        go.Scatter(
            x=equity.index, y=equity.values,
            mode="lines", name="策略权益",
            line=dict(color="#2196F3", width=2),
        ),
        row=1, col=1,
    )

    # 回撤
    cummax = equity.expanding().max()
    drawdown = (equity - cummax) / cummax * 100
    fig.add_trace(
        go.Scatter(
            x=drawdown.index, y=drawdown.values,
            mode="lines", name="回撤",
            fill="tozeroy",
            line=dict(color="#FF5252", width=1),
            fillcolor="rgba(255,82,82,0.2)",
        ),
        row=2, col=1,
    )
    fig.add_hline(y=0, line_dash="dash", line_color="#888", row=2, col=1)

    fig.update_layout(
        height=500,
        showlegend=True,
        hovermode="x unified",
        margin=dict(l=20, r=20, t=40, b=20),
    )
    fig.update_yaxes(title_text="净值", row=1, col=1)
    fig.update_yaxes(title_text="回撤 %", row=2, col=1)

    st.plotly_chart(fig, use_container_width=True)

    # ══════════════════════════════════════════
    # 3. 月度收益热力图
    # ══════════════════════════════════════════
    st.subheader("🗓️ 月度收益")

    monthly = _compute_monthly_returns(equity)
    if not monthly.empty:
        # 数值矩阵
        month_cols = [c for c in monthly.columns if "月" in c]
        if month_cols:
            data_matrix = monthly[month_cols].replace("—", np.nan).astype(float)

            fig_heat = go.Figure(data=go.Heatmap(
                z=data_matrix.values,
                x=month_cols,
                y=[str(y) for y in monthly.index],
                text=[[f"{v:.1f}%" if not np.isnan(v) else "" for v in row]
                      for row in data_matrix.values],
                texttemplate="%{text}",
                textfont={"size": 10},
                colorscale=[
                    [0.0, "#FF1744"],    # 深红 (-10%以下)
                    [0.25, "#FF9100"],   # 橙
                    [0.5, "#FFF176"],    # 黄
                    [0.75, "#81C784"],   # 浅绿
                    [1.0, "#00C853"],    # 深绿 (>10%)
                ],
                zmid=0,
                hovertemplate="%{y}年 %{x}: %{z:.2f}%<extra></extra>",
            ))

            fig_heat.update_layout(
                height=max(200, 40 * len(monthly)),
                margin=dict(l=20, r=20, t=20, b=20),
                xaxis=dict(side="top"),
            )

            st.plotly_chart(fig_heat, use_container_width=True)

        # 年度汇总
        if "年度收益%" in monthly.columns:
            st.dataframe(monthly, use_container_width=True)
        else:
            st.dataframe(monthly, use_container_width=True)

    # ══════════════════════════════════════════
    # 4. 滚动指标（稳定性分析）
    # ══════════════════════════════════════════
    st.subheader("📊 滚动指标（60日窗口）")

    rolling = compute_rolling_metrics(equity, window=60)
    if rolling:
        fig_roll = make_subplots(
            rows=2, cols=2,
            subplot_titles=(
                "滚动 Sharpe 比率", "滚动年化波动率",
                "滚动年化收益", "滚动最大回撤",
            ),
        )

        positions = {
            "sharpe": (1, 1), "volatility": (1, 2),
            "annual_return": (2, 1), "drawdown": (2, 2),
        }

        for key, (r, c) in positions.items():
            if key in rolling and not rolling[key].empty:
                fig_roll.add_trace(
                    go.Scatter(
                        x=rolling[key].index, y=rolling[key].values,
                        mode="lines", name=key,
                        line=dict(width=1.5),
                    ),
                    row=r, col=c,
                )

        fig_roll.update_layout(
            height=500,
            showlegend=False,
            hovermode="x unified",
            margin=dict(l=20, r=20, t=40, b=20),
        )

        st.plotly_chart(fig_roll, use_container_width=True)

    # ══════════════════════════════════════════
    # 5. 交易分布（如有交易数据）
    # ══════════════════════════════════════════
    if trades_data:
        st.subheader("📊 交易分布")

        dist = compute_trade_distribution(trades_data)
        if dist:
            tc1, tc2 = st.columns(2)

            with tc1:
                if "pnl_distribution" in dist and not dist["pnl_distribution"].empty:
                    st.caption("盈亏分布")
                    fig_pnl = go.Figure(data=go.Bar(
                        x=dist["pnl_distribution"].index.tolist(),
                        y=dist["pnl_distribution"].values.tolist(),
                        marker_color=["#FF1744" if "-" in str(x) else "#00C853" for x in dist["pnl_distribution"].index],
                    ))
                    fig_pnl.update_layout(height=300, margin=dict(l=20, r=20, t=20, b=40))
                    st.plotly_chart(fig_pnl, use_container_width=True)

            with tc2:
                if "duration_distribution" in dist and not dist["duration_distribution"].empty:
                    st.caption("持仓天数分布")
                    fig_dur = go.Figure(data=go.Bar(
                        x=dist["duration_distribution"].index.tolist(),
                        y=dist["duration_distribution"].values.tolist(),
                        marker_color="#42A5F5",
                    ))
                    fig_dur.update_layout(height=300, margin=dict(l=20, r=20, t=20, b=40))
                    st.plotly_chart(fig_dur, use_container_width=True)

    # ══════════════════════════════════════════
    # 6. 详细指标表
    # ══════════════════════════════════════════
    with st.expander("📋 完整指标明细"):
        rows = []
        for k, v in metrics.items():
            if v is not None:
                label_map = {
                    "total_return": "累计收益(%)",
                    "cagr": "年化收益(%)",
                    "volatility": "年化波动率(%)",
                    "sharpe": "Sharpe比率",
                    "calmar": "Calmar比率",
                    "sortino": "Sortino比率",
                    "max_drawdown": "最大回撤(%)",
                    "max_dd_duration": "最长回撤持续(天)",
                    "var_95": "VaR 95%(%)",
                    "information_ratio": "信息比率",
                    "win_rate": "胜率(%)",
                    "profit_factor": "盈亏比",
                    "avg_win": "平均盈利",
                    "avg_loss": "平均亏损",
                    "total_trades": "总交易次数",
                    "best_trade": "最佳交易",
                    "worst_trade": "最差交易",
                    "avg_bars": "平均持仓天数",
                    "n_months_positive": "正收益月数",
                    "n_years": "回测年数",
                    "n_days": "回测天数",
                }
                rows.append({
                    "指标": label_map.get(k, k),
                    "数值": f"{v:.2f}" if isinstance(v, float) else str(v),
                })

        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
