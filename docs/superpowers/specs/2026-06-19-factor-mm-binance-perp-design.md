# Factor-Driven Market Making on Binance USDT-M Perpetuals — Design Spec

| 字段 | 值 |
|---|---|
| 状态 | Draft, awaiting user review |
| 日期 | 2026-06-19 |
| 作者 | wzh053 (协作:Claude) |
| 项目根 | `D:\vibe-coding\hummingbot-factor-mm\` |
| 实现框架 | Hummingbot v2 (Strategy V2 Controllers) |

---

## 1. 概述

### 1.1 项目意图

在 Hummingbot v2 框架之上,实现一个基于**简单 L1 因子(Micro-price + OBI)**做被动报价、并带**库存管理**与**多层风控**的做市 Controller,部署在东京 VPS,通过 Binance USDT-M 永续 testnet 完成完整的"接入实盘 → 看到数据 → 验证有效 → 上主网小额"闭环。

项目核心目的是**学习与验证**:让作者熟悉高频做市的实际操作面(订单簿、报价、库存、风控、运维),而非追求 PnL。主网阶段是可选的且永远小额。

### 1.2 范围

**包含(in scope):**

- 单品种 `BTC-USDT`(USDT-M 永续)
- 因子组合:Micro-price 偏移 + Order Book Imbalance(OBI)
- 三层库存控制(软 skew / 不对称报价 / 硬上限强制平仓)
- 中等档风控(Triple barrier / 日累损 kill / 速率限制 / 健康检查)
- VPS 部署(Vultr High Frequency Tokyo 或 AWS Lightsail Tokyo,源码安装 Hummingbot)
- Streamlit 自定义观测面板,补 Hummingbot 自带 dashboard 之缺
- Binance Futures Testnet 为默认环境,主网为可选 Go/No-go 后启用

**排除(out of scope):**

- 多品种 / 跨品种对冲
- L2/L3 订单簿因子(只用 L1)
- 自适应参数 / 在线学习 / 强化学习
- 跨交易所套利(Hummingbot 支持,本项目不做)
- 回测(本项目走 testnet 实盘代替;真要回测时另起 Nautilus Trader 项目)
- 现货 / 期权 / 其它金融产品
- A 股 / 期货 CTP / 外汇等非加密市场

### 1.3 关键约束

| # | 约束 | 来源 |
|---|---|---|
| C1 | Hummingbot v2 Controller 框架 | 用户选定 |
| C2 | Binance USDT-M Perpetual + Testnet 优先 | 用户选定 |
| C3 | 单品种 BTC-USDT | 用户选定 |
| C4 | 频率:100ms ~ 秒级(L1 驱动) | 用户选定 |
| C5 | 因子:Micro-price + OBI 加权 | 用户选定 |
| C6 | 部署:Tokyo VPS,源码安装 | 用户选定 |
| C7 | 数据可见:Hummingbot 自带 + Streamlit 自建 | 用户选定 |
| C8 | API key 严禁入 git;主网仅在 Go/No-go 通过后小额 | 项目规则 |
| C9 | 不为"假设未来需求"做过度抽象(YAGNI) | 项目规则 |
| C10 | 不引入对 Hummingbot 私有 API 的修改 / monkey-patch | 项目规则 |

### 1.4 成功标准

短期(M5 完成时):

- testnet 上 bot 能 7×24 跑、报价随因子变化、库存自动回归、面板实时显示

中期(M8 完成时):

- 通过 Go/No-go 评审清单(见 §10.3)的全部 8 项

长期(M9 完成后):

- 主网小额运行 ≥ 1 周无重大事故
- 形成"因子失效 → testnet 再调"的可重复研究循环

---

## 2. 术语表

| 术语 | 含义 |
|---|---|
| Hummingbot v2 | Hummingbot 的 Strategy V2 框架,以 Controller / Executor 为核心 |
| Controller | Strategy V2 的策略编排单元,继承 `ControllerBase` 或其子类 |
| Executor | 执行单元,封装具体仓位 / 订单生命周期(`PositionExecutor`、`DCAExecutor` 等) |
| `MarketMakingControllerBase` | 做市 Controller 基类,提供 buy/sell spreads 配置与执行编排 |
| Mid | `(best_bid + best_ask) / 2` |
| Micro-price | 按量加权的中间价:`(bid_px·ask_qty + ask_px·bid_qty) / (bid_qty + ask_qty)` |
| OBI | Order Book Imbalance,`(bid_qty − ask_qty) / (bid_qty + ask_qty) ∈ [-1, 1]` |
| Reservation price | A-S 文献术语,带库存惩罚的"内在中间价",报价围绕它对称展开 |
| Skew | 报价相对 mid 的偏移方向 / 幅度 |
| Triple barrier | 单笔仓位的止损 / 止盈 / 时限三合一退出机制 |
| Kill switch | 全局停止下单的开关,触发后只能人工 restart 重置 |
| bp | basis point,1 bp = 0.01% |
| testnet | Binance Futures Testnet,模拟环境,无真实资金 |

---

## 3. 整体架构

### 3.1 部署拓扑

```
┌──────────────────────────────────────────────────────────────────┐
│  Vultr High Frequency Tokyo (Ubuntu 22.04, 2C/4G)                │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ systemd: hummingbot.service                                 │ │
│  │   /opt/hummingbot/  (conda env, source install)             │ │
│  │   ├── bin/hummingbot_quickstart.py                          │ │
│  │   ├── controllers/market_making/factor_mm_btc_perp.py ◄─ 软链│ │
│  │   ├── conf/controllers/factor_mm_btc.yml             ◄─ 软链│ │
│  │   ├── conf/connectors/binance_perpetual_testnet.yml         │ │
│  │   ├── data/  (Hummingbot 自带 sqlite + logs)                │ │
│  │   └── data/factor_metrics.sqlite ◄─ 我们的因子/库存指标     │ │
│  │ 连接 → Binance USDT-M Futures TESTNET (WebSocket + REST)    │ │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ systemd: factor-dashboard.service                           │ │
│  │   streamlit run dashboard/app.py                            │ │
│  │   --server.address=127.0.0.1 --server.port=8501             │ │
│  │   只读 factor_metrics.sqlite + Hummingbot trades.sqlite     │ │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  时钟:chrony      防火墙:ufw(仅开 22)      远程:Tailscale    │
└──────────────────────────────────────────────────────────────────┘
        ▲                                          ▲
        │ SSH(端口改非 22 / 仅密钥登录)            │ Tailscale IP:8501
        │                                          │
   开发机 Windows                              开发机浏览器
   D:\vibe-coding\hummingbot-factor-mm\
   ├── controllers/market_making/factor_mm_btc_perp.py
   ├── conf/controllers/factor_mm_btc.yml.example
   ├── dashboard/app.py
   ├── tests/...
   └── deploy/  (bootstrap、systemd unit、部署脚本)
   git push → VPS git pull → systemctl restart
```

### 3.2 数据流

```
Binance WS (book ticker / depth5)
        │
        ▼
Hummingbot MarketDataProvider
        │
        ├─► (基类拉) update_processed_data()
        │       │
        │       ├─► 计算 micro_price + OBI
        │       ├─► 算 inventory_skew (用 get_current_base_position)
        │       ├─► 写 processed_data = {reference_price, spread_multiplier}
        │       └─► _emit_metrics → factor_metrics.sqlite
        │
        └─► (基类) determine_executor_actions()
                │
                ├─► create_actions_proposal()
                │       └─► get_executor_config(level_id, price, amount)
                │               └─► PositionExecutorConfig(triple_barrier, leverage, ...)
                │
                ├─► stop_actions_proposal()
                └─► executors_to_early_stop() ◄── 我们 override,接日累损 kill
                        │
                        ▼
                Binance REST(下单 / 撤单 / 改单)


            ┌── Hummingbot 自带 sqlite ──► Hummingbot dashboard(账户、订单、PnL)
其它路径 ──┤
            └── factor_metrics.sqlite ────► Streamlit 自建面板(因子、skew、库存、kill)
```

### 3.3 关键操作约束

| # | 约束 | 实现 / 验证方式 |
|---|---|---|
| O1 | API key 永不入 git | `.gitignore` 排除 `conf/connectors/`;CI 不必要 |
| O2 | Binance API 配 IP 白名单 = VPS 公网 IP | 后台手工设;在 README 强调 |
| O3 | API key 权限最小:读 + 期货下单,**关闭提币** | Binance 后台 |
| O4 | Dashboard 仅监听 127.0.0.1,经 Tailscale 访问 | systemd unit 强制 `--server.address=127.0.0.1` |
| O5 | 时钟漂移 > 500ms 自动 halt | `update_processed_data` 顶部健康检查 |
| O6 | OrderBook 新鲜度 > 2.0s 自动 halt | 同上 |
| O7 | 代码部署:开发机 push → VPS pull,**禁止 VPS 上 edit** | 流程纪律,README 申明 |
| O8 | systemd auto-restart 兜底崩溃 | `Restart=always` |
| O9 | 数据持久化:每日 cron rsync `data/` 出 VPS | 由用户配置,本 spec 不强制 |

---

## 4. Controller 设计

### 4.1 文件落点

```
D:\vibe-coding\hummingbot-factor-mm\
└── controllers/market_making/factor_mm_btc_perp.py   (核心类)
└── conf/controllers/factor_mm_btc.yml.example         (参数模板,入 git)
└── conf/controllers/factor_mm_btc.yml                 (实际配置,不入 git)
```

VPS 端通过软链接进入 Hummingbot 树:

```
ln -sf ~/factor-mm/controllers/market_making/factor_mm_btc_perp.py \
       ~/hummingbot/controllers/market_making/factor_mm_btc_perp.py
ln -sf ~/factor-mm/conf/controllers/factor_mm_btc.yml \
       ~/hummingbot/conf/controllers/factor_mm_btc.yml
```

### 4.2 Config 类

继承 `MarketMakingControllerConfigBase`,**仅新增 7 个字段**,所有止损 / 止盈 / 杠杆 / spread / cooldown 复用基类。

```python
from decimal import Decimal
from pydantic import Field
from hummingbot.strategy_v2.controllers.market_making_controller_base import (
    MarketMakingControllerConfigBase,
)


class FactorMMConfig(MarketMakingControllerConfigBase):
    controller_name: str = "factor_mm_btc_perp"
    connector_name: str = "binance_perpetual_testnet"
    trading_pair:   str = "BTC-USDT"

    # ── 新增:因子参数 ──
    obi_weight:             Decimal = Field(default=Decimal("0.5"))     # OBI 占比,Micro-price 占 1-obi_weight
    factor_scale_bps:       Decimal = Field(default=Decimal("2"))       # 因子 → 报价偏移换算 (bp of mid)
    inventory_target:       Decimal = Field(default=Decimal("0"))       # 库存目标(BTC 净敞口)
    inventory_penalty_bps:  Decimal = Field(default=Decimal("3"))       # 库存偏离 → 报价惩罚 (bp of mid per 1 BTC)
    inventory_soft_cap:     Decimal = Field(default=Decimal("0.01"))    # 触发不对称报价
    inventory_hard_cap:     Decimal = Field(default=Decimal("0.02"))    # 触发强制平仓

    # ── 新增:风控参数 ──
    daily_loss_limit_usdt:  Decimal = Field(default=Decimal("50"))      # 日累损 kill 阈值
    max_actions_per_minute: int     = Field(default=30)                 # 全局发单速率上限
    max_orderbook_age_sec:  float   = Field(default=2.0)
    max_clock_drift_sec:    float   = Field(default=0.5)
```

**约定:** 复用基类的 `stop_loss / take_profit / time_limit / leverage / cooldown_time / buy_spreads / sell_spreads / buy_amounts_pct / sell_amounts_pct / executor_refresh_time`,不重定义。

> [需 testnet 验证] `MarketMakingControllerConfigBase` 在 master 分支的精确字段以拉取时为准;以上字段名引用自本 spec 撰写时的 GitHub 主分支抽样。Pydantic 版本(v1 / v2)按 Hummingbot 当前要求,可能需 `field_validator` 而非 `validator`。

### 4.3 核心方法:`update_processed_data`

这是 controller 的"心脏"。基类默认实现把 `reference_price = mid` 写入 `processed_data`;我们替换为因子 + 库存合成的 reservation price。

```python
import time
from decimal import Decimal
from hummingbot.strategy_v2.controllers.market_making_controller_base import (
    MarketMakingControllerBase,
)


class FactorMMBtcPerp(MarketMakingControllerBase):

    def __init__(self, config: FactorMMConfig, *args, **kwargs):
        super().__init__(config, *args, **kwargs)
        self.config = config
        self._action_log: list[float] = []           # 全局发单时间戳,用于速率限制
        self._kill_switch_engaged: bool = False
        self._exch_server_time_cache: tuple[float, float] = (0.0, 0.0)  # (local_ts, server_ts)

    # ─────────────────────────────────────────────────────────────
    async def update_processed_data(self) -> None:
        # 1. 健康检查(任一失败 → halt + 空报价)
        if not self._health_check_ok():
            self._set_halt_state()
            return

        # 2. kill switch
        if self._kill_switch_engaged or self._check_daily_loss_breach():
            self._set_halt_state()
            return

        # 3. 抓 L1
        ob = self.market_data_provider.get_order_book(
            self.config.connector_name, self.config.trading_pair
        )
        bid_px = Decimal(str(ob.bids[0].price))
        bid_qty = Decimal(str(ob.bids[0].amount))
        ask_px = Decimal(str(ob.asks[0].price))
        ask_qty = Decimal(str(ob.asks[0].amount))
        if bid_qty + ask_qty == 0:
            self._set_halt_state()
            return
        mid = (bid_px + ask_px) / 2

        # 4. 因子
        micro_price = (bid_px * ask_qty + ask_px * bid_qty) / (bid_qty + ask_qty)
        micro_signal = (micro_price - mid) / mid          # 价格比例,典型 1e-5 ~ 1e-4
        obi = (bid_qty - ask_qty) / (bid_qty + ask_qty)   # 无量纲, [-1, 1]
        # OBI 乘 1bp 把它放到与 micro_signal 同量纲(都是 mid 的比例)
        obi_as_pct = obi * Decimal("0.0001")
        factor = (
            (Decimal("1") - self.config.obi_weight) * micro_signal
            + self.config.obi_weight * obi_as_pct
        )

        # 5. 库存惩罚
        net_base = Decimal(str(self.get_current_base_position()))  # BTC 净仓
        inv_dev = net_base - self.config.inventory_target
        inv_skew = -inv_dev * self.config.inventory_penalty_bps * mid / Decimal("10000")

        # 6. 因子 skew
        factor_skew = factor * self.config.factor_scale_bps * mid

        # 7. 写 processed_data
        reference_price = mid + factor_skew + inv_skew
        self.processed_data = {
            "reference_price":   reference_price,
            "spread_multiplier": Decimal("1"),
        }

        # 8. L2 / L3 库存控制(覆写 processed_data 的 amount 倾斜)
        self._apply_inventory_tiers(net_base)

        # 9. 落 metrics
        self._emit_metrics(
            mid=mid, micro_price=micro_price, obi=obi, factor=factor,
            net_base=net_base, factor_skew=factor_skew, inv_skew=inv_skew,
            ob_age_sec=self._last_ob_age, clock_drift_sec=self._last_clock_drift,
        )

    # ─────────────────────────────────────────────────────────────
    def get_executor_config(self, level_id: str, price: Decimal, amount: Decimal):
        from hummingbot.strategy_v2.executors.position_executor.data_types import (
            PositionExecutorConfig,
        )
        return PositionExecutorConfig(
            timestamp=self.market_data_provider.time(),
            level_id=level_id,
            connector_name=self.config.connector_name,
            trading_pair=self.config.trading_pair,
            entry_price=price,
            amount=amount,
            triple_barrier_config=self.config.triple_barrier_config,
            leverage=self.config.leverage,
            side=self.get_trade_type_from_level_id(level_id),
        )

    # ─────────────────────────────────────────────────────────────
    def executors_to_early_stop(self):
        from hummingbot.strategy_v2.models.executor_actions import StopExecutorAction
        if self._kill_switch_engaged:
            return [
                StopExecutorAction(executor_id=e.id, controller_id=self.config.id)
                for e in self.get_active_executors()
            ]
        return []
```

> [需 testnet 验证] `PositionExecutorConfig` 的 import 路径、`triple_barrier_config` 的 field 名、`active_executors` 是属性还是方法,均以当前 Hummingbot 主分支为准;以上引用为撰写时观察。

### 4.4 设计决策与理由

| # | 决策 | 理由 |
|---|---|---|
| D1 | 因子 + 库存合成**一条** reservation price,而非两条并行 quote 公式 | Avellaneda-Stoikov 框架,数学一致、可解释 |
| D2 | 仅 override `update_processed_data` + `get_executor_config`(+ `executors_to_early_stop`) | 最少介入基类,后续 Hummingbot 升级冲突面小 |
| D3 | 库存来源:`get_current_base_position()` 而非自跟踪 | 避免与基类状态机漂移 |
| D4 | 风控走 `triple_barrier_config`,不在 controller 内部写仓位级风控 | 复用 `PositionExecutor` 内置逻辑 |
| D5 | factor / inv_skew 全部以 bp 表示,内部按比例换算 | 消除量纲歧义,日志直读 |
| D6 | OBI 乘 `0.0001` 与 micro_signal 同尺度,而非各自加独立缩放系数 | 减少调参维度;真要解耦再加 |
| D7 | metrics 写到独立 sqlite,**不动** Hummingbot 自身 sqlite schema | 隔离升级风险,面板独立演进 |
| D8 | metrics 1 Hz 下采样(非每 tick) | tick 量太大;1 Hz 已足够看趋势 |

### 4.5 复杂度估算

| 部分 | 代码量 | 实现风险 |
|---|---:|---|
| `FactorMMConfig` | ~25 行 | 低 |
| `update_processed_data` + 辅助方法 | ~80 行 | 中(因子量纲调试) |
| `get_executor_config` | ~12 行 | 低 |
| `executors_to_early_stop` + kill 状态机 | ~20 行 | 低 |
| `_emit_metrics` + sqlite schema | ~50 行 | 低 |
| `_health_check_ok` + 时钟/新鲜度 | ~30 行 | 中(`_exchange_server_time` 调用频率) |
| `_apply_inventory_tiers`(L2 不对称) | ~30 行 | 中 |
| **合计** | **~250 行** | 调参 > 编码 |

---

## 5. 库存管理

### 5.1 三层渐进式

| 层级 | 触发条件 | 行为 | 实现 |
|---|---|---|---|
| **L1 软 skew** | 始终生效 | 库存偏离 → 报价反向偏移(吸引对侧、推开同侧) | `update_processed_data` 的 `inv_skew` |
| **L2 不对称报价** | `|net_base| > inventory_soft_cap` | 偏离侧 `*_amounts_pct` 按比例压缩,反方向放大 | `_apply_inventory_tiers` 改 `processed_data` 中的 amounts |
| **L3 硬上限 + 强制平仓** | `|net_base| > inventory_hard_cap` | 撤所有非平仓单 + 发市价 `OrderExecutor` 拉回 `inventory_target` | `executors_to_early_stop` + 额外 `CreateExecutorAction` |

### 5.2 L2 不对称报价细节

```python
def _apply_inventory_tiers(self, net_base: Decimal) -> None:
    cap = self.config.inventory_soft_cap
    if abs(net_base) <= cap:
        return  # L1 阶段,基类对称报价

    # 偏离比例 0..1(到 hard_cap 时为 1)
    ratio = min(
        (abs(net_base) - cap) / (self.config.inventory_hard_cap - cap),
        Decimal("1"),
    )
    # 压制系数:偏离侧 amount × (1 - 0.5*ratio);反方向 × (1 + 0.5*ratio)
    suppress = Decimal("1") - Decimal("0.5") * ratio
    expand   = Decimal("1") + Decimal("0.5") * ratio

    if net_base > 0:        # 净多 → 压买、扩卖
        self.processed_data["buy_amounts_factor"]  = suppress
        self.processed_data["sell_amounts_factor"] = expand
    else:                   # 净空 → 反之
        self.processed_data["buy_amounts_factor"]  = expand
        self.processed_data["sell_amounts_factor"] = suppress
```

> [需 testnet 验证] 基类是否暴露 `buy_amounts_factor` / `sell_amounts_factor` 这类 hook;若不直接支持,改在 `get_price_and_amount` 上 override(基类该方法在文档中明确为公开 utility)。

### 5.3 L3 硬上限强制平仓

`executors_to_early_stop` 的扩展版本:

```python
def executors_to_early_stop(self):
    actions = []
    if self._kill_switch_engaged:
        actions.extend(self._stop_all_active())
        return actions

    net_base = Decimal(str(self.get_current_base_position()))
    if abs(net_base) > self.config.inventory_hard_cap:
        # 撤所有非平仓单
        actions.extend(self._stop_all_active())
        # 由 update_processed_data 顶部检测到 hard cap 时发 OrderExecutor 平仓
        self._pending_force_flatten = True
    return actions
```

`_pending_force_flatten` 在下一次 `determine_executor_actions` 中转为 `CreateExecutorAction(OrderExecutorConfig(side=opposite, amount=|inv_dev|, order_type=MARKET))`。

> [需 testnet 验证] `OrderExecutorConfig` 的 import 路径和字段,以及如何从 controller 主动注入 `CreateExecutorAction`(而非靠 `create_actions_proposal` 自然出单)。可能需要 override `determine_executor_actions` 而非仅 `executors_to_early_stop`。

### 5.4 关键阈值

| 参数 | 默认 | 调参影响 |
|---|---:|---|
| `inventory_target` | 0 BTC | 长期偏置;0 表示中性 |
| `inventory_penalty_bps` | 3 bp / BTC | L1 软 skew 的"弹簧硬度" |
| `inventory_soft_cap` | 0.01 BTC | L2 触发点 |
| `inventory_hard_cap` | 0.02 BTC | L3 触发点;**= testnet 上 1 个标准合约单位级别** |

> 注:数值单位是"bp of mid 每单位 base 偏离 × 10000"。`penalty_bps=300` 在 soft_cap (0.01 BTC) 偏离时产生约 3 bp 的报价偏移(`-0.01 * 300 * mid / 10000`)。spec §4.2 默认值 300 与此一致。

---

## 6. 风控

### 6.1 四个机制

| # | 机制 | 来源 |
|---|---|---|
| R1 | Per-position triple barrier(止损 / 止盈 / 时限) | 基类 `triple_barrier_config` |
| R2 | 日累损 kill switch | 自定义 `executors_to_early_stop` |
| R3 | 全局发单速率上限 | 自定义 `_rate_limit_ok` |
| R4 | 时钟漂移 + 数据新鲜度健康检查 | 自定义 `_health_check_ok` |

### 6.2 R1:Triple barrier

YAML:

```yaml
stop_loss:   0.005    # 0.5%
take_profit: 0.003    # 0.3%
time_limit:  300      # 秒
```

做市场景中:`take_profit < stop_loss`(我们已经收了点差,愿意给行情更长止损半径)。
`time_limit` 强制避免"无限持仓"——若 5 分钟内没走到 TP/SL,平仓让下一笔重新评估。

### 6.3 R2:日累损 kill switch

判定:

```python
def _check_daily_loss_breach(self) -> bool:
    today_pnl = self._read_daily_pnl_from_sqlite()  # 读 Hummingbot trades.sqlite,按 UTC 日聚合
    if today_pnl < -self.config.daily_loss_limit_usdt:
        if not self._kill_switch_engaged:
            self.logger().critical(
                f"KILL SWITCH ENGAGED: daily PnL {today_pnl} < -{self.config.daily_loss_limit_usdt}"
            )
        self._kill_switch_engaged = True
    return self._kill_switch_engaged
```

Kill 后:

- `update_processed_data` 顶部就 return halt 状态
- `executors_to_early_stop` 撤掉所有活跃 executor
- **只能 `systemctl restart hummingbot` 重置**(刻意不自动恢复)

### 6.4 R3:发单速率上限

防的不是策略本身,而是**因子量纲算错 / 数据异常 → 失控发单**。这种事故出过太多次,加个软上限非常便宜。

```python
def _rate_limit_ok(self) -> bool:
    now = time.time()
    self._action_log = [t for t in self._action_log if now - t < 60]
    if len(self._action_log) >= self.config.max_actions_per_minute:
        self.logger().warning(
            f"Rate limited: {len(self._action_log)} actions in last 60s"
        )
        return False
    return True
```

在 `create_actions_proposal` 调用之前调用(可能需在 `determine_executor_actions` 上做轻量 wrap)。

### 6.5 R4:健康检查

```python
def _health_check_ok(self) -> bool:
    now = time.time()
    # 4.1 OrderBook 新鲜度
    ob = self.market_data_provider.get_order_book(
        self.config.connector_name, self.config.trading_pair
    )
    self._last_ob_age = now - getattr(ob, "snapshot_uid_time", now)
    if self._last_ob_age > self.config.max_orderbook_age_sec:
        self.logger().error(f"OrderBook stale: {self._last_ob_age:.2f}s")
        return False

    # 4.2 时钟漂移(每 5 分钟刷一次缓存)
    local_ts, server_ts = self._exch_server_time_cache
    if now - local_ts > 300:
        server_ts = self._fetch_exchange_server_time()
        self._exch_server_time_cache = (now, server_ts)
    drift_now = abs(now - (server_ts + (now - local_ts)))
    self._last_clock_drift = drift_now
    if drift_now > self.config.max_clock_drift_sec:
        self.logger().error(f"Clock drift: {drift_now:.3f}s")
        return False

    return True
```

> [需 testnet 验证] Hummingbot OrderBook 对象上获取最新 snapshot 时间戳的精确属性名(可能是 `last_diff_uid` / `snapshot_uid` / `update_id` + 时间映射)。以 dev session 时拉文档为准。

### 6.6 全部风控参数表

| 参数 | 默认 | 说明 |
|---|---:|---|
| `stop_loss` | 0.005 | 单仓位止损 0.5% |
| `take_profit` | 0.003 | 单仓位止盈 0.3% |
| `time_limit` | 300 s | 单仓位最长持有 5 分钟 |
| `cooldown_time` | 15 s | 同 level 撤后再发间隔(基类) |
| `daily_loss_limit_usdt` | 50 USDT | 日累损 kill |
| `max_actions_per_minute` | 30 | 全局发单速率上限 |
| `max_orderbook_age_sec` | 2.0 s | 数据新鲜度上限 |
| `max_clock_drift_sec` | 0.5 s | 时钟漂移上限 |
| `inventory_soft_cap` | 0.01 BTC | L2 触发 |
| `inventory_hard_cap` | 0.02 BTC | L3 触发 |

### 6.7 刻意不做的事(YAGNI)

- **不写自适应止损 / 波动率自适应 spread**:V1 已有的调参信号足够多,再加自适应等于两层不确定性互相干扰
- **不写复杂的"分钟级别 PnL 滑动止损"**:日累损已经是兜底,中间梯度引入更多 false positive
- **不写自动重启 / 恢复逻辑**:kill 后人工介入,避免"自动恢复又自动 kill 又自动恢复"的循环

---

## 7. 部署

### 7.1 仓库布局

```
D:\vibe-coding\hummingbot-factor-mm\
├── controllers/market_making/
│   └── factor_mm_btc_perp.py
├── conf/
│   ├── controllers/
│   │   └── factor_mm_btc.yml.example         (入 git)
│   └── connectors/
│       └── binance_perpetual_testnet.yml     (.gitignore)
├── dashboard/
│   ├── app.py                                (Streamlit)
│   └── queries.py                            (sqlite 读取层)
├── deploy/
│   ├── bootstrap_vps.sh
│   ├── hummingbot.service
│   ├── factor-dashboard.service
│   └── pull_and_restart.sh
├── tests/
│   ├── test_factor_math.py
│   ├── test_controller.py
│   └── conftest.py                           (mock market_data_provider)
├── docs/superpowers/specs/
│   └── 2026-06-19-factor-mm-binance-perp-design.md   (本文件)
├── .gitignore
├── pyproject.toml
└── README.md
```

`.gitignore` 关键项:

```
conf/connectors/
data/
__pycache__/
*.pyc
.pytest_cache/
.venv/
```

### 7.2 `bootstrap_vps.sh`(关键步骤)

幂等,跑两次不会破坏:

```bash
#!/usr/bin/env bash
set -euo pipefail

# 0. 基础工具 + 时钟
apt update && apt install -y git ufw chrony unattended-upgrades
systemctl enable --now chrony
timedatectl set-ntp true

# 1. 防火墙
ufw default deny incoming
ufw allow OpenSSH
ufw --force enable

# 2. Tailscale
curl -fsSL https://tailscale.com/install.sh | sh
# tailscale up 需人工跑

# 3. Hummingbot 源码 + miniconda
useradd -m -s /bin/bash botuser || true
sudo -u botuser bash <<'EOF'
cd ~
[ -d miniconda3 ] || (
  wget -qO m.sh https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
  bash m.sh -b -p ~/miniconda3 && rm m.sh
)
[ -d hummingbot ] || git clone https://github.com/hummingbot/hummingbot.git
cd hummingbot && ./install
source ~/miniconda3/etc/profile.d/conda.sh && conda activate hummingbot
./compile
EOF

# 4. 我们仓库 + 软链
sudo -u botuser bash <<'EOF'
cd ~ && [ -d factor-mm ] || git clone <YOUR_GIT_URL> factor-mm
ln -sf ~/factor-mm/controllers/market_making/factor_mm_btc_perp.py \
       ~/hummingbot/controllers/market_making/factor_mm_btc_perp.py
EOF

# 5. systemd
cp deploy/hummingbot.service /etc/systemd/system/
cp deploy/factor-dashboard.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable hummingbot factor-dashboard
```

### 7.3 systemd units

`deploy/hummingbot.service`:

```ini
[Unit]
Description=Hummingbot factor MM (BTC perp testnet)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=botuser
WorkingDirectory=/home/botuser/hummingbot
ExecStart=/home/botuser/miniconda3/envs/hummingbot/bin/python \
          bin/hummingbot_quickstart.py -f conf/controllers/factor_mm_btc.yml
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

`deploy/factor-dashboard.service`:

```ini
[Unit]
Description=Factor MM dashboard (Streamlit)
After=network-online.target

[Service]
Type=simple
User=botuser
WorkingDirectory=/home/botuser/factor-mm
ExecStart=/home/botuser/miniconda3/envs/hummingbot/bin/streamlit \
          run dashboard/app.py --server.address=127.0.0.1 --server.port=8501
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 7.4 API key 管理

1. `conf/connectors/binance_perpetual_testnet.yml` **永远** 在 `.gitignore`
2. Binance API 后台:
   - IP 白名单 = VPS 公网 IP
   - 关闭提币权限
   - 仅勾"读 + 期货下单"
3. VPS 端 `chmod 600 conf/connectors/*.yml`,只有 `botuser` 可读

初次配置:

```bash
ssh botuser@<vps-ip>
cd ~/hummingbot
./bin/hummingbot_quickstart.py
> connect binance_perpetual_testnet
# 粘贴 API key / secret(CLI 帮你写到 conf/connectors/...)
> exit
systemctl start hummingbot factor-dashboard
journalctl -u hummingbot -f
```

### 7.5 部署流程

```
开发机:                          VPS:
─────────                        ─────
edit controller / dashboard
pytest                          
git push                ────►   git pull
                                systemctl restart hummingbot
                                systemctl restart factor-dashboard
                                journalctl -u hummingbot -f
```

`deploy/pull_and_restart.sh`(VPS 上):

```bash
#!/usr/bin/env bash
set -euo pipefail
cd ~/factor-mm
git pull --ff-only
sudo systemctl restart hummingbot factor-dashboard
sudo journalctl -u hummingbot -f
```

---

## 8. 观测面板(Streamlit)

### 8.1 设计原则

- **只显示 Hummingbot 自带 dashboard 不显示的东西**:因子值、库存倾斜、kill 状态。不重复造账户 / 订单视图。
- **只读**,挂了不影响交易
- **2 秒刷新**,直接 `pd.read_sql` 读 sqlite
- 全部 Plotly,无 enterprise 组件依赖

### 8.2 布局

```
┌─────────────────────────────────────────────────────────────────┐
│ Factor MM · BTC-USDT Perp · TESTNET            ● Kill: OFF       │
├─────────────────────────────────────────────────────────────────┤
│ 顶栏 6 个 Big Number:                                            │
│   Mid: 65,432.10     │  Net Base: +0.0032 BTC  │  Daily PnL: -3.21│
│   Factor: +0.18 bp   │  Reservation: 65,432.22 │  Actions/60s: 12 │
├─────────────────────────────────────────────────────────────────┤
│ 行 1:因子时间序列(双 y 轴)                                     │
│   ├─ Micro-price signal (bp,左轴)                              │
│   └─ OBI (无量纲,右轴)                                          │
├─────────────────────────────────────────────────────────────────┤
│ 行 2:库存 + skew 时间序列                                       │
│   ├─ Net base position (BTC)                                    │
│   ├─ factor_skew (bp) ─ 蓝                                      │
│   └─ inventory_skew (bp) ─ 橙                                   │
├─────────────────────────────────────────────────────────────────┤
│ 行 3:风控指标                                                   │
│   ├─ Orderbook age(警戒线 max_orderbook_age_sec)               │
│   ├─ Clock drift(警戒线 max_clock_drift_sec)                   │
│   └─ Actions per minute(警戒线 max_actions_per_minute)          │
├─────────────────────────────────────────────────────────────────┤
│ 行 4:最近 50 笔 fills 表格(从 Hummingbot trades.sqlite 读)    │
└─────────────────────────────────────────────────────────────────┘
```

颜色规则:负数红、正数绿、kill ON 时整个顶栏背景变红。

### 8.3 SQLite schema

`data/factor_metrics.sqlite`:

```sql
CREATE TABLE IF NOT EXISTS metrics (
  ts                  INTEGER PRIMARY KEY,   -- unix ms
  mid                 REAL,
  micro_price         REAL,
  obi                 REAL,
  factor_bp           REAL,
  net_base            REAL,
  factor_skew_bp      REAL,
  inv_skew_bp         REAL,
  reference_price     REAL,
  ob_age_sec          REAL,
  clock_drift_sec     REAL,
  actions_60s         INTEGER,
  kill_engaged        INTEGER
);
CREATE INDEX IF NOT EXISTS idx_metrics_ts ON metrics(ts);
```

`_emit_metrics` 在 controller 内以 1 Hz 写入(if `now - last_write_ts >= 1.0`)。

### 8.4 access

Dashboard 仅监听 `127.0.0.1:8501`。开发机经 Tailscale 访问 `http://<vps-tailscale-ip>:8501`。**不**暴露公网。

---

## 9. 测试策略

### 9.1 测试金字塔

| 层 | 数量 | 工具 | 跑多久 |
|---|---:|---|---|
| 单元测试(纯函数) | 8 | pytest | 秒级 |
| 集成测试(mock provider) | 3 | pytest + 假数据 | 数秒 |
| Live testnet 冒烟 | 1 周挂机 | 真 Binance testnet | 7 天 |
| Live testnet 调参 | 1 周 | 真 Binance testnet | 7 天 |

**Hummingbot 自身的代码不重复测**;只测我们的 8 个核心断言。

### 9.2 单元测试(`tests/test_factor_math.py`)

```python
def test_micro_price_equal_qty_returns_mid(): ...
def test_micro_price_skewed_toward_thicker_side(): ...
def test_micro_price_zero_qty_does_not_crash(): ...
def test_obi_boundary_values(): ...
def test_factor_unit_consistency(): ...
def test_inventory_skew_sign(): ...
def test_reservation_price_monotonic_in_factor(): ...
def test_reservation_price_monotonic_in_inventory(): ...
```

策略:把 `update_processed_data` 中的纯计算抽出来到模块级函数(`compute_factor`, `compute_inventory_skew`, `compute_reservation_price`),controller 只做编排。这样单测无需 mock 任何 Hummingbot 对象。

### 9.3 集成测试(`tests/test_controller.py`)

`conftest.py` 提供 `FakeMarketDataProvider`,接受任意 L1 状态 + 当前净仓 + 当日 PnL 注入。

```python
def test_update_processed_data_reference_in_range(fake_provider):
    # 给定 bid/ask,reference_price 落在 (bid, ask) 内
    ...

def test_kill_switch_engages_on_daily_loss(fake_provider):
    fake_provider.set_daily_pnl(-100)
    ctrl = make_controller(daily_loss_limit_usdt=50)
    await ctrl.update_processed_data()
    assert ctrl._kill_switch_engaged
    assert ctrl.processed_data["spread_multiplier"] == 0

def test_health_check_halts_on_stale_book(fake_provider):
    fake_provider.set_ob_age(3.0)
    ctrl = make_controller(max_orderbook_age_sec=2.0)
    await ctrl.update_processed_data()
    assert ctrl.processed_data["spread_multiplier"] == 0
```

### 9.4 不写的测试

- **不写 e2e "下单 → 撮合 → PnL 写库"**:testnet 本身就是这个测试,代价低
- **不写"systemd 单元正确启动"**:M3 里程碑的手动 smoke 替代
- **不写 Hummingbot 升级回归套件**:每次升级前先在 testnet 跑 1 天即可

---

## 10. 实施里程碑

### 10.1 里程碑表

| M | 名称 | Done 标准 | 预估 |
|---|---|---|---:|
| **M0** | 仓库脚手架 | `pyproject.toml` + `.gitignore` + 空骨架 + README + `pytest` 能空跑 | 1 h |
| **M1** | 因子数学 + 单测 | 纯函数版 + §9.2 的 8 个单测全绿;TDD | 3 h |
| **M2** | Controller 类 + 集成测 | 完整 controller + §9.3 的 3 个 mock 集成测全绿;**不连交易所** | 4 h |
| **M3** | VPS 引导 + Hummingbot 装机 | `bootstrap_vps.sh` 跑完、CLI 能 `status`、paper-mode | 3 h |
| **M4** | testnet 接入 + 首次挂单 | API key 配好、journal 看到第一对 buy/sell limit | 2 h |
| **M5** | metrics 落库 + Streamlit 面板 | 4 行图都有数据、刷新流畅、kill 灯能切红 | 4 h |
| **M6** | 1 周 testnet 冒烟 | 7×24 无崩溃、无 OOM、无 API ban、kill 至少人工触发一次有效 | 7 天挂机 |
| **M7** | 1 周 testnet 调参 + 评估 | 调四个核心参数 + 评估报告(PnL/命中率/库存分布/kill 次数) | 7 天 |
| **M8** | **Go/No-go review** | §10.3 全 YES | 1 h 评审 |
| **M9** | 主网小额(可选) | 主网 connector 切换;初始资金 ≤ 200 USDT;杠杆 ≤ 3x;1 周 | 7 天 |

### 10.2 时间汇总

- **M0–M5(到可投入运行):约 17 小时编码 + 装机** —— 一个长周末
- **M0–M8(到 testnet 验证完):额外 ~2 周挂机**
- **M9(可选主网):再额外 1 周**

### 10.3 Go/No-go 评审清单(M8)

**所有项必须 YES,否则停留在 M7:**

```
[ ] 连续 7 天无 unhandled exception 退出
[ ] 连续 7 天无 WebSocket 长时间断连未恢复
[ ] testnet 累计 PnL 为正,或非常接近 0(没被点差吃光)
[ ] 库存分布:90% 时间 |net_base| < inventory_soft_cap
[ ] 因子 → reservation_price 偏移幅度合理(典型 ±5 bp 内,不单边走)
[ ] Kill switch 主动测试 ≥ 1 次,恢复流程走通
[ ] Daily loss limit 至少某天接近过 50%(限额不至于松到看不见)
[ ] 最近 7 天每天 PnL 标准差 < 单日最大 PnL × 2
```

### 10.4 意识形态(写进 README)

> **本项目是"用 testnet 学怎么做高频"的载体,不是"快速赚钱机器"。**
> M9 是可选且**永远小额**。若主网某日发现因子完全失效(广义加密因子半衰期极短),正确反应是**回 testnet 找新因子**,不是加杠杆死扛。

---

## 11. 待 testnet 验证清单

本 spec 撰写时通过 GitHub 抽样了 Hummingbot 主分支的若干 API 表面。以下条目需在 M0/M2 实施时以**当时的真实 master 分支**为准核对:

| # | 项 | 影响 |
|---|---|---|
| V1 | ~~`MarketMakingControllerConfigBase` 字段~~ **已核对(2026-06-19):字段包含 `connector_name / trading_pair / buy_spreads / sell_spreads / buy_amounts_pct / sell_amounts_pct / executor_refresh_time / cooldown_time / leverage / position_mode / stop_loss / take_profit / time_limit`。`triple_barrier_config` 在 PMM Simple V2 中以 `self.config.triple_barrier_config` 访问,推断为计算属性或额外字段,与 §4.3 编码兼容。** | Config 类继承 |
| V2 | Pydantic 版本(v1 / v2),`Field` / `field_validator` 用法 | 整个 Config 类 |
| V3 | ~~`update_processed_data` 是否 async~~ **已核对(2026-06-19):是 `async def`;`ControllerBase` 基类版抛 `NotImplementedError`,`MarketMakingControllerBase` 实现版默认设 `reference_price = mid` 与 `spread_multiplier = 1`。** | §4.3 override |
| V4 | ~~`PositionExecutorConfig` 字段~~ **已核对(2026-06-19):import `hummingbot.strategy_v2.executors.position_executor.data_types`;`PositionExecutorConfig` 字段为 `trading_pair / connector_name / side / entry_price / amount / triple_barrier_config / leverage / activation_bounds / level_id`;`TripleBarrierConfig` 为同文件下独立类,字段 `stop_loss / take_profit / time_limit / trailing_stop / open_order_type / take_profit_order_type / stop_loss_order_type / time_limit_order_type`。spec 编码示例与之兼容。** | §4.3 get_executor_config |
| V5 | ~~`active_executors` 是属性还是方法~~ **已核对(2026-06-19):base 类无此属性,需调用 `self.get_active_executors()` 方法,返回 `List[ExecutorInfo]`。spec 已修正。** | §4.3 executors_to_early_stop |
| V6 | `OrderExecutorConfig` 用于强制平仓的 import 路径 / 字段 | §5.3 L3 强制平仓 |
| V7 | 基类是否暴露 `buy_amounts_factor` / `sell_amounts_factor`,否则需 override `get_price_and_amount` | §5.2 L2 不对称报价 |
| V8 | OrderBook 对象上 snapshot 时间戳的精确属性名 | §6.5 健康检查 |
| V9 | `binance_perpetual_testnet` 是否为合法 connector_name | §4.2 默认值 |
| V10 | Hummingbot trades.sqlite 表结构(用于 dashboard 读 fills 与 PnL 聚合) | §6.3, §8.2 |

凡是与上述假设不一致的,**立即在本 spec 加注修订记录**,而非默默改代码。

---

## 12. 参考

- Hummingbot 主仓库:<https://github.com/hummingbot/hummingbot>
- Strategy V2 Controller 文档:<https://hummingbot.org/strategies/v2-strategies/controllers/>
- DManMakerV2(参考 controller):<https://github.com/hummingbot/hummingbot/blob/master/controllers/market_making/dman_maker_v2.py>
- PMMSimple Controller:<https://github.com/hummingbot/hummingbot/blob/master/controllers/market_making/pmm_simple.py>
- MarketMakingControllerBase:<https://github.com/hummingbot/hummingbot/blob/master/hummingbot/strategy_v2/controllers/market_making_controller_base.py>
- Avellaneda-Stoikov(原始论文):*High-frequency trading in a limit order book*, 2008
- Binance Futures Testnet:<https://testnet.binancefuture.com/>
- Tailscale:<https://tailscale.com/>

---

## 修订记录

| 日期 | 修订 | 作者 |
|---|---|---|
| 2026-06-19 | 初稿 | wzh053 / Claude |
| 2026-06-19 | 核对 §11 中 V1/V3/V4/V5 与 Hummingbot master 分支,V5 发现 `active_executors` 不存在 → §4.3 改用 `get_active_executors()`;V1/V3/V4 字段确认 | Claude |
