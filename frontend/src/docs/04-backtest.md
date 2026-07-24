# 回测使用指南

## 回测配置

在策略编辑器右侧面板配置回测参数：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| **开始日期** | 回测起始日 | 库内最早日期 |
| **结束日期** | 回测终止日 | 库内最晚日期 |
| **初始资金** | 起始现金（元） | 1,000,000 |
| **成交模式** | `next_open` 次日开盘成交 / `current_close` 当日收盘成交 | next_open |
| **滑点** | 成交价偏移百分比 | 0.1% |
| **佣金费率** | 交易佣金率 | 0.025%（万2.5） |
| **最低佣金** | 每笔最低佣金（元） | 5 |
| **印花税** | 卖出时收取 | 0.05%（万5，仅股票） |

## 成交规则

### A 股股票 / 场内 ETF

- **成交价格**：前复权价格
- **买入**：按 100 股整手取整，资金不足时自动缩减手数
- **卖出**：持仓股数必须 ≥ 下单股数，否则拒绝
- **佣金**：费率 × 成交金额，不足最低佣金时按最低收
- **印花税**：仅卖出时收取，买入不收
- **滑点**：实际成交价 = 信号价 × (1 - 滑点%) [买入加、卖出减]

### 场外公募基金

- **成交价格**：次日净值
- **份额**：可为小数
- **申购费**：金额 × 0.15%
- **赎回费**：金额 × 0.5%

## 绩效指标

| 指标 | 说明 |
|------|------|
| **总收益** | 期末净值 / 期初资金 - 1 |
| **年化收益** | 按实际交易日数年化 |
| **最大回撤** | 净值从高点到低点的最大跌幅 |
| **夏普比率** | (年化收益 - 无风险利率) / 年化波动率 |
| **索提诺比率** | 类似夏普，只惩罚下行波动 |
| **卡玛比率** | 年化收益 / 最大回撤 |
| **胜率** | 盈利交易笔数占比 |
| **Alpha** | 相对基准的超额收益 |
| **Beta** | 相对基准的系统性风险敞口 |

## 策略示例：双均线

```python
from app.engine.strategy import Param, Strategy

class DualMA(Strategy):
    """双均线策略：快线上穿慢线时满仓买入，下穿时空仓"""
    
    fast = Param(default=5, min=2, max=60, label="快线周期")
    slow = Param(default=20, min=5, max=250, label="慢线周期")
    symbol = Param(default="510300.SH", label="标的")
    
    def setup(self, ctx):
        ctx.universe = [self.symbol]
        ctx.benchmark = "000300.SH"
    
    def on_bar(self, ctx):
        # 计算均线：history(symbol, field, n) → numpy 数组
        close = ctx.history(self.symbol, "close", self.slow + 1)
        if len(close) < self.slow:
            return
        ma_fast = close[-self.fast:].mean()
        ma_slow = close[-self.slow:].mean()
        # 信号
        if ma_fast > ma_slow:
            ctx.order_target_percent(self.symbol, 1.0)
        else:
            ctx.order_target_percent(self.symbol, 0.0)
```
