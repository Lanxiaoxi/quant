"""行情数据同步：全量回填 + 每日增量（DESIGN.md 5.1）。

核心策略：
- 按 trade_date 一次拉全市场快照（tushare 单日全市场接口），每张表每天仅 1 次调用；
- 增量同步以库内最大日期 +1 为起点；
- 每次同步写入 sync_log；失败单表隔离，不影响其他表。
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Callable

import pandas as pd

from app.data.calendar import TradeCalendar
from app.data.store import DuckDBStore
from app.data.tushare_client import TushareClient

log = logging.getLogger(__name__)

# 首次回填默认起点（全量历史约 4000 个交易日/表，按 90 次/分钟节流约 45 分钟/表）
DEFAULT_BACKFILL_START = date(2010, 1, 1)

# 表配置：tushare 接口、日期列、主键、按日查询的参数名
TABLE_SPECS: dict[str, dict] = {
    "daily":       dict(api="daily",       date_col="trade_date", keys=["ts_code", "trade_date"], day_param="trade_date"),
    "adj_factor":  dict(api="adj_factor",  date_col="trade_date", keys=["ts_code", "trade_date"], day_param="trade_date"),
    "daily_basic": dict(api="daily_basic", date_col="trade_date", keys=["ts_code", "trade_date"], day_param="trade_date"),
    "fund_daily":  dict(api="fund_daily",  date_col="trade_date", keys=["ts_code", "trade_date"], day_param="trade_date"),
    "index_daily": dict(api="index_daily", date_col="trade_date", keys=["ts_code", "trade_date"], day_param="trade_date"),
    # fund_nav 单日全市场约 2.7 万行，超过 tushare 默认返回上限（10500），必须分页拉取
    "fund_nav":    dict(api="fund_nav",    date_col="nav_date",   keys=["ts_code", "nav_date"],   day_param="nav_date",
                        paginate=True, page_size=6000),
}


def _fmt(d: date) -> str:
    return d.strftime("%Y%m%d")


def _to_date_col(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, format="%Y%m%d", errors="coerce").dt.date


class DataSyncer:
    def __init__(self, client: TushareClient, store: DuckDBStore):
        self._client = client
        self._store = store
        self._calendar = TradeCalendar(store)

    # ---------- 基础表 ----------

    def sync_trade_cal(self, start: date, end: date) -> int:
        df = self._client.query("trade_cal", exchange="SSE", start_date=_fmt(start), end_date=_fmt(end))
        if df.empty:
            return 0
        df = df[["exchange", "cal_date", "is_open", "pretrade_date"]].copy()
        df["cal_date"] = _to_date_col(df["cal_date"])
        df["pretrade_date"] = _to_date_col(df["pretrade_date"])
        df["is_open"] = df["is_open"].astype(bool)
        return self._store.upsert("trade_cal", df, ["exchange", "cal_date"])

    def sync_stock_basic(self) -> int:
        frames = []
        # L 上市 / D 退市 / P 暂停上市，全量保留以支持历史回测
        for status in ("L", "D", "P"):
            df = self._client.query(
                "stock_basic",
                list_status=status,
                fields="ts_code,symbol,name,area,industry,market,exchange,list_status,list_date,delist_date",
            )
            if not df.empty:
                frames.append(df)
        if not frames:
            return 0
        df = pd.concat(frames, ignore_index=True)
        df["list_date"] = _to_date_col(df["list_date"])
        df["delist_date"] = _to_date_col(df["delist_date"])
        return self._store.upsert("stock_basic", df, ["ts_code"])

    # ---------- 按日快照表 ----------

    def _fetch_one_day(self, spec: dict, d: date) -> pd.DataFrame:
        """拉取单日全市场快照；paginate=True 的表（fund_nav）循环 offset 分页直到取完。"""
        if not spec.get("paginate"):
            return self._client.query(spec["api"], **{spec["day_param"]: _fmt(d)})
        frames, offset, page_size = [], 0, spec["page_size"]
        while True:
            page = self._client.query(spec["api"], limit=page_size, offset=offset,
                                      **{spec["day_param"]: _fmt(d)})
            if page.empty:
                break
            frames.append(page)
            if len(page) < page_size:
                break
            offset += page_size
        if not frames:
            return pd.DataFrame()
        df = pd.concat(frames, ignore_index=True)
        return df.drop_duplicates(subset=spec["keys"], keep="last")

    def sync_table_by_days(
        self,
        name: str,
        start: date,
        end: date,
        progress: Callable[[str, int, int], None] | None = None,
    ) -> int:
        """按交易日逐日拉全市场快照。trade_cal 必须先同步。"""
        spec = TABLE_SPECS[name]
        days = self._calendar.open_days(start, end)
        if not days:
            log.info("%s: %s ~ %s 无交易日", name, start, end)
            return 0
        total_rows, last_day = 0, None
        for i, d in enumerate(days, 1):
            df = self._fetch_one_day(spec, d)
            if not df.empty:
                df = df.copy()
                df[spec["date_col"]] = _to_date_col(df[spec["date_col"]])
                total_rows += self._store.upsert(name, df, spec["keys"])
                last_day = d
            if progress:
                progress(name, i, len(days))
            elif i % 250 == 0 or i == len(days):
                log.info("%s: %d/%d 天，已写入 %d 行", name, i, len(days), total_rows)
        self._store.log_sync(name, last_day, total_rows, "ok")
        return total_rows

    # ---------- 入口 ----------

    def backfill(
        self,
        start: date = DEFAULT_BACKFILL_START,
        end: date | None = None,
        tables: list[str] | None = None,
        progress: Callable[[str, int, int], None] | None = None,
    ) -> dict[str, int]:
        """首次建库：先日历与代码表，再逐表按日回填。"""
        end = end or date.today()
        results: dict[str, int] = {}
        results["trade_cal"] = self.sync_trade_cal(start - timedelta(days=366), end + timedelta(days=366))
        results["stock_basic"] = self.sync_stock_basic()
        for name in (tables or list(TABLE_SPECS)):
            try:
                results[name] = self.sync_table_by_days(name, start, end, progress)
            except Exception as exc:  # noqa: BLE001 - 单表失败不阻塞其他表
                log.error("%s 回填失败: %s", name, exc)
                self._store.log_sync(name, None, 0, f"failed: {exc}")
                results[name] = -1
        return results

    def sync_incremental(self, tables: list[str] | None = None) -> dict[str, int]:
        """每日增量：从各表库内最大日期 +1 同步到当天。"""
        today = date.today()
        results: dict[str, int] = {}
        # 日历要始终覆盖到未来一年，保证调度可查询
        cal_last = self._store.max_date("trade_cal", "cal_date")
        if cal_last is None or cal_last < today + timedelta(days=180):
            results["trade_cal"] = self.sync_trade_cal(today - timedelta(days=30), today + timedelta(days=366))
        for name in (tables or list(TABLE_SPECS)):
            spec = TABLE_SPECS[name]
            last = self._store.max_date(name, spec["date_col"])
            start = (last + timedelta(days=1)) if last else DEFAULT_BACKFILL_START
            if start > today:
                results[name] = 0
                continue
            try:
                results[name] = self.sync_table_by_days(name, start, today)
            except Exception as exc:  # noqa: BLE001
                log.error("%s 增量同步失败: %s", name, exc)
                self._store.log_sync(name, last, 0, f"failed: {exc}")
                results[name] = -1
        return results

    def status(self) -> pd.DataFrame:
        """各表行数与日期覆盖范围，供 CLI 与前端数据管理页。"""
        date_col_of = {"trade_cal": "cal_date", "stock_basic": "list_date"}
        rows = []
        for name in ("trade_cal", "stock_basic", *TABLE_SPECS):
            date_col = date_col_of.get(name) or TABLE_SPECS[name]["date_col"]
            n = self._store.count(name)
            min_date = self._store.query(f'SELECT MIN("{date_col}") AS d FROM "{name}"')["d"].iloc[0] if n else None
            rows.append({
                "table": name,
                "rows": n,
                "min_date": min_date,
                "max_date": self._store.max_date(name, date_col) if n else None,
            })
        return pd.DataFrame(rows)
