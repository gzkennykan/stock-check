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

# ── DuckDB 1.5.4 兼容：.df() 对空结果可能返回 None ──
import duckdb
_original_df = duckdb.DuckDBPyRelation.df
def _safe_df(self, *args, **kwargs):
    result = _original_df(self, *args, **kwargs)
    return result if result is not None else pd.DataFrame()
duckdb.DuckDBPyRelation.df = _safe_df


# ────────────────────────── 连接管理 ──────────────────────────

import atexit
import sys as _sys

_DB_CONN = None


class _SharedConnection:
    """DuckDB 单例连接包装。

    关键：不定义 execute() —— 让 __getattr__ 返回原始连接的 bound method，
    这样 DuckDB 的 DataFrame 自动注册（依赖 Python 调用栈）不会被包装层打断。

    进程退出时通过 atexit 自动关闭底层连接，确保 WAL 被 checkpoint 且文件锁释放。
    """

    def __init__(self, raw):
        self.__dict__["_raw"] = raw
        self.__dict__["_closed"] = False

    def close(self):
        """下游代码调用 close() 时为 no-op（保持单例存活）。
        真正的关闭只在 _do_close() 中执行（由 atexit 触发）。"""
        pass

    def _do_close(self):
        """真正关闭底层连接——仅由 atexit 调用"""
        if not self._closed:
            try:
                self._raw.close()
            except Exception:
                pass
            self.__dict__["_closed"] = True

    def __getattr__(self, name):
        return getattr(self._raw, name)

    def __setattr__(self, name, value):
        if name in ("_raw", "_closed"):
            self.__dict__[name] = value
        else:
            setattr(self._raw, name, value)


def _cleanup_connection():
    """atexit 回调：正常关闭 DuckDB 连接，释放文件锁"""
    global _DB_CONN
    if _DB_CONN is not None:
        _DB_CONN._do_close()
        _DB_CONN = None


atexit.register(_cleanup_connection)


def get_connection(read_only: bool = False):
    """获取 DuckDB 单例连接（同一进程内共享，避免多 Tab 锁冲突）。

    始终以读写模式打开，避免 DuckDB 检测到同一文件不同配置而报错。
    进程退出时通过 atexit 自动 checkpoint + 关闭，确保下次启动不受锁文件影响。
    """
    global _DB_CONN
    import duckdb

    if _DB_CONN is not None:
        return _DB_CONN

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
            amount      DOUBLE,
            source      VARCHAR(20)   DEFAULT 'akshare',
            updated_at  TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (symbol, trade_date)
        )
    """)
    # 迁移：已有数据库可能缺少 amount 列
    try:
        conn.execute("ALTER TABLE daily_kline ADD COLUMN amount DOUBLE")
    except Exception:
        pass  # 列已存在则忽略
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

    # ── 行业板块实时行情 ──
    conn.execute("""
        CREATE TABLE IF NOT EXISTS industry_spot (
            name            VARCHAR(50)  PRIMARY KEY,
            pct_change      DOUBLE,
            fund_flow       DOUBLE,
            turnover        DOUBLE,
            up_count        INTEGER,
            down_count      INTEGER,
            snapshot_date   DATE         NOT NULL,
            updated_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── 行业成分股 ──
    conn.execute("""
        CREATE TABLE IF NOT EXISTS industry_stocks (
            industry_name   VARCHAR(100) NOT NULL,
            symbol          VARCHAR(10)  NOT NULL,
            stock_name      VARCHAR(50),
            updated_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (industry_name, symbol)
        )
    """)

    # ── 财务指标（按 stock + report_period 唯一） ──
    conn.execute("""
        CREATE TABLE IF NOT EXISTS financial_data (
            symbol          VARCHAR(10)  NOT NULL,
            report_period   VARCHAR(20)  NOT NULL,
            roe             DOUBLE,
            roa             DOUBLE,
            gross_margin    DOUBLE,
            net_margin      DOUBLE,
            revenue_yoy     DOUBLE,
            profit_yoy      DOUBLE,
            debt_ratio      DOUBLE,
            eps             DOUBLE,
            bps             DOUBLE,
            current_ratio   DOUBLE,
            quick_ratio     DOUBLE,
            total_assets    DOUBLE,
            revenue         DOUBLE,
            net_profit      DOUBLE,
            updated_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (symbol, report_period)
        )
    """)

    # ── 涨停板池（pool_type: zt/strong/broken/previous） ──
    conn.execute("""
        CREATE TABLE IF NOT EXISTS zt_pool_daily (
            symbol          VARCHAR(10)  NOT NULL,
            trade_date      DATE         NOT NULL,
            pool_type       VARCHAR(10)  NOT NULL,
            name            VARCHAR(50),
            price           DOUBLE,
            pct_change      DOUBLE,
            turnover_rate   DOUBLE,
            industry        VARCHAR(50),
            seal_fund       DOUBLE,
            zt_time         VARCHAR(10),
            break_count     INTEGER,
            consecutive_days INTEGER,
            updated_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (symbol, trade_date, pool_type)
        )
    """)

    # ── 龙虎榜日数据 ──
    conn.execute("""
        CREATE TABLE IF NOT EXISTS lhb_daily (
            symbol          VARCHAR(10)  NOT NULL,
            trade_date      DATE         NOT NULL,
            name            VARCHAR(50),
            close           DOUBLE,
            pct_change      DOUBLE,
            turnover        DOUBLE,
            net_buy         DOUBLE,
            inst_buy        DOUBLE,
            inst_sell       DOUBLE,
            accum_buy       DOUBLE,
            accum_sell      DOUBLE,
            buy_seat_count  INTEGER,
            sell_seat_count INTEGER,
            onboard_days    INTEGER,
            reason          VARCHAR(200),
            updated_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (symbol, trade_date)
        )
    """)

    # ── 融资融券 ──
    conn.execute("""
        CREATE TABLE IF NOT EXISTS margin_data (
            trade_date      DATE         NOT NULL,
            market          VARCHAR(10)  NOT NULL,
            margin_balance  DOUBLE,
            margin_buy      DOUBLE,
            short_balance   DOUBLE,
            short_sell      DOUBLE,
            net_margin      DOUBLE,
            updated_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (trade_date, market)
        )
    """)

    # ── 北向资金日数据 ──
    conn.execute("""
        CREATE TABLE IF NOT EXISTS northbound_flow (
            trade_date      DATE         PRIMARY KEY,
            total_buy       DOUBLE,
            total_sell      DOUBLE,
            net_flow        DOUBLE,
            sh_buy          DOUBLE,
            sh_sell         DOUBLE,
            sz_buy          DOUBLE,
            sz_sell         DOUBLE,
            updated_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── 盈利能力快照 ──
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stock_profitability (
            symbol          VARCHAR(10)  PRIMARY KEY,
            name            VARCHAR(50),
            roe             DOUBLE,
            net_profit_growth DOUBLE,
            gross_margin    DOUBLE,
            net_margin      DOUBLE,
            revenue_growth  DOUBLE,
            eps             DOUBLE,
            bps             DOUBLE,
            report_date     VARCHAR(20),
            updated_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── 股票新闻 ──
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stock_news (
            symbol          VARCHAR(10)  NOT NULL,
            pub_date        DATE         NOT NULL,
            title           VARCHAR(500),
            source          VARCHAR(100),
            sentiment_score DOUBLE,
            updated_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (symbol, pub_date, title)
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_fd_symbol ON financial_data(symbol)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_zt_date ON zt_pool_daily(trade_date)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_lhb_date ON lhb_daily(trade_date)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_is_industry ON industry_stocks(industry_name)
    """)


# ────────────────────────── 写入操作 ──────────────────────────

def insert_kline(symbol: str, df: pd.DataFrame, source: str = "akshare") -> int:
    """
    将一只股票的日线数据写入 daily_kline 表（upsert 语义：主键冲突时更新）。

    参数:
        symbol: 股票代码
        df: 包含 [open, high, low, close, volume] 的 DataFrame，index 为 date；
            可选含 amount（成交额/元，TDX 源有，akshare 源无）
        source: 数据来源

    返回:
        写入行数
    """
    if df.empty:
        return 0

    conn = get_connection()
    try:
        _ensure_tables(conn)

        # 准备写入数据（含 amount 如果存在）
        base_cols = ["open", "high", "low", "close", "volume"]
        if "amount" in df.columns:
            base_cols.append("amount")
        write_df = df[base_cols].copy()
        # 兼容无 amount 的数据源（akshare），SQL 引用 amount 需要有此列
        if "amount" not in write_df.columns:
            write_df["amount"] = None
        write_df["symbol"] = symbol
        write_df["source"] = source
        write_df["trade_date"] = write_df.index  # index 是 date
        write_df["updated_at"] = datetime.now()

        # DuckDB 原生 upsert: INSERT OR REPLACE
        conn.execute("BEGIN")
        conn.execute("""
            INSERT OR REPLACE INTO daily_kline
                (symbol, trade_date, open, high, low, close, volume, amount, source, updated_at)
            SELECT symbol, trade_date, open, high, low, close, volume, amount, source, updated_at
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
            base_cols = ["open", "high", "low", "close", "volume"]
            if "amount" in df.columns:
                base_cols.append("amount")
            write_df = df[base_cols].copy()
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


def get_common_trading_date() -> str | None:
    """返回 daily_kline 和 fund_flow_daily 两个表都有数据的最近日期。

    用于资金排名等需要两个数据源对齐的场景。
    如果任一表为空或没有交集日期，返回 None。
    """
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "daily_kline") or not _table_exists(conn, "fund_flow_daily"):
            return None
        r = conn.execute("""
            SELECT k.trade_date
            FROM daily_kline k
            INNER JOIN fund_flow_daily f ON f.trade_date = k.trade_date
            GROUP BY k.trade_date
            ORDER BY k.trade_date DESC
            LIMIT 1
        """).fetchone()
        return str(r[0]) if r and r[0] else None
    finally:
        conn.close()


def today_or_latest_trading_day() -> str:
    """
    返回今天或最近交易日（用于周末/节假日自动回退）。

    周一至周五：返回今天的日期
    周六/周日：返回数据库中最近的交易日（通常是周五）
    如果数据库为空，退回上周五。
    """
    from datetime import date, timedelta
    today = date.today()
    weekday = today.weekday()  # 0=Mon ... 6=Sun

    if weekday < 5:
        return today.strftime("%Y-%m-%d")

    # 周末：回退到最近一个交易日
    latest_db = get_latest_trading_date()
    if latest_db:
        return latest_db

    # 数据库为空时退回上周五
    days_since_friday = weekday - 4  # Sat=5→1, Sun=6→2
    last_friday = today - timedelta(days=days_since_friday)
    return last_friday.strftime("%Y-%m-%d")


def get_latest_date_for_stock(symbol: str) -> str | None:
    """获取单只股票在数据库中的最新交易日期，返回 'YYYY-MM-DD'

    与 get_latest_trading_date() 的区别：该函数只查指定 symbol，
    用于增量同步时按每只股票各自的最新日期判断是否需要导入。
    """
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "daily_kline"):
            return None
        r = conn.execute(
            "SELECT MAX(trade_date) FROM daily_kline WHERE symbol = ?", [symbol]
        ).fetchone()
        return str(r[0]) if r and r[0] else None
    finally:
        conn.close()


def get_all_latest_dates() -> dict[str, str]:
    """批量获取所有股票的最新交易日期，返回 {symbol: 'YYYY-MM-DD'}

    一次 SQL 查询替代数千次单股查询，用于增量同步时内存过滤。
    """
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "daily_kline"):
            return {}
        df = conn.execute(
            "SELECT symbol, MAX(trade_date) AS latest FROM daily_kline GROUP BY symbol"
        ).fetchdf()
        return {
            row["symbol"]: str(row["latest"])
            for _, row in df.iterrows()
            if row["latest"] is not None
        }
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
    """获取数据库中所有有名称的股票代码→名称映射。
    优先从 stock_info 表，若为空则回退到实时行情缓存（screener）。"""
    conn = get_connection(read_only=True)
    try:
        if _table_exists(conn, "stock_info"):
            r = conn.execute(
                "SELECT symbol, name FROM stock_info WHERE name IS NOT NULL AND name != ''"
            ).fetchall()
            if r:
                return {row[0]: row[1] for row in r if row[1]}
    finally:
        conn.close()

    # 回退：从 screener 的实时行情 CSV 缓存中获取代码→名称映射
    try:
        from .screener import get_stock_list
        df = get_stock_list()
        if not df.empty and "code" in df.columns and "name" in df.columns:
            codes = df["code"].astype(str).str.zfill(6)
            return dict(zip(codes, df["name"]))
    except Exception:
        pass
    return {}


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


# ══════════════════════════════════════════════════════════════════
# 数据策略统一：新增表的 CRUD 函数
# ══════════════════════════════════════════════════════════════════

# ── 行业板块实时行情 ──

def insert_industry_spot(df: pd.DataFrame, snapshot_date: str) -> int:
    """将行业实时行情写入 DB（upsert 语义）"""
    conn = get_connection(read_only=False)
    try:
        _ensure_tables(conn)
        df = df.copy()
        df["snapshot_date"] = snapshot_date
        cols = {}
        for c in df.columns:
            if "名称" in str(c) or "name" in str(c).lower():
                cols[c] = "name"
            elif "涨跌幅" in str(c) or "pct" in str(c).lower():
                cols[c] = "pct_change"
            elif "资金" in str(c) or "flow" in str(c).lower():
                cols[c] = "fund_flow"
            elif "成交额" in str(c) or "turnover" in str(c).lower():
                cols[c] = "turnover"
        df = df.rename(columns=cols)
        needed = ["name", "snapshot_date"]
        for c in ["pct_change", "fund_flow", "turnover"]:
            if c in df.columns:
                needed.append(c)
        df = df[[c for c in needed if c in df.columns]]
        conn.execute("DELETE FROM industry_spot WHERE snapshot_date = ?", [snapshot_date])
        conn.register("write_df", df)
        conn.execute("INSERT INTO industry_spot SELECT * FROM write_df")
        conn.unregister("write_df")
        return len(df)
    finally:
        conn.close()


def get_industry_spot(snapshot_date: str = None) -> pd.DataFrame:
    """从 DB 读取行业实时行情"""
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "industry_spot"):
            return pd.DataFrame()
        if snapshot_date:
            return conn.execute(
                "SELECT * FROM industry_spot WHERE snapshot_date = ? ORDER BY pct_change DESC",
                [snapshot_date]
            ).df()
        return conn.execute(
            "SELECT * FROM industry_spot WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM industry_spot) ORDER BY pct_change DESC"
        ).df()
    finally:
        conn.close()


def get_industry_spot_latest_date() -> str | None:
    """获取行业行情最新快照日期"""
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "industry_spot"):
            return None
        r = conn.execute("SELECT MAX(snapshot_date) FROM industry_spot").fetchone()
        return str(r[0]) if r and r[0] else None
    finally:
        conn.close()


# ── 行业成分股 ──

def insert_industry_stocks(industry_name: str, stocks: list[dict]) -> int:
    """写入某行业成分股列表到 DB"""
    conn = get_connection(read_only=False)
    try:
        _ensure_tables(conn)
        df = pd.DataFrame(stocks)
        if df.empty:
            return 0
        df["industry_name"] = industry_name
        if "code" in df.columns and "symbol" not in df.columns:
            df["symbol"] = df["code"].astype(str).str.strip()
        if "name" in df.columns and "stock_name" not in df.columns:
            df["stock_name"] = df["name"].astype(str)
        cols = ["industry_name", "symbol"]
        if "stock_name" in df.columns:
            cols.append("stock_name")
        df = df[[c for c in cols if c in df.columns]]
        conn.execute("DELETE FROM industry_stocks WHERE industry_name = ?", [industry_name])
        conn.register("write_df", df)
        conn.execute("INSERT INTO industry_stocks SELECT * FROM write_df")
        conn.unregister("write_df")
        return len(df)
    finally:
        conn.close()


def get_industry_stocks_db(industry_name: str = None) -> pd.DataFrame:
    """从 DB 读取行业成分股。industry_name=None 返回全部行业列表"""
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "industry_stocks"):
            return pd.DataFrame()
        if industry_name:
            return conn.execute(
                "SELECT symbol, stock_name, industry_name FROM industry_stocks WHERE industry_name = ?",
                [industry_name]
            ).df()
        return conn.execute(
            "SELECT DISTINCT industry_name FROM industry_stocks ORDER BY industry_name"
        ).df()
    finally:
        conn.close()


def is_industry_stocks_cached(industry_name: str) -> bool:
    """判断某个行业的成分股是否已缓存"""
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "industry_stocks"):
            return False
        r = conn.execute(
            "SELECT COUNT(*) FROM industry_stocks WHERE industry_name = ?", [industry_name]
        ).fetchone()
        return r[0] > 0 if r else False
    finally:
        conn.close()


# ── 财务指标 ──

def insert_financial_data(df: pd.DataFrame) -> int:
    """写入财务指标到 DB（按 symbol + report_period 去重追加）"""
    conn = get_connection(read_only=False)
    try:
        _ensure_tables(conn)
        if df.empty:
            return 0
        rename = {}
        for c in df.columns:
            cn = str(c).lower().replace(" ", "_")
            for std in ["symbol", "report_period", "roe", "roa", "gross_margin",
                         "net_margin", "revenue_yoy", "profit_yoy", "debt_ratio",
                         "eps", "bps", "current_ratio", "quick_ratio",
                         "total_assets", "revenue", "net_profit"]:
                if cn == std or cn.replace("_", "") == std.replace("_", ""):
                    rename[c] = std
                    break
        df = df.rename(columns=rename)
        df["symbol"] = df["symbol"].astype(str).str.strip()
        existing = set(conn.execute("SELECT symbol, report_period FROM financial_data").fetchall())
        if existing:
            keys = pd.DataFrame(existing, columns=["symbol", "report_period"])
            keys["symbol"] = keys["symbol"].astype(str)
            df = df.merge(keys, on=["symbol", "report_period"], how="left", indicator=True)
            df = df[df["_merge"] == "left_only"].drop(columns=["_merge"])
        if df.empty:
            return 0
        conn.register("write_df", df)
        conn.execute("INSERT INTO financial_data SELECT * FROM write_df")
        conn.unregister("write_df")
        return len(df)
    finally:
        conn.close()


def get_financial_data(symbol: str, n_periods: int = 4) -> pd.DataFrame:
    """从 DB 读取某只股票最近 N 期财务数据"""
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "financial_data"):
            return pd.DataFrame()
        return conn.execute("""
            SELECT * FROM financial_data
            WHERE symbol = ?
            ORDER BY report_period DESC
            LIMIT ?
        """, [symbol, n_periods]).df()
    finally:
        conn.close()


def get_latest_financial(symbol: str) -> dict | None:
    """获取某只股票最新一期财务数据（返回 dict 方便 get()）"""
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "financial_data"):
            return None
        r = conn.execute(
            "SELECT * FROM financial_data WHERE symbol = ? ORDER BY report_period DESC LIMIT 1",
            [symbol]
        ).fetchone()
        if r is None:
            return None
        cols = [d[0] for d in conn.execute("DESCRIBE financial_data").fetchall()]
        return dict(zip(cols, r))
    finally:
        conn.close()


# ── 涨停板池 ──

def insert_zt_pool(df: pd.DataFrame, trade_date: str, pool_type: str) -> int:
    """写入涨停板池数据（先删当天同类型再插入）"""
    conn = get_connection(read_only=False)
    try:
        _ensure_tables(conn)
        if df.empty:
            return 0
        df = df.copy()
        df["trade_date"] = pd.to_datetime(trade_date).date()
        df["pool_type"] = pool_type
        conn.execute("DELETE FROM zt_pool_daily WHERE trade_date = ? AND pool_type = ?",
                      [trade_date, pool_type])
        conn.register("write_df", df)
        cols = conn.execute("SELECT * FROM zt_pool_daily LIMIT 0").description
        existing_cols = [d[0] for d in cols]
        insert_cols = [c for c in df.columns if c in existing_cols]
        conn.execute(f"INSERT INTO zt_pool_daily ({', '.join(insert_cols)}) SELECT {', '.join(insert_cols)} FROM write_df")
        conn.unregister("write_df")
        return len(df)
    finally:
        conn.close()


def get_zt_pool_db(trade_date: str = None, pool_type: str = None) -> pd.DataFrame:
    """从 DB 读取涨停板池"""
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "zt_pool_daily"):
            return pd.DataFrame()
        if trade_date is None:
            r = conn.execute("SELECT MAX(trade_date) FROM zt_pool_daily").fetchone()
            if r is None or r[0] is None:
                return pd.DataFrame()
            trade_date = str(r[0])
        if pool_type:
            return conn.execute(
                "SELECT * FROM zt_pool_daily WHERE trade_date = ? AND pool_type = ? ORDER BY pct_change DESC",
                [trade_date, pool_type]
            ).df()
        return conn.execute(
            "SELECT * FROM zt_pool_daily WHERE trade_date = ? ORDER BY pool_type, pct_change DESC",
            [trade_date]
        ).df()
    finally:
        conn.close()


# ── 龙虎榜 ──

def insert_lhb_daily(df: pd.DataFrame) -> int:
    """写入龙虎榜日数据（去重追加）"""
    conn = get_connection(read_only=False)
    try:
        _ensure_tables(conn)
        if df.empty:
            return 0
        existing = set(conn.execute("SELECT symbol, trade_date FROM lhb_daily").fetchall())
        if existing:
            keys = pd.DataFrame(existing, columns=["symbol", "trade_date"])
            keys["symbol"] = keys["symbol"].astype(str)
            df = df.merge(keys, on=["symbol", "trade_date"], how="left", indicator=True)
            df = df[df["_merge"] == "left_only"].drop(columns=["_merge"])
        if df.empty:
            return 0
        conn.register("write_df", df)
        conn.execute("INSERT INTO lhb_daily SELECT * FROM write_df")
        conn.unregister("write_df")
        return len(df)
    finally:
        conn.close()


def get_lhb_daily_db(trade_date: str = None) -> pd.DataFrame:
    """从 DB 读取龙虎榜日数据"""
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "lhb_daily"):
            return pd.DataFrame()
        if trade_date is None:
            r = conn.execute("SELECT MAX(trade_date) FROM lhb_daily").fetchone()
            if r is None or r[0] is None:
                return pd.DataFrame()
            trade_date = str(r[0])
        return conn.execute(
            "SELECT * FROM lhb_daily WHERE trade_date = ?", [trade_date]
        ).df()
    finally:
        conn.close()


# ── 融资融券 ──

def insert_margin_data(df: pd.DataFrame) -> int:
    """写入融资融券数据（去重追加）"""
    conn = get_connection(read_only=False)
    try:
        _ensure_tables(conn)
        if df.empty:
            return 0
        existing = set(conn.execute("SELECT trade_date, market FROM margin_data").fetchall())
        if existing:
            keys = pd.DataFrame(existing, columns=["trade_date", "market"])
            df = df.merge(keys, on=["trade_date", "market"], how="left", indicator=True)
            df = df[df["_merge"] == "left_only"].drop(columns=["_merge"])
        if df.empty:
            return 0
        conn.register("write_df", df)
        conn.execute("INSERT INTO margin_data SELECT * FROM write_df")
        conn.unregister("write_df")
        return len(df)
    finally:
        conn.close()


def get_margin_data_db(market: str = None, n_days: int = 60) -> pd.DataFrame:
    """从 DB 读取融资融券数据"""
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "margin_data"):
            return pd.DataFrame()
        if market:
            return conn.execute("""
                SELECT * FROM margin_data WHERE market = ?
                ORDER BY trade_date DESC LIMIT ?
            """, [market, n_days]).df()
        return conn.execute("""
            SELECT * FROM margin_data ORDER BY trade_date DESC LIMIT ?
        """, [n_days]).df()
    finally:
        conn.close()


def is_margin_cached(date: str = None) -> bool:
    """判断是否有当天的融资融券数据"""
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "margin_data"):
            return False
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        r = conn.execute("SELECT COUNT(*) FROM margin_data WHERE trade_date = ?", [date]).fetchone()
        return r[0] > 0 if r else False
    finally:
        conn.close()


# ── 北向资金 ──

def insert_northbound_flow(df: pd.DataFrame) -> int:
    """写入北向资金日数据（去重追加）"""
    conn = get_connection(read_only=False)
    try:
        _ensure_tables(conn)
        if df.empty:
            return 0
        existing = conn.execute("SELECT trade_date FROM northbound_flow").fetchall()
        if existing:
            existing_dates = {str(r[0]) for r in existing}
            df = df[~df["trade_date"].astype(str).isin(existing_dates)]
        if df.empty:
            return 0
        conn.register("write_df", df)
        conn.execute("INSERT INTO northbound_flow SELECT * FROM write_df")
        conn.unregister("write_df")
        return len(df)
    finally:
        conn.close()


def get_northbound_flow_db(n_days: int = 200) -> pd.DataFrame:
    """从 DB 读取北向资金历史"""
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "northbound_flow"):
            return pd.DataFrame()
        return conn.execute(
            "SELECT * FROM northbound_flow ORDER BY trade_date DESC LIMIT ?", [n_days]
        ).df()
    finally:
        conn.close()


# ── 盈利能力快照 ──

def insert_stock_profitability(df: pd.DataFrame) -> int:
    """写入全市场盈利能力快照（全量替换）"""
    conn = get_connection(read_only=False)
    try:
        _ensure_tables(conn)
        if df.empty:
            return 0
        conn.execute("DELETE FROM stock_profitability")
        conn.register("write_df", df)
        cols = conn.execute("SELECT * FROM stock_profitability LIMIT 0").description
        existing_cols = [d[0] for d in cols]
        insert_cols = [c for c in df.columns if c in existing_cols]
        conn.execute(f"INSERT INTO stock_profitability ({', '.join(insert_cols)}) SELECT {', '.join(insert_cols)} FROM write_df")
        conn.unregister("write_df")
        return len(df)
    finally:
        conn.close()


def get_profitability_db() -> pd.DataFrame:
    """从 DB 读取盈利能力快照"""
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "stock_profitability"):
            return pd.DataFrame()
        return conn.execute("SELECT * FROM stock_profitability").df()
    finally:
        conn.close()


def is_profitability_fresh(max_age_hours: int = 4) -> bool:
    """判断盈利能力数据是否仍在有效期内"""
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "stock_profitability"):
            return False
        r = conn.execute("SELECT MAX(updated_at) FROM stock_profitability").fetchone()
        if r is None or r[0] is None:
            return False
        age = (datetime.now() - r[0]).total_seconds() / 3600
        return age < max_age_hours
    finally:
        conn.close()


# ── 股票新闻 ──

def insert_stock_news(df: pd.DataFrame) -> int:
    """写入股票新闻（去重追加）"""
    conn = get_connection(read_only=False)
    try:
        _ensure_tables(conn)
        if df.empty:
            return 0
        existing = set(conn.execute("SELECT symbol, pub_date, title FROM stock_news").fetchall())
        if existing:
            keys = pd.DataFrame(existing, columns=["symbol", "pub_date", "title"])
            keys["symbol"] = keys["symbol"].astype(str)
            df = df.merge(keys, on=["symbol", "pub_date", "title"], how="left", indicator=True)
            df = df[df["_merge"] == "left_only"].drop(columns=["_merge"])
        if df.empty:
            return 0
        conn.register("write_df", df)
        conn.execute("INSERT INTO stock_news SELECT * FROM write_df")
        conn.unregister("write_df")
        return len(df)
    finally:
        conn.close()


def get_stock_news_db(symbol: str, n_days: int = 30) -> pd.DataFrame:
    """从 DB 读取股票新闻"""
    conn = get_connection(read_only=True)
    try:
        if not _table_exists(conn, "stock_news"):
            return pd.DataFrame()
        from datetime import datetime, timedelta
        cutoff = (datetime.now() - timedelta(days=n_days)).strftime("%Y-%m-%d")
        return conn.execute("""
            SELECT * FROM stock_news
            WHERE symbol = ? AND pub_date >= ?
            ORDER BY pub_date DESC
        """, [symbol, cutoff]).df()
    finally:
        conn.close()
