# 快速开始

5 分钟上手 trading-quant，完成第一个策略的回测。

## 步骤一：登录

打开平台，使用默认账号登录：

- 用户名：`admin`
- 密码：`admin`

## 步骤二：创建策略

1. 点击左侧导航栏 **策略**
2. 点击右上角 **新建** 按钮
3. 输入策略名称（如 "我的第一个策略"）
4. 在编辑器里粘贴以下代码：

```python
from app.engine.strategy import Param, Strategy

class MyFirst(Strategy):
    symbol = Param(default="510300.SH", label="标的")

    def setup(self, ctx):
        ctx.universe = [self.symbol]
        ctx.benchmark = "000300.SH"

    def on_bar(self, ctx):
        # history(symbol, field, n) → 过去 n 根 bar 的指定字段（numpy 数组）
        close = ctx.history(self.symbol, "close", 20)
        if len(close) < 20:
            return
        ma5 = close[-5:].mean()
        ma20 = close[-20:].mean()
        if ma5 > ma20:
            ctx.order_target_percent(self.symbol, 0.8)
        else:
            ctx.order_target_percent(self.symbol, 0.0)
```

5. 点击 **保存**

## 步骤三：校验参数

- 点击右侧 **校验参数** 按钮
- 系统会提取 `symbol`、`fast`、`slow` 等 `Param` 声明
- 自动在右侧渲染参数表单，可直接修改参数值

## 步骤四：运行回测

1. 在右侧面板配置回测：
   - **开始日期** / **结束日期**：选择回测区间
   - **初始资金**：默认 100 万
   - 其他成本参数保持默认即可
2. 点击 **运行回测**
3. 等待几秒，状态变为"完成"后自动跳转到报告页

## 步骤五：阅读报告

报告页展示四个部分：

- **指标卡片**：总收益、年化收益、最大回撤、夏普比率等
- **净值曲线**：蓝色=策略、灰色=基准，红色阴影=回撤区间
- **月度收益**：每月盈亏热力图
- **成交明细**：每笔交易的完整记录

## 下一步

- 阅读 [策略 API 参考](#strategy-api) 了解 `ctx` 的全部能力
- 了解 [回测配置](#backtest) 中各参数的含义
- 尝试 [模拟交易](#simulation) 让策略在虚拟账户中每日运行
