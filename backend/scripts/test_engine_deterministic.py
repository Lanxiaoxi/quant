"""M2 确定性对账测试：合成数据 + 手工计算的期望值，逐项断言。

覆盖（DESIGN.md 4.3/4.5/第 6 节）：
  1. next_open 成交时点（D1 信号 → D2 开盘成交）与整手规则
  2. 佣金（万2.5 最低5元）与印花税（股票卖出）
  3. 滑点（买 +0.2% / 卖 -0.2%）
  4. 资金不足自动缩减
  5. current_close 模式当日成交
  6. 场外基金：份额小数、按净值成交、申购费
  7. 防未来函数：history 最后一根=当日收盘
  8. 停牌订单挂起、复牌成交
  9. Param 反射/校验、schedule 回调
 10. metrics 总收益对账

运行（backend/ 目录）：python scripts/test_engine_deterministic.py
"""
from __future__ import annotations

import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from app.data.calendar import TradeCalendar
from app.data.portal import DataPortal
from app.data.store import DuckDBStore
from app.engine.runner import BacktestConfig, BacktestRunner
from app.engine.strategy import Param, Strategy

DAYS = [date(2026, 7, d) for d in (20, 21, 22, 23, 24, 27)]
PASS = []


def check(name: str, cond: bool, detail: str = "") -> None:
    PASS.append(cond)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def approx(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def build_store(tmp: Path) -> DuckDBStore:
    store = DuckDBStore(tmp / "t.duckdb")
    store.upsert("trade_cal", pd.DataFrame({
        "exchange": ["SSE"] * 6, "cal_date": DAYS, "is_open": [True] * 6,
        "pretrade_date": [date(2026, 7, 17)] + DAYS[:-1],
    }), ["exchange", "cal_date"])

    def bars(code: str, oc: list[tuple[float, float]], skip: set[int] = frozenset()):
        rows = {"ts_code": [], "trade_date": [], "open": [], "high": [], "low": [],
                "close": [], "pre_close": [], "vol": [], "amount": []}
        prev = oc[0][0]
        for i, (o, c) in enumerate(oc):
            if i in skip:
                continue
            rows["ts_code"].append(code)
            rows["trade_date"].append(DAYS[i])
            rows["open"].append(o)
            rows["close"].append(c)
            rows["high"].append(max(o, c) + 0.2)
            rows["low"].append(min(o, c) - 0.2)
            rows["pre_close"].append(prev)
            rows["vol"].append(1e6)
            rows["amount"].append(1e7)
            prev = c
        return pd.DataFrame(rows)

    # 主测试股：open 10~15 逐日+1，close 10.5~15.5 逐日+1
    oc = [(10.0 + i, 10.5 + i) for i in range(6)]
    store.upsert("daily", bars("600000.SH", oc), ["ts_code", "trade_date"])
    # 停牌股：07-22、07-23 无 bar
    store.upsert("daily", bars("000001.SZ", oc, skip={2, 3}), ["ts_code", "trade_date"])
    # 复权因子恒为 1（qfq == raw）
    store.upsert("adj_factor", pd.DataFrame({
        "ts_code": ["600000.SH"] * 6 + ["000001.SZ"] * 4,
        "trade_date": DAYS + [DAYS[0], DAYS[1], DAYS[4], DAYS[5]],
        "adj_factor": [1.0] * 10,
    }), ["ts_code", "trade_date"])
    # 基准指数（有波动，保证 beta 可算）
    store.upsert("index_daily", pd.DataFrame({
        "ts_code": ["000300.SH"] * 6, "trade_date": DAYS,
        "open": [4000, 4010, 3990, 4020, 4005, 4030],
        "high": [4010, 4020, 4000, 4030, 4015, 4040],
        "low": [3990, 4000, 3980, 4010, 3995, 4020],
        "close": [4000.0, 4010.0, 3990.0, 4020.0, 4005.0, 4030.0],
        "pre_close": [3995.0, 4000.0, 4010.0, 3990.0, 4020.0, 4005.0],
        "vol": [1e9] * 6, "amount": [1e11] * 6,
    }), ["ts_code", "trade_date"])
    # 场外基金：净值 1.00 → 1.05
    store.upsert("fund_nav", pd.DataFrame({
        "ts_code": ["110022.OF"] * 6, "nav_date": DAYS,
        "unit_nav": [1.00, 1.01, 1.02, 1.03, 1.04, 1.05],
        "accum_nav": [2.00, 2.01, 2.02, 2.03, 2.04, 2.05],
    }), ["ts_code", "nav_date"])
    return store


class BuySell(Strategy):
    """D1 满仓买入，D4 清仓。"""

    def setup(self, ctx):
        ctx.universe = ["600000.SH"]

    def on_bar(self, ctx):
        if ctx.now == DAYS[0]:
            ctx.order_target_percent("600000.SH", 1.0)
        elif ctx.now == DAYS[3]:
            ctx.order_target_percent("600000.SH", 0.0)


def make_runner(store: DuckDBStore) -> BacktestRunner:
    return BacktestRunner(DataPortal(store, TradeCalendar(store)), TradeCalendar(store))


def cfg(**kw) -> BacktestConfig:
    base = dict(start=DAYS[0], end=DAYS[-1], initial_cash=10000.0,
                slippage_pct=0.0, commission_rate=0.0, commission_min=0.0,
                stamp_tax_sell=0.0, benchmark="000300.SH")
    base.update(kw)
    return BacktestConfig(**base)


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        runner = make_runner(build_store(Path(td)))

        # ---------- 场景 1：零费用零滑点，next_open 时点与净值对账 ----------
        r = runner.run(BuySell, cfg())
        eq = r.equity["total_value"].tolist()
        expect = [10000.0, 10450.0, 11350.0, 12250.0, 12700.0, 12700.0]
        check("S1 净值序列", all(approx(a, b) for a, b in zip(eq, expect)) and len(eq) == 6,
              f"{eq}")
        t = r.trades
        check("S1 买入 D2 开盘价成交", len(t) == 2 and t.iloc[0]["fill_date"] == DAYS[1]
              and approx(t.iloc[0]["fill_price"], 11.0) and t.iloc[0]["qty"] == 900.0)
        check("S1 卖出 D5 开盘价成交", t.iloc[1]["fill_date"] == DAYS[4]
              and approx(t.iloc[1]["fill_price"], 14.0) and t.iloc[1]["qty"] == -900.0)
        check("S1 total_return=27%", approx(r.metrics["total_return"], 0.27, 1e-4),
              f"{r.metrics['total_return']}")
        check("S1 基准指标存在", "benchmark_return" in r.metrics)

        # ---------- 场景 2：佣金+印花税 ----------
        r2 = runner.run(BuySell, cfg(commission_rate=0.00025, commission_min=5.0, stamp_tax_sell=0.0005))
        check("S2 买入佣金=max(2.475,5)=5", approx(r2.trades.iloc[0]["fee"], 5.0))
        check("S2 卖出费用=5+6.3=11.3", approx(r2.trades.iloc[1]["fee"], 11.3, 1e-2),
              f"{r2.trades.iloc[1]['fee']}")
        check("S2 期末现金=12683.7", approx(r2.equity["cash"].iloc[-1], 12683.7, 1e-2),
              f"{r2.equity['cash'].iloc[-1]}")

        # ---------- 场景 3：滑点 ----------
        r3 = runner.run(BuySell, cfg(slippage_pct=0.002))
        check("S3 买价=11*1.002", approx(r3.trades.iloc[0]["fill_price"], 11.022, 1e-3))
        check("S3 卖价=14*0.998", approx(r3.trades.iloc[1]["fill_price"], 13.972, 1e-3))

        # ---------- 场景 4：资金不足自动缩减 ----------
        class OverBuy(Strategy):
            def setup(self, ctx):
                ctx.universe = ["600000.SH"]

            def on_bar(self, ctx):
                if ctx.now == DAYS[0]:
                    ctx.order_target_percent("600000.SH", 3.0)  # 300% 仓位

        r4 = runner.run(OverBuy, cfg())
        check("S4 缩减到 900 股成交", len(r4.trades) == 1 and r4.trades.iloc[0]["qty"] == 900.0,
              f"trades={len(r4.trades)} rejected={len(r4.rejected)}")

        # ---------- 场景 5：current_close 当日成交 ----------
        r5 = runner.run(BuySell, cfg(fill_mode="current_close"))
        check("S5 当日买当日成交", r5.trades.iloc[0]["fill_date"] == DAYS[0]
              and approx(r5.trades.iloc[0]["fill_price"], 10.5))
        check("S5 当日卖当日成交", r5.trades.iloc[1]["fill_date"] == DAYS[3]
              and approx(r5.trades.iloc[1]["fill_price"], 13.5))

        # ---------- 场景 6：场外基金 ----------
        class BuyFund(Strategy):
            def setup(self, ctx):
                ctx.universe = ["110022.OF"]

            def on_bar(self, ctx):
                if ctx.now == DAYS[0]:
                    ctx.order_target_percent("110022.OF", 0.455)  # 4550 份（非整百，验证不适用整手规则）

        r6 = runner.run(BuyFund, cfg())
        f = r6.trades.iloc[0]
        check("S6 基金次日净值成交", f["fill_date"] == DAYS[1] and approx(f["fill_price"], 1.01),
              f"{f['fill_date']} @ {f['fill_price']}")
        check("S6 基金份额不按整手截断", approx(f["qty"], 4550.0), f"qty={f['qty']}")
        check("S6 申购费≈金额*0.0015", approx(f["fee"], f["amount"] * 0.0015, 0.01), f"fee={f['fee']}")

        # ---------- 场景 7：防未来函数 ----------
        class Spy(Strategy):
            seen = {}

            def setup(self, ctx):
                ctx.universe = ["600000.SH"]

            def on_bar(self, ctx):
                Spy.seen[ctx.now] = ctx.history("600000.SH", "close", 3).tolist()

        runner.run(Spy, cfg())
        check("S7 当根 bar=当日收盘", approx(Spy.seen[DAYS[2]][-1], 12.5)
              and Spy.seen[DAYS[2]] == [10.5, 11.5, 12.5], f"{Spy.seen[DAYS[2]]}")
        check("S7 首日仅 1 根", Spy.seen[DAYS[0]] == [10.5])

        # ---------- 场景 8：停牌挂起 ----------
        class BuySusp(Strategy):
            def setup(self, ctx):
                ctx.universe = ["000001.SZ"]

            def on_bar(self, ctx):
                if ctx.now == DAYS[1]:
                    ctx.order("000001.SZ", 100)

        r8 = runner.run(BuySusp, cfg())
        check("S8 停牌两日不成交，复牌 D5 成交", len(r8.trades) == 1
              and r8.trades.iloc[0]["fill_date"] == DAYS[4], f"{r8.trades['fill_date'].tolist()}")

        # ---------- 场景 9：Param 与 schedule ----------
        class WithParam(Strategy):
            n = Param(default=2, min=1, max=5, label="窗口")
            calls = []

            def setup(self, ctx):
                ctx.universe = ["600000.SH"]
                ctx.schedule(at="14:00", fn=self.cb)

            def cb(self, ctx):
                WithParam.calls.append(ctx.now)

            def on_bar(self, ctx):
                _ = ctx.history("600000.SH", "close", self.n)

        schema = WithParam.params_json_schema()
        check("S9 Param schema", schema == [{"name": "n", "default": 2, "min": 1, "max": 5,
                                             "step": None, "label": "窗口"}], f"{schema}")
        WithParam.calls = []
        runner.run(WithParam, cfg(params={"n": 3}))
        check("S9 schedule 每日触发 6 次", len(WithParam.calls) == 6)
        try:
            WithParam(n=99)
            check("S9 参数越界报错", False)
        except ValueError:
            check("S9 参数越界报错", True)

    print(f"\n{'全部通过' if all(PASS) else '存在失败'}：{sum(PASS)}/{len(PASS)}")
    return 0 if all(PASS) else 1


if __name__ == "__main__":
    sys.exit(main())
