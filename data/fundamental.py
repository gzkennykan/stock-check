"""
财务数据模块：基本面指标获取（ROE、营收增速、毛利率、负债率等）
数据源: 新浪财经 stock_financial_abstract（覆盖银行/非银全行业）
"""
import pandas as pd
from pathlib import Path

_CACHE_DIR = Path(__file__).parent.parent / "data_cache"


# 新浪财经指标名 → 内部字段名
INDICATOR_MAP = {
    "净资产收益率(ROE)": "roe",
    "总资产报酬率(ROA)": "roa",
    "毛利率": "gross_margin",
    "销售净利率": "net_margin",
    "营业总收入增长率": "revenue_yoy",
    "归属母公司净利润增长率": "profit_yoy",
    "资产负债率": "debt_ratio",
    "流动比率": "current_ratio",
    "速动比率": "quick_ratio",
    "基本每股收益": "eps",
    "每股净资产": "bps",
    "营业总收入": "total_revenue",
    "净利润": "net_profit",
    "经营现金流量净额": "operating_cf",
}


def _parse_sina_abstract(df: pd.DataFrame, symbol: str) -> dict | None:
    """解析新浪财经 stock_financial_abstract 返回的宽表"""
    try:
        result = {"symbol": symbol}

        # 日期列：第3列往后都是报告期（YYYYMMDD 格式），已排序
        date_cols = [c for c in df.columns[2:] if str(c).isdigit() and len(str(c)) == 8]
        if not date_cols:
            return None

        # 构建指标查找表：{(指标名, 选项): {日期: 值}}
        indicator_data = {}
        for _, row in df.iterrows():
            category = str(row.iloc[0])
            indicator = str(row.iloc[1])
            key = indicator
            for dc in date_cols:
                val = row[dc]
                try:
                    v = float(val) if pd.notna(val) else None
                except (ValueError, TypeError):
                    v = None
                if v is not None:
                    indicator_data.setdefault(key, {})[dc] = v

        # 按日期从新到旧取每个指标最近一个非NaN值
        for indicator, en_name in INDICATOR_MAP.items():
            if indicator not in indicator_data:
                continue
            dates_sorted = sorted(indicator_data[indicator].keys(), reverse=True)
            for dc in dates_sorted:
                v = indicator_data[indicator][dc]
                if v is not None:
                    result[en_name] = v
                    break

        # 规模指标（元）需要换算：新浪返回的是"元"，数值可能已经是绝对数
        # 营业总收入、净利润、经营现金流 —— 新浪返回单位为元
        for key in ["total_revenue", "net_profit", "operating_cf"]:
            if key in result:
                result[key] = float(result[key])

        return result
    except Exception:
        return None


def fetch_financial_indicators(symbol: str) -> dict | None:
    """
    获取单只股票的最新财务指标（新浪财经数据源）。
    遍历报告期从新到旧，取每个指标最近一个非NaN值。
    银行/非银全行业覆盖，无数据缺失问题。
    """
    import akshare as ak
    try:
        df = ak.stock_financial_abstract(symbol=symbol)
        if df.empty or df.shape[1] < 3:
            return None

        result = _parse_sina_abstract(df, symbol)
        if result is None:
            return None

        # 股票名称
        try:
            from data.screener import get_stock_list
            stocks = get_stock_list()
            match = stocks[stocks["code"] == symbol]
            if not match.empty:
                result["name"] = str(match.iloc[0]["name"])
        except Exception:
            pass

        return result
    except Exception:
        return None


def fetch_multi_financials(symbols: list[str]) -> pd.DataFrame:
    """
    批量获取多只股票的财务指标，返回 DataFrame。
    """
    rows = []
    for sym in symbols:
        data = fetch_financial_indicators(sym)
        if data:
            rows.append(data)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def fetch_performance_forecast(report_date: str = None) -> pd.DataFrame:
    """
    获取 A 股业绩预告数据（东方财富 datacenter 源，缓存兜底）。

    参数:
        report_date: 报告期，如 "2024-12-31"，默认最新
    """
    import time as _time
    import random as _random
    from datetime import datetime
    from utils import resilient_get, resilient_session
    try:
        if report_date is None:
            now = datetime.now()
            y = now.year
            m = now.month
            q = ((m - 1) // 3)
            y = y - 1 if q == 0 else y
            q = 4 if q == 0 else q
            month = q * 3
            day = 31 if month in (3, 12) else 30
            report_date = f"{y}-{month:02d}-{day:02d}"

        url = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
        all_records = []
        page = 1
        session = resilient_session()
        while True:
            params = {
                "sortColumns": "NOTICE_DATE,SECURITY_CODE",
                "sortTypes": "-1,-1",
                "pageSize": "200",
                "pageNumber": str(page),
                "reportName": "RPT_PUBLIC_OP_NEWPREDICT",
                "columns": "ALL",
                "filter": f"(REPORT_DATE='{report_date}')",
            }
            r = resilient_get(url, params=params, timeout=60, session=session)
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
            _time.sleep(_random.uniform(0.3, 0.8))

        if not all_records:
            return _load_forecast_cache()

        df = pd.DataFrame(all_records)
        result = pd.DataFrame()
        result["股票代码"] = df["SECURITY_CODE"].astype(str)
        result["股票简称"] = df["SECURITY_NAME_ABBR"].astype(str)
        result["公告日期"] = pd.to_datetime(df["NOTICE_DATE"]).dt.date
        result["报告期"] = pd.to_datetime(df["REPORT_DATE"]).dt.date
        result["预测指标"] = df["PREDICT_FINANCE"].astype(str)
        result["业绩变动"] = df["PREDICT_TYPE"].astype(str)
        result["业绩变动幅度(%)"] = pd.to_numeric(df.get("PREDICT_RATIO_LOWER", 0), errors="coerce")
        result["预测净利润下限"] = pd.to_numeric(df.get("PREDICT_AMT_LOWER", 0), errors="coerce")
        result["预测净利润上限"] = pd.to_numeric(df.get("PREDICT_AMT_UPPER", 0), errors="coerce")
        result["上年同期值"] = pd.to_numeric(df.get("PREYEAR_SAME_PERIOD", 0), errors="coerce")
        result["业绩变动原因"] = df.get("CHANGE_REASON_EXPLAIN", "")

        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        result.to_csv(_CACHE_DIR / "forecast_cache.csv", index=False)
        return result
    except Exception:
        return _load_forecast_cache()


def _load_forecast_cache() -> pd.DataFrame:
    """加载业绩预告缓存数据"""
    cache_file = _CACHE_DIR / "forecast_cache.csv"
    if cache_file.exists():
        return pd.read_csv(cache_file)
    return pd.DataFrame()
