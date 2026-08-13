"""Tab 信号验证：选股信号后验证闭环 — 统计 T+N 后真实命中率与超额收益"""
import streamlit as st
import pandas as pd

from data.signal_tracker import validate_signals, summarize_validation
from data.database import get_signal_records
from utils import round_df


def render():
    st.title("📊 信号后验证")
    st.caption("记录每日选股信号 → T+N 交易日后统计真实命中率与超额收益（vs 沪深300）")

    fwd_days = st.multiselect(
        "验证周期", [1, 5, 20], default=[5, 20],
        format_func=lambda x: f"T+{x}", key="sv_periods",
    )
    if not fwd_days:
        st.info("请至少选择一个验证周期")
        return

    recs = get_signal_records()
    if recs.empty:
        st.info("暂无信号记录。请先到「智能选股」页点击「📝 记录信号」。")
        return

    # ── 汇总统计 ──
    summary = summarize_validation(forward_days=tuple(fwd_days))
    if summary.empty:
        st.warning("信号记录数据不足（可能尚无 T+N 之后的行情），暂时无法验证。")
    else:
        st.subheader("📈 汇总统计（按来源 × 周期）")
        st.dataframe(round_df(summary), width='stretch', hide_index=True)
        st.caption("命中率 = 前向收益 > 0 的比例；超额胜率 = 跑赢沪深300 的比例")

    # ── 信号明细 ──
    st.subheader("📋 信号明细")
    detail = validate_signals(forward_days=tuple(fwd_days))
    if detail.empty:
        st.info("明细暂无数据（信号日后行情不足）。")
    else:
        show = detail.copy()
        for c in ("fwd_return", "bench_return", "excess_return"):
            if c in show.columns:
                show[c] = show[c].apply(lambda x: f"{x*100:+.2f}%" if pd.notna(x) else "N/A")
        show = show.rename(columns={
            "signal_date": "信号日", "symbol": "代码", "name": "名称",
            "source": "来源", "forward_days": "周期",
            "fwd_return": "前向收益", "bench_return": "基准收益", "excess_return": "超额收益",
        })
        st.dataframe(show, width='stretch', hide_index=True)

    # ── 最近记录 ──
    st.subheader("🕐 最近信号记录")
    recent = recs.head(100).copy()
    recent["signal_date"] = recent["signal_date"].dt.strftime("%Y-%m-%d")
    recent = recent.rename(columns={
        "signal_date": "信号日", "symbol": "代码", "name": "名称",
        "source": "来源", "signal_price": "信号价", "score": "评分",
    })
    st.dataframe(round_df(recent), width='stretch', hide_index=True)
