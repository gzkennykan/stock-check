"""Tab AI: 🤖 AI 智能分析 — LLM 驱动的多维度股票解读"""
import streamlit as st
import pandas as pd
from datetime import datetime

from data.llm_analysis import (
    analyze_stock, analyze_portfolio, set_llm_config,
    get_llm_config, LLM_CONFIG,
)
from data.database import get_stock_name_map
from data.technicals import compute_full_analysis
from data.fund_flow import get_fund_flow_summary
from data.fundamental import fetch_financial_indicators


def _resolve_input(raw: str, name_map: dict) -> str | None:
    """解析用户输入 → 股票代码"""
    raw = raw.strip()
    if not raw:
        return None
    if raw.isdigit() and len(raw) == 6:
        return raw.zfill(6)
    lowered = raw.lower().replace(" ", "")
    for code, name in name_map.items():
        if name and lowered in name.lower().replace(" ", ""):
            return code
    return None


def render():
    st.title("🤖 AI 智能分析")
    st.caption("LLM 驱动的多维度股票分析 — 技术面 + 资金面 + 基本面 + AI 解读")

    # ── API 配置（折叠） ──
    with st.expander("⚙️ LLM API 配置", expanded=False):
        cfg = get_llm_config()

        c1, c2 = st.columns(2)
        with c1:
            provider = st.selectbox(
                "LLM 提供商",
                ["deepseek", "qwen", "openai"],
                index=["deepseek", "qwen", "openai"].index(cfg["provider"]),
                format_func=lambda x: {"deepseek": "DeepSeek", "qwen": "通义千问", "openai": "OpenAI兼容"}[x],
                key="ai_provider",
            )
        with c2:
            model = st.text_input(
                "模型名称",
                value=cfg["model"],
                placeholder="deepseek-chat / qwen-plus / gpt-4o-mini",
                key="ai_model",
            )

        c3, c4 = st.columns(2)
        with c3:
            api_key = st.text_input(
                "API Key",
                type="password",
                value=cfg["api_key"],
                placeholder="sk-...",
                key="ai_api_key",
            )
        with c4:
            base_url = st.text_input(
                "API Base URL（可选）",
                value=cfg["base_url"],
                placeholder="留空使用默认",
                key="ai_base_url",
            )

        if st.button("💾 保存配置", key="ai_save_config"):
            set_llm_config(
                provider=provider,
                api_key=api_key,
                model=model,
                base_url=base_url,
            )
            st.success("配置已保存（本会话有效）")
            st.rerun()

        # 使用提示
        api_configured = bool(api_key or cfg["api_key"])
        if api_configured:
            st.success(f"✅ 已配置 {provider} / {model or cfg['model']}")
        else:
            st.info(
                "💡 未配置 API Key 时将使用**规则引擎**进行离线分析。"
                "配置 LLM 后可获得更深入的自然语言解读。\n\n"
                "**获取免费 API Key:**\n"
                "- DeepSeek: https://platform.deepseek.com （新用户赠送额度）\n"
                "- 通义千问: https://dashscope.aliyun.com （百万人免费额度）"
            )

    st.divider()

    # ── 主功能区 ──
    tab_single, tab_batch, tab_portfolio = st.tabs([
        "🔍 单股分析", "📋 批量分析", "🧺 组合诊断"
    ])

    name_map = get_stock_name_map()

    # ══════════════════════════════════════════
    # Tab 1: 单股分析
    # ══════════════════════════════════════════
    with tab_single:
        col_in1, col_in2, col_in3 = st.columns([3, 1, 2])
        with col_in1:
            user_input = st.text_input(
                "输入股票代码或名称",
                placeholder="如：600519 或 贵州茅台",
                key="ai_input",
            )
        with col_in2:
            do_analyze = st.button("🔬 AI 分析", use_container_width=True, type="primary", key="ai_go")
        with col_in3:
            extra_q = st.text_input(
                "额外问题（可选）",
                placeholder="如：现在适合买入吗？",
                key="ai_question",
            )

        if do_analyze and user_input.strip():
            code = _resolve_input(user_input.strip(), name_map)
            if not code:
                st.error(f"未找到匹配「{user_input}」的股票")
            else:
                name = name_map.get(code, "")
                with st.spinner(f"🤖 AI 正在分析 {code} {name} ..."):
                    tech = compute_full_analysis(code)
                    flow = get_fund_flow_summary(code, days=10)
                    funda = fetch_financial_indicators(code)
                    result = analyze_stock(
                        code, name,
                        tech=tech, flow=flow, funda=funda,
                        question=extra_q.strip() if extra_q.strip() else None,
                        auto_fetch=False,
                    )

                _render_single_result(result)

    # ══════════════════════════════════════════
    # Tab 2: 批量分析
    # ══════════════════════════════════════════
    with tab_batch:
        batch_input = st.text_area(
            "输入股票列表（每行一个，代码或名称）",
            placeholder="600519\n000858\n招商银行\n宁德时代",
            height=120,
            key="ai_batch_input",
        )
        if st.button("🔬 批量 AI 分析", use_container_width=True, type="primary", key="ai_batch_go"):
            lines = [l.strip() for l in batch_input.strip().split("\n") if l.strip()]
            if not lines:
                st.error("请输入至少一只股票")
            else:
                results = []
                progress = st.progress(0, "批量分析中...")
                status = st.empty()

                for i, line in enumerate(lines):
                    code = _resolve_input(line, name_map)
                    if not code:
                        results.append({"symbol": line, "name": "未匹配", "error": "无法识别"})
                        continue

                    name = name_map.get(code, "")
                    status.text(f"({i+1}/{len(lines)}) 分析 {code} {name} ...")

                    tech = compute_full_analysis(code)
                    flow = get_fund_flow_summary(code, days=10)
                    funda = fetch_financial_indicators(code)
                    r = analyze_stock(code, name, tech=tech, flow=flow, funda=funda, auto_fetch=False)
                    results.append(r)
                    progress.progress((i + 1) / len(lines))

                progress.empty()
                status.empty()
                _render_batch_results(results)

    # ══════════════════════════════════════════
    # Tab 3: 组合诊断
    # ══════════════════════════════════════════
    with tab_portfolio:
        pf_input = st.text_area(
            "输入持仓股票（每行一个）",
            placeholder="600519 贵州茅台\n000858 五粮液\n600036 招商银行",
            height=120,
            key="ai_pf_input",
        )
        if st.button("🧺 组合诊断", use_container_width=True, type="primary", key="ai_pf_go"):
            lines = [l.strip() for l in pf_input.strip().split("\n") if l.strip()]
            if len(lines) < 2:
                st.error("至少需要2只股票进行组合诊断")
            else:
                stocks = []
                for line in lines:
                    parts = line.split()
                    if parts:
                        code = _resolve_input(parts[0], name_map)
                        if code:
                            name = name_map.get(code, parts[1] if len(parts) > 1 else "")
                            stocks.append((code, name))

                with st.spinner(f"🤖 正在诊断 {len(stocks)} 只股票组合 ..."):
                    result = analyze_portfolio(stocks)

                _render_portfolio_result(result)


def _render_single_result(result: dict):
    """渲染单股分析结果"""
    if result.get("error"):
        st.warning(f"分析异常: {result['error']}")
        if result.get("raw"):
            with st.expander("查看原始回复"):
                st.text(result["raw"])
        return

    st.divider()

    # ── 头部：评分 + 评级 ──
    score = result.get("score", 0) or 0
    rating = result.get("rating", "未知")
    rating_color = {
        "强烈关注": "#00C853", "可关注": "#FFD600",
        "观察": "#FF9100", "暂不建议": "#FF1744",
    }

    hc1, hc2, hc3 = st.columns([2, 1, 3])
    with hc1:
        st.markdown(f"## {result['name']} ({result['symbol']})")
    with hc2:
        color = rating_color.get(rating, "#888")
        st.markdown(
            f"<div style='text-align:center;font-size:48px;font-weight:bold;color:{color}'>{score:.1f}</div>"
            f"<div style='text-align:center'>/ 10</div>",
            unsafe_allow_html=True,
        )
    with hc3:
        st.markdown(f"### {rating}")
        st.markdown(f"> {result.get('summary', '')}")

    # ── 详细分析 ──
    st.divider()
    tab_t, tab_f, tab_b, tab_r = st.tabs([
        "🔧 技术面", "💰 资金面", "📊 基本面", "⚠️ 风险与建议"
    ])

    with tab_t:
        st.markdown(result.get("technical_view", "数据不足"))
        # 展示数据来源
        ds = result.get("data_sources", {})
        if ds.get("tech_available"):
            st.caption("✅ 数据来源: 本地K线数据库")

    with tab_f:
        st.markdown(result.get("fund_flow_view", "数据不足"))
        if ds.get("flow_available"):
            st.caption("✅ 数据来源: 同花顺资金流快照")

    with tab_b:
        st.markdown(result.get("fundamental_view", "数据不足"))
        if ds.get("funda_available"):
            st.caption("✅ 数据来源: 新浪财经财务摘要")

    with tab_r:
        risk = result.get("risk_warning", "")
        if risk and risk != "未发现显著风险":
            st.error(f"🚨 {risk}")
        else:
            st.success("✅ 未发现显著风险")

        levels = result.get("key_levels", {})
        if levels:
            support = levels.get("support", 0)
            resistance = levels.get("resistance", 0)
            if support and resistance:
                st.info(f"📐 关键价位 — 支撑: {support:.2f} | 阻力: {resistance:.2f}")

        st.markdown(f"**💡 操作建议:** {result.get('action_suggestion', '')}")

    # ── 原始回复 ──
    raw = result.get("raw_response", "")
    if raw and "规则引擎" not in str(raw):
        with st.expander("查看 AI 原始回复"):
            st.text(raw)
    elif raw:
        st.caption(f"ℹ️ {raw}")


def _render_batch_results(results: list):
    """渲染批量分析结果表格"""
    st.divider()
    st.subheader(f"批量分析结果 ({len(results)} 只)")

    rows = []
    for r in results:
        rows.append({
            "代码": r.get("symbol", ""),
            "名称": r.get("name", ""),
            "评分": r.get("score") or 0,
            "评级": r.get("rating", "未知"),
            "核心结论": r.get("summary", r.get("error", ""))[:60],
        })

    df = pd.DataFrame(rows)
    df = df.sort_values("评分", ascending=False).reset_index(drop=True)

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "评分": st.column_config.ProgressColumn(
                format="%.1f", min_value=0, max_value=10,
            ),
            "代码": st.column_config.TextColumn(width="small"),
            "名称": st.column_config.TextColumn(width="small"),
            "评级": st.column_config.TextColumn(width="small"),
        },
    )

    # 每只股票展开详情
    for r in results:
        if r.get("error"):
            continue
        with st.expander(f"{r.get('rating', '')} {r['symbol']} {r['name']} — {r.get('score', 0):.1f}分"):
            _render_single_result(r)


def _render_portfolio_result(result: dict):
    """渲染组合诊断结果"""
    st.divider()
    st.subheader("📊 组合诊断报告")

    st.info(result.get("overall_view", ""))

    mc1, mc2 = st.columns(2)
    with mc1:
        st.metric("最佳标的", result.get("best_pick", "N/A"))
    with mc2:
        st.metric("组合均分", f"{result.get('avg_score', 0):.1f} / 10")

    stocks = result.get("stocks", [])
    if stocks:
        st.divider()
        st.subheader("📋 成分股详情")

        rows = []
        for r in stocks:
            rows.append({
                "代码": r["symbol"], "名称": r.get("name", ""),
                "评分": r["score"], "评级": r["rating"],
                "风险": (r.get("risk_warning", "") or "")[:40],
            })
        df = pd.DataFrame(rows)
        df = df.sort_values("评分", ascending=False).reset_index(drop=True)
        st.dataframe(df, use_container_width=True, hide_index=True)
