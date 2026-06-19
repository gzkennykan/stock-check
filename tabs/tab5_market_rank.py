"""Tab 5: 资金排名 — 资金净额/成交额 TOP50"""
import streamlit as st
from data.screener import get_fund_flow_data, get_stock_list, get_top_turnover
from utils import fmt_yuan, search_stocks, format_stock_display

VIEWS = {
    "inflow": {"title": "资金净流入 TOP50", "source": "同花顺"},
    "outflow": {"title": "资金净流出 TOP50", "source": "同花顺"},
    "turnover": {"title": "成交额 TOP50", "source": "新浪行情"},
}


def render():
    st.title("资金排名")

    col_view, col_refresh, col_info = st.columns([2, 2, 3])
    with col_view:
        view = st.selectbox(
            "排行类型",
            options=["inflow", "outflow", "turnover"],
            format_func=lambda v: {"inflow": "资金净流入 TOP50",
                                   "outflow": "资金净流出 TOP50",
                                   "turnover": "成交额 TOP50"}[v],
            key="rank_view",
        )
    with col_refresh:
        refresh = st.button("🔄 刷新数据", use_container_width=True, key="rank_refresh")
    with col_info:
        st.caption(f"数据源: {VIEWS[view]['source']} (DuckDB)")

    kw = st.text_input("🔍 搜索代码/名称", key="rank_search",
                       placeholder="输入股票代码或名称从全市场搜索...")

    with st.spinner("加载中..."):
        try:
            if view == "turnover":
                full = get_stock_list()
                display = search_stocks(full, kw).copy()
                if not kw:
                    display = get_top_turnover(50).copy()
            else:
                full = get_fund_flow_data()
                full = full[~full["name"].astype(str).str.contains("ST|退")]
                display = search_stocks(full, kw).copy()
                if not kw:
                    asc = (view == "outflow")
                    display = full.sort_values("main_capital", ascending=asc).head(50).copy()
        except Exception as e:
            st.error(f"数据加载失败: {e}")
            return

    if display.empty:
        st.info("暂无数据" if not kw else f"未找到匹配 '{kw}' 的股票")
        return

    # 资金流特殊列
    extra_cols = {}
    if view in ("inflow", "outflow"):
        label = "资金净流入" if view == "inflow" else "资金净流出"
        display[label] = display["main_capital"].apply(lambda x: fmt_yuan(x, signed=True))
        if "capital_inflow" in display.columns:
            display["流入资金"] = display["capital_inflow"].apply(fmt_yuan)
        if "capital_outflow" in display.columns:
            display["流出资金"] = display["capital_outflow"].apply(fmt_yuan)
        if "turnover" in display.columns:
            display["净额占比"] = display.apply(
                lambda r: f"{r['main_capital']/r['turnover']*100:+.1f}%"
                if r.get("turnover", 0) > 0 else "N/A", axis=1
            )
        display = format_stock_display(display,
            drop_after=["main_capital", "capital_inflow", "capital_outflow",
                        "turnover_rate", "hot_money", "retail_money", "net_flow_pct"])
    else:
        display["成交额显示"] = display["turnover"].apply(fmt_yuan)
        display = format_stock_display(display)

    st.dataframe(
        display, use_container_width=True, hide_index=True,
        column_config={"涨跌幅(%)": st.column_config.NumberColumn(format="%.2f%%")},
    )
