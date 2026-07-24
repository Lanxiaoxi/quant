"""回测路由（DESIGN.md 第 8 节）。

POST /api/backtests         发起回测（子进程隔离执行）
GET  /api/backtests         列表
GET  /api/backtests/{id}    详情（status/metrics/config）
GET  /api/backtests/{id}/series | /trades | /positions
WS   /ws/backtests/{id}     状态流
"""
from __future__ import annotations

import json
import multiprocessing as mp
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.db import SessionLocal, get_db
from app.engine.worker import execute_backtest
from app.models import BacktestRun, Strategy

router = APIRouter(tags=["backtests"])
# 运行中的子进程引用，防止被 GC 回收
_running: list[mp.Process] = []


class BacktestRequest(BaseModel):
    strategy_id: int
    start: str
    end: str
    initial_cash: float | None = None
    fill_mode: str | None = None
    slippage_pct: float | None = None
    commission_rate: float | None = None
    commission_min: float | None = None
    stamp_tax_sell: float | None = None
    fund_subscribe_fee: float | None = None
    fund_redeem_fee: float | None = None
    benchmark: str | None = None
    params: dict[str, Any] | None = None


def _merge_config(strategy: Strategy, req: BacktestRequest) -> dict[str, Any]:
    base = dict(strategy.default_config or {})
    for k, v in req.model_dump(exclude={"strategy_id"}).items():
        if v is not None:
            base[k] = v
    base["start"] = req.start
    base["end"] = req.end
    if "start" not in base or "end" not in base:
        raise HTTPException(400, "缺少 start/end")
    return base


@router.post("/api/backtests")
def create_backtest(req: BacktestRequest, _: object = Depends(get_current_user), db: Session = Depends(get_db)):
    s = db.get(Strategy, req.strategy_id)
    if not s:
        raise HTTPException(404, "策略不存在")
    config = _merge_config(s, req)
    run = BacktestRun(strategy_id=s.id, status="pending", config=config)
    db.add(run)
    db.commit()
    db.refresh(run)

    sqlite_url = f"sqlite:///{settings.sqlite_path}"
    proc = mp.Process(
        target=execute_backtest,
        args=(run.id, s.code, config, str(settings.duckdb_path), str(settings.runs_dir), sqlite_url),
        daemon=False,
    )
    proc.start()
    _running.append(proc)
    return {"id": run.id, "status": "pending"}


@router.get("/api/backtests")
def list_backtests(strategy_id: int | None = Query(None), limit: int = 50,
                   _: object = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(BacktestRun)
    if strategy_id:
        q = q.filter(BacktestRun.strategy_id == strategy_id)
    rows = q.order_by(BacktestRun.created_at.desc()).limit(limit).all()
    return [{"id": r.id, "strategy_id": r.strategy_id, "status": r.status,
             "config": r.config, "metrics": r.metrics,
             "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]


@router.get("/api/backtests/{rid}")
def get_backtest(rid: int, _: object = Depends(get_current_user), db: Session = Depends(get_db)):
    r = db.get(BacktestRun, rid)
    if not r:
        raise HTTPException(404, "回测不存在")
    return {"id": r.id, "strategy_id": r.strategy_id, "status": r.status,
            "config": r.config, "metrics": r.metrics, "error": r.error,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None}


def _read_result(rid: int, name: str):
    rdir = Path(settings.runs_dir) / str(rid)
    f = rdir / f"{name}.json"
    if not f.exists():
        raise HTTPException(404, f"结果 {name} 不存在（回测未完成或失败）")
    return json.loads(f.read_text(encoding="utf-8"))


@router.get("/api/backtests/{rid}/series")
def get_series(rid: int, _: object = Depends(get_current_user)):
    return _read_result(rid, "equity")


@router.get("/api/backtests/{rid}/trades")
def get_trades(rid: int, _: object = Depends(get_current_user)):
    return _read_result(rid, "trades")


@router.get("/api/backtests/{rid}/positions")
def get_positions(rid: int, _: object = Depends(get_current_user)):
    return _read_result(rid, "positions")
