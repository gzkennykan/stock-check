"""
行业板块数据模块：行业分类、行业指数、板块热度分析、资金流向
"""
import pandas as pd
from pathlib import Path
from utils import retry

_CACHE_DIR = Path(__file__).parent.parent / "data_cache"


def fetch_industry_list() -> list[str]:
    """获取所有行业板块名称列表（同花顺分类）"""
    import akshare as ak
    try:
        df = ak.stock_board_industry_name_ths()
        if "name" in df.columns:
            return sorted(df["name"].tolist())
        elif "板块名称" in df.columns:
            return sorted(df["板块名称"].tolist())
        return sorted(df.iloc[:, 0].tolist())
    except Exception as e:
        raise RuntimeError(f"获取行业列表失败: {e}")


@retry(times=2, delay=1.0)
def fetch_industry_index(industry_name: str, end_date: str = "") -> pd.DataFrame:
    """
    获取单个行业板块指数历史数据（同花顺 10jqka）。

    参数:
        industry_name: 行业名称，如 "半导体及元件"
        end_date: 结束日期 YYYYMMDD，默认当天
    """
    import akshare as ak
    from datetime import datetime
    try:
        if not end_date:
            end_date = datetime.now().strftime("%Y%m%d")
        df = ak.stock_board_industry_index_ths(
            symbol=industry_name,
            end_date=end_date,
        )
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date").sort_index()
        elif "日期" in df.columns:
            df["日期"] = pd.to_datetime(df["日期"])
            df = df.set_index("日期").sort_index()
        # 确保有close列
        if "close" not in df.columns:
            for c in df.columns:
                if "收盘" in str(c) or "close" in str(c).lower():
                    df = df.rename(columns={c: "close"})
                    break
        return df
    except Exception:
        return pd.DataFrame()


def fetch_industry_spot() -> pd.DataFrame:
    """获取所有行业板块实时行情（涨跌幅排名）"""
    import akshare as ak
    try:
        df = ak.stock_board_industry_summary_ths()
        return df
    except Exception as e:
        raise RuntimeError(f"获取行业行情失败: {e}")


def fetch_industry_fund_flow() -> pd.DataFrame:
    """
    获取行业资金流向数据（同花顺源）。
    返回 90 个行业的实时资金流入/流出/净额、涨跌幅等。
    """
    import akshare as ak
    try:
        df = ak.stock_fund_flow_industry(symbol="即时")
        return df
    except Exception as e:
        raise RuntimeError(f"获取行业资金流向失败: {e}")


def _get_industry_code(industry_name: str) -> str | None:
    """根据行业名称获取同花顺行业代码"""
    import akshare as ak
    try:
        df = ak.stock_board_industry_name_ths()
        if "name" in df.columns and "code" in df.columns:
            match = df[df["name"] == industry_name]
            if not match.empty:
                return str(match.iloc[0]["code"])
    except Exception:
        pass
    return None


def _get_ths_v_cookie() -> str:
    """生成同花顺 10jqka 反爬 v 值"""
    import py_mini_racer
    from akshare.stock_feature.stock_board_industry_ths import _get_file_content_ths
    js_code = py_mini_racer.MiniRacer()
    js_code.eval(_get_file_content_ths("ths.js"))
    return js_code.call("v")


def _fetch_industry_stocks_page(code: str, page: int, v_cookie: str) -> list[dict]:
    """获取单页行业成分股（10jqka 分页接口）"""
    import requests
    from bs4 import BeautifulSoup

    url = (
        f"https://q.10jqka.com.cn/thshy/detail/board/{code}"
        f"/field/199112/order/desc/page/{page}/ajax/1/code/{code}"
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Cookie": f"v={v_cookie}",
    }
    r = requests.get(url, headers=headers, timeout=15)
    if r.status_code != 200:
        return []
    return _parse_page_rows(BeautifulSoup(r.text, "lxml"))


def fetch_industry_stocks(industry_name: str) -> pd.DataFrame:
    """获取某个行业板块的成分股列表（同花顺 10jqka 实时）"""
    import requests
    from bs4 import BeautifulSoup

    code = _get_industry_code(industry_name)
    if code is None:
        raise RuntimeError(f"未找到行业代码: {industry_name}")

    v_cookie = _get_ths_v_cookie()

    # 请求第1页以获取总页数
    url = (
        f"https://q.10jqka.com.cn/thshy/detail/board/{code}"
        f"/field/199112/order/desc/page/1/ajax/1/code/{code}"
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Cookie": f"v={v_cookie}",
    }
    r = requests.get(url, headers=headers, timeout=15)
    if r.status_code != 200:
        raise RuntimeError(f"请求失败: HTTP {r.status_code}")

    soup = BeautifulSoup(r.text, "lxml")
    pager = soup.find("div", class_="m-pager")
    total_pages = 1
    if pager:
        pages = set()
        for a in pager.find_all("a"):
            p = a.get("page")
            if p and p.isdigit():
                pages.add(int(p))
        if pages:
            total_pages = min(max(pages), 5)  # 最多5页，服务端分页限制

    # 收集所有页数据
    all_rows = []
    for p in range(1, total_pages + 1):
        if p == 1:
            rows = _parse_page_rows(soup)
        else:
            # 每页重新生成 v cookie，避免反爬拦截
            v_cookie = _get_ths_v_cookie()
            rows = _fetch_industry_stocks_page(code, p, v_cookie)
        all_rows.extend(rows)

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)
    for col in ["现价", "涨跌幅(%)", "涨跌", "涨速(%)", "换手(%)", "量比", "振幅(%)", "市盈率"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in ["成交额", "流通股", "流通市值"]:
        if col in df.columns:
            df[col] = df[col].apply(_parse_unit_value)
            df = df.rename(columns={col: f"{col}(亿)"})

    return df


def _parse_unit_value(raw: str) -> float:
    """解析带中文单位的数值字符串 → 亿"""
    import re
    if not isinstance(raw, str):
        return float("nan")
    raw = raw.strip()
    if raw in ("--", "-", "—", ""):
        return float("nan")
    match = re.match(r"([\d.,\-]+)\s*(万亿|亿|万)?", raw)
    if not match:
        return float("nan")
    try:
        val = float(match.group(1).replace(",", ""))
    except ValueError:
        return float("nan")
    unit = match.group(2) or ""
    if unit == "万亿":
        val *= 10000
    elif unit == "万":
        val /= 10000
    return round(val, 4)


def _parse_page_rows(soup) -> list[dict]:
    """从 BeautifulSoup 对象解析表格行"""
    table = soup.find("table", class_="m-table")
    if not table:
        return []
    tbody = table.find("tbody")
    if not tbody:
        return []
    rows = []
    for tr in tbody.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 14:
            continue
        rows.append({
            "序号":     tds[0].get_text(strip=True),
            "代码":     tds[1].get_text(strip=True),
            "名称":     tds[2].get_text(strip=True),
            "现价":     tds[3].get_text(strip=True),
            "涨跌幅(%)": tds[4].get_text(strip=True),
            "涨跌":     tds[5].get_text(strip=True),
            "涨速(%)":  tds[6].get_text(strip=True),
            "换手(%)":  tds[7].get_text(strip=True),
            "量比":     tds[8].get_text(strip=True),
            "振幅(%)":  tds[9].get_text(strip=True),
            "成交额":    tds[10].get_text(strip=True),
            "流通股":    tds[11].get_text(strip=True),
            "流通市值":   tds[12].get_text(strip=True),
            "市盈率":    tds[13].get_text(strip=True),
        })
    return rows


def analyze_industry_rotation() -> pd.DataFrame | None:
    """
    行业轮动分析：基于同花顺行业资金流向实时排名。

    数据来自 10jqka.com.cn 资金流向，覆盖 90 个行业。
    列序固定（即时）：序号 | 行业 | 行业指数 | 涨跌幅 | 流入资金 | 流出资金 | 净额 | 公司家数 | 领涨股 | 领涨股涨幅 | 当前价

    返回 DataFrame，按净额（资金净流入）降序排列。
    """
    try:
        raw = fetch_industry_fund_flow()
        if raw.empty:
            return None

        result = pd.DataFrame()
        # 按固定位置取列（同花顺即时模式下列序稳定，HTML 表头标注单位为亿）
        result["行业"] = raw.iloc[:, 1].astype(str)
        result["涨跌幅(%)"] = pd.to_numeric(raw.iloc[:, 3], errors="coerce")
        result["流入资金(亿)"] = pd.to_numeric(raw.iloc[:, 4], errors="coerce").round(2)
        result["流出资金(亿)"] = pd.to_numeric(raw.iloc[:, 5], errors="coerce").round(2)
        result["净额(亿)"] = pd.to_numeric(raw.iloc[:, 6], errors="coerce").round(2)
        result["领涨股"] = raw.iloc[:, 8].astype(str)
        result["领涨股涨幅(%)"] = pd.to_numeric(raw.iloc[:, 9], errors="coerce")

        # 按净额降序排列
        result = result.sort_values("净额(亿)", ascending=False)
        result = result.reset_index(drop=True)
        result["排名"] = range(1, len(result) + 1)
        return result
    except Exception:
        return None
