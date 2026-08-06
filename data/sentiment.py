"""
新闻舆情分析模块

功能:
  1. 获取个股新闻/公告（东方财富公告 API）
  2. 情绪打分（规则引擎，无需 LLM API）
  3. 近7日情绪趋势
  4. 重大公告自动识别

数据源: 东方财富个股公告 API (np-anotice-stock.eastmoney.com)
"""
import re
from datetime import datetime, timedelta, date
from collections import Counter

import pandas as pd
import numpy as np


# ── 中文情绪词典 ──
_POSITIVE_KEYWORDS = [
    "增长", "大涨", "涨停", "突破", "利好", "盈利", "新高",
    "回购", "增持", "分红", "中标", "签约", "订单", "扩产",
    "超预期", "扭亏", "减亏", "改善", "提升", "强劲", "景气",
    "上升", "反弹", "强势", "连涨", "看好", "推荐", "买入",
    "龙头", "领先", "创新", "突破性", "加速", "放量",
    "合作协议", "技术突破", "产能释放", "业绩预增",
    "获得专利", "政策支持", "战略合作", "重大项目",
]

_NEGATIVE_KEYWORDS = [
    "下跌", "跌停", "大跌", "亏损", "减持", "暴雷", "违约",
    "下滑", "恶化", "下降", "风险", "违规", "处罚", "调查",
    "诉讼", "冻结", "退市", "ST", "停牌", "利空", "负面",
    "下滑", "疲软", "低迷", "破位", "连跌", "卖出", "减持",
    "雷", "踩雷", "暴亏", "巨亏", "预亏", "债务违约",
    "高管离职", "业绩变脸", "资产减值", "商誉减值",
    "被立案", "问询函", "监管函", "股价异动",
]


def _get_sentiment_score(text: str) -> float:
    """
    基于关键词词典计算单条文本的情绪分 [-1, 1]。
    正值=正面，负值=负面。
    """
    if not text or pd.isna(text):
        return 0.0

    text = str(text).lower()
    pos_count = sum(1 for kw in _POSITIVE_KEYWORDS if kw.lower() in text)
    neg_count = sum(1 for kw in _NEGATIVE_KEYWORDS if kw.lower() in text)

    total = pos_count + neg_count
    if total == 0:
        return 0.0

    # 加权：标题关键词权重更高
    raw = (pos_count - neg_count) / max(total, 1)
    return round(max(-1.0, min(1.0, raw * 1.5)), 3)


def _classify_sentiment(score: float) -> str:
    if score > 0.3:
        return "positive"
    elif score < -0.3:
        return "negative"
    else:
        return "neutral"


def _normalize_cached_news(df: pd.DataFrame) -> pd.DataFrame:
    """补齐 DB 缓存行缺失的列，使返回结构与 API 路径一致。

    stock_news 表只持久化 [symbol, pub_date, title, sentiment_score]，
    缺少 sentiment_label / pub_time。直接返回会导致调用方 KeyError。
    """
    if df is None or df.empty:
        return df
    df = df.copy()
    if "pub_time" not in df.columns and "pub_date" in df.columns:
        df["pub_time"] = pd.to_datetime(df["pub_date"], errors="coerce")
    if "sentiment_label" not in df.columns and "sentiment_score" in df.columns:
        df["sentiment_label"] = df["sentiment_score"].apply(_classify_sentiment)
    return df


def fetch_stock_news(symbol: str, max_pages: int = 3) -> pd.DataFrame:
    """
    获取个股新闻/公告（东方财富源）— DB优先，API补充。

    返回:
        DataFrame: title, content, pub_time, sentiment_score, sentiment_label

    注意: 使用东方财富个股公告 API（np-anotice-stock），
    避开搜索 API 结果不稳定和 AKShare 的 pandas/pyarrow 正则兼容问题。
    周末自动使用 DB 缓存（最近 3 天）避免无数据。
    """
    from data.database import get_stock_news_db, insert_stock_news

    # 周末/节假日：放宽 DB 缓存窗口（最近3天），覆盖周五的数据
    is_weekend = date.today().weekday() >= 5
    db_cache_days = 3 if is_weekend else 1

    # 1) DB 优先
    try:
        cached = get_stock_news_db(symbol, n_days=db_cache_days)
        if not cached.empty:
            return _normalize_cached_news(cached)
    except Exception:
        pass

    # 2) 直接调用东方财富个股公告 API
    try:
        df = _fetch_announcements(symbol)
        if df is None or df.empty:
            # 周末回退：查 DB 最近 30 天的缓存
            try:
                return _normalize_cached_news(get_stock_news_db(symbol, n_days=30))
            except Exception:
                return pd.DataFrame()
    except Exception:
        try:
            return _normalize_cached_news(get_stock_news_db(symbol, n_days=30))
        except Exception:
            return pd.DataFrame()

    # 情绪打分
    df["sentiment_score"] = df["title"].apply(_get_sentiment_score)
    df["sentiment_label"] = df["sentiment_score"].apply(_classify_sentiment)

    if "pub_time" in df.columns:
        df = df.sort_values("pub_time", ascending=False)

    if len(df) > max_pages * 50:
        df = df.head(max_pages * 50)

    # 3) 写入 DB（下次周末可直接用缓存）
    try:
        db_df = df.copy()
        db_df["symbol"] = symbol
        if "pub_time" in db_df.columns:
            db_df["pub_date"] = pd.to_datetime(db_df["pub_time"], errors="coerce").dt.date
        insert_stock_news(db_df[["symbol", "pub_date", "title", "sentiment_score"]])
    except Exception:
        pass

    return df


def _fetch_announcements(symbol: str) -> pd.DataFrame | None:
    """
    从东方财富个股公告 API 获取公告列表。
    兼容 pandas 3.0+ / pyarrow 24.x（不使用 str.replace with regex）。
    """
    import requests as _requests

    clean_symbol = symbol.strip().zfill(6)

    # 先判断市场前缀
    if clean_symbol.startswith(("6", "5", "9")):
        market_code = "1"    # 沪市
    elif clean_symbol.startswith(("0", "3", "2")):
        market_code = "0"    # 深市
    else:
        market_code = "0"

    url = "https://np-anotice-stock.eastmoney.com/api/security/ann"
    params = {
        "sr": -1,
        "page_size": 50,
        "page_index": 1,
        "ann_type": "A",
        "client_source": "web",
        "stock_list": f"{clean_symbol},{market_code}",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://data.eastmoney.com/",
    }

    r = _requests.get(url, params=params, headers=headers, timeout=15)
    if r.status_code != 200:
        return None

    data = r.json()
    items = data.get("data", {}).get("list", [])
    if not items:
        return None

    rows = []
    for item in items:
        title = item.get("title_ch", "") or item.get("title", "")
        # 拼接栏目名作为补充上下文
        columns = item.get("columns", [])
        col_name = columns[0].get("column_name", "") if columns else ""
        content = f"[{col_name}] {title}" if col_name else title

        rows.append({
            "title": title,
            "content": content,
            "pub_time": item.get("notice_date", ""),
            "art_code": item.get("art_code", ""),
        })

    df = pd.DataFrame(rows)
    if "pub_time" in df.columns:
        df["pub_time"] = pd.to_datetime(df["pub_time"], errors="coerce")

    return df


def get_sentiment_summary(symbol: str, days: int = 7) -> dict:
    """
    获取个股近期情绪摘要。

    返回:
        {
            "total_news": int,
            "positive_count": int, "neutral_count": int, "negative_count": int,
            "avg_score": float,           # 平均情绪分
            "sentiment_trend": str,       # "improving" / "deteriorating" / "stable"
            "daily_scores": [{date, avg_score, count}, ...],
            "top_positive": [title, ...],  # 最正面3条
            "top_negative": [title, ...],  # 最负面3条
            "key_events": [title, ...],    # 重大事件（评分极端或含关键词）
        }
    """
    news = fetch_stock_news(symbol)
    if news.empty:
        return {"total_news": 0, "error": "无新闻数据"}

    # 时间过滤
    if "pub_time" in news.columns:
        cutoff = datetime.now() - timedelta(days=days)
        news = news[news["pub_time"] >= cutoff]

    if news.empty:
        return {"total_news": 0, "error": f"近{days}日无新闻"}

    total = len(news)
    pos = int((news["sentiment_label"] == "positive").sum())
    neg = int((news["sentiment_label"] == "negative").sum())
    neu = total - pos - neg
    avg_score = round(float(news["sentiment_score"].mean()), 3) if total > 0 else 0.0

    # 趋势判断
    if "pub_time" in news.columns:
        daily = []
        news["日期"] = news["pub_time"].dt.date
        for d, grp in news.groupby("日期"):
            daily.append({
                "date": str(d),
                "avg_score": round(float(grp["sentiment_score"].mean()), 3),
                "count": len(grp),
            })
        daily.sort(key=lambda x: x["date"])

        # 趋势：比较前后3天
        if len(daily) >= 4:
            first_half = [x["avg_score"] for x in daily[:len(daily)//2]]
            second_half = [x["avg_score"] for x in daily[len(daily)//2:]]
            first_avg = sum(first_half) / len(first_half) if first_half else 0
            second_avg = sum(second_half) / len(second_half) if second_half else 0
            if second_avg - first_avg > 0.1:
                trend = "improving"
            elif second_avg - first_avg < -0.1:
                trend = "deteriorating"
            else:
                trend = "stable"
        else:
            trend = "stable" if len(daily) <= 1 else "stable"
    else:
        daily = []
        trend = "stable"

    # 最正面/最负面
    sorted_news = news.sort_values("sentiment_score")
    top_neg = sorted_news.head(3)["title"].tolist() if neg > 0 else []
    top_pos = sorted_news.tail(3)["title"].tolist()[::-1] if pos > 0 else []

    # 重大事件识别
    event_keywords = ["公告", "重组", "收购", "增发", "分红", "立案", "ST",
                      "退市", "停牌", "问询", "监管", "诉讼", "中标", "签约",
                      "业绩预告", "业绩快报", "股东", "减持", "增持", "回购"]
    key_events = []
    for _, row in news.iterrows():
        title = str(row.get("title", ""))
        if any(kw in title for kw in event_keywords):
            key_events.append(title)
    key_events = key_events[:10]

    return {
        "total_news": total,
        "positive_count": pos,
        "neutral_count": neu,
        "negative_count": neg,
        "avg_score": avg_score,
        "sentiment_trend": trend,
        "daily_scores": daily,
        "top_positive": top_pos,
        "top_negative": top_neg,
        "key_events": key_events,
    }
