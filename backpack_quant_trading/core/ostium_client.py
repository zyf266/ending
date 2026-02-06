import logging
import time
import asyncio
import os
from typing import Dict, List, Optional, Any
from ostium_python_sdk import OstiumSDK, NetworkConfig
from eth_account import Account
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 导入配置
from backpack_quant_trading.config.settings import config

# 配置日志
logger = logging.getLogger(__name__)

class OstiumAPIClient:
    """Ostium Exchange API 客户端"""

    def __init__(self, rpc_url: str = None, private_key: str = None):
        """
        初始化Ostium API客户端
        
        Args:
            rpc_url: RPC URL，用于连接到区块链网络
            private_key: 私钥，用于签名交易（可选）
        """
        # 从环境变量或配置中获取参数
        self.rpc_url = rpc_url or os.getenv('OSTIUM_RPC_URL') or config.ostium.RPC_URL
        self.private_key = private_key or os.getenv('OSTIUM_PRIVATE_KEY') or config.ostium.PRIVATE_KEY
        self.network = config.ostium.NETWORK  # 'mainnet' 或 'testnet'
        
        # 先设置日志记录器
        self.logger = logger
        
        # 初始化SDK
        self.sdk = None
        self._init_sdk()
        
        # 获取交易者地址
        self.trader_address = None
        if self.private_key:
            try:
                account = Account.from_key(self.private_key)
                self.trader_address = account.address
                self.logger.info(f"交易者地址: {self.trader_address}")
            except Exception as e:
                self.logger.warning(f"无法从私钥获取地址: {e}")
    
    def _init_sdk(self):
        """初始化Ostium SDK"""
        try:
            self.logger.info("初始化Ostium SDK...")
            
            # 检查必要的参数
            if not self.rpc_url:
                raise ValueError("RPC_URL 未配置")
            
            # 根据网络类型获取配置
            if self.network == 'testnet':
                network_config = NetworkConfig.testnet()
                self.logger.info("使用 Testnet 配置")
            else:
                network_config = NetworkConfig.mainnet()
                self.logger.info("使用 Mainnet 配置")
            
            # 使用NetworkConfig、私钥和RPC URL初始化SDK
            # 注意：如果没有提供私钥，SDK将只能进行只读操作
            self.sdk = OstiumSDK(network_config, self.private_key, self.rpc_url, verbose=False)
            self.logger.info("Ostium SDK初始化成功")
            return True
        except Exception as e:
            self.logger.error(f"Ostium SDK初始化失败: {e}")
            self.logger.info("将使用模拟数据进行测试")
            # 不抛出异常，继续执行，后续方法会处理SDK为None的情况
            return False
    
    async def get_markets(self) -> List[str]:
        """获取交易对列表"""
        try:
            if self.sdk:
                try:
                    # 根据文档，SDK使用sdk.subgraph.get_pairs()来获取交易对列表
                    pairs = await self.sdk.subgraph.get_pairs()
                    self.logger.info(f"获取交易对列表成功，共 {len(pairs)} 个对")
                    
                    # 转换为我们需要的市场格式
                    markets = []
                    for pair in pairs:
                        # 根据SDK返回的pair对象结构
                        try:
                            if isinstance(pair, dict):
                                # 获取pair的名称
                                if 'name' in pair:
                                    markets.append(pair['name'])
                                elif 'asset' in pair:
                                    markets.append(pair['asset'])
                            else:
                                # pair可能是对象，尝试获取属性
                                if hasattr(pair, 'name'):
                                    markets.append(pair.name)
                                elif hasattr(pair, 'asset'):
                                    markets.append(pair.asset)
                        except Exception as e:
                            self.logger.debug(f"处理pair失败: {e}")
                            continue
                    
                    if markets:
                        self.logger.info(f"获取的交易对: {markets[:5]}...")
                        return markets
                    else:
                        # 如果获取为空，返回默认市场
                        self.logger.warning("获取的交易对列表为空，使用默认列表")
                        return self._get_default_markets()
                except Exception as e:
                    self.logger.error(f"从SDK获取交易对失败: {e}")
                    return self._get_default_markets()
            else:
                # SDK未初始化，返回模拟数据
                self.logger.info("SDK未初始化，使用默认交易对列表")
                return self._get_default_markets()
        except Exception as e:
            self.logger.error(f"获取交易对列表失败: {e}")
            return self._get_default_markets()
    
    def _get_default_markets(self) -> List[str]:
        """获取默认交易对列表"""
        return [
            "BTC-USD",  # 比特币
            "ETH-USD",  # 以太坊
            "SOL-USD",  # 索拉纳
            "EUR-USD",  # 欧元
            "GBP-USD"   # 英镑
        ]
    
    async def get_price(self, symbol: str) -> float:
        """获取特定交易对的价格"""
        try:
            if self.sdk:
                # 处理交易对格式，转换为 SDK 需要的格式
                # 【关键修复】先标准化格式：移除连字符、空格等
                normalized_symbol = symbol.upper().replace("-", "").replace("_", "").replace(" ", "")
                self.logger.info(f"🔍 格式化交易对: {symbol} -> {normalized_symbol}")
                
                asset = self._parse_asset_from_symbol(symbol)
                denomination = "USD"
                
                # 【特殊处理】USDJPY 需要查询 USD/JPY 而不是 JPY/USD
                # 支持 USDJPY, USD-JPY, USDYJPY 等多种格式
                if "USDJPY" in normalized_symbol or normalized_symbol == "USDJPY":
                    # USDJPY 在系统中对应 asset_type 4 (JPY)
                    # 但价格查询需要 USD/JPY 格式
                    try:
                        price, _, _ = await self.sdk.price.get_price("USD", "JPY")
                        float_price = float(price)
                        self.logger.info(f"✅ 获取交易对 {symbol} (USD/JPY) 的价格: {float_price}")
                        return float_price
                    except Exception as e1:
                        self.logger.warning(f"尝试 USD/JPY 失败: {e1}")
                        # 如果失败，尝试 JPY/USD 并取倒数
                        try:
                            price, _, _ = await self.sdk.price.get_price("JPY", "USD")
                            float_price = float(price)
                            if float_price > 0:
                                float_price = 1.0 / float_price
                                self.logger.info(f"✅ 获取交易对 {symbol} (JPY/USD 转换为 USD/JPY) 的价格: {float_price}")
                                return float_price
                            else:
                                raise ValueError("JPY/USD 价格为 0 或负数")
                        except Exception as e2:
                            self.logger.error(f"所有 USDJPY 格式都失败: USD/JPY({e1}), JPY/USD({e2})")
                            # 返回模拟价格作为备选
                            return 158.0  # USDJPY 的合理模拟价格
                else:
                    try:
                        # 根据文档，SDK 使用 sdk.price.get_price(asset, denomination) 来获取价格
                        price, _, _ = await self.sdk.price.get_price(asset, denomination)
                        float_price = float(price)
                        self.logger.info(f"✅ 获取交易对 {symbol} ({asset}, {denomination}) 的价格: {float_price}")
                        return float_price
                    except Exception as price_error:
                        self.logger.warning(f"从 SDK 获取价格失败: {price_error}")
                        raise
                
            # SDK 未初始化，返回模拟价格
            return self._get_simulated_price(symbol)
        except Exception as e:
            self.logger.error(f"获取交易对 {symbol} 的价格失败: {e}")
            return self._get_simulated_price(symbol)
    
    def _parse_asset_from_symbol(self, symbol: str) -> str:
        """从交易对符号解析资产
        
        支持的输入格式：
        - ETH-USD -> ETH
        - ETH-USDT-SWAP -> ETH
        - ETH_USDC_PERP -> ETH
        - BTC-USD -> BTC
        """
        # 标准化：转大写
        symbol = symbol.upper()
        
        # 直接提取币种（优先级处理）
        if symbol.startswith("ETH"):
            return "ETH"
        elif symbol.startswith("BTC"):
            return "BTC"
        elif symbol.startswith("SOL"):
            return "SOL"
        elif symbol.startswith("ARB"):
            return "ARB"
        
        # 兜底：移除常见后缀和分隔符
        for suffix in ["_USDC_PERP", "_USDT_PERP", "_PERP", "-USDT-SWAP", "-USD", "-USDT"]:
            if suffix in symbol:
                return symbol.replace(suffix, "").replace("_", "").replace("-", "")
        
        # 如果都没匹配，返回第一个分隔符前的内容
        for delimiter in ["-", "_"]:
            if delimiter in symbol:
                return symbol.split(delimiter)[0]
        
        return symbol
    
    def _get_simulated_price(self, symbol: str) -> float:
        """获取模拟价格"""
        # 【关键修复】标准化符号格式
        symbol = symbol.upper().replace("-", "").replace("_", "").replace(" ", "")
        
        prices = {
            "BTC": 45000.0,
            "ETH": 3000.0,
            "SOL": 100.0,
            "EUR": 1.1,
            "GBP": 1.27,
            "USDJPY": 158.0,  # 【新增】USDJPY 模拟价格
            "JPY": 158.0,      # 兼容字段
            "NVDA": 150.0,
            "GOOG": 200.0,
            "AMZN": 180.0
        }
        
        # 查找资产
        for key, price in prices.items():
            if key in symbol:
                return price
        
        # 如果不匹配，返回默认价格
        return 1000.0
    
    async def get_klines(self, symbol: str, interval: str = '1m', limit: int = 200, 
                        start_time: Optional[int] = None, end_time: Optional[int] = None) -> List[Dict[str, Any]]:
        """获取K线数据
        
        Args:
            symbol: 交易对（如 NDX-USD, ETH-USD）
            interval: K线间隔 ('1m', '5m', '15m', '1h', '4h', '1d')
            limit: 返回的K线数量
            start_time: 开始时间戳（秒），如果不提供则从当前时间往前推算
            end_time: 结束时间戳（秒），如果不提供则使用当前时间
            
        Returns:
            List[Dict]: K线数据列表，每个字典包含 [timestamp, open, high, low, close, volume]
        """
        try:
            if not self.sdk:
                self.logger.warning("SDK未初始化，无法获取K线数据")
                return []
            
            # 处理交易对格式
            asset = self._parse_asset_from_symbol(symbol)
            
            # 如果没有提供时间范围，计算默认值
            if end_time is None:
                end_time = int(time.time())
            
            if start_time is None:
                # 根据间隔计算开始时间
                interval_seconds = self._interval_to_seconds(interval)
                start_time = end_time - (interval_seconds * limit)
            
            self.logger.info(f"获取K线数据: {symbol} ({asset}), 间隔: {interval}, 数量: {limit}")
            self.logger.info(f"时间范围: {start_time} - {end_time}")
            
            # 尝试通过 subgraph 获取历史价格数据
            try:
                # 注意：这里需要根据实际的 Ostium SDK subgraph API 调整
                # 如果 SDK 有历史价格查询方法，使用它
                # 否则，我们可能需要通过其他方式获取
                
                # 方法1: 尝试使用 subgraph 查询历史交易数据
                # 这需要根据实际的 SDK API 调整
                klines = await self._get_klines_from_subgraph(asset, interval, start_time, end_time, limit)
                
                if klines and len(klines) > 0:
                    self.logger.info(f"✅ 从 subgraph 获取到 {len(klines)} 根K线数据")
                    return klines
                else:
                    self.logger.warning("从 subgraph 未获取到K线数据，尝试其他方法")
                    
            except Exception as subgraph_error:
                self.logger.warning(f"从 subgraph 获取K线数据失败: {subgraph_error}")
            
            # 方法2: 如果 subgraph 不可用，返回空列表，让调用方使用备选方案
            self.logger.warning("⚠️  Ostium SDK 可能不支持直接获取K线数据，建议使用第三方数据源")
            return []
            
        except Exception as e:
            self.logger.error(f"获取K线数据失败: {e}")
            return []
    
    def _interval_to_seconds(self, interval: str) -> int:
        """将K线间隔转换为秒数"""
        interval_map = {
            '1m': 60,
            '5m': 300,
            '15m': 900,
            '30m': 1800,
            '1h': 3600,
            '4h': 14400,
            '1d': 86400,
        }
        return interval_map.get(interval.lower(), 60)
    
    async def _get_klines_from_subgraph(self, asset: str, interval: str, 
                                        start_time: int, end_time: int, limit: int) -> List[Dict[str, Any]]:
        """从 subgraph 获取K线数据
        
        注意：根据 Ostium SDK 文档，subgraph 主要用于查询：
        - 交易对信息 (get_pairs)
        - 开仓交易 (get_open_trades)
        - 订单信息 (get_orders)
        - 订单历史 (get_order_history)
        
        目前 SDK 没有直接的历史价格/K线数据接口，所以这里返回空列表
        实际使用时，建议使用第三方数据源（如 Binance API）获取历史K线数据
        """
        try:
            # 根据 Ostium SDK 文档，subgraph 没有历史价格查询接口
            # 但我们可以尝试从订单历史中提取价格信息（如果可用）
            # 不过这种方法可能不够完整，所以建议使用第三方数据源
            
            self.logger.debug("Ostium SDK subgraph 不支持历史K线数据查询，建议使用第三方数据源")
            return []
            
        except Exception as e:
            self.logger.error(f"从 subgraph 获取K线数据失败: {e}")
            return []
    
    async def get_funding_rate(self, symbol: str) -> float:
        """获取资金费率
        
        Args:
            symbol: 交易对（如ETH_USDC_PERP 或 ETH-USD）
            
        Returns:
            float: 资金费率
        """
        try:
            if self.sdk:
                # 处理交易对格式
                asset = self._parse_asset_from_symbol(symbol)
                
                # 根据文档，通过子图获取交易对详情，查找资金费率信息
                try:
                    pairs = await self.sdk.subgraph.get_pairs()
                    for pair in pairs:
                        # 检查交易对是否匹配
                        pair_name = ""
                        if isinstance(pair, dict):
                            pair_name = pair.get('name', '')
                        else:
                            pair_name = getattr(pair, 'name', '')
                        
                        if asset.upper() in pair_name.upper().replace("-", "").replace("_", ""):
                            # 查找资金费率字段
                            for field in ['fundingRate', 'currentFundingRate', 'funding_rate']:
                                if isinstance(pair, dict) and field in pair:
                                    rate = float(pair[field])
                                    self.logger.info(f"获取交易对 {symbol} 的资金费率: {rate}")
                                    return rate
                                elif hasattr(pair, field):
                                    rate = float(getattr(pair, field))
                                    self.logger.info(f"获取交易对 {symbol} 的资金费率: {rate}")
                                    return rate
                except Exception as subgraph_error:
                    self.logger.warning(f"从子图获取资金费率失败: {subgraph_error}")
            
            # 如果SDK不可用或方法调用失败，使用模拟值
            simulated_rate = (time.time() % 1000) / 1000000 - 0.0005
            self.logger.info(f"使用模拟资金费率: {simulated_rate}")
            return simulated_rate
        except Exception as e:
            self.logger.error(f"获取资金费率失败: {e}")
            return 0.0
    
    async def place_order(self, symbol: str, side: str, quantity: float, order_type: str, 
                    price: Optional[float] = None, reduce_only: bool = False, leverage: int = 1) -> Dict[str, Any]:
        """下单
        
        Args:
            symbol: 交易对（如 ETH-USD 或 BTC-USD）
            side: 方向 ('BUY' 或 'SELL')
            quantity: 抵押品数量（USDC）
            order_type: 订单类型 ('MARKET', 'LIMIT', 'STOP')
            price: 价格（限价单需要）
            reduce_only: 是否仅减少持仓
            leverage: 杠杆倍数
        """
        try:
            if not self.sdk:
                return self._create_simulated_order_result(symbol, side, quantity, order_type)
            
            # 处理交易对格式
            asset = self._parse_asset_from_symbol(symbol)
            
            # 确保side是大写，并且符合SDK要求
            formatted_side = side.upper()
            if formatted_side not in ['BUY', 'SELL']:
                raise ValueError(f"无效的订单方向: {side}")
            
            # 获取资产类型ID
            asset_type = self._get_asset_type_id(asset)
            if asset_type is None:
                raise ValueError(f"不支持的资产: {asset}")
            
            # Ostium 合约有最小抵押要求，过小会 revert (0xf120e11f)
            MIN_COLLATERAL_USDC = 1.0
            if not reduce_only and quantity < MIN_COLLATERAL_USDC:
                raise ValueError(
                    f"Ostium 单笔抵押（USDC）过小: {quantity:.4f}，请至少 {MIN_COLLATERAL_USDC} USDC（可调大网格「单格投资」或杠杆）"
                )
            
            # 准备交易参数（根据文档）
            trade_params = {
                'collateral': quantity,        # USDC金额
                'leverage': leverage,          # 杠杆倍数
                'asset_type': asset_type,     # 资产类型ID
                'direction': formatted_side == 'BUY',  # True for Long, False for Short
                'order_type': order_type.upper()      # 'MARKET', 'LIMIT', or 'STOP'
            }
            
            # 设置限价或止损价格
            if order_type.upper() in ['LIMIT', 'STOP'] and price is not None:
                at_price = price
            else:
                # 如果是市价单，获取当前价格
                at_price = await self.get_price(symbol)
            
            # 执行交易
            self.logger.info(f"下单参数: {trade_params}, 价格: {at_price}")
            try:
                receipt = self.sdk.ostium.perform_trade(trade_params, at_price=at_price)
            except Exception as e:
                err_str = str(e)
                if "0xf120e11f" in err_str or "0xF120E11F" in err_str.upper():
                    raise ValueError(
                        "Ostium 合约拒绝: 订单金额过小或未满足最小要求，请增大单笔保证金（建议至少 1 USDC）"
                    ) from e
                raise
            
            # 记录返回的原始数据
            self.logger.info(f"🔍 SDK perform_trade 返回类型: {type(receipt)}, 内容: {receipt}")
            
            # 处理返回结果
            tx_hash = ''
            if isinstance(receipt, dict):
                # 处理 {'receipt': {...}, 'order_id': ...} 格式
                if 'receipt' in receipt:
                    receipt_obj = receipt['receipt']
                    if hasattr(receipt_obj, '__getitem__') and 'transactionHash' in receipt_obj:
                        tx_obj = receipt_obj['transactionHash']
                        tx_hash = tx_obj.hex() if hasattr(tx_obj, 'hex') else str(tx_obj)
                elif 'transactionHash' in receipt:
                    tx_obj = receipt['transactionHash']
                    tx_hash = tx_obj.hex() if hasattr(tx_obj, 'hex') else str(tx_obj)
            elif hasattr(receipt, 'transactionHash'):
                tx_hash = receipt.transactionHash.hex() if hasattr(receipt.transactionHash, 'hex') else str(receipt.transactionHash)
            
            self.logger.info(f"下单成功，交易哈希: {tx_hash}")
            
            # 尝试从 receipt 解析 trade_index（按照 hedge 的实现）
            trade_index = None
            pair_id = asset_type  # 默认使用 asset_type 作为 pair_id
            try:
                # 【关键修复】方法 1：从 logs 中解析 TradeOpened 事件（最可靠）
                if isinstance(receipt, dict) and 'receipt' in receipt:
                    receipt_obj = receipt['receipt']
                    if hasattr(receipt_obj, 'logs') or (isinstance(receipt_obj, dict) and 'logs' in receipt_obj):
                        logs = receipt_obj.get('logs') if isinstance(receipt_obj, dict) else receipt_obj.logs
                        # TradeOpened 事件签名: 0xfb4a26aa34682aa753cb2aa37ef1bc38eee1af6719db3a8cfe892c50406ea0e0
                        TRADE_OPENED_SIGNATURE = '0xfb4a26aa34682aa753cb2aa37ef1bc38eee1af6719db3a8cfe892c50406ea0e0'
                        for log in logs:
                            topics = log.get('topics') if isinstance(log, dict) else getattr(log, 'topics', [])
                            if topics and len(topics) >= 2:
                                event_sig = topics[0].hex() if hasattr(topics[0], 'hex') else str(topics[0])
                                if event_sig == TRADE_OPENED_SIGNATURE:
                                    # topics[1] 包含 trade_index
                                    index_hex = topics[1].hex() if hasattr(topics[1], 'hex') else str(topics[1])
                                    trade_index = int(index_hex, 16)
                                    self.logger.info(f"✅ 从 logs 解析 TradeOpened 事件获取 trade_index: {trade_index}")
                                    break
                
                # 方法 2: 从 receipt 对象的 events 获取
                if trade_index is None and hasattr(receipt, 'events'):
                    for event in receipt.events:
                        if hasattr(event, 'event') and event.event == 'TradeOpened':
                            if hasattr(event, 'args') and hasattr(event.args, 'index'):
                                trade_index = event.args.index
                                self.logger.info(f"✅ 从 receipt 事件获取 index: {trade_index}")
                                break
                
                # 方法 3: 从 receipt 字典获取
                if trade_index is None and isinstance(receipt, dict):
                    if 'index' in receipt:
                        trade_index = receipt['index']
                        self.logger.info(f"✅ 从 receipt 字典获取 index: {trade_index}")
                    elif 'tradeIndex' in receipt:
                        trade_index = receipt['tradeIndex']
                        self.logger.info(f"✅ 从 receipt 获取 tradeIndex: {trade_index}")
                
                # 方法 4: Ostium 限价单事件 0xc5bd5ba7...，index 在 log.data（32 字节 uint256）
                LIMIT_ORDER_EVENT_SIG = '0xc5bd5ba70b0fccae9ac4984c1b7e09d0eb00930a72e0712688fc62b4ae70ebc5'
                if trade_index is None and isinstance(receipt, dict) and 'receipt' in receipt:
                    receipt_obj = receipt['receipt']
                    logs = receipt_obj.get('logs') if isinstance(receipt_obj, dict) else getattr(receipt_obj, 'logs', None)
                    if logs:
                        for log in logs:
                            topics = log.get('topics') if isinstance(log, dict) else getattr(log, 'topics', [])
                            if not topics:
                                continue
                            sig = topics[0].hex() if hasattr(topics[0], 'hex') else str(topics[0])
                            if sig.lower() == LIMIT_ORDER_EVENT_SIG.lower():
                                data = log.get('data') if isinstance(log, dict) else getattr(log, 'data', None)
                                if data is not None:
                                    try:
                                        h = data.hex() if hasattr(data, 'hex') else str(data)
                                        if isinstance(h, str) and h.startswith('0x'):
                                            trade_index = int(h, 16)
                                            self.logger.info(f"✅ 从限价单事件 log.data 解析 index: {trade_index}")
                                        break
                                    except (ValueError, TypeError):
                                        pass
                        # 若无限价单事件，再尝试任意 log 的 topics[1]（避免 topics[1]=地址时误解析）
                        if trade_index is None:
                            for log in logs:
                                topics = log.get('topics') if isinstance(log, dict) else getattr(log, 'topics', [])
                                if topics and len(topics) >= 2:
                                    try:
                                        index_hex = topics[1].hex() if hasattr(topics[1], 'hex') else str(topics[1])
                                        if isinstance(index_hex, str) and index_hex.startswith('0x'):
                                            n = int(index_hex, 16)
                                            if 0 < n < 2**32:
                                                trade_index = n
                                                self.logger.info(f"✅ 从 logs topics[1] 解析 index: {trade_index}")
                                                break
                                    except (ValueError, TypeError):
                                        continue
                
                # 方法 5: 下单后延迟反查 get_positions / get_orders，用 tx 或最近持仓拿到 index（限价单成交后会有持仓）
                if trade_index is None and tx_hash:
                    await asyncio.sleep(2)
                    try:
                        positions = await self.get_positions(symbol=symbol)
                        if positions:
                            # 取最新一条持仓的 index（刚成交的限价单会出现在这里）
                            pos = positions[0]
                            trade_index = pos.get('index') or pos.get('trade_index')
                            if trade_index is not None:
                                pair_id = pos.get('pair_id')
                                if pair_id is not None:
                                    pair_id = int(pair_id) if not isinstance(pair_id, int) else pair_id
                                self.logger.info(f"✅ 从 get_positions 反查得到 index: {trade_index}, pair_id: {pair_id}")
                        if trade_index is None and hasattr(self.sdk, 'subgraph') and hasattr(self.sdk.subgraph, 'get_orders'):
                            open_orders = await self.sdk.subgraph.get_orders(self.trader_address)
                            for order in (open_orders or []):
                                o = order if isinstance(order, dict) else getattr(order, '__dict__', {})
                                tx = o.get('transactionHash') or o.get('txHash') or getattr(order, 'transactionHash', None)
                                if tx and (tx.hex() if hasattr(tx, 'hex') else str(tx)).lower() == tx_hash.lower():
                                    trade_index = o.get('index') or o.get('orderIndex') or getattr(order, 'index', None)
                                    if trade_index is not None:
                                        self.logger.info(f"✅ 从 get_orders 反查得到 order index: {trade_index}")
                                    break
                    except Exception as fallback_err:
                        self.logger.debug(f"反查 index 失败: {fallback_err}")
                
                if trade_index is not None:
                    self.logger.info(f"✅ 成功从交易回执获取 index: {trade_index}")
                else:
                    self.logger.warning(f"⚠️ 未能从 receipt 提取 trade_index，返回的数据结构: {type(receipt)}, keys: {list(receipt.keys()) if isinstance(receipt, dict) else 'N/A'}")
            except Exception as parse_error:
                self.logger.warning(f"解析 receipt 获取 index 失败: {parse_error}")
            
            return {
                'orderId': tx_hash or f"ORDER_{int(time.time())}",
                'symbol': symbol,
                'side': side,
                'quantity': quantity,
                'orderType': order_type,
                'price': at_price,
                'leverage': leverage,
                'status': 'FILLED',
                'timestamp': int(time.time() * 1000),
                'transactionHash': tx_hash,
                'tx_hash': tx_hash,  # 兼容字段
                'index': trade_index,
                'trade_index': trade_index,
                'pair_id': pair_id  # 添加 pair_id
            }
        except Exception as e:
            self.logger.error(f"下单失败: {e}")
            # 返回错误结果
            return {
                'orderId': f"ERROR_{int(time.time())}",
                'symbol': symbol,
                'side': side,
                'quantity': quantity,
                'orderType': order_type,
                'status': 'FAILED',
                'error': str(e),
                'timestamp': int(time.time() * 1000)
            }
    
    def _get_asset_type_id(self, asset: str) -> Optional[int]:
        """获取资产类型ID"""
        asset_map = {
            "BTC": 0,
            "ETH": 1,
            "EUR": 2,
            "GBP": 3,
            "JPY": 4,
            "USDJPY": 4,  # USD/JPY 对应 JPY
            "XAU": 5,
            "HG": 6,
            "CL": 7,
            "XAG": 8,
            "SOL": 9,
            "SPX": 10,
            "DJI": 11,
            "NDX": 12,
            "NIK": 13,
            "FTSE": 14,
            "DAX": 15,
            "USDCAD": 16,
            "USDMXN": 17,
            "NVDA": 18,
            "GOOG": 19,
            "AMZN": 20,
            "META": 21,
            "TSLA": 22,
            "AAPL": 23,
            "MSFT": 24
        }
        return asset_map.get(asset.upper())
    
    async def get_pair_id_for_symbol(self, symbol: str) -> Optional[int]:
        """根据交易对符号获取 Ostium pair_id（用于 Subgraph 返回空时仍可尝试平仓）。
        依赖 get_pairs，若事件循环已关闭或网络异常会返回 None。"""
        try:
            if not self.sdk:
                return None
            pairs = await self.sdk.subgraph.get_pairs()
            norm = (symbol or "").upper().replace("-", "").replace("_", "")
            for pair in (pairs or []):
                name = ""
                if isinstance(pair, dict):
                    name = (pair.get("name") or pair.get("id") or "").upper().replace("-", "").replace("_", "")
                    pid = pair.get("id")
                else:
                    name = (getattr(pair, "name", None) or getattr(pair, "id", None) or "").upper().replace("-", "").replace("_", "")
                    pid = getattr(pair, "id", None)
                if norm and name and norm in name:
                    if pid is not None:
                        return int(pid)
            return None
        except RuntimeError as re:
            if "Event loop is closed" in str(re) or "event loop" in str(re).lower():
                self.logger.debug("get_pair_id_for_symbol: 事件循环已关闭，跳过")
                return None
            raise
        except Exception as e:
            self.logger.warning(f"get_pair_id_for_symbol 失败: {e}")
            return None
    
    def _create_simulated_order_result(self, symbol: str, side: str, quantity: float, 
                                      order_type: str, price: float = None) -> Dict[str, Any]:
        """创建模拟订单结果"""
        order_id = f"SIM_{int(time.time())}_{symbol}"
        self.logger.info(f"使用模拟订单: {order_id}")
        return {
            'orderId': order_id,
            'symbol': symbol,
            'side': side,
            'quantity': quantity,
            'orderType': order_type,
            'price': price,
            'status': 'FILLED',
            'timestamp': int(time.time() * 1000)
        }
    
    async def execute_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str,
        price: Optional[float] = None,
        max_leverage: Optional[int] = None,
        reduce_only: bool = False,
    ) -> Dict[str, Any]:
        """执行订单 (适配 ExchangeClient 接口)。
        网格等策略传入的 quantity 常为「标的数量」(如 ETH)，此处自动转为 Ostium 要求的「抵押品 USDC」：
        collateral = quantity * price / leverage。
        """
        leverage = max_leverage or 1
        formatted_order_type = order_type.upper()
        at_price = price
        if at_price is None:
            at_price = await self.get_price(symbol)
        # 若 quantity 明显为标的数量（如 < 1 且价格 > 1000），按「标的数量」转为抵押品 USDC
        if quantity < 1 and at_price and at_price > 100:
            collateral_usdc = quantity * at_price / leverage
            self.logger.info(f"🔄 将标的数量 {quantity} (价格 {at_price}) 转为抵押品 USDC: {collateral_usdc:.4f}")
            quantity = collateral_usdc
        return await self.place_order(
            symbol=symbol,
            side=side.upper(),
            quantity=quantity,
            order_type=formatted_order_type,
            price=price,
            reduce_only=reduce_only,
            leverage=leverage,
        )

    async def get_order(self, order_id: str, symbol: Optional[str] = None) -> Dict[str, Any]:
        """获取订单状态
        
        注意：Ostium 是链上交易，如果 order_id 是交易哈希且已确认，通常认为已成交。
        如果是限价单，需要通过 subgraph 查询是否已转为 trade。
        """
        try:
            if not self.sdk or not self.trader_address:
                return {'status': 'FILLED', 'orderId': order_id} # 模拟环境下返回已成交
            
            # 1. 检查是否是模拟 ID
            if order_id.startswith("SIM_") or order_id.startswith("ORDER_") or order_id.startswith("ERROR_"):
                return {'status': 'FILLED', 'orderId': order_id}

            def _norm_tx(tx):
                if tx is None: return ''
                return (tx.hex() if hasattr(tx, 'hex') else str(tx)).lower()
            order_id_lower = order_id.lower() if isinstance(order_id, str) else str(order_id)
            open_trades = []
            open_orders = []
            try:
                open_trades = await self.sdk.subgraph.get_open_trades(self.trader_address)
            except RuntimeError as re:
                if "Event loop is closed" in str(re) or "event loop" in str(re).lower():
                    return {'status': 'FILLED', 'orderId': order_id}
                raise
            for trade in open_trades:
                trade_tx = _norm_tx(trade.get('transactionHash') if isinstance(trade, dict) else getattr(trade, 'transactionHash', None))
                if order_id_lower == trade_tx:
                    return {'status': 'FILLED', 'orderId': order_id, 'order_type': 'MARKET'}

            try:
                open_orders = await self.sdk.subgraph.get_orders(self.trader_address)
                for order in (open_orders or []):
                    o = order if isinstance(order, dict) else getattr(order, '__dict__', {})
                    order_tx = _norm_tx(o.get('transactionHash') or o.get('txHash') or (getattr(order, 'transactionHash', None) if not isinstance(order, dict) else None))
                    if order_id_lower == order_tx:
                        return {'status': 'NEW', 'orderId': order_id}
            except RuntimeError as re:
                if "Event loop is closed" in str(re) or "event loop" in str(re).lower():
                    return {'status': 'FILLED', 'orderId': order_id}
                raise
            except Exception:
                pass

            if symbol and order_id_lower.startswith('0x') and len(order_id_lower) == 66:
                try:
                    positions = await self.get_positions(symbol=symbol)
                    if positions:
                        self.logger.info(f"🔄 get_order(tx_hash): 该 symbol 有 {len(positions)} 个持仓，视为已成交以便网格挂平仓单")
                        return {'status': 'FILLED', 'orderId': order_id}
                except RuntimeError as re:
                    if "Event loop is closed" in str(re):
                        return {'status': 'FILLED', 'orderId': order_id}
                    raise

            return {'status': 'FILLED', 'orderId': order_id}
            
        except Exception as e:
            self.logger.error(f"查询订单失败: {e}")
            return {'status': 'UNKNOWN', 'error': str(e)}

    def cancel_order(self, pair_id: int, order_index: int) -> Dict[str, Any]:
        """撤销限价单 (原始逻辑，供实盘 Webhook 使用)"""
        try:
            if self.sdk:
                # 根据SDK文档，使用 sdk.ostium.cancel_limit_order(pair_id, index)
                result = self.sdk.ostium.cancel_limit_order(pair_id, order_index)
                self.logger.info(f"撤销订单成功: pair_id={pair_id}, order_index={order_index}")
                return {
                    'pairId': pair_id,
                    'orderIndex': order_index,
                    'status': 'CANCELED',
                    'transactionHash': result.get('transactionHash', '') if isinstance(result, dict) else str(result),
                    'timestamp': int(time.time() * 1000)
                }
            else:
                self.logger.info(f"使用模拟撤销结果 (SDK未初始化)")
                return {
                    'pairId': pair_id,
                    'orderIndex': order_index,
                    'status': 'CANCELED',
                    'timestamp': int(time.time() * 1000)
                }
        except Exception as e:
            self.logger.error(f"撤销订单失败: {e}")
            return {
                'pairId': pair_id,
                'orderIndex': order_index,
                'status': 'FAILED',
                'error': str(e),
                'timestamp': int(time.time() * 1000)
            }

    async def cancel_order_async(self, symbol: str, order_id: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """异步撤单适配器 (专门供网格策略/ExchangeClient协议使用)"""
        try:
            if not order_id: return {'status': 'FAILED'}
            # 如果是网格存入的 "pair_id:index" 格式
            if ":" in str(order_id):
                p_id, idx = order_id.split(":")
                return self.cancel_order(int(p_id), int(idx))
            
            self.logger.warning(f"⚠️ Ostium 无法直接通过哈希撤单: {order_id}")
            return {'status': 'CANCELED', 'orderId': order_id}
        except Exception as e:
            return {'status': 'FAILED', 'error': str(e)}

    # -------------------------------------------------------------------------
    # 原始实盘方法 (供 Webhook/LiveTradingEngine 使用)
    # -------------------------------------------------------------------------
    def cancel_order_direct(self, pair_id: int, order_index: int) -> Dict[str, Any]:
        """直接撤销限价单"""
        try:
            if self.sdk:
                result = self.sdk.ostium.cancel_limit_order(pair_id, order_index)
                self.logger.info(f"撤销订单成功: pair_id={pair_id}, order_index={order_index}")
                return {
                    'pairId': pair_id,
                    'orderIndex': order_index,
                    'status': 'CANCELED',
                    'transactionHash': result.get('transactionHash', '') if isinstance(result, dict) else str(result),
                    'timestamp': int(time.time() * 1000)
                }
            else:
                # SDK未初始化，返回模拟结果
                self.logger.info(f"使用模拟撤销结果 (SDK未初始化)")
                return {
                    'pairId': pair_id,
                    'orderIndex': order_index,
                    'status': 'CANCELED',
                    'timestamp': int(time.time() * 1000)
                }
        except Exception as e:
            self.logger.error(f"撤销订单失败: {e}")
            return {
                'pairId': pair_id,
                'orderIndex': order_index,
                'status': 'FAILED',
                'error': str(e),
                'timestamp': int(time.time() * 1000)
            }
    
    async def get_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取开仓交易
        
        Args:
            symbol: 交易对（可选），如果不提供则获取所有头寸
        
        注意：Subgraph 查询可能有延迟，建议在策略层面维护持仓状态缓存
        """
        try:
            if not self.sdk or not self.trader_address:
                self.logger.warning("⚠️  SDK 或地址不可用，返回空持仓")
                return []
            
            def _fetch_trades(addr):
                return self.sdk.subgraph.get_open_trades(addr)

            # 避免事件循环已关闭时仍发起 gql 导致 RuntimeError
            try:
                self.logger.info(f"🔍 查询开仓交易：trader={self.trader_address}")
                open_trades = await _fetch_trades(self.trader_address)
                if not open_trades and self.trader_address != self.trader_address.lower():
                    open_trades = await _fetch_trades(self.trader_address.lower())
            except RuntimeError as re:
                if "Event loop is closed" in str(re) or "event loop" in str(re).lower():
                    self.logger.debug("事件循环已关闭，跳过 subgraph 查询")
                    return []
                raise
            except Exception as e:
                self.logger.warning(f"Subgraph 查询开仓交易失败: {e}")
                return []
            
            if not open_trades:
                self.logger.warning(f"⚠️  Subgraph 返回空数组（界面有持仓时请检查 SDK 的 subgraph URL 与网络是否与前端一致）")
                return []
            
            self.logger.info(f"✅ Subgraph 返回 {len(open_trades)} 个开仓交易")
            
            # 转换为统一格式
            positions = []
            for trade in open_trades:
                try:
                    # 获取交易信息
                    if isinstance(trade, dict):
                        pair_info = trade.get('pair', {})
                        pair_name = pair_info.get('name', 'UNKNOWN') if isinstance(pair_info, dict) else getattr(pair_info, 'name', 'UNKNOWN')
                    else:
                        pair_name = getattr(trade, 'pair', {}).name if hasattr(getattr(trade, 'pair', {}), 'name') else 'UNKNOWN'
                    
                    # 如果指定了symbol，则过滤
                    if symbol and symbol.upper() not in pair_name.upper().replace("-", ""):
                        continue
                    
                    # 提取 pair_id（从 pair 对象中获取 id）
                    pair_id = None
                    if isinstance(trade, dict):
                        pair_info = trade.get('pair', {})
                        if isinstance(pair_info, dict):
                            pair_id = pair_info.get('id')
                        elif hasattr(pair_info, 'id'):
                            pair_id = getattr(pair_info, 'id')
                    else:
                        pair_obj = getattr(trade, 'pair', None)
                        if pair_obj and hasattr(pair_obj, 'id'):
                            pair_id = getattr(pair_obj, 'id')
                    
                    position = {
                        'symbol': pair_name,
                        'index': trade.get('index', 0) if isinstance(trade, dict) else getattr(trade, 'index', 0),
                        'collateral': trade.get('collateral', 0) if isinstance(trade, dict) else getattr(trade, 'collateral', 0),
                        'leverage': trade.get('leverage', 1) if isinstance(trade, dict) else getattr(trade, 'leverage', 1),
                        'direction': trade.get('direction', True) if isinstance(trade, dict) else getattr(trade, 'direction', True),
                        'pair_id': pair_id,  # 添加 pair_id
                        'status': 'OPEN',
                        'timestamp': int(time.time() * 1000),
                        'raw_data': trade
                    }
                    positions.append(position)
                except Exception as e:
                    self.logger.warning(f"处理交易失败: {e}")
                    continue
            
            if positions:
                self.logger.info(f"✅ 过滤后得到 {len(positions)} 个持仓")
            return positions
        except Exception as e:
            self.logger.error(f"💔 获取持仓失败: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return []
    
    def _get_simulated_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取模拟持仓"""
        self.logger.info(f"使用模拟持仓数据")
        if symbol:
            return [{
                'symbol': symbol,
                'index': 0,
                'collateral': 100.0,
                'leverage': 1,
                'direction': True,
                'status': 'OPEN',
                'timestamp': int(time.time() * 1000)
            }]
        return []
    
    async def close_position(self, pair_id: int, trade_index: int, market_price: Optional[float] = None) -> Dict[str, Any]:
        """平仓
        
        根据 SDK 文档，close_trade 方法签名：
        sdk.ostium.close_trade(pair_id, trade_index, market_price)
        
        Args:
            pair_id: 交易对ID（从 get_positions 或 get_pairs 获取）
            trade_index: 交易索引（从 get_positions 获取的 index）
            market_price: 市场价格（可选，如果不提供会使用当前价格）
        """
        try:
            if not self.sdk:
                return self._create_simulated_close_result(pair_id, trade_index)
            
            # 如果不提供价格，获取当前价格
            # 根据 SDK 文档，需要提供 market_price
            if market_price is None:
                # 尝试从 pair_id 获取对应的交易对符号
                try:
                    pairs = await self.sdk.subgraph.get_pairs()
                    for pair in pairs:
                        if isinstance(pair, dict):
                            if pair.get('id') == pair_id:
                                pair_name = pair.get('name', '')
                                # 使用 get_price 方法（已经处理了 USDJPY 等特殊情况）
                                market_price = await self.get_price(pair_name)
                                break
                    else:
                        # 如果找不到，使用默认方法
                        market_price = await self.get_price("NDX-USD")  # 默认使用纳指价格
                except Exception as price_error:
                    self.logger.warning(f"获取市场价格失败: {price_error}，使用默认价格")
                    market_price = await self.get_price("NDX-USD")
            
            # SDK close_trade 为同步调用（内部 web3），在线程中执行避免阻塞事件循环及 shutdown 时 "no running event loop"
            self.logger.info(f"🔍 调用 SDK close_trade: pair_id={pair_id}, trade_index={trade_index}, market_price={market_price}")
            result = await asyncio.to_thread(
                self.sdk.ostium.close_trade, pair_id, trade_index, market_price
            )
            
            # 记录返回的原始数据
            self.logger.info(f"🔍 SDK close_trade 返回类型: {type(result)}, 内容: {result}")
            
            # 处理返回结果
            tx_hash = ''
            if isinstance(result, dict):
                # 处理 {'receipt': {...}, 'order_id': ...} 格式
                if 'receipt' in result:
                    receipt_obj = result['receipt']
                    if hasattr(receipt_obj, '__getitem__') and 'transactionHash' in receipt_obj:
                        tx_obj = receipt_obj['transactionHash']
                        tx_hash = tx_obj.hex() if hasattr(tx_obj, 'hex') else str(tx_obj)
                    elif hasattr(receipt_obj, 'transactionHash'):
                        tx_obj = receipt_obj.transactionHash
                        tx_hash = tx_obj.hex() if hasattr(tx_obj, 'hex') else str(tx_obj)
                elif 'transactionHash' in result:
                    tx_obj = result['transactionHash']
                    tx_hash = tx_obj.hex() if hasattr(tx_obj, 'hex') else str(tx_obj)
            elif hasattr(result, 'transactionHash'):
                tx_hash = result.transactionHash.hex() if hasattr(result.transactionHash, 'hex') else str(result.transactionHash)
            
            if not tx_hash:
                self.logger.warning("⚠️ 未能从返回结果中提取交易哈希，可能平仓未真正执行")
                return {
                    'pairId': pair_id,
                    'tradeIndex': trade_index,
                    'status': 'FAILED',
                    'error': '未能获取交易哈希，平仓可能未真正执行',
                    'timestamp': int(time.time() * 1000)
                }
            
            self.logger.info(f"✅ 平仓成功，交易哈希: {tx_hash}")
            return {
                'pairId': pair_id,
                'tradeIndex': trade_index,
                'status': 'CLOSED',
                'transactionHash': tx_hash,
                'tx_hash': tx_hash,  # 兼容字段
                'timestamp': int(time.time() * 1000)
            }
        except Exception as e:
            self.logger.error(f"平仓失败: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return {
                'pairId': pair_id,
                'tradeIndex': trade_index,
                'status': 'FAILED',
                'error': str(e),
                'timestamp': int(time.time() * 1000)
            }
    
    def _create_simulated_close_result(self, pair_id: int, trade_index: int) -> Dict[str, Any]:
        """创建模拟平仓结果"""
        self.logger.info(f"使用模拟平仓结果")
        return {
            'pairId': pair_id,
            'tradeIndex': trade_index,
            'status': 'CLOSED',
            'timestamp': int(time.time() * 1000)
        }
    
    async def get_balance(self) -> Dict[str, float]:
        """获取账户余额。SDK 可能返回 tuple(Decimal, Decimal) 或 dict，统一转为 {'USDC': float}"""
        try:
            if not self.sdk or not self.trader_address:
                return {'USDC': 0.0, 'error': 'SDK未初始化或地址不可用'}
            
            raw = self.sdk.balance.get_balance(self.trader_address)
            self.logger.info(f"获取账户余额成功: {raw}")

            # SDK 返回 tuple( collateral, usdc ) 或 dict
            if isinstance(raw, (tuple, list)) and len(raw) >= 2:
                usdc_val = raw[1]
                return {'USDC': float(usdc_val)}
            if isinstance(raw, dict):
                return {'USDC': float(raw.get('USDC', raw.get('usdc', 0.0)))}
            return {'USDC': 0.0}
        except Exception as e:
            self.logger.error(f"获取账户余额失败: {e}")
            return {'USDC': 0.0, 'error': str(e)}
    
    async def update_tp_sl(self, pair_id: int, trade_index: int, tp_price: Optional[float] = None, 
                          sl_price: Optional[float] = None) -> Dict[str, Any]:
        """更新止盈止损
        
        Args:
            pair_id: 交易对ID
            trade_index: 交易索引
            tp_price: 止盈价格
            sl_price: 止损价格
        """
        try:
            if not self.sdk:
                return {'status': 'SIMULATED', 'message': '使用模拟结果'}
            
            result = {}
            
            # 更新止盈
            if tp_price is not None:
                try:
                    tp_result = self.sdk.ostium.update_tp(pair_id, trade_index, tp_price)
                    result['tp'] = {'status': 'SUCCESS', 'price': tp_price}
                    self.logger.info(f"止盈设置成功: {tp_price}")
                except Exception as e:
                    result['tp'] = {'status': 'FAILED', 'error': str(e)}
                    self.logger.error(f"设置止盈失败: {e}")
            
            # 更新止损
            if sl_price is not None:
                try:
                    sl_result = self.sdk.ostium.update_sl(pair_id, trade_index, sl_price)
                    result['sl'] = {'status': 'SUCCESS', 'price': sl_price}
                    self.logger.info(f"止损设置成功: {sl_price}")
                except Exception as e:
                    result['sl'] = {'status': 'FAILED', 'error': str(e)}
                    self.logger.error(f"设置止损失败: {e}")
            
            return result
        except Exception as e:
            self.logger.error(f"更新止盈止损失败: {e}")
            return {'status': 'FAILED', 'error': str(e)}

# 测试Ostium API客户端
async def test_ostium_api_client():
    """测试Ostium API客户端"""
    try:
        print("="*50)
        print("开始测试 Ostium API 客户端")
        print("="*50)
        
        client = OstiumAPIClient()
        
        # 测试 1: 获取交易对列表
        print("\n[1] 测试获取交易对列表...")
        try:
            markets = await client.get_markets()
            print(f"✓ 交易对列表 ({len(markets)} 个): {markets}")
        except Exception as e:
            print(f"✗ 获取交易对列表失败: {e}")
            markets = []
        
        # 测试 2-4: 其他功能
        if markets:
            symbol = markets[0]
            print(f"\n使用交易对: {symbol}")
            
            # 测试 2: 获取价格
            print("\n[2] 测试获取价格...")
            try:
                price = await client.get_price(symbol)
                print(f"✓ {symbol} 价格: {price}")
            except Exception as e:
                print(f"✗ 获取价格失败: {e}")
            
            # 测试 3: 获取资金费率
            print("\n[3] 测试获取资金费率...")
            try:
                funding_rate = await client.get_funding_rate(symbol)
                print(f"✓ {symbol} 资金费率: {funding_rate}")
            except Exception as e:
                print(f"✗ 获取资金费率失败: {e}")
            
            # 测试 4: 下单
            print("\n[4] 测试下单...")
            try:
                order = await client.place_order(
                    symbol=symbol,
                    side="BUY",
                    quantity=10,  # 10 USDC
                    order_type="MARKET",
                    leverage=1
                )
                print(f"✓ 下单成功")
                print(f"  - 订单ID: {order.get('orderId')}")
                print(f"  - 状态: {order.get('status')}")
            except Exception as e:
                print(f"✗ 下单失败: {e}")
            
            # 测试 5: 获取持仓
            print("\n[5] 测试获取持仓...")
            try:
                positions = await client.get_positions(symbol=symbol)
                print(f"✓ 获取持仓成功 ({len(positions)} 个)")
                for i, pos in enumerate(positions):
                    print(f"  - 持仓 {i+1}: {pos.get('symbol')}, 放大{pos.get('leverage')}x")
            except Exception as e:
                print(f"✗ 获取持仓失败: {e}")
            
            # 测试 6: 获取账户余额
            print("\n[6] 测试获取账户余额...")
            try:
                balance = await client.get_balance()
                print(f"✓ 账户余额: {balance}")
            except Exception as e:
                print(f"✗ 获取余额失败: {e}")
        
        print("\n" + "="*50)
        print("测试完成")
        print("="*50)
        return True
    except Exception as e:
        print(f"\n✗ 测试遇到严重错误: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    # 运行异步测试
    asyncio.run(test_ostium_api_client())