"""双均线策略真实数据回测 demo（DESIGN.md 4.1 同款策略）。

用法（backend/ 目录）：
    python scripts/run_backtest_demo.py [start] [end] [symbol]
    python scripts/run_backtest_demo.py 2024-01-01 2026-07-22 510300.SH

回填进行中也能跑（只读连接，与写入进程共存）；不给日期时自动用库内最近两年。
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.data.calendar import TradeCalendar
from app.data.portal import DataPortal
from app.data.store import DuckDBStore
from app.engine.runner import BacktestConfig, BacktestRunner
from app.engine.strategy import Param, Strategy


class DualMA(Strategy):
    """双均线：快线上穿满仓，下穿空仓。"""
    symbol = Param(default="510300.SH", label="标的代码")
    fast = Param(default=5, min=2, max=60, label="快线周期")
    slow = Param(default=20, min=5, max=250, label="慢线周期")

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


def main() -> int:
    args = sys.argv[1:]
    symbol = args[2] if len(args) > 2 else "510300.SH"

    store = DuckDBStore(read_only=True)
    calendar = TradeCalendar(store)
    portal = DataPortal(store, calendar)

    if len(args) >= 2:
        start, end = date.fromisoformat(args[0]), date.fromisoformat(args[1])
    else:
        from app.data.portal import infer_asset_type
        table = {"stock": "daily", "etf": "fund_daily", "index": "index_daily", "fund": "fund_nav"}[infer_asset_type(symbol)]
        date_col = "nav_date" if table == "fund_nav" else "trade_date"
        max_d = store.query(f'SELECT MAX({date_col}) AS d FROM "{table}" WHERE ts_code = ?', [symbol])["d"].iloc[0]
        if max_d is None:
            print(f"库内暂无 {symbol} 数据（{table} 表可能仍在回填），请稍后重试或指定区间")
            return 1
        end = max_d.date() if hasattr(max_d, "date") else max_d
        start = end - timedelta(days=730)
        print(f"未指定区间，自动使用库内最近窗口：{start} ~ {end}")

    runner = BacktestRunner(portal, calendar)
    result = runner.run(DualMA, BacktestConfig(
        start=start, end=end, initial_cash=1_000_000,
        params={"fast": 5, "slow": 20, "symbol": symbol},
    ))

    m = result.metrics
    print(f"\n===== {result.strategy_name} @ {symbol} | {m['start']} ~ {m['end']} =====")
    print(f"期末净值   {m['final_value']:>14,.2f}   总收益 {m['total_return']:>8.2%}")
    print(f"年化收益   {m['annual_return']:>14.2%}   回撤   {m['max_drawdown']:>8.2%}")
    print(f"夏普       {m['sharpe']:>14}   卡玛   {m['calmar']:>8}")
    if "benchmark_return" in m:
        print(f"基准收益   {m['benchmark_return']:>14.2%}   超额年化 {m['excess_annual']:>7.2%}   beta {m['beta']}")
    print(f"成交 {len(result.trades)} 笔，拒单 {len(result.rejected)} 笔")
    if not result.trades.empty:
        print("\n最近 5 笔成交：")
        print(result.trades.tail(5).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
