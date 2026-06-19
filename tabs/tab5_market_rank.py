"""Tab 5: 资金排名 — 主力流入/流出/成交额 TOP50 三合一"""
import streamlit as st
from data.screener import get_fund_flow_data, get_stock_list, get_top_turnover
from utils import fmt_yuan

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
        st.caption(f"数据源: {VIEWS[view]['source']}，每5分钟缓存")

    kw = st.text_input("🔍 搜索代码/名称", key="rank_search",
                       placeholder="输入股票代码或名称从全市场搜索...")

    with st.spinner("加载中..."):
        try:
            if view == "turnover":
                if kw:
                    full = get_stock_list()
                    mask = (full["code"].astype(str).str.contains(kw.lower()) |
                            full["name"].astype(str).str.lower().str.contains(kw.lower()))
                    display = full[mask].copy()
                else:
                    display = get_top_turnover(50).copy()
            else:
                full = get_fund_flow_data()
                full = full[~full["name"].astype(str).str.contains("ST|退")]
                if kw:
                    mask = (full["code"].astype(str).str.contains(kw.lower()) |
                            full["name"].astype(str).str.lower().str.contains(kw.lower()))
                    display = full[mask].copy()
                else:
                    asc = (view == "outflow")
                    display = full.sort_values("main_capital", ascending=asc).head(50).copy()
        except Exception as e:
            st.error(f"数据加载失败: {e}")
            return

    if display.empty:
        st.info("暂无数据" if not kw else f"未找到匹配 '{kw}' 的股票")
        return

    display["price"] = display["price"].round(2)
    display["pct_change"] = display["pct_change"].round(2)
    if "volume" in display.columns:
        display["volume"] = display["volume"].fillna(0).astype(int)
    if "turnover" in display.columns:
        display["turnover"] = display["turnover"].fillna(0).astype(int)

    # 资金流视图
    if view in ("inflow", "outflow"):
        label = "资金净流入" if view == "inflow" else "资金净流出"
        display[label] = display["main_capital"].apply(lambda x: fmt_yuan(x, signed=True))
        if "capital_inflow" in display.columns:
            display["流入资金"] = display["capital_inflow"].apply(fmt_yuan)
        if "capital_outflow" in display.columns:
            display["流出资金"] = display["capital_outflow"].apply(fmt_yuan)
        if "turnover_rate" in display.columns:
            display["换手率(%)"] = display["turnover_rate"]
        drop_cols = ["main_capital", "capital_inflow", "capital_outflow", "turnover_rate", "hot_money", "retail_money", "net_flow_pct"]
        display = display.drop(columns=[c for c in drop_cols if c in display.columns], errors="ignore")
    else:
        display["成交额显示"] = display["turnover"].apply(fmt_yuan)

    display = display.rename(columns={
        "code": "代码", "name": "名称", "price": "最新价", "pct_change": "涨跌幅(%)",
        "volume": "成交量(手)", "turnover": "成交额(元)",
        "pe": "市盈率", "pb": "市净率",
        "market_cap": "总市值", "circulating_cap": "流通市值",
        "turnover_rate": "换手率(%)",
        "open": "今开", "high": "最高", "low": "最低", "prev_close": "昨收",
        "change": "涨跌额",
    })

    st.dataframe(
        display,
        use_container_width=True, hide_index=True,
        column_config={
            "涨跌幅(%)": st.column_config.NumberColumn(format="%.2f%%"),
        },
    )
