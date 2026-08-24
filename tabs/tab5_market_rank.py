"""Tab 5: 资金排名 — 资金净额/成交额 TOP50"""
import streamlit as st
from data.screener import get_fund_flow_data, get_stock_list, get_top_turnover
from utils import fmt_yuan, search_stocks, format_stock_display, style_pct_col

VIEWS = {
    "inflow": {"title": "资金净流入 TOP50", "source": "同花顺"},
    "outflow": {"title": "资金净流出 TOP50", "source": "同花顺"},
    "turnover": {"title": "成交额 TOP50", "source": "新浪行情"},
}


def render():
    st.title("资金排名")
    st.caption("ℹ️ 「资金净流入/净流出」采用同花顺统计口径（按单笔成交额分档推断主力，非逐笔精确数据）；"
               "同一股票在不同软件(同花顺/东财/通达信)口径下数值可能有差异，建议用于方向与相对强弱参考。")

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
        refresh = st.button("🔄 刷新数据", width='stretch', key="rank_refresh")
    with col_info:
        data_date = st.session_state.get("_fund_flow_date")
        err = st.session_state.get("_fund_flow_error")
        if view != "turnover" and data_date:
            st.caption(f"📅 {data_date} — K线+资金流")
        elif view != "turnover" and err:
            st.caption(f"⚠️ {err}")
        else:
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
    if view in ("inflow", "outflow"):
        label = "资金净流入" if view == "inflow" else "资金净流出"
        display[label] = display["main_capital"].apply(lambda x: fmt_yuan(x, signed=True))
        if "capital_inflow" in display.columns:
            display["流入资金"] = display["capital_inflow"].apply(fmt_yuan)
        if "capital_outflow" in display.columns:
            display["流出资金"] = display["capital_outflow"].apply(fmt_yuan)
        if "turnover" in display.columns:
            display["成交额显示"] = display["turnover"].apply(fmt_yuan)
            display["净额占比"] = display.apply(
                lambda r: f"{r['main_capital']/r['turnover']*100:+.1f}%"
                if r.get("turnover", 0) > 0 else "N/A", axis=1
            )
        display = format_stock_display(display,
            drop_after=["main_capital", "capital_inflow", "capital_outflow",
                        "hot_money", "retail_money", "net_flow_pct"])
    else:
        display["成交额显示"] = display["turnover"].apply(fmt_yuan)
        display = format_stock_display(display)

    # 去掉原始「成交额(元)」列（避免大数字显示成科学计数法），统一用「成交额」亿格式
    display = display.drop(columns=["成交额(元)"], errors="ignore")
    display = display.rename(columns={"成交额显示": "成交额"})

    col_cfg = {"涨跌幅(%)": st.column_config.NumberColumn(format="%.2f%%")}
    if "最新价" in display.columns:
        col_cfg["最新价"] = st.column_config.NumberColumn(format="%.2f")
    if "换手率(%)" in display.columns:
        col_cfg["换手率(%)"] = st.column_config.NumberColumn(format="%.2f%%")

    st.dataframe(
        style_pct_col(display.style, "涨跌幅(%)"), width='stretch', hide_index=True,
        column_config=col_cfg,
    )
