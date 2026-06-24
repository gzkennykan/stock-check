"""Tab 9: 强势股 — 龙虎榜 + 涨停板分析"""
import streamlit as st
import pandas as pd
from datetime import datetime
from data.lhb import get_lhb_daily, get_lhb_seat_detail
from utils import fmt_wan, latest_trading_day, is_weekend


def _fmt_zt_time(val):
    """格式化涨停时间: '092500' → '09:25:00' / '09:25' """
    if pd.isna(val):
        return "-"
    s = str(val).strip()
    if len(s) >= 6:
        return f"{s[:2]}:{s[2:4]}:{s[4:6]}"
    if len(s) >= 4:
        return f"{s[:2]}:{s[2:4]}"
    return s


def render():
    st.title("🐉 龙虎榜 & 涨停板")
    st.caption("追踪市场最强标的 — 龙虎榜席位 + 涨停池分析（数据源: 新浪财经 / 东方财富）")

    tab_z1, tab_z2, tab_z3 = st.tabs([
        "🐉 龙虎榜", "📈 涨停板", "💥 炸板监控"
    ])

    # ══════════════════════════════════════════
    # Tab 1: 龙虎榜 (已有功能)
    # ══════════════════════════════════════════
    with tab_z1:
        st.subheader("当日上榜个股 & 席位明细")

        col_lhb1, col_lhb2, col_lhb3 = st.columns([2, 2, 2])
        with col_lhb1:
            default_date = latest_trading_day()
            lhb_date = st.date_input("上榜日期", value=default_date, key="lhb_date")
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
                lhb_df = pd.DataFrame()

        if lhb_df.empty:
            st.warning(f"{lhb_date_str} 暂无龙虎榜上榜数据（可能非交易日或数据未更新）")
        else:
            st.caption(f"共 {len(lhb_df)} 只上榜股票")

            search_lhb = st.text_input("🔍 搜索代码/名称", key="search_lhb",
                                       placeholder="输入股票代码或名称过滤...")

            df_display = lhb_df.copy()
            if search_lhb:
                kw = search_lhb.lower()
                df_display = df_display[
                    df_display["code"].astype(str).str.contains(kw) |
                    df_display["name"].astype(str).str.lower().str.contains(kw)
                ]
                if df_display.empty:
                    st.info(f"未找到匹配 '{search_lhb}' 的上榜股票")

            if not df_display.empty:
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

    # ══════════════════════════════════════════
    # Tab 2: 涨停板分析 ✨
    # ══════════════════════════════════════════
    with tab_z2:
        st.subheader("今日涨停板分析")
        st.caption("涨停板池 + 连板梯队 + 封板强度（数据源: 东方财富）")

        col_z1, col_z2 = st.columns([2, 3])
        with col_z1:
            refresh_zt = st.button("🔄 刷新涨停数据", use_container_width=True, key="refresh_zt")
        with col_z2:
            st.caption("首次加载约需10秒")

        with st.spinner("正在获取涨停板数据..."):
            try:
                from data.zt_pool import get_zt_pool, get_zt_strong, get_zt_summary
                zt_df = get_zt_pool(force_refresh=refresh_zt)
                zt_strong = get_zt_strong(force_refresh=refresh_zt)
                zt_summary = get_zt_summary(force_refresh=refresh_zt)
            except Exception as e:
                st.error(f"获取涨停板数据失败: {e}")
                zt_df, zt_strong, zt_summary = pd.DataFrame(), pd.DataFrame(), {}

        if zt_df.empty:
            st.info("暂无涨停板数据（可能非交易日或数据尚未更新）")
        else:
            # ── 概览卡片 ──
            zt_count = zt_summary.get("zt_count", len(zt_df))
            broken_count = zt_summary.get("broken_count", 0)
            strong_count = zt_summary.get("strong_count", 0)

            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.metric("涨停家数", zt_count)
            with c2:
                st.metric("连板股", strong_count)
            with c3:
                st.metric("今日炸板", broken_count)
            with c4:
                br = zt_summary.get("broken_rate", 0)
                st.metric("炸板率", f"{br}%")

            # ── 连板梯队 ──
            board_dist = zt_summary.get("board_distribution", {})
            if board_dist:
                st.caption("**连板梯队分布**")
                board_cols = st.columns(min(8, len(board_dist)))
                for i, (days, cnt) in enumerate(sorted(board_dist.items())):
                    with board_cols[i % len(board_cols)]:
                        label = "首板" if days == 1 else f"{days}连板"
                        st.metric(label, cnt)

            # ── 涨停板列表 ──
            st.divider()
            st.caption(f"涨停板明细（共 {len(zt_df)} 只）")

            zt_search = st.text_input("🔍 搜索", key="search_zt",
                                      placeholder="代码/名称/行业...")

            zt_display = zt_df.copy()
            if zt_search:
                kw = zt_search.lower()
                zt_display = zt_display[
                    zt_display["code"].astype(str).str.contains(kw) |
                    zt_display["name"].astype(str).str.lower().str.contains(kw) |
                    zt_display.get("industry", pd.Series()).astype(str).str.lower().str.contains(kw)
                ]

            if not zt_display.empty:
                show = zt_display.copy()
                # Prepare display columns
                show["price"] = show.get("price", pd.NA)
                show["pct_change"] = show.get("pct_change", pd.NA)
                show["turnover_rate"] = show.get("turnover_rate", pd.NA)

                if "seal_fund_val" in show.columns:
                    show["封单(万)"] = show["seal_fund_val"].apply(
                        lambda x: f"{x:,.0f}" if pd.notna(x) else "-"
                    )
                elif "seal_fund" in show.columns:
                    show["封单"] = show["seal_fund"].astype(str)

                if "first_zt_time" in show.columns:
                    # 格式化时间: "092500" → "09:25"
                    show["封板时间"] = show["first_zt_time"].apply(_fmt_zt_time)
                elif "zt_time" in show.columns:
                    show["封板时间"] = show["zt_time"].apply(_fmt_zt_time)
                if "break_count" in show.columns:
                    show["炸板次数"] = show["break_count"]
                if "industry" in show.columns:
                    show["行业"] = show["industry"]

                display_cols = ["code", "name", "price", "pct_change", "turnover_rate"]
                extra = [c for c in ["封单(万)", "封单", "封板时间", "炸板次数", "行业"] if c in show.columns]
                display_cols.extend(extra)
                display_cols = [c for c in display_cols if c in show.columns]

                show = show[display_cols]
                show = show.rename(columns={
                    "code": "代码", "name": "名称", "price": "最新价",
                    "pct_change": "涨跌幅(%)", "turnover_rate": "换手率(%)",
                })

                st.dataframe(
                    show,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "涨跌幅(%)": st.column_config.NumberColumn(format="%.2f%%"),
                        "换手率(%)": st.column_config.NumberColumn(format="%.2f"),
                        "代码": st.column_config.TextColumn(width="small"),
                        "名称": st.column_config.TextColumn(width="small"),
                    },
                )
            else:
                if zt_search:
                    st.info(f"未找到匹配 '{zt_search}' 的涨停股")

            # ── 强势股（连板） ──
            if not zt_strong.empty:
                st.divider()
                st.subheader("🔥 强势连板股")
                strong_display = zt_strong.copy()
                scols = ["code", "name", "price", "pct_change", "turnover_rate"]
                if "consecutive_days" in strong_display.columns:
                    scols.append("consecutive_days")
                if "industry" in strong_display.columns:
                    scols.append("industry")
                scols = [c for c in scols if c in strong_display.columns]
                strong_display = strong_display[scols]
                strong_display = strong_display.rename(columns={
                    "code": "代码", "name": "名称", "price": "最新价",
                    "pct_change": "涨跌幅(%)", "turnover_rate": "换手率(%)",
                    "consecutive_days": "连板天数", "industry": "行业",
                })
                st.dataframe(
                    strong_display,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "涨跌幅(%)": st.column_config.NumberColumn(format="%.2f%%"),
                        "代码": st.column_config.TextColumn(width="small"),
                        "名称": st.column_config.TextColumn(width="small"),
                    },
                )

            # ── 行业分布 ──
            top_inds = zt_summary.get("top_industries", {})
            if top_inds:
                st.divider()
                st.caption("**涨停行业分布 TOP10**")
                ind_cols = st.columns(5)
                for i, (ind, cnt) in enumerate(list(top_inds.items())[:10]):
                    with ind_cols[i % 5]:
                        st.metric(ind, f"{cnt}只")

    # ══════════════════════════════════════════
    # Tab 3: 炸板监控 ✨
    # ══════════════════════════════════════════
    with tab_z3:
        st.subheader("炸板监控")
        st.caption("涨停后打开的股票 — 封板失败，警惕短期风险（数据源: 东方财富）")

        if st.button("🔄 刷新炸板数据", use_container_width=True, key="refresh_broken"):
            st.cache_data.clear()

        with st.spinner("获取炸板数据..."):
            try:
                from data.zt_pool import get_zt_broken
                broken_df = get_zt_broken(force_refresh=refresh_zt if 'refresh_zt' in dir() else False)
            except Exception as e:
                st.error(f"获取炸板数据失败: {e}")
                broken_df = pd.DataFrame()

        if broken_df.empty:
            st.info("今日暂无炸板股票 🎉")
        else:
            st.warning(f"今日共 {len(broken_df)} 只股票炸板")

            b_display = broken_df.copy()
            bcols = ["code", "name", "price", "pct_change", "turnover_rate"]
            if "break_count" in b_display.columns:
                bcols.append("break_count")
            if "industry" in b_display.columns:
                bcols.append("industry")
            if "turnover" in b_display.columns:
                b_display["成交额(万)"] = (b_display["turnover"] / 10000).round(0).astype(int)
                bcols.append("成交额(万)")

            bcols = [c for c in bcols if c in b_display.columns]
            b_display = b_display[bcols]
            b_display = b_display.rename(columns={
                "code": "代码", "name": "名称", "price": "最新价",
                "pct_change": "涨跌幅(%)", "turnover_rate": "换手率(%)",
                "break_count": "炸板次数", "industry": "行业",
            })

            st.dataframe(
                b_display,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "涨跌幅(%)": st.column_config.NumberColumn(format="%.2f%%"),
                    "换手率(%)": st.column_config.NumberColumn(format="%.2f"),
                    "代码": st.column_config.TextColumn(width="small"),
                    "名称": st.column_config.TextColumn(width="small"),
                },
            )

            st.caption("💡 炸板=封涨停后又被打开，反映多空分歧大。炸板次数越多封板越不牢固，次日低开概率较高。")
