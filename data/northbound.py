"""
北向资金数据模块：沪股通/深股通资金流向分析
数据源: 东方财富 datacenter-web API
"""
import time
import random
import pandas as pd
from datetime import datetime
from pathlib import Path
from utils import retry, resilient_get, resilient_session

_CACHE_DIR = Path(__file__).parent.parent / "data_cache"
_NB_FLOW_CACHE = _CACHE_DIR / "northbound_flow.csv"


def fetch_northbound_flow(start_date: str = None, end_date: str = None) -> pd.DataFrame:
    """
    获取北向资金每日总成交额历史数据（亿元）。

    返回 DataFrame，日期索引，含 deal_amt（总成交额，亿）。
    注：每日净买入/净卖出数据已于2024年8月停止披露，不再返回。
    失败时返回缓存数据（如有）。
    """
    try:
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        all_records = []
        page = 1
        session = resilient_session()
        while True:
            params = {
                "sortColumns": "TRADE_DATE",
                "sortTypes": "-1",
                "pageSize": "1000",
                "pageNumber": str(page),
                "reportName": "RPT_MUTUAL_DEAL_HISTORY",
                "columns": "TRADE_DATE,DEAL_AMT",
                "source": "WEB",
                "client": "WEB",
                "filter": '(MUTUAL_TYPE="005")',
            }
            r = resilient_get(url, params=params, timeout=30, session=session)
            data = r.json()
            if not data.get("success"):
                break
            result = data["result"]
            if result is None:
                break
            records = result.get("data") or []
            all_records.extend(records)
            if page >= (result.get("pages") or 1):
                break
            page += 1
            time.sleep(random.uniform(0.3, 0.8))  # 分页节流

        if not all_records:
            return _load_nb_cache(start_date, end_date)

        df = pd.DataFrame(all_records)
        result = pd.DataFrame()
        result["date"] = pd.to_datetime(df["TRADE_DATE"])
        result["deal_amt"] = pd.to_numeric(df["DEAL_AMT"], errors="coerce") / 10000  # 万元→亿
        result = result.set_index("date").sort_index()
        result = result.dropna(subset=["deal_amt"])

        # 写缓存
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        result.to_csv(_NB_FLOW_CACHE)

        if start_date:
            result = result.loc[result.index >= start_date]
        if end_date:
            result = result.loc[result.index <= end_date]
        return result
    except Exception:
        return _load_nb_cache(start_date, end_date)


def _load_nb_cache(start_date=None, end_date=None) -> pd.DataFrame:
    """加载北向资金缓存数据"""
    if _NB_FLOW_CACHE.exists():
        df = pd.read_csv(_NB_FLOW_CACHE, index_col=0, parse_dates=True)
        df = df.sort_index()
        if start_date:
            df = df.loc[df.index >= start_date]
        if end_date:
            df = df.loc[df.index <= end_date]
        return df
    return pd.DataFrame()


def fetch_northbound_summary() -> pd.DataFrame:
    """获取当日北向资金市场汇总（沪股通/深股通分别统计）"""
    import akshare as ak
    try:
        df = ak.stock_hsgt_fund_flow_summary_em()
        if df is not None and not df.empty:
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)
            df.to_csv(_CACHE_DIR / "northbound_summary.csv", index=False)
        return df if df is not None else pd.DataFrame()
    except Exception:
        cache_file = _CACHE_DIR / "northbound_summary.csv"
        if cache_file.exists():
            return pd.read_csv(cache_file)
        return pd.DataFrame()


@retry(times=2, delay=1.0)
def fetch_northbound_individual(symbol: str):
    """获取单只股票的北向资金持仓历史（季度数据，数据源: 东方财富 datacenter-web）
    返回 (DataFrame, name) 元组，name 为股票中文名称
    """
    try:
        code = symbol.zfill(6)
        market = "SH" if code.startswith("6") else "SZ"
        secucode = f"{code}.{market}"

        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        all_records = []
        stock_name = ""
        page = 1
        session = resilient_session()
        while True:
            params = {
                "sortColumns": "TRADE_DATE",
                "sortTypes": "-1",
                "pageSize": "500",
                "pageNumber": str(page),
                "reportName": "RPT_MUTUAL_HOLDSTOCKNDATE_STA_NEW",
                "columns": "ALL",
                "source": "WEB",
                "client": "WEB",
                "filter": f'(INTERVAL_TYPE="001")(SECUCODE="{secucode}")',
            }
            r = resilient_get(url, params=params, timeout=30, session=session)
            data = r.json()
            if not data.get("success"):
                break
            result = data["result"]
            if result is None:
                break
            records = result.get("data") or []
            all_records.extend(records)
            if not stock_name and records:
                stock_name = records[0].get("SECURITY_NAME", "")
            if page >= (result.get("pages") or 1):
                break
            page += 1
            time.sleep(random.uniform(0.3, 0.8))

        if not all_records:
            return pd.DataFrame(), ""

        df = pd.DataFrame(all_records)
        result = pd.DataFrame()
        result["date"] = pd.to_datetime(df["TRADE_DATE"])
        result["close"] = pd.to_numeric(df.get("CLOSE_PRICE", 0), errors="coerce")
        result["pct_change"] = pd.to_numeric(df.get("CHANGE_RATE", 0), errors="coerce")
        result["hold_shares"] = pd.to_numeric(df["HOLD_SHARES"], errors="coerce")
        result["hold_value"] = pd.to_numeric(df["HOLD_MARKET_CAP"], errors="coerce")
        result["hold_pct"] = pd.to_numeric(df.get("TOTAL_SHARES_RATIO", df.get("FREE_SHARES_RATIO", 0)), errors="coerce")
        result["free_shares_ratio"] = pd.to_numeric(df.get("FREE_SHARES_RATIO", 0), errors="coerce")
        result["participant_num"] = pd.to_numeric(df.get("PARTICIPANT_NUM", 0), errors="coerce")
        result = result.set_index("date").sort_index()
        result = result.dropna(subset=["hold_shares"])
        return result, stock_name
    except Exception:
        return pd.DataFrame(), ""
