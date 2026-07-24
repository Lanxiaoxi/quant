"""M3 API 全流程集成测试（DESIGN.md 里程碑 M3 验收：建策略→回测→拿报告）。

- 使用独立临时 DATA_DIR + 合成 duckdb，不触碰真实 market.duckdb（避免与回填写进程锁冲突）；
- TestClient 跑：登录 → 建策略 → validate → 发起回测 → 轮询 → 取 series/trades/metrics。

运行（backend/ 目录）：python scripts/test_api.py
"""
from __future__ import annotations

import math
import os
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

# 必须在导入 app 之前设定 DATA_DIR，使 settings 指向临时库
_TMP = tempfile.mkdtemp(prefix="tq_api_")
os.environ["DATA_DIR"] = _TMP
os.environ["TQ_ADMIN_PASSWORD"] = "admin"
os.environ["TQ_JWT_SECRET"] = "test-secret"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.data.store import DuckDBStore  # noqa: E402

DUALMA_CODE = '''
from app.engine.strategy import Param, Strategy

class DualMA(Strategy):
    symbol = Param(default="600000.SH", label="标的")
    fast = Param(default=5, min=2, max=60, label="快线")
    slow = Param(default=20, min=5, max=250, label="慢线")

    def setup(self, ctx):
        ctx.universe = [self.symbol]
        ctx.benchmark = "000300.SH"

    def on_bar(self, ctx):
        close = ctx.history(self.symbol, "close", self.slow + 1)
        if len(close) < self.slow + 1:
            return
        if close[-self.fast:].mean() > close[-self.slow:].mean():
            ctx.order_target_percent(self.symbol, 0.95)
        else:
            ctx.order_target_percent(self.symbol, 0.0)
'''

PASS = []


def check(name: str, cond: bool, detail: str = "") -> None:
    PASS.append(cond)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def build_synthetic_market() -> tuple[date, date]:
    """60 个交易日，先涨后跌，保证双均线有金叉/死叉成交。"""
    store = DuckDBStore()  # 指向 _TMP/market.duckdb
    start = date(2025, 1, 2)
    days, d = [], start
    while len(days) < 60:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    closes = [10 + i * 0.1 for i in range(30)] + [13 - (i - 30) * 0.1 for i in range(30, 60)]
    opens = [closes[0]] + closes[:-1]
    store.upsert("trade_cal", pd.DataFrame({
        "exchange": ["SSE"] * 60, "cal_date": days, "is_open": [True] * 60,
        "pretrade_date": [days[0] - timedelta(days=3)] + days[:-1],
    }), ["exchange", "cal_date"])
    store.upsert("daily", pd.DataFrame({
        "ts_code": ["600000.SH"] * 60, "trade_date": days,
        "open": opens, "close": closes,
        "high": [max(o, c) + 0.1 for o, c in zip(opens, closes)],
        "low": [min(o, c) - 0.1 for o, c in zip(opens, closes)],
        "pre_close": opens, "vol": [1e6] * 60, "amount": [1e7] * 60,
    }), ["ts_code", "trade_date"])
    store.upsert("adj_factor", pd.DataFrame({
        "ts_code": ["600000.SH"] * 60, "trade_date": days, "adj_factor": [1.0] * 60,
    }), ["ts_code", "trade_date"])
    bench = [4000 + math.sin(i / 8) * 50 + i for i in range(60)]
    store.upsert("index_daily", pd.DataFrame({
        "ts_code": ["000300.SH"] * 60, "trade_date": days,
        "open": bench, "close": bench, "high": [b + 5 for b in bench],
        "low": [b - 5 for b in bench], "pre_close": bench, "vol": [1e9] * 60, "amount": [1e11] * 60,
    }), ["ts_code", "trade_date"])
    store.close()
    return days[0], days[-1]


def main() -> int:
    start, end = build_synthetic_market()

    from app.main import app
    with TestClient(app) as client:
        # 1. 登录
        r = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
        check("登录成功", r.status_code == 200, str(r.status_code))
        token = r.json()["access_token"]
        H = {"Authorization": f"Bearer {token}"}

        # 鉴权拦截
        check("未带 token 被拒", client.get("/api/strategies").status_code == 401)

        # 2. 建策略
        r = client.post("/api/strategies", json={"name": "双均线", "code": DUALMA_CODE}, headers=H)
        check("建策略", r.status_code == 200, str(r.status_code))
        sid = r.json()["id"]

        # 3. validate 提取 Param schema
        r = client.post(f"/api/strategies/{sid}/validate", headers=H)
        check("validate 提取 Param", r.status_code == 200 and r.json()["name"] == "DualMA"
              and any(p["name"] == "fast" for p in r.json()["params"]), str(r.json()))

        # 4. 发起回测
        r = client.post("/api/backtests", json={
            "strategy_id": sid, "start": start.isoformat(), "end": end.isoformat(),
            "params": {"fast": 5, "slow": 20, "symbol": "600000.SH"},
            "initial_cash": 1_000_000, "slippage_pct": 0.0, "commission_min": 0.0,
            "commission_rate": 0.0, "stamp_tax_sell": 0.0,
        }, headers=H)
        check("发起回测", r.status_code == 200, str(r.status_code) + r.text)
        rid = r.json()["id"]

        # 5. 轮询直到完成（子进程）
        status, deadline = "pending", time.time() + 90
        while time.time() < deadline:
            r = client.get(f"/api/backtests/{rid}", headers=H)
            status = r.json()["status"]
            if status in ("done", "failed"):
                break
            time.sleep(1)
        check("回测完成", status == "done", f"status={status} err={r.json().get('error')}")
        if status != "done":
            print(r.json().get("error"))
            return 1

        metrics = r.json()["metrics"]
        check("metrics 含年化/回撤/夏普",
              all(k in metrics for k in ("annual_return", "max_drawdown", "sharpe", "total_return")),
              str({k: metrics.get(k) for k in ("total_return", "annual_return", "max_drawdown", "sharpe")}))

        # 6. 取净值/成交
        r = client.get(f"/api/backtests/{rid}/series", headers=H)
        series = r.json()
        check("净值序列 60 根", len(series) == 60 and "total_value" in series[0], f"len={len(series)}")
        r = client.get(f"/api/backtests/{rid}/trades", headers=H)
        trades = r.json()
        check("有成交记录", isinstance(trades, list) and len(trades) >= 2, f"trades={len(trades)}")

        # 7. 健康检查
        check("health", client.get("/api/health").json()["ok"])

        print(f"\n{'全部通过' if all(PASS) else '存在失败'}：{sum(PASS)}/{len(PASS)}")
        print(f"指标：总收益 {metrics['total_return']:.2%}  年化 {metrics['annual_return']:.2%}  "
              f"回撤 {metrics['max_drawdown']:.2%}  夏普 {metrics['sharpe']}  成交 {len(trades)} 笔")
        return 0 if all(PASS) else 1


if __name__ == "__main__":
    sys.exit(main())
