"""WebSocket：回测状态流（轮询 DB，终态后关闭；DESIGN.md 第 8 节）。

实时日志推送留待 M4；当前每秒推送状态变化与最终指标。
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models import BacktestRun, SimAccount, SimEquity

router = APIRouter()


@router.websocket("/ws/backtests/{rid}")
async def backtest_ws(websocket: WebSocket, rid: int):
    await websocket.accept()
    eng = create_engine(f"sqlite:///{settings.sqlite_path}", connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=eng)
    last_payload = None
    try:
        while True:
            db = Session()
            r = db.get(BacktestRun, rid)
            if r is None:
                await websocket.send_json({"status": "missing"})
                break
            payload = {"id": r.id, "status": r.status}
            if r.status in ("done", "failed"):
                payload["metrics"] = r.metrics
                payload["error"] = r.error
            db.close()
            if payload != last_payload:
                await websocket.send_json(payload)
                last_payload = payload
            if r.status in ("done", "failed"):
                break
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass
    finally:
        await websocket.close()


@router.websocket("/ws/sims/{aid}")
async def sim_ws(websocket: WebSocket, aid: int):
    await websocket.accept()
    eng = create_engine(f"sqlite:///{settings.sqlite_path}", connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=eng)
    last_id = 0
    try:
        while True:
            db = Session()
            a = db.get(SimAccount, aid)
            if a is None:
                await websocket.send_json({"status": "missing"})
                break
            eq = db.query(SimEquity).filter(SimEquity.account_id == aid)\
                .order_by(SimEquity.id.desc()).first()
            db.close()
            cur_id = eq.id if eq else 0
            if cur_id > last_id:
                await websocket.send_json({
                    "status": a.status,
                    "total_value": eq.total_value if eq else a.initial_cash,
                    "cash": eq.cash if eq else a.initial_cash,
                    "last_run_date": str(a.last_run_date) if a.last_run_date else None,
                })
                last_id = cur_id
            if a.status not in ("running",):
                break
            await asyncio.sleep(5)
    except WebSocketDisconnect:
        pass
    finally:
        await websocket.close()
