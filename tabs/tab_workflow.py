"""Tab 选股工作流 — 8 步闭环选股 SOP"""
import streamlit as st
import pandas as pd
from datetime import datetime

from data.zt_pool import get_zt_pool, get_zt_summary
from data.screener import get_fund_flow_data, get_stock_list
from data.anomaly import run_all_anomalies
from data.candlestick import scan_all_candlestick_patterns
from data.patterns import run_all_patterns
from data.factors import compute_composite_ranking
from data.industry_db import compute_industry_momentum, get_industry_list_from_db
from data.database import get_stock_name_map
from utils import fmt_yuan, parse_cn_money


_VALID_STOCK_CODES: set = None  # lazy cache


def _get_valid_stock_codes() -> set:
    """返回真实A股个股代码白名单（排除指数/ETF/债券等非股票标的）"""
    global _VALID_STOCK_CODES
    if _VALID_STOCK_CODES is not None:
        return _VALID_STOCK_CODES

    try:
        df = get_stock_list()
        if not df.empty and "code" in df.columns:
            _VALID_STOCK_CODES = set(df["code"].astype(str).str.zfill(6))
        else:
            _VALID_STOCK_CODES = set()
    except Exception:
        _VALID_STOCK_CODES = set()
    return _VALID_STOCK_CODES


def _filter_valid_codes(codes: set) -> set:
    """只保留真实个股代码，剔除指数/ETF/债券"""
    valid = _get_valid_stock_codes()
    if not valid:
        return codes  # 如果白名单为空，保留全部（宁可多显示不要漏掉）
    return {c for c in codes if str(c).zfill(6) in valid}


def _fmt_time(t):
    if pd.isna(t):
        return "-"
    s = str(t).strip()
    if len(s) >= 6:
        return f"{s[:2]}:{s[2:4]}:{s[4:6]}"
    if len(s) >= 4:
        return f"{s[:2]}:{s[2:4]}"
    return s


def _is_early_seal(t):
    """判断封板时间是否在 10:00 前"""
    try:
        s = str(t).strip()
        if len(s) >= 4:
            hh, mm = int(s[:2]), int(s[2:4])
            return hh < 10 or (hh == 10 and mm == 0 and len(s) < 6)
    except (ValueError, TypeError):
        pass
    return False


def _run_step1():
    """Step 1: 涨停板初筛"""
    zt_df = get_zt_pool(force_refresh=True)
    zt_summary = get_zt_summary(force_refresh=True)
    if "first_zt_time" in zt_df.columns:
        zt_df["_early"] = zt_df["first_zt_time"].apply(_is_early_seal)
        zt_df["_seal"] = zt_df.get("seal_fund_val", 0).fillna(0)
        early_zt = zt_df[(zt_df["_early"]) & (zt_df["_seal"] > 0)]
        early_zt = early_zt.sort_values("_seal", ascending=False)
    else:
        early_zt = zt_df.copy()
    st.session_state.wf_zt = early_zt
    for c in early_zt["code"].head(30).values:
        st.session_state.wf_candidates.add(str(c).zfill(6))
    return f"涨停 {len(zt_df)} 只，早封板 {len(early_zt)} 只"


def _run_step2():
    """Step 2: 资金流确认"""
    ff = get_fund_flow_data()
    if ff.empty:
        return "资金流数据为空"
    ff = ff[~ff["name"].astype(str).str.contains("ST|退")]
    ff_top20 = ff.sort_values("main_capital", ascending=False).head(20)
    st.session_state.wf_ff_top20 = ff_top20
    zt_codes = set(str(c).zfill(6) for c in st.session_state.get("wf_candidates", set()))
    ff_top20_codes = set(str(c).zfill(6) for c in ff_top20["code"])
    overlap = zt_codes & ff_top20_codes
    st.session_state.wf_overlap_ff = overlap
    return f"涨停池 ∩ 资金TOP20: {len(overlap)} 只重叠"


def _run_step3():
    """Step 3: 异动检测"""
    anomalies = run_all_anomalies()
    st.session_state.wf_anomalies = anomalies
    anom_codes = set()
    for k, v in anomalies.items():
        if isinstance(v, pd.DataFrame) and "symbol" in v.columns:
            for c in v["symbol"].values:
                anom_codes.add(str(c).zfill(6))
    st.session_state.wf_anom_codes = anom_codes
    total = sum(len(v) if isinstance(v, pd.DataFrame) else 0 for v in anomalies.values())
    return f"发现 {total} 条异动信号"


def _run_step4():
    """Step 4: K线形态"""
    patterns = scan_all_candlestick_patterns()
    st.session_state.wf_patterns = patterns
    bullish = [k for k, v in patterns.items()
               if isinstance(v, pd.DataFrame) and not v.empty
               and any(b in k for b in ["Bullish", "Hammer", "Morning", "Soldiers"])]
    # 看涨形态的股票代码加入候选池
    for name, df in patterns.items():
        if isinstance(df, pd.DataFrame) and not df.empty:
            if any(b in name for b in ["Bullish", "Hammer", "Morning", "Soldiers"]):
                for c in df.get("symbol", pd.Series()).head(20).values:
                    st.session_state.wf_candidates.add(str(c).zfill(6))
    return f"发现 {len(bullish)} 种看涨形态"


def _run_step5():
    """Step 5: 技术形态确认"""
    pats = run_all_patterns()
    st.session_state.wf_tech_patterns = pats
    # 金叉+放量突破的股票代码加入候选池
    for name, df in pats.items():
        if isinstance(df, pd.DataFrame) and not df.empty:
            if any(kw in name for kw in ["金叉", "突破", "volume_breakout"]):
                for c in df.get("symbol", pd.Series()).head(20).values:
                    st.session_state.wf_candidates.add(str(c).zfill(6))
    total = sum(len(v) if isinstance(v, pd.DataFrame) else 0 for v in pats.values())
    return f"发现 {total} 条技术信号"


def _run_step6():
    """Step 6: 多因子排名"""
    ranking = compute_composite_ranking()
    if ranking.empty:
        return "多因子排名数据为空"
    top_n = max(20, len(ranking) // 10)
    top = ranking.head(top_n)
    st.session_state.wf_ranking = top
    for c in top["symbol"].head(top_n).values:
        st.session_state.wf_candidates.add(str(c).zfill(6))
    return f"TOP {top_n} 只 (前10%)"


def _run_step7():
    """Step 7: 行业轮动"""
    momentum = compute_industry_momentum()
    st.session_state.wf_industry_momentum = momentum
    if not momentum.empty:
        top_inds = momentum.head(3)
        return f"动量最强: {', '.join(top_inds['industry'].head(3).values)}"
    return "行业动量数据为空"


_STEPS = [
    ("🔍 涨停板初筛", _run_step1),
    ("💰 资金流确认", _run_step2),
    ("⚡ 异动检测", _run_step3),
    ("🕯️ K线形态", _run_step4),
    ("📐 技术确认", _run_step5),
    ("🎯 多因子排名", _run_step6),
    ("🔄 行业轮动", _run_step7),
]


def render():
    st.title("📋 选股工作流")
    st.caption("8 步闭环选股 — 涨停板 → 资金确认 → 异动 → K线形态 → 技术确认 → 多因子 → 行业 → 回测诊断")

    # 候选池（跨步骤共享）
    if "wf_candidates" not in st.session_state:
        st.session_state.wf_candidates = set()
    if "wf_auto_status" not in st.session_state:
        st.session_state.wf_auto_status = {}

    # ── 一键选股按钮 ──
    btn_col1, btn_col2 = st.columns([2, 5])
    with btn_col1:
        if st.button("🚀 一键自动选股", use_container_width=True, type="primary", key="wf_auto"):
            st.cache_data.clear()
            st.session_state.wf_auto_status = {}
            st.session_state.wf_candidates = set()
            progress = st.progress(0, "开始自动选股...")
            status_text = st.empty()
            for i, (step_name, step_fn) in enumerate(_STEPS):
                status_text.text(f"正在执行: {step_name} ...")
                try:
                    msg = step_fn()
                    st.session_state.wf_auto_status[step_name] = f"✅ {msg}"
                except Exception as e:
                    st.session_state.wf_auto_status[step_name] = f"❌ 失败: {str(e)[:50]}"
                progress.progress((i + 1) / len(_STEPS))
            progress.empty()
            # 剔除指数/ETF/债券等非股票标的
            st.session_state.wf_candidates = _filter_valid_codes(st.session_state.wf_candidates)
            status_text.text("✅ 一键选股完成！")
    with btn_col2:
        if st.session_state.wf_auto_status:
            st.caption("  |  ".join(
                f"{v}" for v in list(st.session_state.wf_auto_status.values())[-3:]
            ))

    st.divider()

    # ══════════════════════════════════════════
    # Step 1: 涨停板初筛
    # ══════════════════════════════════════════
    with st.expander("🔍 第1步：涨停板初筛", expanded=not bool(st.session_state.wf_auto_status)):
        c1, c2 = st.columns([2, 3])
        with c1:
            if st.button("🔄 拉取涨停板", key="wf_step1"):
                try:
                    st.cache_data.clear()
                    msg = _run_step1()
                    st.success(msg)
                except Exception as e:
                    st.error(f"获取涨停板失败: {e}")
        with c2:
            s1 = st.session_state.wf_auto_status.get("🔍 涨停板初筛", "")
            if s1:
                st.success(s1) if "✅" in s1 else st.error(s1)

        zt_data = st.session_state.get("wf_zt")
        if zt_data is not None and not zt_data.empty:
            show = zt_data[["code", "name", "price", "pct_change", "first_zt_time",
                             "seal_fund_val", "break_count", "industry"]].head(20).copy()
            show["封板时间"] = show["first_zt_time"].apply(_fmt_time)
            show["封单(万)"] = show["seal_fund_val"].apply(lambda x: f"{x:,.0f}" if pd.notna(x) else "-")
            show = show.rename(columns={
                "code": "代码", "name": "名称", "price": "最新价",
                "pct_change": "涨跌幅(%)", "break_count": "炸板",
                "industry": "行业",
            })
            st.dataframe(show[[c for c in ["代码", "名称", "最新价", "涨跌幅(%)",
                            "封板时间", "封单(万)", "炸板", "行业"] if c in show.columns]],
                         use_container_width=True, hide_index=True)
            st.caption(f"✅ {len(st.session_state.wf_candidates)} 只进入候选池")
        else:
            st.info("👆 点击「拉取涨停板」开始")

    # ══════════════════════════════════════════
    # Step 2: 资金流确认
    # ══════════════════════════════════════════
    with st.expander("💰 第2步：资金流确认", expanded=False):
        c2a, c2b = st.columns([2, 3])
        with c2a:
            if st.button("🔄 加载资金排名 TOP20", key="wf_step2"):
                try:
                    msg = _run_step2()
                    st.success(msg)
                except Exception as e:
                    st.error(f"加载失败: {e}")
        with c2b:
            s2 = st.session_state.wf_auto_status.get("💰 资金流确认", "")
            if s2:
                st.success(s2) if "✅" in s2 else st.error(s2)

        ff20 = st.session_state.get("wf_ff_top20")
        overlap = st.session_state.get("wf_overlap_ff", set())
        if ff20 is not None and not ff20.empty:
            ff20["净额"] = ff20["main_capital"].apply(lambda x: fmt_yuan(x, signed=True))
            ff20["_in_overlap"] = ff20["code"].apply(
                lambda c: "🔥" if str(c).zfill(6) in overlap else "")
            show = ff20[["_in_overlap", "code", "name", "price", "pct_change", "净额"]].copy()
            show = show.rename(columns={
                "_in_overlap": "标记", "code": "代码", "name": "名称",
                "price": "最新价", "pct_change": "涨跌幅(%)",
            })
            st.dataframe(show, use_container_width=True, hide_index=True)
            st.caption("🔥 = 同时出现在涨停池和资金TOP20中")
        else:
            st.info("👆 点击加载资金排名")

    # ══════════════════════════════════════════
    # Step 3: 异常检测
    # ══════════════════════════════════════════
    with st.expander("⚡ 第3步：异动检测", expanded=False):
        c3a, c3b = st.columns([2, 3])
        with c3a:
            if st.button("🔍 扫描全市场异动", key="wf_step3"):
                with st.spinner("扫描中（约15-30秒）..."):
                    try:
                        msg = _run_step3()
                        st.success(msg)
                    except Exception as e:
                        st.error(f"扫描失败: {e}")
        with c3b:
            s3 = st.session_state.wf_auto_status.get("⚡ 异动检测", "")
            if s3:
                st.success(s3) if "✅" in s3 else st.error(s3)

        anomalies = st.session_state.get("wf_anomalies", {})
        if anomalies:
            for name, df in anomalies.items():
                if isinstance(df, pd.DataFrame) and not df.empty:
                    with st.expander(f"{name} ({len(df)} 条)", expanded=False):
                        names = get_stock_name_map()
                        show = df.head(10).copy()
                        if "symbol" in show.columns:
                            show["名称"] = show["symbol"].map(names).fillna("")
                            cols = [c for c in ["symbol", "名称"] if c in show.columns]
                            show = show[cols]
                        st.dataframe(show, use_container_width=True, hide_index=True)
        else:
            st.info("👆 点击扫描异动")

    # ══════════════════════════════════════════
    # Step 4: K线形态
    # ══════════════════════════════════════════
    with st.expander("🕯️ 第4步：K线形态识别", expanded=False):
        c4a, c4b = st.columns([2, 3])
        with c4a:
            if st.button("🔍 扫描看涨形态", key="wf_step4"):
                with st.spinner("扫描中..."):
                    try:
                        msg = _run_step4()
                        st.success(msg)
                    except Exception as e:
                        st.error(f"扫描失败: {e}")
        with c4b:
            s4 = st.session_state.wf_auto_status.get("🕯️ K线形态", "")
            if s4:
                st.success(s4) if "✅" in s4 else st.error(s4)

        patterns = st.session_state.get("wf_patterns", {})
        if patterns:
            bullish_patterns = {k: v for k, v in patterns.items()
                if isinstance(v, pd.DataFrame) and not v.empty
                and any(b in k for b in ["Bullish", "Hammer", "Morning", "Soldiers"])}
            if bullish_patterns:
                for name, df in bullish_patterns.items():
                    with st.expander(f"🟢 {name} ({len(df)} 只)", expanded=False):
                        names = get_stock_name_map()
                        show = df.head(10).copy()
                        if "symbol" in show.columns:
                            show["名称"] = show["symbol"].map(names).fillna("")
                        st.dataframe(show, use_container_width=True, hide_index=True)
            else:
                st.info("未发现看涨形态")
        else:
            st.info("👆 点击扫描K线形态")

    # ══════════════════════════════════════════
    # Step 5: 技术形态确认
    # ══════════════════════════════════════════
    with st.expander("📐 第5步：技术形态确认", expanded=False):
        c5a, c5b = st.columns([2, 3])
        with c5a:
            if st.button("🔍 扫描技术形态", key="wf_step5"):
                with st.spinner("扫描中..."):
                    try:
                        msg = _run_step5()
                        st.success(msg)
                    except Exception as e:
                        st.error(f"扫描失败: {e}")
        with c5b:
            s5 = st.session_state.wf_auto_status.get("📐 技术确认", "")
            if s5:
                st.success(s5) if "✅" in s5 else st.error(s5)

        tech_pats = st.session_state.get("wf_tech_patterns", {})
        if tech_pats:
            for name, df in tech_pats.items():
                if isinstance(df, pd.DataFrame) and not df.empty:
                    if any(kw in name for kw in ["金叉", "突破", "volume_breakout"]):
                        with st.expander(f"📈 {name} ({len(df)} 条)", expanded=False):
                            st.dataframe(df.head(10), use_container_width=True, hide_index=True)
        else:
            st.info("👆 点击扫描技术形态")

    # ══════════════════════════════════════════
    # Step 6: 多因子排名
    # ══════════════════════════════════════════
    with st.expander("🎯 第6步：多因子排名", expanded=False):
        c6a, c6b = st.columns([2, 3])
        with c6a:
            if st.button("🎯 计算多因子排名", key="wf_step6"):
                with st.spinner("计算中..."):
                    try:
                        msg = _run_step6()
                        st.success(msg)
                    except Exception as e:
                        st.error(f"计算失败: {e}")
        with c6b:
            s6 = st.session_state.wf_auto_status.get("🎯 多因子排名", "")
            if s6:
                st.success(s6) if "✅" in s6 else st.error(s6)

        ranking = st.session_state.get("wf_ranking")
        if ranking is not None and not ranking.empty:
            names = get_stock_name_map()
            show = ranking.head(30).copy()
            show["名称"] = show["symbol"].map(names).fillna("")
            if "symbol" in show.columns:
                show["symbol"] = show["symbol"].astype(str)
            st.dataframe(show, use_container_width=True, hide_index=True)
            st.caption(f"✅ 候选池累计: {len(st.session_state.wf_candidates)} 只")
        else:
            st.info("👆 点击计算排名")

    # ══════════════════════════════════════════
    # Step 7: 行业确认
    # ══════════════════════════════════════════
    with st.expander("🔄 第7步：行业轮动确认", expanded=False):
        c7a, c7b = st.columns([2, 3])
        with c7a:
            if st.button("📊 查看行业动量", key="wf_step7"):
                with st.spinner("计算中..."):
                    try:
                        msg = _run_step7()
                        st.success(msg)
                    except Exception as e:
                        st.error(f"计算失败: {e}")
        with c7b:
            s7 = st.session_state.wf_auto_status.get("🔄 行业轮动", "")
            if s7:
                st.success(s7) if "✅" in s7 else st.error(s7)

        momentum = st.session_state.get("wf_industry_momentum")
        if momentum is not None and not momentum.empty:
            st.dataframe(momentum.head(20), use_container_width=True, hide_index=True)
        else:
            st.info("👆 点击查看行业动量")

    # ══════════════════════════════════════════
    # Step 8: 候选池汇总 & 一键诊断
    # ══════════════════════════════════════════
    st.divider()
    st.subheader("🎯 候选池汇总")

    candidates = st.session_state.wf_candidates

    # 过滤非个股标的（指数/ETF/债券等）
    valid_codes = _get_valid_stock_codes()
    if valid_codes:
        removed = {c for c in candidates if c not in valid_codes}
        if removed:
            st.session_state.wf_candidates = candidates = candidates & valid_codes

    if candidates:
        cand_list = sorted(candidates)
        name_map = get_stock_name_map()

        # 代码 + 中文名称 网格展示
        cols = st.columns(8)
        for i, c in enumerate(cand_list[:40]):
            cname = name_map.get(c, "")
            display_text = f"{c}\n{cname}" if cname else c
            with cols[i % 8]:
                st.code(display_text)

        selected = st.multiselect(
            "选择候选股进行诊断",
            options=cand_list,
            format_func=lambda c: f"{c} — {name_map.get(c, '')}" if name_map.get(c) else c,
            key="wf_selected",
            max_selections=5
        )

        if selected:
            if st.button("🔬 一键诊断选中股票", use_container_width=True, key="wf_diag"):
                st.session_state.wf_diag_targets = selected
                st.session_state.work_mode = "回测"
                st.rerun()

        c8a, c8b = st.columns(2)
        with c8a:
            if st.button("🗑️ 清空候选池", key="wf_clear"):
                st.session_state.wf_candidates = set()
                st.session_state.wf_auto_status = {}
                st.rerun()
        with c8b:
            st.caption(f"当前 {len(candidates)} 只候选")
    else:
        st.info("候选池为空，请点击「🚀 一键自动选股」或逐步执行上述步骤积累候选股")

