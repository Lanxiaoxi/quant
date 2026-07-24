"""模拟交易调度器（APScheduler，DESIGN.md 7.2）。

交易日 17:00：扫描 running 状态账户 → 逐日推进。
"""
from __future__ import annotations

import logging
from datetime import date, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.core.db import SessionLocal
from app.data.calendar import TradeCalendar
from app.data.portal import DataPortal
from app.data.store import DuckDBStore
from app.engine.sim_runner import advance_sim_account
from app.models import SimAccount, Strategy

log = logging.getLogger(__name__)


def _sim_job():
    """实际调度逻辑：推进所有运行中的模拟账户。"""
    log.info("模拟交易调度开始")
    store = DuckDBStore(read_only=True)
    calendar = TradeCalendar(store)
    portal = DataPortal(store, calendar)
    today = date.today()
    if not calendar.is_open(today):
        log.info("今日非交易日，跳过")
        store.close()
        return
    db = SessionLocal()
    try:
        accounts = db.query(SimAccount).filter(SimAccount.status == "running").all()
        for acc in accounts:
            s = db.get(Strategy, acc.strategy_id)
            if not s:
                continue
            if acc.last_run_date and acc.last_run_date >= today:
                continue  # 今日已处理
            # 首次运行从账户创建日期或最新有数据的日期开始
            run_day = calendar.next_open_day(acc.last_run_date or (today - __import__('datetime').timedelta(days=1)))
            if run_day and run_day <= today:
                try:
                    summary = advance_sim_account(acc, s.code, run_day, portal, calendar, db)
                    log.info("账户 %d (%s) 推进到 %s: 净值=%.2f", acc.id, acc.name, run_day, summary["total_value"])
                except Exception as exc:  # noqa: BLE001
                    log.error("账户 %d 推进失败: %s", acc.id, exc)
    finally:
        db.close()
        store.close()


scheduler = AsyncIOScheduler()


def start_scheduler():
    scheduler.add_job(_sim_job, CronTrigger(hour=17, minute=0, timezone="Asia/Shanghai"),
                      id="sim_daily", name="模拟交易每日调度")
    scheduler.start()
