"""交易日历服务：引擎迭代骨架（DESIGN.md 5.1 trade_cal）。

分钟级扩展时，交易时段（09:30-11:30 / 13:00-15:00）常量也放在这里，
DataPortal 与未来的 IntradayTimerTrigger 共用。
"""
from __future__ import annotations

from datetime import date, time, timedelta

from app.data.store import DuckDBStore

# A股交易时段（分钟级 / 盘中模式预留）
MORNING_SESSION = (time(9, 30), time(11, 30))
AFTERNOON_SESSION = (time(13, 0), time(15, 0))


class TradeCalendar:
    def __init__(self, store: DuckDBStore, exchange: str = "SSE"):
        self._store = store
        self._exchange = exchange

    def open_days(self, start: date, end: date) -> list[date]:
        df = self._store.query(
            "SELECT cal_date FROM trade_cal WHERE exchange = ? AND is_open "
            "AND cal_date BETWEEN ? AND ? ORDER BY cal_date",
            [self._exchange, start, end],
        )
        return [d.date() if hasattr(d, "date") else d for d in df["cal_date"]]

    def is_open(self, day: date) -> bool:
        df = self._store.query(
            "SELECT is_open FROM trade_cal WHERE exchange = ? AND cal_date = ?",
            [self._exchange, day],
        )
        return bool(not df.empty and df["is_open"].iloc[0])

    def next_open_day(self, day: date) -> date | None:
        df = self._store.query(
            "SELECT MIN(cal_date) AS d FROM trade_cal WHERE exchange = ? AND is_open AND cal_date > ?",
            [self._exchange, day],
        )
        val = df["d"].iloc[0]
        if val is None:
            return None
        return val.date() if hasattr(val, "date") else val

    def previous_open_day(self, day: date) -> date | None:
        df = self._store.query(
            "SELECT MAX(cal_date) AS d FROM trade_cal WHERE exchange = ? AND is_open AND cal_date < ?",
            [self._exchange, day],
        )
        val = df["d"].iloc[0]
        if val is None:
            return None
        return val.date() if hasattr(val, "date") else val

    def back_n_open_days(self, end: date, n: int) -> date:
        """从 end（含）往前数 n 个交易日，返回最早的日期；日历不足时给足缓冲。"""
        days = self.open_days(end - timedelta(days=n * 3 + 30), end)
        return days[-n] if len(days) >= n else (days[0] if days else end - timedelta(days=n * 3 + 30))
