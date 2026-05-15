"""Tab 6: 资金净流出 TOP50"""
import streamlit as st
from data.screener import get_top_capital_outflow, get_fund_flow_data
from utils import fmt_yuan


def render():
    st.title("资金净流出 TOP50")
    st.caption("主力资金净流出最多的50只个股（数据源: 同花顺）")

    col_btn6, col_info6 = st.columns([2, 3])
    with col_btn6:
        refresh_out = st.button("🔄 刷新资金流向", use_container_width=True, key="refresh_outflow")
    with col_info6:
        st.caption("数据每5分钟缓存一次，与流入数据共享缓存")

    out_search = st.text_input("🔍 搜索代码/名称", key="search_outflow", placeholder="输入股票代码或名称，从全市场搜索...")

    with st.spinner("正在获取资金流出排行..."):
        try:
            if out_search:
                full_data = get_fund_flow_data()
                kw = out_search.lower()
                display_out = full_data[
                    full_data["code"].astype(str).str.contains(kw) |
                    full_data["name"].astype(str).str.lower().str.contains(kw)
                ].copy()
            else:
                display_out = get_top_capital_outflow(50).copy()
        except Exception as e:
            st.error(f"获取资金流出排行失败: {e}")
            st.stop()

    if not display_out.empty:
        display_out["price"] = display_out["price"].round(2)
        display_out["pct_change"] = display_out["pct_change"].round(2)
        display_out["主力净流出"] = display_out["main_capital"].apply(lambda x: fmt_yuan(x, signed=True))
        display_out["散户资金"] = display_out["retail_money"].apply(lambda x: fmt_yuan(x, signed=True))
        display_out = display_out.rename(columns={
            "code": "代码", "name": "名称", "price": "最新价",
            "pct_change": "涨跌幅(%)", "main_capital": "主力净流出(元)",
            "retail_money": "散户资金(元)",
        })
        st.dataframe(
            display_out,
            use_container_width=True,
            hide_index=True,
            column_config={
                "涨跌幅(%)": st.column_config.NumberColumn(format="%.2f%%"),
            },
        )
    else:
        st.info("暂无资金流出数据" if not out_search else f"未找到匹配 '{out_search}' 的股票")
