"""数据管理路由（DESIGN.md 第 8 节）。

GET  /api/data/status   各表覆盖范围
POST /api/data/sync     手动触发增量同步（注意：与正在运行的回填写进程互斥）
"""
from __future__ import annotations

import duckdb
from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.core.config import settings

router = APIRouter(prefix="/api/data", tags=["data"])

_DATE_COL = {"trade_cal": "cal_date", "stock_basic": "list_date", "daily": "trade_date",
             "adj_factor": "trade_date", "daily_basic": "trade_date", "fund_daily": "trade_date",
             "index_daily": "trade_date", "fund_nav": "nav_date"}
_TABLES = list(_DATE_COL)


@router.get("/status")
def status(_: object = Depends(get_current_user)):
    """只读打开 duckdb；被占用时返回提示而非 500。"""
    try:
        con = duckdb.connect(str(settings.duckdb_path), read_only=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"行情库暂不可读（可能正在同步）：{exc}")
    rows = []
    for t, col in _DATE_COL.items():
        try:
            n = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            rng = con.execute(f'SELECT MIN("{col}"), MAX("{col}") FROM "{t}"').fetchone() if n else (None, None)
        except Exception:
            n, rng = 0, (None, None)
        rows.append({"table": t, "rows": n, "min_date": str(rng[0]) if rng[0] else None,
                     "max_date": str(rng[1]) if rng[1] else None})
    con.close()
    return rows


@router.post("/sync")
def sync(_: object = Depends(get_current_user)):
    """手动触发增量同步（后台运行，与定时调度同一入口）。"""
    from app.data.sync import DataSyncer
    from app.data.tushare_client import TushareClient
    from app.data.store import DuckDBStore
    try:
        store = DuckDBStore()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"行情库被占用，无法同步：{exc}")
    results = DataSyncer(TushareClient(), store).sync_incremental()
    return results
