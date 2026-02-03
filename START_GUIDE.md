# 快速启动指南

## 修复内容总结

### 1. K线数据类型错误修复 ✅
- **问题**: 时间戳字段是字符串，无法与整数比较
- **修复**: 添加类型转换逻辑，支持字符串和数字两种格式

### 2. 交易对映射功能 ✅
- **Backpack K线数据**: 使用 `ETH_USDC_PERP` 格式
- **Deepcoin 下单平台**: 使用 `ETH-USDT-SWAP` 格式
- **自动映射**: 系统会自动转换

## 启动命令

### 方式1: 直接使用Deepcoin格式（推荐）

```bash
python -m backpack_quant_trading.main --mode live --strategy ai_adaptive --symbols ETH-USDT-SWAP --exchange deepcoin
```

**说明**:
- `--symbols ETH-USDT-SWAP`: 使用Deepcoin的交易对格式
- `--exchange deepcoin`: 指定在Deepcoin上下单
- 系统会自动将 `ETH-USDT-SWAP` 映射为 `ETH_USDC_PERP` 以获取Backpack K线
- 下单时会自动转换回 `ETH-USDT-SWAP` 格式

### 方式2: 使用Backpack格式（如果只在Backpack交易）

```bash
python -m backpack_quant_trading.main --mode live --strategy ai_adaptive --symbols ETH_USDC_PERP --exchange backpack
```

## 预期日志

启动后你应该看到：

```
================================================================================
🚀 [平台配置] 跨平台协同模式
📊 [数据源] K线数据来自: Backpack (WebSocket)
💰 [下单平台] 订单执行于: Deepcoin
🔍 [余额查询] 使用: Deepcoin API
================================================================================

正在验证交易对有效性...
交易所支持的有效交易对数量: XXX
✅ 交易对映射: ETH-USDT-SWAP -> ETH_USDC_PERP (用于获取K线)
已转换为Backpack格式的交易对: ['ETH_USDC_PERP']

================================================================================
📥 [数据预加载] 开始预加载历史K线数据...
📥 [数据预加载] 目标: 为每个交易对获取 1000 根15分钟K线
================================================================================
📡 [数据预加载] 正在获取 ETH_USDC_PERP 的历史K线数据...
📊 [数据预加载] API返回数据类型: <class 'list'>, 长度: XXX
📝 [数据预加载] 第一条K线样本:
   类型: <class 'dict'>
   内容: {'close': '3021.58', 'start': '2026-01-27 23:45:00', ...}
📈 [数据预加载] ETH_USDC_PERP 进度: 100/XXX
...
✅ [数据预加载] ETH_USDC_PERP 成功加载 XXX/XXX 条历史K线
✅ [数据预加载] ETH_USDC_PERP 缓存验证: 共XXX条数据
🤖 [数据预加载] 触发 ETH_USDC_PERP 首次AI分析...
```

## 交易对映射关系

| 用户输入 (Deepcoin) | Backpack K线 | 说明 |
|---------------------|--------------|------|
| ETH-USDT-SWAP | ETH_USDC_PERP | 自动映射 |
| BTC-USDT-SWAP | BTC_USDC_PERP | 自动映射 |
| SOL-USDT-SWAP | SOL_USDC_PERP | 自动映射 |

**工作原理**:
1. 策略注册时建立映射: `ETH_USDC_PERP -> ETH-USDT-SWAP`
2. 获取K线时使用: `ETH_USDC_PERP` (Backpack)
3. 下单时自动转换: `ETH-USDT-SWAP` (Deepcoin)

## 常见问题

### Q: 为什么要这样设计？
A: 因为Backpack有优质的K线数据，但你想在Deepcoin下单。系统自动处理格式转换。

### Q: 如果我只用Backpack怎么办？
A: 直接用 `--symbols ETH_USDC_PERP --exchange backpack`，不会进行任何转换。

### Q: 支持哪些交易对？
A: 任何在Backpack有对应USDC永续合约的币种，系统会自动将USDT映射为USDC。

---
更新时间: 2026-01-28
