"""
通达信 (TDX) .day 日K线二进制文件解析器

格式说明（每条记录 32 字节）:
  struct: <IIIIIfII  (小端序)
  - date:   uint32  日期 YYYYMMDD
  - open:   uint32  开盘价 * 100
  - high:   uint32  最高价 * 100
  - low:    uint32  最低价 * 100
  - close:  uint32  收盘价 * 100
  - amount: float32  成交额 (元)
  - volume: uint32  成交量 (股)
  - rsv:    uint32  保留位

文件路径约定:
  vipdoc/sh/lday/sh600036.day  → 沪市A股 600036
  vipdoc/sz/lday/sz000001.day  → 深市A股 000001
  vipdoc/bj/lday/bj8xxxxx.day  → 北交所
"""
import struct
import pandas as pd
from pathlib import Path
from datetime import datetime

# TDX 日线单条记录: 8个字段 × 4字节 = 32字节
TDX_DAY_FORMAT = "<IIIIIfII"
TDX_DAY_SIZE = struct.calcsize(TDX_DAY_FORMAT)  # 32


def parse_day_file(file_path: Path) -> pd.DataFrame | None:
    """
    解析单个 .day 文件，返回标准 OHLCV DataFrame。
    """
    return _parse_day_bytes(file_path.read_bytes(), file_path.name)


def parse_day_file_tail(file_path: Path, n_records: int = 5) -> pd.DataFrame | None:
    """
    仅读取 .day 文件末尾 N 条记录（增量同步用，毫秒级）。
    默认取最后 5 条，覆盖最近一周交易日。
    """
    fsize = file_path.stat().st_size
    if fsize == 0:
        return None
    # 只读末尾 N 条 × 32 字节
    read_size = min(fsize, n_records * TDX_DAY_SIZE + 32)
    with open(file_path, "rb") as fh:
        fh.seek(fsize - read_size)
        tail_bytes = fh.read(read_size)
    return _parse_day_bytes(tail_bytes, file_path.name)


def _parse_day_bytes(raw: bytes, name: str = "") -> pd.DataFrame | None:
    """解析 .day 二进制数据块，返回 OHLCV DataFrame"""
    if len(raw) == 0:
        return None

    if len(raw) % TDX_DAY_SIZE != 0:
        raise ValueError(
            f"{name}: 文件大小 {len(raw)} 不是 {TDX_DAY_SIZE} 的整数倍，格式异常"
        )

    num_records = len(raw) // TDX_DAY_SIZE
    records = []
    for i in range(num_records):
        offset = i * TDX_DAY_SIZE
        chunk = raw[offset:offset + TDX_DAY_SIZE]
        try:
            date, op, hi, lo, cl, amt, vol, _ = struct.unpack(TDX_DAY_FORMAT, chunk)
        except struct.error:
            continue  # 忽略损坏的记录

        # 跳过无效记录
        if date < 19900101 or date > 20991231 or op == 0:
            continue

        records.append({
            "date": date,
            "open": op / 100.0,
            "high": hi / 100.0,
            "low": lo / 100.0,
            "close": cl / 100.0,
            "amount": amt,
            "volume": vol,
        })

    if not records:
        return None

    df = pd.DataFrame(records)
    df["trade_date"] = pd.to_datetime(df["date"].astype(str), format="%Y%m%d")
    df = df.set_index("trade_date")
    df = df[["open", "high", "low", "close", "volume", "amount"]].sort_index()
    return df


def parse_filename(file_name: str) -> tuple[str, str] | None:
    """
    从 TDX 文件名提取市场和代码。

    示例:
        sh600036.day → ("sh", "600036")
        sz000001.day → ("sz", "000001")
        bj830799.day → ("bj", "830799")
    """
    name = Path(file_name).stem  # 去扩展名
    if len(name) < 3:
        return None
    market = name[:2]  # sh / sz / bj
    symbol = name[2:]
    if market in ("sh", "sz", "bj") and symbol.isdigit() and len(symbol) == 6:
        return market, symbol
    return None


def scan_vipdoc(vipdoc_root: str | Path) -> list[dict]:
    """
    扫描通达信 vipdoc 目录，找到所有 .day 文件。

    参数:
        vipdoc_root: vipdoc 目录路径，如 C:/zd_zxzq_gm/vipdoc

    返回:
        [{"market": "sh", "symbol": "600036", "path": Path, "size": int, "estimated_rows": int}, ...]
    """
    vipdoc = Path(vipdoc_root)
    if not vipdoc.exists():
        return []

    files = []
    for sub in ["sh/lday", "sz/lday", "bj/lday", "ds/lday"]:
        lday_dir = vipdoc / sub
        if not lday_dir.is_dir():
            continue
        for f in sorted(lday_dir.glob("*.day")):
            parsed = parse_filename(f.name)
            if parsed is None:
                continue
            market, symbol = parsed
            file_size = f.stat().st_size
            files.append({
                "market": market,
                "symbol": symbol,
                "path": f,
                "size": file_size,
                "estimated_rows": file_size // TDX_DAY_SIZE,
            })

    return files


def import_vipdoc_to_db(vipdoc_root: str | Path,
                        symbols: list[str] = None,
                        progress_callback=None) -> dict:
    """
    扫描 vipdoc 目录下的 .day 文件，解析并导入 DuckDB。

    参数:
        vipdoc_root: vipdoc 目录路径
        symbols:     要导入的股票代码列表，None=全部
        progress_callback: 可选回调 fn(current, total, symbol)

    返回:
        {"imported": 行数, "stocks": [...], "errors": [...]}
    """
    from .database import insert_kline
    from .fetcher import _detect_source

    # 这里需要用绝对导入避免循环问题
    import importlib
    db = importlib.import_module("data.database")

    all_files = scan_vipdoc(vipdoc_root)

    if symbols:
        all_files = [f for f in all_files if f["symbol"] in symbols]

    if not all_files:
        return {"imported": 0, "stocks": [], "errors": ["未找到 .day 文件"]}

    result = {"imported": 0, "stocks": [], "errors": []}
    total = len(all_files)

    for idx, finfo in enumerate(all_files):
        sym = finfo["symbol"]
        try:
            df = parse_day_file(finfo["path"])
            if df is None:
                result["errors"].append(f"{sym}: 文件为空或格式异常")
                continue

            n = db.insert_kline(sym, df, source="tdx")
            result["imported"] += n
            result["stocks"].append({
                "symbol": sym,
                "market": finfo["market"],
                "rows": n,
                "start": str(df.index.min().date()),
                "end": str(df.index.max().date()),
            })

        except Exception as e:
            result["errors"].append(f"{sym}: {e}")

        if progress_callback:
            progress_callback(idx + 1, total, sym)

    return result


def import_vipdoc_to_db_incremental(vipdoc_root: str | Path,
                                     symbols: list[str] = None,
                                     n_days: int = 5,
                                     progress_callback=None) -> dict:
    """
    增量同步：每个 .day 文件只读取末尾 N 条记录，跳过已有日期。

    比全量导入快 100 倍以上（每个文件只读 ~160 字节 vs 全部 37KB）。
    """
    from data.database import insert_kline, get_latest_trading_date

    all_files = scan_vipdoc(vipdoc_root)
    if symbols:
        all_files = [f for f in all_files if f["symbol"] in symbols]
    if not all_files:
        return {"imported": 0, "stocks": [], "errors": ["未找到 .day 文件"]}

    db_latest = get_latest_trading_date()

    result = {"imported": 0, "stocks": [], "errors": [], "skipped": 0}
    total = len(all_files)

    for idx, finfo in enumerate(all_files):
        sym = finfo["symbol"]
        try:
            df = parse_day_file_tail(finfo["path"], n_records=n_days)
            if df is None or df.empty:
                result["skipped"] += 1
                if progress_callback:
                    progress_callback(idx + 1, total, sym)
                continue

            # 过滤掉数据库已有的日期
            if db_latest:
                df = df[df.index > pd.Timestamp(db_latest)]
            if df.empty:
                result["skipped"] += 1
                if progress_callback:
                    progress_callback(idx + 1, total, sym)
                continue

            n = insert_kline(sym, df, source="tdx")
            result["imported"] += 1
            result["stocks"].append({
                "symbol": sym, "market": finfo["market"],
                "rows": n,
                "start": str(df.index.min().date()),
                "end": str(df.index.max().date()),
            })
        except Exception as e:
            result["errors"].append(f"{sym}: {e}")

        if progress_callback:
            progress_callback(idx + 1, total, sym)

    return result


def import_vipdoc_to_db_direct(vipdoc_root: str | Path,
                               symbols: list[str] = None,
                               progress_callback=None) -> dict:
    """
    与 import_vipdoc_to_db 相同，但使用直接导入避免循环引用问题。
    """
    from data.database import insert_kline

    all_files = scan_vipdoc(vipdoc_root)

    if symbols:
        all_files = [f for f in all_files if f["symbol"] in symbols]

    if not all_files:
        return {"imported": 0, "stocks": [], "errors": ["未找到 .day 文件"]}

    result = {"imported": 0, "stocks": [], "errors": []}
    total = len(all_files)

    for idx, finfo in enumerate(all_files):
        sym = finfo["symbol"]
        try:
            df = parse_day_file(finfo["path"])
            if df is None:
                result["errors"].append(f"{sym}: 文件为空或格式异常")
                continue

            n = insert_kline(sym, df, source="tdx")
            result["imported"] += n
            result["stocks"].append({
                "symbol": sym,
                "market": finfo["market"],
                "rows": n,
                "start": str(df.index.min().date()),
                "end": str(df.index.max().date()),
            })

        except Exception as e:
            result["errors"].append(f"{sym}: {e}")

        if progress_callback:
            progress_callback(idx + 1, total, sym)

    return result


# ────────────────────────── CLI ──────────────────────────

def _main():
    """命令行入口: python -m data.tdx_reader <vipdoc路径>"""
    import argparse

    parser = argparse.ArgumentParser(description="通达信 .day → DuckDB 导入工具")
    parser.add_argument("vipdoc", type=str, nargs="?", default=None,
                        help="vipdoc 目录路径（默认扫描 C:/zd_zxzq_gm/vipdoc）")
    parser.add_argument("--dry-run", action="store_true", help="仅预览不写入")
    parser.add_argument("-s", "--symbol", type=str, nargs="*", help="指定股票代码")
    args = parser.parse_args()

    # 默认路径
    if args.vipdoc is None:
        from config import get_tdx_vipdoc_path
        detected = get_tdx_vipdoc_path()
        if detected:
            args.vipdoc = detected
        else:
            print("未找到通达信 vipdoc 目录，请手动指定路径")
            return

    vipdoc = Path(args.vipdoc)

    print("=" * 60)
    print(f"  通达信 .day → DuckDB 导入")
    print(f"  路径: {vipdoc}")
    print("=" * 60)

    # 扫描
    files = scan_vipdoc(vipdoc)
    if args.symbol:
        files = [f for f in files if f["symbol"] in args.symbol]

    if not files:
        print("\n未找到 .day 文件。请在券商客户端中浏览日K线图以下载数据。")
        return

    total_rows = sum(f["estimated_rows"] for f in files)
    print(f"\n扫描到 {len(files)} 个 .day 文件, 预估 {total_rows:,} 行数据:")
    for f in files[:20]:
        print(f"  {f['market']}{f['symbol']}.day  "
              f"({f['size']/1024:.1f} KB, ~{f['estimated_rows']} 行)")
    if len(files) > 20:
        print(f"  ... 及其他 {len(files) - 20} 个文件")

    if args.dry_run:
        print(f"\n[预览模式] 未写入数据库")
        return

    # 导入
    print("\n导入中...")
    result = import_vipdoc_to_db_direct(vipdoc, args.symbol,
                                         progress_callback=lambda c, t, s: print(
                                             f"  [{c}/{t}] {s}"))
    print(f"\n完成: {result['imported']} 行 ({len(result['stocks'])} 只股票)")

    if result["errors"]:
        print(f"\n错误 ({len(result['errors'])}):")
        for e in result["errors"][:10]:
            print(f"  {e}")

    # 显示 DB 状态
    from data.database import get_stocks_in_db
    existing = get_stocks_in_db()
    if not existing.empty:
        print(f"\n数据库状态: {len(existing)} 只股票, {existing['rows'].sum()} 行")


if __name__ == "__main__":
    _main()
