"""绩效指标计算（DESIGN.md 第 6 节）。

约定：
- 年化按 252 个交易日；
- 无风险利率 rf 取 2%（用于夏普/Sortino/Alpha）；
- 胜率/盈亏比基于日收益（M2 口径；逐笔配对口径后期可加）。
"""
from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252
RISK_FREE_RATE = 0.02


def compute_metrics(equity: pd.DataFrame, initial_cash: float,
                    benchmark: str | None, days: list[date]) -> dict[str, Any]:
    values = equity["total_value"]
    rets = values.pct_change().dropna()
    n = len(values)

    total_return = values.iloc[-1] / initial_cash - 1
    annual_return = (1 + total_return) ** (TRADING_DAYS_PER_YEAR / max(n - 1, 1)) - 1 if n > 1 else 0.0
    volatility = rets.std() * np.sqrt(TRADING_DAYS_PER_YEAR) if len(rets) else 0.0

    cummax = values.cummax()
    drawdown = values / cummax - 1
    max_drawdown = float(drawdown.min())

    excess = rets.mean() * TRADING_DAYS_PER_YEAR - RISK_FREE_RATE
    sharpe = excess / volatility if volatility > 0 else 0.0
    downside = rets[rets < 0]
    downside_std = downside.std() * np.sqrt(TRADING_DAYS_PER_YEAR) if len(downside) else 0.0
    sortino = excess / downside_std if downside_std > 0 else 0.0
    calmar = annual_return / abs(max_drawdown) if max_drawdown < 0 else 0.0

    win_days = rets[rets > 0]
    loss_days = rets[rets < 0]
    win_rate = len(win_days) / len(rets) if len(rets) else 0.0
    pl_ratio = (win_days.mean() / abs(loss_days.mean())) if len(win_days) and len(loss_days) and loss_days.mean() != 0 else 0.0

    metrics: dict[str, Any] = {
        "start": str(days[0]), "end": str(days[-1]), "days": n,
        "initial_cash": initial_cash,
        "final_value": round(float(values.iloc[-1]), 2),
        "total_return": round(float(total_return), 4),
        "annual_return": round(float(annual_return), 4),
        "max_drawdown": round(max_drawdown, 4),
        "volatility": round(float(volatility), 4),
        "sharpe": round(float(sharpe), 3),
        "sortino": round(float(sortino), 3),
        "calmar": round(float(calmar), 3),
        "win_rate_daily": round(float(win_rate), 4),
        "pl_ratio_daily": round(float(pl_ratio), 3),
    }

    if benchmark and "benchmark_value" in equity.columns:
        bench = equity["benchmark_value"].dropna()
        bench_rets = bench.pct_change().dropna()
        aligned = pd.concat([rets, bench_rets], axis=1, keys=["s", "b"]).dropna()
        if len(aligned) > 2 and aligned["b"].var() > 0:
            beta = aligned["s"].cov(aligned["b"]) / aligned["b"].var()
            bench_total = bench.iloc[-1] / bench.iloc[0] - 1
            bench_annual = (1 + bench_total) ** (TRADING_DAYS_PER_YEAR / max(len(bench) - 1, 1)) - 1
            alpha = annual_return - (RISK_FREE_RATE + beta * (bench_annual - RISK_FREE_RATE))
            metrics.update({
                "benchmark": benchmark,
                "benchmark_return": round(float(bench_total), 4),
                "benchmark_annual": round(float(bench_annual), 4),
                "alpha": round(float(alpha), 4),
                "beta": round(float(beta), 3),
                "excess_annual": round(float(annual_return - bench_annual), 4),
            })
    return metrics


def monthly_returns(values: pd.Series) -> pd.DataFrame:
    """月度收益矩阵：index=年，columns=月（1-12）。首月以期初净值为基准。"""
    if values.empty:
        return pd.DataFrame()
    idx = pd.to_datetime(pd.Series(values.index).astype(str))
    monthly_last = values.groupby([idx.dt.year, idx.dt.month]).last()
    rows: dict[int, dict[int, float]] = {}
    prev_val: float | None = None
    for (y, m), v in monthly_last.items():
        base = prev_val if prev_val is not None else values.iloc[0]
        rows.setdefault(int(y), {})[int(m)] = round(float(v / base - 1), 4) if base else np.nan
        prev_val = v
    return pd.DataFrame.from_dict(rows, orient="index").sort_index()
