"""Tab 5: 资金净流入 TOP50"""
import streamlit as st
from data.screener import get_top_capital_inflow, get_fund_flow_data
from utils import fmt_yuan


def render():
    st.title("资金净流入 TOP50")
    st.caption("主力资金净流入最多的50只个股（数据源: 同花顺）")

    col_btn5, col_info5 = st.columns([2, 3])
    with col_btn5:
        refresh_flow = st.button("🔄 刷新资金流向", use_container_width=True, key="refresh_flow")
    with col_info5:
        st.caption("数据每5分钟缓存一次，首次加载需等待30秒左右")

    flow_search = st.text_input("🔍 搜索代码/名称", key="search_inflow", placeholder="输入股票代码或名称，从全市场搜索...")

    with st.spinner("正在获取资金流向数据..."):
        try:
            if flow_search:
                full_data = get_fund_flow_data()
                kw = flow_search.lower()
                display_flow = full_data[
                    full_data["code"].astype(str).str.contains(kw) |
                    full_data["name"].astype(str).str.lower().str.contains(kw)
                ].copy()
            else:
                display_flow = get_top_capital_inflow(50).copy()
        except Exception as e:
            st.error(f"获取资金流向失败: {e}")
            st.stop()

    if not display_flow.empty:
        display_flow["price"] = display_flow["price"].round(2)
        display_flow["pct_change"] = display_flow["pct_change"].round(2)
        display_flow["主力净流入"] = display_flow["main_capital"].apply(lambda x: fmt_yuan(x, signed=True))
        display_flow["散户资金"] = display_flow["retail_money"].apply(lambda x: fmt_yuan(x, signed=True))
        display_flow = display_flow.rename(columns={
            "code": "代码", "name": "名称", "price": "最新价",
            "pct_change": "涨跌幅(%)", "main_capital": "主力净流入(元)",
            "retail_money": "散户资金(元)",
        })
        st.dataframe(
            display_flow,
            use_container_width=True,
            hide_index=True,
            column_config={
                "涨跌幅(%)": st.column_config.NumberColumn(format="%.2f%%"),
            },
        )
    else:
        st.info("暂无资金流向数据" if not flow_search else f"未找到匹配 '{flow_search}' 的股票")
