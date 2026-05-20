"""
Plotly 交互图表：资金曲线、回撤、K线、多策略对比、优化历史
"""
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np


def plot_equity_drawdown(equity: pd.Series, bm_equity: pd.Series = None,
                         bm_name: str = "基准") -> go.Figure:
    """资金曲线 + 回撤曲线双图，可选叠加基准曲线"""
    if equity is None or len(equity) == 0:
        return go.Figure()

    rolling_max = equity.cummax()
    drawdown = (equity - rolling_max) / rolling_max * 100

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        vertical_spacing=0.05,
                        row_heights=[0.65, 0.35],
                        subplot_titles=("资金曲线", "回撤曲线"))

    # 资金曲线
    fig.add_trace(go.Scatter(
        x=equity.index, y=equity.values,
        mode="lines", name="策略资金",
        fill="tozeroy", fillcolor="rgba(30,136,229,0.1)",
        line=dict(color="#1E88E5", width=2),
        hovertemplate="%{x|%Y-%m-%d}<br>策略: ¥%{y:,.0f}<extra></extra>"
    ), row=1, col=1)

    # 基准曲线
    if bm_equity is not None and len(bm_equity) > 0:
        fig.add_trace(go.Scatter(
            x=bm_equity.index, y=bm_equity.values,
            mode="lines", name=bm_name,
            line=dict(color="#FF9800", width=1.5, dash="dot"),
            hovertemplate=f"%{{x|%Y-%m-%d}}<br>{bm_name}: ¥%{{y:,.0f}}<extra></extra>"
        ), row=1, col=1)
        # 收益率对比
        strat_return = (equity / equity.iloc[0] - 1) * 100
        bm_return = (bm_equity / bm_equity.iloc[0] - 1) * 100
        fig.add_trace(go.Scatter(
            x=bm_return.index, y=(strat_return - bm_return).values,
            mode="lines", name="超额收益",
            fill="tozeroy", fillcolor="rgba(76,175,80,0.15)",
            line=dict(color="#4CAF50", width=1),
            hovertemplate="%{x|%Y-%m-%d}<br>超额收益: %{y:.2f}%<extra></extra>"
        ), row=2, col=1)
    else:
        fig.add_hline(y=equity.values[0], line_dash="dash", line_color="gray",
                      opacity=0.5, row=1, col=1,
                      annotation_text="初始资金")

    # 回撤曲线
    fig.add_trace(go.Scatter(
        x=drawdown.index, y=drawdown.values,
        mode="lines", name="回撤",
        fill="tozeroy", fillcolor="rgba(229,57,53,0.3)",
        line=dict(color="#E53935", width=1),
        hovertemplate="%{x|%Y-%m-%d}<br>回撤: %{y:.2f}%<extra></extra>"
    ), row=2, col=1)

    fig.update_layout(
        height=600, showlegend=bm_equity is not None and len(bm_equity) > 0,
        hovermode="x unified",
        margin=dict(l=20, r=20, t=40, b=20),
        template="plotly_white",
        legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01),
    )
    fig.update_xaxes(rangeslider_visible=False)
    return fig


def plot_kline(df: pd.DataFrame) -> go.Figure:
    """K线图（Candlestick）+ 成交量柱"""
    if df is None or len(df) == 0:
        return go.Figure()

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        vertical_spacing=0.03,
                        row_heights=[0.7, 0.3])

    # K线
    fig.add_trace(go.Candlestick(
        x=df.index, open=df["open"], high=df["high"],
        low=df["low"], close=df["close"],
        name="K线",
        increasing=dict(line=dict(color="#E53935"), fillcolor="#E53935"),
        decreasing=dict(line=dict(color="#1E8E4A"), fillcolor="#1E8E4A"),
        hovertemplate="%{x|%Y-%m-%d}<br>O: ¥%{open:.2f}<br>H: ¥%{high:.2f}<br>"
                       "L: ¥%{low:.2f}<br>C: ¥%{close:.2f}<extra></extra>"
    ), row=1, col=1)

    # 成交量
    colors = ["#E53935" if df["close"].iloc[i] >= df["open"].iloc[i] else "#1E8E4A"
              for i in range(len(df))]
    fig.add_trace(go.Bar(
        x=df.index, y=df["volume"],
        name="成交量", marker_color=colors,
        hovertemplate="%{x|%Y-%m-%d}<br>量: %{y:,.0f}<extra></extra>"
    ), row=2, col=1)

    fig.update_layout(
        height=500, showlegend=False,
        template="plotly_white",
        margin=dict(l=20, r=20, t=20, b=20),
        xaxis_rangeslider_visible=False,
    )
    fig.update_yaxes(title_text="价格 (¥)", row=1, col=1)
    fig.update_yaxes(title_text="成交量", row=2, col=1)
    return fig


def plot_comparison_chart(results: dict[str, dict]) -> go.Figure:
    """多策略对比柱状图：年化收益 + 夏普 + 最大回撤"""
    if not results:
        return go.Figure()
    names = list(results.keys())
    annual = [results[n].get("annual_return", 0) * 100 for n in names]
    sharpe = [results[n].get("sharpe_ratio") or 0 for n in names]
    dd = [-(results[n].get("max_drawdown", 0) * 100) for n in names]

    fig = make_subplots(rows=1, cols=3, subplot_titles=("年化收益 (%)", "夏普比率", "最大回撤 (%)"))

    colors_ret = ["#4CAF50" if v > 0 else "#E53935" for v in annual]
    fig.add_trace(go.Bar(x=names, y=annual, marker_color=colors_ret,
                         text=[f"{v:.1f}%" for v in annual], textposition="outside"),
                  row=1, col=1)
    fig.add_trace(go.Bar(x=names, y=sharpe, marker_color="#1E88E5",
                         text=[f"{v:.2f}" for v in sharpe], textposition="outside"),
                  row=1, col=2)
    fig.add_trace(go.Bar(x=names, y=dd, marker_color="#E53935",
                         text=[f"{v:.1f}%" for v in dd], textposition="outside"),
                  row=1, col=3)

    fig.update_layout(height=350, showlegend=False, template="plotly_white",
                      margin=dict(l=20, r=20, t=40, b=20))
    return fig


def plot_comparison_curves(curves: dict[str, pd.Series]) -> go.Figure:
    """多策略资金曲线叠加"""
    if not curves:
        return go.Figure()
    fig = go.Figure()
    colors = ["#1E88E5", "#E53935", "#43A047"]
    for i, (name, series) in enumerate(curves.items()):
        pct = (series / series.iloc[0] - 1) * 100
        fig.add_trace(go.Scatter(
            x=pct.index, y=pct.values, mode="lines",
            name=name, line=dict(color=colors[i % 3], width=2),
            hovertemplate=f"{name}<br>%{{x|%Y-%m-%d}}<br>收益率: %{{y:.2f}}%<extra></extra>"
        ))
    fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
    fig.update_layout(
        height=400, template="plotly_white",
        hovermode="x unified",
        margin=dict(l=20, r=20, t=20, b=20),
        yaxis_title="累计收益率 (%)",
    )
    return fig


def plot_optimization_history(trials_df: pd.DataFrame, param_names: list[str]) -> go.Figure:
    """优化历史散点图"""
    if trials_df.empty:
        return go.Figure()

    n_params = len(param_names)
    fig = make_subplots(
        rows=1, cols=min(n_params, 2),
        subplot_titles=[f"{p} vs 目标值" for p in param_names[:2]]
    )

    for i, p in enumerate(param_names[:2]):
        col_name = f"params_{p}"
        if col_name not in trials_df.columns:
            continue
        x_vals = trials_df[col_name]
        y_vals = trials_df["value"]
        fig.add_trace(go.Scatter(
            x=x_vals, y=y_vals, mode="markers",
            marker=dict(size=8, opacity=0.6, color="#1E88E5"),
            hovertemplate=f"{p}: %{{x}}<br>目标: %{{y:.4f}}<extra></extra>",
            name=p
        ), row=1, col=i + 1)

    fig.update_layout(height=300, showlegend=False, template="plotly_white",
                      margin=dict(l=20, r=20, t=40, b=20))
    return fig
