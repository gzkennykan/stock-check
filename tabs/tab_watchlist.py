"""Tab ⭐ 自选股 — 盯盘面板，实时行情 + 盈亏追踪"""
import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime

from data.database import (
    add_to_watchlist, remove_from_watchlist, get_watchlist, get_stock_name_map,
)
from data.screener import get_stock_list


@st.cache_data(ttl=60)
def _get_realtime_quotes(codes: list[str]) -> pd.DataFrame:
    """获取自选股实时行情（来自缓存的 A 股行情数据）"""
    if not codes:
        return pd.DataFrame()
    try:
        all_stocks = get_stock_list()
        if all_stocks.empty:
            return pd.DataFrame()
        quotes = all_stocks[all_stocks["code"].isin(codes)].copy()
        return quotes
    except Exception:
        return pd.DataFrame()


def render():
    st.title("⭐ 自选股")
    st.caption("盯盘面板 — 实时行情 | 涨跌排序 | 快速诊断")

    # ── 添加自选 ──
    add_col1, add_col2 = st.columns([3, 1])
    with add_col1:
        new_code = st.text_input(
            "添加自选股（代码或名称）",
            placeholder="600519 或 贵州茅台",
            key="wl_add",
        )
    with add_col2:
        if st.button("➕ 添加", use_container_width=True, key="wl_add_btn"):
            if new_code.strip():
                raw = new_code.strip()
                name_map = get_stock_name_map()
                code = None
                name = ""
                if raw.isdigit() and len(raw) == 6:
                    code = raw.zfill(6)
                    name = name_map.get(code, "")
                else:
                    # 按名称搜索
                    lowered = raw.lower().replace(" ", "")
                    for c, n in name_map.items():
                        if n and lowered in n.lower().replace(" ", ""):
                            code = c
                            name = n
                            break

                if code:
                    add_to_watchlist(code, name)
                    st.success(f"✅ 已添加 {code} {name}")
                    st.rerun()
                else:
                    st.error(f"未找到「{raw}」")

    st.divider()

    # ── 自选股列表 ──
    wl_df = get_watchlist()
    if wl_df.empty:
        st.info("👆 添加你的自选股，实时追踪行情")
        return

    codes = wl_df["symbol"].tolist()

    # 获取实时行情
    quotes = _get_realtime_quotes(codes)

    if quotes.empty:
        st.warning("无法获取实时行情，请刷新重试")
        st.dataframe(wl_df, use_container_width=True, hide_index=True)
        return

    # ── 行情卡片 ──
    st.subheader(f"📊 自选行情 ({len(codes)} 只)")

    # 统计卡片
    qc1, qc2, qc3, qc4 = st.columns(4)
    up_count = int((quotes["pct_change"] > 0).sum()) if "pct_change" in quotes.columns else 0
    down_count = int((quotes["pct_change"] < 0).sum()) if "pct_change" in quotes.columns else 0
    flat_count = len(quotes) - up_count - down_count
    avg_pct = quotes["pct_change"].mean() if "pct_change" in quotes.columns else 0

    with qc1:
        st.metric("📈 上涨", f"{up_count} 只")
    with qc2:
        st.metric("📉 下跌", f"{down_count} 只")
    with qc3:
        st.metric("➖ 平盘", f"{flat_count} 只")
    with qc4:
        st.metric("均涨跌", f"{avg_pct:.2f}%",
                  delta=f"{up_count - down_count}")

    # 排序选项
    sort_col1, sort_col2 = st.columns([2, 3])
    with sort_col1:
        sort_by = st.selectbox(
            "排序",
            ["涨跌幅(%)", "最新价"],
            key="wl_sort",
        )
    sort_asc = sort_by == "最新价"  # 价格升序

    # 构建显示表
    display = quotes.merge(wl_df[["symbol", "note"]], left_on="code", right_on="symbol", how="left")
    display["名称"] = display["code"].map(get_stock_name_map()).fillna(display.get("name", ""))

    show_cols = ["code", "名称", "price", "pct_change", "volume", "turnover"]
    if "pe" in display.columns:
        show_cols.append("pe")
    if "market_cap" in display.columns:
        show_cols.append("market_cap")
    show_cols += ["note"]
    show_cols = [c for c in show_cols if c in display.columns]

    display = display[show_cols]

    if "pct_change" in display.columns:
        display = display.sort_values("pct_change", ascending=sort_asc)

    # 格式化
    display = display.rename(columns={
        "code": "代码", "price": "最新价", "pct_change": "涨跌幅(%)",
        "volume": "成交量(手)", "turnover": "成交额",
        "pe": "PE", "market_cap": "市值",
        "note": "备注",
    })

    # 彩色高亮
    def _color_pct(val):
        try:
            v = float(val)
            if v > 2:
                return "background-color: #C8E6C9; font-weight: bold"
            elif v > 0:
                return "background-color: #E8F5E9"
            elif v < -2:
                return "background-color: #FFCDD2; font-weight: bold"
            elif v < 0:
                return "background-color: #FFEBEE"
        except:
            pass
        return ""

    styled = display.style.applymap(
        _color_pct,
        subset=["涨跌幅(%)"] if "涨跌幅(%)" in display.columns else [],
    )

    st.dataframe(
        styled,
        use_container_width=True,
        hide_index=True,
        column_config={
            "涨跌幅(%)": st.column_config.NumberColumn(format="%.2f%%"),
            "最新价": st.column_config.NumberColumn(format="%.2f"),
            "代码": st.column_config.TextColumn(width="small"),
            "名称": st.column_config.TextColumn(width="small"),
        },
    )

    # ── 操作按钮 ──
    st.divider()
    op_col1, op_col2, op_col3 = st.columns(3)

    with op_col1:
        # 批量诊断
        selected_for_diag = st.multiselect(
            "选择诊断",
            options=codes,
            format_func=lambda c: f"{c} — {get_stock_name_map().get(c, '')}",
            key="wl_diag_sel",
            max_selections=5,
        )
        if selected_for_diag and st.button("🔬 诊断选中", key="wl_diag_btn"):
            st.session_state.wf_quick_diag_code = selected_for_diag[0]
            st.session_state.wf_quick_diag_trigger = True
            st.rerun()

    with op_col2:
        # 移除自选
        remove_code = st.selectbox(
            "移除自选",
            options=[""] + codes,
            format_func=lambda c: f"{c} — {get_stock_name_map().get(c, '')}" if c else "选择...",
            key="wl_remove",
        )
        if remove_code and st.button("🗑️ 移除", key="wl_remove_btn"):
            remove_from_watchlist(remove_code)
            st.success(f"已移除 {remove_code}")
            st.rerun()

    with op_col3:
        # 清空全部
        if st.button("🗑️ 清空全部自选", key="wl_clear_all"):
            for c in codes:
                remove_from_watchlist(c)
            st.success("已清空")
            st.rerun()

    # 导出
    csv = display.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "📥 导出 CSV", data=csv,
        file_name=f"watchlist_{datetime.now().strftime('%Y%m%d')}.csv",
        mime="text/csv",
    )
