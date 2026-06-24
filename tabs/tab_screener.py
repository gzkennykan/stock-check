"""Tab 智能选股 — 多维度筛选 + 值博率排名（合并原 tab8 + tab10）"""
import streamlit as st
import pandas as pd
from datetime import datetime
from data.screener import get_combined_data, smart_screen, get_industry_list
from data.factors import compute_upside_score
from utils import fmt_yuan, format_stock_display


def _render_filter_mode(combined: pd.DataFrame):
    """多维度筛选模式（原 tab8）"""
    st.caption(f"共 {len(combined)} 只股票已加载")

    with st.expander("🔍 多维度筛选条件", expanded=True):
        tab_dim1, tab_dim2, tab_dim3, tab_dim4, tab_dim5 = st.tabs([
            "📊 行情", "📈 估值", "💰 资金", "🏭 行业", "📋 基本面"
        ])

        with tab_dim1:
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                market_s = st.selectbox("市场", ["全部", "上海", "深圳", "北交所"], key="sc_market")
            with c2:
                price_min_s = st.number_input("最低价", 0.0, None, 0.0, step=0.1, key="sc_pmin")
            with c3:
                price_max_s = st.number_input("最高价", 0.0, None, 0.0, step=0.1, key="sc_pmax")
            with c4:
                keyword_s = st.text_input("代码/名称", placeholder="搜索", key="sc_kw")

            c5, c6, c7 = st.columns(3)
            with c5:
                pct_min_s = st.number_input("最低涨跌幅(%)", -20.0, 20.0, -20.0, step=0.1, key="sc_pctmin")
            with c6:
                pct_max_s = st.number_input("最高涨跌幅(%)", -20.0, 20.0, 20.0, step=0.1, key="sc_pctmax")
            with c7:
                vol_min_s = st.number_input("最低成交量(手)", 0, None, 0, step=10000, key="sc_vol")

        with tab_dim2:
            vc1, vc2, vc3 = st.columns(3)
            with vc1:
                pe_min_s = st.number_input("PE ≥", 0.0, None, 0.0, step=1.0, key="sc_pemin")
                pe_max_s = st.number_input("PE ≤", 0.0, None, 0.0, step=1.0, key="sc_pemax")
            with vc2:
                pb_min_s = st.number_input("PB ≥", 0.0, None, 0.0, step=0.1, key="sc_pbmin")
                pb_max_s = st.number_input("PB ≤", 0.0, None, 0.0, step=0.1, key="sc_pbmax")
            with vc3:
                mktcap_min_s = st.number_input("总市值≥(亿)", 0.0, None, 0.0, step=1.0, key="sc_mktcap")
                turnover_min_s = st.number_input("换手率≥(%)", 0.0, None, 0.0, step=0.1, key="sc_tr")

        with tab_dim3:
            cc1, cc2, cc3 = st.columns(3)
            with cc1:
                flow_min_s = st.number_input("主力净流入≥(万)", None, None, value=None, step=100, key="sc_flow")
            with cc2:
                flow_pct_min_s = st.number_input("净流入占比≥(%)", -100.0, 100.0, -100.0, step=0.1, key="sc_fpmin")
            with cc3:
                flow_pct_max_s = st.number_input("净流入占比≤(%)", -100.0, 100.0, 100.0, step=0.1, key="sc_fpmax")

        with tab_dim4:
            ind_options = get_industry_list()
            selected_inds = st.multiselect(
                "选择行业（留空=全部）", options=ind_options, default=[],
                placeholder="如：半导体、银行...", key="sc_inds")

        with tab_dim5:
            fc1, fc2, fc3 = st.columns(3)
            with fc1:
                roe_min = st.number_input("ROE ≥ (%)", 0.0, None, 0.0, step=0.5, key="sc_roe")
                gross_min = st.number_input("毛利率 ≥ (%)", 0.0, None, 0.0, step=0.5, key="sc_gm")
            with fc2:
                revg_min = st.number_input("营收增速 ≥ (%)", -100.0, None, -100.0, step=0.5, key="sc_revg")
                profitg_min = st.number_input("利润增速 ≥ (%)", -100.0, None, -100.0, step=0.5, key="sc_prog")
            with fc3:
                debt_max = st.number_input("资产负债率 ≤ (%)", 0.0, None, 0.0, step=1.0, key="sc_debt")
                netm_min = st.number_input("净利率 ≥ (%)", 0.0, None, 0.0, step=0.5, key="sc_nm")

        st.divider()
        sc1, sc2, sc3 = st.columns(3)
        with sc1:
            sort_opts = {"": "默认", "pct_change": "涨跌幅", "price": "最新价",
                         "volume": "成交量", "turnover": "成交额",
                         "main_capital": "资金净额", "pe": "市盈率", "pb": "市净率",
                         "market_cap": "总市值", "turnover_rate": "换手率"}
            sort_choice = st.selectbox("排序", list(sort_opts.keys()),
                                       format_func=lambda x: sort_opts[x], key="sc_sort")
        with sc2:
            sort_order = st.radio("方向", ["降序", "升序"], horizontal=True, key="sc_order")
        with sc3:
            top_n = st.number_input("取前N只", 0, 500, 200, step=50, help="0=全部", key="sc_topn")

    # 执行筛选
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
        turnover_rate_min=turnover_min_s if turnover_min_s > 0 else None,
        main_capital_min=flow_min_val,
        net_flow_pct_min=flow_pct_min_s if flow_pct_min_s > -100 else None,
        net_flow_pct_max=flow_pct_max_s if flow_pct_max_s < 100 else None,
        industries=selected_inds if selected_inds else None,
        keyword=keyword_s.strip(),
        sort_by=sort_choice, ascending=(sort_order == "升序"),
        top_n=int(top_n) if top_n > 0 else None,
    )

    # 基本面后筛选
    fin_active = any([roe_min > 0, gross_min > 0, revg_min > -100,
                      profitg_min > -100, debt_max > 0, netm_min > 0])
    if fin_active and not result.empty:
        from data.fundamental import fetch_financial_indicators
        fin_rows = []
        with st.spinner("获取基本面数据..."):
            for _, row in result.head(50).iterrows():
                code = str(row.get("code", ""))
                if not code: continue
                fdata = fetch_financial_indicators(code)
                if fdata:
                    fdata["_match_code"] = code
                    fin_rows.append(fdata)
        if fin_rows:
            fin_df = pd.DataFrame(fin_rows).rename(columns={"_match_code": "code"})
            result = result.merge(fin_df, on="code", how="inner")
            if roe_min > 0 and "roe" in result.columns:
                result = result[result["roe"] >= roe_min]
            if gross_min > 0 and "gross_margin" in result.columns:
                result = result[result["gross_margin"] >= gross_min]
            if revg_min > -100 and "revenue_yoy" in result.columns:
                result = result[result["revenue_yoy"] >= revg_min]
            if profitg_min > -100 and "profit_yoy" in result.columns:
                result = result[result["profit_yoy"] >= profitg_min]
            if debt_max > 0 and "debt_ratio" in result.columns:
                result = result[result["debt_ratio"] <= debt_max]
            if netm_min > 0 and "net_margin" in result.columns:
                result = result[result["net_margin"] >= netm_min]

    st.subheader(f"筛选结果 ({len(result)} 只)")
    _render_result_table(result)


def _render_upside_mode(combined: pd.DataFrame):
    """值博率排名模式（原 tab10）"""
    col_v1, col_v2, col_v3 = st.columns([2, 2, 2])
    with col_v1:
        v_market = st.selectbox("市场板块", ["全部", "上海", "深圳", "北交所"], key="up_market")
    with col_v2:
        v_topn = st.selectbox("显示数量", [30, 50, 100, 200], index=1, key="up_topn")
    with col_v3:
        if st.button("🔄 刷新", use_container_width=True, key="up_refresh"):
            st.cache_data.clear()

    v_search = st.text_input("🔍 搜索代码/名称", key="up_search", placeholder="输入代码或名称过滤...")

    data = combined.copy()
    if v_market == "上海":
        data = data[data["code"].str.startswith("6")]
    elif v_market == "深圳":
        data = data[data["code"].str.startswith(("0", "3"))]
    elif v_market == "北交所":
        data = data[data["code"].str.startswith(("8", "4", "9"))]

    if "name" in data.columns:
        data = data[~data["name"].astype(str).str.contains("ST|退")]

    data["upside_score"] = compute_upside_score(data)
    data = data.sort_values("upside_score", ascending=False)

    if v_search:
        kw = v_search.lower()
        data = data[data["code"].astype(str).str.contains(kw) |
                    data["name"].astype(str).str.lower().str.contains(kw)]

    v_top = data.head(int(v_topn))
    st.subheader(f"值博率 TOP {len(v_top)}")

    display = v_top.copy()
    show_cols = ["code", "name", "price", "pct_change", "upside_score",
                 "main_capital", "turnover_rate", "pe", "industry"]
    show_cols = [c for c in show_cols if c in display.columns]
    display = display[show_cols]

    display["upside_score"] = display["upside_score"].round(0).astype(int)
    if "main_capital" in display.columns:
        display["资金净额"] = display["main_capital"].apply(lambda x: fmt_yuan(x, signed=True))

    display = format_stock_display(
        display, extra_rename={"upside_score": "值博率", "pe": "PE(市盈率)"},
        drop_after=["main_capital"])

    st.dataframe(display, use_container_width=True, hide_index=True,
        column_config={
            "涨跌幅(%)": st.column_config.NumberColumn(format="%.2f%%"),
            "值博率": st.column_config.ProgressColumn(format="%d", min_value=0, max_value=100),
            "代码": st.column_config.TextColumn(width="small"),
            "名称": st.column_config.TextColumn(width="small"),
        })

    st.caption("💡 评分：资金流入(27%) + 净流入占比(17%) + 涨幅合理性(16%) + 技术面(15%) + 换手(10%) + 盈利(10%) + 估值(5%)")


def _render_result_table(result: pd.DataFrame):
    """渲染筛选结果表格"""
    if result.empty:
        st.info("没有符合条件的股票，请放宽筛选条件")
        return

    display = result.copy()
    cols_show = ["code", "name", "price", "pct_change",
                 "pe", "pb", "market_cap", "turnover_rate",
                 "volume", "turnover", "main_capital",
                 "capital_inflow", "capital_outflow", "industry"]
    extra_fin = ["roe", "gross_margin", "net_margin", "revenue_yoy", "profit_yoy", "debt_ratio"]
    for efc in extra_fin:
        if efc in display.columns: cols_show.append(efc)
    cols_show = [c for c in cols_show if c in display.columns]
    display = display[cols_show]

    if "main_capital" in display.columns:
        display["资金净额"] = display["main_capital"].apply(lambda x: fmt_yuan(x, signed=True))
    if "capital_inflow" in display.columns:
        display["流入资金"] = display["capital_inflow"].apply(fmt_yuan)
    if "capital_outflow" in display.columns:
        display["流出资金"] = display["capital_outflow"].apply(fmt_yuan)
    if "market_cap" in display.columns:
        display["总市值(亿)"] = display["market_cap"].apply(
            lambda x: f"{x/10000:.1f}" if pd.notna(x) and x > 0 else "-")

    fin_labels = [("roe", "ROE(%)"), ("gross_margin", "毛利率(%)"),
                  ("net_margin", "净利率(%)"), ("revenue_yoy", "营收增速(%)"),
                  ("profit_yoy", "利润增速(%)"), ("debt_ratio", "负债率(%)")]
    for fcol, flabel in fin_labels:
        if fcol in display.columns:
            display[flabel] = display[fcol].apply(lambda x: f"{x:.1f}%" if pd.notna(x) else "N/A")

    display = format_stock_display(display, extra_rename={"pe": "PE(市盈率)", "pb": "PB(市净率)"})
    drop = ["main_capital", "capital_inflow", "capital_outflow", "market_cap",
            "roe", "gross_margin", "net_margin", "revenue_yoy", "profit_yoy", "debt_ratio"]
    display = display[[c for c in display.columns if c not in drop]]

    st.dataframe(display, use_container_width=True, hide_index=True,
        column_config={
            "涨跌幅(%)": st.column_config.NumberColumn(format="%.2f%%"),
            "代码": st.column_config.TextColumn(width="small"),
            "名称": st.column_config.TextColumn(width="small"),
        })

    csv_data = result.to_csv(index=False).encode("utf-8-sig")
    st.download_button("📥 导出 CSV", data=csv_data,
        file_name=f"screener_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv", mime="text/csv")


def render():
    st.title("🧠 智能选股")
    st.caption("多维度筛选 + 值博率排名 — 统一选股工具")

    # 模式切换
    mode = st.radio("模式", ["🔍 多维度筛选", "🔥 值博率排名"], horizontal=True, key="sc_mode")

    # 数据加载
    if "sc_combined" not in st.session_state:
        st.session_state.sc_combined = None

    if st.button("🔄 加载/刷新数据", use_container_width=True, key="sc_load"):
        st.cache_data.clear()
        with st.spinner("加载全市场数据..."):
            try:
                st.session_state.sc_combined = get_combined_data(force_refresh=True)
                st.success(f"已加载 {len(st.session_state.sc_combined)} 只股票")
            except Exception as e:
                st.error(f"加载失败: {e}")
                return

    combined = st.session_state.sc_combined
    if combined is None or combined.empty:
        st.info("👆 点击加载数据开始")
        return

    st.divider()

    if "值博率" in mode:
        _render_upside_mode(combined)
    else:
        _render_filter_mode(combined)
