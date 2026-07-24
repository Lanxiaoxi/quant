"""模拟交易运行器：逐日推进（DESIGN.md 7.2）。

与回测引擎同构——同一套 Broker/Context/Portfolio，只是 bar 来源改为每日数据，
状态持久化到 DB。策略代码零修改（注：跨日 self.xxx 状态不持久，应通过 ctx.portfolio 传递）。
"""
from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session

from app.data.calendar import TradeCalendar
from app.data.portal import DataPortal
from app.engine.broker import Broker, CostConfig
from app.engine.context import Context, Order, Portfolio, Position
from app.engine.loader import load_strategy_class
from app.models import SimAccount, SimEquity, SimOrder, SimPosition

log = logging.getLogger(__name__)


def advance_sim_account(
    account: SimAccount,
    strategy_code: str,
    day: date,
    portal: DataPortal,
    calendar: TradeCalendar,
    db: Session,
) -> dict:
    """逐日推进一个模拟账户；返回状态摘要。"""
    strategy_cls = load_strategy_class(strategy_code)
    cost = CostConfig()
    portfolio = Portfolio(cash=float(account.current_cash))

    # 还原持仓
    for p in db.query(SimPosition).filter(SimPosition.account_id == account.id).all():
        portfolio.positions[p.symbol] = Position(symbol=p.symbol, qty=p.qty, avg_cost=p.avg_cost)

    # 还原挂起订单
    broker = Broker(portal, portfolio, cost)
    for o in db.query(SimOrder).filter(SimOrder.account_id == account.id, SimOrder.status == "pending").all():
        broker.pending.append(Order(
            symbol=o.symbol, qty=o.qty if o.side == "buy" else -o.qty,
            side=o.side, signal_date=o.signal_date,
        ))

    strategy = strategy_cls(**dict(account.params or {}))
    ctx = Context(portal, broker, portfolio)
    ctx._advance(day)

    # setup 仅在首次调用（账户从未跑过）
    if account.last_run_date is None:
        strategy.setup(ctx)

    # ① 撮合昨日的挂起订单
    broker.fill_pending(day)
    # ② 市价更新
    broker.mark_prices(day)
    # ③ 跑策略与定时回调
    strategy.on_bar(ctx)
    for sched in ctx._scheduled_for_today():
        try:
            sched.fn(ctx)
        except Exception as exc:  # noqa: BLE001
            log.warning("账户 %d schedule %s 异常: %s", account.id, sched.at, exc)

    # 持久化：订单（删旧挂起，重写当前全量）
    db.query(SimOrder).filter(SimOrder.account_id == account.id, SimOrder.status == "pending").delete()
    for o in broker.pending:
        db.add(SimOrder(account_id=account.id, symbol=o.symbol, side=o.side, qty=abs(o.qty),
                        signal_date=o.signal_date, status="pending"))
    for o in broker.trades:
        db.add(SimOrder(account_id=account.id, symbol=o.symbol, side=o.side, qty=abs(o.qty),
                        signal_date=o.signal_date, fill_date=o.fill_date or day,
                        fill_price=o.fill_price, amount=o.amount, fee=o.fee, status="filled"))
    for o in broker.rejected:
        db.add(SimOrder(account_id=account.id, symbol=o.symbol, side=o.side, qty=abs(o.qty),
                        signal_date=o.signal_date, status="rejected", reason=o.reason))
    # 持仓（覆盖式）
    db.query(SimPosition).filter(SimPosition.account_id == account.id).delete()
    for pos in portfolio.positions.values():
        db.add(SimPosition(account_id=account.id, symbol=pos.symbol, qty=pos.qty, avg_cost=pos.avg_cost))
    # 净值快照
    db.add(SimEquity(account_id=account.id, trade_date=day,
                     total_value=round(portfolio.total_value, 2),
                     cash=round(portfolio.cash, 2),
                     market_value=round(portfolio.market_value, 2)))
    account.current_cash = round(portfolio.cash, 2)
    account.last_run_date = day
    db.commit()

    # 持久化策略日志
    log_dir = Path("data") / "sims" / str(account.id) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{day.isoformat()}.json"
    log_file.write_text(json.dumps(
        [{"date": str(d), "level": lv, "msg": m} for d, lv, m in ctx.log.records],
        ensure_ascii=False), encoding="utf-8")

    return {"total_value": portfolio.total_value, "cash": portfolio.cash,
            "trades": len(broker.trades), "pending": len(broker.pending)}
