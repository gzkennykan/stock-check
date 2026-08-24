"""
自定义策略模板 + 历史验证模块

模板注册表：每个模板 = 声明式参数 + run_fn(end_date, params) -> DataFrame[symbol, close, score]
历史验证：按日期循环在历史各交易日跑模板 → record_signals(source=f"template:{id}")
         → 复用 signal_tracker 的 validate/summarize 闭环，统计命中率/平均超额。

与现有 8 个硬编码策略不同，这里提供可配置、可复用的「选股规则模板」，
专用于历史信号回测（事件研究式），验证某条规则的长期有效性。
"""
import pandas as pd
from datetime import timedelta

from .database import (
    get_connection, _table_exists, get_stock_name_map, get_latest_trading_date,
)
from .signal_tracker import record_signals, validate_signals, summarize_validation
from .patterns import scan_golden_cross, scan_volume_breakout, scan_new_high


# ─────────────────────────── 工具函数 ───────────────────────────

def _to_signal_df(df: pd.DataFrame, score_col: str = None) -> pd.DataFrame:
    """把扫描结果统一为 [code, name, price, score] 供 record_signals 使用。"""
    if df is None or df.empty:
        return pd.DataFrame(columns=["code", "name", "price", "score"])
    out = pd.DataFrame()
    out["code"] = df["symbol"].astype(str).str.strip().str.zfill(6)
    if "close" in df.columns:
        out["price"] = pd.to_numeric(df["close"], errors="coerce")
    else:
        out["price"] = None
    if score_col and score_col in df.columns:
        out["score"] = pd.to_numeric(df[score_col], errors="coerce")
    else:
        out["score"] = None
    names = get_stock_name_map()
    out["name"] = out["code"].map(names).fillna("")
    return out


def _trading_dates(start_date: str, end_date: str) -> list[str]:
    """取区间内全部交易日（升序，字符串 YYYY-MM-DD）。"""
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "daily_kline"):
            return []
        df = conn.execute(
            "SELECT DISTINCT trade_date FROM daily_kline "
            "WHERE trade_date BETWEEN ? AND ? ORDER BY trade_date",
            [start_date, end_date],
        ).df()
        return [str(d)[:10] for d in df["trade_date"].tolist()]
    finally:
        conn.close()


# ─────────────────────────── 模板 run_fn 实现 ───────────────────────────

def _run_ma_bullish(end_date: str, params: dict) -> pd.DataFrame:
    """均线多头排列：MA5 > MA20 > MA60 且收盘价站上 MA20。"""
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "daily_kline"):
            return pd.DataFrame()
        base = (pd.to_datetime(end_date) - pd.Timedelta(days=150)).strftime("%Y-%m-%d")
        df = conn.execute("""
            WITH ma AS (
                SELECT symbol, trade_date, close,
                    AVG(close) OVER w5  AS ma5,
                    AVG(close) OVER w20 AS ma20,
                    AVG(close) OVER w60 AS ma60
                FROM daily_kline
                WHERE trade_date >= ?
                WINDOW w5  AS (PARTITION BY symbol ORDER BY trade_date ROWS 4 PRECEDING),
                       w20 AS (PARTITION BY symbol ORDER BY trade_date ROWS 19 PRECEDING),
                       w60 AS (PARTITION BY symbol ORDER BY trade_date ROWS 59 PRECEDING)
            )
            SELECT symbol, ROUND(close, 2) as close,
                ROUND(ma5, 2) as ma5, ROUND(ma20, 2) as ma20, ROUND(ma60, 2) as ma60,
                ROUND((close / NULLIF(ma20, 0) - 1) * 100, 2) as score
            FROM ma
            WHERE trade_date = ?
              AND ma60 > 0 AND ma20 > 0 AND ma5 > 0
              AND ma5 > ma20 AND ma20 > ma60 AND close > ma20
            ORDER BY score DESC
        """, [base, end_date]).df()
        return df
    finally:
        conn.close()


def _run_rsi_oversold(end_date: str, params: dict) -> pd.DataFrame:
    """RSI 超卖：RSI14 < 阈值（潜在反弹）。"""
    threshold = float(params.get("threshold", 30))
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "daily_kline"):
            return pd.DataFrame()
        base = (pd.to_datetime(end_date) - pd.Timedelta(days=100)).strftime("%Y-%m-%d")
        df = conn.execute("""
            WITH gains AS (
                SELECT symbol, trade_date, close,
                    close - LAG(close,1) OVER (PARTITION BY symbol ORDER BY trade_date) AS delta
                FROM daily_kline WHERE trade_date >= ?
            ),
            smoothed AS (
                SELECT symbol, trade_date,
                    AVG(CASE WHEN delta > 0 THEN delta ELSE 0 END)
                        OVER (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 13 PRECEDING AND CURRENT ROW) AS avg_gain,
                    AVG(CASE WHEN delta < 0 THEN -delta ELSE 0 END)
                        OVER (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 13 PRECEDING AND CURRENT ROW) AS avg_loss
                FROM gains
            )
            SELECT s.symbol, ROUND(c.close, 2) as close,
                ROUND(100 - 100 / (1 + s.avg_gain / NULLIF(s.avg_loss, 0)), 2) AS rsi,
                ROUND(? - (100 - 100 / (1 + s.avg_gain / NULLIF(s.avg_loss, 0))), 2) AS score
            FROM smoothed s
            JOIN daily_kline c ON c.symbol = s.symbol AND c.trade_date = s.trade_date
            WHERE s.trade_date = ?
              AND s.avg_loss > 0
              AND (100 - 100 / (1 + s.avg_gain / NULLIF(s.avg_loss, 0))) < ?
            ORDER BY score DESC
        """, [base, end_date, threshold]).df()
        return df
    finally:
        conn.close()


def _run_multi_factor(end_date: str, params: dict) -> pd.DataFrame:
    """综合多因子评分 TOP N（较慢，全市场因子计算）。"""
    from .factors import compute_composite_ranking
    top_n = int(params.get("top_n", 30))
    df = compute_composite_ranking(end_date)
    if df is None or df.empty:
        return pd.DataFrame()
    return df.head(top_n)


def _wrap_pattern(scan_fn, default_kwargs: dict):
    """把 data/patterns 的单日全市场扫描函数包成模板 run_fn。"""
    def run(end_date, params):
        kw = dict(default_kwargs)
        for k, v in kw.items():
            if k in params:
                kw[k] = type(v)(params[k])
        df = scan_fn(end_date, **kw)
        return df if df is not None else pd.DataFrame()
    return run


# ─────────────────────────── 模板注册表 ───────────────────────────

TEMPLATES: list[dict] = [
    {
        "id": "ma_bullish",
        "name": "均线多头排列",
        "desc": "MA5>MA20>MA60 且收盘价站上 MA20 — 多头趋势启动",
        "params_schema": [],
        "run_fn": _run_ma_bullish,
        "score_col": "score",
        "slow": False,
    },
    {
        "id": "ma_golden_cross",
        "name": "MA5金叉MA20",
        "desc": "MA5 上穿 MA20（最近 N 日内发生）",
        "params_schema": [
            {"key": "lookback_days", "label": "交叉回溯天数", "default": 5, "min": 1, "max": 20},
        ],
        "run_fn": _wrap_pattern(scan_golden_cross, {"lookback_days": 5}),
        "score_col": None,
        "slow": False,
    },
    {
        "id": "volume_breakout",
        "name": "放量突破",
        "desc": "价格突破 MA60 且成交量 > N 倍 20 日均量",
        "params_schema": [
            {"key": "vol_multiplier", "label": "量比阈值", "default": 2.0, "min": 1.0, "max": 5.0, "step": 0.1},
        ],
        "run_fn": _wrap_pattern(scan_volume_breakout, {"vol_multiplier": 2.0}),
        "score_col": "vol_ratio",
        "slow": False,
    },
    {
        "id": "new_high",
        "name": "N日新高",
        "desc": "当日收盘价创 N 日新高 — 向上突破",
        "params_schema": [
            {"key": "n_days", "label": "N日", "default": 60, "min": 10, "max": 250},
        ],
        "run_fn": _wrap_pattern(scan_new_high, {"n_days": 60}),
        "score_col": None,
        "slow": False,
    },
    {
        "id": "rsi_oversold",
        "name": "RSI超卖",
        "desc": "RSI14 低于阈值 — 超卖潜在反弹",
        "params_schema": [
            {"key": "threshold", "label": "RSI阈值", "default": 30, "min": 10, "max": 50},
        ],
        "run_fn": _run_rsi_oversold,
        "score_col": "score",
        "slow": False,
    },
    {
        "id": "multi_factor_top",
        "name": "多因子TOP",
        "desc": "综合多因子评分最高的 N 只（动量/波动/量能/趋势/回撤）",
        "params_schema": [
            {"key": "top_n", "label": "TOP N", "default": 30, "min": 10, "max": 100},
        ],
        "run_fn": _run_multi_factor,
        "score_col": "composite",
        "slow": True,
    },
]


def get_template(template_id: str) -> dict | None:
    for t in TEMPLATES:
        if t["id"] == template_id:
            return t
    return None


# ─────────────────────────── 历史验证 ───────────────────────────

def backtest_template(template_id: str, start_date: str, end_date: str,
                      interval_days: int = 5, params: dict = None,
                      top_n: int = None) -> dict | None:
    """
    在历史各交易日等间隔跑模板并记录信号（幂等：同日期同股票覆盖）。

    返回: {template_id, name, dates_run, total_signals, per_date:[{date,count}]}
    """
    tmpl = get_template(template_id)
    if tmpl is None:
        return None
    params = params or {}
    dates = _trading_dates(start_date, end_date)
    sampled = dates[::max(1, interval_days)]

    per_date, total = [], 0
    for d in sampled:
        try:
            df = tmpl["run_fn"](d, params)
            sig = _to_signal_df(df, tmpl.get("score_col"))
            if top_n and not sig.empty:
                sig = sig.head(top_n)
            n = record_signals(sig, source=f"template:{template_id}", signal_date=d)
            if n:
                total += n
                per_date.append({"date": d, "count": n})
        except Exception:
            continue

    return {
        "template_id": template_id,
        "name": tmpl["name"],
        "dates_run": len(sampled),
        "total_signals": total,
        "per_date": per_date,
    }


def validate_template(template_id: str, forward_days=(1, 5, 20),
                      benchmark: str = "000300") -> pd.DataFrame:
    """对某模板的历史信号做验证，返回明细。"""
    return validate_signals(forward_days=forward_days, benchmark=benchmark,
                            source=f"template:{template_id}")


def summarize_template(template_id: str, forward_days=(1, 5, 20),
                       benchmark: str = "000300") -> pd.DataFrame:
    """对某模板的历史信号做汇总（命中率/平均收益/平均超额/超额胜率）。"""
    return summarize_validation(forward_days=forward_days, benchmark=benchmark,
                                source=f"template:{template_id}")


# 便于 UI 计算默认回测区间
def default_backtest_range() -> tuple[str, str]:
    """返回 (起始日期, 结束日期)：最近约一年，结束日留出未来验证空间。"""
    latest = get_latest_trading_date()
    if latest is None:
        return "2025-01-01", "2025-12-31"
    end = pd.Timestamp(latest) - timedelta(days=60)
    start = pd.Timestamp(latest) - timedelta(days=425)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
