"""
将现有 data_cache/*.csv (单股日线) 批量导入 DuckDB 数据库

用法:
    python -m data.import_csv          # 导入全部
    python -m data.import_csv --dry-run  # 仅预览不写入
    python -m data.import_csv -s 600036  # 只导入指定股票
"""
import pandas as pd
from pathlib import Path
from config import DATA_DIR
from .database import insert_kline, upsert_stock_info, get_stocks_in_db
from .fetcher import _detect_source


def _is_kline_csv(df: pd.DataFrame) -> bool:
    """判断 CSV 是否是日线数据（有 OHLCV 列）"""
    required = {"open", "high", "low", "close", "volume"}
    return required.issubset(set(c.lower() for c in df.columns))


def _find_kline_csvs(data_dir: Path) -> list[Path]:
    """扫描 data_cache 目录，找出所有单股日线 CSV"""
    csvs = []
    for f in sorted(data_dir.glob("*.csv")):
        # 跳过系统缓存文件（以下划线开头）
        if f.stem.startswith("_"):
            continue
        # 跳过非6位数字命名的文件（如 northbound_flow.csv）
        if not f.stem.isdigit() or len(f.stem) != 6:
            continue
        csvs.append(f)
    return csvs


def import_csv_to_db(symbols: list[str] = None, dry_run: bool = False) -> dict:
    """
    将 CSV 日线数据导入 DuckDB。

    参数:
        symbols: 要导入的股票代码列表，None=全部
        dry_run: True=仅预览不写入

    返回:
        {"imported": 总行数, "stocks": [...], "errors": [...]}
    """
    csv_files = _find_kline_csvs(DATA_DIR)

    if symbols:
        csv_files = [f for f in csv_files if f.stem in symbols]

    if not csv_files:
        return {"imported": 0, "stocks": [], "errors": ["未找到可导入的 CSV 文件"]}

    result = {"imported": 0, "stocks": [], "errors": []}

    for csv_path in csv_files:
        sym = csv_path.stem
        try:
            df = pd.read_csv(csv_path, index_col=0, parse_dates=True)
            if not _is_kline_csv(df):
                continue

            result["stocks"].append({
                "symbol": sym,
                "rows": len(df),
                "start": str(df.index.min().date()),
                "end": str(df.index.max().date()),
            })

            if not dry_run:
                source = _detect_source(sym)
                n = insert_kline(sym, df, source=source)
                result["imported"] += n

        except Exception as e:
            result["errors"].append(f"{sym}: {e}")

    return result


def _main():
    import argparse
    parser = argparse.ArgumentParser(description="CSV → DuckDB 导入工具")
    parser.add_argument("--dry-run", action="store_true", help="仅预览不写入")
    parser.add_argument("-s", "--symbol", type=str, nargs="*", help="指定股票代码")
    args = parser.parse_args()

    print("=" * 60)
    print("  CSV → DuckDB 数据导入")
    print("=" * 60)

    # 预览
    csv_files = _find_kline_csvs(DATA_DIR)
    if args.symbol:
        csv_files = [f for f in csv_files if f.stem in args.symbol]
    print(f"\n[Files] Found {len(csv_files)} stock CSV files:")
    for f in csv_files:
        df = pd.read_csv(f, index_col=0, parse_dates=True)
        print(f"   {f.stem}: {len(df)} rows, {df.index.min().date()} ~ {df.index.max().date()}")

    # 导入
    result = import_csv_to_db(args.symbol, dry_run=args.dry_run)

    if args.dry_run:
        print(f"\n[Dry Run] Preview: {len(result['stocks'])} stocks, "
              f"{sum(s['rows'] for s in result['stocks'])} rows")
    else:
        print(f"\n[OK] Imported: {result['imported']} rows ({len(result['stocks'])} stocks)")

    if result["errors"]:
        print(f"\n[WARN] Errors ({len(result['errors'])}):")
        for e in result["errors"]:
            print(f"   {e}")

    # 显示当前 DB 状态
    existing = get_stocks_in_db()
    if not existing.empty:
        print(f"\n[DB Stats] {len(existing)} stocks, "
              f"{existing['rows'].sum()} rows")

    print()


if __name__ == "__main__":
    _main()
