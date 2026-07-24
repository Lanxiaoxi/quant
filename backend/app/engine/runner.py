"""回测主循环：逐 bar 推进（DESIGN.md 第 6 节）。

bar 内顺序（与模拟交易 7.2 严格一致，保证回测/模拟同构）：
  ① 撮合上一信号日挂起的订单（next_open：按今日开盘价成交）
  ② 按收盘价更新持仓市价
  ③ 调用策略 on_bar 与 schedule 回调 → 新订单挂起
  ④ （current_close 模式）当日订单按收盘价立即成交
  ⑤ 结算当日净值快照
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Type

import pandas as pd

from app.data.calendar import TradeCalendar
from app.data.portal import DataPortal
from app.engine.broker import Broker, CostConfig
from app.engine.context import Context, Portfolio
from app.engine.metrics import compute_metrics, monthly_returns
from app.engine.strategy import Strategy


@dataclass
class BacktestConfig:
    start: date
    end: date
    initial_cash: float = 1_000_000.0
    freq: str = "1d"
    fill_mode: str = "next_open"
    slippage_pct: float = 0.002
    commission_rate: float = 0.00025
    commission_min: float = 5.0
    stamp_tax_sell: float = 0.0005
    fund_subscribe_fee: float = 0.0015
    fund_redeem_fee: float = 0.005
    benchmark: str | None = "000300.SH"
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class BacktestResult:
    strategy_name: str
    config: BacktestConfig
    equity: pd.DataFrame       # index=date: total_value, cash, market_value, benchmark_value
    trades: pd.DataFrame       # 已成交订单明细
    rejected: pd.DataFrame     # 拒单明细
    positions: pd.DataFrame    # 每日持仓快照
    monthly: pd.DataFrame      # 月度收益矩阵（年 × 月）
    metrics: dict[str, Any]
    logs: list[tuple]


class BacktestRunner:
    def __init__(self, portal: DataPortal, calendar: TradeCalendar):
        self._portal = portal
        self._calendar = calendar

    def run(self, strategy_cls: Type[Strategy], config: BacktestConfig) -> BacktestResult:
        if config.freq != "1d":
            raise NotImplementedError("分钟级回测为预留扩展（DESIGN.md 7.3）")
        days = self._calendar.open_days(config.start, config.end)
        if not days:
            raise ValueError(f"{config.start} ~ {config.end} 无交易日（trade_cal 未同步？）")

        strategy = strategy_cls(**config.params)
        portfolio = Portfolio(cash=float(config.initial_cash))
        cost = CostConfig(
            fill_mode=config.fill_mode,
            slippage_pct=config.slippage_pct,
            commission_rate=config.commission_rate,
            commission_min=config.commission_min,
            stamp_tax_sell=config.stamp_tax_sell,
            fund_subscribe_fee=config.fund_subscribe_fee,
            fund_redeem_fee=config.fund_redeem_fee,
        )
        broker = Broker(self._portal, portfolio, cost)
        ctx = Context(self._portal, broker, portfolio, freq=config.freq)

        # setup：以首个交易日为当前时间，股票池/基准/schedule 在此时声明
        ctx._advance(days[0])
        strategy.setup(ctx)
        benchmark = ctx.benchmark or config.benchmark

        equity_rows: list[dict] = []
        position_rows: list[dict] = []

        for day in days:
            ctx._advance(day)
            broker.fill_pending(day)                      # ① 昨日信号今日成交
            broker.mark_prices(day)                       # ② 市价更新
            strategy.on_bar(ctx)                          # ③ 策略主逻辑
            for sched in ctx._scheduled_for_today():      # ③' 定时回调（日频近似语义）
                sched.fn(ctx)
            if config.fill_mode == "current_close":       # ④ 当日单当日线价成交
                broker.fill_pending(day, include_today=True)
                broker.mark_prices(day)
            equity_rows.append({                          # ⑤ 净值结算
                "date": day,
                "total_value": portfolio.total_value,
                "cash": portfolio.cash,
                "market_value": portfolio.market_value,
            })
            for sym, pos in portfolio.positions.items():
                position_rows.append({
                    "date": day, "symbol": sym, "qty": pos.qty,
                    "avg_cost": round(pos.avg_cost, 4), "last_price": pos.last_price,
                    "market_value": round(pos.market_value, 2),
                })

        equity = pd.DataFrame(equity_rows).set_index("date")
        if benchmark:
            bench = self._portal.get_bars(benchmark, days[0], days[-1], adjust="none")
            if not bench.empty:
                base = bench["close"].iloc[0]
                equity["benchmark_value"] = bench["close"] / base * config.initial_cash

        metrics = compute_metrics(equity, config.initial_cash, benchmark, days)
        return BacktestResult(
            strategy_name=strategy_cls.__name__,
            config=config,
            equity=equity,
            trades=self._orders_df(broker.trades),
            rejected=self._orders_df(broker.rejected),
            positions=pd.DataFrame(position_rows),
            monthly=monthly_returns(equity["total_value"]),
            metrics=metrics,
            logs=ctx.log.records,
        )

    @staticmethod
    def _orders_df(orders) -> pd.DataFrame:
        cols = ["symbol", "side", "qty", "signal_date", "fill_date", "fill_price", "amount", "fee", "status", "reason"]
        if not orders:
            return pd.DataFrame(columns=cols)
        return pd.DataFrame([{c: getattr(o, c) for c in cols} for o in orders])
