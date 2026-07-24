"""M1 冒烟测试：合成数据 → DuckDB 存储 → DataPortal 查询验证。

覆盖验收点（DESIGN.md 里程碑 M1）：
- 个股日线前复权计算（含一次 10 送 10 的因子跳变）
- 场内 ETF、指数日线读取
- 场外基金净值 → bar 序列映射
- history / history_universe 接口
- 品种自动识别

运行（backend/ 目录）：python scripts/smoke_portal.py
"""
from __future__ import annotations

import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from app.data.calendar import TradeCalendar
from app.data.portal import DataPortal, infer_asset_type
from app.data.store import DuckDBStore

PASS = []


def check(name: str, cond: bool, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    PASS.append(cond)
    print(f"[{status}] {name} {detail}")


def build_store(tmp: Path) -> DuckDBStore:
    store = DuckDBStore(tmp / "test.duckdb")

    cal = pd.DataFrame({
        "exchange": ["SSE"] * 5,
        "cal_date": [date(2026, 7, d) for d in (20, 21, 22, 23, 24)],
        "is_open": [True, True, True, True, True],
        "pretrade_date": [date(2026, 7, d) for d in (17, 20, 21, 22, 23)],
    })
    store.upsert("trade_cal", cal, ["exchange", "cal_date"])

    # 600000.SH：07-22 发生 10 送 10（因子 1.0 → 2.0，上市初为 1），raw 价格 20,20,10,10,10
    daily = pd.DataFrame({
        "ts_code": ["600000.SH"] * 5,
        "trade_date": [date(2026, 7, d) for d in (20, 21, 22, 23, 24)],
        "open": [19.8, 20.1, 9.9, 10.1, 10.2],
        "high": [20.5, 20.6, 10.3, 10.4, 10.5],
        "low": [19.5, 19.8, 9.8, 9.9, 10.0],
        "close": [20.0, 20.0, 10.0, 10.0, 10.0],
        "pre_close": [19.9, 20.0, 20.0, 10.0, 10.0],
        "vol": [1e6] * 5,
        "amount": [2e7] * 5,
    })
    store.upsert("daily", daily, ["ts_code", "trade_date"])

    factor = pd.DataFrame({
        "ts_code": ["600000.SH"] * 5,
        "trade_date": [date(2026, 7, d) for d in (20, 21, 22, 23, 24)],
        "adj_factor": [1.0, 1.0, 2.0, 2.0, 2.0],
    })
    store.upsert("adj_factor", factor, ["ts_code", "trade_date"])

    etf = pd.DataFrame({
        "ts_code": ["510300.SH"] * 3,
        "trade_date": [date(2026, 7, d) for d in (22, 23, 24)],
        "open": [4.0, 4.1, 4.05], "high": [4.12, 4.15, 4.1],
        "low": [3.98, 4.05, 4.0], "close": [4.1, 4.08, 4.09],
        "pre_close": [3.99, 4.1, 4.08], "vol": [5e8] * 3, "amount": [2e9] * 3,
    })
    store.upsert("fund_daily", etf, ["ts_code", "trade_date"])

    index = pd.DataFrame({
        "ts_code": ["000300.SH"] * 3,
        "trade_date": [date(2026, 7, d) for d in (22, 23, 24)],
        "open": [4100.0, 4120.0, 4110.0], "high": [4130.0, 4140.0, 4120.0],
        "low": [4090.0, 4110.0, 4100.0], "close": [4120.0, 4115.0, 4118.0],
        "pre_close": [4095.0, 4120.0, 4115.0], "vol": [1e10] * 3, "amount": [3e11] * 3,
    })
    store.upsert("index_daily", index, ["ts_code", "trade_date"])

    nav = pd.DataFrame({
        "ts_code": ["000001.OF"] * 3,
        "nav_date": [date(2026, 7, d) for d in (22, 23, 24)],
        "unit_nav": [1.234, 1.240, 1.237],
        "accum_nav": [3.456, 3.462, 3.459],
    })
    store.upsert("fund_nav", nav, ["ts_code", "nav_date"])
    return store


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        store = build_store(Path(td))
        portal = DataPortal(store, TradeCalendar(store))

        # 品种识别
        check("infer 个股", infer_asset_type("600000.SH") == "stock")
        check("infer ETF", infer_asset_type("510300.SH") == "etf")
        check("infer 指数", infer_asset_type("000300.SH") == "index")
        check("infer 场外基金", infer_asset_type("000001.OF") == "fund")

        # 前复权：f_end=2.0（07-24），除权前 20*1/2 → 10；除权后 10*2/2 → 10，全线 10
        qfq = portal.get_bars("600000.SH", date(2026, 7, 20), date(2026, 7, 24), adjust="qfq")
        closes = qfq["close"].round(6).tolist()
        check("个股前复权价格连续", closes == [10.0] * 5, f"closes={closes}")

        # 不复权
        raw = portal.get_bars("600000.SH", date(2026, 7, 20), date(2026, 7, 24), adjust="none")
        check("不复权返回原始价", raw["close"].tolist() == [20.0, 20.0, 10.0, 10.0, 10.0])

        # 后复权：f_first=1.0（上市初），除权后 10*2/1 → 20，全线 20
        hfq = portal.get_bars("600000.SH", date(2026, 7, 20), date(2026, 7, 24), adjust="hfq")
        check("后复权价格连续", hfq["close"].round(6).tolist() == [20.0] * 5,
              f"closes={hfq['close'].round(6).tolist()}")

        # ETF / 指数
        etf = portal.get_bars("510300.SH", date(2026, 7, 22), date(2026, 7, 24))
        check("ETF 日线", len(etf) == 3 and etf["close"].iloc[0] == 4.1)
        idx = portal.get_bars("000300.SH", date(2026, 7, 22), date(2026, 7, 24))
        check("指数日线", len(idx) == 3 and idx["close"].iloc[-1] == 4118.0)

        # 场外基金：O/H/L = 单位净值
        fund = portal.get_bars("000001.OF", date(2026, 7, 22), date(2026, 7, 24))
        check("场外基金净值映射",
              len(fund) == 3 and fund["close"].iloc[0] == 1.234 and fund["open"].iloc[1] == 1.240)

        # history / history_universe
        h = portal.history("600000.SH", "close", 3, end=date(2026, 7, 24))
        check("history 取近 3 根(前复权)", isinstance(h, np.ndarray) and h.tolist() == [10.0, 10.0, 10.0])
        hu = portal.history_universe(["510300.SH", "000300.SH"], "close", 2, end=date(2026, 7, 24))
        check("history_universe 面板", list(hu.columns) == ["510300.SH", "000300.SH"] and len(hu) == 2)

        # 分钟级预留：明确报 NotImplementedError
        try:
            portal.get_bars("600000.SH", date(2026, 7, 20), date(2026, 7, 24), freq="1m")
            check("分钟级预留报错", False)
        except NotImplementedError:
            check("分钟级预留报错", True)

    print(f"\n{'全部通过' if all(PASS) else '存在失败'}：{sum(PASS)}/{len(PASS)}")
    return 0 if all(PASS) else 1


if __name__ == "__main__":
    sys.exit(main())
