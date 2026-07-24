# trading-quant 详细设计方案

> 版本：v1.1（2026-07-23）｜状态：待评审
> v1.1：新增盘中运行预留设计（4.2.1 定时回调语义、5.1 频率抽象、第 7 节 Trigger/Feed 可插拔架构）
> 定位：个人量化平台 —— 网页编写策略 → 一键回测 → 绩效报告 → 模拟交易运行

---

## 1. 已确认决策

| 维度 | 结论 |
|---|---|
| 品种 | A股股票、场内ETF、场外公募基金 |
| 频率 | 日线优先，引擎按 bar 频率抽象，预留分钟级与盘中定时运行扩展 |
| 引擎 | 自研，事件驱动，回测/模拟双模式复用同一策略代码 |
| 策略 API | 类式（`Strategy` 基类 + `Param` 声明式参数），设计目标：合理、简洁、高效 |
| 数据源 | tushare Pro 为主（2000 积分），baostock/akshare 兜底校验 |
| 部署 | 云服务器，单人使用 + JWT 登录鉴权 |
| 存储 | DuckDB + Parquet（行情）；SQLite（业务数据） |

---

## 2. 技术栈

**后端**：Python 3.11+ / FastAPI / SQLAlchemy + SQLite / APScheduler / tushare / DuckDB / pandas + numpy / uvicorn

**前端**：React 18 + TypeScript + Vite / Tailwind CSS + shadcn/ui / Monaco Editor / ECharts / TanStack Query

**部署**：docker-compose（backend + caddy），Caddy 自动 HTTPS，数据卷持久化

---

## 3. 目录结构

```
trading-quant/
├── backend/
│   ├── app/
│   │   ├── main.py               # FastAPI 入口
│   │   ├── core/                 # 配置、鉴权、DB 会话
│   │   ├── api/                  # 路由：auth / strategies / backtests / sims / data
│   │   ├── models/               # SQLAlchemy 业务表
│   │   ├── engine/               # 自研回测引擎（核心）
│   │   │   ├── strategy.py       # Strategy 基类、Param 描述符
│   │   │   ├── context.py        # ctx 上下文
│   │   │   ├── broker.py         # 撮合、成本模型、账户记账
│   │   │   ├── runner.py         # 回测主循环（bar 迭代）
│   │   │   └── metrics.py        # 绩效指标计算
│   │   ├── data/                 # tushare 客户端、增量同步、DuckDB 查询层
│   │   ├── scheduler/            # 每日数据同步 job、模拟交易 job
│   │   └── sandbox/              # 策略子进程执行器（隔离 + 超时）
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── pages/                # Login / Strategies / Editor / Report / Sim / Data
│       ├── components/           # 图表、指标卡、订单表、参数表单
│       └── api/                  # 接口客户端、WebSocket
├── data/                         # 行情 DuckDB/Parquet + SQLite（部署卷，gitignore）
├── docker-compose.yml
└── DESIGN.md
```

---

## 4. 策略 API 契约（本方案核心，请重点审阅）

### 4.1 一个完整示例

```python
class DualMA(Strategy):
    """双均线策略：快线上穿持有，下穿空仓"""
    fast = Param(default=5,  min=2, max=60,  label="快线周期")
    slow = Param(default=20, min=5, max=250, label="慢线周期")

    def setup(self, ctx):
        ctx.universe = ["510300.SH"]       # 股票池：列表或每日动态选股
        ctx.benchmark = "000300.SH"

    def on_bar(self, ctx):
        close = ctx.history("510300.SH", "close", self.slow + 1)
        if len(close) < self.slow + 1:
            return
        if close[-self.fast:].mean() > close[-self.slow:].mean():
            ctx.order_target_percent("510300.SH", 0.95)
        else:
            ctx.order_target_percent("510300.SH", 0)
```

### 4.2 生命周期

| 钩子 | 时机 | 用途 |
|---|---|---|
| `setup(ctx)` | 回测/模拟启动时一次 | 设股票池、基准，初始化 `self.xxx` 状态 |
| `on_bar(ctx)` | 每个交易日一次 | 策略主逻辑、下单 |

显式不提供：`before_trading_start` / `after_trading_end` 等钩子（保持概念最少）；日内定时需求由 `ctx.schedule` 统一承载（见下）。

### 4.2.1 盘中定时回调（设计预留，语义现在定稿）

策略可在 `setup` 中声明日内定时任务——例如"每个交易日 14:00 按当时价格调仓"：

```python
class AfternoonRebalance(Strategy):
    def setup(self, ctx):
        ctx.universe = ["510300.SH", "510500.SH"]
        ctx.schedule(at="14:00", fn=self.rebalance)   # 每个交易日 14:00 触发

    def on_bar(self, ctx):
        pass   # 日频逻辑（可选，与定时回调并存）

    def rebalance(self, ctx):
        px = ctx.price("510300.SH")   # 盘中模式下取到 14:00 的价格
        ...
```

**同一行策略代码，在不同运行模式下语义自动映射**（策略零修改）：

| 运行模式 | 触发时机 | `ctx.price` 取到 | 实现阶段 |
|---|---|---|---|
| 回测 · 日频 | 当日 bar（近似为收盘时刻） | 当日收盘价（近似，报告页标注该假设） | M2 |
| 回测 · 分钟级 | 14:00 的分钟 bar | 14:00 分钟 bar 价格 | 预留（需分钟数据） |
| 模拟 · 日频批处理 | 收盘后批处理（近似） | 当日收盘价（近似） | M5 |
| 模拟 · 盘中运行 | 14:00 真实触发 | 14:00 实时行情 | 预留（需实时行情源，见第 7 节） |

### 4.3 `ctx` 接口

| 接口 | 返回 | 说明 |
|---|---|---|
| `ctx.now` | `datetime` | 当前 bar 时间（日频为当日日期，盘中为具体时刻） |
| `ctx.history(symbol, field, n)` | `np.ndarray` | 过去 n 根 bar 的单字段序列（含当根），**引擎保证不含未来数据** |
| `ctx.history_universe(field, n)` | `pd.DataFrame` | 整个股票池的面板数据（index=日期，columns=代码） |
| `ctx.price(symbol)` | `float` | 当前 bar 价格（日频=收盘价，盘中=当时最新价） |
| `ctx.portfolio` | `Portfolio` | `.cash` `.market_value` `.total_value` `.positions` |
| `ctx.portfolio.positions[symbol]` | `Position` | `.qty` `.avg_cost` `.last_price` `.market_value` |
| `ctx.order(symbol, qty)` | `Order` | 按股数（正买负卖） |
| `ctx.order_value(symbol, value)` | `Order` | 按金额 |
| `ctx.order_target(symbol, qty)` | `Order` | 调到目标股数 |
| `ctx.order_target_percent(symbol, pct)` | `Order` | 调到目标仓位比例（最常用） |
| `ctx.log.info/.warning(...)` | — | 写入运行日志，报告页可见 |
| `ctx.universe` / `ctx.benchmark` | 可写属性 | 股票池与基准 |
| `ctx.schedule(at, fn)` | — | 声明日内定时回调（如 `at="14:00"`），各模式语义见 4.2.1 |

### 4.4 Param 声明式参数

```python
fast = Param(default=5, min=2, max=60, step=1, label="快线周期")
```

- 引擎扫描类属性中的 `Param`，自动生成 JSON Schema
- 前端据此渲染参数表单（滑块/输入框），无需写任何前端代码
- 后期参数寻优直接复用 `min/max/step` 做网格搜索

### 4.5 成交与成本假设（回测配置项，不写进策略代码）

```json
{
  "start": "2019-01-01", "end": "2026-07-01", "initial_cash": 1000000,
  "freq": "1d", "fill_mode": "next_open",
  "slippage_pct": 0.002,
  "commission": {"rate": 0.00025, "min": 5},
  "stamp_tax_sell": 0.0005,
  "fund_fee": {"subscribe": 0.0015, "redeem": 0.005},
  "benchmark": "000300.SH", "params": {"fast": 5, "slow": 20}
}
```

- `fill_mode`：`next_open`（默认，下一 bar 开盘价成交，杜绝未来函数）或 `current_close`（当根 bar 收盘价，用于快速验证想法）；"下一 bar" 随 `freq` 自然泛化：日频=次交易日开盘，分钟级=下一分钟开盘
- 印花税仅股票卖出收取；ETF 免印花税；场外基金按净值成交、申赎费用单独配置
- 场外基金特殊处理：日频下净值即价格序列，`next_open` 语义自然映射为"次日净值成交"

### 4.6 执行隔离

每次回测/模拟在**独立子进程**中运行：超时上限（默认 10 分钟）、stdout/stderr 捕获进日志、崩溃不影响主服务。单人使用场景不做 import 白名单硬限制，但子进程无网络代理环境变量，降低误用风险。

---

## 5. 数据层设计

### 5.1 行情表（DuckDB + Parquet，按年分区）

| 表 | tushare 来源 | 粒度 | 说明 |
|---|---|---|---|
| `trade_cal` | `trade_cal` | 日 | 交易日历，引擎迭代骨架 |
| `stock_basic` | `stock_basic` | 周更 | 代码、名称、上市日期、市场 |
| `daily` | `daily` | 日 | A股 OHLCV、成交额 |
| `adj_factor` | `adj_factor` | 日 | 复权因子，查询层默认前复权 |
| `daily_basic` | `daily_basic` | 日 | PE/PB/总市值/流通市值（选股因子） |
| `fund_daily` | `fund_daily` | 日 | 场内ETF OHLCV |
| `fund_nav` | `fund_nav` | 日 | 场外基金净值 |
| `index_daily` | `index_daily` | 日 | 指数（基准用） |
| `bars_1m`（预留） | `stk_mins`（需 5000 积分）/ 实时行情落库 | 分钟 | 含 `bar_time` 时间戳列，分钟级扩展时启用 |

**同步策略**：每个交易日 17:00 增量同步。**按 `trade_date` 一次拉全市场**（tushare 支持单日全市场快照），每天仅约 7 次调用，远低于 2000 积分的频次上限；首次建库按年分段回溯。回测只读本地 DuckDB，不消耗积分。

**查询层按频率抽象（DataPortal）**：引擎迭代器与 `ctx.history` 统一经 DataPortal 取 bar，`freq="1d"` 读日线表、`freq="1m"`（未来）读分钟表；A股交易时段（09:30–11:30 / 13:00–15:00）内置在 DataPortal 的日历服务中，分钟级启用时直接可用。策略代码对频率无感知。

### 5.2 业务表（SQLite）

| 表 | 关键字段 |
|---|---|
| `users` | id, username, password_hash |
| `strategies` | id, name, code, params_json, description, created_at, updated_at |
| `backtest_runs` | id, strategy_id, status(pending/running/done/failed), config_json, metrics_json, result_dir, error, created_at, finished_at |
| `sim_accounts` | id, name, strategy_id, initial_cash, status(running/paused), created_at |
| `sim_orders` | id, account_id, signal_date, fill_date, symbol, side, qty, price, amount, fee, status(pending/filled/cancelled) |
| `sim_positions` | account_id, symbol, qty, avg_cost（物化当前持仓） |
| `sim_equity` | account_id, trade_date, total_value, cash, market_value（每日快照） |
| `sync_log` | source, table_name, last_trade_date, rows, status, synced_at |

回测明细（净值序列、成交、持仓历史）数据量大，存 `data/runs/{run_id}/` 下的 parquet + json，DB 只存摘要指标和路径。

---

## 6. 回测执行流程

```
前端提交(策略+配置) → 创建 backtest_run(pending)
  → 后台队列 → 子进程加载策略类 + 本地行情 → 逐 bar 迭代
  → 订单进 broker：次日开盘价 ± 滑点成交 → 扣费 → 记账
  → 每日结算净值 → 结束算绩效指标
  → 结果写 runs/{id}/，更新 DB → WebSocket 通知前端
```

**绩效指标**：总收益、年化收益、最大回撤、夏普、Sortino、Calmar、波动率、胜率、盈亏比、Alpha/Beta（对基准）、超额年化；净值曲线、回撤曲线、月度收益矩阵、成交明细、持仓历史。

---

## 7. 模拟交易设计

**与回测严格同构**——这是本平台最重要的设计承诺：模拟交易跑的就是回测引擎，同一策略、同一撮合与记账逻辑，只是注入不同的"触发器"与"行情馈送"。

### 7.1 两个可插拔接口（盘中运行的架构预留）

| 接口 | 职责 | 本期实现（M5） | 未来实现 |
|---|---|---|---|
| `Trigger` 触发器 | 决定"何时跑策略" | `DailyCronTrigger`：交易日 17:00 批处理 | `IntradayTimerTrigger`：交易时段常驻，分钟 bar 驱动 + `ctx.schedule` 定时点（如 14:00）真实触发 |
| `MarketDataFeed` 行情馈送 | 决定"价格从哪来" | `DailySnapshotFeed`：读本地 DuckDB 日线 | `RealtimeQuoteFeed`：盘中轮询/推送实时行情，同时落库为分钟 bar |

引擎主循环、订单生命周期（信号 → 挂起 → 下一 bar 确认成交）、记账与绩效逻辑**完全复用回测引擎**；盘中模式只是把 bar 粒度从"日"换成"分钟"、触发源从"cron"换成"盘中定时器"。**策略代码零修改**——今天写的日频策略里声明了 `ctx.schedule(at="14:00")`，未来接入实时源后自动变成真实的 14:00 成交。

### 7.2 本期（日频批处理）调度流程

每日调度（APScheduler，交易日）：

```
17:00 增量同步行情
  → 对每个 running 状态的 sim_account：
      ① 用前一信号日挂起的订单，按今日开盘价成交（与回测 next_open 一致）
      ② 结算今日净值快照
      ③ 以今日为当前 bar 跑策略 on_bar 与 schedule 回调（近似语义，见 4.2.1）→ 新订单挂起
  → WebSocket 推送账户更新
```

效果：模拟账户的成交假设与回测完全一致，**回测曲线与模拟曲线可直接对比**，策略有没有失效一眼可见。

### 7.3 未来盘中运行流程（设计示意，不在本期实现）

```
09:15  启动盘中会话：加载策略、恢复持仓与挂起订单
09:30–15:00  IntradayTimerTrigger 驱动：
   · 每根分钟 bar 收盘 → 确认挂起订单成交（分钟级 next_open 语义）
                       → 触发 on_bar（若策略声明分钟频率）
   · 到达 ctx.schedule 声明的时刻（如 14:00）→ 触发对应回调，ctx.price 取实时价
15:30  收盘结算：净值快照、日志归档、会话休眠
```

---

## 8. 后端 API 概览

```
POST   /api/auth/login
GET    /api/strategies            POST /api/strategies
GET    /api/strategies/{id}       PUT  /api/strategies/{id}      DELETE /api/strategies/{id}
POST   /api/strategies/{id}/validate        # 语法检查 + Param 提取（供前端表单）
GET    /api/backtests             POST /api/backtests            # 发起回测
GET    /api/backtests/{id}        GET  /api/backtests/{id}/series   # 净值/回撤序列
GET    /api/backtests/{id}/trades GET  /api/backtests/{id}/positions
GET    /api/sims                  POST /api/sims                 # 创建模拟账户
POST   /api/sims/{id}/start       POST /api/sims/{id}/stop
GET    /api/sims/{id}             GET  /api/sims/{id}/orders
GET    /api/data/status           POST /api/data/sync            # 手动触发同步
WS     /ws/backtests/{id}         # 进度与日志流
WS     /ws/sims/{id}              # 账户实时更新
```

---

## 9. 前端页面

| 路由 | 页面 | 内容 |
|---|---|---|
| `/login` | 登录 | 单用户密码 |
| `/strategies` | 策略列表 | 新建/复制/删除，最近回测状态 |
| `/strategies/{id}` | 策略编辑器 | Monaco（Python 高亮、自动补全 ctx）+ 右侧参数表单（由 Param 自动生成）+ 回测配置面板 + 运行按钮 |
| `/backtests/{id}` | 回测报告 | 指标卡、净值/回撤叠加基准图、月度收益热力图、成交与持仓明细表、运行日志 |
| `/sims` | 模拟交易 | 账户卡片（净值、当日盈亏、状态） |
| `/sims/{id}` | 账户详情 | 净值曲线 vs 回测曲线、当前持仓、订单流（含 pending）、策略日志 |
| `/data` | 数据管理 | 各表覆盖范围与最后同步日期、同步日志、手动同步按钮 |

---

## 10. 里程碑

| 里程碑 | 内容 | 验收标准 |
|---|---|---|
| **M1 数据管道** | 脚手架 + tushare 客户端 + 首次全量/每日增量同步 + DuckDB 查询层 | 本地能查任意个股/ETF/基金/指数的前复权日线 |
| **M2 引擎核心** | Strategy/Param/ctx/broker/metrics，命令行可跑回测 | 双均线示例跑出正确净值与指标，与已知结果对账 |
| **M3 后端服务** | 策略 CRUD、回测任务队列、WebSocket、JWT 登录 | Postman 全流程：建策略→回测→拿报告 |
| **M4 前端** | 登录、策略列表、编辑器、回测报告页、数据管理页 | 浏览器完成 M3 全流程 |
| **M5 模拟交易** | 调度器、虚拟账户、成交确认、账户监控页 | 策略挂模拟盘后自动每日运行，曲线与回测可比 |
| **M6 云部署** | docker-compose、Caddy HTTPS、数据卷、开机自启 | 公网域名访问，重启数据不丢 |

预留扩展（不在本期，接口已按 4.2.1 / 5.1 / 7.1 预留）：分钟级数据与撮合、盘中定时运行（如 14:00 真实成交）、参数寻优、因子研究、多账户。

---

## 11. 风险与开放问题

1. **tushare 频次**：按日全市场快照已规避；若首次建库触发限流，同步器内置退避重试，建库分天完成。
2. **场外基金回测真实性**：T+1 确认、申购赎回费打折等规则做了简化（配置化费率 + 次日净值成交），报告页会标注该假设。
3. **策略安全**：单人使用 + 子进程隔离足够；若未来开放给他人，需要引入真正的沙箱（如 RestrictedPython 或容器级隔离）。
4. **停牌/涨跌停**：M2 撮合对停牌（无当日数据）不成交；涨跌停不可成交规则放 M5 前补齐（避免模拟盘与回测假设不一致）。
5. **盘中实时行情源**：日频模拟不依赖实时行情；未来盘中模式需要稳定的实时源——候选为 akshare 实时快照（免费，但云 IP 有限流风险）、tushare 实时/分钟接口（需更高积分）、券商行情 API。届时按可用性实现 `RealtimeQuoteFeed` 即可，架构不受影响。
