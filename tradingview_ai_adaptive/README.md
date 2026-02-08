# AI Adaptive 策略 - TradingView 版本

本文件将 `backpack_quant_trading/strategy/ai_adaptive.py` 的**本地指标预筛选逻辑**迁移到 TradingView 回测。  
由于 TradingView 无法调用外部 AI，这里使用“本地预筛选 + 方向判定”作为 AI 代理逻辑。

## 使用方法

1. 打开 TradingView → Pine 编辑器  
2. 复制 `ai_adaptive.pine` 内容 → 保存  
3. 添加到图表并回测  

## 逻辑要点（对应 ai_adaptive.py）

- **触发条件**（满足任意 N 个）  
  - RSI 超买/超卖  
  - 价格接近布林带上下轨  
  - MACD 柱状图绝对值较大  
- **方向判断**：  
  - RSI 低/触下轨 → 偏多  
  - RSI 高/触上轨 → 偏空  
  - MACD 柱状图方向用于冲突处理  
- **止盈止损**：固定比例（默认止损 50%，止盈 100%）
- **杠杆**：按 `杠杆(倍)` 输入计算下单数量（默认 100x）
- **冷却期**：平仓后 N 根 K 线不再开仓  

## 参数建议

- 1m/5m：`cooldown_bars=10~20`  
- 15m/1h：`cooldown_bars=20~40`  
- 若交易过多：提高 `min_conditions` 或增大 `bb_dist_pct`  

如需更贴近 AI 策略的“深度分析”，可以在 TradingView 里叠加更多过滤条件（如多周期趋势/成交量确认）。  
