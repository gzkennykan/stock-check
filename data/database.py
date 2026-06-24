"""
DuckDB 本地数据库：存储股票历史日线数据 & 基本信息，支持高性能分析查询

数据库文件: data_cache/stock_system.duckdb
表结构:
  - daily_kline: 日线OHLCV数据 (主键: symbol + trade_date)
  - stock_info:   股票基本信息 (主键: symbol)
"""
import pandas as pd
from pathlib import Path
from datetime import datetime
from config import DB_PATH


# ────────────────────────── 连接管理 ──────────────────────────

_DB_CONN = None


class _SharedConnection:
    """DuckDB 单例连接包装：close() 为 no-op，其余全部委托原始连接。

    关键：不定义 execute() —— 让 __getattr__ 返回原始连接的 bound method，
    这样 DuckDB 的 DataFrame 自动注册（依赖 Python 调用栈）不会被包装层打断。
    """

    def __init__(self, raw):
        self.__dict__["_raw"] = raw

    def close(self):
        pass  # 下游代码可安全调用，不真正关闭

    def __getattr__(self, name):
        return getattr(self._raw, name)

    def __setattr__(self, name, value):
        if name == "_raw":
            self.__dict__["_raw"] = value
        else:
            setattr(self._raw, name, value)


def get_connection(read_only: bool = False):
    """获取 DuckDB 单例连接（同一进程内共享，避免多 Tab 锁冲突）"""
    global _DB_CONN
    import duckdb
    if _DB_CONN is None:
        raw = duckdb.connect(str(DB_PATH), read_only=False)
        raw.execute("PRAGMA threads=2")
        _DB_CONN = _SharedConnection(raw)
    return _DB_CONN


def _ensure_tables(conn) -> None:
    """确保核心表存在，首次调用时自动建表"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_kline (
            symbol      VARCHAR(10)   NOT NULL,
            trade_date  DATE          NOT NULL,
            open        DOUBLE,
            high        DOUBLE,
            low         DOUBLE,
            close       DOUBLE,
            volume      DOUBLE,
            source      VARCHAR(20)   DEFAULT 'akshare',
            updated_at  TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (symbol, trade_date)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stock_info (
            symbol      VARCHAR(10)   PRIMARY KEY,
            name        VARCHAR(50),
            market      VARCHAR(10),
            industry    VARCHAR(100),
            listed_date DATE,
            updated_at  TIMESTAMP     DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # 自选股表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS watchlist (
            symbol      VARCHAR(10)   PRIMARY KEY,
            name        VARCHAR(50),
            added_at    TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,
            note        VARCHAR(200)
        )
    """)
    # 每日资金流向快照（同花顺源，日积月累）
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fund_flow_daily (
            symbol          VARCHAR(10)   NOT NULL,
            trade_date      DATE          NOT NULL,
            price           DOUBLE,
            pct_change      DOUBLE,
            turnover_rate   DOUBLE,
            capital_inflow  DOUBLE,        -- 流入资金(元)
            capital_outflow DOUBLE,        -- 流出资金(元)
            main_net        DOUBLE,        -- 净额(元)
            turnover        DOUBLE,        -- 成交额(元)
            updated_at      TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (symbol, trade_date)
        )
    """)
    # 为常见查询建立索引
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_kline_symbol ON daily_kline(symbol)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_kline_date ON daily_kline(trade_date)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_ff_symbol ON fund_flow_daily(symbol)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_ff_date ON fund_flow_daily(trade_date)
    """)


# ────────────────────────── 写入操作 ──────────────────────────

def insert_kline(symbol: str, df: pd.DataFrame, source: str = "akshare") -> int:
    """
    将一只股票的日线数据写入 daily_kline 表（upsert 语义：主键冲突时更新）。

    参数:
        symbol: 股票代码
        df: 包含 [open, high, low, close, volume] 的 DataFrame，index 为 date
        source: 数据来源

    返回:
        写入行数
    """
    if df.empty:
        return 0

    conn = get_connection()
    try:
        _ensure_tables(conn)

        # 准备写入数据
        write_df = df[["open", "high", "low", "close", "volume"]].copy()
        write_df["symbol"] = symbol
        write_df["source"] = source
        write_df["trade_date"] = write_df.index  # index 是 date
        write_df["updated_at"] = datetime.now()

        # DuckDB 原生 upsert: INSERT OR REPLACE
        conn.execute("BEGIN")
        conn.execute("""
            INSERT OR REPLACE INTO daily_kline
                (symbol, trade_date, open, high, low, close, volume, source, updated_at)
            SELECT symbol, trade_date, open, high, low, close, volume, source, updated_at
            FROM write_df
        """)
        conn.execute("COMMIT")
        return len(write_df)
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def insert_kline_batch(records: list[dict]) -> int:
    """
    批量写入多只股票的日线数据。

    参数:
        records: [{"symbol": "600036", "df": DataFrame, "source": "akshare"}, ...]

    返回:
        总写入行数
    """
    total = 0
    conn = get_connection()
    try:
        _ensure_tables(conn)
        for rec in records:
            df = rec["df"]
            if df.empty:
                continue
            write_df = df[["open", "high", "low", "close", "volume"]].copy()
            write_df["symbol"] = rec["symbol"]
            write_df["source"] = rec.get("source", "akshare")
            write_df["trade_date"] = write_df.index
            write_df["updated_at"] = datetime.now()
            conn.execute("INSERT OR REPLACE INTO daily_kline BY NAME SELECT * FROM write_df")
            total += len(write_df)
    finally:
        conn.close()
    return total


def upsert_stock_info(symbol: str, name: str = None, market: str = None,
                      industry: str = None, listed_date: str = None) -> None:
    """更新或插入股票基本信息"""
    conn = get_connection()
    try:
        _ensure_tables(conn)
        conn.execute("""
            INSERT OR REPLACE INTO stock_info (symbol, name, market, industry, listed_date, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, [symbol, name, market, industry, listed_date])
    finally:
        conn.close()


def delete_kline(symbol: str, before_date: str = None) -> int:
    """
    删除某只股票的日线数据。

    参数:
        symbol: 股票代码
        before_date: 若指定，只删除该日期之前的数据

    返回:
        删除行数
    """
    conn = get_connection()
    try:
        if before_date:
            result = conn.execute(
                "DELETE FROM daily_kline WHERE symbol = ? AND trade_date < ?",
                [symbol, before_date]
            )
        else:
            result = conn.execute("DELETE FROM daily_kline WHERE symbol = ?", [symbol])
        return result.fetchall()[0][0] if result else 0
    finally:
        conn.close()


# ────────────────────────── 资金流向快照 ──────────────────────────

def insert_fund_flow_snapshot(df: pd.DataFrame, trade_date: str = None) -> int:
    """将每日资金流向快照写入 fund_flow_daily 表（upsert）。"""
    if df is None or df.empty:
        return 0
    conn = get_connection()
    try:
        _ensure_tables(conn)
        w = df.copy()
        w = w.rename(columns={
            "code": "symbol",
            "main_capital": "main_net",
        })
        if trade_date:
            w["trade_date"] = trade_date
        elif "trade_date" not in w.columns:
            w["trade_date"] = datetime.now().strftime("%Y-%m-%d")
        # Keep only needed columns
        needed = ["symbol", "trade_date", "price", "pct_change",
                   "turnover_rate", "capital_inflow", "capital_outflow",
                   "main_net", "turnover"]
        for c in needed:
            if c not in w.columns:
                w[c] = 0
        w = w[needed]
        w["updated_at"] = datetime.now()

        conn.execute("BEGIN")
        conn.execute("""
            INSERT OR REPLACE INTO fund_flow_daily
                (symbol, trade_date, price, pct_change, turnover_rate,
                 capital_inflow, capital_outflow, main_net, turnover, updated_at)
            SELECT symbol, trade_date::DATE, price, pct_change, turnover_rate,
                   capital_inflow, capital_outflow, main_net, turnover, updated_at
            FROM w
        """)
        conn.execute("COMMIT")
        return len(w)
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def get_fund_flow_history(symbol: str, limit: int = 120) -> pd.DataFrame:
    """
    读取单只股票的历史资金流向数据。
    返回: [trade_date, price, pct_change, turnover_rate,
            capital_inflow, capital_outflow, main_net, turnover]
    """
    conn = get_connection(read_only=True)
    try:
        df = conn.execute("""
            SELECT trade_date, price, pct_change, turnover_rate,
                   capital_inflow, capital_outflow, main_net, turnover
            FROM fund_flow_daily
            WHERE symbol = ?
            ORDER BY trade_date DESC
            LIMIT ?
        """, [symbol, limit]).df()
        if not df.empty:
            df["trade_date"] = pd.to_datetime(df["trade_date"])
            df = df.sort_values("trade_date")
        return df
    finally:
        conn.close()


def get_fund_flow_latest_date() -> str | None:
    """获取资金流向表中的最新日期"""
    conn = get_connection(read_only=True)
    try:
        r = conn.execute("SELECT MAX(trade_date) FROM fund_flow_daily").fetchone()
        return str(r[0]) if r and r[0] else None
    finally:
        conn.close()


def get_fund_flow_ranking(date: str = None, sort_by: str = "main_net",
                           ascending: bool = False, limit: int = 50) -> pd.DataFrame:
    """
    获取资金流向排名。date=None 取最新日期。
    sort_by: main_net / capital_inflow / turnover
    """
    conn = get_connection(read_only=True)
    try:
        if date is None:
            date = get_fund_flow_latest_date()
        if date is None:
            return pd.DataFrame()
        order_dir = "ASC" if ascending else "DESC"
        col = sort_by if sort_by in ("main_net", "capital_inflow", "turnover") else "main_net"
        df = conn.execute(f"""
            SELECT symbol, price, pct_change, turnover_rate,
                   capital_inflow, capital_outflow, main_net, turnover
            FROM fund_flow_daily
            WHERE trade_date = ?
            ORDER BY {col} {order_dir}
            LIMIT ?
        """, [date, limit]).df()
        # 补齐名称
        try:
            names = get_stock_name_map()
            df["name"] = df["symbol"].map(names).fillna("")
        except Exception:
            df["name"] = ""
        return df
    finally:
        conn.close()



_TARGET_PREFIXES = ("60", "00", "30", "688")


def is_target_stock(symbol: str) -> bool:
    """判断是否为四大板块目标股票（上海主板/深圳主板/创业板/科创板）"""
    return symbol.startswith(_TARGET_PREFIXES)


def delete_non_target_stocks() -> dict:
    """
    删除非目标板块的股票数据（北交所、B股、三板、基金等）。
    仅保留上海主板(60)、深圳主板(00)、创业板(30)、科创板(688)。

    返回: {"deleted_stocks": int, "deleted_rows": int}
    """
    conn = get_connection()
    try:
        r = conn.execute("""
            SELECT COUNT(DISTINCT symbol), COUNT(*)
            FROM daily_kline
            WHERE symbol NOT LIKE '60%'
              AND symbol NOT LIKE '00%'
              AND symbol NOT LIKE '30%'
              AND symbol NOT LIKE '688%'
        """).fetchone()
        deleted_stocks = r[0] if r else 0
        deleted_rows = r[1] if r else 0

        if deleted_rows > 0:
            conn.execute("""
                DELETE FROM daily_kline
                WHERE symbol NOT LIKE '60%'
                  AND symbol NOT LIKE '00%'
                  AND symbol NOT LIKE '30%'
                  AND symbol NOT LIKE '688%'
            """)
        return {"deleted_stocks": deleted_stocks, "deleted_rows": deleted_rows}
    finally:
        conn.close()


def get_board_stats() -> pd.DataFrame:
    """按板块统计数据库内股票数量和数据行数"""
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "daily_kline"):
            return pd.DataFrame()
        return conn.execute("""
            SELECT
                CASE
                    WHEN symbol LIKE '60%' THEN '上海主板'
                    WHEN symbol LIKE '00%' THEN '深主板'
                    WHEN symbol LIKE '30%' THEN '创业板'
                    WHEN symbol LIKE '688%' THEN '科创板'
                    WHEN symbol LIKE '8%' OR symbol LIKE '4%' OR symbol LIKE '9%' THEN '北交所'
                    ELSE '其他'
                END as board,
                COUNT(DISTINCT symbol) as stock_count,
                COUNT(*) as rows
            FROM daily_kline
            GROUP BY board
            ORDER BY stock_count DESC
        """).df()
    finally:
        conn.close()


# ────────────────────────── 查询操作 ──────────────────────────

def _table_exists(conn, table: str) -> bool:
    """检查表是否存在（兼容 read_only 连接）"""
    try:
        r = conn.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema='main' AND table_name=?", [table]
        ).fetchone()
        return r[0] > 0 if r else False
    except Exception:
        return False


def get_kline(symbol: str, start: str = None, end: str = None,
              source: str = None) -> pd.DataFrame:
    """
    从数据库查询单只股票的日线数据。

    参数:
        symbol: 股票代码
        start: 起始日期 "YYYY-MM-DD"（含）
        end:   结束日期 "YYYY-MM-DD"（含）
        source: 数据来源过滤

    返回:
        DataFrame，index 为 trade_date，列为 [open, high, low, close, volume]
    """
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "daily_kline"):
            return pd.DataFrame()

        where = ["symbol = ?"]
        params = [symbol]
        if start:
            where.append("trade_date >= ?")
            params.append(start)
        if end:
            where.append("trade_date <= ?")
            params.append(end)
        if source:
            where.append("source = ?")
            params.append(source)

        query = f"""
            SELECT trade_date, open, high, low, close, volume
            FROM daily_kline
            WHERE {' AND '.join(where)}
            ORDER BY trade_date
        """
        df = conn.execute(query, params).df()
        if df.empty:
            return pd.DataFrame()
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df = df.set_index("trade_date")
        return df
    finally:
        conn.close()


def get_kline_batch(symbols: list[str], start: str = None,
                    end: str = None) -> dict[str, pd.DataFrame]:
    """
    批量查询多只股票的日线数据。

    返回:
        {"600036": DataFrame, "000001": DataFrame, ...}
    """
    if not symbols:
        return {}

    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "daily_kline"):
            return {}
        placeholders = ",".join(["?"] * len(symbols))
        where = [f"symbol IN ({placeholders})"]
        params = list(symbols)
        if start:
            where.append("trade_date >= ?")
            params.append(start)
        if end:
            where.append("trade_date <= ?")
            params.append(end)

        query = f"""
            SELECT symbol, trade_date, open, high, low, close, volume
            FROM daily_kline
            WHERE {' AND '.join(where)}
            ORDER BY symbol, trade_date
        """
        df = conn.execute(query, params).df()
        if df.empty:
            return {}

        df["trade_date"] = pd.to_datetime(df["trade_date"])
        result = {}
        for sym, group in df.groupby("symbol"):
            g = group.set_index("trade_date")[["open", "high", "low", "close", "volume"]]
            result[sym] = g.sort_index()
        return result
    finally:
        conn.close()


def search_kline(symbols: list[str], start: str, end: str,
                 fields: list[str] = None) -> pd.DataFrame:
    """
    灵活查询接口：返回指定股票的指定字段，适合分析型查询。

    参数:
        symbols: 股票代码列表
        start/end: 日期范围
        fields: 需要的列，默认全部。支持: symbol, trade_date, open, high, low, close, volume

    返回:
        DataFrame（不设 index，方便 join/groupby）
    """
    if not symbols:
        return pd.DataFrame()

    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "daily_kline"):
            return pd.DataFrame()
        if fields:
            cols = ", ".join(f for f in fields if f in
                             ["symbol", "trade_date", "open", "high", "low", "close", "volume"])
        else:
            cols = "symbol, trade_date, open, high, low, close, volume"

        placeholders = ",".join(["?"] * len(symbols))
        query = f"""
            SELECT {cols}
            FROM daily_kline
            WHERE symbol IN ({placeholders})
              AND trade_date >= ?
              AND trade_date <= ?
            ORDER BY symbol, trade_date
        """
        df = conn.execute(query, list(symbols) + [start, end]).df()
        if not df.empty and "trade_date" in df.columns:
            df["trade_date"] = pd.to_datetime(df["trade_date"])
        return df
    finally:
        conn.close()


# ────────────────────────── 元数据查询 ──────────────────────────

def get_db_stats() -> dict:
    """获取数据库统计信息"""
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "daily_kline"):
            return {
                "stock_count": 0, "total_rows": 0,
                "min_date": None, "max_date": None,
                "sources": [], "db_size_mb": 0,
            }
        stats = {}

        # 股票数量
        r = conn.execute("SELECT COUNT(DISTINCT symbol) FROM daily_kline").fetchone()
        stats["stock_count"] = r[0] if r else 0

        # 总数据行数
        r = conn.execute("SELECT COUNT(*) FROM daily_kline").fetchone()
        stats["total_rows"] = r[0] if r else 0

        # 日期范围
        r = conn.execute(
            "SELECT MIN(trade_date), MAX(trade_date) FROM daily_kline"
        ).fetchone()
        stats["min_date"] = str(r[0]) if r and r[0] else None
        stats["max_date"] = str(r[1]) if r and r[1] else None

        # 数据源分布
        r = conn.execute(
            "SELECT source, COUNT(*) as cnt FROM daily_kline GROUP BY source ORDER BY cnt DESC"
        ).fetchall()
        stats["sources"] = [{"source": row[0], "count": row[1]} for row in r]

        # 数据库文件大小
        if DB_PATH.exists():
            stats["db_size_mb"] = round(DB_PATH.stat().st_size / (1024 * 1024), 2)
        else:
            stats["db_size_mb"] = 0

        return stats
    finally:
        conn.close()


def get_stocks_in_db() -> pd.DataFrame:
    """获取数据库中已有的股票列表及其数据范围"""
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "daily_kline"):
            return pd.DataFrame()
        query = """
            SELECT
                k.symbol,
                COALESCE(s.name, '') as name,
                COALESCE(s.market, '') as market,
                MIN(k.trade_date) as data_start,
                MAX(k.trade_date) as data_end,
                COUNT(*) as rows
            FROM daily_kline k
            LEFT JOIN stock_info s ON k.symbol = s.symbol
            GROUP BY k.symbol, s.name, s.market
            ORDER BY k.symbol
        """
        df = conn.execute(query).df()
        if not df.empty:
            for col in ["data_start", "data_end"]:
                df[col] = pd.to_datetime(df[col])
        return df
    finally:
        conn.close()


# ────────────────────────── 分析辅助 ──────────────────────────

def get_latest_trading_date() -> str | None:
    """获取数据库中最新的交易日期，返回 'YYYY-MM-DD'"""
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "daily_kline"):
            return None
        r = conn.execute("SELECT MAX(trade_date) FROM daily_kline").fetchone()
        return str(r[0]) if r and r[0] else None
    finally:
        conn.close()


def get_trading_date_range(n_back: int) -> tuple[str, str] | tuple[None, None]:
    """
    获取最近 N 个交易日的起止日期。

    参数:
        n_back: 往回取多少个交易日

    返回:
        (start_date, end_date) 或 (None, None)
    """
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "daily_kline"):
            return None, None
        r = conn.execute("""
            WITH dates AS (
                SELECT DISTINCT trade_date
                FROM daily_kline
                ORDER BY trade_date DESC
                LIMIT ?
            )
            SELECT MIN(trade_date), MAX(trade_date) FROM dates
        """, [n_back]).fetchone()
        if r and r[0]:
            return str(r[0]), str(r[1])
        return None, None
    finally:
        conn.close()


def get_all_symbols() -> list[str]:
    """获取数据库中所有股票代码列表"""
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "daily_kline"):
            return []
        r = conn.execute(
            "SELECT DISTINCT symbol FROM daily_kline ORDER BY symbol"
        ).fetchall()
        return [row[0] for row in r]
    finally:
        conn.close()


def get_stock_name_map() -> dict[str, str]:
    """获取数据库中所有有名称的股票代码→名称映射"""
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "stock_info"):
            return {}
        r = conn.execute(
            "SELECT symbol, name FROM stock_info WHERE name IS NOT NULL AND name != ''"
        ).fetchall()
        return {row[0]: row[1] for row in r if row[1]}
    finally:
        conn.close()


# ══════════════════════════════════════════
# 自选股 CRUD
# ══════════════════════════════════════════

def add_to_watchlist(symbol: str, name: str = "", note: str = "") -> bool:
    """添加/更新自选股"""
    conn = get_connection(read_only=False)
    try:
        conn.execute("""
            INSERT OR REPLACE INTO watchlist (symbol, name, note)
            VALUES (?, ?, ?)
        """, [str(symbol).strip().zfill(6), name, note])
        return True
    except Exception:
        return False
    finally:
        conn.close()


def remove_from_watchlist(symbol: str) -> bool:
    """从自选股移除"""
    conn = get_connection(read_only=False)
    try:
        conn.execute("DELETE FROM watchlist WHERE symbol = ?",
                     [str(symbol).strip().zfill(6)])
        return True
    except Exception:
        return False
    finally:
        conn.close()


def get_watchlist() -> pd.DataFrame:
    """获取全部自选股"""
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "watchlist"):
            return pd.DataFrame(columns=["symbol", "name", "added_at", "note"])
        return conn.execute(
            "SELECT symbol, name, added_at, note FROM watchlist ORDER BY added_at DESC"
        ).df()
    finally:
        conn.close()


def compute_daily_returns(symbols: list[str], start: str, end: str) -> pd.DataFrame:
    """
    计算多只股票的日收益率矩阵（收盘价 pct_change）。

    返回:
        DataFrame，index=date, columns=symbol, values=daily_return
    """
    df = search_kline(symbols, start, end, fields=["symbol", "trade_date", "close"])
    if df.empty:
        return pd.DataFrame()

    pivot = df.pivot(index="trade_date", columns="symbol", values="close")
    pivot = pivot.sort_index()
    returns = pivot.pct_change().dropna(how="all")
    return returns


def compute_correlation(symbols: list[str], start: str, end: str) -> pd.DataFrame:
    """
    计算多只股票的相关性矩阵。

    返回:
        DataFrame，index=symbol, columns=symbol, values=correlation
    """
    returns = compute_daily_returns(symbols, start, end)
    if returns.empty or len(returns) < 10:
        return pd.DataFrame()
    return returns.corr()
