"""
缓存预热脚本：在启动 Streamlit 前预加载常用数据，减少首次打开等待时间。
运行: python warmup.py
"""
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))


def warm_cache(label: str, fn, **kwargs):
    """执行单个预热任务，显示耗时"""
    t0 = time.time()
    try:
        result = fn(**kwargs)
        elapsed = time.time() - t0
        count = len(result) if hasattr(result, '__len__') else '?'
        print(f"  [{elapsed:5.1f}s] {label} — ✓ ({count} 条)")
        return True
    except Exception as e:
        elapsed = time.time() - t0
        print(f"  [{elapsed:5.1f}s] {label} — ✗ ({e})")
        return False


def main():
    print("=" * 50)
    print("  股票量化回测系统 — 缓存预热")
    print("=" * 50)

    # 行情数据（全 A 股 ~5200 只）
    from data.screener import get_stock_list, get_fund_flow_data, _fetch_profitability_data
    warm_cache("全 A 股实时行情", get_stock_list, force_refresh=False)

    # 资金流向（全市场 ~5200 只，最慢的一项）
    warm_cache("同花顺资金流向", get_fund_flow_data, force_refresh=False)

    # 盈利能力（季度财报 ~5200 只）
    warm_cache("最新季度财报(ROE/增长/毛利率)", _fetch_profitability_data, force_refresh=False)

    print("-" * 50)
    print("  预热完成，可启动 Streamlit。")
    print("=" * 50)


if __name__ == "__main__":
    main()
