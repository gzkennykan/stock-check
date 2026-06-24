"""
AI/LLM 智能分析模块：调用大语言模型对个股做多维度解读，生成自然语言投资建议。

支持的LLM提供商:
  - DeepSeek  (默认，国内可用，成本低)
  - 通义千问 (DashScope)
  - OpenAI 兼容接口 (可配自定义 endpoint)

数据输入: 复用现有的 compute_full_analysis / get_fund_flow_summary / fetch_financial_indicators
输出: 自然语言分析报告 + JSON 结构化评分
"""
import json
import os
import requests
from datetime import datetime
from typing import Optional


# ── LLM 配置 ──
# 优先级: 环境变量 > config.py 设置 > 默认值
LLM_CONFIG = {
    "provider": os.getenv("LLM_PROVIDER", "deepseek"),  # deepseek | qwen | openai
    "deepseek": {
        "api_key": os.getenv("DEEPSEEK_API_KEY", ""),
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
    },
    "qwen": {
        "api_key": os.getenv("DASHSCOPE_API_KEY", ""),
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
    },
    "openai": {
        "api_key": os.getenv("OPENAI_API_KEY", ""),
        "base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    },
    "temperature": 0.3,
    "max_tokens": 2048,
}


def get_llm_config() -> dict:
    """获取当前 LLM 配置"""
    provider = LLM_CONFIG["provider"]
    cfg = LLM_CONFIG.get(provider, {})
    return {
        "provider": provider,
        "api_key": cfg.get("api_key", ""),
        "base_url": cfg.get("base_url", ""),
        "model": cfg.get("model", ""),
        "temperature": LLM_CONFIG["temperature"],
        "max_tokens": LLM_CONFIG["max_tokens"],
    }


def set_llm_config(provider: str = None, api_key: str = None,
                   model: str = None, base_url: str = None):
    """运行时设置 LLM 配置（存入 session_state 前调用）"""
    if provider:
        LLM_CONFIG["provider"] = provider
    cfg = LLM_CONFIG.get(LLM_CONFIG["provider"], {})
    if api_key:
        cfg["api_key"] = api_key
    if model:
        cfg["model"] = model
    if base_url:
        cfg["base_url"] = base_url


def _build_system_prompt() -> str:
    """构建系统提示词"""
    return """你是一位资深的A股量化分析师，擅长综合技术面、资金面、基本面和市场情绪给出客观的判断。

你的分析必须：
1. 基于我提供的数据，不编造信息
2. 给出明确的评分（1-10分）和评级（强烈关注/可关注/观察/暂不建议）
3. 指出关键风险点
4. 使用简洁的中文，避免废话

输出格式（严格JSON）：
{
  "score": 7.5,
  "rating": "可关注",
  "summary": "一句话核心结论，不超过50字",
  "technical_view": "技术面分析，2-3句话",
  "fund_flow_view": "资金面分析，2-3句话",
  "fundamental_view": "基本面分析，2-3句话",
  "risk_warning": "主要风险提示，2-3条",
  "key_levels": {"support": 0.0, "resistance": 0.0},
  "action_suggestion": "操作建议，1-2句话"
}"""


def _build_user_prompt(
    symbol: str, name: str,
    tech: dict, flow: dict, funda: dict,
    question: str = None,
) -> str:
    """构建用户提示词（填入实际数据）"""
    parts = [f"请分析 {symbol} {name} 的当前状况。"]

    # ── 技术面数据 ──
    if tech and "error" not in tech:
        parts.append("\n【技术面数据】")
        parts.append(f"- 最新收盘价: {tech.get('close', 'N/A')}")
        parts.append(f"- 近20日收益: {tech.get('ret_20d', 'N/A')}%")
        parts.append(f"- 近60日收益: {tech.get('ret_60d', 'N/A')}%")
        parts.append(f"- 近120日收益: {tech.get('ret_120d', 'N/A')}%")
        parts.append(f"- RSI(14): {tech.get('rsi14', 'N/A')}")
        parts.append(f"- MACD柱: {tech.get('macd_hist', 'N/A')}")
        parts.append(f"- 60日年化波动: {tech.get('vol_60d_annual', 'N/A')}%")
        parts.append(f"- MA20: {tech.get('ma20', 'N/A')}")
        parts.append(f"- MA60: {tech.get('ma60', 'N/A')}")
        parts.append(f"- MA120: {tech.get('ma120', 'N/A')}")
        trend = tech.get("trend", {})
        if trend:
            parts.append(f"- 均线结构: vs MA20={trend.get('vs_ma20', 'N/A')}, "
                        f"vs MA60={trend.get('vs_ma60', 'N/A')}, "
                        f"vs MA120={trend.get('vs_ma120', 'N/A')}")
        parts.append(f"- 20日区间: {tech.get('level_20d_low', 'N/A')} - {tech.get('level_20d_high', 'N/A')}")
        parts.append(f"- 60日区间: {tech.get('level_60d_low', 'N/A')} - {tech.get('level_60d_high', 'N/A')}")

    # ── 资金面数据 ──
    if flow:
        parts.append("\n【资金面数据】")
        parts.append(f"- 今日主力净流入: {flow.get('today_main_net_yi', 'N/A')} 亿元")
        parts.append(f"- 近10日均值: {flow.get('mean', 'N/A')} 亿元/日")
        parts.append(f"- 近10日累计: {sum(d.get('main_net_yi', 0) for d in flow.get('recent_days', [])):.2f} 亿元")
        parts.append(f"- 最新涨跌幅: {flow.get('pct_change', 'N/A')}%")

    # ── 基本面数据 ──
    if funda:
        parts.append("\n【基本面数据】")
        parts.append(f"- ROE: {funda.get('roe', 'N/A')}%")
        parts.append(f"- ROA: {funda.get('roa', 'N/A')}%")
        parts.append(f"- 毛利率: {funda.get('gross_margin', 'N/A')}%")
        parts.append(f"- 净利率: {funda.get('net_margin', 'N/A')}%")
        parts.append(f"- 营收增速: {funda.get('revenue_yoy', 'N/A')}%")
        parts.append(f"- 利润增速: {funda.get('profit_yoy', 'N/A')}%")
        parts.append(f"- 资产负债率: {funda.get('debt_ratio', 'N/A')}%")
        parts.append(f"- EPS: {funda.get('eps', 'N/A')}")
        parts.append(f"- 每股净资产: {funda.get('bps', 'N/A')}")

    if question:
        parts.append(f"\n用户额外问题: {question}")

    parts.append("\n请给出你的分析结果（严格按JSON格式输出）。")
    return "\n".join(parts)


def _call_llm(system_prompt: str, user_prompt: str) -> Optional[str]:
    """调用 LLM API，返回原始文本"""
    cfg = get_llm_config()
    api_key = cfg["api_key"]

    if not api_key:
        return None

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": cfg["temperature"],
        "max_tokens": cfg["max_tokens"],
    }

    try:
        resp = requests.post(
            f"{cfg['base_url']}/chat/completions",
            headers=headers,
            json=payload,
            timeout=60,
        )
        if resp.status_code == 200:
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        else:
            return f"[LLM错误] HTTP {resp.status_code}: {resp.text[:200]}"
    except requests.exceptions.Timeout:
        return "[LLM错误] 请求超时（60秒）"
    except Exception as e:
        return f"[LLM错误] {str(e)[:200]}"


def _parse_llm_response(text: str) -> dict:
    """从 LLM 回复中提取 JSON"""
    if not text:
        return {"error": "LLM 未返回内容", "raw": ""}

    # 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 尝试提取 ```json ... ``` 块
    import re
    m = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # 解析失败，返回原始文本
    return {
        "error": "无法解析LLM返回的JSON",
        "raw": text,
        "score": None,
        "rating": "未知",
        "summary": text[:200],
    }


def analyze_stock(
    symbol: str,
    name: str = "",
    question: str = None,
    tech: dict = None,
    flow: dict = None,
    funda: dict = None,
    auto_fetch: bool = True,
) -> dict:
    """
    对单只股票执行 LLM 智能分析。

    参数:
        symbol:   股票代码
        name:     股票名称
        question: 用户额外问题（可选）
        tech:     技术分析 dict（可选，None 时自动获取）
        flow:     资金流 dict（可选）
        funda:    基本面 dict（可选）
        auto_fetch: 是否自动从数据库拉取数据

    返回:
        {
            "symbol", "name",
            "score": float,        # 1-10 综合评分
            "rating": str,         # 评级
            "summary": str,        # 核心结论
            "technical_view": str,
            "fund_flow_view": str,
            "fundamental_view": str,
            "risk_warning": str,
            "key_levels": {"support": float, "resistance": float},
            "action_suggestion": str,
            "raw_response": str,   # LLM 原始回复
            "data_sources": {...}, # 输入数据源
        }
    """
    # ── 自动拉取数据 ──
    if auto_fetch:
        if tech is None:
            from data.technicals import compute_full_analysis
            tech = compute_full_analysis(symbol)
        if flow is None:
            from data.fund_flow import get_fund_flow_summary
            flow = get_fund_flow_summary(symbol, days=10)
        if funda is None:
            from data.fundamental import fetch_financial_indicators
            funda = fetch_financial_indicators(symbol)

    # ── 构建 prompt ──
    system_prompt = _build_system_prompt()
    user_prompt = _build_user_prompt(symbol, name, tech, flow, funda, question)

    # ── 无 API key 时使用规则引擎 ──
    cfg = get_llm_config()
    if not cfg["api_key"]:
        return _rule_based_analysis(symbol, name, tech, flow, funda, question)

    # ── 调用 LLM ──
    raw = _call_llm(system_prompt, user_prompt)
    result = _parse_llm_response(raw)

    result["symbol"] = symbol
    result["name"] = name
    result["raw_response"] = raw
    result["data_sources"] = {
        "tech_available": tech is not None and "error" not in tech,
        "flow_available": flow is not None,
        "funda_available": funda is not None,
    }

    return result


def _rule_based_analysis(symbol, name, tech, flow, funda, question=None) -> dict:
    """
    无 API key 时的规则引擎兜底分析。
    基于阈值规则生成类似 AI 的输出，确保离线可用。
    """
    score = 5.0
    reasons = []
    risks = []
    support = None
    resistance = None

    # ── 技术面评分 (0-4) ──
    tech_view_parts = []
    if tech and "error" not in tech:
        close = tech.get("close", 0)
        ma20 = tech.get("ma20") or 0
        ma60 = tech.get("ma60") or 0
        rsi = tech.get("rsi14")
        ret20 = tech.get("ret_20d") or 0

        if close > ma20 > 0:
            score += 1.0
            tech_view_parts.append("股价站上MA20，短线偏强")
        elif close < ma20 and ma20 > 0:
            score -= 0.5
            tech_view_parts.append("股价低于MA20，短线承压")

        if close > ma60 > 0:
            score += 0.8
            tech_view_parts.append("站稳MA60，中期趋势向好")
        elif close < ma60 and ma60 > 0:
            score -= 0.3
            risks.append("股价运行在MA60下方，中期趋势偏弱")

        if rsi and rsi > 70:
            score -= 0.5
            tech_view_parts.append(f"RSI={rsi}，处于超买区")
            risks.append("RSI超买，短期回调风险")
        elif rsi and rsi < 30:
            score += 0.5
            tech_view_parts.append(f"RSI={rsi}，处于超卖区，有反弹需求")
        elif rsi:
            tech_view_parts.append(f"RSI={rsi}，处于中性区间")

        if ret20 > 10:
            score += 0.5
            tech_view_parts.append("近20日涨幅>10%，动能强劲")
        elif ret20 < -10:
            score -= 0.5
            tech_view_parts.append("近20日跌幅>10%，短期超跌")
            risks.append("近20日跌幅较大，可能仍有下行惯性")

        support = tech.get("level_60d_low")
        resistance = tech.get("level_60d_high")
        tech_view_parts.append(f"60日区间: {support}-{resistance}")
    else:
        tech_view_parts.append("暂无技术面数据")

    # ── 资金面评分 (0-3) ──
    flow_view_parts = []
    if flow:
        today_yi = flow.get("today_main_net_yi", 0) or 0
        mean_yi = flow.get("mean", 0) or 0
        if today_yi > 1:
            score += 1.5
            flow_view_parts.append(f"今日主力净流入{today_yi:.2f}亿，大资金积极介入")
        elif today_yi > 0.3:
            score += 1.0
            flow_view_parts.append(f"今日主力净流入{today_yi:.2f}亿，小幅流入")
        elif today_yi > 0:
            score += 0.3
            flow_view_parts.append(f"今日主力净流入{today_yi:.2f}亿，微量流入")
        elif today_yi < -1:
            score -= 1.0
            flow_view_parts.append(f"今日主力净流出{abs(today_yi):.2f}亿，资金撤离")
            risks.append("主力资金净流出，短期承压")
        elif today_yi < 0:
            score -= 0.3
            flow_view_parts.append(f"今日主力小幅净流出{abs(today_yi):.2f}亿")

        if mean_yi > 0.5:
            score += 0.5
            flow_view_parts.append(f"近10日均流入{mean_yi:.2f}亿，资金持续关注")
        elif mean_yi < -0.5:
            score -= 0.3
            flow_view_parts.append(f"近10日均流出{abs(mean_yi):.2f}亿")
    else:
        flow_view_parts.append("暂无资金流数据")

    # ── 基本面评分 (0-3) ──
    funda_view_parts = []
    if funda:
        roe = funda.get("roe") or 0
        profit_yoy = funda.get("profit_yoy") or 0
        debt = funda.get("debt_ratio") or 0
        gross = funda.get("gross_margin") or 0

        if roe > 15:
            score += 1.5
            funda_view_parts.append(f"ROE={roe}%，盈利能力优秀")
        elif roe > 10:
            score += 1.0
            funda_view_parts.append(f"ROE={roe}%，盈利良好")
        elif roe > 5:
            score += 0.3
            funda_view_parts.append(f"ROE={roe}%，盈利一般")
        elif roe > 0:
            funda_view_parts.append(f"ROE={roe}%，盈利偏低")
        else:
            score -= 0.5
            funda_view_parts.append("ROE为负，处于亏损状态")
            risks.append("公司盈利能力较弱（ROE偏低/为负）")

        if profit_yoy > 30:
            score += 0.8
            funda_view_parts.append(f"利润增速{profit_yoy}%，高增长")
        elif profit_yoy > 0:
            score += 0.3
            funda_view_parts.append(f"利润增速{profit_yoy}%，正增长")
        elif profit_yoy < 0:
            score -= 0.3
            funda_view_parts.append(f"利润增速{profit_yoy}%，负增长")
            risks.append(f"利润同比下滑{abs(profit_yoy)}%")

        if debt > 80:
            score -= 0.5
            risks.append(f"资产负债率{debt}%，财务杠杆偏高")
        elif 20 <= debt <= 60:
            score += 0.2

        if gross > 30:
            score += 0.3
            funda_view_parts.append(f"毛利率{gross}%，竞争力较强")
    else:
        funda_view_parts.append("暂无基本面数据")

    # ── 综合 ──
    score = max(1.0, min(10.0, score))
    if score >= 7.5:
        rating = "强烈关注"
    elif score >= 6.0:
        rating = "可关注"
    elif score >= 4.0:
        rating = "观察"
    else:
        rating = "暂不建议"

    summary_map = {
        (7.5, 11): "综合评分优秀，技术面与资金面共振，值得重点关注",
        (6.0, 7.5): "综合评分良好，多数指标正面，可适当关注",
        (4.0, 6.0): "综合评分中等，存在一些不确定因素，建议观察",
        (0, 4.0): "综合评分偏低，多项指标偏弱，暂不建议介入",
    }
    summary = "综合评分中等"
    for (lo, hi), text in summary_map.items():
        if lo <= score < hi:
            summary = text
            break

    return {
        "symbol": symbol,
        "name": name,
        "score": round(score, 1),
        "rating": rating,
        "summary": summary,
        "technical_view": "；".join(tech_view_parts) if tech_view_parts else "数据不足",
        "fund_flow_view": "；".join(flow_view_parts) if flow_view_parts else "数据不足",
        "fundamental_view": "；".join(funda_view_parts) if funda_view_parts else "数据不足",
        "risk_warning": "；".join(risks) if risks else "未发现显著风险",
        "key_levels": {"support": support or 0, "resistance": resistance or 0},
        "action_suggestion": _gen_action(score, symbol, name),
        "raw_response": "[规则引擎模式 - 未配置LLM API Key]",
        "data_sources": {
            "tech_available": tech is not None and "error" not in tech,
            "flow_available": flow is not None,
            "funda_available": funda is not None,
        },
    }


def _gen_action(score: float, symbol: str, name: str) -> str:
    """根据评分生成操作建议"""
    if score >= 7.5:
        return f"建议将{name}({symbol})加入重点观察列表，等待回调至均线支撑位时分批建仓"
    elif score >= 6.0:
        return f"建议轻仓试探{name}({symbol})，设置止损位在近期低点下方3-5%"
    elif score >= 4.0:
        return f"建议暂时观望{name}({symbol})，等待技术面或资金面出现明确转强信号"
    else:
        return f"暂不建议参与{name}({symbol})，可关注同行业基本面更优的标的"


def analyze_portfolio(stocks: list[tuple[str, str]]) -> dict:
    """
    对一组股票做组合层面的 LLM 分析。

    参数:
        stocks: [(code, name), ...]

    返回:
        { "overall_view": str, "best_pick": str, "risk_summary": str, "stocks": [...] }
    """
    # 先对每只股票做规则引擎分析（不用LLM，省token）
    results = []
    for code, name in stocks:
        from data.technicals import compute_full_analysis
        from data.fund_flow import get_fund_flow_summary
        from data.fundamental import fetch_financial_indicators

        tech = compute_full_analysis(code)
        flow = get_fund_flow_summary(code, days=10)
        funda = fetch_financial_indicators(code)

        r = _rule_based_analysis(code, name, tech, flow, funda)
        results.append(r)

    if not results:
        return {"overall_view": "无数据", "stocks": []}

    # 排序取最佳
    results.sort(key=lambda x: x["score"], reverse=True)
    best = results[0]
    avg_score = sum(r["score"] for r in results) / len(results)

    overall = (
        f"组合共{len(results)}只股票，均分{avg_score:.1f}。"
        f"最佳标的: {best['name']}({best['symbol']})，评分{best['score']}。"
        f"整体{'偏强' if avg_score >= 6 else '中性' if avg_score >= 4 else '偏弱'}，"
        f"建议{'积极布局' if avg_score >= 6 else '精选个股' if avg_score >= 4 else '等待时机'}。"
    )

    return {
        "overall_view": overall,
        "best_pick": f"{best['name']}({best['symbol']})",
        "best_score": best["score"],
        "avg_score": round(avg_score, 1),
        "stocks": results,
    }
