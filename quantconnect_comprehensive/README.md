# Comprehensive 策略 - QuantConnect 版本

将 `backpack_quant_trading/strategy/comprehensive.py` 多指标综合策略适配为 QuantConnect 可回测的算法。

## 目录结构

```
quantconnect_comprehensive/
├── main.py      # 主算法（可直接复制到 QuantConnect 云端）
└── README.md    # 使用说明
```

## 使用方法

1. 登录 [QuantConnect](https://www.quantconnect.com)
2. 新建 Algorithm → Python
3. 将 `main.py` 全部内容复制到编辑器中
4. 根据需要修改 `Initialize()` 中的参数：
   - `SetStartDate` / `SetEndDate`：回测区间
   - `AddCrypto("ETHUSD", Resolution.Daily)`：可改为 `"BTCUSD"` 或 `Resolution.Hour` / `Resolution.Minute`
5. 点击 Backtest 运行回测

## 策略逻辑摘要

- **多指标评分**：趋势、价格位置、RSI、K线形态、成交量、KDJ、OBV、均线、MACD
- **趋势过滤**：仅跟随趋势（uptrend 做多，downtrend 做空）
- **MA50 过滤**：做多需价在 MA50 上方，做空需价在 MA50 下方
- **布林带宽度过滤**：BB_WIDTH < 0.02 不开仓
- **止盈止损**：TP 0.5%，SL 0.4%
- **冷却期**：平仓后 5 根 K 线内不再开仓

## 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `min_score_to_open` | 4 | 最低条件数量 |
| `min_weighted_score` | 5.0 | 最低加权分 |
| `take_profit_pct` | 0.5 | 止盈百分比 |
| `stop_loss_pct` | 0.4 | 止损百分比 |
| `rsi_oversold` | 35 | RSI 超卖阈值 |
| `rsi_overbought` | 65 | RSI 超买阈值 |
| `require_ma50_filter` | True | 是否启用 MA50 过滤 |
| `min_bb_width` | 0.02 | 最小布林带宽度 |
| `cooldown_days` | 5 | 冷却天数 |

## 数据说明

- 默认使用 **ETHUSD** 日线 (`Resolution.Daily`)
- QuantConnect 加密货币数据来自 GDAX/Coinbase
- 若需分钟级回测，将 `Resolution.Daily` 改为 `Resolution.Minute`，并相应调整 `History` 的 period 单位

## 注意事项

1. **账户类型**：默认 Cash 账户（不支持做空），`allow_short=False`。若需做空，改为 `allow_short=True` 并切换到 Margin 账户。
2. 策略为单标的全仓模式，仓位比例由 `margin_levels` 与评分决定
3. 若长时间无交易，可适当调低 `min_score_to_open` 或 `min_weighted_score`
