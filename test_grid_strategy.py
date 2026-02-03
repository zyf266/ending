"""
网格交易策略测试
"""
import asyncio
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from backpack_quant_trading.strategy.grid_strategy import GridTradingStrategy
from backpack_quant_trading.core.api_client import BackpackAPIClient
from backpack_quant_trading.config.settings import config
from backpack_quant_trading.utils.logger import get_logger
logger = get_logger("test_grid")


async def test_grid_strategy():
    """测试网格策略基本功能"""
    
    logger.info("=" * 60)
    logger.info("🧪 开始测试网格交易策略")
    logger.info("=" * 60)
    
    # 初始化API客户端
    api_client = BackpackAPIClient(
        access_key=config.backpack.ACCESS_KEY,
        refresh_key=config.backpack.REFRESH_KEY
    )
    
    # 测试参数
    symbol = "ETH_USDC_PERP"
    price_lower = 3000.0
    price_upper = 3500.0
    grid_count = 10
    investment_per_grid = 10.0
    leverage = 10
    
    logger.info(f"\n📊 网格配置:")
    logger.info(f"   交易对: {symbol}")
    logger.info(f"   价格区间: ${price_lower} - ${price_upper}")
    logger.info(f"   网格数量: {grid_count}")
    logger.info(f"   单格投资: ${investment_per_grid}")
    logger.info(f"   杠杆倍数: {leverage}x")
    
    # 创建网格策略
    grid_strategy = GridTradingStrategy(
        symbol=symbol,
        price_lower=price_lower,
        price_upper=price_upper,
        grid_count=grid_count,
        investment_per_grid=investment_per_grid,
        leverage=leverage,
        api_client=api_client
    )
    
    logger.info("\n✅ 网格策略创建成功")
    
    # 显示网格层级
    logger.info(f"\n📋 网格层级详情:")
    df = grid_strategy.get_grid_levels_df()
    logger.info(f"\n{df.to_string()}")
    
    # 显示初始状态
    status = grid_strategy.get_status()
    logger.info(f"\n📊 初始状态:")
    logger.info(f"   运行中: {status['running']}")
    logger.info(f"   网格层级数: {status['grid_levels']}")
    logger.info(f"   挂单数: {status['pending_orders']}")
    
    # 注意：实际启动需要真实账户和余额
    logger.info(f"\n⚠️  如需测试实盘启动，请手动调用 grid_strategy.start()")
    logger.info(f"    测试命令: await grid_strategy.start()")
    
    logger.info("\n" + "=" * 60)
    logger.info("✅ 测试完成")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_grid_strategy())
