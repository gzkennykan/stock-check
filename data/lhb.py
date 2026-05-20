"""
龙虎榜数据模块：新浪源（无墙）+ 个股席位明细抓取
"""
import pandas as pd
import requests
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup
from utils import get_cache_ttl, retry

_LHB_CACHE_DIR = Path(__file__).parent.parent / "data_cache"
_LHB_SEAT_DIR = _LHB_CACHE_DIR / "lhb_seats"


def _lhb_daily_cache_path(date: str) -> Path:
    """返回指定日期的龙虎榜缓存文件路径"""
    return _LHB_CACHE_DIR / f"_lhb_daily_{date}.csv"


def _cleanup_old_lhb_caches(keep_days: int = 7):
    """清理超过 keep_days 天的旧龙虎榜缓存文件"""
    import glob
    import os
    import time
    cutoff = time.time() - keep_days * 86400
    for f in _LHB_CACHE_DIR.glob("_lhb_daily_*.csv"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
        except Exception:
            pass


def _lhb_type(symbol: str) -> str:
    """根据代码判断龙虎榜 type 参数: 01=上海, 02=深圳"""
    s = str(symbol).strip()
    if s.startswith(("6", "5", "9")):
        return "01"
    elif s.startswith(("0", "3", "2")):
        return "02"
    return "02"


def _today_str() -> str:
    return datetime.now().strftime("%Y%m%d")


@retry(times=2, delay=1.0)
def _fetch_lhb_daily_sina(date: str) -> pd.DataFrame:
    """封装 AKShare stock_lhb_detail_daily_sina，按位置索引映射列（避免列名编码问题）"""
    import akshare as ak
    try:
        raw = ak.stock_lhb_detail_daily_sina(date=date)
    except Exception as e:
        raise RuntimeError(f"AKShare 龙虎榜接口调用失败: {e}")

    if raw is None or raw.empty:
        return pd.DataFrame()

    # 按位置取列，不依赖列名（避免编码问题）
    ncols = raw.shape[1]
    if ncols < 8:
        return pd.DataFrame()

    df = pd.DataFrame()
    df["code"] = raw.iloc[:, 1].astype(str).str.strip()
    df["name"] = raw.iloc[:, 2].astype(str).str.strip()
    df["close"] = pd.to_numeric(raw.iloc[:, 3], errors="coerce")
    df["pct_change"] = pd.to_numeric(raw.iloc[:, 4], errors="coerce")
    df["volume"] = pd.to_numeric(raw.iloc[:, 5], errors="coerce")
    df["turnover"] = pd.to_numeric(raw.iloc[:, 6], errors="coerce")
    df["reason"] = raw.iloc[:, 7].astype(str).str.strip()

    df = df.sort_values("turnover", ascending=False).drop_duplicates(subset="code", keep="first")
    return df


@retry(times=2, delay=1.0)
def _fetch_lhb_ggtj_sina(symbol: str = "5") -> pd.DataFrame:
    """封装 AKShare stock_lhb_ggtj_sina，按位置索引映射列"""
    import akshare as ak
    try:
        raw = ak.stock_lhb_ggtj_sina(symbol=symbol)
    except Exception:
        return pd.DataFrame()

    if raw is None or raw.empty or raw.shape[1] < 8:
        return pd.DataFrame()

    df = pd.DataFrame()
    df["code"] = raw.iloc[:, 0].astype(str).str.strip()
    df["onboard_days"] = pd.to_numeric(raw.iloc[:, 2], errors="coerce")
    df["accum_buy"] = pd.to_numeric(raw.iloc[:, 3], errors="coerce")
    df["accum_sell"] = pd.to_numeric(raw.iloc[:, 4], errors="coerce")
    df["net_buy"] = pd.to_numeric(raw.iloc[:, 5], errors="coerce")
    df["buy_seat_count"] = pd.to_numeric(raw.iloc[:, 6], errors="coerce")
    df["sell_seat_count"] = pd.to_numeric(raw.iloc[:, 7], errors="coerce")

    for c in df.columns:
        if c != "code":
            df[c] = df[c].fillna(0)
    df = df.sort_values("onboard_days", ascending=False).drop_duplicates(subset="code", keep="first")
    return df


@retry(times=2, delay=1.0)
def _fetch_lhb_jgmx_sina() -> pd.DataFrame:
    """封装 AKShare stock_lhb_jgmx_sina，按位置索引映射列"""
    import akshare as ak
    try:
        raw = ak.stock_lhb_jgmx_sina()
    except Exception:
        return pd.DataFrame()

    if raw is None or raw.empty or raw.shape[1] < 5:
        return pd.DataFrame()

    df = pd.DataFrame()
    df["code"] = raw.iloc[:, 0].astype(str).str.strip()
    df["date"] = raw.iloc[:, 2].astype(str).str.strip()
    df["inst_buy"] = pd.to_numeric(raw.iloc[:, 3], errors="coerce")
    df["inst_sell"] = pd.to_numeric(raw.iloc[:, 4], errors="coerce")

    # 过滤当天
    today_match = datetime.now().strftime("%Y-%m-%d")
    df = df[df["date"] == today_match]
    return df.drop(columns=["date"])


@retry(times=2, delay=1.0)
def _scrape_seat_detail(symbol: str, date: str) -> pd.DataFrame:
    """
    通过 Sina AJAX 接口获取个股龙虎榜席位买卖明细。
    date 格式: "2026-05-12"
    返回列: symbol, date, side, seat_name, buy_amount, sell_amount, net_amount
    金额单位: 万元
    """
    import json
    url = "http://vip.stock.finance.sina.com.cn/q/api/jsonp.php/var%20details=/InvestConsultService.getLHBComBSData"
    params = {"symbol": symbol, "tradedate": date, "type": "02"}
    r = requests.get(url, params=params, timeout=15,
                     headers={"Referer": "https://vip.stock.finance.sina.com.cn/"})
    if r.status_code != 200:
        return pd.DataFrame()

    # 解析 JSONP: 去除开头注释 /*...*/ 再取 var details=({...});
    text = r.text.strip()
    # 去掉开头的 JS 注释块
    if text.startswith("/*"):
        comment_end = text.find("*/")
        if comment_end > 0:
            text = text[comment_end + 2:].strip()
    prefix = "var details="
    if prefix in text:
        json_str = text[text.find(prefix) + len(prefix):].rstrip(";")
        if json_str.startswith("(") and json_str.endswith(")"):
            json_str = json_str[1:-1]
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return pd.DataFrame()
    else:
        return pd.DataFrame()

    records = []
    for side_key, side_label in [("buy", "买入"), ("sell", "卖出")]:
        items = data.get(side_key, [])
        for item in items:
            rec = {
                "symbol": symbol,
                "date": date,
                "side": side_label,
                "seat_name": item.get("comName", ""),
                "buy_amount": float(item.get("buyAmount", 0)),
                "sell_amount": float(item.get("sellAmount", 0)),
                "net_amount": float(item.get("netAmount", 0)),
            }
            records.append(rec)

    if not records:
        return pd.DataFrame()
    return pd.DataFrame(records)


def get_lhb_seat_detail(symbol: str, date: str, force_refresh: bool = False) -> pd.DataFrame:
    """获取单只股票某日龙虎榜席位明细，缓存到 lhb_seats/ 目录"""
    _LHB_SEAT_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = _LHB_SEAT_DIR / f"{symbol}_{date.replace('-', '')}.csv"
    if not force_refresh and cache_file.exists():
        return pd.read_csv(cache_file, dtype={"symbol": str})

    df = _scrape_seat_detail(symbol, date)
    if not df.empty:
        df.to_csv(cache_file, index=False)
    return df


def get_lhb_daily(date: str | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """获取龙虎榜日榜聚合数据：行情 + 上榜天数 + 机构买卖。按日期缓存"""
    if date is None:
        date = _today_str()

    cache_path = _lhb_daily_cache_path(date)

    if not force_refresh and cache_path.exists():
        mtime = datetime.fromtimestamp(cache_path.stat().st_mtime)
        if (datetime.now() - mtime).total_seconds() < get_cache_ttl(5, 30) * 60:
            df = pd.read_csv(cache_path, dtype={"code": str})
            if "date" in df.columns:
                return df

    _LHB_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    daily = _fetch_lhb_daily_sina(date)
    if daily.empty:
        return pd.DataFrame()

    try:
        ggtj = _fetch_lhb_ggtj_sina("5")
    except Exception:
        ggtj = pd.DataFrame()

    try:
        jgmx = _fetch_lhb_jgmx_sina()
    except Exception:
        jgmx = pd.DataFrame()

    merged = daily.copy()
    if not ggtj.empty:
        merged = merged.merge(ggtj, on="code", how="left")
    if not jgmx.empty:
        merged = merged.merge(jgmx, on="code", how="left")

    for col in ["onboard_days", "accum_buy", "accum_sell", "net_buy",
                "buy_seat_count", "sell_seat_count", "inst_buy", "inst_sell"]:
        if col in merged.columns:
            merged[col] = merged[col].fillna(0)
        else:
            merged[col] = 0

    merged["date"] = date
    merged.to_csv(cache_path, index=False)
    _cleanup_old_lhb_caches()
    return merged
