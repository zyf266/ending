import asyncio
import signal
import sys
import argparse
import logging
from typing import Any
from datetime import datetime, timedelta
from pathlib import Path
# 获取项目根目录（backpack_quant_trading的路径）
# 使用相对导入
from .config.settings import config
from .core.data_manager import DataManager
from .core.risk_manager import RiskManager
from .strategy.base import BaseStrategy
from .strategy.mean_reversion import MeanReversionStrategy
from .strategy.ai_adaptive import AIAdaptiveStrategy
from .engine.backtest import BacktestEngine, BacktestResult
from .engine.live_trading import LiveTradingEngine
from .utils.logger import setup_logger, get_logger
from .core.api_client import BackpackAPIClient, ExchangeClient
from .core.deepcoin_client import DeepcoinAPIClient
from .core.hyperliquid_client import HyperliquidAPIClient

# 初始化日志系统
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
setup_logger(level=logging.DEBUG)
logger = get_logger(__name__)


# 简单的策略注册表，后续添加新策略只需在此处注册
STRATEGY_REGISTRY: dict[str, Any] = {
    "mean_reversion": MeanReversionStrategy,
    "ai_adaptive": AIAdaptiveStrategy,
    "high_frequency": "日内高频交易",
}

# 策略显示名称映射
STRATEGY_DISPLAY_NAMES = {
    "mean_reversion": "均值回归测试",
    "ai_adaptive": "Ai自适应策略",
    "high_frequency": "日内高频交易",
}

# 交易所注册表：目前支持 backpack, deepcoin, ostium
EXCHANGE_REGISTRY: dict[str, Any] = {
    "backpack": BackpackAPIClient,
    "deepcoin": DeepcoinAPIClient,
    "ostium": "Ostium",
    "hyperliquid": HyperliquidAPIClient,
}


class TradingBot:
    def __init__(self, mode: str = 'backtest'):
        self.mode = mode
        self.data_manager = DataManager(api_client=None, mode=mode)
        self.risk_manager = RiskManager(config)
        self.strategies: dict = {}
        self.backtest_engine = BacktestEngine()
        self.live_engine = None
        self.running = False

    def add_strategy(self, symbol: str, strategy: BaseStrategy):
        self.strategies[symbol] = strategy
        logger.info(f"添加策略: {strategy.name} for {symbol}")

    def run_backtest(self, symbols: list, start_date: datetime, end_date: datetime):
        logger.info(f"开始回测: {start_date} 到 {end_date}")

        data = {}
        for symbol in symbols:
            df = self.data_manager.fetch_historical_data(
                symbol=symbol,
                interval='1h',
                start_time=start_date,
                end_time=end_date
            )
            if not df.empty:
                df = self.data_manager.calculate_technical_indicators(df)
                data[symbol] = df
                logger.info(f"加载 {symbol} 数据: {len(df)} 条记录")

        if not data:
            logger.warning("未获取到任何市场数据")
            return []

        results = []
        for symbol, strategy in self.strategies.items():
            if symbol not in data:
                continue

            logger.info(f"运行策略回测: {strategy.name} - {symbol}")

            single_data = {symbol: data[symbol]}
            result = self.backtest_engine.run(
                strategy, single_data, start_date, end_date
            )

            report = self.backtest_engine.generate_report(result)
            results.append({
                'strategy': strategy.name,
                'symbol': symbol,
                'result': result,
                'report': report
            })

            logger.info(f"回测完成: {symbol}\n{report}")

        return results

    async def run_live_trading(self):
        logger.info("启动实盘交易模式")

        if self.live_engine is None:
            self.live_engine = LiveTradingEngine(config)

        for symbol, strategy in self.strategies.items():
            self.live_engine.register_strategy(symbol, strategy)

        self.live_engine.on_order(self._on_order_update)
        self.live_engine.on_position(self._on_position_update)
        self.live_engine.on_trade(self._on_trade)

        try:
            await self.live_engine.initialize()
            
            # 初始化后，将API客户端传递给策略，便于获取实际账户余额
            for strategy in self.strategies.values():
                # 这里传入的是抽象的交易所客户端，支持后续切换到其他交易所实现
                strategy.api_client = self.live_engine.exchange_client
            
            logger.info(f"账户信息: {self.live_engine.get_account_summary()}")
            logger.info(f"持仓信息: {self.live_engine.get_positions_summary()}")

            await self.live_engine.start()

        except KeyboardInterrupt:
            logger.info("收到用户中断信号")
        except Exception as e:
            logger.error(f"实盘交易异常: {e}")
        finally:
            if self.live_engine:
                await self.live_engine.stop()

    def _on_order_update(self, order):
        logger.info(f"订单更新: {order.order_id} - {order.status.value}")

    def _on_position_update(self, position):
        logger.info(f"仓位更新: {position.symbol} - {position.side.value}: {position.quantity}")

    def _on_trade(self, order, trade_type):
        logger.info(f"成交通知: {order.symbol} {order.side.value} {order.filled_quantity}")


def run_backtest_demo():
    bot = TradingBot(mode='backtest')

    symbols = ['SOL_USDC', 'BTC_USDC', 'ETH_USDC']

    strategy = MeanReversionStrategy(
        symbols=symbols,
        api_client=None,
        risk_manager=bot.risk_manager
    )
    strategy.params.lookback_period = 5
    strategy.params.zscore_threshold = 1.0
    strategy.params.position_size = 0.03  # 仓位大小为3%
    strategy.params.stop_loss_percent = 0.05
    strategy.params.take_profit_percent = 0.03

    for symbol in symbols:
        bot.add_strategy(symbol, strategy)

    start_date = datetime.now() - timedelta(days=30)
    end_date = datetime.now()

    results = bot.run_backtest(symbols, start_date, end_date)

    if results:
        total_return = sum(r['result'].total_return for r in results) / len(results)
        total_trades = sum(r['result'].total_trades for r in results)
        avg_sharpe = sum(r['result'].sharpe_ratio for r in results) / len(results)

        print(f"\n{'='*50}")
        print(f"汇总统计:")
        print(f"  平均收益率: {total_return:.2f}%")
        print(f"  总交易次数: {total_trades}")
        print(f"  平均夏普比率: {avg_sharpe:.2f}")
        print(f"{'='*50}")


async def run_live_demo(args):
    # 根据参数选择交易所实现（默认为 backpack）
    exchange_name = getattr(args, "exchange", "backpack")
    exchange_cls = EXCHANGE_REGISTRY.get(exchange_name)
    if exchange_cls is None:
        raise ValueError(f"未知交易所: {exchange_name}")

    # 创建交易所客户端实例
    exchange_client = exchange_cls()

    # 如果传入了杠杆，覆盖全局配置（仅对当前进程生效）
    if getattr(args, "leverage", None):
        config.trading.LEVERAGE = args.leverage

    bot = TradingBot(mode='live')

    symbols = args.symbols

    # 根据策略名称从注册表中创建策略实例
    strategy_name = args.strategy
    strategy_cls = STRATEGY_REGISTRY.get(strategy_name)
    if strategy_cls is None:
        raise ValueError(f"未知策略: {strategy_name}")

    # 准备策略初始化参数
    strategy_kwargs = {
        "symbols": symbols,
        "api_client": exchange_client,
        "risk_manager": bot.risk_manager
    }
    
    # 如果是AI策略,传递专用参数
    if strategy_name == "ai_adaptive":
        # 从命令行或默认值获取参数
        strategy_kwargs["margin"] = getattr(args, "position_size", 100)  # 保证金(默认100 USDC)
        strategy_kwargs["leverage"] = getattr(args, "leverage", 50)  # 杠杆(默认50x)
        strategy_kwargs["stop_loss_ratio"] = getattr(args, "stop_loss", 0.015)  # 止损比例(默认1.5%)
        strategy_kwargs["take_profit_ratio"] = getattr(args, "take_profit", 0.02)  # 止盈比例(默认2%)
    
    strategy = strategy_cls(**strategy_kwargs)
    # 默认参数仍然沿用原有设置，便于快速测试
    if hasattr(strategy, "params"):
        # 这些字段仅在 MeanReversionStrategy 上存在，其他策略可以自行定义
        if hasattr(strategy.params, "lookback_period"):
            strategy.params.lookback_period = 5
        if hasattr(strategy.params, "zscore_threshold"):
            strategy.params.zscore_threshold = 1.0
        # position_size 可以被命令行参数覆盖
        if hasattr(strategy.params, "position_size"):
            if getattr(args, "position_size", None):
                strategy.params.position_size = args.position_size
            else:
                strategy.params.position_size = 0.03
        if hasattr(strategy.params, "take_profit_percent"):
            if getattr(args, "take_profit", None):
                strategy.params.take_profit_percent = args.take_profit
            else:
                strategy.params.take_profit_percent = 0.03
        
        if hasattr(strategy.params, "stop_loss_percent"):
            if getattr(args, "stop_loss", None):
                strategy.params.stop_loss_percent = args.stop_loss
            else:
                strategy.params.stop_loss_percent = 0.02

    for symbol in symbols:
        bot.add_strategy(symbol, strategy)

    # 注入可切换的交易所客户端
    bot.live_engine = LiveTradingEngine(config, exchange_client=exchange_client)
    for symbol, s in bot.strategies.items():
        bot.live_engine.register_strategy(symbol, s)

    await bot.run_live_trading()


def main():
    parser = argparse.ArgumentParser(description='Backpack Exchange 量化交易系统')
    parser.add_argument('--mode', choices=['backtest', 'live'], default='backtest',
                        help='运行模式: backtest=回测, live=实盘')
    parser.add_argument('--symbols', type=str, nargs='+',
                        default=['ETH_USDC_PERP'],
                        help='交易对列表')
    parser.add_argument('--strategy', type=str, default='mean_reversion',
                        choices=list(STRATEGY_REGISTRY.keys()), help='策略类型')
    parser.add_argument('--exchange', type=str, default='backpack',
                        choices=list(EXCHANGE_REGISTRY.keys()), help='交易所名称')
    parser.add_argument('--days', type=int, default=30, help='回测天数')
    parser.add_argument('--position-size', type=float, default=None,
                        help='AI策略:保证金(USDC); 其他策略:仓位比例')
    parser.add_argument('--leverage', type=int, default=None,
                        help='实盘模式下使用的杠杆倍数（覆盖全局配置）')
    parser.add_argument('--stop-loss', type=float, default=None,
                        help='止损比例')
    parser.add_argument('--take-profit', type=float, default=None,
                        help='止盈比例')

    args = parser.parse_args()

    print(f"""
╔══════════════════════════════════════════════════════════════╗
║         Backpack Exchange 量化交易系统 v1.0                  ║
╠══════════════════════════════════════════════════════════════╣
║  模式: {args.mode.upper():<50}║
║  交易对: {', '.join(args.symbols):<48}║
║  策略: {args.strategy:<50}║
║  交易所: {args.exchange:<48}║
╚══════════════════════════════════════════════════════════════╝
    """)

    if args.mode == 'backtest':
        run_backtest_demo()
    else:
        asyncio.run(run_live_demo(args))


if __name__ == '__main__':
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))

    main()
