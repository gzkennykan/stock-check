"""
ui/theme.py — 全站设计 token + Plotly 统一模板 + 全局 CSS。

用法：
    from ui.theme import base_fig, apply_theme, kline_fig, apply_global_css, UP, DOWN

设计约定（国内习惯：红涨绿跌）：
    UP   = 涨 / 正收益 / 看多 / 买入     (红)
    DOWN = 跌 / 负收益 / 看空 / 卖出     (绿)
"""
import plotly.graph_objects as go
import plotly.io as pio

Template = go.layout.Template

# ─────────────────────────── 颜色 token ───────────────────────────
UP = "#E4393F"       # 涨 / 正收益 / 看多
DOWN = "#2E9E44"     # 跌 / 负收益 / 看空
FLAT = "#8B98A5"     # 平 / 中性
WARN = "#F59E0B"     # 警示 / 超买超卖 / 观察
INFO = "#3B82F6"     # 信息 / 信号 / 底部区域
ACCENT = "#1A6FE8"   # 交互高亮 / 主按钮 / focus ring

TEXT = "#1F2933"     # 主文本
TEXT_2 = "#506173"   # 次级文本
MUTED = "#8795A1"    # 说明 / 注脚
BG = "#FFFFFF"       # 卡片
BG_APP = "#F5F7FA"   # 页面底
BORDER = "#E3E8EE"   # 分隔 / 描边
GRID = "#EEF2F6"     # 图表网格线

# 频率/分类色板（多序列图按此顺序取色）
COLORWAY = [UP, INFO, DOWN, WARN, "#7C5CFC", "#14B8A6", "#F97316", "#0EA5E9"]

# 连续色标（红=强/高，绿=弱/低；CN语境）
SCORE_RYG = [[0, DOWN], [0.5, "#FFFFFF"], [1, UP]]          # 评分/动量热图
CORR_RdBu = [[0, "#3B82F6"], [0.5, "#FFFFFF"], [1, "#E4393F"]]  # 相关性 -1..1

# 字体（中文优先 + 数字等宽对齐）
FONT_STACK = "system-ui,-apple-system,'PingFang SC','Microsoft YaHei','Segoe UI',sans-serif"

RADIUS = 12
SPACE = [4, 8, 12, 16, 24, 32]


# ─────────────────────────── Plotly 全局模板 ───────────────────────────
# 用自定义 "winnerk" 模板统一全站图表骨架；默认设为它，显式 template 也统一替换。
_WINNERK_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor=BG,
    font=dict(family=FONT_STACK, color=TEXT, size=13),
    colorway=COLORWAY,
    margin=dict(l=48, r=24, t=40, b=40),
    hoverlabel=dict(bgcolor=BG, font_size=12, font_family=FONT_STACK),
    legend=dict(orientation="h", yanchor="bottom", y=-0.22,
                xanchor="center", x=0.5, font=dict(size=11, color=TEXT_2)),
    xaxis=dict(showgrid=False, zeroline=False, linecolor=BORDER,
               tickfont=dict(color=TEXT_2)),
    yaxis=dict(showgrid=True, gridcolor=GRID, zeroline=False,
               linecolor=BORDER, tickfont=dict(color=TEXT_2)),
)

pio.templates["winnerk"] = Template(layout=_WINNERK_LAYOUT)
pio.templates.default = "winnerk"


# ─────────────────────────── Plotly 模板 ───────────────────────────

def base_fig(height: int = 360, title: str = None) -> go.Figure:
    """统一图表底座：去掉 plotly_white，用自定义 token。"""
    return go.Figure().update_layout(
        template=None,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor=BG,
        font=dict(family=FONT_STACK, color=TEXT, size=13),
        colorway=COLORWAY,
        height=height,
        title=dict(text=title, x=0.02, font=dict(size=16, color=TEXT)),
        margin=dict(l=48, r=24, t=40 if title else 24, b=40),
        hovermode="x unified",
        hoverlabel=dict(bgcolor=BG, font_size=12, font_family=FONT_STACK),
        legend=dict(orientation="h", yanchor="bottom", y=-0.22,
                    xanchor="center", x=0.5, font=dict(size=11, color=TEXT_2)),
        xaxis=dict(showgrid=False, zeroline=False, linecolor=BORDER,
                   tickfont=dict(color=TEXT_2)),
        yaxis=dict(showgrid=True, gridcolor=GRID, zeroline=False,
                   linecolor=BORDER, tickfont=dict(color=TEXT_2)),
        dragmode="pan",
    )


def apply_theme(fig: go.Figure, **kwargs) -> go.Figure:
    """把任意 figure 覆盖成统一主题，kwargs 直接透传给 update_layout。"""
    fig.update_layout(
        template=None,
        colorway=COLORWAY,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor=BG,
        font=dict(family=FONT_STACK, color=TEXT),
        **kwargs,
    )
    return fig


def kline_fig(height: int = 460) -> go.Figure:
    """K线主图模板：隐藏 rangeslider、网格更轻。"""
    fig = base_fig(height)
    fig.update_layout(
        xaxis=dict(rangeslider=dict(visible=False), showgrid=False),
        yaxis=dict(gridcolor=GRID),
    )
    return fig


# ─────────────────────────── Streamlit 全局 CSS ───────────────────────────

def apply_global_css() -> None:
    """注入全局 CSS：中文字体栈 + 数字等宽对齐。app.py 顶部调用一次。"""
    import streamlit as st
    st.markdown(
        f"""
        <style>
        html, body, [class*="css"], [data-testid="stMetricValue"],
        [data-testid="stMetricDelta"], [data-testid="stDataFrame"] * {{
            font-family: {FONT_STACK};
        }}
        [data-testid="stDataFrame"] *,
        [data-testid="stMetricValue"],
        [data-testid="stMetricDelta"] {{
            font-variant-numeric: tabular-nums;
        }}
        [data-testid="stMetric"] {{
            background: {BG};
            border: 1px solid {BORDER};
            border-radius: {RADIUS}px;
            padding: 12px 16px;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )
