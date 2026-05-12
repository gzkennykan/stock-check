"""
A股选股筛选器：从 Sina 源获取全市场行情，按条件过滤
"""
import re
import pandas as pd
from datetime import datetime
from pathlib import Path
from io import StringIO

_CACHE_DIR = Path(__file__).parent.parent / "data_cache"
_CACHE_FILE = _CACHE_DIR / "_screener_cache.csv"
_CACHE_TTL_MINUTES = 15  # 缓存15分钟，避免频繁请求

_INDUSTRY_CACHE_FILE = _CACHE_DIR / "_industry_mapping.csv"
_INDUSTRY_TTL_HOURS = 24  # 行业分类不常变，缓存1天

_FUND_FLOW_CACHE_FILE = _CACHE_DIR / "_fund_flow_cache.csv"
_FUND_FLOW_TTL_MINUTES = 15


def _fetch_spot_data() -> pd.DataFrame:
    """从 AKShare (Sina 源) 获取全 A 股实时行情"""
    import akshare as ak
    raw = ak.stock_zh_a_spot()
    df = raw.copy()
    # Sina 源返回的中文列名
    df = df.rename(columns={
        "代码": "code", "名称": "name",
        "最新价": "price", "涨跌额": "change", "涨跌幅": "pct_change",
        "昨收": "prev_close", "今开": "open", "最高": "high", "最低": "low",
        "成交量": "volume", "成交额": "turnover",
    })
    cols = ["code", "name", "price", "pct_change", "change", "open", "high",
            "low", "prev_close", "volume", "turnover"]
    df = df[[c for c in cols if c in df.columns]]
    return df


def _is_cache_fresh() -> bool:
    if not _CACHE_FILE.exists():
        return False
    mtime = datetime.fromtimestamp(_CACHE_FILE.stat().st_mtime)
    return (datetime.now() - mtime).total_seconds() < _CACHE_TTL_MINUTES * 60


def get_stock_list(force_refresh: bool = False) -> pd.DataFrame:
    """获取 A 股全市场行情 DataFrame，自动缓存"""
    if not force_refresh and _is_cache_fresh():
        df = pd.read_csv(_CACHE_FILE, dtype={"code": str})
        return df

    df = _fetch_spot_data()
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(_CACHE_FILE, index=False)
    return df


# 申万行业分类代码 → 名称映射（一级行业，前2位代码）
_SW_INDUSTRY_MAP = {
    "11": "农林牧渔",
    "21": "采掘",
    "22": "基础化工",
    "23": "钢铁",
    "24": "有色金属",
    "25": "建筑材料",
    "26": "建筑装饰",
    "27": "电子",
    "28": "汽车",
    "31": "电力设备",
    "32": "计算机",
    "33": "家用电器",
    "34": "食品饮料",
    "35": "纺织服饰",
    "36": "轻工制造",
    "37": "医药生物",
    "41": "公用事业",
    "42": "交通运输",
    "43": "房地产",
    "45": "商贸零售",
    "46": "社会服务",
    "47": "银行",
    "48": "非银金融",
    "49": "综合",
    "51": "传媒",
    "61": "通信",
    "62": "机械设备",
    "63": "电力设备",
    "64": "建筑装饰",
    "65": "国防军工",
    "71": "计算机",
    "72": "传媒",
    "73": "通信",
    "74": "煤炭",
    "75": "石油石化",
    "76": "环保",
    "77": "美容护理",
}

# 二级/三级 细分行业代码 → 名称（满足用户关注的细分板块）
_SW_SUB_INDUSTRY_MAP = {
    "2701": "半导体",
    "2702": "元件",
    "2703": "光学光电子",
    "2704": "其他电子",
    "2705": "消费电子",
    "2706": "电子化学品",
    "3404": "白酒",
    "3405": "食品加工",
    "3406": "饮料乳品",
    "3407": "调味发酵品",
    "3408": "休闲食品",
    "3501": "服装家纺",
    "3502": "饰品",
    "3503": "纺织制造",
    "3601": "造纸",
    "3602": "包装印刷",
    "3603": "家居用品",
    "3604": "文娱用品",
    "3701": "化学制药",
    "3702": "中药",
    "3703": "生物制品",
    "3704": "医疗器械",
    "3705": "医药商业",
    "3706": "医疗服务",
    "4301": "房地产开发",
    "4302": "房地产服务",
    "4501": "一般零售",
    "4502": "专业连锁",
    "4503": "互联网电商",
    "4504": "贸易",
    "4601": "旅游及景区",
    "4602": "酒店餐饮",
    "4603": "教育",
    "4604": "体育",
    "4605": "专业服务",
    "4606": "会展服务",
    "4701": "国有大型银行",
    "4702": "股份制银行",
    "4703": "城商行",
    "4704": "农商行",
    "4801": "证券",
    "4802": "保险",
    "4803": "多元金融",
    "4804": "金融控股",
    "4901": "综合",
    "6501": "航天装备",
    "6502": "航空装备",
    "6503": "地面兵装",
    "6504": "航海装备",
    "6505": "军工电子",
    "6506": "军工材料",
    "2801": "乘用车",
    "2802": "商用车",
    "2803": "汽车零部件",
    "2804": "汽车服务",
    "2805": "摩托车及其他",
    "3301": "白色家电",
    "3302": "黑色家电",
    "3303": "小家电",
    "3304": "家电零部件",
    "2401": "贵金属",
    "2402": "工业金属",
    "2403": "小金属",
    "2404": "能源金属",
    "2201": "化学原料",
    "2202": "化学制品",
    "2203": "化学纤维",
    "2204": "塑料",
    "2205": "橡胶",
    "2206": "农化制品",
    "2207": "非金属材料",
}


def _map_sw_code_to_names(code: str) -> list[str]:
    """将申万6位行业代码转为行业名称列表 [一级名称, 二级名称(如有)]"""
    names = []
    cat1 = code[:2]
    cat2 = code[:4]
    if cat1 in _SW_INDUSTRY_MAP:
        names.append(_SW_INDUSTRY_MAP[cat1])
    if cat2 in _SW_SUB_INDUSTRY_MAP:
        names.append(_SW_SUB_INDUSTRY_MAP[cat2])
    # 三级代码兜底：若一二级均未命中，直接用6位代码作为名称
    if not names:
        names.append(code)
    return names


def _build_industry_mapping() -> dict:
    """从申万行业分类构建 股票代码→行业名称列表 映射（取每只股票最新分类）"""
    try:
        import akshare as ak
        df = ak.stock_industry_clf_hist_sw()
    except Exception:
        return {}

    if df.empty:
        return {}

    # 每只股票取最新的一条分类记录
    latest = df.sort_values("update_time").groupby("symbol").last().reset_index()

    code_to_industry: dict[str, list[str]] = {}
    for _, row in latest.iterrows():
        symbol = row["symbol"]
        sw_code = row["industry_code"]
        names = _map_sw_code_to_names(sw_code)
        code_to_industry[symbol] = names

    return code_to_industry


def _load_industry_mapping() -> dict:
    """加载行业映射（24小时缓存，首次自动构建）"""
    if _INDUSTRY_CACHE_FILE.exists():
        age_sec = (datetime.now() - datetime.fromtimestamp(
            _INDUSTRY_CACHE_FILE.stat().st_mtime)).total_seconds()
        if age_sec < _INDUSTRY_TTL_HOURS * 3600:
            mapping: dict[str, list[str]] = {}
            df = pd.read_csv(_INDUSTRY_CACHE_FILE, dtype={"code": str, "industry": str})
            for _, row in df.iterrows():
                mapping.setdefault(row["code"], []).append(row["industry"])
            return mapping

    mapping = _build_industry_mapping()
    if mapping:
        rows = [{"code": c, "industry": i}
                for c, inds in mapping.items() for i in inds]
        pd.DataFrame(rows).to_csv(_INDUSTRY_CACHE_FILE, index=False)
    return mapping


def get_industry_list() -> list[str]:
    """返回所有可用的行业板块名称（按拼音排序）"""
    try:
        mapping = _load_industry_mapping()
        industries = sorted({i for inds in mapping.values() for i in inds})
        return industries
    except Exception:
        return []


def screen_stocks(df: pd.DataFrame,
                  price_min: float | None = None,
                  price_max: float | None = None,
                  pct_min: float | None = None,
                  pct_max: float | None = None,
                  vol_min: float | None = None,
                  vol_max: float | None = None,
                  turnover_min: float | None = None,
                  turnover_max: float | None = None,
                  keyword: str = "",
                  market: str = "全部",
                  industries: list[str] | None = None) -> pd.DataFrame:
    """按多个条件筛选股票"""
    result = df.copy()

    if market == "上海":
        result = result[result["code"].str.startswith("6")]
    elif market == "深圳":
        result = result[result["code"].str.startswith(("0", "3"))]
    elif market == "北交所":
        result = result[result["code"].str.startswith(("8", "4", "9"))]

    if industries:
        try:
            mapping = _load_industry_mapping()
            allowed = set()
            for code, ind_list in mapping.items():
                if any(ind in industries for ind in ind_list):
                    allowed.add(code)
            if allowed:
                # 行情数据代码带 sh/sz/bj 前缀，行业映射为纯6位代码，需要统一
                result = result[
                    result["code"].str.replace(r"^(sh|sz|bj)", "", regex=True).isin(allowed)
                ]
        except Exception:
            pass

    if price_min is not None:
        result = result[result["price"] >= price_min]
    if price_max is not None:
        result = result[result["price"] <= price_max]

    if pct_min is not None:
        result = result[result["pct_change"] >= pct_min]
    if pct_max is not None:
        result = result[result["pct_change"] <= pct_max]

    if vol_min is not None:
        result = result[result["volume"] >= vol_min]
    if vol_max is not None:
        result = result[result["volume"] <= vol_max]

    if turnover_min is not None:
        result = result[result["turnover"] >= turnover_min]
    if turnover_max is not None:
        result = result[result["turnover"] <= turnover_max]

    if keyword:
        kw = keyword.lower()
        mask = result["code"].str.contains(kw) | result["name"].str.lower().str.contains(kw)
        result = result[mask]

    return result.reset_index(drop=True)


# ════════════════ 资金流向 & 成交额排行 ════════════════

def _parse_cn_money(val: str) -> float:
    """解析带中文单位的金额字符串，如 '18.47亿' → 1847000000, '1.27万' → 12700"""
    if isinstance(val, (int, float)):
        return float(val)
    val = str(val).strip()
    if not val:
        return 0.0
    num_str = val.rstrip("亿万千百")
    unit = val[len(num_str):]
    try:
        num = float(num_str)
    except ValueError:
        return 0.0
    if "亿" in unit:
        num *= 100_000_000
    elif "万" in unit:
        num *= 10_000
    return num


def _fetch_fund_flow_page(v_code: str, page: int) -> pd.DataFrame:
    """获取单页同花顺个股资金流向数据"""
    import requests
    url = f"http://data.10jqka.com.cn/funds/ggzjl/field/zdf/order/desc/page/{page}/ajax/1/free/1/"
    headers = {
        "Accept": "text/html, */*; q=0.01",
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "hexin-v": v_code,
        "Referer": "http://data.10jqka.com.cn/funds/hyzjl/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "X-Requested-With": "XMLHttpRequest",
    }
    r = requests.get(url, headers=headers, timeout=15)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    return pd.read_html(StringIO(r.text))[0]


_V_CODE_MINIRACER = None
_JS_CONTENT = None


def _get_v_code() -> str:
    """生成同花顺接口所需的 hexin-v 验证码（复用 MiniRacer 实例）"""
    global _V_CODE_MINIRACER, _JS_CONTENT
    import py_mini_racer
    import akshare.stock_feature.stock_fund_flow as ths_mod
    if _V_CODE_MINIRACER is None:
        _V_CODE_MINIRACER = py_mini_racer.MiniRacer()
        _JS_CONTENT = ths_mod._get_file_content_ths("ths.js")
        _V_CODE_MINIRACER.eval(_JS_CONTENT)
    return _V_CODE_MINIRACER.call("v")


def _fetch_all_fund_flow() -> pd.DataFrame:
    """从同花顺获取全部个股资金流向数据，104页约5200只股票"""
    import requests
    from bs4 import BeautifulSoup

    v_code = _get_v_code()
    headers = {
        "Accept": "text/html, */*; q=0.01",
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "hexin-v": v_code,
        "Referer": "http://data.10jqka.com.cn/funds/hyzjl/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "X-Requested-With": "XMLHttpRequest",
    }
    # 获取第一页（同时取得总页数）
    url = "http://data.10jqka.com.cn/funds/ggzjl/field/zdf/order/desc/page/1/ajax/1/free/1/"
    r = requests.get(url, headers=headers, timeout=15)
    if r.status_code != 200:
        raise RuntimeError(f"获取资金流向失败: HTTP {r.status_code}")

    soup = BeautifulSoup(r.text, "lxml")
    page_info = soup.find("span", class_="page_info")
    total_pages = int(page_info.text.split("/")[1]) if page_info else 104
    all_pages = [pd.read_html(StringIO(r.text))[0]]

    # 获取剩余页
    for page in range(2, total_pages + 1):
        v_code = _get_v_code()
        headers["hexin-v"] = v_code
        try:
            r = requests.get(url.replace("/page/1/", f"/page/{page}/"), headers=headers, timeout=15)
            if r.status_code == 200:
                all_pages.append(pd.read_html(StringIO(r.text))[0])
        except Exception:
            continue

    df = pd.concat(all_pages, ignore_index=True)
    # 列名: 序号, 股票代码, 股票名称, 最新价, 涨跌幅, 净流量, 主力资金(元), 游资(元), 散户(元), 成交量(元)
    df.columns = ["rank", "code", "name", "price", "pct_change_str",
                   "net_flow_pct", "main_capital", "hot_money",
                   "retail_money", "volume_str"]
    df = df.drop(columns=["rank"])

    # 清洗数值列
    for col in ["price", "pct_change_str", "net_flow_pct"]:
        df[col] = pd.to_numeric(
            df[col].astype(str).str.replace("%", "", regex=False), errors="coerce"
        )
    df["pct_change"] = df["pct_change_str"]
    for money_col in ["main_capital", "hot_money", "retail_money"]:
        df[money_col] = df[money_col].apply(_parse_cn_money)
    df["code"] = df["code"].astype(str).str.strip()
    df = df.drop(columns=["pct_change_str", "volume_str"])

    return df


def _is_fund_flow_cache_fresh() -> bool:
    if not _FUND_FLOW_CACHE_FILE.exists():
        return False
    mtime = datetime.fromtimestamp(_FUND_FLOW_CACHE_FILE.stat().st_mtime)
    return (datetime.now() - mtime).total_seconds() < _FUND_FLOW_TTL_MINUTES * 60


def get_fund_flow_data(force_refresh: bool = False) -> pd.DataFrame:
    """获取全市场资金流向数据，自动缓存"""
    if not force_refresh and _is_fund_flow_cache_fresh():
        return pd.read_csv(_FUND_FLOW_CACHE_FILE, dtype={"code": str})

    df = _fetch_all_fund_flow()
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(_FUND_FLOW_CACHE_FILE, index=False)
    return df


def get_top_capital_inflow(n: int = 50) -> pd.DataFrame:
    """资金净流入（主力资金）最多的 N 只个股"""
    df = get_fund_flow_data()
    top = df.nlargest(n, "main_capital")
    return top[["code", "name", "price", "pct_change", "main_capital"]].reset_index(drop=True)


def get_top_capital_outflow(n: int = 50) -> pd.DataFrame:
    """资金净流出（主力资金卖出）最多的 N 只个股"""
    df = get_fund_flow_data()
    top = df.nsmallest(n, "main_capital")
    return top[["code", "name", "price", "pct_change", "main_capital"]].reset_index(drop=True)


def get_top_turnover(n: int = 50) -> pd.DataFrame:
    """成交额最多的 N 只个股（基于实时行情数据）"""
    df = get_stock_list()
    top = df.nlargest(n, "turnover")
    return top[["code", "name", "price", "pct_change", "turnover"]].reset_index(drop=True)


# ════════════════ 智能选股：多维度数据合并 ════════════════

_COMBINED_CACHE_FILE = _CACHE_DIR / "_combined_cache.csv"
_COMBINED_TTL_MINUTES = 15


def get_combined_data(force_refresh: bool = False) -> pd.DataFrame:
    """
    合并多维度数据：行情(新浪) + 资金流(同花顺) + 行业(申万)
    返回包含所有维度的宽表 DataFrame
    """
    # 检查缓存：需同时满足 TTL 且依赖的源缓存不超过它
    if not force_refresh and _COMBINED_CACHE_FILE.exists():
        age_sec = (datetime.now() - datetime.fromtimestamp(
            _COMBINED_CACHE_FILE.stat().st_mtime)).total_seconds()
        if age_sec < _COMBINED_TTL_MINUTES * 60:
            # 确认源数据缓存不新于合并缓存（防止源数据已刷新但合并缓存是旧的）
            combined_mtime = datetime.fromtimestamp(_COMBINED_CACHE_FILE.stat().st_mtime)
            sources_ok = True
            if _FUND_FLOW_CACHE_FILE.exists():
                ff_mtime = datetime.fromtimestamp(_FUND_FLOW_CACHE_FILE.stat().st_mtime)
                if ff_mtime > combined_mtime:
                    sources_ok = False
            if _CACHE_FILE.exists():
                spot_mtime = datetime.fromtimestamp(_CACHE_FILE.stat().st_mtime)
                if spot_mtime > combined_mtime:
                    sources_ok = False
            if sources_ok:
                return pd.read_csv(_COMBINED_CACHE_FILE, dtype={"code": str, "industry": str})

    # 1. 行情数据
    spot = get_stock_list()
    # 统一代码格式：去掉 sh/sz/bj 前缀
    spot["code_raw"] = spot["code"]
    spot["code"] = spot["code"].str.replace(r"^(sh|sz|bj)", "", regex=True)

    # 2. 资金流数据
    try:
        flow = get_fund_flow_data()
        flow_cols = [c for c in ["code", "main_capital", "hot_money",
                                  "retail_money", "net_flow_pct"] if c in flow.columns]
        flow = flow[flow_cols]
    except Exception:
        flow = pd.DataFrame(columns=["code"])

    # 3. 行业分类
    try:
        mapping = _load_industry_mapping()
        ind_rows = [{"code": c, "industry": ", ".join(inds)}
                    for c, inds in mapping.items()]
        industry_df = pd.DataFrame(ind_rows)
    except Exception:
        industry_df = pd.DataFrame(columns=["code", "industry"])

    # 合并
    merged = spot.merge(flow, on="code", how="left")
    merged = merged.merge(industry_df, on="code", how="left")
    merged["industry"] = merged["industry"].fillna("")

    # 填充缺失的资金流数据
    for col in ["main_capital", "hot_money", "retail_money", "net_flow_pct"]:
        if col in merged.columns:
            merged[col] = merged[col].fillna(0)
        else:
            merged[col] = 0

    # 计算一些衍生指标
    if "market_cap" not in merged.columns:
        merged["market_cap"] = 0  # placeholder

    # 按上海→深圳→北交所排序，主力资金数据对上海/深圳覆盖更全
    merged["_market_order"] = merged["code"].apply(
        lambda c: 0 if c[:1] == "6" else (1 if c[:1] in "03" else 2)
    )
    merged = merged.sort_values(["_market_order", "code"]).drop(columns=["_market_order"])

    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    merged.to_csv(_COMBINED_CACHE_FILE, index=False)
    return merged


def smart_screen(
    df: pd.DataFrame | None = None,
    *,
    # 行情维度
    price_min: float | None = None,
    price_max: float | None = None,
    pct_change_min: float | None = None,
    pct_change_max: float | None = None,
    volume_min: float | None = None,
    turnover_min: float | None = None,
    market: str = "全部",
    # 资金维度
    main_capital_min: float | None = None,
    main_capital_max: float | None = None,
    hot_money_min: float | None = None,
    net_flow_pct_min: float | None = None,
    net_flow_pct_max: float | None = None,
    # 行业维度
    industries: list[str] | None = None,
    # 搜索
    keyword: str = "",
    # 排序
    sort_by: str = "",
    ascending: bool = False,
    top_n: int | None = None,
) -> pd.DataFrame:
    """
    智能多维度选股

    参数:
        sort_by: 排序字段 (code, price, pct_change, volume, turnover,
                  main_capital, hot_money, net_flow_pct)
        top_n: 取前 N 只，None 返回全部
    """
    if df is None:
        df = get_combined_data()
    result = df.copy()

    # 行情筛选
    if market == "上海":
        result = result[result["code"].str.startswith("6")]
    elif market == "深圳":
        result = result[result["code"].str.startswith(("0", "3"))]
    elif market == "北交所":
        result = result[result["code"].str.startswith(("8", "4", "9"))]

    if price_min is not None:
        result = result[result["price"] >= price_min]
    if price_max is not None:
        result = result[result["price"] <= price_max]
    if pct_change_min is not None:
        result = result[result["pct_change"] >= pct_change_min]
    if pct_change_max is not None:
        result = result[result["pct_change"] <= pct_change_max]
    if volume_min is not None:
        result = result[result["volume"] >= volume_min]
    if turnover_min is not None:
        result = result[result["turnover"] >= turnover_min]

    # 资金流筛选
    if "main_capital" in result.columns:
        if main_capital_min is not None:
            result = result[result["main_capital"] >= main_capital_min]
        if main_capital_max is not None:
            result = result[result["main_capital"] <= main_capital_max]
    if "hot_money" in result.columns and hot_money_min is not None:
        result = result[result["hot_money"] >= hot_money_min]
    if "net_flow_pct" in result.columns:
        if net_flow_pct_min is not None:
            result = result[result["net_flow_pct"] >= net_flow_pct_min]
        if net_flow_pct_max is not None:
            result = result[result["net_flow_pct"] <= net_flow_pct_max]

    # 行业筛选
    if industries:
        result = result[
            result["industry"].apply(
                lambda s: any(ind in str(s).split(", ") for ind in industries)
            )
        ]

    # 关键词搜索
    if keyword:
        kw = keyword.lower()
        mask = result["code"].astype(str).str.contains(kw) | \
               result["name"].astype(str).str.lower().str.contains(kw)
        result = result[mask]

    # 排序
    sort_cols = [
        "price", "pct_change", "volume", "turnover",
        "main_capital", "hot_money", "net_flow_pct",
    ]
    if sort_by and sort_by in sort_cols and sort_by in result.columns:
        result = result.sort_values(sort_by, ascending=ascending)

    # 取前N
    if top_n is not None and top_n > 0:
        result = result.head(top_n)

    return result.reset_index(drop=True)
