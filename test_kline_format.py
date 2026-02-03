"""
快速测试Backpack API返回的K线格式

使用方法:
    python test_kline_format.py
"""
import asyncio
import logging
from datetime import datetime, timedelta
from backpack_quant_trading.core.api_client import BackpackAPIClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def test():
    client = BackpackAPIClient()
    symbol = "ETH_USDC_PERP"  # Backpack使用USDC而不是USDT
    
    # 获取最近10条K线
    start_time = int((datetime.now() - timedelta(hours=3)).timestamp())
    end_time = int(datetime.now().timestamp())
    
    logger.info(f"获取 {symbol} 的K线数据...")
    logger.info(f"时间范围: {datetime.fromtimestamp(start_time)} ~ {datetime.fromtimestamp(end_time)}")
    
    klines = await client.get_klines(
        symbol=symbol,
        interval="15m",
        start_time=start_time,
        end_time=end_time,
        limit=10
    )
    
    logger.info(f"="*80)
    logger.info(f"返回数据类型: {type(klines)}")
    logger.info(f"返回数据长度: {len(klines) if klines else 0}")
    logger.info(f"="*80)
    
    if klines and len(klines) > 0:
        logger.info(f"\n第一条K线:")
        logger.info(f"  类型: {type(klines[0])}")
        logger.info(f"  内容: {klines[0]}")
        
        if isinstance(klines[0], dict):
            logger.info(f"  字段: {list(klines[0].keys())}")
            logger.info(f"\n字段值:")
            for key, value in klines[0].items():
                logger.info(f"    {key}: {value} (类型: {type(value).__name__})")
        elif isinstance(klines[0], list):
            logger.info(f"  长度: {len(klines[0])}")
            logger.info(f"  元素:")
            for i, val in enumerate(klines[0]):
                logger.info(f"    [{i}]: {val} (类型: {type(val).__name__})")
    else:
        logger.error("未获取到数据!")
    
    await client.close_session()

if __name__ == "__main__":
    asyncio.run(test())
