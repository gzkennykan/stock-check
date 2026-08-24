"""
ui/charts.py — 统一图表构建器（纯 Plotly，无 Streamlit 依赖）。

从各页散落的 make_subplots / update_layout 中收敛出常见图表的统一实现，
统一使用 ui.theme 的设计 token 与 winnerk 模板。

可复用：
    candlestick()   K线 + 成交量副图（红涨绿跌）
    dual_axis()     双轴折线（如 资金净额 vs 收盘价）
    bar_pct()       红涨绿跌柱状（行业动量 / 涨跌幅排序）
"""
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .theme import UP, DOWN, COLORWAY, kline_fig


def _base_layout(height: int) -> dict:
    """kline_fig 的 layout dict，去掉 title 以免与调用方冲突。"""
    d = kline_fig(height).layout.to_plotly_json()
    d.pop("title", None)
    return d


def candlestick(df: pd.DataFrame, ma_list=(20, 60, 120), title: str = "K线") -> go.Figure:
    """K线 + 成交量副图，红涨绿跌，均线用主题色。df 需含 open/high/low/close/volume。"""
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        row_heights=[0.72, 0.28], vertical_spacing=0.03)
    fig.add_trace(go.Candlestick(
        x=df.index, open=df["open"], high=df["high"],
        low=df["low"], close=df["close"],
        increasing=dict(line=dict(color=UP), fillcolor=UP),
        decreasing=dict(line=dict(color=DOWN), fillcolor=DOWN),
        name="K线"), row=1, col=1)

    ma_colors = (COLORWAY[1], COLORWAY[3], COLORWAY[4])  # 信息蓝/警示黄/紫
    for n, c in zip(ma_list, ma_colors):
        col = f"ma{n}"
        if col in df.columns:
            fig.add_trace(go.Scatter(x=df.index, y=df[col], name=f"MA{n}",
                                     line=dict(width=1, color=c)), row=1, col=1)

    vol_colors = [UP if c >= o else DOWN for c, o in zip(df["close"], df["open"])]
    fig.add_trace(go.Bar(x=df.index, y=df["volume"], marker_color=vol_colors,
                         name="量", showlegend=False), row=2, col=1)

    fig.update_layout(**_base_layout(460),
                      title=title, xaxis_rangeslider_visible=False)
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])], row=1, col=1)
    return fig


def dual_axis(x, y_left, y_right, *, x_title: str = "", y_left_title="",
              y_right_title="", name_left="", name_right="", title: str = "") -> go.Figure:
    """双轴折线（左轴/右轴单位不同，如 资金净额 vs 收盘价）。"""
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Scatter(x=x, y=y_left, name=name_left or y_left_title,
                             line=dict(color=COLORWAY[0], width=2)), secondary_y=False)
    fig.add_trace(go.Scatter(x=x, y=y_right, name=name_right or y_right_title,
                             line=dict(color=COLORWAY[1], width=2)), secondary_y=True)
    fig.update_layout(**_base_layout(360), title=title)
    fig.update_xaxes(title_text=x_title, showgrid=False)
    fig.update_yaxes(title_text=y_left_title, secondary_y=False)
    fig.update_yaxes(title_text=y_right_title, secondary_y=True, showgrid=False)
    return fig


def bar_pct(labels, values, *, title: str = "", colors=None) -> go.Figure:
    """红涨绿跌柱状（行业动量 / 涨跌幅排序）。值正=红，负=绿。"""
    if colors is None:
        colors = [UP if v >= 0 else DOWN for v in values]
    fig = go.Figure(go.Bar(x=labels, y=values, marker_color=colors))
    fig.update_layout(**_base_layout(360), title=title)
    fig.update_yaxes(tickformat=".1f")
    return fig
