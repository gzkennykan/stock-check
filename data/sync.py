"""
每日数据同步模块：收盘后自动将数据库内全部股票的最新日线写入 DuckDB。

用法：
  python -m data.sync                    # 同步全部股票（仅最新交易日）
  python -m data.sync -n 5               # 同步最近 5 个交易日
  python -m data.sync -s 600036,000001   # 只同步指定股票
  python -m data.sync --since 2026-06-01 # 从指定日期起同步
"""
import pandas as pd
import time
from pathlib import Path
from datetime import datetime, timedelta
from config import DATA_DIR


def _list_tracked_symbols(only_target: bool = True) -> list[str]:
    """获取数据库中已有的股票代码，默认只返回四大板块"""
    from .database import get_all_symbols, is_target_stock
    symbols = get_all_symbols()
    if only_target:
        symbols = [s for s in symbols if is_target_stock(s)]
    return symbols


def _list_target_symbols() -> list[str]:
    """仅获取四大板块股票代码"""
    from .database import get_all_symbols, is_target_stock
    return [s for s in get_all_symbols() if is_target_stock(s)]


def _get_latest_date_for_symbol(symbol: str) -> str | None:
    """获取某只股票在数据库中的最新日期"""
    from .database import get_connection
    conn = get_connection(read_only=True)
    try:
        r = conn.execute(
            "SELECT MAX(trade_date) FROM daily_kline WHERE symbol = ?", [symbol]
        ).fetchone()
        return str(r[0]) if r and r[0] else None
    finally:
        conn.close()


def _fetch_latest_from_akshare(symbol: str, since_date: str) -> pd.DataFrame | None:
    """用 AKShare 获取单只股票从 since_date 至今的日线（不含 since_date 当日）"""
    try:
        import akshare as ak

        # 新浪格式
        if symbol.startswith(("6", "5", "9")):
            sina = f"sh{symbol}"
        elif symbol.startswith(("0", "3", "2")):
            sina = f"sz{symbol}"
        else:
            return None

        today = datetime.now().strftime("%Y%m%d")
        raw = ak.stock_zh_a_daily(
            symbol=sina,
            start_date=since_date.replace("-", ""),
            end_date=today,
            adjust="qfq",
        )
        if raw.empty:
            return None

        df = raw.copy()
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
        df = df[["open", "high", "low", "close", "volume"]].sort_index()

        # 只取 since_date 之后的数据
        cutoff = pd.to_datetime(since_date)
        df = df[df.index > cutoff]

        return df if not df.empty else None
    except Exception:
        return None


def sync_daily(symbols: list[str] = None, n_days: int = 1,
               since_date: str = None, progress_cb=None) -> dict:
    """
    增量同步日线数据到 DuckDB。

    参数：
        symbols:    股票代码列表，None=全部在库股票
        n_days:     同步最近 N 个交易日
        since_date: 从指定日期起同步（覆盖 n_days）
        progress_cb: 可选回调 fn(current, total, symbol, status)

    返回：
        {"updated": int, "skipped": int, "errors": [...], "new_rows": int}
    """
    from .database import insert_kline

    if symbols is None:
        symbols = _list_tracked_symbols()
    if not symbols:
        return {"updated": 0, "skipped": 0, "errors": ["数据库为空"], "new_rows": 0}

    # 确定起始日期
    if since_date:
        cutoff = since_date
    elif n_days > 1:
        cutoff = (datetime.now() - timedelta(days=n_days + 3)).strftime("%Y-%m-%d")
    else:
        cutoff = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")

    total = len(symbols)
    result = {"updated": 0, "skipped": 0, "errors": [], "new_rows": 0}

    for i, sym in enumerate(symbols):
        try:
            # 先检查是否需要更新
            latest = _get_latest_date_for_symbol(sym)
            if latest and latest >= datetime.now().strftime("%Y-%m-%d"):
                result["skipped"] += 1
                if progress_cb:
                    progress_cb(i + 1, total, sym, "skip")
                continue

            # 从 AKShare 拉取
            df = _fetch_latest_from_akshare(sym, cutoff)
            if df is None or df.empty:
                result["skipped"] += 1
                if progress_cb:
                    progress_cb(i + 1, total, sym, "no_data")
                continue

            # 写入数据库
            n = insert_kline(sym, df, source="akshare")
            result["updated"] += 1
            result["new_rows"] += n

            if progress_cb:
                progress_cb(i + 1, total, sym, f"+{n}")

            # 请求间隔，避免被封
            time.sleep(0.15)

        except Exception as e:
            result["errors"].append(f"{sym}: {e}")
            if progress_cb:
                progress_cb(i + 1, total, sym, "err")

    return result


def sync_from_tdx(vipdoc_path: str = None, symbols: list[str] = None,
                  full_import: bool = False) -> dict:
    """
    从通达信 .day 文件同步最新数据。

    参数：
        vipdoc_path: vipdoc 目录，不传自动探测
        symbols:     要同步的股票，None=全部（四大板块）
        full_import: True=全量导入（首次使用），False=增量（日常同步，秒级）

    返回：
        {"imported": int, "stocks": [...], "errors": [...]}
    """
    from .tdx_reader import import_vipdoc_to_db_direct, import_vipdoc_to_db_incremental

    if vipdoc_path is None:
        from config import get_tdx_vipdoc_path
        detected = get_tdx_vipdoc_path()
        if detected:
            vipdoc_path = str(detected)
        else:
            return {"imported": 0, "stocks": [], "errors": ["未找到券商客户端目录"]}

    if full_import:
        return import_vipdoc_to_db_direct(vipdoc_path, symbols)
    else:
        return import_vipdoc_to_db_incremental(vipdoc_path, symbols, n_days=5)


# ══════════════════════════════════════════
# CLI
# ══════════════════════════════════════════

def _main():
    import argparse

    parser = argparse.ArgumentParser(description="每日数据同步工具")
    parser.add_argument("-n", "--days", type=int, default=1,
                        help="同步最近 N 个交易日（默认 1）")
    parser.add_argument("-s", "--symbols", type=str, default=None,
                        help="指定股票代码，逗号分隔，默认全部")
    parser.add_argument("--since", type=str, default=None,
                        help="从指定日期起同步 YYYY-MM-DD")
    parser.add_argument("--source", choices=["akshare", "tdx"], default="akshare",
                        help="数据源（默认 akshare）")
    parser.add_argument("--tdx-path", type=str, default=None,
                        help="通达信 vipdoc 路径（仅 --source=tdx 时有效）")
    args = parser.parse_args()

    symbols = None
    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",")]

    print("=" * 60)
    print("  数据同步工具")
    print(f"  数据源: {args.source}  |  股票: {len(symbols) if symbols else '全部'}")
    print("=" * 60)
    print()

    if args.source == "tdx":
        result = sync_from_tdx(args.tdx_path, symbols)
        print(f"导入完成: {result['imported']} 行 ({len(result['stocks'])} 只股票)")
        if result["errors"]:
            print(f"错误 ({len(result['errors'])}):")
            for e in result["errors"][:5]:
                print(f"  {e}")
    else:
        result = sync_daily(
            symbols, n_days=args.days, since_date=args.since,
            progress_cb=lambda c, t, s, st:
                print(f"  [{c}/{t}] {s}  {st}")
        )
        print()
        print(f"✅ 更新: {result['updated']} 只  |  "
              f"跳过: {result['skipped']} 只  |  "
              f"新增: {result['new_rows']} 行")
        if result["errors"]:
            print(f"⚠️ 错误 ({len(result['errors'])}):")
            for e in result["errors"][:5]:
                print(f"  {e}")

    # 显示最终状态
    from .database import get_db_stats
    stats = get_db_stats()
    print(f"\n📊 数据库状态: {stats['stock_count']} 只, "
          f"{stats['total_rows']:,} 行, "
          f"最新: {stats['max_date']}")


if __name__ == "__main__":
    _main()
