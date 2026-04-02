# 实盘交易API

<cite>
**本文引用的文件**
- [api/main.py](file://backpack_quant_trading/api/main.py)
- [api/routers/trading.py](file://backpack_quant_trading/api/routers/trading.py)
- [engine/live_trading.py](file://backpack_quant_trading/engine/live_trading.py)
- [core/risk_manager.py](file://backpack_quant_trading/core/risk_manager.py)
- [webhook_service.py](file://backpack_quant_trading/webhook_service.py)
- [config/settings.py](file://backpack_quant_trading/config/settings.py)
- [frontend/src/api/trading.js](file://backpack_quant_trading/frontend/src/api/trading.js)
- [core/api_client.py](file://backpack_quant_trading/core/api_client.py)
- [engine/webhook_trading.py](file://backpack_quant_trading/engine/webhook_trading.py)
</cite>

## 目录
1. [简介](#简介)
2. [项目结构](#项目结构)
3. [核心组件](#核心组件)
4. [架构总览](#架构总览)
5. [详细组件分析](#详细组件分析)
6. [依赖分析](#依赖分析)
7. [性能考虑](#性能考虑)
8. [故障排查指南](#故障排查指南)
9. [结论](#结论)
10. [附录](#附录)

## 简介
本文件为实盘交易API的详细技术文档，覆盖交易控制、订单管理、仓位查询与交易状态监控接口。文档同时阐述交易参数配置（交易对选择、下单数量、价格类型、止损止盈设置等）、订单生命周期管理（创建、取消、修改、状态查询）、实时交易状态推送与WebSocket连接管理、风险控制参数与资金管理策略。为便于前后端对接，文档提供了HTTP接口定义、请求/响应模式、错误处理策略与典型调用示例。

## 项目结构
后端基于FastAPI提供REST接口，前端通过统一的JavaScript封装调用。交易引擎分为两类：
- 子进程模式：Backpack/Deepcoin，由后端启动子进程执行策略。
- Webhook模式：Ostium/Hyperliquid，由独立Webhook服务承载多实例引擎。

```mermaid
graph TB
subgraph "后端"
API["FastAPI 应用<br/>路由注册与CORS"]
TR["实盘交易路由<br/>/api/trading"]
WH["Webhook服务<br/>/webhook, /register_instance 等"]
end
subgraph "交易引擎"
LT["Live Trading Engine<br/>子进程模式"]
WT["Webhook Trading Engine<br/>多实例"]
RM["Risk Manager<br/>风控与资金管理"]
AC["Exchange Client<br/>Backpack/Deepcoin/Ostium/Hyperliquid"]
end
subgraph "前端"
FE["前端API封装<br/>/src/api/trading.js"]
end
FE --> API
API --> TR
TR --> LT
TR --> WH
LT --> AC
WT --> AC
LT --> RM
WT --> RM
```

图表来源
- [api/main.py:36-48](file://backpack_quant_trading/api/main.py#L36-L48)
- [api/routers/trading.py:334-462](file://backpack_quant_trading/api/routers/trading.py#L334-L462)
- [webhook_service.py:83-241](file://backpack_quant_trading/webhook_service.py#L83-L241)

章节来源
- [api/main.py:14-98](file://backpack_quant_trading/api/main.py#L14-L98)
- [api/routers/trading.py:23-561](file://backpack_quant_trading/api/routers/trading.py#L23-L561)
- [webhook_service.py:26-598](file://backpack_quant_trading/webhook_service.py#L26-L598)

## 核心组件
- FastAPI应用与路由：负责注册交易相关路由、CORS配置与静态资源挂载。
- 实盘交易路由：提供策略启动/停止、实例管理、日志查询、HYPE策略管理等接口。
- Webhook服务：多实例引擎管理、信号路由、动态配置更新、广播/单实例模式。
- 交易引擎：Live Trading Engine（子进程模式）与Webhook Trading Engine（Webhook模式）。
- 风控与资金管理：Risk Manager统一风控策略与资金限额。
- 交易所客户端：BackpackAPIClient等抽象，适配不同交易所的下单与查询。

章节来源
- [api/main.py:36-48](file://backpack_quant_trading/api/main.py#L36-L48)
- [api/routers/trading.py:23-561](file://backpack_quant_trading/api/routers/trading.py#L23-L561)
- [webhook_service.py:26-598](file://backpack_quant_trading/webhook_service.py#L26-L598)
- [core/risk_manager.py:48-566](file://backpack_quant_trading/core/risk_manager.py#L48-L566)
- [core/api_client.py:22-86](file://backpack_quant_trading/core/api_client.py#L22-L86)

## 架构总览
实盘交易API采用“后端路由 + 交易引擎 + Webhook服务”的分层架构。后端路由负责参数校验、实例注册与进程/服务管理；交易引擎负责订单执行、仓位管理与风控；Webhook服务负责多实例信号路由与动态配置。

```mermaid
sequenceDiagram
participant FE as "前端"
participant API as "FastAPI路由(/api/trading)"
participant WH as "Webhook服务(/webhook)"
participant ENG as "交易引擎(Live/Webhook)"
participant EX as "交易所客户端"
FE->>API : POST /api/trading/launch
API->>API : 校验参数/解析交易对
alt Ostium/Hyperliquid
API->>WH : POST /register_instance
WH->>ENG : 初始化引擎实例
ENG->>EX : 订阅行情/查询余额
ENG-->>WH : 注册成功
WH-->>API : {"status" : "success","instance_id" : "..."}
else Backpack/Deepcoin
API->>ENG : 启动子进程执行策略
ENG->>EX : 下单/查询
ENG-->>API : {"ok" : true,"instance_id" : "..."}
end
API-->>FE : 返回实例ID/状态
```

图表来源
- [api/routers/trading.py:334-462](file://backpack_quant_trading/api/routers/trading.py#L334-L462)
- [webhook_service.py:83-241](file://backpack_quant_trading/webhook_service.py#L83-L241)

## 详细组件分析

### 实盘交易路由（/api/trading）
- 策略与平台查询：获取可用策略、交易所与HYPE策略列表。
- 实例管理：
  - 启动策略：支持Backpack/Deepcoin子进程模式与Ostium/Hyperliquid Webhook模式。
  - 停止实例：子进程模式通过PID终止，Webhook模式通过注销接口。
  - 实例列表：聚合Webhook运行实例与本地子进程实例。
- HYPE策略管理：独立线程模式，支持启动、停止、状态查询与启停切换。
- 日志查询：聚合Webhook、子进程与HYPE策略日志。

接口定义与示例
- 获取策略与平台
  - 方法：GET
  - 路径：/api/trading/strategies
  - 响应：包含策略列表、交易所列表与HYPE策略列表
- 启动策略
  - 方法：POST
  - 路径：/api/trading/launch
  - 请求体字段（示例）：platform, strategy, symbol, size, leverage, take_profit, stop_loss, api_key, api_secret, passphrase, private_key, forbidden_ranges
  - 响应：返回instance_id与状态
- 停止实例
  - 方法：DELETE
  - 路径：/api/trading/instances/{instance_id}
  - 响应：{"message":"ok"}
- 实例列表
  - 方法：GET
  - 路径：/api/trading/instances
  - 响应：实例数组（含平台、策略名、symbol、balance、status等）
- HYPE策略管理
  - 启动：POST /api/trading/hype/start
  - 停止：POST /api/trading/hype/stop
  - 状态：GET /api/trading/hype/status
  - 切换：POST /api/trading/hype/toggle
- 日志
  - 方法：GET
  - 路径：/api/trading/logs
  - 响应：最近日志文本

章节来源
- [api/routers/trading.py:89-102](file://backpack_quant_trading/api/routers/trading.py#L89-L102)
- [api/routers/trading.py:105-200](file://backpack_quant_trading/api/routers/trading.py#L105-L200)
- [api/routers/trading.py:243-290](file://backpack_quant_trading/api/routers/trading.py#L243-L290)
- [api/routers/trading.py:292-332](file://backpack_quant_trading/api/routers/trading.py#L292-L332)
- [api/routers/trading.py:334-462](file://backpack_quant_trading/api/routers/trading.py#L334-L462)
- [api/routers/trading.py:527-561](file://backpack_quant_trading/api/routers/trading.py#L527-L561)

### Webhook服务（/webhook）
- 多实例引擎管理：注册/注销实例、查询实例、余额查询。
- 信号路由：单实例与广播模式，支持按策略名与symbol筛选。
- 动态配置：更新保证金、止盈止损、杠杆与symbol。
- 熔断重置：手动解除熔断锁定。
- 签名校验：可选HMAC签名验证。

接口定义与示例
- 注册实例
  - 方法：POST
  - 路径：/register_instance
  - 请求体字段：instance_id, private_key, strategy_name, symbol, leverage, margin_amount, stop_loss_ratio, take_profit_ratio, forbidden_hours
  - 响应：{"status":"success","instance_id": "...","exchange":"ostium|hyperliquid"}
- 注销实例
  - 方法：POST
  - 路径：/unregister_instance/{instance_id}
  - 响应：{"status":"success","message":"实例已注销"}
- 实例列表
  - 方法：GET
  - 路径：/instances
  - 响应：实例数组（包含instance_id、symbol、exchange、strategy）
- 余额查询
  - 方法：GET
  - 路径：/balance/{instance_id}
  - 响应：{"balance": ...}
- 信号接口
  - 方法：POST
  - 路径：/webhook 或 /webhook/{instance_id}
  - 请求体：TradingViewSignal（包含signal、symbol、instance_id、strategy_name、price、timestamp等）
  - 响应：{"status":"success","message":"Signal received","instance_id": "..."}
- 广播模式
  - 方法：POST
  - 路径：/webhook
  - 请求体：TradingViewSignal + 可选strategy_name/symbol
  - 响应：{"status":"success","message":"Signal broadcasted to X instances","instances":[],"broadcast_count":X}
- 动态配置更新
  - 方法：POST
  - 路径：/update_config/{instance_id}
  - 请求体：margin_amount、stop_loss_ratio、take_profit_ratio、leverage、symbol
  - 响应：当前配置快照
- 熔断重置
  - 方法：POST
  - 路径：/reset/{instance_id}
  - 响应：{"status":"success","message":"Service reset successful"}

章节来源
- [webhook_service.py:83-241](file://backpack_quant_trading/webhook_service.py#L83-L241)
- [webhook_service.py:246-290](file://backpack_quant_trading/webhook_service.py#L246-L290)
- [webhook_service.py:292-318](file://backpack_quant_trading/webhook_service.py#L292-L318)
- [webhook_service.py:319-444](file://backpack_quant_trading/webhook_service.py#L319-L444)
- [webhook_service.py:445-479](file://backpack_quant_trading/webhook_service.py#L445-L479)
- [webhook_service.py:480-500](file://backpack_quant_trading/webhook_service.py#L480-L500)
- [webhook_service.py:512-588](file://backpack_quant_trading/webhook_service.py#L512-L588)

### 交易引擎与订单管理
- Live Trading Engine（子进程模式）
  - 订单/仓位/余额数据结构：Order、Position、AccountBalance。
  - WebSocket订阅：K线频道订阅与消息处理。
  - 订单生命周期：下单、查询、取消、历史查询。
  - 风控：余额缓存、仓位与保证金检查、止盈止损监控。
- Webhook Trading Engine（Webhook模式）
  - 信号解析与执行：根据TradingViewSignal生成下单指令。
  - 仓位计算：基于保证金与杠杆计算下单金额。
  - 休市控制：按北京时间小时列表控制交易时段。
  - 风控：止盈止损比例、熔断与通知。

```mermaid
classDiagram
class Order {
+string orderId
+string symbol
+string side
+string type
+decimal quantity
+decimal? price
+decimal filledQuantity
+string status
+datetime createdAt
+datetime updatedAt
+decimal commission
+dict to_dict()
}
class Position {
+string symbol
+string side
+decimal quantity
+decimal entryPrice
+decimal markPrice
+decimal unrealizedPnl
+decimal realizedPnl
+dict to_dict()
}
class AccountBalance {
+string asset
+decimal available
+decimal locked
+decimal total
+dict to_dict()
}
class LiveTradingEngine {
+initialize()
+start()
+stop()
+register_strategy(symbol, strategy)
+get_balance_cached()
+on_order(callback)
+on_position(callback)
+on_trade(callback)
}
LiveTradingEngine --> Order : "管理"
LiveTradingEngine --> Position : "管理"
LiveTradingEngine --> AccountBalance : "管理"
```

图表来源
- [engine/live_trading.py:50-124](file://backpack_quant_trading/engine/live_trading.py#L50-L124)
- [engine/live_trading.py:347-587](file://backpack_quant_trading/engine/live_trading.py#L347-L587)

章节来源
- [engine/live_trading.py:50-124](file://backpack_quant_trading/engine/live_trading.py#L50-L124)
- [engine/live_trading.py:347-587](file://backpack_quant_trading/engine/live_trading.py#L347-L587)
- [engine/webhook_trading.py:22-84](file://backpack_quant_trading/engine/webhook_trading.py#L22-L84)

### 风控与资金管理
- 风控参数
  - 最大单笔仓位比例、日度最大亏损、最大回撤、止损/止盈比例、无风险利率、默认杠杆。
- 风控检查
  - 仓位验证：基于总保证金与账户资金估算，防止超过最大仓位比例。
  - 订单风控：计算本次订单所需保证金，结合总保证金与账户资金评估风险。
  - 风险事件记录：拒绝/警告事件持久化。
- 风险报告：VaR、压力测试、风险评分与建议。

章节来源
- [config/settings.py:55-64](file://backpack_quant_trading/config/settings.py#L55-L64)
- [core/risk_manager.py:87-229](file://backpack_quant_trading/core/risk_manager.py#L87-L229)
- [core/risk_manager.py:503-542](file://backpack_quant_trading/core/risk_manager.py#L503-L542)

### 交易参数配置
- 交易对选择
  - 支持简写与完整格式互转，Backpack/Deepcoin/Hyperliquid/Ostium格式解析。
- 下单数量
  - 子进程模式：--position-size/--take-profit/--stop-loss传参。
  - Webhook模式：通过环境变量或动态配置设置保证金范围。
- 价格类型
  - 支持市价单/限价单，限价单需提供price。
- 止损止盈
  - 百分比/杠杆驱动的止盈止损，支持动态更新。
- 休市控制
  - Ostium支持按小时禁用交易时段。

章节来源
- [api/routers/trading.py:53-86](file://backpack_quant_trading/api/routers/trading.py#L53-L86)
- [api/routers/trading.py:373-392](file://backpack_quant_trading/api/routers/trading.py#L373-L392)
- [webhook_service.py:512-588](file://backpack_quant_trading/webhook_service.py#L512-L588)
- [engine/webhook_trading.py:131-140](file://backpack_quant_trading/engine/webhook_trading.py#L131-L140)

### 订单生命周期管理
- 创建：下单接口支持市价/限价单，限价单需提供price。
- 查询：活跃库与历史库双通道查询。
- 修改：Webhook模式支持动态更新止盈止损/杠杆/保证金。
- 取消：单订单与全部订单取消。
- 状态：Pending/Open/Filled/Cancelled/Rejected。

章节来源
- [core/api_client.py:413-545](file://backpack_quant_trading/core/api_client.py#L413-L545)
- [webhook_service.py:512-588](file://backpack_quant_trading/webhook_service.py#L512-L588)

### 交易状态监控与WebSocket
- WebSocket客户端：连接、订阅、取消订阅、消息接收与重连。
- 订阅频道：kline:1m等（Backpack格式）。
- 状态推送：通过回调通知订单/仓位/成交变更。

章节来源
- [engine/live_trading.py:126-345](file://backpack_quant_trading/engine/live_trading.py#L126-L345)

## 依赖分析
- 组件耦合
  - 实盘交易路由依赖数据库管理器与Webhook服务；交易引擎依赖交易所客户端与风控模块。
  - Webhook服务与交易引擎通过信号模型解耦。
- 外部依赖
  - FastAPI/Uvicorn、websockets、requests、SQLAlchemy、cryptography等。

```mermaid
graph LR
TR["/api/trading 路由"] --> DB["数据库管理器"]
TR --> WH["Webhook服务"]
TR --> LT["Live Trading Engine"]
LT --> AC["Exchange Client"]
LT --> RM["Risk Manager"]
WH --> WT["Webhook Trading Engine"]
WT --> AC
WT --> RM
```

图表来源
- [api/routers/trading.py:109-200](file://backpack_quant_trading/api/routers/trading.py#L109-L200)
- [webhook_service.py:28-32](file://backpack_quant_trading/webhook_service.py#L28-L32)

章节来源
- [api/routers/trading.py:109-200](file://backpack_quant_trading/api/routers/trading.py#L109-L200)
- [webhook_service.py:28-32](file://backpack_quant_trading/webhook_service.py#L28-L32)

## 性能考虑
- 余额缓存：交易引擎对余额调用进行缓存，降低API调用频率。
- 订阅合并：WebSocket连接复用与频道合并，减少连接开销。
- 异步并发：Webhook服务与交易引擎广泛使用异步I/O与并发锁，提升吞吐。
- 日志聚合：后端聚合多源日志，避免频繁磁盘IO。

章节来源
- [engine/live_trading.py:408-442](file://backpack_quant_trading/engine/live_trading.py#L408-L442)
- [webhook_service.py:48-68](file://backpack_quant_trading/webhook_service.py#L48-L68)

## 故障排查指南
- 启动失败
  - 检查Webhook服务端口占用与进程状态；确认私钥与配置正确。
- 订单失败
  - 核对签名/时间戳/参数完整性；查看交易所返回状态与风控拦截日志。
- WebSocket断连
  - 检查代理设置与网络连通性；关注重连与订阅恢复逻辑。
- 日志定位
  - 通过后端日志接口获取最近日志，定位异常堆栈。

章节来源
- [api/routers/trading.py:355-369](file://backpack_quant_trading/api/routers/trading.py#L355-L369)
- [engine/live_trading.py:153-236](file://backpack_quant_trading/engine/live_trading.py#L153-L236)
- [api/routers/trading.py:527-561](file://backpack_quant_trading/api/routers/trading.py#L527-L561)

## 结论
本实盘交易API通过清晰的路由分层、灵活的引擎模式与完善的风控体系，为多交易所、多策略的实盘交易提供了稳定可靠的基础设施。前端可通过统一封装便捷调用，后端可按需扩展Webhook实例与策略引擎，满足复杂交易场景的需求。

## 附录

### 前端调用封装
- 获取策略与平台：GET /trading/strategies
- 获取实例列表：GET /trading/instances
- 启动策略：POST /trading/launch
- 停止实例：DELETE /trading/instances/:id
- 获取日志：GET /trading/logs
- HYPE策略：启动/停止/状态/切换

章节来源
- [frontend/src/api/trading.js:1-14](file://backpack_quant_trading/frontend/src/api/trading.js#L1-L14)