"""模拟交易路由（DESIGN.md 第 8 节）。"""
from __future__ import annotations

import json
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models import SimAccount, SimEquity, SimOrder, Strategy

router = APIRouter(prefix="/api/sims", tags=["sims"])


class SimAccountIn(BaseModel):
    name: str
    strategy_id: int
    initial_cash: float = 1_000_000.0
    params: dict[str, Any] | None = None


# ---------- CRUD ----------

@router.get("")
def list_sims(_=Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(SimAccount).order_by(SimAccount.created_at.desc()).all()
    return [{"id": r.id, "name": r.name, "strategy_id": r.strategy_id,
             "initial_cash": r.initial_cash, "current_cash": r.current_cash,
             "status": r.status, "last_run_date": str(r.last_run_date) if r.last_run_date else None,
             "created_at": r.created_at.isoformat() if r.created_at else None}
            for r in rows]


@router.post("")
def create_sim(body: SimAccountIn, _=Depends(get_current_user), db: Session = Depends(get_db)):
    if not db.get(Strategy, body.strategy_id):
        raise HTTPException(404, "策略不存在")
    a = SimAccount(**body.model_dump())
    db.add(a); db.commit(); db.refresh(a)
    return {"id": a.id, "name": a.name, "status": a.status}


@router.delete("/{aid}")
def delete_sim(aid: int, _=Depends(get_current_user), db: Session = Depends(get_db)):
    a = db.get(SimAccount, aid)
    if not a: raise HTTPException(404, "账户不存在")
    db.delete(a); db.commit()
    return {"ok": True}


# ---------- 操作 ----------

@router.post("/{aid}/start")
def start_sim(aid: int, _=Depends(get_current_user), db: Session = Depends(get_db)):
    a = db.get(SimAccount, aid)
    if not a: raise HTTPException(404, "账户不存在")
    a.status = "running"; db.commit()
    return {"ok": True, "status": a.status}


@router.post("/{aid}/stop")
def stop_sim(aid: int, _=Depends(get_current_user), db: Session = Depends(get_db)):
    a = db.get(SimAccount, aid)
    if not a: raise HTTPException(404, "账户不存在")
    a.status = "stopped"; db.commit()
    return {"ok": True, "status": a.status}


# ---------- 详情 ----------

@router.get("/{aid}")
def get_sim(aid: int, _=Depends(get_current_user), db: Session = Depends(get_db)):
    a = db.get(SimAccount, aid)
    if not a: raise HTTPException(404, "账户不存在")
    return {"id": a.id, "name": a.name, "strategy_id": a.strategy_id,
            "initial_cash": a.initial_cash, "current_cash": a.current_cash,
            "status": a.status, "last_run_date": str(a.last_run_date) if a.last_run_date else None,
            "params": a.params, "created_at": a.created_at.isoformat() if a.created_at else None}


@router.get("/{aid}/equity")
def get_sim_equity(aid: int, _=Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(SimEquity).filter(SimEquity.account_id == aid).order_by(SimEquity.trade_date).all()
    return [{"date": str(r.trade_date), "total_value": r.total_value,
             "cash": r.cash, "market_value": r.market_value} for r in rows]


@router.get("/{aid}/orders")
def get_sim_orders(aid: int, limit: int = 50, _=Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(SimOrder).filter(SimOrder.account_id == aid)\
        .order_by(SimOrder.signal_date.desc(), SimOrder.id.desc()).limit(limit).all()
    return [{"id": r.id, "symbol": r.symbol, "side": r.side, "qty": r.qty,
             "signal_date": str(r.signal_date), "fill_date": str(r.fill_date) if r.fill_date else None,
             "fill_price": r.fill_price, "amount": r.amount, "fee": r.fee,
             "status": r.status, "reason": r.reason} for r in rows]


@router.get("/{aid}/logs")
def get_sim_logs(aid: int, limit: int = 10, _=Depends(get_current_user)):
    """返回模拟账户最近 N 天的策略日志。"""
    from pathlib import Path
    log_dir = Path("data") / "sims" / str(aid) / "logs"
    if not log_dir.exists():
        return []
    files = sorted(log_dir.glob("*.json"), reverse=True)[:limit]
    result = []
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        for entry in data:
            entry["date"] = str(entry["date"])
        result.extend(data)
    return result
