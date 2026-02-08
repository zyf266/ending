"""
双频趋势共振高频策略回测
- 需 1 分钟 K 线（内部重采样为 15 分钟做趋势判定）
- 时间止损 8 分钟，风险回报比 1:1.5
"""

import asyncio
import sys
import os
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from backpack_quant_trading.core.binance_monitor import fetch_binance_klines_batch
from backpack_quant_trading.strategy.dual_freq_trend import DualFreqTrendResonanceStrategy
from backpack_quant_trading.engine.backtest import BacktestEngine, BacktestResult
from backpack_quant_trading.config.settings import TradingConfig


def fetch_klines(symbol: str, interval: str, total: int):
    return fetch_binance_klines_batch(symbol, interval, total_limit=total, batch_size=1000) or []


def klines_to_dataframe(klines: list) -> pd.DataFrame:
    if not klines:
        return pd.DataFrame()
    df = pd.DataFrame(klines)
    df["datetime"] = pd.to_datetime(df["time"], unit="ms")
    df = df.set_index("datetime")
    df = df[["open", "high", "low", "close", "volume"]]
    df.index.name = None
    return df


async def run_backtest():
    print("=" * 60)
    print("双频趋势共振高频策略回测 v2")
    print("配置: 只做回调 | 止盈止损各0.4% | 时间止损6min | 冷却40min")
    print("=" * 60)

    klines = fetch_klines("ETHUSDT", "1m", 2000)
    if len(klines) < 200:
        print(f"数据不足: 仅 {len(klines)} 根")
        return

    df = klines_to_dataframe(klines)
    print(f"获取 {len(df)} 根 1 分钟 K 线: {df.index[0]} ~ {df.index[-1]}")

    config = TradingConfig()
    strategy = DualFreqTrendResonanceStrategy(
        symbols=["ETHUSDT"],
        config=config,
        params={
            "time_stop_minutes": 6,
            "sl_pct": 0.004,
            "tp_pct": 0.004,   # 止盈=止损，1:1 盈亏比
            "margin_per_trade": 10.0,
            "cooldown_bars": 50,      # 平仓后50分钟冷却
            "use_breakout_mode": False,  # 关闭突破，只做回调
        }
    )

    engine = BacktestEngine(initial_capital=500)
    result = await engine.run(strategy, {"ETHUSDT": df}, df.index[0], df.index[-1])

    print("\n回测结果")
    print("-" * 60)
    print(f"初始资金: $500.00")
    print(f"最终资金: ${engine.portfolio_values[-1]:,.2f}" if engine.portfolio_values else "N/A")
    print(f"总收益率: {result.total_return:.2f}%")
    print(f"最大回撤: {result.max_drawdown:.2f}%")
    print(f"胜率: {result.win_rate:.2f}%")
    print(f"总交易: {result.total_trades} (盈:{result.winning_trades} 亏:{result.losing_trades})")
    if result.total_trades > 0:
        print(f"盈利因子: {result.profit_factor:.2f}")
    print("-" * 60)

    closed = [t for t in result.trades if t.exit_price is not None]
    if closed:
        print("\n交易明细")
        print("-" * 100)
        print(f"{'序号':<4} {'方向':<4} {'开仓时间':<22} {'开仓价':<10} {'平仓时间':<22} {'平仓价':<10} {'盈亏($)':<10} {'盈亏%':<8}")
        print("-" * 100)
        for i, t in enumerate(closed, 1):
            side = "做多" if t.action == 'sell' else "做空"
            et = t.entry_time.strftime("%Y-%m-%d %H:%M") if t.entry_time else "-"
            xt = t.exit_time.strftime("%Y-%m-%d %H:%M") if t.exit_time else "-"
            pnl_s = f"+{t.pnl:.2f}" if t.pnl >= 0 else f"{t.pnl:.2f}"
            pct_s = f"+{t.pnl_percent:.1f}%" if t.pnl_percent >= 0 else f"{t.pnl_percent:.1f}%"
            print(f"{i:<4} {side:<4} {et:<22} {t.entry_price:<10.2f} {xt:<22} {t.exit_price:<10.2f} {pnl_s:<10} {pct_s:<8}")
        print("-" * 100)


if __name__ == "__main__":
    asyncio.run(run_backtest())
