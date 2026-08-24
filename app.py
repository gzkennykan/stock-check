"""
WinnerK股票查询系统 — Streamlit 可视化界面
运行: streamlit run app.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st

from strategies import MACrossStrategy, MACDStrategy, RSIStrategy
from strategies import BollingerStrategy, TripleMAStrategy, KDJStrategy
from strategies import DonchianStrategy, ATRStrategy

st.set_page_config(page_title="WinnerK股票查询系统", page_icon="📈", layout="wide")

from ui.theme import apply_global_css
apply_global_css()


def _is_lock_error(msg: str) -> bool:
    """判断是否为 DuckDB 文件锁被占用的瞬时错误（常因后台定时任务/另一个实例同步中）。"""
    m = str(msg)
    return any(pat in m for pat in (
        "Cannot open file", "另一个程序正在使用此文件", "already open",
        "Could not set lock", "lock", "being used by another process",
    ))


def _startup_tdx_sync():
    """
    启动时自动从通达信本地 .day 文件增量同步到 DuckDB。
    每个浏览器会话仅执行一次，增量模式（每只股票只读末尾 160 字节），
    5000+ 只股票约 1-3 秒完成。
    """
    if "_tdx_startup_sync_done" in st.session_state:
        return

    # 先标记完成，防止异常时重复触发
    st.session_state._tdx_startup_sync_done = True

    from config import get_tdx_vipdoc_path
    from data.sync import sync_from_tdx
    from data.database import get_db_stats

    vipdoc_path = get_tdx_vipdoc_path()

    if vipdoc_path is None:
        st.session_state._tdx_startup_result = {
            "status": "not_found",
            "message": "未检测到券商客户端 (通达信) 数据目录"
        }
        return

    import time as _t

    last_exc = None
    stats_after = None
    result = None
    # 数据库文件锁（另一个进程同步中）通常是瞬时：最多重试 3 次
    for attempt in range(4):
        try:
            stats_after = get_db_stats()
            result = sync_from_tdx(str(vipdoc_path), full_import=False)
            last_exc = None
            break
        except Exception as e:
            last_exc = e
            if not _is_lock_error(str(e)):
                break
            _t.sleep(1.5 * (attempt + 1))

    if last_exc is not None:
        if _is_lock_error(str(last_exc)):
            # 重试后仍被占用 → 友好降级，允许下次交互手动重试
            st.session_state._tdx_startup_result = {
                "status": "locked",
                "message": "数据库暂时被占用（可能正在后台同步），稍后重试",
            }
        else:
            st.session_state._tdx_startup_result = {
                "status": "error",
                "message": str(last_exc),
            }
        return

    if result.get("errors") and any(
        "未找到券商客户端目录" in str(e) for e in result["errors"]
    ):
        st.session_state._tdx_startup_result = {
            "status": "no_path",
            "message": "vipdoc 目录为空或不存在 .day 文件"
        }
        return

    new_stocks = result.get("imported", 0)
    skipped = result.get("skipped", 0)
    errors = result.get("errors", [])

    st.session_state._tdx_startup_result = {
        "status": "ok",
        "new_stocks": new_stocks,
        "skipped": skipped,
        "errors": errors,
        "vipdoc_path": str(vipdoc_path),
        "stock_count": stats_after.get("stock_count", 0),
        "max_date": stats_after.get("max_date", ""),
    }


def _startup_fund_flow_sync():
    """
    启动时后台抓取当日全市场资金流快照（同花顺源）。
    使用 daemon 线程不阻塞启动，结果就绪后自动写入 session_state。
    """
    import threading

    if "_ff_startup_sync_done" in st.session_state:
        return
    st.session_state._ff_startup_sync_done = True

    def _do_sync():
        from data.fund_flow import sync_fund_flow_snapshot
        try:
            result = sync_fund_flow_snapshot()
            st.session_state._ff_startup_result = result
        except Exception as e:
            st.session_state._ff_startup_result = {"status": "error", "message": str(e)}

    t = threading.Thread(target=_do_sync, daemon=True)
    t.start()


_startup_tdx_sync()
# 资金流同步：后台线程在启动时抓取当日全市场资金流快照（不阻塞启动）。
# 若接口慢/失败，get_fund_flow_data() 会有自愈同步兜底。
_startup_fund_flow_sync()


STRATEGY_MAP = {
    "双均线 (MA Cross)": MACrossStrategy,
    "MACD": MACDStrategy,
    "RSI 超买超卖": RSIStrategy,
    "布林带 (Bollinger)": BollingerStrategy,
    "三均线 (Triple MA)": TripleMAStrategy,
    "KDJ": KDJStrategy,
    "唐奇安通道 (Donchian)": DonchianStrategy,
    "ATR动态跟踪": ATRStrategy,
}

HOT_STOCKS = {
    "招商银行": "600036",
    "贵州茅台": "600519",
    "宁德时代": "300750",
    "平安银行": "000001",
    "比亚迪": "002594",
}

# =========================== 页面导航（侧边栏分组） ===========================
# 17 个页面按「市场分析 / 策略研究 / 数据」分组，放侧边栏；
# 每次只渲染当前选中的页面（st.navigation），比原先 17 个 tab 全渲染更快。

from tabs.tab_workflow import render as render_wf
from tabs.tab_ai import render as render_ai
from tabs.tab1_backtest import render as render_tab1
from tabs.tab2_compare import render as render_tab2
from tabs.tab3_optimize import render as render_tab3
from tabs.tab_performance import render as render_perf
from tabs.tab_ml import render as render_ml
from tabs.tab_signal_validation import render as render_sv
from tabs.tab5_market_rank import render as render_tab4
from tabs.tab_screener import render as render_sc
from tabs.tab9_lhb import render as render_lhb
from tabs.tab_watchlist import render as render_wl
from tabs.tab11_portfolio import render as render_tab8
from tabs.tab12_northbound import render as render_tab9
from tabs.tab13_fundamental import render as render_tab10
from tabs.tab14_industry import render as render_tab11
from tabs.tab15_database import render as render_tab12
from tabs.tab16_advanced import render as render_tab13
from tabs.tab_strategy_templates import render as render_stpl

PAGES = {
    "📈 市场分析": [
        st.Page(render_wf, title="选股工作流", icon="📋", url_path="workflow"),
        st.Page(render_sc, title="智能选股", icon="🧠", url_path="screener"),
        st.Page(render_tab4, title="资金排名", icon="💰", url_path="market-rank"),
        st.Page(render_lhb, title="龙虎榜", icon="🐉", url_path="lhb"),
        st.Page(render_wl, title="自选股", icon="⭐", url_path="watchlist"),
        st.Page(render_tab11, title="市场全景", icon="🏭", url_path="industry"),
        st.Page(render_tab9, title="北向&融资", icon="🌏", url_path="northbound"),
        st.Page(render_tab10, title="财务分析", icon="📊", url_path="fundamental"),
        st.Page(render_ai, title="AI智能分析", icon="🤖", url_path="ai"),
    ],
    "🧪 策略研究": [
        st.Page(render_tab1, title="单策略回测", icon="📊", url_path="backtest"),
        st.Page(render_tab2, title="策略对比", icon="📋", url_path="compare"),
        st.Page(render_tab3, title="参数优化", icon="🔧", url_path="optimize"),
        st.Page(render_perf, title="绩效分析", icon="📈", url_path="performance"),
        st.Page(render_tab8, title="组合回测", icon="🧺", url_path="portfolio"),
        st.Page(render_ml, title="ML因子研究", icon="🧠", url_path="ml"),
        st.Page(render_sv, title="信号验证", icon="📡", url_path="signal-validation"),
        st.Page(render_stpl, title="策略模板", icon="🧩", url_path="strategy-templates"),
        st.Page(render_tab13, title="高级分析", icon="🔬", url_path="advanced"),
    ],
    "🗄️ 数据": [
        st.Page(render_tab12, title="数据中心", icon="🗄️", url_path="database"),
    ],
}

pg = st.navigation(PAGES, position="sidebar")

# =========================== 侧边栏（三区分流） ===========================
# ① 导航区 由 st.navigation 自带；
# ② 全局控制区（工作模式/搜索/快捷选股/数据状态）→ ui.sidebar.render_global_controls
# ③ 页内上下文 → 回测参数折叠以保留共享状态；自动日报/推送折叠。
from ui.sidebar import (
    render_global_controls, render_backtest_params, render_settings,
)

render_global_controls(HOT_STOCKS)
st.sidebar.divider()
render_backtest_params(STRATEGY_MAP)
st.sidebar.divider()
render_settings()

# =========================== 页面路由 ===========================
pg.run()
