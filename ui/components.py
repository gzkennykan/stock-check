"""
ui/components.py — 语义化 Streamlit 组件。

统一 HTML 风格（badge / conclusion_card / diagnosis_section），
以及修正标准 st.metric 红涨绿跌语义的 metric_cn。
"""
import pandas as pd
import streamlit as st

from .theme import UP, DOWN, FLAT, WARN, INFO, TEXT, TEXT_2, MUTED, BG, BORDER, RADIUS


# ─────────────────────────── 状态徽章 ───────────────────────────

_BADGE = {
    "bull": ("看涨", UP, "rgba(228,57,63,0.10)"),
    "bear": ("看跌", DOWN, "rgba(46,158,68,0.10)"),
    "flat": ("中性", FLAT, "rgba(139,152,165,0.12)"),
    "warn": ("观察", WARN, "rgba(245,158,11,0.12)"),
    "info": ("信号", INFO, "rgba(59,130,246,0.10)"),
}


def badge(kind: str, text: str = None, *, score: float = None) -> None:
    """渲染一个带底色的语义 pill。

    kind: bull/bear/flat/warn/info；score: 可选，拼到文本后。
    """
    label, fg, bg = _BADGE.get(kind, _BADGE["flat"])
    txt = text or label
    if score is not None:
        fg = UP if score >= 70 else (WARN if score >= 55 else DOWN)
        txt = f"{txt} {score:.1f}"
    st.markdown(
        f'<span style="display:inline-block;padding:3px 10px;border-radius:999px;'
        f'background:{bg};color:{fg};font-weight:600;font-size:12px">{txt}</span>',
        unsafe_allow_html=True,
    )


def score_badge(score: float) -> None:
    """按分数自动评级出徽章（>=70看涨 / 55-70信号 / 40-55观察 / <40看跌）。"""
    if score >= 70:
        badge("bull", score=score)
    elif score >= 55:
        badge("info", score=score)
    elif score >= 40:
        badge("warn", score=score)
    else:
        badge("bear", score=score)


# ─────────────────────────── 指标卡（红涨绿跌） ───────────────────────────

def metric_cn(label: str, value, *, delta: float = None, good: str = "up",
              help: str = "涨/多为好 → good='up'; 跌/空为好 → good='down'") -> None:
    """指标卡，delta 箭头颜色按红涨绿跌。

    Streamlit st.metric 默认 delta 正=绿↑（美股习惯），这里修正为 CN 语义。
    """
    if delta is None:
        st.metric(label, value)
        return
    is_good_positive = (delta > 0) == (good == "up")
    color = UP if is_good_positive else DOWN
    st.metric(label, value, delta=f"{delta:+.2f}", delta_color="off")
    if help:
        st.caption(help)


# ─────────────────────────── 结论前置卡 ───────────────────────────

def conclusion_card(verdict: str, points: list[str], *, tone: str = "info",
                    title: str = "结论") -> None:
    """每个结果页正文第 1 行：一句判断 + 最多 3 条支撑点。"""
    color = _BADGE.get(tone, _BADGE["info"])[1]
    dots = "".join(f'<li style="margin:3px 0">{p}</li>' for p in points[:3])
    st.markdown(
        f'<div style="border:1px solid {BORDER};border-left:4px solid {color};'
        f'border-radius:{RADIUS}px;background:{BG};padding:14px 16px;margin-bottom:12px">'
        f'<b style="color:{TEXT};font-size:15px">{title}</b>'
        f'<div style="margin:6px 0;font-size:14px"><b style="color:{color}">{verdict}</b></div>'
        f'<ul style="margin:0;padding-left:18px;color:{TEXT_2};font-size:13px">{dots}</ul>'
        f'</div>',
        unsafe_allow_html=True,
    )


# ─────────────────────────── 四分区诊断卡 ───────────────────────────

def _items_html(items) -> str:
    rows = []
    for it in items:
        if len(it) == 3:
            label, value, pct = it
            bg = UP if pct > 0.66 else (WARN if pct > 0.4 else DOWN)
            width = max(4, min(100, abs(pct) * 100))
            rows.append(
                f'<div style="margin:6px 0">'
                f'<div style="display:flex;justify-content:space-between;font-size:13px;color:{TEXT_2}">'
                f'<span>{label}</span><b style="color:{TEXT}">{value}</b></div>'
                f'<div style="height:6px;border-radius:999px;background:#EEF2F6;margin-top:4px">'
                f'<div style="height:6px;border-radius:999px;background:{bg};width:{width:.0f}%"></div>'
                f'</div></div>'
            )
        else:
            label, value = it
            rows.append(
                f'<div style="display:flex;justify-content:space-between;font-size:13px;'
                f'color:{TEXT_2};margin:3px 0"><span>{label}</span><b style="color:{TEXT}">{value}</b></div>'
            )
    return "".join(rows)


def diagnosis_section(title: str, icon: str, score: float, max_score: float,
                      items) -> None:
    """一个带进度条的四分区诊断卡，替代成堆的 st.write 冒号列表。

    items: [(label, value), ...] 或 [(label, value, pct_basis), ...]
    """
    pct = score / max_score if max_score else 0
    color = UP if pct > 0.66 else (WARN if pct > 0.4 else DOWN)
    st.markdown(
        f'<div style="border:1px solid {BORDER};border-radius:{RADIUS}px;'
        f'padding:16px;background:{BG};margin-bottom:12px">'
        f'<div style="display:flex;justify-content:space-between;align-items:center">'
        f'<b style="font-size:14px">{icon} {title}</b>'
        f'<span style="color:{color};font-weight:700">{score:.0f}/{max_score:.0f}</span></div>'
        f'<div style="height:6px;border-radius:999px;background:#EEF2F6;margin:10px 0">'
        f'<div style="height:6px;border-radius:999px;background:{color};width:{pct*100:.0f}%"></div>'
        f'</div>{_items_html(items)}</div>',
        unsafe_allow_html=True,
    )


# ─────────────────────────── 三态（空/加载/错误） ───────────────────────────

def empty_state(icon: str, title: str, hint: str = None, action: str = None,
                *, on_click=None, key: str = None) -> bool:
    """居中空状态。返回 True 表示用户点了 action 按钮。"""
    st.markdown(f'<div style="text-align:center;padding:32px;color:{MUTED}">'
                f'<div style="font-size:40px">{icon}</div>'
                f'<b style="color:{TEXT_2};font-size:15px">{title}</b>'
                f'{"<div style=font-size:13px;margin-top:4px>" + hint + "</div>" if hint else ""}'
                f'</div>', unsafe_allow_html=True)
    if action:
        return st.button(action, key=key, on_click=on_click)
    return False


def loading_state(text: str, expected_secs: int = None) -> st.delta_generator.DeltaGenerator:
    """长任务加载态：普通 spinner 或带预计时间的 st.status。"""
    if expected_secs and expected_secs > 5:
        return st.status(f"{text}（预计约 {expected_secs}s）", expanded=True)
    return st.spinner(text)


def error_retry(error, retry_cb, *, key: str = None) -> None:
    """顶部错误提示 + 重试按钮。"""
    st.error(f"⚠️ {str(error)[:120]}")
    st.button("重试", key=key, on_click=retry_cb)


# ─────────────────────────── 闭环进度条（stepper） ───────────────────────────

def stepper(steps: list[dict]) -> None:
    """横向步骤条：steps=[{label, ok: bool|None, note: str}, ...]，ok=None 表示未执行。"""
    chips = []
    for s in steps:
        label = s["label"]
        note = s.get("note", "")
        ok = s.get("ok")
        if ok is True:
            style = f"background:rgba(228,57,63,0.10);color:{UP};border:1px solid {UP}"
            mark = "✓"
        elif ok is False:
            style = f"background:rgba(46,158,68,0.10);color:{DOWN};border:1px solid {DOWN}"
            mark = "✗"
        else:
            style = "background:#EEF2F6;color:#8795A1"
            mark = "○"
        title = f' title="{note}"' if note else ""
        chips.append(
            f'<span style="display:inline-block;padding:5px 12px;border-radius:999px;'
            f'font-size:12px;margin:2px;{style}"{title}>{mark} {label}</span>'
        )
    st.markdown('<div style="margin:6px 0 14px">' + " ".join(chips) + '</div>',
                unsafe_allow_html=True)
