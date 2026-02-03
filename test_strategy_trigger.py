"""
测试脚本: 验证历史K线数据加载和AI策略触发

使用方法:
    python test_strategy_trigger.py
"""
import asyncio
import logging
from datetime import datetime, timedelta
from backpack_quant_trading.core.api_client import BackpackAPIClient
from backpack_quant_trading.core.data_manager import DataManager
from backpack_quant_trading.strategy.ai_adaptive import AIAdaptiveStrategy
from backpack_quant_trading.core.risk_manager import RiskManager
from backpack_quant_trading.config.settings import config

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def test_backpack_api():
    """测试1: Backpack API K线获取"""
    logger.info("="*80)
    logger.info("测试1: Backpack API K线获取")
    logger.info("="*80)
    
    client = BackpackAPIClient()
    symbol = "ETH_USDC_PERP"
    
    try:
        # 测试获取最近10条K线
        logger.info(f"正在获取 {symbol} 的最近10条15分钟K线...")
        start_time = int((datetime.now() - timedelta(hours=3)).timestamp())
        klines = await client.get_klines(symbol, "15m", start_time=start_time, limit=10)
        
        if klines:
            logger.info(f"✅ 成功获取 {len(klines)} 条K线")
            logger.info(f"📝 第一条K线样本:")
            logger.info(f"   类型: {type(klines[0])}")
            logger.info(f"   内容: {klines[0]}")
            
            # 检查数据格式
            first_kline = klines[0]
            if isinstance(first_kline, dict):
                logger.info(f"   字段: {list(first_kline.keys())}")
            elif isinstance(first_kline, list):
                logger.info(f"   长度: {len(first_kline)}")
            
            return True
        else:
            logger.error("❌ 未获取到K线数据")
            return False
    except Exception as e:
        logger.error(f"❌ API调用失败: {e}", exc_info=True)
        return False

async def test_data_manager():
    """测试2: DataManager数据加载"""
    logger.info("="*80)
    logger.info("测试2: DataManager数据加载")
    logger.info("="*80)
    
    client = BackpackAPIClient()
    data_manager = DataManager(api_client=client, mode="live")
    symbol = "ETH_USDC_PERP"
    
    try:
        # 获取历史K线并加载到缓存
        logger.info(f"正在获取 {symbol} 的1000条15分钟K线...")
        start_time = int((datetime.now() - timedelta(days=11)).timestamp())
        klines = await client.get_klines(symbol, "15m", start_time=start_time, limit=1000)
        
        logger.info(f"获取到 {len(klines)} 条K线，开始加载到缓存...")
        
        # 模拟live_trading.py中的数据加载逻辑
        for idx, k in enumerate(klines[:10]):  # 只测试前10条
            if isinstance(k, dict):
                # 处理字典格式
                time_val = k.get('start') or k.get('timestamp') or k.get('t')
                
                # 转换时间
                if isinstance(time_val, str):
                    from dateutil import parser
                    dt = parser.parse(time_val)
                    timestamp_ms = int(dt.timestamp() * 1000)
                else:
                    timestamp_ms = int(time_val * 1000) if time_val < 10000000000 else int(time_val)
                
                k_data = {
                    "t": timestamp_ms,
                    "o": str(k.get('open', 0)),
                    "h": str(k.get('high', 0)),
                    "l": str(k.get('low', 0)),
                    "c": str(k.get('close', 0)),
                    "v": str(k.get('volume', 0))
                }
            elif isinstance(k, list):
                k_data = {
                    "t": int(k[0] * 1000) if k[0] < 10000000000 else int(k[0]),
                    "o": str(k[1]),
                    "h": str(k[2]),
                    "l": str(k[3]),
                    "c": str(k[4]),
                    "v": str(k[5]) if len(k) > 5 else "0"
                }
            else:
                logger.warning(f"未知格式: {type(k)}")
                continue
            
            await data_manager.add_kline_data(symbol, k_data, interval="15m")
            logger.info(f"   [{idx+1}/10] 加载K线: 时间={k_data['t']}, 收盘={k_data['c']}")
        
        # 验证缓存
        df = await data_manager.fetch_recent_data(symbol, interval="15m", limit=50)
        logger.info(f"✅ 缓存验证: 共 {len(df)} 条数据")
        
        if not df.empty:
            logger.info(f"   最新K线时间: {df.index[-1]}")
            logger.info(f"   最新收盘价: {df['close'].iloc[-1]}")
            return True
        else:
            logger.error("❌ 缓存为空")
            return False
            
    except Exception as e:
        logger.error(f"❌ 数据加载失败: {e}", exc_info=True)
        return False

async def test_ai_strategy():
    """测试3: AI策略触发"""
    logger.info("="*80)
    logger.info("测试3: AI策略触发")
    logger.info("="*80)
    
    client = BackpackAPIClient()
    data_manager = DataManager(api_client=client, mode="live")
    risk_manager = RiskManager(config)
    symbol = "ETH_USDC_PERP"
    
    try:
        # 1. 加载历史数据
        logger.info(f"正在获取 {symbol} 的50条15分钟K线用于测试...")
        start_time = int((datetime.now() - timedelta(hours=13)).timestamp())
        klines = await client.get_klines(symbol, "15m", start_time=start_time, limit=50)
        
        # 2. 加载到缓存
        for k in klines:
            if isinstance(k, dict):
                time_val = k.get('start') or k.get('timestamp') or k.get('t')
                if isinstance(time_val, str):
                    from dateutil import parser
                    dt = parser.parse(time_val)
                    timestamp_ms = int(dt.timestamp() * 1000)
                else:
                    timestamp_ms = int(time_val * 1000) if time_val < 10000000000 else int(time_val)
                
                k_data = {
                    "t": timestamp_ms,
                    "o": str(k.get('open', 0)),
                    "h": str(k.get('high', 0)),
                    "l": str(k.get('low', 0)),
                    "c": str(k.get('close', 0)),
                    "v": str(k.get('volume', 0))
                }
            elif isinstance(k, list):
                k_data = {
                    "t": int(k[0] * 1000) if k[0] < 10000000000 else int(k[0]),
                    "o": str(k[1]),
                    "h": str(k[2]),
                    "l": str(k[3]),
                    "c": str(k[4]),
                    "v": str(k[5]) if len(k) > 5 else "0"
                }
            else:
                continue
            
            await data_manager.add_kline_data(symbol, k_data, interval="15m")
        
        # 3. 获取DataFrame
        df = await data_manager.fetch_recent_data(symbol, interval="15m", limit=50)
        logger.info(f"准备的数据: {len(df)} 条K线")
        
        if df.empty:
            logger.error("❌ 数据为空，无法测试策略")
            return False
        
        # 4. 创建AI策略
        logger.info("创建AI策略实例...")
        strategy = AIAdaptiveStrategy(
            symbols=[symbol],
            api_client=client,
            risk_manager=risk_manager,
            margin=100,
            leverage=50,
            stop_loss_ratio=0.015,
            take_profit_ratio=0.02
        )
        
        # 5. 调用策略
        logger.info("🤖 调用AI策略 calculate_signal...")
        signals = await strategy.calculate_signal({symbol: df})
        
        if signals:
            logger.info(f"✅ 策略生成 {len(signals)} 个信号:")
            for sig in signals:
                logger.info(f"   - {sig.action.upper()} {sig.symbol} @ {sig.price}, 数量: {sig.quantity}")
        else:
            logger.info("📊 策略执行完成，当前无交易信号")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ AI策略测试失败: {e}", exc_info=True)
        return False

async def main():
    """主测试流程"""
    logger.info("\n" + "="*80)
    logger.info("开始测试策略触发问题修复")
    logger.info("="*80 + "\n")
    
    results = {
        "Backpack API": False,
        "数据加载": False,
        "AI策略": False
    }
    
    # 测试1: API
    try:
        results["Backpack API"] = await test_backpack_api()
    except Exception as e:
        logger.error(f"测试1失败: {e}")
    
    await asyncio.sleep(2)
    
    # 测试2: 数据加载
    try:
        results["数据加载"] = await test_data_manager()
    except Exception as e:
        logger.error(f"测试2失败: {e}")
    
    await asyncio.sleep(2)
    
    # 测试3: AI策略
    try:
        results["AI策略"] = await test_ai_strategy()
    except Exception as e:
        logger.error(f"测试3失败: {e}")
    
    # 打印汇总
    logger.info("\n" + "="*80)
    logger.info("测试结果汇总:")
    logger.info("="*80)
    for test_name, passed in results.items():
        status = "✅ 通过" if passed else "❌ 失败"
        logger.info(f"  {test_name}: {status}")
    
    all_passed = all(results.values())
    logger.info("="*80)
    if all_passed:
        logger.info("🎉 所有测试通过！策略触发问题已修复。")
    else:
        logger.info("⚠️ 部分测试失败，请检查上方日志。")
    logger.info("="*80)

if __name__ == "__main__":
    asyncio.run(main())
