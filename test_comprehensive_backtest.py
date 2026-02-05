"""
综合性策略回测脚本

配置：
- 初始资金：500U
- 杠杆：100x
- 保证金分级：1指标=5U, 2指标=10U, 3+指标=20U
- 止盈：100%（账户盈利）
- 止损：50%（账户亏损）
"""

import asyncio
import pandas as pd
from datetime import datetime
from loguru import logger
import sys
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from backpack_quant_trading.config.settings import TradingConfig
from backpack_quant_trading.strategy.comprehensive import ComprehensiveStrategy
from backpack_quant_trading.engine.backtest import BacktestEngine


async def run_comprehensive_backtest():
    """运行综合性策略回测"""
    
    logger.info("=" * 80)
    logger.info("🚀 综合性策略回测 - 多指标评分系统")
    logger.info("=" * 80)
    
    # 1. 配置参数
    config = TradingConfig()
    config.LEVERAGE = 100  # 100倍杠杆
    
    symbols = ['ETH-USDT-SWAP']
    
    # 2. 初始化策略
    strategy = ComprehensiveStrategy(
        symbols=symbols,
        config=config,
        params={
            'initial_capital': 500,  # 初始资金500U
            'margin_level_1': 5.0,   # 1个指标：5U
            'margin_level_2': 10.0,  # 2个指标：10U
            'margin_level_3': 20.0,  # 3个以上指标：20U
            'take_profit_pct': 1.0,  # 止盈：100%
            'stop_loss_pct': 0.5,    # 止损：50%
        }
    )
    
    # 3. 加载K线数据
    data_file = project_root / 'backpack_quant_trading' / 'data' / 'ETH_1m_live.csv'
    
    if not data_file.exists():
        logger.error(f"❌ K线数据文件不存在: {data_file}")
        return
    
    logger.info(f"📂 加载K线数据: {data_file}")
    df = pd.read_csv(data_file)
    
    # 数据预处理
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.set_index('timestamp', inplace=True)
    
    # 确保必要列存在
    required_cols = ['open', 'high', 'low', 'close', 'volume']
    for col in required_cols:
        if col not in df.columns:
            logger.error(f"❌ 缺少必要列: {col}")
            return
    
    logger.info(f"✅ K线数据加载成功: {len(df)}根K线")
    logger.info(f"   时间范围: {df.index[0]} ~ {df.index[-1]}")
    
    # 4. 初始化回测引擎
    backtest = BacktestEngine(initial_capital=500)  # 初始资金500U
    backtest.commission_rate = 0.0005  # 手续费0.05%
    backtest.slippage = 0.0001  # 滑点0.01%
    
    # 5. 运行回测
    logger.info("\n" + "=" * 80)
    logger.info("📊 开始回测...")
    logger.info("=" * 80)
    
    # 获取时间范围
    start_date = df.index[0]
    end_date = df.index[-1]
    
    market_data = {'ETH-USDT-SWAP': df}
    results = await backtest.run(strategy=strategy, data=market_data, start_date=start_date, end_date=end_date)
    
    # 6. 输出回测结果
    logger.info("\n" + "=" * 80)
    logger.info("📈 回测结果统计")
    logger.info("=" * 80)
    
    if results:
        # 基础统计
        logger.info(f"\n【基础信息】")
        logger.info(f"  初始资金: ${backtest.initial_capital:.2f}")
        logger.info(f"  最终资金: ${backtest.portfolio_values[-1] if backtest.portfolio_values else 0:.2f}")
        logger.info(f"  总收益: ${(backtest.portfolio_values[-1] - backtest.initial_capital) if backtest.portfolio_values else 0:.2f}")
        logger.info(f"  收益率: {results.total_return:.2f}%")
        logger.info(f"  年化收益率: {results.annualized_return:.2f}%")
        logger.info(f"  杠杆倍数: {config.LEVERAGE}x")
        
        # 交易统计
        logger.info(f"\n【交易统计】")
        logger.info(f"  总交易次数: {results.total_trades}")
        logger.info(f"  盈利次数: {results.winning_trades}")
        logger.info(f"  亏损次数: {results.losing_trades}")
        logger.info(f"  胜率: {results.win_rate:.2f}%")
        
        # 盈亏统计
        logger.info(f"\n【盈亏统计】")
        if results.winning_trades > 0:
            winning_pnl = [t.pnl for t in results.trades if t.pnl > 0]
            logger.info(f"  最大盈利: ${max(winning_pnl):.2f}")
            logger.info(f"  平均盈利: ${sum(winning_pnl) / len(winning_pnl):.2f}")
        if results.losing_trades > 0:
            losing_pnl = [t.pnl for t in results.trades if t.pnl < 0]
            logger.info(f"  最大亏损: ${min(losing_pnl):.2f}")
            logger.info(f"  平均亏损: ${sum(losing_pnl) / len(losing_pnl):.2f}")
        logger.info(f"  盈亏比: {results.profit_factor:.2f}")
        
        # 风险指标
        logger.info(f"\n【风险指标】")
        logger.info(f"  最大回撤: {results.max_drawdown:.2f}%")
        logger.info(f"  夏普比率: {results.sharpe_ratio:.2f}")
        
        # 交易详情
        logger.info(f"\n【交易详情】")
        for i, trade in enumerate(results.trades[:10], 1):  # 显示前10笔交易
            logger.info(f"  {i}. {trade.action.upper()} {trade.symbol} @ ${trade.entry_price:.2f}, "
                       f"PnL: ${trade.pnl:.2f} ({trade.pnl_percent:.2f}%), 原因: {trade.reason}")
    
    logger.info("\n" + "=" * 80)
    logger.info("✅ 回测完成")
    logger.info("=" * 80)
    
    # 【新增】导出交易详情到CSV
    if results and results.trades:
        import csv
        trades_file = project_root / 'comprehensive_trades.csv'
        with open(trades_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['#', '交易类型', '交易对', '开仓价', '平仓价', '数量', '盈亏', '盈亏%', '手续费', '时间', '原因'])
            for i, trade in enumerate(results.trades, 1):
                writer.writerow([
                    i,
                    trade.action.upper(),
                    trade.symbol,
                    f"{trade.entry_price:.2f}",
                    f"{trade.exit_price:.2f}" if trade.exit_price else "",
                    f"{trade.quantity:.4f}",
                    f"{trade.pnl:.2f}",
                    f"{trade.pnl_percent:.2f}%",
                    f"{trade.commission:.4f}",
                    str(trade.entry_time),
                    trade.reason
                ])
        logger.info(f"✅ 交易详情已导出: {trades_file}")
    
    # 【新增】生成K线图 + 买卖点标注
    if results and results.trades:
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        from matplotlib.patches import Rectangle
        
        # 设置中文字体
        plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial Unicode MS']
        plt.rcParams['axes.unicode_minus'] = False
        
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(20, 12), height_ratios=[3, 1])
        
        # 上图：K线 + 买卖点
        ax1.plot(df.index, df['close'], label='Close Price', color='black', linewidth=0.8, alpha=0.7)
        
        # 标注买卖点
        buy_trades = [t for t in results.trades if t.action == 'buy']
        sell_trades = [t for t in results.trades if t.action == 'sell']
        
        buy_times = [t.entry_time for t in buy_trades]
        buy_prices = [t.entry_price for t in buy_trades]
        
        sell_times = [t.entry_time for t in sell_trades]
        sell_prices = [t.entry_price for t in sell_trades]
        
        ax1.scatter(buy_times, buy_prices, color='red', marker='^', s=100, label=f'Buy ({len(buy_trades)})', zorder=5)
        ax1.scatter(sell_times, sell_prices, color='green', marker='v', s=100, label=f'Sell ({len(sell_trades)})', zorder=5)
        
        ax1.set_title(f'Comprehensive Strategy Backtest - ETH-USDT-SWAP (Total Trades: {len(results.trades)})', fontsize=16, fontweight='bold')
        ax1.set_ylabel('Price (USDT)', fontsize=12)
        ax1.legend(loc='upper left', fontsize=10)
        ax1.grid(True, alpha=0.3)
        
        # 下图：资金曲线
        ax2.plot(backtest.dates, backtest.portfolio_values, label='Portfolio Value', color='blue', linewidth=2)
        ax2.axhline(y=backtest.initial_capital, color='gray', linestyle='--', label='Initial Capital', alpha=0.5)
        ax2.set_xlabel('Time', fontsize=12)
        ax2.set_ylabel('Portfolio Value ($)', fontsize=12)
        ax2.set_title('Portfolio Value Over Time', fontsize=14)
        ax2.legend(loc='upper left', fontsize=10)
        ax2.grid(True, alpha=0.3)
        
        # 添加统计信息
        stats_text = f"""Initial: ${backtest.initial_capital:.0f}
Final: ${backtest.portfolio_values[-1]:.0f}
Return: {results.total_return:.1f}%
Trades: {results.total_trades}
Win Rate: {results.win_rate:.1f}%
Max DD: {results.max_drawdown:.2f}%"""
        ax1.text(0.02, 0.98, stats_text, transform=ax1.transAxes, 
                fontsize=10, verticalalignment='top',
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))
        
        plt.tight_layout()
        chart_file = project_root / 'comprehensive_backtest_chart.png'
        plt.savefig(chart_file, dpi=150, bbox_inches='tight')
        logger.info(f"✅ K线图已生成: {chart_file}")
        plt.close()
    
    return results


if __name__ == '__main__':
    # 配置日志
    logger.remove()
    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        level="INFO"
    )
    
    # 运行回测
    results = asyncio.run(run_comprehensive_backtest())
    
    if results and results.total_trades > 0:
        logger.info(f"\n🎉 回测成功完成！最终收益率: {results.total_return:.2f}%")
    else:
        logger.error("❌ 回测失败或无交易记录")
