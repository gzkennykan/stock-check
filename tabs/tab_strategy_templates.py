"""Tab 策略模板 — 自定义选股规则模板 + 历史信号验证"""
import streamlit as st
import pandas as pd
from datetime import datetime

from data.strategy_templates import (
    TEMPLATES, get_template, backtest_template,
    validate_template, summarize_template, default_backtest_range,
)
from data.database import get_signal_records
from utils import round_df


def _render_params(tmpl: dict) -> dict:
    """按参数 schema 渲染输入控件，返回 params dict。"""
    params = {}
    for p in tmpl.get("params_schema", []):
        key = p["key"]
        label = p.get("label", key)
        default = p.get("default", 0)
        if isinstance(default, float):
            params[key] = st.number_input(
                label, value=float(default),
                min_value=float(p.get("min", 0.0)), max_value=float(p.get("max", 100.0)),
                step=float(p.get("step", 0.1)), key=f"stpl_{tmpl['id']}_{key}")
        else:
            params[key] = st.number_input(
                label, value=int(default),
                min_value=int(p.get("min", 0)), max_value=int(p.get("max", 1000)),
                step=int(p.get("step", 1)), key=f"stpl_{tmpl['id']}_{key}")
    return params


def _render_validation(source: str):
    """渲染某信号源的历史验证结果。"""
    summary = summarize_template(source.replace("template:", ""))
    if summary.empty:
        st.info("暂无验证结果。信号不足或需要更早的结束日期（需留出未来 T+20 交易日验证空间）")
        return

    st.subheader("📊 验证汇总")
    st.caption("按信号日收盘价为基准，统计 T+N 交易日后的收益与相对沪深300的超额收益")
    st.dataframe(round_df(summary), width='stretch', hide_index=True)

    # 核心指标卡
    for _, row in summary.iterrows():
        if row["周期"] == "T+20":
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.metric("样本数", int(row["样本数"]))
            with c2:
                st.metric("命中率(T+20)", f"{row['命中率%']:.1f}%" if pd.notna(row['命中率%']) else "N/A")
            with c3:
                st.metric("平均收益(T+20)", f"{row['平均收益%']:+.2f}%" if pd.notna(row['平均收益%']) else "N/A")
            with c4:
                st.metric("平均超额(T+20)", f"{row['平均超额%']:+.2f}%" if pd.notna(row['平均超额%']) else "N/A")
            break

    st.subheader("🔍 信号明细")
    detail = validate_template(source.replace("template:", ""))
    if not detail.empty:
        show = detail.copy()
        for c in ["fwd_return", "bench_return", "excess_return"]:
            if c in show.columns:
                show[c] = show[c].apply(
                    lambda x: f"{x * 100:+.2f}%" if pd.notna(x) else "N/A")
        st.dataframe(show, width='stretch', hide_index=True)


def render():
    st.title("📡 策略模板 & 历史验证")
    st.caption("把选股规则固化为模板 → 在历史各交易日回放 → 用信号验证闭环统计命中率/超额收益")
    st.caption("⚠️ 事件研究式验证：不含交易成本与仓位管理，反映「选股规则」本身的有效性，而非完整策略收益")

    col_t, col_desc = st.columns([1, 2])
    with col_t:
        tpl_id = st.selectbox(
            "选择模板",
            options=[t["id"] for t in TEMPLATES],
            format_func=lambda i: next(t["name"] for t in TEMPLATES if t["id"] == i),
            key="stpl_sel",
        )
    with col_desc:
        tmpl = get_template(tpl_id)
        st.info(tmpl["desc"])

    c_p1, c_p2 = st.columns([1, 1])
    with c_p1:
        params = _render_params(tmpl)
    with c_p2:
        st.markdown("#### 回测区间")
        default_start, default_end = default_backtest_range()
        start_date = st.date_input("起始日期", value=pd.to_datetime(default_start), key="stpl_start")
        end_date = st.date_input("结束日期", value=pd.to_datetime(default_end), key="stpl_end")
        interval_days = st.number_input("采样间隔（交易日）", value=5, min_value=1, max_value=30,
                                        step=1, key="stpl_interval")
        top_n = st.number_input("单日信号上限（0=不限）", value=0, min_value=0, max_value=100,
                                step=5, key="stpl_topn")

    if tmpl.get("slow"):
        st.warning("⚠️ 该模板每次扫描需全市场因子计算（约10秒/日期），历史回测较慢，建议增大采样间隔或缩短区间")

    if st.button("🚀 历史验证", type="primary", width='stretch', key="stpl_run"):
        src = f"template:{tpl_id}"
        with st.spinner(f"在 {start_date} ~ {end_date} 回放模板「{tmpl['name']}」..."):
            bt = backtest_template(
                tpl_id,
                start_date.strftime("%Y-%m-%d"),
                end_date.strftime("%Y-%m-%d"),
                interval_days=interval_days,
                params=params,
                top_n=top_n if top_n > 0 else None,
            )
        if bt is None:
            st.error("模板执行失败")
        else:
            st.success(f"回放完成：{bt['dates_run']} 个交易日，共记录 {bt['total_signals']} 条信号")
            with st.expander(f"逐日信号数（{len(bt['per_date'])} 个交易日）"):
                if bt["per_date"]:
                    st.dataframe(round_df(pd.DataFrame(bt["per_date"])), width='stretch', hide_index=True)
            _render_validation(src)
            st.session_state["stpl_last_source"] = src

    st.divider()

    # 最近信号记录（按当前选中的模板 source 过滤）
    src = f"template:{tpl_id}"
    st.subheader("📋 该模板最近信号")
    recs = get_signal_records(source=src, start=start_date.strftime("%Y-%m-%d"))
    if recs.empty:
        st.caption("暂无该模板信号，点击上方「历史验证」生成")
    else:
        show = recs.head(50).copy()
        show["signal_date"] = pd.to_datetime(show["signal_date"]).dt.date
        st.dataframe(show, width='stretch', hide_index=True)
