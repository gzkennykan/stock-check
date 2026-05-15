"""Tab 7: 成交额 TOP50"""
import streamlit as st
from data.screener import get_top_turnover, get_stock_list
from utils import fmt_yuan


def render():
    st.title("成交额 TOP50")
    st.caption("当日成交额最多的50只个股（数据源: 新浪行情）")

    col_btn6, col_info6 = st.columns([2, 3])
    with col_btn6:
        refresh_turn = st.button("🔄 刷新行情", use_container_width=True, key="refresh_turn")
    with col_info6:
        st.caption("数据每5分钟缓存一次")

    turn_search = st.text_input("🔍 搜索代码/名称", key="search_turnover", placeholder="输入股票代码或名称，从全市场搜索...")

    with st.spinner("正在获取成交额排行..."):
        try:
            if turn_search:
                full_data = get_stock_list()
                kw = turn_search.lower()
                display_turn = full_data[
                    full_data["code"].astype(str).str.contains(kw) |
                    full_data["name"].astype(str).str.lower().str.contains(kw)
                ].copy()
            else:
                display_turn = get_top_turnover(50).copy()
        except Exception as e:
            st.error(f"获取成交额排行失败: {e}")
            st.stop()

    if not display_turn.empty:
        display_turn["price"] = display_turn["price"].round(2)
        display_turn["pct_change"] = display_turn["pct_change"].round(2)
        display_turn["turnover"] = display_turn["turnover"].astype(int)
        display_turn["成交额显示"] = display_turn["turnover"].apply(fmt_yuan)
        display_turn = display_turn.rename(columns={
            "code": "代码", "name": "名称", "price": "最新价",
            "pct_change": "涨跌幅(%)", "turnover": "成交额(元)",
        })
        st.dataframe(
            display_turn,
            use_container_width=True,
            hide_index=True,
            column_config={
                "涨跌幅(%)": st.column_config.NumberColumn(format="%.2f%%"),
            },
        )
    else:
        st.info("暂无成交额数据" if not turn_search else f"未找到匹配 '{turn_search}' 的股票")
