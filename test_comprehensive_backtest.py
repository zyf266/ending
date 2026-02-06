"""
Comprehensive 策略回测脚本
- 从币安分批次获取 K 线（避免限流）
- 分别回测 300 根 1 分钟、300 根 15 分钟
- 初始资金 500U，杠杆 100x，止盈 100%，止损 50%
- 输出每笔交易明细 + 开平仓 CSV 记录 + K 线买卖点标注图
"""

import asyncio
import sys
import os
import time
import pandas as pd
import numpy as np
from datetime import datetime
from decimal import Decimal

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from backpack_quant_trading.core.binance_monitor import fetch_binance_klines_batch
from backpack_quant_trading.strategy.comprehensive import ComprehensiveStrategyV2
from backpack_quant_trading.engine.backtest import BacktestEngine, BacktestResult
from backpack_quant_trading.config.settings import TradingConfig


def fetch_binance_klines_safe(symbol: str, interval: str, total: int):
    """分批次获取币安 K 线（内部每批 1000 根，自动限流）"""
    return fetch_binance_klines_batch(symbol, interval, total_limit=total, batch_size=1000) or []


def klines_to_dataframe(klines: list) -> pd.DataFrame:
    """K 线列表转 DataFrame，index 为 datetime"""
    if not klines:
        return pd.DataFrame()
    df = pd.DataFrame(klines)
    df["datetime"] = pd.to_datetime(df["time"], unit="ms")
    df = df.set_index("datetime")
    df = df[["open", "high", "low", "close", "volume"]]
    df.index.name = None
    return df


def plot_trades_on_klines(df: pd.DataFrame, closed_trades: list, label: str) -> str:
    """在 K 线图上标注买卖点，保存为 PNG"""
    try:
        import mplfinance as mpf
    except ImportError:
        try:
            import matplotlib.pyplot as plt
            # 简易方案：折线图 + 散点（开仓+平仓）
            fig, ax = plt.subplots(figsize=(14, 6))
            ax.plot(df.index, df['close'], 'b-', alpha=0.8, label='收盘价')
            buy_ts, buy_p = [], []
            sell_ts, sell_p = [], []
            for t in closed_trades:
                if t.action == 'buy':  # 平空：开仓=卖v，平仓=买^
                    buy_ts.append(t.exit_time)
                    buy_p.append(float(t.exit_price))
                    sell_ts.append(t.entry_time)
                    sell_p.append(float(t.entry_price))
                else:  # 平多：开仓=买^，平仓=卖v
                    buy_ts.append(t.entry_time)
                    buy_p.append(float(t.entry_price))
                    sell_ts.append(t.exit_time)
                    sell_p.append(float(t.exit_price))
            if buy_ts:
                ax.scatter(buy_ts, buy_p, c='green', s=80, marker='^', label='买/平空')
            if sell_ts:
                ax.scatter(sell_ts, sell_p, c='red', s=80, marker='v', label='卖/平多')
            ax.set_title(f'K 线买卖点 - {label}')
            ax.legend()
            ax.grid(True, alpha=0.3)
            plt.xticks(rotation=30)
            fname = f"backtest_trades_{label.replace(' ', '_')}.png"
            plt.savefig(fname, dpi=120, bbox_inches='tight')
            plt.close()
            return fname
        except Exception as e2:
            print(f"matplotlib 绘图失败: {e2}")
            return ""

    # mplfinance 方案：蜡烛图 + 买卖点（需与主 df 同长度，非交易点用 NaN）
    suffix = label.replace(" ", "_").replace("分钟", "m")
    fname = f"backtest_trades_{suffix}.png"

    # 买卖点：开仓+平仓。做多=开多(买^) 平多(卖v)；做空=开空(卖v) 平空(买^)
    buy_series = pd.Series(np.nan, index=df.index)
    sell_series = pd.Series(np.nan, index=df.index)
    for t in closed_trades:
        def mark(ts, p, is_buy):
            idx = df.index.get_indexer([ts], method='nearest')[0]
            if idx < len(df.index):
                (buy_series if is_buy else sell_series).iloc[idx] = p
        # 开仓点
        mark(t.entry_time, float(t.entry_price), is_buy=(t.action == 'sell'))  # 平多=卖→开多是买
        # 平仓点
        mark(t.exit_time, float(t.exit_price), is_buy=(t.action == 'buy'))     # 平空=买，平多=卖

    addplots = []
    if buy_series.notna().any():
        addplots.append(mpf.make_addplot(buy_series, type='scatter', markersize=80, marker='^', color='lime'))
    if sell_series.notna().any():
        addplots.append(mpf.make_addplot(sell_series, type='scatter', markersize=80, marker='v', color='red'))

    mpf.plot(
        df, type='candle', volume=True, style='charles',
        title=f'K 线买卖点 - {label}',
        addplot=addplots if addplots else None,
        savefig=fname
    )
    return fname


async def run_backtest(interval: str, total_bars: int, label: str):
    """运行单次回测"""
    print(f"\n{'='*60}")
    print(f"📊 回测: {label} ({total_bars} 根 {interval} K 线)")
    print("=" * 60)

    # 1. 获取数据
    print("⏳ 从币安获取数据（分批次，避免限流）...")
    klines = fetch_binance_klines_safe("ETHUSDT", interval, total_bars)
    if len(klines) < 100:
        print(f"❌ 数据不足: 仅获取 {len(klines)} 根")
        return None, None, None

    df = klines_to_dataframe(klines)
    print(f"✅ 获取 {len(df)} 根 K 线: {df.index[0]} ~ {df.index[-1]}")

    # 2. 策略与回测
    config = TradingConfig()
    strategy = ComprehensiveStrategyV2(
        symbols=["ETHUSDT"],
        config=config,
        params={
            "default_tp_pct": 0.8,    # 止盈 80%（更易达成，提高胜率）
            "default_sl_pct": 0.5,   # 止损 50%
        }
    )

    engine = BacktestEngine(initial_capital=500)
    data = {"ETHUSDT": df}
    start_dt = df.index[0]
    end_dt = df.index[-1]

    result = await engine.run(strategy, data, start_dt, end_dt)

    # 3. 输出汇总
    print(f"\n📈 回测结果 ({label})")
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

    # 4. 每笔交易明细（仅已平仓）
    closed = [t for t in result.trades if t.exit_price is not None]
    if closed:
        print("\n📋 交易明细")
        print("-" * 100)
        print(f"{'序号':<4} {'方向':<4} {'开仓时间':<22} {'开仓价':<10} {'平仓时间':<22} {'平仓价':<10} {'盈亏($)':<10} {'盈亏%':<8}")
        print("-" * 100)
        for i, t in enumerate(closed, 1):
            side = "做多" if t.action == 'sell' else "做空"  # 平多=卖, 平空=买
            et = t.entry_time.strftime("%Y-%m-%d %H:%M") if t.entry_time else "-"
            xt = t.exit_time.strftime("%Y-%m-%d %H:%M") if t.exit_time else "-"
            pnl_s = f"+{t.pnl:.2f}" if t.pnl >= 0 else f"{t.pnl:.2f}"
            pct_s = f"+{t.pnl_percent:.1f}%" if t.pnl_percent >= 0 else f"{t.pnl_percent:.1f}%"
            print(f"{i:<4} {side:<4} {et:<22} {t.entry_price:<10.2f} {xt:<22} {t.exit_price:<10.2f} {pnl_s:<10} {pct_s:<8}")
        print("-" * 100)

    # 5. 保存开平仓记录到 CSV（方便复盘）
    csv_path = save_trades_to_csv(closed, label)
    if csv_path:
        print(f"\n📁 开平仓记录已保存: {csv_path}")

    # 6. 生成 K 线买卖点标注图
    if closed:
        try:
            save_path = plot_trades_on_klines(df, closed, label)
            if save_path:
                print(f"\n📊 K 线买卖点图已保存: {save_path}")
        except Exception as e:
            print(f"\n⚠ 生成K线图失败: {e}")

    return result, df, engine


def save_trades_to_csv(closed_trades: list, label: str) -> str:
    """将开平仓记录保存到 CSV 文件"""
    if not closed_trades:
        return ""
    rows = []
    for i, t in enumerate(closed_trades, 1):
        side = "做多" if t.action == 'sell' else "做空"
        rows.append({
            "序号": i,
            "方向": side,
            "标的": t.symbol,
            "开仓时间": t.entry_time.strftime("%Y-%m-%d %H:%M:%S") if t.entry_time else "",
            "开仓价": round(t.entry_price, 4),
            "平仓时间": t.exit_time.strftime("%Y-%m-%d %H:%M:%S") if t.exit_time else "",
            "平仓价": round(t.exit_price, 4) if t.exit_price else "",
            "数量": round(t.quantity, 6),
            "盈亏_USD": round(t.pnl, 4),
            "盈亏_%": round(t.pnl_percent, 2),
            "手续费": round(t.commission, 4),
            "原因": t.reason or "",
        })
    df_out = pd.DataFrame(rows)
    suffix = label.replace(" ", "_").replace("分钟", "m")
    fname = f"backtest_trades_{suffix}.csv"
    df_out.to_csv(fname, index=False, encoding="utf-8-sig")
    return fname


async def main():
    print("Comprehensive 策略回测")
    print("配置: 2 指标=5U, 3 指标=10U, 4+ 指标=20U | 止盈 100% | 止损 50%")

    # 回测 1 分钟（先用 300 根测试）
    r1, _, _ = await run_backtest("1m", 3000, "1 分钟 K 线")
    time.sleep(2)  # 两次获取间隔，避免限流

    # 回测 15 分钟
    r2, _, _ = await run_backtest("15m", 3000, "15 分钟 K 线")
    # 若数据不足，r1/r2 可能为 None，已处理

    print("\n✅ 回测完成")


if __name__ == "__main__":
    asyncio.run(main())
