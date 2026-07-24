"""回测执行 worker：在独立子进程中运行策略，写结果、更新 DB（DESIGN.md 4.6 隔离）。

由 multiprocessing.Process 调用 execute_backtest(...)；崩溃不影响主服务。
"""
from __future__ import annotations

import json
import logging
import time
import traceback
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# 子进程独立日志（不继承父进程 handler，直接写同一文件）
LOG_FILE = Path(__file__).resolve().parents[2] / "server.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(str(LOG_FILE), encoding="utf-8", mode="a"),
    ],
)
log = logging.getLogger("trading-quant")


def execute_backtest(run_id: int, code: str, config_dict: dict[str, Any],
                     duckdb_path: str, runs_dir: str, sqlite_url: str) -> None:
    """子进程入口：加载策略 → 跑回测 → 落结果 → 更新 DB。"""
    t0 = time.time()
    log.info("回测 #%d 开始 (%s ~ %s)", run_id, config_dict.get("start"), config_dict.get("end"))

    from app.data.calendar import TradeCalendar
    from app.data.portal import DataPortal
    from app.data.store import DuckDBStore
    from app.engine.loader import load_strategy_class
    from app.engine.runner import BacktestConfig, BacktestRunner
    import pandas as pd
    from app.models import BacktestRun

    eng = create_engine(sqlite_url, connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=eng)
    db = Session()
    run = db.get(BacktestRun, run_id)
    if run is None:
        db.close()
        return
    try:
        run.status = "running"
        db.commit()

        cls = load_strategy_class(code)
        c = config_dict
        cfg = BacktestConfig(
            start=date.fromisoformat(c["start"]),
            end=date.fromisoformat(c["end"]),
            initial_cash=float(c.get("initial_cash", 1_000_000)),
            freq="1d",
            fill_mode=c.get("fill_mode", "next_open"),
            slippage_pct=float(c.get("slippage_pct", 0.002)),
            commission_rate=float(c.get("commission_rate", 0.00025)),
            commission_min=float(c.get("commission_min", 5.0)),
            stamp_tax_sell=float(c.get("stamp_tax_sell", 0.0005)),
            fund_subscribe_fee=float(c.get("fund_subscribe_fee", 0.0015)),
            fund_redeem_fee=float(c.get("fund_redeem_fee", 0.005)),
            benchmark=c.get("benchmark"),
            params=c.get("params", {}) or {},
        )

        store = DuckDBStore(duckdb_path, read_only=True)
        runner = BacktestRunner(DataPortal(store, TradeCalendar(store)), TradeCalendar(store))
        result = runner.run(cls, cfg)
        store.close()

        rdir = Path(runs_dir) / str(run_id)
        rdir.mkdir(parents=True, exist_ok=True)
        eq = result.equity.astype(float).round(2)
        eq.assign(date=eq.index.astype(str)).to_json(rdir / "equity.json", orient="records")

        # trades/positions: 日期列转字符串，避免输出时间戳
        trades = result.trades.round(4)
        for col in trades.columns:
            if trades[col].dtype == 'object':
                try: trades[col] = pd.to_datetime(trades[col]).dt.strftime('%Y-%m-%d')
                except: pass
        trades.to_json(rdir / "trades.json", orient="records")

        positions = result.positions.round(4)
        for col in positions.columns:
            if positions[col].dtype == 'object':
                try: positions[col] = pd.to_datetime(positions[col]).dt.strftime('%Y-%m-%d')
                except: pass
        positions.to_json(rdir / "positions.json", orient="records")
        (rdir / "metrics.json").write_text(json.dumps(result.metrics, ensure_ascii=False), encoding="utf-8")
        (rdir / "logs.json").write_text(json.dumps(
            [{"date": str(d), "level": lv, "msg": m} for d, lv, m in result.logs],
            ensure_ascii=False), encoding="utf-8")

        run.status = "done"
        run.metrics = result.metrics
        run.result_dir = str(rdir)
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        elapsed = time.time() - t0
        log.info("回测 #%d 完成  %.1fs | 总收益 %.2f%%  夏普 %.2f",
                 run_id, elapsed, result.metrics["total_return"] * 100, result.metrics["sharpe"])
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        run = db.get(BacktestRun, run_id)
        if run is not None:
            run.status = "failed"
            run.error = f"{exc}\n{traceback.format_exc()[-800:]}"
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
        elapsed = time.time() - t0
        log.exception("回测 #%d 失败  %.1fs", run_id, elapsed)
    finally:
        db.close()
