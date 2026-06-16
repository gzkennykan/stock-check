"""
全局配置
"""
from pathlib import Path

# 项目根目录
ROOT_DIR = Path(__file__).parent

# 数据缓存目录
DATA_DIR = ROOT_DIR / "data_cache"
DATA_DIR.mkdir(exist_ok=True)

# DuckDB 数据库路径
DB_PATH = DATA_DIR / "stock_system.duckdb"

# 回测默认参数
INITIAL_CASH = 1_000_000.0      # 初始资金
COMMISSION_RATE = 0.0003        # 佣金率 (万三)
STAMP_TAX = 0.001               # 印花税 (卖出千一)
SLIPPAGE = 0.0001               # 滑点
DEFAULT_BENCHMARK = "000300"    # 默认基准 (沪深300)

# 数据源
DEFAULT_SOURCE = "akshare"      # akshare / yfinance

# 回测默认时间范围
DEFAULT_START = "2023-01-01"
DEFAULT_END = "2024-12-31"

# ────────────────────────── 通达信 (TDX) 本地数据 ──────────────────────────

# 通达信 vipdoc 候选路径（按顺序自动探测）
TDX_VIPDOC_CANDIDATES = [
    "C:/zd_zxzq_gm/vipdoc",
    "C:/中信证券至信版/vipdoc",
    "C:/new_zxzq/vipdoc",
]

# 手动指定的 vipdoc 路径（None=自动探测）
TDX_VIPDOC_PATH = None


def get_tdx_vipdoc_path() -> Path | None:
    """返回通达信 vipdoc 目录路径（手动配置优先，否则自动探测）"""
    if TDX_VIPDOC_PATH:
        p = Path(TDX_VIPDOC_PATH)
        if p.exists():
            return p
    for candidate in TDX_VIPDOC_CANDIDATES:
        p = Path(candidate)
        if p.exists():
            return p
    return None
