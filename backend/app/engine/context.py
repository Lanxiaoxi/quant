"""ctx 上下文与账户类型（DESIGN.md 4.3）。

- 所有策略能力挂在 Context 上：数据(history/price)、账户(portfolio)、下单(order 四语义)、定时(schedule)、日志(log)；
- 防未来函数：history 只能取到当前 bar（含）及之前的数据，由引擎注入的日期保证；
- ctx.now 当前为 date，盘中模式启用时为 datetime（接口语义不变）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Callable

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from app.data.portal import DataPortal
    from app.engine.broker import Broker


@dataclass
class Position:
    symbol: str
    qty: float
    avg_cost: float
    last_price: float = 0.0

    @property
    def market_value(self) -> float:
        return self.qty * self.last_price


@dataclass
class Portfolio:
    cash: float
    positions: dict[str, Position] = field(default_factory=dict)

    @property
    def market_value(self) -> float:
        return sum(p.market_value for p in self.positions.values())

    @property
    def total_value(self) -> float:
        return self.cash + self.market_value


@dataclass
class Order:
    symbol: str
    qty: float                 # 带符号：正买负卖
    side: str                  # "buy" / "sell"
    signal_date: date          # 下单所在 bar（信号日）
    status: str = "pending"    # pending / filled / rejected / cancelled
    fill_date: date | None = None
    fill_price: float | None = None
    amount: float = 0.0        # 成交金额
    fee: float = 0.0           # 总费用
    reason: str = ""           # 拒单/废单原因


class RunLogger:
    """策略日志：写入运行记录，报告页可见（ctx.log.info(...)）。"""

    def __init__(self) -> None:
        self.records: list[tuple[date | datetime, str, str]] = []
        self._now: date | datetime | None = None

    def _log(self, level: str, msg: Any) -> None:
        self.records.append((self._now, level, str(msg)))

    def info(self, msg: Any) -> None:
        self._log("INFO", msg)

    def warning(self, msg: Any) -> None:
        self._log("WARN", msg)

    def error(self, msg: Any) -> None:
        self._log("ERROR", msg)


@dataclass
class _Schedule:
    at: str                     # "HH:MM"，日频模式下在当日 bar 近似触发（DESIGN.md 4.2.1）
    fn: Callable


class Context:
    """策略上下文。引擎每根 bar 推进 _now 并注入数据/撮合实现。"""

    def __init__(self, portal: "DataPortal", broker: "Broker", portfolio: Portfolio,
                 freq: str = "1d", adjust: str = "qfq"):
        self._portal = portal
        self._broker = broker
        self._portfolio = portfolio
        self._freq = freq
        self._adjust = adjust
        self._now: date | datetime | None = None
        self._schedules: list[_Schedule] = []
        self.universe: list[str] = []
        self.benchmark: str | None = None
        self.log = RunLogger()

    # ---- 引擎内部（策略不应调用） ----

    def _advance(self, now: date | datetime) -> None:
        self._now = now
        self.log._now = now

    def _scheduled_for_today(self) -> list["_Schedule"]:
        """日频模式：所有定时回调在当日 bar 触发（近似语义，DESIGN.md 4.2.1）。"""
        return list(self._schedules)

    # ---- 时间 ----

    @property
    def now(self) -> date | datetime:
        assert self._now is not None, "setup 之后才可访问 ctx.now"
        return self._now

    # ---- 数据 ----

    def history(self, symbol: str, field: str, n: int) -> np.ndarray:
        """过去 n 根 bar 的单字段序列（含当根）；引擎保证不含未来数据。"""
        assert isinstance(self._now, date)
        return self._portal.history(symbol, field, n, end=self._now, adjust=self._adjust)

    def history_universe(self, field: str, n: int) -> pd.DataFrame:
        """当前股票池的面板数据：index=日期，columns=代码。"""
        assert isinstance(self._now, date)
        return self._portal.history_universe(self.universe, field, n, end=self._now, adjust=self._adjust)

    def price(self, symbol: str) -> float | None:
        """当前 bar 价格（日频=收盘价）；无数据（停牌）返回 None。"""
        arr = self.history(symbol, "close", 1)
        if len(arr) == 0:
            return None
        val = float(arr[-1])
        return None if math.isnan(val) else val

    # ---- 账户 ----

    @property
    def portfolio(self) -> Portfolio:
        return self._portfolio

    # ---- 下单（四语义，DESIGN.md 4.3） ----

    def order(self, symbol: str, qty: float) -> Order:
        """按数量下单：正买负卖。"""
        return self._broker.place_order(symbol, float(qty), self.now)

    def order_value(self, symbol: str, value: float) -> Order | None:
        """按金额下单。"""
        price = self.price(symbol)
        if price is None or price <= 0:
            self.log.warning(f"{symbol} 无价格，order_value 取消")
            return None
        return self.order(symbol, value / price)

    def order_target(self, symbol: str, target_qty: float) -> Order | None:
        """调整持仓到目标数量。"""
        current = self._portfolio.positions.get(symbol)
        delta = float(target_qty) - (current.qty if current else 0.0)
        if delta == 0:
            return None
        return self.order(symbol, delta)

    def order_target_percent(self, symbol: str, percent: float) -> Order | None:
        """调整持仓到目标仓位比例（占总资产，最常用）。"""
        price = self.price(symbol)
        if price is None or price <= 0:
            self.log.warning(f"{symbol} 无价格，order_target_percent 取消")
            return None
        target_value = self._portfolio.total_value * percent
        return self.order_target(symbol, target_value / price)

    # ---- 定时回调（盘中模式预留，DESIGN.md 4.2.1） ----

    def schedule(self, at: str, fn: Callable) -> None:
        """声明日内定时回调，如 at="14:00"。日频模式下在当日 bar 近似触发。"""
        hh, _, mm = at.partition(":")
        if not (hh.isdigit() and mm.isdigit() and 0 <= int(hh) <= 23 and 0 <= int(mm) <= 59):
            raise ValueError(f"schedule 时间格式应为 HH:MM，收到: {at}")
        self._schedules.append(_Schedule(at=f"{int(hh):02d}:{int(mm):02d}", fn=fn))
