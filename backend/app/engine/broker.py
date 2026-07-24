"""broker：撮合、成本模型、账户记账（DESIGN.md 4.5）。

关键假设：
- 信号与成交统一使用前复权价格（自洽近似：收益率正确，股数为"复权股数"；
  真实价格+除权事件调仓是后期精细化方向）；
- next_open（默认）：订单在下一根 bar 开盘价 ± 滑点成交，杜绝未来函数；
- current_close：订单在当根 bar 收盘价成交，用于快速验证想法；
- 场外基金（.OF）：按下根 bar 净值成交，无滑点，申赎费用单独配置，份额允许小数；
- 停牌（当日无 bar）：订单保持挂起，后续 bar 继续尝试。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from app.data.portal import infer_asset_type
from app.engine.context import Order, Portfolio, Position

if TYPE_CHECKING:
    from app.data.portal import DataPortal

LOT_SIZE = 100  # A股/ETF 买入整手


@dataclass
class CostConfig:
    fill_mode: str = "next_open"        # next_open / current_close
    slippage_pct: float = 0.002
    commission_rate: float = 0.00025
    commission_min: float = 5.0
    stamp_tax_sell: float = 0.0005      # 仅股票卖出收取
    fund_subscribe_fee: float = 0.0015  # 场外基金申购
    fund_redeem_fee: float = 0.005      # 场外基金赎回


class Broker:
    def __init__(self, portal: "DataPortal", portfolio: Portfolio, cost: CostConfig):
        self._portal = portal
        self._portfolio = portfolio
        self._cost = cost
        self.pending: list[Order] = []
        self.trades: list[Order] = []      # 已成交
        self.rejected: list[Order] = []    # 已拒单

    # ---------- 下单 ----------

    def place_order(self, symbol: str, qty: float, signal_date: date) -> Order:
        side = "buy" if qty > 0 else "sell"
        order = Order(symbol=symbol, qty=qty, side=side, signal_date=signal_date)
        if qty == 0:
            return self._reject(order, "数量为 0")
        if side == "buy" and infer_asset_type(symbol) in ("stock", "etf"):
            qty = (qty // LOT_SIZE) * LOT_SIZE
            if qty <= 0:
                return self._reject(order, "买入数量不足一手(100)")
            order.qty = qty
        self.pending.append(order)
        return order

    # ---------- 成交（引擎每根 bar 调用） ----------

    def fill_pending(self, day: date, include_today: bool = False) -> list[Order]:
        """撮合挂起订单。include_today=True 用于 current_close 模式（当日单当日线价成交）。"""
        filled: list[Order] = []
        still_pending: list[Order] = []
        for order in self.pending:
            if order.signal_date > day or (order.signal_date == day and not include_today):
                still_pending.append(order)
                continue
            price = self._fill_price(order, day)
            if price is None:  # 停牌/无数据，继续挂起
                still_pending.append(order)
                continue
            self._execute(order, price, day)
            if order.status == "filled":
                filled.append(order)
            elif order.status != "rejected":  # rejected 已入拒单列表，不可重回 pending
                still_pending.append(order)
        self.pending = still_pending
        self.trades.extend(filled)
        return filled

    def mark_prices(self, day: date) -> None:
        """每日按收盘价更新持仓市价（停牌沿用上一价）。"""
        for pos in self._portfolio.positions.values():
            close = self._close_of(pos.symbol, day)
            if close is not None:
                pos.last_price = close

    # ---------- 内部 ----------

    def _fill_price(self, order: Order, day: date) -> float | None:
        atype = infer_asset_type(order.symbol)
        if atype == "fund":
            return self._close_of(order.symbol, day)  # 场外基金按当日净值成交，无滑点
        if self._cost.fill_mode == "current_close":
            base = self._close_of(order.symbol, day)
        else:
            base = self._open_of(order.symbol, day)
        if base is None:
            return None
        slip = self._cost.slippage_pct
        return base * (1 + slip) if order.side == "buy" else base * (1 - slip)

    def _execute(self, order: Order, price: float, day: date) -> bool:
        if order.side == "buy":
            return self._execute_buy(order, price, day)
        return self._execute_sell(order, price, day)

    def _execute_buy(self, order: Order, price: float, day: date) -> bool:
        qty = order.qty
        # 资金不足：逐手缩减；缩减后仍买不起则拒单（下根 bar 不再重试，避免幽灵单）
        while qty > 0 and self._buy_cost(qty, price, order.symbol) > self._portfolio.cash:
            qty -= LOT_SIZE if infer_asset_type(order.symbol) in ("stock", "etf") else qty
        if qty <= 0:
            self._reject(order, "资金不足")
            return False
        amount = qty * price
        fee = self._buy_fee(amount, order.symbol)
        self._portfolio.cash -= amount + fee
        pos = self._portfolio.positions.get(order.symbol)
        if pos is None:
            pos = Position(symbol=order.symbol, qty=0.0, avg_cost=0.0, last_price=price)
            self._portfolio.positions[order.symbol] = pos
        pos.avg_cost = (pos.avg_cost * pos.qty + amount) / (pos.qty + qty)
        pos.qty += qty
        pos.last_price = price
        self._fill(order, qty, price, amount, fee, day)
        return True

    def _execute_sell(self, order: Order, price: float, day: date) -> bool:
        pos = self._portfolio.positions.get(order.symbol)
        if pos is None or pos.qty <= 0:
            self._reject(order, "无持仓可卖")
            return False
        qty = min(-order.qty, pos.qty)  # 超卖部分自动截断
        amount = qty * price
        fee = self._sell_fee(amount, order.symbol)
        self._portfolio.cash += amount - fee
        pos.qty -= qty
        pos.last_price = price
        if pos.qty <= 1e-9:
            del self._portfolio.positions[order.symbol]
        self._fill(order, qty, price, amount, fee, day)
        return True

    def _buy_cost(self, qty: float, price: float, symbol: str) -> float:
        amount = qty * price
        return amount + self._buy_fee(amount, symbol)

    def _buy_fee(self, amount: float, symbol: str) -> float:
        atype = infer_asset_type(symbol)
        if atype == "fund":
            return amount * self._cost.fund_subscribe_fee
        if atype == "index":
            return 0.0  # 指数不可直接交易（仅作基准），买入无意义；防御性返回
        return max(amount * self._cost.commission_rate, self._cost.commission_min)

    def _sell_fee(self, amount: float, symbol: str) -> float:
        atype = infer_asset_type(symbol)
        if atype == "fund":
            return amount * self._cost.fund_redeem_fee
        commission = max(amount * self._cost.commission_rate, self._cost.commission_min)
        stamp = amount * self._cost.stamp_tax_sell if atype == "stock" else 0.0  # ETF 免印花税
        return commission + stamp

    def _open_of(self, symbol: str, day: date) -> float | None:
        return self._bar_field(symbol, "open", day)

    def _close_of(self, symbol: str, day: date) -> float | None:
        return self._bar_field(symbol, "close", day)

    def _bar_field(self, symbol: str, field: str, day: date) -> float | None:
        arr = self._portal.history(symbol, field, 1, end=day)
        return float(arr[-1]) if len(arr) else None

    def _fill(self, order: Order, qty: float, price: float,
              amount: float, fee: float, day: date) -> None:
        order.status = "filled"
        order.qty = qty if order.side == "buy" else -qty
        order.fill_date = day
        order.fill_price = round(price, 4)
        order.amount = round(amount, 2)
        order.fee = round(fee, 2)

    def _reject(self, order: Order, reason: str) -> Order:
        order.status = "rejected"
        order.reason = reason
        self.rejected.append(order)
        return order
