"""DataPortal：统一行情查询层（DESIGN.md 5.1 频率抽象）。

- 引擎迭代器与 ctx.history 统一经此处取 bar；
- freq="1d" 读日线表；freq="1m" 为分钟级预留（bars_1m，待启用）；
- 品种自动识别：A股个股 / 场内ETF / 场外基金 / 指数；
- 前复权（默认）/ 后复权 / 不复权。
"""
from __future__ import annotations

from datetime import date
from typing import Literal

import numpy as np
import pandas as pd

from app.data.calendar import TradeCalendar
from app.data.store import DuckDBStore

AssetType = Literal["stock", "etf", "fund", "index"]
Adjust = Literal["qfq", "hfq", "none"]

# 场内基金（ETF/LOF）代码前缀：沪市 51/58/56，深市 15/16/18
_ETF_PREFIX = ("51", "58", "56", "15", "16", "18")


def infer_asset_type(ts_code: str) -> AssetType:
    """按 tushare 代码规则推断品种。

    - 000001.OF 等 .OF 后缀      → 场外基金（fund_nav）
    - 000300.SH / 399006.SZ 等   → 指数（沪 000/880 开头，深 399 开头）
    - 510300.SH / 159915.SZ 等   → 场内 ETF（fund_daily）
    - 其余 .SH/.SZ/.BJ           → 个股
    """
    code, _, exch = ts_code.partition(".")
    exch = exch.upper()
    if exch == "OF":
        return "fund"
    if exch == "SH" and code.startswith(("000", "880")):
        return "index"
    if exch == "SZ" and code.startswith("399"):
        return "index"
    if code.startswith(_ETF_PREFIX):
        return "etf"
    return "stock"


class DataPortal:
    def __init__(self, store: DuckDBStore, calendar: TradeCalendar):
        self._store = store
        self._calendar = calendar

    # ---------- 主接口 ----------

    def get_bars(
        self,
        symbol: str,
        start: date,
        end: date,
        freq: str = "1d",
        adjust: Adjust = "qfq",
    ) -> pd.DataFrame:
        """返回 index=trade_date、columns=[open,high,low,close,pre_close,vol,amount] 的 DataFrame。"""
        if freq != "1d":
            raise NotImplementedError("分钟级为预留扩展（DESIGN.md 5.1 bars_1m），当前仅支持 freq='1d'")
        atype = infer_asset_type(symbol)
        if atype == "stock":
            return self._apply_adjust(self._ohlcv("daily", symbol, start, end), symbol, end, adjust)
        if atype == "etf":
            df = self._ohlcv("fund_daily", symbol, start, end)
            # 场内基金复权因子与股票共用 adj_factor 接口；缺因子时退化为不复权
            try:
                return self._apply_adjust(df, symbol, end, adjust)
            except Exception:
                return df
        if atype == "index":
            return self._ohlcv("index_daily", symbol, start, end)  # 指数无需复权
        return self._fund_nav_bars(symbol, start, end)

    def history(self, symbol: str, field: str, n: int, end: date | None = None,
                adjust: Adjust = "qfq") -> np.ndarray:
        """取截至 end（含）的过去 n 根 bar 单字段序列——未来引擎 ctx.history 的实现。"""
        end = end or date.today()
        start = self._calendar.back_n_open_days(end, n)
        df = self.get_bars(symbol, start, end, adjust=adjust)
        if df.empty or field not in df.columns:
            return np.array([])
        return df[field].tail(n).to_numpy()

    def history_universe(self, symbols: list[str], field: str, n: int,
                         end: date | None = None, adjust: Adjust = "qfq") -> pd.DataFrame:
        """股票池面板数据：index=日期，columns=代码——未来 ctx.history_universe 的实现。"""
        end = end or date.today()
        start = self._calendar.back_n_open_days(end, n)
        frames = {}
        for s in symbols:
            df = self.get_bars(s, start, end, adjust=adjust)
            if not df.empty and field in df.columns:
                frames[s] = df[field].tail(n)
        return pd.DataFrame(frames)

    # ---------- 内部 ----------

    def _ohlcv(self, table: str, symbol: str, start: date, end: date) -> pd.DataFrame:
        df = self._store.query(
            f'SELECT trade_date, open, high, low, close, pre_close, vol, amount '
            f'FROM "{table}" WHERE ts_code = ? AND trade_date BETWEEN ? AND ? ORDER BY trade_date',
            [symbol, start, end],
        )
        if df.empty:
            return df
        return df.set_index("trade_date")

    def _apply_adjust(self, df: pd.DataFrame, symbol: str, end: date, adjust: Adjust) -> pd.DataFrame:
        """前复权：price * f / f_end（f_end 为 end 之前最近因子）；后复权：price * f / f_first。"""
        if adjust == "none" or df.empty:
            return df
        factors = self._store.query(
            "SELECT trade_date, adj_factor FROM adj_factor WHERE ts_code = ? AND trade_date <= ? ORDER BY trade_date",
            [symbol, end],
        )
        if factors.empty:
            return df
        merged = pd.merge_asof(
            df.reset_index().sort_values("trade_date"),
            factors.sort_values("trade_date"),
            on="trade_date",
        ).set_index("trade_date")
        base = factors["adj_factor"].iloc[-1] if adjust == "qfq" else factors["adj_factor"].iloc[0]
        ratio = merged["adj_factor"] / base
        for col in ("open", "high", "low", "close", "pre_close"):
            merged[col] = merged[col] * ratio
        return merged.drop(columns=["adj_factor"])

    def _fund_nav_bars(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        """场外基金：净值即价格序列，O/H/L 等于当日单位净值（DESIGN.md 4.5 次日净值成交）。"""
        df = self._store.query(
            "SELECT nav_date, unit_nav FROM fund_nav WHERE ts_code = ? AND nav_date BETWEEN ? AND ? ORDER BY nav_date",
            [symbol, start, end],
        )
        if df.empty:
            return pd.DataFrame(columns=["open", "high", "low", "close", "pre_close", "vol", "amount"])
        df = df.rename(columns={"nav_date": "trade_date", "unit_nav": "close"}).set_index("trade_date")
        df["open"] = df["high"] = df["low"] = df["close"]
        df["pre_close"] = df["close"].shift(1)
        df["vol"] = np.nan
        df["amount"] = np.nan
        return df[["open", "high", "low", "close", "pre_close", "vol", "amount"]]
