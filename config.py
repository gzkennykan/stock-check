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
