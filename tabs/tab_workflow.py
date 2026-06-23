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
    st.session_state.wf_zt_codes = set(str(c).zfill(6) for c in early_zt["code"].values)
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
    top_n = max(20, len(ranking) // 100)
    top = ranking.head(top_n)
    st.session_state.wf_ranking = top
    for c in top["symbol"].head(top_n).values:
        st.session_state.wf_candidates.add(str(c).zfill(6))
    return f"TOP {top_n} 只 (前1%)"


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

    # ── 单股快速诊断 ──
    diag_col1, diag_col2, diag_col3 = st.columns([3, 1, 3])
    with diag_col1:
        quick_code = st.text_input(
            "🔍 输入股票代码快速诊断",
            placeholder="如：600519（沪深A股6位代码）",
            key="wf_quick_code",
            label_visibility="collapsed",
        )
    with diag_col2:
        if st.button("🔬 诊断", use_container_width=True, key="wf_quick_diag_btn"):
            if quick_code and len(quick_code.strip()) == 6 and quick_code.strip().isdigit():
                code = quick_code.strip().zfill(6)
                st.session_state.wf_quick_diag_code = code
                st.session_state.wf_quick_diag_trigger = True
            else:
                st.error("请输入6位数字代码")
    with diag_col3:
        if st.session_state.get("wf_quick_diag_trigger") and st.session_state.get("wf_quick_diag_code"):
            st.caption(f"✅ 上次诊断: {st.session_state.wf_quick_diag_code}")

    # 单股诊断结果
    if st.session_state.get("wf_quick_diag_trigger"):
        code = st.session_state.get("wf_quick_diag_code", "")
        if code:
            name_map = get_stock_name_map()
            with st.spinner(f"正在诊断 {code} {name_map.get(code, '')} ..."):
                _run_deep_diagnostics([code], name_map)
            st.session_state.wf_quick_diag_trigger = False

    if st.session_state.get("wf_quick_diag_trigger") or st.session_state.get("wf_quick_diag_code"):
        st.divider()

    # ── 一键选股按钮 ──
    btn_col1, btn_col2 = st.columns([2, 5])
    with btn_col1:
        if st.button("🚀 一键自动选股", use_container_width=True, type="primary", key="wf_auto"):
            st.cache_data.clear()
            st.session_state.wf_auto_status = {}
            st.session_state.wf_candidates = set()
            st.session_state._deep_diag_done = False
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
                st.session_state._deep_diag_done = False
                st.rerun()
        with c8b:
            st.caption(f"当前 {len(candidates)} 只候选")
    else:
        st.info("候选池为空，请点击「🚀 一键自动选股」或逐步执行上述步骤积累候选股")

    # ══════════════════════════════════════════
    # 4维度深度诊断（同花顺AI方法论）
    # ══════════════════════════════════════════
    st.divider()
    st.subheader("🔬 4维度深度诊断")
    st.caption(
        "同花顺AI方法论：技术面(40%) + 资金面(30%) + 基本面(20%) + 机构行为(10%) → 综合评分"
    )

    if not candidates:
        st.info("候选池为空，请先执行选股步骤")
        return

    cand_list = sorted(candidates)
    if st.button("🔬 对所有候选股执行4维度深度诊断", use_container_width=True, type="primary", key="wf_deep_diag"):
        _run_deep_diagnostics(cand_list, name_map)

    # 如果自动选股已完成且候选池有股票，自动触发
    if st.session_state.wf_auto_status and not st.session_state.get("_deep_diag_done"):
        st.session_state._deep_diag_done = True
        _run_deep_diagnostics(cand_list, name_map, silent=False)


def _run_deep_diagnostics(codes: list, name_map: dict, silent: bool = False):
    """
    4维度深度诊断：
    1. 技术面 40% — 趋势/均线/RSI/MACD/动量
    2. 资金面 30% — 主力净流入/近10日累计/资金趋势
    3. 基本面 20% — ROE/利润增速/毛利率/负债率
    4. 机构行为 10% — 涨停池/资金TOP20重叠
    """
    from data.technicals import compute_full_analysis
    from data.fund_flow import get_fund_flow_summary
    from data.fundamental import fetch_financial_indicators
    from data.database import get_stock_name_map

    if not silent:
        progress = st.progress(0, "正在执行4维度深度诊断...")
        status_text = st.empty()

    results = []
    total = len(codes)

    for i, code in enumerate(codes):
        if not silent:
            status_text.text(f"诊断中: {code} {name_map.get(code, '')} ({i+1}/{total})")

        name = name_map.get(code, "")
        row = {"code": code, "name": name}

        # ── 维度1：技术面 ──
        tech_score = 0
        try:
            tech = compute_full_analysis(code)
            if tech and "error" not in tech:
                row["close"] = tech.get("close")
                row["trend"] = tech.get("trend", {})
                row["rsi14"] = tech.get("rsi14")
                row["ret_20d"] = tech.get("ret_20d")
                row["ret_60d"] = tech.get("ret_60d")
                row["vol_60d"] = tech.get("vol_60d_annual")
                row["ma20"] = tech.get("ma20")
                row["ma60"] = tech.get("ma60")
                row["ma120"] = tech.get("ma120")
                row["macd_hist"] = tech.get("macd_hist")

                # 评分：均线多头排列 (0-30)
                close = tech.get("close", 0)
                ma20 = tech.get("ma20") or 0
                ma60 = tech.get("ma60") or 0
                ma120 = tech.get("ma120") or 0
                if close > ma20 > 0:
                    tech_score += 15
                if close > ma60 > 0:
                    tech_score += 10
                if ma20 > ma60 > 0:
                    tech_score += 5  # 金叉已形成

                # RSI 健康区间 40-70 (0-15)
                rsi = tech.get("rsi14")
                if rsi and 40 <= rsi <= 70:
                    tech_score += 15
                elif rsi and 30 <= rsi < 40:
                    tech_score += 8  # 偏弱但有反弹空间

                # MACD 多头 (0-10)
                macd_h = tech.get("macd_hist")
                if macd_h and macd_h > 0:
                    tech_score += 10

                # 短期动量 (0-10)
                ret20 = tech.get("ret_20d") or 0
                ret60 = tech.get("ret_60d") or 0
                if ret20 > 5:
                    tech_score += 7
                elif ret20 > 0:
                    tech_score += 4
                if ret60 > 10:
                    tech_score += 3

                # 波动率合理 (0-5)
                vol = tech.get("vol_60d_annual") or 0
                if 20 <= vol <= 60:
                    tech_score += 5
                elif vol < 20:
                    tech_score += 2  # 太稳，缺乏动能
            else:
                row["trend"] = {}
        except Exception:
            row["trend"] = {}

        row["tech_score"] = min(tech_score, 70)  # raw max = 70

        # ── 维度2：资金面 ──
        flow_score = 0
        try:
            ff = get_fund_flow_summary(code, days=10)
            if ff:
                row["ff_today_yi"] = ff.get("today_main_net_yi", 0)
                row["ff_10d_mean_yi"] = ff.get("mean", 0)
                row["ff_10d_sum_yi"] = round(
                    sum(d.get("main_net_yi", 0) for d in ff.get("recent_days", [])), 4
                )

                # 今日主力净流入 (0-20)
                today_net = ff.get("today_main_net_yi", 0) or 0
                if today_net > 1:
                    flow_score += 20
                elif today_net > 0.3:
                    flow_score += 15
                elif today_net > 0:
                    flow_score += 10

                # 近10日资金趋势 (0-15)
                recent = ff.get("recent_days", [])
                pos_days = sum(1 for d in recent if d.get("main_net_yi", 0) > 0)
                cumsum = row.get("ff_10d_sum_yi", 0) or 0
                if cumsum > 5:
                    flow_score += 15
                elif cumsum > 1:
                    flow_score += 10
                elif cumsum > 0:
                    flow_score += 5
                if pos_days >= 7:
                    flow_score += 5  # 持续流入加分
        except Exception:
            pass

        row["flow_score"] = min(flow_score, 40)  # raw max = 40

        # ── 维度3：基本面 ──
        funda_score = 0
        try:
            fin = fetch_financial_indicators(code)
            if fin:
                roe = fin.get("roe") or 0
                profit_yoy = fin.get("profit_yoy") or 0
                gross_margin = fin.get("gross_margin") or 0
                debt_ratio = fin.get("debt_ratio") or 0
                row["roe"] = roe
                row["profit_yoy"] = profit_yoy
                row["gross_margin"] = gross_margin
                row["debt_ratio"] = debt_ratio

                if roe > 15:
                    funda_score += 12
                elif roe > 10:
                    funda_score += 8
                elif roe > 5:
                    funda_score += 4

                if profit_yoy > 30:
                    funda_score += 8
                elif profit_yoy > 10:
                    funda_score += 5
                elif profit_yoy > 0:
                    funda_score += 2

                if gross_margin > 30:
                    funda_score += 5
                elif gross_margin > 15:
                    funda_score += 2

                if 20 <= debt_ratio <= 70:
                    funda_score += 3
                elif 0 < debt_ratio < 20:
                    funda_score += 1  # 太保守，杠杆利用率低
        except Exception:
            pass

        row["funda_score"] = min(funda_score, 28)

        # ── 维度4：机构行为 ──
        insti_score = 0
        zt_codes = set(str(c).zfill(6) for c in st.session_state.get("wf_candidates", set())
                        if str(c).zfill(6) in st.session_state.get("wf_zt_codes", set()))
        ff_top_codes = st.session_state.get("wf_overlap_ff", set())

        if code in zt_codes:
            insti_score += 6  # 涨停板重叠
        if code in ff_top_codes:
            insti_score += 6  # 资金TOP20重叠

        row["insti_score"] = insti_score

        # ── 综合评分 ──
        # 各维度归一化到百分制
        composite = (
            row["tech_score"] / 70 * 40 +
            row["flow_score"] / 40 * 30 +
            row["funda_score"] / 28 * 20 +
            row["insti_score"] / 12 * 10
        )
        row["composite"] = round(composite, 1)

        # 评级
        if composite >= 70:
            row["rating"] = "🟢 强烈关注"
        elif composite >= 55:
            row["rating"] = "🟡 可关注"
        elif composite >= 40:
            row["rating"] = "🟠 观察"
        else:
            row["rating"] = "🔴 暂不建议"

        results.append(row)

        if not silent:
            progress.progress((i + 1) / total)

    if not silent:
        progress.empty()
        status_text.empty()

    if not results:
        st.warning("诊断失败，未获取到任何股票数据")
        return

    # ── 排序并展示 ──
    df_diag = pd.DataFrame(results)
    df_diag = df_diag.sort_values("composite", ascending=False).reset_index(drop=True)

    # 摘要统计
    green = int((df_diag["composite"] >= 70).sum())
    yellow = int(((df_diag["composite"] >= 55) & (df_diag["composite"] < 70)).sum())
    orange = int(((df_diag["composite"] >= 40) & (df_diag["composite"] < 55)).sum())
    red = int((df_diag["composite"] < 40).sum())

    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("🟢 强烈关注", f"{green} 只")
    mc2.metric("🟡 可关注", f"{yellow} 只")
    mc3.metric("🟠 观察", f"{orange} 只")
    mc4.metric("🔴 暂不建议", f"{red} 只")

    st.divider()

    # 诊断结果表
    display = df_diag.copy()
    show_cols = ["code", "name", "composite", "rating",
                 "tech_score", "flow_score", "funda_score", "insti_score"]
    show_cols += [c for c in ["close", "ret_20d", "rsi14", "ff_today_yi", "roe", "profit_yoy"]
                  if c in display.columns]
    show_cols = [c for c in show_cols if c in display.columns]
    display = display[show_cols]

    # 列名中文化
    rename = {
        "code": "代码", "name": "名称", "composite": "综合分",
        "rating": "评级", "tech_score": "技术面",
        "flow_score": "资金面", "funda_score": "基本面",
        "insti_score": "机构行为",
        "close": "最新价", "ret_20d": "20日收益%",
        "rsi14": "RSI(14)", "ff_today_yi": "今日主力(亿)",
        "roe": "ROE(%)", "profit_yoy": "利润增速%",
    }
    display = display.rename(columns={k: v for k, v in rename.items() if k in display.columns})

    st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "综合分": st.column_config.ProgressColumn(
                format="%.1f", min_value=0, max_value=100,
            ),
            "评级": st.column_config.TextColumn(width="small"),
            "代码": st.column_config.TextColumn(width="small"),
            "名称": st.column_config.TextColumn(width="small"),
        },
    )

    # ── 每只股票详细展开 ──
    st.divider()
    st.subheader("📋 个股详细诊断报告")

    for _, r in df_diag.iterrows():
        code = r["code"]
        name = r.get("name", "")
        with st.expander(f"{r['rating']} {code} {name} — 综合 {r['composite']} 分"):
            c1, c2 = st.columns(2)

            with c1:
                st.markdown("**🔧 技术面**")
                trend = r.get("trend", {}) or {}
                st.write(f"- 趋势状态: {trend.get('status', 'N/A')}")
                st.write(f"- 20日收益: {r.get('ret_20d', 'N/A')}%")
                st.write(f"- 60日收益: {r.get('ret_60d', 'N/A')}%")
                st.write(f"- RSI(14): {r.get('rsi14', 'N/A')}")
                st.write(f"- 60日波动: {r.get('vol_60d', 'N/A')}%")
                st.write(f"- MA20: {r.get('ma20', 'N/A')}")
                st.write(f"- MA60: {r.get('ma60', 'N/A')}")
                st.write(f"- MA120: {r.get('ma120', 'N/A')}")
                st.write(f"- MACD柱: {r.get('macd_hist', 'N/A')}")
                st.caption(f"得分: {r['tech_score']}/70")

            with c2:
                st.markdown("**💰 资金面**")
                st.write(f"- 今日主力净流入: {r.get('ff_today_yi', 'N/A')} 亿")
                st.write(f"- 近10日均值: {r.get('ff_10d_mean_yi', 'N/A')} 亿")
                st.write(f"- 近10日累计: {r.get('ff_10d_sum_yi', 'N/A')} 亿")
                st.caption(f"得分: {r['flow_score']}/40")

                st.markdown("**📊 基本面**")
                st.write(f"- ROE: {r.get('roe', 'N/A')}%")
                st.write(f"- 利润增速: {r.get('profit_yoy', 'N/A')}%")
                st.write(f"- 毛利率: {r.get('gross_margin', 'N/A')}%")
                st.write(f"- 负债率: {r.get('debt_ratio', 'N/A')}%")
                st.caption(f"得分: {r['funda_score']}/28")

                st.markdown("**🏛️ 机构行为**")
                zt_codes = set(str(c).zfill(6) for c in st.session_state.get("wf_candidates", set())
                                if str(c).zfill(6) in st.session_state.get("wf_zt_codes", set()))
                ff_top = st.session_state.get("wf_overlap_ff", set())
                flags = []
                if code in zt_codes:
                    flags.append("🔥 涨停板重叠")
                if code in ff_top:
                    flags.append("💰 资金TOP20重叠")
                if flags:
                    for f in flags:
                        st.write(f"- {f}")
                else:
                    st.write("- 无特殊机构信号")
                st.caption(f"得分: {r['insti_score']}/12")

    st.success(f"✅ 深度诊断完成！共分析 {len(results)} 只候选股")
