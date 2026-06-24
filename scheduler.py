"""
定时任务调度 + 消息推送模块

功能:
  1. 后台线程定时执行选股+诊断
  2. 汇总结果生成日报
  3. 推送到企业微信/桌面通知

依赖: schedule (pip install schedule), plyer (pip install plyer)
"""
import json
import threading
import time
from datetime import datetime, date
from pathlib import Path
from typing import Callable, Optional

import requests


# ── 配置 ──
_CONFIG_DIR = Path(__file__).parent.parent / "data_cache"
_CONFIG_FILE = _CONFIG_DIR / "_scheduler_config.json"

DEFAULT_CONFIG = {
    "enabled": False,
    "run_time": "09:00",           # 每日执行时间
    "weekdays_only": True,          # 仅交易日（周一至周五）
    "wechat_webhook_url": "",       # 企业微信机器人 Webhook
    "dingtalk_webhook_url": "",     # 钉钉机器人 Webhook
    "desktop_notify": True,         # 桌面通知开关
    "last_run": None,               # 上次执行时间
    "last_report": "",              # 上次报告摘要
}


def _load_config() -> dict:
    """加载调度配置"""
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if _CONFIG_FILE.exists():
        try:
            with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            cfg = DEFAULT_CONFIG.copy()
            cfg.update(saved)
            return cfg
        except Exception:
            return DEFAULT_CONFIG.copy()
    return DEFAULT_CONFIG.copy()


def save_config(cfg: dict):
    """保存调度配置"""
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def get_config() -> dict:
    return _load_config()


def _send_wechat(msg: str, webhook_url: str) -> bool:
    """推送消息到企业微信机器人"""
    try:
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "content": msg,
            },
        }
        resp = requests.post(webhook_url, json=payload, timeout=10)
        return resp.status_code == 200 and resp.json().get("errcode") == 0
    except Exception:
        return False


def _send_dingtalk(msg: str, webhook_url: str) -> bool:
    """推送消息到钉钉机器人"""
    try:
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": "WinnerK 选股日报",
                "text": msg,
            },
        }
        resp = requests.post(webhook_url, json=payload, timeout=10)
        return resp.status_code == 200
    except Exception:
        return False


def _desktop_notify(title: str, message: str):
    """桌面通知（跨平台）"""
    try:
        from plyer import notification
        notification.notify(
            title=title,
            message=message[:256],
            timeout=10,
        )
    except Exception:
        pass  # plyer 未安装时静默失败


def _build_daily_report(
    zt_result: str,
    flow_result: str,
    anomaly_counts: int,
    candidates: list,
    top_diag: list[dict],
) -> str:
    """构建日报 Markdown 内容"""
    today_str = date.today().strftime("%Y-%m-%d")
    weekday = ["一", "二", "三", "四", "五", "六", "日"][date.today().weekday()]

    lines = [
        f"# 📈 WinnerK 选股日报",
        f"**{today_str} 周{weekday}**",
        "",
        "---",
        "",
        "## 📊 今日概况",
        f"- 涨停板: {zt_result}",
        f"- 资金流: {flow_result}",
        f"- 异动信号: {anomaly_counts} 条",
        f"- 候选池: {len(candidates)} 只",
        "",
    ]

    if top_diag:
        lines.append("## 🎯 综合评分 TOP5")
        lines.append("")
        lines.append("| 排名 | 代码 | 名称 | 评分 | 评级 |")
        lines.append("|------|------|------|------|------|")
        for i, d in enumerate(top_diag[:5]):
            lines.append(
                f"| {i+1} | {d.get('code', '')} | {d.get('name', '')} "
                f"| {d.get('composite', d.get('score', 0)):.1f} | {d.get('rating', '')} |"
            )
        lines.append("")

    lines.append("---")
    lines.append(f"> 🤖 由 WinnerK 股票量化系统自动生成 | {today_str}")

    return "\n".join(lines)


def run_daily_workflow(logger: Callable = None) -> dict:
    """
    执行每日选股+诊断工作流，通过 logger 报告进度。

    返回:
        { "zt": str, "flow": str, "anomalies": int, "candidates": list, "diagnostics": list }
    """
    def _log(msg):
        if logger:
            logger(msg)

    result = {
        "zt": "",
        "flow": "",
        "anomalies": 0,
        "candidates": [],
        "diagnostics": [],
    }

    try:
        # Step 1: 涨停板
        _log("同步TDX数据...")
        from data.sync import sync_from_tdx
        from config import get_tdx_vipdoc_path
        vipdoc = get_tdx_vipdoc_path()
        if vipdoc:
            sync_from_tdx(str(vipdoc), full_import=False)

        _log("拉取涨停板...")
        from data.zt_pool import get_zt_pool
        zt_df = get_zt_pool(force_refresh=True)
        result["zt"] = f"涨停 {len(zt_df)} 只"

        # Step 2: 资金流
        _log("同步资金流...")
        from data.fund_flow import sync_fund_flow_snapshot
        ff = sync_fund_flow_snapshot()
        if ff.get("status") == "ok":
            result["flow"] = f"资金流 {ff['count']} 只"

        # Step 3: 异动
        _log("扫描异动...")
        from data.anomaly import run_all_anomalies
        anomalies = run_all_anomalies()
        result["anomalies"] = sum(
            len(v) if hasattr(v, '__len__') else 0
            for v in anomalies.values()
        )

        # Step 4-6: 多因子
        _log("计算多因子排名...")
        from data.factors import compute_composite_ranking
        ranking = compute_composite_ranking()
        if not ranking.empty:
            top_n = max(5, len(ranking) // 100)
            top = ranking.head(top_n)
            result["candidates"] = top["symbol"].tolist()

            # Step 7: 诊断 TOP5
            _log("4维诊断TOP5...")
            from data.technicals import compute_full_analysis
            from data.fund_flow import get_fund_flow_summary
            from data.fundamental import fetch_financial_indicators
            from data.database import get_stock_name_map
            names = get_stock_name_map()

            for code in result["candidates"][:5]:
                try:
                    tech = compute_full_analysis(code)
                    flow = get_fund_flow_summary(code, days=10)
                    funda = fetch_financial_indicators(code)

                    # 简单评分
                    tech_s = min(70, max(0,
                        (15 if tech.get("close", 0) > (tech.get("ma20") or 0) else 0)
                        + (10 if (tech.get("rsi14") or 50) < 70 else 0)
                        + (10 if (tech.get("macd_hist") or -1) > 0 else 0)
                    ))
                    flow_s = min(40, max(0,
                        (20 if (flow.get("today_main_net_yi") or 0) > 0 else 0)
                    ))
                    funda_s = min(28, max(0,
                        (12 if (funda.get("roe") or 0) > 10 else 0)
                    ))
                    composite = tech_s / 70 * 40 + flow_s / 40 * 30 + funda_s / 28 * 20

                    rating = "可关注" if composite >= 55 else "观察"
                    if composite >= 70:
                        rating = "强烈关注"

                    result["diagnostics"].append({
                        "code": code,
                        "name": names.get(code, ""),
                        "composite": round(composite, 1),
                        "rating": rating,
                    })
                except Exception:
                    pass

    except Exception as e:
        _log(f"❌ 工作流异常: {e}")

    return result


def start_scheduler(logger: Callable = None):
    """
    启动后台调度线程（非阻塞）。

    需要 pip install schedule
    """
    cfg = _load_config()
    if not cfg["enabled"]:
        return None

    try:
        import schedule
    except ImportError:
        if logger:
            logger("⚠️ 请先安装 schedule: pip install schedule")
        return None

    def _job():
        nonlocal cfg
        cfg = _load_config()
        if not cfg["enabled"]:
            return

        # 交易日检查
        if cfg.get("weekdays_only", True):
            if date.today().weekday() >= 5:
                return

        if logger:
            logger(f"[{datetime.now():%H:%M:%S}] ⏰ 定时任务触发...")

        result = run_daily_workflow(logger)
        report = _build_daily_report(
            result["zt"], result["flow"],
            result["anomalies"], result["candidates"],
            result["diagnostics"],
        )

        # 推送
        pushed = False
        wechat_url = cfg.get("wechat_webhook_url", "").strip()
        if wechat_url:
            ok = _send_wechat(report, wechat_url)
            if logger:
                logger(f"企业微信推送: {'成功' if ok else '失败'}")
            pushed = pushed or ok

        dingtalk_url = cfg.get("dingtalk_webhook_url", "").strip()
        if dingtalk_url:
            ok = _send_dingtalk(report, dingtalk_url)
            if logger:
                logger(f"钉钉推送: {'成功' if ok else '失败'}")
            pushed = pushed or ok

        if cfg.get("desktop_notify", True):
            _desktop_notify("WinnerK 选股日报", f"候选池 {len(result['candidates'])} 只")

        # 保存状态
        cfg["last_run"] = datetime.now().isoformat()
        cfg["last_report"] = report[:500]
        save_config(cfg)

        if logger:
            logger(f"✅ 日报生成完成，推送{'成功' if pushed else '未配置渠道'}")

    # 解析执行时间
    run_time = cfg.get("run_time", "09:00")
    schedule.every().day.at(run_time).do(_job)

    if logger:
        logger(f"⏰ 调度器已启动，每日 {run_time} 执行")

    # 后台线程
    def _loop():
        while True:
            schedule.run_pending()
            time.sleep(30)  # 每30秒检查一次

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    return t


def run_now(logger: Callable = None) -> str:
    """立即执行一次日报生成+推送，返回报告文本"""
    result = run_daily_workflow(logger)
    report = _build_daily_report(
        result["zt"], result["flow"],
        result["anomalies"], result["candidates"],
        result["diagnostics"],
    )

    cfg = _load_config()
    wechat_url = cfg.get("wechat_webhook_url", "").strip()
    if wechat_url:
        _send_wechat(report, wechat_url)
    dingtalk_url = cfg.get("dingtalk_webhook_url", "").strip()
    if dingtalk_url:
        _send_dingtalk(report, dingtalk_url)
    if cfg.get("desktop_notify", True):
        _desktop_notify("WinnerK 选股日报", f"候选池 {len(result['candidates'])} 只")

    cfg["last_run"] = datetime.now().isoformat()
    cfg["last_report"] = report[:500]
    save_config(cfg)

    return report
