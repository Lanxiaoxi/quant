"""DuckDB 行情存储层：建表、批量 upsert、基础查询。

存储决策：使用 DuckDB 原生列式表（单文件 market.duckdb），upsert 友好、
分析查询快；DESIGN.md 中的 Parquet 分区留给回测结果与未来的分钟数据。
"""
from __future__ import annotations

import threading
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from app.core.config import settings

_SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS trade_cal (
        exchange VARCHAR, cal_date DATE, is_open BOOLEAN, pretrade_date DATE,
        PRIMARY KEY (exchange, cal_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS stock_basic (
        ts_code VARCHAR PRIMARY KEY, symbol VARCHAR, name VARCHAR, area VARCHAR,
        industry VARCHAR, market VARCHAR, exchange VARCHAR, list_status VARCHAR,
        list_date DATE, delist_date DATE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS daily (
        ts_code VARCHAR, trade_date DATE,
        open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, pre_close DOUBLE,
        "change" DOUBLE, pct_chg DOUBLE, vol DOUBLE, amount DOUBLE,
        PRIMARY KEY (ts_code, trade_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS adj_factor (
        ts_code VARCHAR, trade_date DATE, adj_factor DOUBLE,
        PRIMARY KEY (ts_code, trade_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS daily_basic (
        ts_code VARCHAR, trade_date DATE, close DOUBLE,
        turnover_rate DOUBLE, turnover_rate_f DOUBLE, volume_ratio DOUBLE,
        pe DOUBLE, pe_ttm DOUBLE, pb DOUBLE, ps DOUBLE, ps_ttm DOUBLE,
        dv_ratio DOUBLE, dv_ttm DOUBLE,
        total_share DOUBLE, float_share DOUBLE, free_share DOUBLE,
        total_mv DOUBLE, circ_mv DOUBLE,
        PRIMARY KEY (ts_code, trade_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fund_daily (
        ts_code VARCHAR, trade_date DATE,
        open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, pre_close DOUBLE,
        "change" DOUBLE, pct_chg DOUBLE, vol DOUBLE, amount DOUBLE,
        PRIMARY KEY (ts_code, trade_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fund_nav (
        ts_code VARCHAR, nav_date DATE, unit_nav DOUBLE, accum_nav DOUBLE, adj_nav DOUBLE,
        PRIMARY KEY (ts_code, nav_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS index_daily (
        ts_code VARCHAR, trade_date DATE,
        open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, pre_close DOUBLE,
        "change" DOUBLE, pct_chg DOUBLE, vol DOUBLE, amount DOUBLE,
        PRIMARY KEY (ts_code, trade_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sync_log (
        table_name VARCHAR, last_date DATE, rows_synced INTEGER,
        status VARCHAR, synced_at TIMESTAMP
    )
    """,
]


class DuckDBStore:
    """线程安全的 DuckDB 单连接封装（单写者场景足够）。"""

    def __init__(self, path: Path | str | None = None, read_only: bool = False):
        settings.ensure_dirs()
        self._path = Path(path) if path else settings.duckdb_path
        self._lock = threading.Lock()
        self._con = duckdb.connect(str(self._path), read_only=read_only)
        if not read_only:
            self.init_schema()

    def init_schema(self) -> None:
        with self._lock:
            for stmt in _SCHEMA_STATEMENTS:
                self._con.execute(stmt)

    def table_columns(self, table: str) -> list[str]:
        with self._lock:
            rows = self._con.execute(f"PRAGMA table_info('{table}')").fetchall()
        return [r[1] for r in rows]

    def upsert(self, table: str, df: pd.DataFrame, key_cols: list[str]) -> int:
        """INSERT OR REPLACE 批量写入；列自动对齐表结构（取交集）。"""
        if df is None or df.empty:
            return 0
        cols = [c for c in self.table_columns(table) if c in df.columns]
        missing_keys = [k for k in key_cols if k not in cols]
        if missing_keys:
            raise ValueError(f"upsert {table}: 缺少主键列 {missing_keys}")
        aligned = df[cols].copy()
        col_list = ", ".join(f'"{c}"' for c in cols)
        with self._lock:
            self._con.register("_stage", aligned)
            try:
                self._con.execute(
                    f'INSERT OR REPLACE INTO "{table}" ({col_list}) SELECT {col_list} FROM _stage'
                )
            finally:
                self._con.unregister("_stage")
        return len(aligned)

    def query(self, sql: str, params: list[Any] | None = None) -> pd.DataFrame:
        with self._lock:
            return self._con.execute(sql, params or []).df()

    def max_date(self, table: str, date_col: str) -> date | None:
        df = self.query(f'SELECT MAX("{date_col}") AS d FROM "{table}"')
        val = df["d"].iloc[0]
        if val is None or pd.isna(val):
            return None
        return val.date() if hasattr(val, "date") else val

    def count(self, table: str) -> int:
        df = self.query(f'SELECT COUNT(*) AS n FROM "{table}"')
        return int(df["n"].iloc[0])

    def log_sync(self, table: str, last_date: date | None, rows: int, status: str) -> None:
        with self._lock:
            self._con.execute(
                "INSERT INTO sync_log (table_name, last_date, rows_synced, status, synced_at) VALUES (?, ?, ?, ?, now())",
                [table, last_date, rows, status],
            )

    def close(self) -> None:
        with self._lock:
            self._con.close()
