#!/usr/bin/env python3
"""
双频趋势共振 TV 版 - 本地回测脚本
用法（在项目根目录或 backpack_quant_trading 下）:
  python -m backpack_quant_trading.run_dual_freq_tv_backtest
  python -m backpack_quant_trading.run_dual_freq_tv_backtest --csv data/ETH_1m_live.csv --symbol ETH_USDC
  python -m backpack_quant_trading.run_dual_freq_tv_backtest --csv "C:/path/to/klines.csv" --symbol ETH_USDC
CSV 格式：timestamp(或 datetime), open, high, low, close, volume；时间列将作为索引。
"""

import asyncio
import argparse
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd
import sys

# 保证能导入同包模块
if __name__ == "__main__" and __package__ is None:
    __package__ = "backpack_quant_trading"

from backpack_quant_trading.config.settings import config
from backpack_quant_trading.core.risk_manager import RiskManager
from backpack_quant_trading.strategy.dual_freq_trend_tv import DualFreqTrendTVStrategy
from backpack_quant_trading.engine.backtest import BacktestEngine, BacktestResult


def load_1m_csv(csv_path: str) -> pd.DataFrame:
    """加载 1 分钟 K 线 CSV，返回索引为时间的 DataFrame。列名不区分大小写。"""
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV 不存在: {csv_path}")
    df = pd.read_csv(path)
    df = df.rename(columns={c: c.strip().lower() for c in df.columns})
    # 时间列：timestamp / datetime / date 或第一列
    tcol = None
    for name in ("timestamp", "datetime", "date", "time"):
        if name in df.columns:
            tcol = name
            break
    if tcol is None:
        tcol = df.columns[0]
    df[tcol] = pd.to_datetime(df[tcol])
    df = df.set_index(tcol)
    df = df.sort_index()
    required = ["open", "high", "low", "close", "volume"]
    for r in required:
        if r not in df.columns:
            raise ValueError(f"CSV 缺少列: {r}，当前列: {list(df.columns)}")
    df = df[required].astype(float)
    df = df.dropna(subset=["close"])
    return df


def main():
    parser = argparse.ArgumentParser(description="双频趋势共振 TV 版 - 本地回测")
    parser.add_argument("--csv", type=str, default=None, help="1 分钟 K 线 CSV 路径（默认: data/ETH_1m_live.csv）")
    parser.add_argument("--symbol", type=str, default="ETH_USDC", help="回测标的符号（用于引擎与报告）")
    parser.add_argument("--capital", type=float, default=10000.0, help="初始资金")
    parser.add_argument("--start", type=str, default=None, help="开始日期 YYYY-MM-DD，不填用数据起始")
    parser.add_argument("--end", type=str, default=None, help="结束日期 YYYY-MM-DD，不填用数据末尾")
    args = parser.parse_args()

    # 默认 CSV 路径
    if args.csv is None:
        base = Path(__file__).resolve().parent
        default_csv = base / "data" / "ETH_1m_live.csv"
        if not default_csv.exists():
            default_csv = base.parent / "backpack_quant_trading" / "data" / "ETH_1m_live.csv"
        args.csv = str(default_csv)

    df = load_1m_csv(args.csv)
    symbol = args.symbol

    start_date = pd.Timestamp(df.index.min())
    end_date = pd.Timestamp(df.index.max())
    if args.start:
        start_date = pd.Timestamp(args.start)
    if args.end:
        end_date = pd.Timestamp(args.end)
    df = df.loc[start_date:end_date]
    if df.empty:
        print("错误: 指定日期区间无数据")
        sys.exit(1)
    data = {symbol: df}
    start_date = start_date.to_pydatetime() if hasattr(start_date, "to_pydatetime") else start_date
    end_date = end_date.to_pydatetime() if hasattr(end_date, "to_pydatetime") else end_date

    risk_manager = RiskManager(config)
    strategy = DualFreqTrendTVStrategy(
        symbols=[symbol],
        api_client=None,
        risk_manager=risk_manager,
        leverage=100,
        margin_per_trade=10.0,
        tp_pct=150.0,
        sl_pct=50.0,
        time_stop_bars=6,
        cooldown_bars=6,
        min_entry_gap=6,
        use_big_order_eaten=True,
        big_order_vol_mul=2.0,
        big_order_close_ratio=0.6,
        daily_loss_pct=5.0,
    )

    engine = BacktestEngine(initial_capital=args.capital)
    result = asyncio.run(engine.run(strategy, data, start_date, end_date))

    report = engine.generate_report(result)
    print(report)

    # 打印最近几笔交易
    closed = [t for t in engine.trades if t.exit_price is not None]
    if closed:
        print("\n最近 10 笔交易:")
        for t in closed[-10:]:
            print(f"  {t.entry_time} -> {t.exit_time} | {t.action} qty={t.quantity:.4f} entry={t.entry_price:.2f} exit={t.exit_price:.2f} pnl={t.pnl:.2f} {t.reason}")
    return result


if __name__ == "__main__":
    main()
