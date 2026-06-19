"""Tab 10: 值博率 — 多因子评分"""
import streamlit as st
import pandas as pd
from datetime import datetime
from data.screener import get_combined_data
from data.factors import compute_upside_score
from utils import fmt_yuan


def render():
    st.title("🔥 上涨值博率")
    st.caption("多因子评分模型：综合资金流、涨跌幅、换手率、估值，筛选高上涨潜力的股票")

    col_v1, col_v2, col_v3 = st.columns([2, 2, 2])
    with col_v1:
        v_market = st.selectbox("市场板块", ["全部", "上海", "深圳", "北交所"], key="v_market")
    with col_v2:
        v_topn = st.selectbox("显示数量", [30, 50, 100, 200], index=1, key="v_topn")
    with col_v3:
        v_refresh = st.button("🔄 刷新数据", use_container_width=True, key="v_refresh")

    v_search = st.text_input("🔍 搜索代码/名称", key="search_upside", placeholder="输入股票代码或名称过滤...")

    with st.spinner("正在加载全市场数据并计算值博率..."):
        try:
            v_data = get_combined_data(force_refresh=v_refresh)
        except Exception as e:
            st.error(f"数据加载失败: {e}")
            return

    if v_market == "上海":
        v_data = v_data[v_data["code"].str.startswith("6")]
    elif v_market == "深圳":
        v_data = v_data[v_data["code"].str.startswith(("0", "3"))]
    elif v_market == "北交所":
        v_data = v_data[v_data["code"].str.startswith(("8", "4", "9"))]

    if "name" in v_data.columns:
        v_data = v_data[~v_data["name"].astype(str).str.contains("ST|退")]

    v_data["upside_score"] = compute_upside_score(v_data)
    v_data = v_data.sort_values("upside_score", ascending=False)

    # 搜索过滤
    if v_search:
        kw = v_search.lower()
        v_data = v_data[
            v_data["code"].astype(str).str.contains(kw) |
            v_data["name"].astype(str).str.lower().str.contains(kw)
        ]

    v_top = v_data.head(int(v_topn))

    st.subheader(f"值博率 TOP {len(v_top)}")

    v_display = v_top.copy()
    show_cols = ["code", "name", "price", "pct_change", "upside_score",
                 "main_capital", "turnover_rate", "pe", "industry"]
    show_cols = [c for c in show_cols if c in v_display.columns]
    v_display = v_display[show_cols]

    v_display["price"] = v_display["price"].round(2)
    v_display["pct_change"] = v_display["pct_change"].round(2)
    v_display["upside_score"] = v_display["upside_score"].round(0).astype(int)
    if "turnover_rate" in v_display.columns:
        v_display["turnover_rate"] = v_display["turnover_rate"].round(2)
    if "pe" in v_display.columns:
        v_display["pe"] = v_display["pe"].round(1)

    if "main_capital" in v_display.columns:
        v_display["资金净额"] = v_display["main_capital"].apply(lambda x: fmt_yuan(x, signed=True))

    v_display = v_display.rename(columns={
        "code": "代码", "name": "名称", "price": "最新价",
        "pct_change": "涨跌幅(%)", "upside_score": "值博率",
        "turnover_rate": "换手率(%)", "pe": "PE(市盈率)",
        "industry": "行业",
    })

    drop_cols = ["main_capital"]
    v_display = v_display[[c for c in v_display.columns if c not in drop_cols]]

    st.dataframe(
        v_display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "涨跌幅(%)": st.column_config.NumberColumn(format="%.2f%%"),
            "值博率": st.column_config.ProgressColumn(
                format="%d", min_value=0, max_value=100,
            ),
            "代码": st.column_config.TextColumn(width="small"),
            "名称": st.column_config.TextColumn(width="small"),
        },
    )

    st.caption("💡 值博率评分：资金流入(27%) + 净流入占比(17%) + 涨幅合理性(16%) + "
              "技术面(15%：强势度+振幅+量价配合+主力背离) + 换手(10%) + 盈利能力(10%) + 估值(5%)")

    # CSV 导出
    csv_data = v_data.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "📥 导出 CSV",
        data=csv_data,
        file_name=f"upside_score_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
    )
