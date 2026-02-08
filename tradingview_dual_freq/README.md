# DualFreq Trend Resonance - TradingView 版本

对应策略：`backpack_quant_trading/strategy/dual_freq_trend.py`

## 使用方法
1. TradingView 打开 Pine 编辑器
2. 复制 `dual_freq_trend.pine` 全部内容
3. 添加到图表并回测

## 逻辑概述
- **15m 趋势**：EMA9/EMA21 连续同向确认
- **1m 入场**：
  - 回调：价格接近 EMA13 或 布林中轨，RSI6 回升/回落
  - 突破：金叉/死叉 + 放量 + RSI 强弱（可开关）
- **止盈止损**：默认 100% / 50%
- **杠杆**：默认 100x（按 equity*leverage/price 计算下单量）
- **时间止损**：6 分钟
- **趋势反转退出**：15m 方向反转平仓
- **冷却期**：50 根 K 线

## 参数建议
- 若开单太少：关闭 `use_breakout_mode` 外，调小 `cooldown_bars` 到 30
- 若胜率偏低：开启 `use_breakout_mode`，或者调大 `time_stop_bars`
