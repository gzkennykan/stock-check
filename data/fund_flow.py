"""
个股资金流向模块：本地 DuckDB 历史快照

数据源: 同花顺 (10jqka) → AKShare stock_fund_flow_individual()
策略: 每次打开程序自动抓取当日全市场排名快照存入 DuckDB fund_flow_daily 表，
       日积月累形成个股历史资金流档案。

优势: 离线可用，不依赖东方财富（已被封），历史越长分析越有价值。
"""
import numpy as np
import pandas as pd
from datetime import datetime
from pathlib import Path

from utils import retry
from data.database import (
    insert_fund_flow_snapshot, get_fund_flow_history,
    get_fund_flow_latest_date,
)


@retry(times=2, delay=2.0)
def _fetch_daily_ranking_from_10jqka() -> pd.DataFrame:
    """
    从同花顺获取当日全市场资金流向排名（约 5200 只股票）。
    返回 DataFrame: [code, name, price, pct_change, turnover_rate,
                      capital_inflow, capital_outflow, main_capital, turnover]
    """
    import akshare as ak
    try:
        raw = ak.stock_fund_flow_individual()
    except Exception as e:
        raise RuntimeError(f"同花顺资金流接口调用失败: {e}")

    if raw is None or raw.empty:
        raise RuntimeError("同花顺返回空数据")

    raw.columns = [
        "rank", "code", "name", "price", "pct_change_str", "turnover_rate_str",
        "capital_inflow_str", "capital_outflow_str", "main_capital_str", "turnover_str"
    ]

    df = raw.copy()
    df = df.drop(columns=["rank"])
    df["code"] = df["code"].astype(str).str.strip().str.zfill(6)

    # 数值清洗
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["pct_change"] = df["pct_change_str"].astype(str).str.replace("%", "", regex=False)
    df["pct_change"] = pd.to_numeric(df["pct_change"], errors="coerce")
    df["turnover_rate"] = df["turnover_rate_str"].astype(str).str.replace("%", "", regex=False)
    df["turnover_rate"] = pd.to_numeric(df["turnover_rate"], errors="coerce")

    # 资金列（带"亿"/"万"单位）
    from utils import parse_cn_money
    for src, dst in [
        ("capital_inflow_str", "capital_inflow"),
        ("capital_outflow_str", "capital_outflow"),
        ("main_capital_str", "main_capital"),
        ("turnover_str", "turnover"),
    ]:
        df[dst] = df[src].apply(parse_cn_money)

    df = df.drop(columns=["pct_change_str", "turnover_rate_str",
                           "capital_inflow_str", "capital_outflow_str",
                           "main_capital_str", "turnover_str"], errors="ignore")
    return df


def sync_fund_flow_snapshot(force: bool = False) -> dict:
    """
    同步当日全市场资金流快照到 DuckDB。
    同一天只同步一次（force=True 强制覆盖）。

    返回: {"status": "ok"/"error"/"skipped", "count": N, "date": "...", "message": ""}
    """
    today = datetime.now().strftime("%Y-%m-%d")

    # 检查今天是否已有数据
    if not force:
        latest = get_fund_flow_latest_date()
        if latest and latest >= today:
            return {"status": "skipped", "count": 0, "date": latest,
                     "message": f"今日({today})已有快照"}

    try:
        df = _fetch_daily_ranking_from_10jqka()
    except Exception as e:
        return {"status": "error", "count": 0, "date": today,
                "message": str(e)}

    if df.empty:
        return {"status": "error", "count": 0, "date": today,
                "message": "同花顺返回空数据"}

    try:
        n = insert_fund_flow_snapshot(df, trade_date=today)
    except Exception as e:
        return {"status": "error", "count": 0, "date": today,
                "message": f"写入DB失败: {e}"}

    return {"status": "ok", "count": n, "date": today,
            "message": f"已保存 {n} 只股票资金流快照"}


def get_individual_fund_flow(symbol: str, force_refresh: bool = False) -> pd.DataFrame | None:
    """
    从本地 DuckDB 读取个股资金流历史（最多 120 个交易日）。

    返回列:
        date, price, pct_change, turnover_rate,
        main_net (净额), capital_inflow, capital_outflow, turnover
    """
    # 确保今日快照存在
    if force_refresh:
        try:
            sync_fund_flow_snapshot(force=True)
        except Exception:
            pass

    s = str(symbol).strip().zfill(6)
    df = get_fund_flow_history(s, limit=120)
    if df is None or df.empty:
        return None
    df = df.rename(columns={"trade_date": "date"})
    return df


def get_fund_flow_summary(symbol: str, days: int = 10) -> dict | None:
    """
    从本地 DuckDB 读取个股资金流统计摘要。

    返回:
        { "latest_date", "close", "pct_change",
          "today_main_net", "today_main_net_yi",
          "mean", "median", "min", "max",
          "recent_days": [{date, main_net_yi, close}, ...] }
    """
    df = get_individual_fund_flow(symbol)
    if df is None or df.empty:
        return None

    recent = df.tail(days).copy()
    if "main_net" not in recent.columns:
        return None

    main_net = recent["main_net"].dropna()
    if main_net.empty:
        return None

    latest = recent.iloc[-1]

    recent_list = []
    for _, r in recent.iterrows():
        recent_list.append({
            "date": str(r["date"])[:10] if pd.notna(r["date"]) else "",
            "main_net_yi": round(float(r["main_net"]) / 1e8, 4) if pd.notna(r.get("main_net")) else 0,
            "close": round(float(r.get("price", 0)), 2) if pd.notna(r.get("price")) else 0,
        })

    return {
        "latest_date": str(latest["date"])[:10] if pd.notna(latest["date"]) else "",
        "close": round(float(latest.get("price", 0)), 2),
        "pct_change": round(float(latest.get("pct_change", 0)), 2),
        "today_main_net": float(main_net.iloc[-1]) if len(main_net) > 0 else 0,
        "today_main_net_yi": round(float(main_net.iloc[-1]) / 1e8, 4) if len(main_net) > 0 else 0,
        "mean": round(float(main_net.mean()) / 1e8, 4),
        "median": round(float(main_net.median()) / 1e8, 4),
        "min": round(float(main_net.min()) / 1e8, 4),
        "max": round(float(main_net.max()) / 1e8, 4),
        "recent_days": recent_list,
    }
