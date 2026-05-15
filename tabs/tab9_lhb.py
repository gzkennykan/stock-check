"""Tab 9: 龙虎榜 — 上榜个股 & 席位明细"""
import streamlit as st
import pandas as pd
from datetime import datetime
from data.lhb import get_lhb_daily, get_lhb_seat_detail
from utils import fmt_wan, latest_trading_day, is_weekend


def render():
    st.title("🐉 龙虎榜")
    st.caption("当日上榜个股，含席位买卖明细、上榜天数、机构动向（数据源: 新浪财经）")

    col_lhb1, col_lhb2, col_lhb3 = st.columns([2, 2, 2])
    with col_lhb1:
        default_date = latest_trading_day()
        lhb_date = st.date_input("上榜日期", value=default_date)
    with col_lhb2:
        st.write("")
        st.write("")
        refresh_lhb = st.button("🔄 刷新数据", use_container_width=True, key="refresh_lhb")
    with col_lhb3:
        st.write("")
        st.caption("数据每5分钟缓存一次")

    if is_weekend(lhb_date):
        st.warning("⚠️ 所选日期为周末休市日，龙虎榜数据需在交易日才会更新。请选择周一至周五的日期。")

    lhb_date_str = lhb_date.strftime("%Y%m%d")
    lhb_date_dash = lhb_date.strftime("%Y-%m-%d")

    with st.spinner("正在获取龙虎榜数据..."):
        try:
            lhb_df = get_lhb_daily(date=lhb_date_str, force_refresh=refresh_lhb)
        except Exception as e:
            st.error(f"获取龙虎榜数据失败: {e}")
            st.stop()

    if lhb_df.empty:
        st.warning(f"{lhb_date_str} 暂无龙虎榜上榜数据（可能非交易日或数据未更新）")
        st.stop()

    st.caption(f"共 {len(lhb_df)} 只上榜股票")

    search_lhb = st.text_input("🔍 搜索代码/名称", key="search_lhb", placeholder="输入股票代码或名称过滤...")

    df_display = lhb_df.copy()
    if search_lhb:
        kw = search_lhb.lower()
        df_display = df_display[
            df_display["code"].astype(str).str.contains(kw) |
            df_display["name"].astype(str).str.lower().str.contains(kw)
        ]
        if df_display.empty:
            st.info(f"未找到匹配 '{search_lhb}' 的上榜股票")
            st.stop()

    tbl = df_display.copy()
    tbl["close"] = tbl["close"].round(2)
    tbl["pct_change"] = tbl["pct_change"].round(2)
    tbl["turnover"] = tbl["turnover"].fillna(0).astype(int)

    tbl["成交额"] = tbl["turnover"].apply(fmt_wan)
    tbl["净买入"] = tbl["net_buy"].apply(lambda x: fmt_wan(x, signed=True))
    tbl["机构买入"] = tbl["inst_buy"].apply(fmt_wan)
    tbl["机构卖出"] = tbl["inst_sell"].apply(fmt_wan)
    tbl["5日累计买"] = tbl["accum_buy"].apply(fmt_wan)
    tbl["5日累计卖"] = tbl["accum_sell"].apply(fmt_wan)

    tbl_display = tbl.rename(columns={
        "code": "代码", "name": "名称", "close": "收盘价",
        "pct_change": "涨跌幅(%)", "onboard_days": "上榜天数",
        "buy_seat_count": "买入席位", "sell_seat_count": "卖出席位",
        "reason": "上榜原因",
    })

    show_cols = ["代码", "名称", "收盘价", "涨跌幅(%)", "成交额", "净买入",
                 "上榜天数", "机构买入", "机构卖出",
                 "5日累计买", "5日累计卖",
                 "买入席位", "卖出席位", "上榜原因"]
    show_cols = [c for c in show_cols if c in tbl_display.columns]

    st.dataframe(
        tbl_display[show_cols],
        use_container_width=True,
        hide_index=True,
        column_config={
            "涨跌幅(%)": st.column_config.NumberColumn(format="%.2f%%"),
            "代码": st.column_config.TextColumn(width="small"),
            "名称": st.column_config.TextColumn(width="small"),
        },
    )

    # ─── 席位明细（可展开） ───
    st.divider()
    st.subheader("🔍 查看个股席位明细")
    lhb_codes = list(df_display["code"].unique())
    selected_lhb = st.selectbox(
        "选择上榜股票",
        options=lhb_codes,
        format_func=lambda c: f"{c} — {df_display[df_display['code']==c]['name'].values[0]}",
        key="lhb_select",
    )

    if selected_lhb:
        with st.spinner(f"获取 {selected_lhb} 席位明细..."):
            try:
                seat_df = get_lhb_seat_detail(selected_lhb, lhb_date_dash,
                                              force_refresh=refresh_lhb)
            except Exception as e:
                st.error(f"获取席位明细失败: {e}")
                seat_df = pd.DataFrame()

        if seat_df.empty:
            st.info(f"{selected_lhb} 席位明细暂无数据")
        else:
            buy_seats = seat_df[seat_df["side"] == "买入"].sort_values("buy_amount", ascending=False).head(5)
            sell_seats = seat_df[seat_df["side"] == "卖出"].sort_values("sell_amount", ascending=False).head(5)

            c_left, c_right = st.columns(2)
            with c_left:
                st.markdown("### 🟢 买入前5席位")
                if buy_seats.empty:
                    st.caption("无买入数据")
                else:
                    buy_show = buy_seats[["seat_name", "buy_amount", "sell_amount", "net_amount"]].copy()
                    buy_show.columns = ["营业部", "买入(万)", "卖出(万)", "净额(万)"]
                    for c in ["买入(万)", "卖出(万)", "净额(万)"]:
                        buy_show[c] = buy_show[c].round(1)
                    st.dataframe(buy_show, use_container_width=True, hide_index=True)

            with c_right:
                st.markdown("### 🔴 卖出前5席位")
                if sell_seats.empty:
                    st.caption("无卖出数据")
                else:
                    sell_show = sell_seats[["seat_name", "buy_amount", "sell_amount", "net_amount"]].copy()
                    sell_show.columns = ["营业部", "买入(万)", "卖出(万)", "净额(万)"]
                    for c in ["买入(万)", "卖出(万)", "净额(万)"]:
                        sell_show[c] = sell_show[c].round(1)
                    st.dataframe(sell_show, use_container_width=True, hide_index=True)
