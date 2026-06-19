"""Tab 8: 智能选股 — 多维度筛选"""
import streamlit as st
import pandas as pd
from datetime import datetime
from data.screener import get_combined_data, smart_screen, get_industry_list
from utils import fmt_yuan, format_stock_display


def render():
    st.title("智能选股")
    st.caption("多维度筛选：行情 + 资金流 + 行业，支持组合条件与自定义排序")

    col_btn8, col_info8 = st.columns([2, 3])
    with col_btn8:
        refresh_combined = st.button("🔄 刷新数据", use_container_width=True, key="refresh_smart")
    with col_info8:
        st.caption("首次加载约30秒（含资金流），之后5分钟缓存")

    with st.spinner("正在加载多维度数据..."):
        try:
            combined = get_combined_data(force_refresh=refresh_combined)
        except Exception as e:
            st.error(f"数据加载失败: {e}")
            return

    st.caption(f"共 {len(combined)} 只股票已加载")

    with st.expander("🔍 多维度筛选条件", expanded=True):
        tab_dim1, tab_dim2, tab_dim3, tab_dim4, tab_dim5 = st.tabs([
            "📊 行情维度", "📈 估值维度", "💰 资金维度", "🏭 行业维度", "📋 基本面"
        ])

        with tab_dim1:
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                market_s = st.selectbox("市场板块", ["全部", "上海", "深圳", "北交所"], key="smart_market")
            with c2:
                price_min_s = st.number_input("最低价", 0.0, None, 0.0, step=0.1, key="smart_pmin")
            with c3:
                price_max_s = st.number_input("最高价", 0.0, None, 0.0, step=0.1, key="smart_pmax")
            with c4:
                keyword_s = st.text_input("代码/名称", placeholder="搜索", key="smart_kw")

            c5, c6, c7 = st.columns(3)
            with c5:
                pct_min_s = st.number_input("最低涨跌幅(%)", -20.0, 20.0, -20.0, step=0.1, key="smart_pct_min")
            with c6:
                pct_max_s = st.number_input("最高涨跌幅(%)", -20.0, 20.0, 20.0, step=0.1, key="smart_pct_max")
            with c7:
                vol_min_s = st.number_input("最低成交量(手)", 0, None, 0, step=10000, key="smart_vol")

        with tab_dim2:
            vc1, vc2, vc3 = st.columns(3)
            with vc1:
                pe_min_s = st.number_input(
                    "PE(TTM) ≥", 0.0, None, 0.0, step=1.0,
                    help="市盈率下限，0=不限制", key="smart_pe_min"
                )
                pe_max_s = st.number_input(
                    "PE(TTM) ≤", 0.0, None, 0.0, step=1.0,
                    help="市盈率上限，0=不限制", key="smart_pe_max"
                )
            with vc2:
                pb_min_s = st.number_input(
                    "PB ≥", 0.0, None, 0.0, step=0.1,
                    help="市净率下限，0=不限制", key="smart_pb_min"
                )
                pb_max_s = st.number_input(
                    "PB ≤", 0.0, None, 0.0, step=0.1,
                    help="市净率上限，0=不限制", key="smart_pb_max"
                )
            with vc3:
                mktcap_min_s = st.number_input(
                    "总市值≥(亿)", 0.0, None, 0.0, step=1.0,
                    help="总市值下限（亿元），0=不限制", key="smart_mktcap"
                )
                turnover_rate_min_s = st.number_input(
                    "换手率≥(%)", 0.0, None, 0.0, step=0.1,
                    help="换手率下限，0=不限制", key="smart_tr"
                )

        with tab_dim3:
            cc1, cc2, cc3 = st.columns(3)
            with cc1:
                flow_min_s = st.number_input(
                    "主力净流入≥(万)", None, None, value=None, step=100,
                    help="主力资金净流入下限（万元），留空=不限制"
                )
            with cc2:
                flow_pct_min_s = st.number_input(
                    "净流入占比≥(%)", -100.0, 100.0, -100.0, step=0.1,
                    help="净流量占比下限"
                )
            with cc3:
                flow_pct_max_s = st.number_input(
                    "净流入占比≤(%)", -100.0, 100.0, 100.0, step=0.1,
                    help="净流量占比上限"
                )

        with tab_dim4:
            industry_options = get_industry_list()
            selected_inds = st.multiselect(
                "选择行业板块（留空=全部）",
                options=industry_options,
                default=[],
                placeholder="如：半导体、银行、白酒...",
                key="smart_inds",
            )

        with tab_dim5:
            fc1, fc2, fc3 = st.columns(3)
            with fc1:
                roe_min = st.number_input(
                    "ROE ≥ (%)", 0.0, None, 0.0, step=0.5,
                    help="净资产收益率下限，0=不限制", key="smart_roe"
                )
                gross_margin_min = st.number_input(
                    "毛利率 ≥ (%)", 0.0, None, 0.0, step=0.5,
                    help="毛利率下限，0=不限制", key="smart_gm"
                )
            with fc2:
                rev_growth_min = st.number_input(
                    "营收增速 ≥ (%)", -100.0, None, -100.0, step=0.5,
                    help="营收同比增长率下限", key="smart_revg"
                )
                profit_growth_min = st.number_input(
                    "利润增速 ≥ (%)", -100.0, None, -100.0, step=0.5,
                    help="净利润同比增长率下限", key="smart_prog"
                )
            with fc3:
                debt_max = st.number_input(
                    "资产负债率 ≤ (%)", 0.0, None, 0.0, step=1.0,
                    help="资产负债率上限，0=不限制", key="smart_debt"
                )
                net_margin_min = st.number_input(
                    "净利率 ≥ (%)", 0.0, None, 0.0, step=0.5,
                    help="净利率下限，0=不限制", key="smart_nm"
                )

        st.divider()
        sc1, sc2, sc3 = st.columns(3)
        with sc1:
            sort_options = {
                "": "默认(不排序)",
                "pct_change": "涨跌幅",
                "price": "最新价",
                "volume": "成交量",
                "turnover": "成交额",
                "main_capital": "资金净额",
                "capital_inflow": "资金流入",
                "capital_outflow": "资金流出",
                "pe": "市盈率(PE)",
                "pb": "市净率(PB)",
                "market_cap": "总市值",
                "turnover_rate": "换手率",
            }
            sort_choice = st.selectbox("排序字段", list(sort_options.keys()),
                                       format_func=lambda x: sort_options[x], key="smart_sort")
        with sc2:
            sort_order = st.radio("排序方向", ["降序", "升序"], horizontal=True, key="smart_order")
        with sc3:
            top_n = st.number_input("取前N只", 0, 500, 200, step=50,
                                    help="0=返回全部匹配股票")

    flow_min_val = flow_min_s * 10000 if flow_min_s is not None and flow_min_s > 0 else None
    mktcap_min_val = mktcap_min_s * 10000 if mktcap_min_s > 0 else None
    result = smart_screen(
        combined,
        price_min=price_min_s if price_min_s > 0 else None,
        price_max=price_max_s if price_max_s > 0 else None,
        pct_change_min=pct_min_s if pct_min_s > -20 else None,
        pct_change_max=pct_max_s if pct_max_s < 20 else None,
        volume_min=vol_min_s if vol_min_s > 0 else None,
        market=market_s,
        pe_min=pe_min_s if pe_min_s > 0 else None,
        pe_max=pe_max_s if pe_max_s > 0 else None,
        pb_min=pb_min_s if pb_min_s > 0 else None,
        pb_max=pb_max_s if pb_max_s > 0 else None,
        mktcap_min=mktcap_min_val,
        turnover_rate_min=turnover_rate_min_s if turnover_rate_min_s > 0 else None,
        main_capital_min=flow_min_val,
        net_flow_pct_min=flow_pct_min_s if flow_pct_min_s > -100 else None,
        net_flow_pct_max=flow_pct_max_s if flow_pct_max_s < 100 else None,
        industries=selected_inds if selected_inds else None,
        keyword=keyword_s.strip(),
        sort_by=sort_choice,
        ascending=(sort_order == "升序"),
        top_n=int(top_n) if top_n > 0 else None,
    )

    # ── 基本面后筛选 ──
    fin_filters_active = any([
        roe_min > 0, gross_margin_min > 0,
        rev_growth_min > -100, profit_growth_min > -100,
        debt_max > 0, net_margin_min > 0,
    ])

    if fin_filters_active and not result.empty:
        from data.fundamental import fetch_financial_indicators

        fin_candidates = result.head(50)
        fin_rows = []
        with st.spinner("正在获取基本面数据（约需30秒）..."):
            for _, row in fin_candidates.iterrows():
                code = str(row.get("code", ""))
                if not code:
                    continue
                fdata = fetch_financial_indicators(code)
                if fdata:
                    fdata["_match_code"] = code
                    fin_rows.append(fdata)

        if fin_rows:
            fin_df = pd.DataFrame(fin_rows)
            fin_df = fin_df.rename(columns={"_match_code": "code"})
            result = result.merge(fin_df, on="code", how="inner")

            if roe_min > 0 and "roe" in result.columns:
                result = result[result["roe"] >= roe_min]
            if gross_margin_min > 0 and "gross_margin" in result.columns:
                result = result[result["gross_margin"] >= gross_margin_min]
            if rev_growth_min > -100 and "revenue_yoy" in result.columns:
                result = result[result["revenue_yoy"] >= rev_growth_min]
            if profit_growth_min > -100 and "profit_yoy" in result.columns:
                result = result[result["profit_yoy"] >= profit_growth_min]
            if debt_max > 0 and "debt_ratio" in result.columns:
                result = result[result["debt_ratio"] <= debt_max]
            if net_margin_min > 0 and "net_margin" in result.columns:
                result = result[result["net_margin"] >= net_margin_min]

    st.subheader(f"筛选结果 ({len(result)} 只)")

    if result.empty:
        st.info("没有符合条件的股票，请放宽筛选条件")
    else:
        display = result.copy()
        cols_show = ["code", "name", "price", "pct_change",
                     "pe", "pb", "market_cap", "turnover_rate",
                     "volume", "turnover",
                     "main_capital", "capital_inflow", "capital_outflow", "industry"]
        extra_fin_cols = ["roe", "gross_margin", "net_margin",
                          "revenue_yoy", "profit_yoy", "debt_ratio"]
        for efc in extra_fin_cols:
            if efc in display.columns:
                cols_show.append(efc)
        cols_show = [c for c in cols_show if c in display.columns]
        display = display[cols_show]

        # 资金格式化
        if "main_capital" in display.columns:
            display["资金净额"] = display["main_capital"].apply(lambda x: fmt_yuan(x, signed=True))
        if "capital_inflow" in display.columns:
            display["流入资金"] = display["capital_inflow"].apply(fmt_yuan)
        if "capital_outflow" in display.columns:
            display["流出资金"] = display["capital_outflow"].apply(fmt_yuan)
        if "market_cap" in display.columns:
            display["总市值(亿)"] = display["market_cap"].apply(
                lambda x: f"{x/10000:.1f}" if pd.notna(x) and x > 0 else "-"
            )
        for fcol, flabel in [
            ("roe", "ROE(%)"), ("gross_margin", "毛利率(%)"),
            ("net_margin", "净利率(%)"), ("revenue_yoy", "营收增速(%)"),
            ("profit_yoy", "利润增速(%)"), ("debt_ratio", "负债率(%)"),
        ]:
            if fcol in display.columns:
                display[flabel] = display[fcol].apply(
                    lambda x: f"{x:.1f}%" if pd.notna(x) else "N/A"
                )

        display = format_stock_display(display, extra_rename={"pe": "PE(市盈率)", "pb": "PB(市净率)"})
        drop_cols = ["main_capital", "capital_inflow", "capital_outflow", "market_cap",
                     "roe", "gross_margin", "net_margin",
                     "revenue_yoy", "profit_yoy", "debt_ratio"]
        display = display[[c for c in display.columns if c not in drop_cols]]

        st.dataframe(
            display,
            use_container_width=True,
            hide_index=True,
            column_config={
                "涨跌幅(%)": st.column_config.NumberColumn(format="%.2f%%"),
                "代码": st.column_config.TextColumn(width="small"),
                "名称": st.column_config.TextColumn(width="small"),
            },
        )

        csv_data = result.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "📥 导出 CSV",
            data=csv_data,
            file_name=f"smart_screen_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
        )
