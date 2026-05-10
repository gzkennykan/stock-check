"""
A股选股筛选器：从 Sina 源获取全市场行情，按条件过滤
"""
import pandas as pd
from datetime import datetime
from pathlib import Path

_CACHE_DIR = Path(__file__).parent.parent / "data_cache"
_CACHE_FILE = _CACHE_DIR / "_screener_cache.csv"
_CACHE_TTL_MINUTES = 15  # 缓存15分钟，避免频繁请求

_INDUSTRY_CACHE_FILE = _CACHE_DIR / "_industry_mapping.csv"
_INDUSTRY_TTL_HOURS = 24  # 行业分类不常变，缓存1天


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
                result = result[result["code"].isin(allowed)]
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
