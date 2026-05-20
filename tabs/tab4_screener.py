"""Tab 4: 选股池 — 全A股行情筛选"""
import streamlit as st
import pandas as pd
from datetime import datetime
from data.screener import get_stock_list, screen_stocks, get_industry_list


def render():
    st.title("选股池")

    col_btn, col_info = st.columns([2, 3])
    with col_btn:
        refresh = st.button("🔄 刷新行情数据", use_container_width=True)
    with col_info:
        st.caption("数据每5分钟缓存一次，点击刷新获取最新行情")

    with st.spinner("正在获取全 A 股行情数据..."):
        try:
            full_df = get_stock_list(force_refresh=refresh)
        except Exception as e:
            st.error(f"获取行情数据失败: {e}")
            return

    if full_df.empty:
        st.warning("未能获取到股票数据，请检查网络后刷新重试")
        return

    st.caption(f"共 {len(full_df)} 只股票，数据时间: {datetime.now().strftime('%H:%M:%S')}")

    st.subheader("筛选条件")
    with st.expander("展开筛选", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            market = st.selectbox("市场板块", ["全部", "上海", "深圳", "北交所"])
        with c2:
            keyword = st.text_input("代码/名称搜索", placeholder="输入代码或名称关键字")
        with c3:
            price_min = st.number_input("最低价", 0.0, None, 0.0, step=0.1)
        with c4:
            price_max = st.number_input("最高价", 0.0, None, 0.0, step=0.1)

        with st.spinner("加载行业分类..."):
            industry_options = get_industry_list()
        selected_industries = st.multiselect(
            "行业板块（可多选，留空=全部）",
            options=industry_options,
            default=[],
            placeholder="选择行业板块，如 半导体、银行、军工...",
        )

        c5, c6 = st.columns(2)
        with c5:
            pct_min = st.number_input("最低涨跌幅 (%)", -20.0, 20.0, -20.0, step=0.1)
        with c6:
            pct_max = st.number_input("最高涨跌幅 (%)", -20.0, 20.0, 20.0, step=0.1)

        c7, c8 = st.columns(2)
        with c7:
            vol_min = st.number_input("最低成交量 (手)", 0, None, 0, step=10000)
        with c8:
            turnover_min = st.number_input("最低成交额 (元)", 0.0, None, 0.0, step=100000.0)

    result = screen_stocks(
        full_df,
        price_min=price_min if price_min > 0 else None,
        price_max=price_max if price_max > 0 else None,
        pct_min=pct_min if pct_min > -20 else None,
        pct_max=pct_max if pct_max < 20 else None,
        vol_min=vol_min if vol_min > 0 else None,
        turnover_min=turnover_min if turnover_min > 0 else None,
        keyword=keyword.strip(),
        market=market,
        industries=selected_industries if selected_industries else None,
    )

    st.subheader(f"筛选结果 ({len(result)} 只)")
    if result.empty:
        st.info("没有符合条件的股票，请放宽筛选条件")
    else:
        display_df = result.copy()
        show_cols = ["code", "name", "price", "change", "pct_change",
                     "open", "high", "low", "prev_close", "volume", "turnover",
                     "pe", "pb", "market_cap", "circulating_cap", "turnover_rate",
                     "buy", "sell", "ticktime"]
        show_cols = [c for c in show_cols if c in display_df.columns]
        display_df = display_df[show_cols]
        display_df["price"] = display_df["price"].round(2)
        display_df["pct_change"] = display_df["pct_change"].round(2)
        display_df["change"] = display_df["change"].round(2)
        display_df["volume"] = display_df["volume"].astype(int)
        display_df["turnover"] = display_df["turnover"].astype(int)
        if "pe" in display_df.columns:
            display_df["pe"] = display_df["pe"].round(1)
        if "pb" in display_df.columns:
            display_df["pb"] = display_df["pb"].round(2)
        if "market_cap" in display_df.columns:
            display_df["market_cap"] = display_df["market_cap"].fillna(0).astype(int)
        if "circulating_cap" in display_df.columns:
            display_df["circulating_cap"] = display_df["circulating_cap"].fillna(0).astype(int)
        if "turnover_rate" in display_df.columns:
            display_df["turnover_rate"] = display_df["turnover_rate"].round(2)
        display_df = display_df.rename(columns={
            "code": "代码", "name": "名称", "price": "最新价",
            "pct_change": "涨跌幅(%)", "change": "涨跌额",
            "open": "今开", "high": "最高", "low": "最低",
            "prev_close": "昨收", "volume": "成交量(手)", "turnover": "成交额(元)",
            "pe": "PE(市盈率)", "pb": "PB(市净率)",
            "market_cap": "总市值", "circulating_cap": "流通市值",
            "turnover_rate": "换手率(%)",
            "buy": "买入价", "sell": "卖出价",
            "ticktime": "更新时间",
        })
        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "代码": st.column_config.TextColumn(width="small"),
                "名称": st.column_config.TextColumn(width="small"),
                "涨跌幅(%)": st.column_config.NumberColumn(format="%.2f%%"),
            },
        )
        st.caption("💡 点击表头可排序，筛选条件同时生效以缩小范围")
