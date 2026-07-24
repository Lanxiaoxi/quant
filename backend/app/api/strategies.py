"""策略 CRUD 与校验路由（DESIGN.md 第 8 节）。

- POST /api/strategies/{id}/validate：exec 代码、提取 Param schema，供前端自动渲染参数表单。
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.engine.loader import load_strategy_class
from app.models import Strategy

router = APIRouter(prefix="/api/strategies", tags=["strategies"])


class StrategyIn(BaseModel):
    name: str
    code: str
    description: str = ""
    default_config: dict | None = None


class StrategyOut(BaseModel):
    id: int
    name: str
    code: str
    description: str
    default_config: dict | None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    model_config = {"from_attributes": True}


@router.get("", response_model=list[StrategyOut])
def list_strategies(_: object = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(Strategy).order_by(Strategy.updated_at.desc()).all()


@router.post("", response_model=StrategyOut)
def create_strategy(body: StrategyIn, _: object = Depends(get_current_user), db: Session = Depends(get_db)):
    s = Strategy(**body.model_dump())
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


@router.get("/{sid}", response_model=StrategyOut)
def get_strategy(sid: int, _: object = Depends(get_current_user), db: Session = Depends(get_db)):
    s = db.get(Strategy, sid)
    if not s:
        raise HTTPException(404, "策略不存在")
    return s


@router.put("/{sid}", response_model=StrategyOut)
def update_strategy(sid: int, body: StrategyIn, _: object = Depends(get_current_user), db: Session = Depends(get_db)):
    s = db.get(Strategy, sid)
    if not s:
        raise HTTPException(404, "策略不存在")
    for k, v in body.model_dump().items():
        setattr(s, k, v)
    db.commit()
    db.refresh(s)
    return s


@router.delete("/{sid}")
def delete_strategy(sid: int, _: object = Depends(get_current_user), db: Session = Depends(get_db)):
    s = db.get(Strategy, sid)
    if not s:
        raise HTTPException(404, "策略不存在")
    db.delete(s)
    db.commit()
    return {"ok": True}


@router.post("/{sid}/validate")
def validate_strategy(sid: int, _: object = Depends(get_current_user), db: Session = Depends(get_db)):
    """语法检查 + Param 提取（供前端表单）。"""
    s = db.get(Strategy, sid)
    if not s:
        raise HTTPException(404, "策略不存在")
    try:
        cls = load_strategy_class(s.code)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"策略代码无效: {exc}")
    return {"name": cls.__name__, "params": cls.params_json_schema()}
