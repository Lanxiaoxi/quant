# 策略 API 参考

## Strategy 基类

每个策略必须继承 `Strategy` 基类，并实现两个方法：

```python
from app.engine.strategy import Param, Strategy

class MyStrategy(Strategy):
    # 策略参数��使用 Param 声明）
    
    def setup(self, ctx):
        """初始化：在回测开始前调用一次"""
        pass
    
    def on_bar(self, ctx):
        """每个交易日调用一次，策略核心逻辑"""
        pass
```

## Param 描述符

用 `Param` 声明策略参数，前端会自动渲染对应的表单控件：

```python
class DualMA(Strategy):
    fast = Param(default=5, min=2, max=60, label="快线周期")
    slow = Param(default=20, min=5, max=250, label="慢线周期")
    symbol = Param(default="510300.SH", label="标的代码")
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `default` | `int/float/str` | 默认值，同时决定参数类型 |
| `min` | `int/float` | 最小值（数值型参数） |
| `max` | `int/float` | 最大值（数值型参数） |
| `step` | `int/float` | 步长（数值型参数，默认 1） |
| `label` | `str` | 参数显示名称，前端表单的标签 |

根据 `default` 的类型，前端自动选择控件：

- `int` → 数字输入框（整数）
- `float` → 数字输入框（小数）
- `str` → 文本输入框

## Context (ctx) 上下文

`setup` 和 `on_bar` 都接收 `ctx` 参数，它提供了策略所需的所有能力。

### 时间与行情

```python
ctx.now          # 当前交易日，datetime.date 类型
ctx.universe     # 股票池，setup 中设置
ctx.benchmark    # 基准指数代码
ctx.cash         # 当前可用资金

# history(symbol, field, n) → numpy 数组（已防未来函数）
close = ctx.history("510300.SH", "close", 20)     # 最近 20 根收盘价
volume = ctx.history("510300.SH", "volume", 5)    # 最近 5 根成交量

# history_universe(field, n) → DataFrame（index=日期, columns=代码）
df = ctx.history_universe("close", 20)             # 股票池全体收盘价面板

# 当前价格（日线 = 当日收盘价，无数据/停牌返回 None）
price = ctx.price("510300.SH")
```

`field` 支持的值：`open`、`high`、`low`、`close`、`volume`、`amount`。

### 持仓与账户

```python
# 当前持仓
ctx.portfolio.value        # 总资产（现金+持仓市值）
ctx.portfolio.positions    # dict，key 是标的代码
pos = ctx.portfolio["510300.SH"]  # 单只标的持仓
pos.qty                    # 持仓数量
pos.market_value           # 持仓市值
pos.avg_cost               # 持仓均价

# 可用资金
ctx.cash                   # 剩余现金
```

### 下单

平台提供四种下单语义，覆盖常见场景：

```python
# 1. 按金额买入（自动计算股数/份数）
ctx.order("510300.SH", amount=10000)  # 买入 1 万元

# 2. 按股数买入（股票整手规则自动处理）
ctx.order("510300.SH", qty=100)

# 3. 按目标仓位百分比调仓
ctx.order_target_percent("510300.SH", 0.6)  # 目标 60% 仓位

# 4. 按目标金额调仓
ctx.order_target_value("510300.SH", 50000)  # 目标持仓 5 万元
```

`order` 返回值：

```python
o = ctx.order("510300.SH", amount=10000)
o.side       # "buy" 或 "sell"
o.qty        # 下单股数
o.status     # "pending" → "filled" / "rejected"
```

### 其他

```python
ctx.log("message")         # 输出日志，在报告页可查看
ctx.schedule("14:00", fn)  # 盘中定时执行（分钟级扩展预留）
```

## 防未来函数

引擎保证策略不会看到未来数据：

- `ctx.history()` 的行情只返回到当前日期（含当日）
- `ctx.price()` 当天收盘价在回测中视为已知（日线回测假设收盘后决策）
- 下单在次日开盘价成交（`next_open` 模式）
