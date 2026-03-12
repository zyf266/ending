import asyncio
import json
import os
import time
import uuid
import websockets
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable, Any
from decimal import Decimal
from dataclasses import dataclass, field
from enum import Enum
from asyncio import Lock

from ..core.data_manager import DataManager
from ..core.risk_manager import RiskManager
from ..strategy.base import BaseStrategy, Signal
from ..utils.logger import get_logger
from ..config.settings import config

logger = get_logger(__name__)


# 运行时枚举类（与数据库模型中的枚举不同，用于运行时状态管理）
class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"
    IOC = "ioc"
    FOK = "fok"


class OrderStatus(Enum):
    PENDING = "pending"
    OPEN = "open"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class PositionSide(Enum):
    LONG = "long"
    SHORT = "short"


# 运行时数据类（用于内存中的订单和持仓管理）
@dataclass
class Order:
    """运行时订单类"""
    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    price: Optional[Decimal] = None
    filled_quantity: Decimal = Decimal("0")
    status: OrderStatus = OrderStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    filled_at: Optional[datetime] = None
    commission: Decimal = Decimal("0")
    reason: str = ""
    signal: Optional[Signal] = None  # 【修复】保存策略信号，用于同步止损止盈信息

    def to_dict(self) -> Dict:
        return {
            "orderId": self.order_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "type": self.order_type.value,
            "quantity": str(self.quantity),
            "price": str(self.price) if self.price else None,
            "filledQuantity": str(self.filled_quantity),
            "status": self.status.value,
            "createdAt": self.created_at.isoformat(),
            "updatedAt": self.updated_at.isoformat(),
            "commission": str(self.commission)
        }


@dataclass
class Position:
    """运行时持仓类"""
    symbol: str
    side: PositionSide
    quantity: Decimal
    entry_price: Decimal
    mark_price: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": str(self.quantity),
            "entryPrice": str(self.entry_price),
            "markPrice": str(self.mark_price),
            "unrealizedPnl": str(self.unrealized_pnl),
            "realizedPnl": str(self.realized_pnl)
        }


@dataclass
class AccountBalance:
    """运行时账户余额类"""
    asset: str
    available: Decimal
    locked: Decimal
    total: Decimal

    def to_dict(self) -> Dict:
        return {
            "asset": self.asset,
            "available": str(self.available),
            "locked": str(self.locked),
            "total": str(self.total)
        }


class WebSocketClient:
    """简化的WebSocket客户端（用于实时数据订阅）"""
    def __init__(self, base_url: str = "wss://ws.backpack.exchange"):
        self.base_url = base_url
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.subscriptions: Dict[str, set] = {}
        self.reconnect_delay = 1
        self.max_reconnect_delay = 60
        self.running = False
        self._lock = Lock()

    def _is_connected(self) -> bool:
        """检查WebSocket是否已连接"""
        try:
            if self.ws is None:
                return False
            
            if hasattr(self.ws, 'state'):
                return self.ws.state == 1
            elif hasattr(self.ws, 'open'):
                return self.ws.open
            else:
                return True
        except Exception as e:
            logger.error(f"连接状态检查异常: {e}")
            return False

    async def connect(self, max_retries: int = 3):
        """建立WebSocket连接
        
        Args:
            max_retries: 最大重试次数
        """
        if self._is_connected():
            logger.info("WebSocket已连接，跳过连接步骤")
            return

        # --- 【新增】自适应代理支持 ---
        import os
        proxy_url = os.environ.get('HTTPS_PROXY') or os.environ.get('http_proxy') or os.environ.get('HTTP_PROXY')
        
        # 【关键修复】检查websockets库是否支持proxy参数
        import inspect
        connect_signature = inspect.signature(websockets.connect)
        supports_proxy = 'proxy' in connect_signature.parameters
        
        if proxy_url and not supports_proxy:
            logger.warning(f"⚠️ 检测到代理设置({proxy_url})，但websockets库不支持proxy参数，已忽略")
            logger.warning(f"💡 如需使用代理，请升级websockets: pip install --upgrade websockets")
            proxy_url = None
        # ---------------------------

        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"正在连接WebSocket服务器: {self.base_url} (第{attempt}/{max_retries}次尝试)")
                
                # 【关键修复】根据是否支持proxy参数来构造连接
                connect_kwargs = {
                    'ping_interval': 30,
                    'ping_timeout': 30,
                    'open_timeout': 20
                }
                
                if proxy_url and supports_proxy:
                    connect_kwargs['proxy'] = proxy_url
                    logger.info(f"🌐 使用代理: {proxy_url}")
                
                self.ws = await asyncio.wait_for(
                    websockets.connect(self.base_url, **connect_kwargs),
                    timeout=30
                )
                logger.info("✅ WebSocket连接已建立")
                
                # 重连时需要重新订阅，先保存旧订阅记录
                old_subscriptions = self.subscriptions.copy()
                # 清空订阅状态，确保重新订阅
                self.subscriptions = {}
                # 恢复订阅
                for channel, symbols in old_subscriptions.items():
                    for symbol in symbols:
                        await self.subscribe(channel, symbol)
                self.reconnect_delay = 1
                return  # 【成功】连接成功，退出重试循环
                
            except asyncio.TimeoutError:
                last_error = "WebSocket连接超时"
                logger.error(f"❌ 连接超时 (第{attempt}/{max_retries}次尝试)")
                self.ws = None
                
                if attempt < max_retries:
                    wait_time = 2 ** attempt  # 指数退避：2s, 4s, 8s
                    logger.info(f"⏱️ {wait_time}秒后重试...")
                    await asyncio.sleep(wait_time)
                    
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                logger.error(f"❌ WebSocket连接失败: {last_error} (第{attempt}/{max_retries}次尝试)")
                logger.exception("WebSocket连接异常详情:")
                self.ws = None
                
                if attempt < max_retries:
                    wait_time = 2 ** attempt
                    logger.info(f"⏱️ {wait_time}秒后重试...")
                    await asyncio.sleep(wait_time)
        
        # 【全部失败】所有重试都失败
        error_msg = f"WebSocket连接失败，已重试{max_retries}次: {last_error}"
        logger.error(f"❌ {error_msg}")
        raise ConnectionError(error_msg)

    async def _resubscribe(self):
        """重新订阅所有频道（已废弃，由connect方法内部处理）"""
        pass

    async def subscribe(self, channel: str, symbol: str = None):
        """订阅频道"""
        if not symbol:
            logger.error("订阅必须指定交易对symbol")
            return
        
        # 格式化频道名称
        if channel.startswith("kline:"):
            formatted_channel = channel.replace(":", ".")
        else:
            formatted_channel = channel.replace(":", "_")
        
        # 标准化交易对格式
        if "_" in symbol:
            standard_symbol = symbol
        else:
            if len(symbol) == 6:
                standard_symbol = f"{symbol[:3]}_{symbol[3:]}"
            elif len(symbol) == 8:
                standard_symbol = f"{symbol[:3]}_{symbol[3:]}"
            else:
                standard_symbol = symbol
        
        subscribe_key = f"{formatted_channel}.{standard_symbol}"
        
        subscribe_msg = {
            "id": str(uuid.uuid4()),
            "method": "SUBSCRIBE",
            "params": [subscribe_key]
        }
        
        msg_str = json.dumps(subscribe_msg, separators=(",", ":"), ensure_ascii=True)
        logger.info(f"发送订阅消息: {msg_str}")

        if self._is_connected():
            # 移除重复订阅检查，确保重连后能正常订阅
            await self.ws.send(msg_str)
            if channel not in self.subscriptions:
                self.subscriptions[channel] = set()
            self.subscriptions[channel].add(standard_symbol)
            logger.info(f"✅ 订阅成功: {subscribe_key}")
        else:
            logger.error("WebSocket未连接，订阅失败")

    async def unsubscribe(self, channel: str, symbol: str = None):
        """取消订阅"""
        if not symbol:
            logger.error("取消订阅必须指定交易对symbol")
            return
        
        if channel.startswith("kline:"):
            formatted_channel = channel.replace(":", ".")
        else:
            formatted_channel = channel.replace(":", "_")
        
        if "_" in symbol:
            standard_symbol = symbol
        else:
            if len(symbol) == 6:
                standard_symbol = f"{symbol[:3]}_{symbol[3:]}"
            elif len(symbol) == 8:
                standard_symbol = f"{symbol[:3]}_{symbol[3:]}"
            else:
                standard_symbol = symbol
        
        unsubscribe_key = f"{formatted_channel}.{standard_symbol}"
        
        message = {
            "id": str(uuid.uuid4()),
            "method": "UNSUBSCRIBE",
            "params": [unsubscribe_key]
        }
        
        msg_str = json.dumps(message, separators=(",", ":"), ensure_ascii=True)

        if self._is_connected():
            await self.ws.send(msg_str)
            if channel in self.subscriptions:
                self.subscriptions[channel].discard(standard_symbol)
            logger.info(f"已取消订阅频道: {unsubscribe_key}")

    async def receive(self) -> Dict:
        """接收消息"""
        if not self._is_connected():
            raise ConnectionError("WebSocket未连接")

        try:
            message = await self.ws.recv()
            return json.loads(message)
        except websockets.exceptions.ConnectionClosed as e:
            # 【修复】WebSocket连接已关闭，清空 ws 对象以触发重连
            logger.warning(f"⚠️ WebSocket连接已关闭: {e}")
            self.ws = None
            raise ConnectionError(f"WebSocket连接已关闭: {e}")
        except Exception as e:
            logger.error(f"接收消息失败: {e}")
            raise

    async def close(self):
        """关闭连接"""
        if self.ws:
            await self.ws.close()
            self.ws = None
            logger.info("WebSocket连接已关闭")


class LiveTradingEngine:
    """实盘交易引擎

    行情数据统一从 Backpack WebSocket 订阅；
    下单相关通过 ExchangeClient 抽象，方便后续接入其他交易所。
    """
    def __init__(self, config, exchange_client: Optional["ExchangeClient"] = None):
        from ..core.api_client import BackpackAPIClient, ExchangeClient  # 避免循环导入

        self.config = config
        # 使用可注入的交易所客户端；默认仍然是 Backpack
        self.exchange_client: ExchangeClient = exchange_client or BackpackAPIClient(
            access_key=config.backpack.ACCESS_KEY,
            refresh_key=config.backpack.REFRESH_KEY,
        )
        # WebSocket 仍然使用 Backpack 的地址获取实时K线/行情
        self.ws_client = WebSocketClient(config.backpack.WS_BASE_URL)
        # DataManager 只依赖行情与K线，因此固定使用 Backpack 的 REST/WebSocket
        self.data_manager = DataManager(api_client=self.exchange_client, mode="live")
        # 初始化数据库管理器
        from ..database.models import DatabaseManager
        self.db_manager = DatabaseManager()
        self.risk_manager = RiskManager(config, db_manager=self.db_manager)


        self.strategies: Dict[str, BaseStrategy] = {}
        self.orders: Dict[str, Order] = {}
        self.positions: Dict[str, Position] = {}
        self.balances: Dict[str, AccountBalance] = {}

        self.order_lock = Lock()
        self.position_lock = Lock()
        self.balance_lock = Lock()

        self.running = False
        self.trading_symbols: List[str] = []

        self.order_callbacks: List[Callable] = []
        self.position_callbacks: List[Callable] = []
        self.trade_callbacks: List[Callable] = []

        self.order_id_prefix = "live_"
        self._order_counter = 0
        
        # 【修复】添加余额缓存，减少API调用频率
        self._balance_cache = None
        self._balance_cache_time = 0
        self._balance_cache_ttl = 600  # 缓存10分钟（600秒），避免频繁调用API
        
        # 【新增】Symbol映射表: Backpack格式 -> 用户输入格式
        # 用于将WebSocket收到的symbol映射到策略注册的symbol
        self.symbol_mapping: Dict[str, str] = {}  # {"ETH_USDT_PERP": "ETH-USDT-SWAP"}

        # 【仪表盘余额】子进程实例ID，用于将余额写入 live_balances.json 供 API 读取
        self._instance_id = os.environ.get("LIVE_INSTANCE_ID", "")

    def generate_order_id(self) -> str:
        """生成唯一订单ID"""
        self._order_counter += 1
        return f"{self.order_id_prefix}{self._order_counter}_{int(time.time() * 1000)}"
    
    async def get_balance_cached(self) -> List[Dict]:
        """【修复】获取余额（带缓存，减少API调用）

        注意：这里通过抽象的 exchange_client 获取余额，
        因此无论使用哪家交易所实现，只要实现了 ExchangeClient 接口即可复用。
        """
        current_time = time.time()
        
        # 如果缓存有效，直接返回缓存数据
        if self._balance_cache is not None and (current_time - self._balance_cache_time) < self._balance_cache_ttl:
            logger.debug(f"💾 使用余额缓存，剩余TTL: {self._balance_cache_ttl - (current_time - self._balance_cache_time):.1f}秒")
            return self._balance_cache
        
        # 缓存过期，重新获取
        try:
            logger.debug(f"📞 调用交易所API获取余额: {self.exchange_client.__class__.__name__}")
            balance = await self.exchange_client.get_balance()
            logger.debug(f"📥 API返回原始余额数据: {balance}")
            
            self._balance_cache = balance
            self._balance_cache_time = current_time
            logger.debug(f"🔄 更新余额缓存: {balance}")
            return balance
        except Exception as e:
            logger.error(f"❌ 获取余额失败: {e}")
            import traceback
            traceback.print_exc()
            # 如果有旧缓存，即使过期也返回（避免程序崩溃）
            if self._balance_cache is not None:
                logger.warning("⚠️ API调用失败，使用过期缓存")
                return self._balance_cache
            # 返回空列表而不是抛出异常
            logger.warning("⚠️ 无缓存可用，返回空余额")
            return []

    async def initialize(self):
        """初始化交易引擎"""
        logger.info("初始化实盘交易引擎...")
        
        # 【新增】显示平台信息
        exchange_name = self.exchange_client.__class__.__name__.replace('APIClient', '')
        logger.info("="*80)
        logger.info("🚀 [平台配置] 跨平台协同模式")
        logger.info(f"📊 [数据源] K线数据来自: Backpack (WebSocket)")
        logger.info(f"💰 [下单平台] 订单执行于: {exchange_name}")
        logger.info(f"🔍 [余额查询] 使用: {exchange_name} API")
        logger.info("="*80)

        try:
            logger.info("正在获取API会话...")
            # 通过抽象的交易所客户端初始化会话（具体实现内部自行处理）
            if hasattr(self.exchange_client, "get_session"):
                await self.exchange_client.get_session()
            logger.info("API会话获取成功")
            
            # 验证交易对有效性（在Backpack上验证，因为K线数据来自Backpack）
            if self.trading_symbols:
                logger.info("正在验证交易对有效性（在Backpack上验证）...")
                
                # 【修复】使用Backpack API验证交易对，因为K线数据来自Backpack
                from ..core.api_client import BackpackAPIClient
                backpack_client = BackpackAPIClient()
                
                try:
                    markets = await backpack_client.get_markets()
                    valid_symbols = set(markets.keys())
                    logger.info(f"Backpack支持的交易对数量: {len(valid_symbols)}")

                    # 【新增】对于每个用户输入的交易对，转换为Backpack格式以获取K线
                    filtered_symbols = []
                    for user_symbol in self.trading_symbols:
                        # 转换为Backpack格式（用于获取K线数据）
                        backpack_symbol = self._convert_to_backpack_format(user_symbol)
                        
                        # 验证Backpack格式的交易对是否存在
                        if backpack_symbol in valid_symbols:
                            filtered_symbols.append(backpack_symbol)
                            if backpack_symbol != user_symbol:
                                logger.info(f"✅ 交易对映射: {user_symbol} -> {backpack_symbol} (用于获取K线)")
                            else:
                                logger.info(f"✅ 交易对有效: {user_symbol}")
                        else:
                            logger.warning(f"⚠️ Backpack不支持交易对: {backpack_symbol} (由{user_symbol}转换)")
                    
                    if not filtered_symbols:
                        raise Exception("无有效交易对，请检查订阅的交易对格式")
                    
                    # 【关键】更新trading_symbols为Backpack格式（用于获取K线）
                    # 但保留原始映射关系，以便下单时转换回用户格式
                    self.trading_symbols = filtered_symbols
                    logger.info(f"已转换为Backpack格式的交易对: {self.trading_symbols}")
                    
                finally:
                    # 关闭临时创建的Backpack客户端
                    await backpack_client.close_session()
            
            logger.info("正在连接WebSocket...")
            await self.ws_client.connect()
            logger.info("WebSocket连接成功")

            logger.info("正在加载账户余额...")
            await self.load_balances()
            logger.info("账户余额加载成功")
            pv = float(self.get_portfolio_value())
            logger.info(f"💾 组合价值: {pv:.2f} USD, instance_id={self._instance_id}")
            self._write_balance_to_file(pv)  # 立即写入供仪表盘显示
            
            logger.info("正在加载持仓...")
            await self.load_positions()
            logger.info("持仓加载成功")
            
            logger.info("正在加载未完成订单...")
            await self.load_open_orders()
            logger.info("未完成订单加载成功")

            # 【新增】预加载历史K线数据，确保策略启动时有足够的数据
            logger.info("正在预加载历史K线数据...")
            await self.preload_historical_data()
            logger.info("历史K线数据预加载成功")

            logger.info(f"账户余额: {self.get_account_summary()}")
            logger.info(f"当前持仓: {self.get_positions_summary()}")

        except Exception as e:
            logger.error(f"初始化失败: {e}")
            logger.exception("初始化异常详情:")
            raise

    async def start(self):
        """启动交易引擎"""
        if self.running:
            logger.warning("交易引擎已在运行中")
            return

        exchange_name = self.exchange_client.__class__.__name__.replace('APIClient', '')
        logger.info("="*80)
        logger.info("🚀 启动实盘交易引擎...")
        logger.info(f"📊 [Backpack] 负责: K线数据推送 (WebSocket)")
        logger.info(f"💰 [{exchange_name}] 负责: 订单执行 + 余额查询 + 持仓管理")
        logger.info("="*80)
        self.running = True

        if not self.ws_client._is_connected():
            await self.ws_client.connect()
        
        # 订阅K线频道（日内交易使用1分钟周期，AI策略分析）
        for symbol in self.trading_symbols:
            logger.info(f"📡 [Backpack] 订阅{symbol}的K线数据频道（1分钟）...")
            await self.ws_client.subscribe("kline:1m", symbol)

        tasks = [
            self._order_status_loop(),
            self._price_monitor_loop(),
            self._position_monitor_loop(),  # 【新增】止盈止损监控
            self._snapshot_loop(),         # 【新增】资产快照监控
            self._heartbeat_loop()
        ]


        await asyncio.gather(*tasks)

    async def stop(self):
        """停止交易引擎"""
        logger.info("停止实盘交易引擎...")
        self.running = False

        cancel_tasks = []
        for symbol in self.trading_symbols:
            cancel_tasks.append(self.cancel_all_orders(symbol))

        if cancel_tasks:
            await asyncio.gather(*cancel_tasks, return_exceptions=True)

        await self.ws_client.close()
        # 通过抽象交易所客户端关闭会话（如果支持）
        if hasattr(self.exchange_client, "close_session"):
            await self.exchange_client.close_session()

        logger.info("实盘交易引擎已停止")

    def register_strategy(self, symbol: str, strategy: BaseStrategy):
        """注册策略
        
        Args:
            symbol: 用户输入的交易对格式
                    - 如果是Backpack格式（如ETH_USDC_PERP），直接使用
                    - 如果是Deepcoin格式（如ETH-USDT-SWAP），需要映射到Backpack格式
        """
        self.strategies[symbol] = strategy
        if symbol not in self.trading_symbols:
            self.trading_symbols.append(symbol)
        logger.info(f"已注册策略: {symbol} - {strategy.__class__.__name__}")
        
        # 【新增】自动建立symbol映射关系
        # 检查是否需要映射（例如：Deepcoin格式 -> Backpack格式）
        backpack_symbol = self._convert_to_backpack_format(symbol)
        if backpack_symbol != symbol:
            self.symbol_mapping[backpack_symbol] = symbol
            logger.info(f"📌 建立symbol映射: {backpack_symbol} (Backpack) -> {symbol} (用户/Deepcoin)")
    
    def _convert_from_backpack_format(self, backpack_symbol: str) -> str:
        """将Backpack格式转换回用户格式（用于下单）
        
        如果symbol_mapping中有映射关系，返回用户格式；否则返回原symbol
        
        Examples:
            ETH_USDC_PERP (Backpack) -> ETH-USDT-SWAP (Deepcoin, 如果有映射)
            ETH_USDC_PERP (Backpack) -> ETH_USDC_PERP (如果无映射，直接使用)
        """
        # 查找映射表
        return self.symbol_mapping.get(backpack_symbol, backpack_symbol)
    
    def _extract_base_currency(self, symbol: str) -> str:
        """提取交易对的基础币种（用于缓存键）
        
        Examples:
            ETH-USDT-SWAP -> ETH
            ETH_USDC_PERP -> ETH
            BTC-USDT-SWAP -> BTC
            SOL_USDC_PERP -> SOL
        """
        # 移除常见后缀
        clean = symbol.replace("-SWAP", "").replace("-PERP", "").replace("_PERP", "")
        
        # 分割并取第一部分
        if "-" in clean:
            return clean.split("-")[0]  # ETH-USDT -> ETH
        elif "_" in clean:
            return clean.split("_")[0]  # ETH_USDC -> ETH
        else:
            return clean  # 已经是单个币种
    
    def _convert_to_backpack_format(self, symbol: str) -> str:
        """将交易对转换为Backpack格式（用于获取K线数据）
        
        Examples:
            ETH-USDT-SWAP (Deepcoin) -> ETH_USDC_PERP (Backpack)
            BTC-USDT-SWAP (Deepcoin) -> BTC_USDC_PERP (Backpack)
            ETH_USDC_PERP (Backpack) -> ETH_USDC_PERP (不变)
        """
        # 如果已经是Backpack格式，直接返回
        if "_PERP" in symbol or "_USDC" in symbol:
            return symbol
        
        # 解析Deepcoin格式: ETH-USDT-SWAP
        if "-SWAP" in symbol or "-PERP" in symbol:
            # 移除后缀
            clean = symbol.replace("-SWAP", "").replace("-PERP", "")
            # 分割币种: ETH-USDT -> [ETH, USDT]
            parts = clean.split("-")
            if len(parts) >= 2:
                base = parts[0]  # ETH
                # Backpack使用USDC，将USDT替换为USDC
                quote = "USDC"  # 强制使用USDC（Backpack的计价币）
                return f"{base}_{quote}_PERP"
        
        # 其他格式尝试标准化
        return self._normalize_to_backpack_format(symbol)
    
    def _normalize_to_backpack_format(self, symbol: str) -> str:
        """将交易对格式标准化为Backpack格式
        
        Examples:
            ETH-USDT-SWAP -> ETH_USDT_PERP
            ETH/USDT -> ETH_USDT_PERP
            BTC-USDC-SWAP -> BTC_USDC_PERP
        """
        # 移除所有分隔符,提取基础币种和计价币种
        clean = symbol.replace("-", "").replace("_", "").replace("/", "").upper()
        
        # 移除SWAP/PERP后缀
        clean = clean.replace("SWAP", "").replace("PERP", "")
        
        # 识别常见的计价币种
        quote_currencies = ["USDT", "USDC", "USD", "BTC", "ETH"]
        base = None
        quote = None
        
        for q in quote_currencies:
            if clean.endswith(q):
                quote = q
                base = clean[:-len(q)]
                break
        
        if not base or not quote:
            # 无法识别,返回原symbol
            return symbol
        
        # 统一转为Backpack格式: BASE_QUOTE_PERP
        return f"{base}_{quote}_PERP"

    def on_order(self, callback: Callable):
        """注册订单回调"""
        self.order_callbacks.append(callback)

    def on_position(self, callback: Callable):
        """注册仓位回调"""
        self.position_callbacks.append(callback)

    def on_trade(self, callback: Callable):
        """注册成交回调"""
        self.trade_callbacks.append(callback)

    async def _notify_order_update(self, order: Order):
        """通知订单更新"""
        for callback in self.order_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(order)
                else:
                    callback(order)
            except Exception as e:
                logger.error(f"订单回调执行失败: {e}")

    async def _notify_position_update(self, position: Position):
        """通知仓位更新"""
        for callback in self.position_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(position)
                else:
                    callback(position)
            except Exception as e:
                logger.error(f"仓位回调执行失败: {e}")

    async def _notify_trade(self, order: Order, trade_type: str):
        """通知成交"""
        for callback in self.trade_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(order, trade_type)
                else:
                    callback(order, trade_type)
            except Exception as e:
                logger.error(f"成交回调执行失败: {e}")

    async def load_balances(self):
        """加载账户余额"""
        try:
            # 【修复】使用缓存获取余额
            balances = await self.get_balance_cached()
            logger.debug(f"获取到的余额原始数据: {balances}")

            async with self.balance_lock:
                self.balances.clear()
                # 兼容两种格式：List[Dict]（Deepcoin 等）和 Dict[str, float]（Backpack get_balance）
                if isinstance(balances, dict):
                    for asset, available in balances.items():
                        if not asset:
                            continue
                        av = float(available) if isinstance(available, (int, float)) else float(available or 0)
                        self.balances[asset] = AccountBalance(
                            asset=asset,
                            available=Decimal(str(av)),
                            locked=Decimal("0"),
                            total=Decimal(str(av))
                        )
                        logger.debug(f"加载余额: {asset} - 可用={av}, 总计={av}")
                else:
                    for bal in balances or []:
                        if not isinstance(bal, dict):
                            continue
                        asset = bal.get("asset") or bal.get("currency") or bal.get("symbol", "")
                        if not asset:
                            continue
                        available = bal.get("available") or bal.get("availableBalance") or bal.get("free") or 0
                        locked = bal.get("locked") or bal.get("lockedBalance") or 0
                        if isinstance(available, str):
                            try:
                                available = float(available)
                            except Exception:
                                available = 0
                        if isinstance(locked, str):
                            try:
                                locked = float(locked)
                            except Exception:
                                locked = 0
                        self.balances[asset] = AccountBalance(
                            asset=asset,
                            available=Decimal(str(available)),
                            locked=Decimal(str(locked)),
                            total=Decimal(str(available)) + Decimal(str(locked))
                        )
                        logger.debug(f"加载余额: {asset} - 可用={available}, 锁定={locked}, 总计={available + locked}")
            logger.info(f"已加载余额, 共 {len(self.balances)} 种资产")
        except Exception as e:
            logger.error(f"加载余额失败: {e}", exc_info=True)

    async def load_positions(self):
        """加载持仓"""
        try:
            positions = await self.exchange_client.get_positions()
            logger.debug(f"📊 获取到的持仓原始数据: {positions}")
            logger.debug(f"📊 数据类型: {type(positions)}")
            
            async with self.position_lock:
                self.positions.clear()
                
                # 【修复】支持列表和字典两种格式
                if isinstance(positions, list):
                    # 列表格式：[{symbol, side, quantity, ...}, ...]
                    logger.info(f"📊 持仓数据是列表格式，共 {len(positions)} 条")
                    for pos in positions:
                        if not isinstance(pos, dict):
                            continue
                        symbol = pos.get('symbol', '')
                        if not symbol:
                            continue
                        
                        # 【修复】Backpack API 字段映射
                        # netQuantity: 净持仓（负数=空头，正数=多头）
                        # netExposureQuantity: 绝对数量
                        net_qty = float(pos.get('netQuantity', 0))
                        abs_qty = float(pos.get('netExposureQuantity', 0))
                        
                        # 跳过空持仓
                        if abs_qty == 0:
                            continue
                        
                        # 根据 netQuantity 的正负判断方向
                        side = PositionSide.SHORT if net_qty < 0 else PositionSide.LONG
                        
                        self.positions[symbol] = Position(
                            symbol=symbol,
                            side=side,
                            quantity=Decimal(str(abs_qty)),  # 使用绝对数量
                            entry_price=Decimal(str(pos.get('entryPrice', 0))),
                            mark_price=Decimal(str(pos.get('markPrice', 0))),
                            unrealized_pnl=Decimal(str(pos.get('pnlUnrealized', 0))),  # 注意字段名
                            realized_pnl=Decimal(str(pos.get('pnlRealized', 0)))  # 注意字段名
                        )
                        logger.info(f"✅ 加载持仓: {symbol}, {side.value}, 净数量: {net_qty}, 绝对数量: {abs_qty}, 入场价: {pos.get('entryPrice', 0)}")
                        
                elif isinstance(positions, dict):
                    # 字典格式：{symbol: {side, quantity, ...}, ...}
                    logger.info(f"📊 持仓数据是字典格式，共 {len(positions)} 条")
                    for symbol, pos in positions.items():
                        raw_side = pos.get('side', 'long')
                        side = PositionSide.LONG if str(raw_side).lower() == 'long' else PositionSide.SHORT
                        
                        self.positions[symbol] = Position(
                            symbol=symbol,
                            side=side,
                            quantity=Decimal(str(pos.get('quantity', 0))),
                            entry_price=Decimal(str(pos.get('entryPrice', 0) or pos.get('avgEntryPrice', 0))),
                            mark_price=Decimal(str(pos.get('markPrice', 0))),
                            unrealized_pnl=Decimal(str(pos.get('unrealizedPnl', 0))),
                            realized_pnl=Decimal(str(pos.get('realizedPnl', 0)))
                        )
                        logger.info(f"✅ 加载持仓: {symbol}, {side.value}, 数量: {pos.get('quantity', 0)}, 入场价: {pos.get('entryPrice', 0)}")
                        
            logger.info(f"已加载持仓, 共 {len(self.positions)} 个")
        except Exception as e:
            if "404" in str(e) or "not found" in str(e).lower():
                logger.info("当前无持仓")
                self.positions = {}
            else:
                logger.error(f"加载持仓失败: {e}", exc_info=True)

    async def load_open_orders(self):
        """加载未完成订单"""
        try:
            orders = await self.exchange_client.get_open_orders()
            async with self.order_lock:
                self.orders.clear()
                for order_data in orders:
                    order = self._parse_order_response(order_data)
                    self.orders[order.order_id] = order
            logger.info(f"已加载未完成订单, 共 {len(self.orders)} 个")
        except Exception as e:
            logger.error(f"加载未完成订单失败: {e}")

    def _parse_order_response(self, data: Dict) -> Order:
        """解析订单响应"""
        # Backpack API返回的side是'Bid'/'Ask'，需要转换为'buy'/'sell'
        raw_side = data.get("side", "Bid")
        if raw_side == "Bid":
            side = OrderSide.BUY
        elif raw_side == "Ask":
            side = OrderSide.SELL
        else:
            side = OrderSide(raw_side)  # 如果已经是'buy'/'sell'则直接使用
        
        # Backpack API返回的orderType是'Limit'/'Market'，需要转换为小写
        raw_type = data.get("orderType", "Limit")
        order_type = OrderType(raw_type.lower())
        
        # Backpack API返回的status是'New'/'Filled'/'Cancelled'，需要转换
        raw_status = data.get("status", "New")
        status_mapping = {
            "New": OrderStatus.OPEN,
            "Filled": OrderStatus.FILLED,
            "Cancelled": OrderStatus.CANCELLED,
            "PartiallyFilled": OrderStatus.OPEN,
            "Rejected": OrderStatus.REJECTED
        }
        status = status_mapping.get(raw_status, OrderStatus.PENDING)
        
        # Backpack API使用'id'而不是'orderId'
        order_id = str(data.get("id", data.get("orderId", "")))
        
        # Backpack API使用'executedQuantity'而不是'filledQuantity'
        filled_qty = data.get("executedQuantity", data.get("filledQuantity", "0"))
        
        # Backpack API使用'createdAt'（毫秒级时间戳）
        created_time = data.get("createdAt", data.get("createdTime", 0))
        
        return Order(
            order_id=order_id,
            symbol=data.get("symbol", ""),
            side=side,
            order_type=order_type,
            quantity=Decimal(str(data.get("quantity", "0"))),
            price=Decimal(str(data.get("price", "0"))) if data.get("price") else None,
            filled_quantity=Decimal(str(filled_qty)),
            status=status,
            created_at=datetime.fromtimestamp(created_time / 1000),
            updated_at=datetime.now(),
            commission=Decimal(str(data.get("commission", "0")))
        )

    async def place_order(self, symbol: str, side: OrderSide, order_type: OrderType,
                         quantity: Decimal, price: Decimal = None,
                         strategy_signal: Signal = None, is_close: bool = False,
                         reduce_only: bool = False) -> Optional[Order]:
        """下单
        
        Args:
            symbol: 交易对（Backpack格式，如ETH_USDC_PERP）
            is_close: 是否为平仓订单，平仓订单跳过风控检查
            reduce_only: 是否为只减少持仓订单，用于平仓
        """
        async with self.order_lock:
            order_id = self.generate_order_id()
        
        # 【新增】将Backpack格式转换为实际下单交易所的格式
        # symbol参数是Backpack格式（用于K线获取），需要转换为下单交易所的格式
        order_symbol = self._convert_from_backpack_format(symbol)
        if order_symbol != symbol:
            logger.info(f"📌 下单时转换交易对: {symbol} (Backpack) -> {order_symbol} (下单平台)")

        try:
            # 格式化数量：Backpack要求4位小数
            quantity_float = float(quantity)
            quantity_rounded = round(quantity_float, 4)
            
            # 【修复】平仓订单跳过风控检查
            if not is_close:
                # 【修复】市价单没有价格，优先使用信号中的价格，其次从市场获取
                check_price = price
                if not check_price or check_price == Decimal("0"):
                    # 【关键修复】优先使用strategy_signal中的价格（更准确）
                    if strategy_signal and hasattr(strategy_signal, 'price') and strategy_signal.price:
                        check_price = Decimal(str(strategy_signal.price))
                        logger.info(f"💰 市价单使用信号中的价格进行风控检查: {check_price} ({symbol})")
                    else:
                        # 如果信号中没有价格，才从市场获取
                        try:
                            # 【关键修复】使用转换后的order_symbol获取ticker
                            ticker = await self.exchange_client.get_ticker(order_symbol)
                            check_price = Decimal(str(ticker.get('lastPrice', 0)))
                            logger.info(f"💰 市价单使用市场价格进行风控检查: {check_price} ({order_symbol})")
                        except Exception as e:
                            logger.error(f"获取市场价格失败: {e}")
                            return None
                
                # 【修复】获取账户资金作为风险检查的参数，使用缓存减少API调用
                account_capital = 0.0
                try:
                    balance = await self.get_balance_cached()
                    # 兼容 Dict[str, float] 和 List[Dict] 格式，累加 USDC/USDT/USD
                    if isinstance(balance, dict):
                        for asset, amt in balance.items():
                            if asset and asset.upper() in ['USDC', 'USDT', 'USD']:
                                account_capital += float(amt or 0)
                                logger.debug(f"找到 {asset} 余额: {float(amt or 0):.2f}")
                    else:
                        for b in balance or []:
                            if not isinstance(b, dict):
                                continue
                            asset = b.get('asset') or b.get('currency') or b.get('symbol', '')
                            if asset and asset.upper() in ['USDC', 'USDT', 'USD']:
                                available = b.get('available') or b.get('availableBalance') or b.get('free') or b.get('limit') or 0
                                if isinstance(available, str):
                                    try:
                                        available = float(available)
                                    except Exception:
                                        available = 0
                                account_capital += float(available)
                                logger.debug(f"找到 {asset} 余额: {float(available):.2f}")
                    logger.info(f"💰 风控检查使用的总账户余额 (USDC+USDT+USD): {account_capital:.2f}")
                except Exception as e:
                    logger.error(f"获取账户余额失败: {e}")

                risk_result = self.risk_manager.check_order_risk(
                    symbol=symbol,
                    side=side.value,
                    quantity=float(quantity),
                    price=float(check_price),  # 使用check_price而不是price
                    account_capital=account_capital
                )

                if not risk_result.approved:
                    logger.warning(f"订单未通过风控检查: {'; '.join(risk_result.violations)}")
                    return None
            else:
                logger.info(f"✅ 平仓订单跳过风控检查: {symbol}")

            response = await self.exchange_client.execute_order(
                symbol=order_symbol,  # 使用转换后的交易对（下单平台的格式）
                side=side.value,
                order_type=order_type.value.capitalize(),
                quantity=quantity_rounded,
                price=float(price) if price else None,
                reduce_only=reduce_only  # 【关键】传递 reduceOnly 参数
            )

            # 检查响应是否有效
            if not response:
                logger.error(f"订单响应为空")
                return None
            
            # 如果响应是列表，取第一个元素
            if isinstance(response, list):
                if not response:
                    logger.error(f"订单响应列表为空")
                    return None
                response_data = response[0]
            else:
                response_data = response
            
            # 检查是否有错误信息
            if isinstance(response_data, dict) and response_data.get('code') and response_data.get('message'):
                logger.error(f"API返回错误: {response_data.get('message')}")
                return None
            
            order = self._parse_order_response(response_data)
            order.status = OrderStatus.OPEN
            order.signal = strategy_signal  # 【修复】保存策略信号

            async with self.order_lock:
                self.orders[order.order_id] = order

            logger.info(f"订单已提交: {order.to_dict()}")

            # 【问题2修复】保存订单到数据库
            try:
                db_order_dict = {
                    'order_id': order.order_id,
                    'client_id': None,
                    'symbol': order.symbol,
                    'side': order.side.value,
                    'type': order.order_type.value,
                    'quantity': float(order.quantity),
                    'price': float(order.price) if order.price else None,
                    'status': order.status.value,
                    'filledQuantity': float(order.filled_quantity),
                    'avgPrice': None,
                    'commission': float(order.commission),
                    'commissionAsset': 'USDC',
                    'createdTime': int(order.created_at.timestamp() * 1000)
                }
                self.db_manager.save_order(db_order_dict)
                logger.info(f"✅ 订单已保存到数据库: {order.order_id}")
            except Exception as e:
                logger.error(f"❌ 保存订单到数据库失败: {e}", exc_info=True)
                logger.error(f"订单数据: {db_order_dict}")

            await self._notify_order_update(order)

            return order

        except Exception as e:
            logger.error(f"下单失败: {e}", exc_info=True)
            return None

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        """取消订单"""
        try:
            await self.exchange_client.cancel_order(symbol, order_id)

            async with self.order_lock:
                if order_id in self.orders:
                    self.orders[order_id].status = OrderStatus.CANCELLED
                    self.orders[order_id].updated_at = datetime.now()

            logger.info(f"订单已取消: {order_id}")
            return True

        except Exception as e:
            logger.error(f"取消订单失败: {e}")
            return False

    async def cancel_all_orders(self, symbol: str = None):
        """取消所有订单"""
        try:
            await self.exchange_client.cancel_all_orders(symbol)
            logger.info(f"已取消所有订单: {symbol or '全部'}")
            return True
        except Exception as e:
            logger.error(f"取消所有订单失败: {e}")
            return False

    async def preload_historical_data(self, limit: int = 1000):
        """预加载历史K线数据
        
        Args:
            limit: 获取的K线数量，默认1000根（用于AI策略的首次深度分析）
        """
        logger.info("="*80)
        logger.info("📥 [数据预加载] 开始预加载历史K线数据...")
        logger.info(f"📥 [数据预加载] 目标: 为每个交易对获取 {limit} 根**1分钟**K线 (日内交易模式)")
        logger.info("="*80)
        
        # 【关键修复】创建临时Backpack客户端用于获取K线
        from ..core.api_client import BackpackAPIClient
        backpack_client = BackpackAPIClient(
            access_key=self.config.backpack.ACCESS_KEY,
            refresh_key=self.config.backpack.REFRESH_KEY
        )
        
        for symbol in self.trading_symbols:
            try:
                logger.info(f"📡 [数据预加载] 正在获取 {symbol} 的历史K线数据 (1分钟周期, limit={limit})...")
                
                # 计算开始时间（对于1m周期，1000根 = 1000分钟 ≈ 16.7小时，取1天保险）
                start_time = int((datetime.now() - timedelta(days=1)).timestamp())
                end_time = int(datetime.now().timestamp())
                
                logger.debug(f"📅 时间范围: {datetime.fromtimestamp(start_time)} ~ {datetime.fromtimestamp(end_time)}")
                
                # 【关键修复】使用统一的转换方法，将用户symbol转换为Backpack格式
                backpack_symbol = self._convert_to_backpack_format(symbol)
                if backpack_symbol != symbol:
                    logger.info(f"🔄 [数据预加载] 交易对转换: {symbol} -> {backpack_symbol}")
                
                # 【关键修复】使用Backpack客户端获取历史1分钟K线
                klines = await backpack_client.get_klines(
                    symbol=backpack_symbol,
                    interval="1m",  # 日内交易改为1分钟周期
                    start_time=start_time,
                    end_time=end_time,
                    limit=limit
                )
                
                logger.info(f"📊 [数据预加载] API返回数据类型: {type(klines)}, 长度: {len(klines) if klines else 0}")
                
                if klines and len(klines) > 0:
                    # 打印第一条数据样本，用于调试
                    logger.info(f"📝 [数据预加载] 第一条K线样本:")
                    logger.info(f"   类型: {type(klines[0])}")
                    logger.info(f"   内容: {klines[0]}")

                    
                    success_count = 0
                    # 将历史数据添加到数据管理器
                    for idx, k in enumerate(klines):
                        try:
                            # Backpack API返回的是字典格式，需要转换为WebSocket格式
                            # API格式: {"start": "2024-01-01T00:00:00Z", "open": "3500", ...}
                            # 目标格式: {"t": timestamp, "o": "3500", "h": "3520", ...}
                            
                            if isinstance(k, dict):
                                # 处理Backpack API的字典格式
                                # 时间字段可能是 'start', 'timestamp', 't' 等
                                time_val = k.get('start') or k.get('timestamp') or k.get('t') or k.get('time')
                                
                                # 转换时间为毫秒级时间戳
                                if isinstance(time_val, str):
                                    # ISO格式字符串 "2024-01-01T00:00:00Z"
                                    # 【关键修复】Backpack API返回UTC时间，需要正确处理时区
                                    from dateutil import parser
                                    import pytz
                                    dt = parser.parse(time_val)
                                    # 如果时间字符串没有时区信息，假定为UTC
                                    if dt.tzinfo is None:
                                        dt = dt.replace(tzinfo=pytz.UTC)
                                    timestamp_ms = int(dt.timestamp() * 1000)
                                    logger.debug(f"📅 时间解析: {time_val} -> {dt} -> {timestamp_ms}")
                                elif isinstance(time_val, (int, float)):
                                    # 已经是时间戳，判断是秒还是毫秒
                                    timestamp_ms = int(time_val * 1000) if time_val < 10000000000 else int(time_val)
                                else:
                                    logger.warning(f"⚠️ 无法解析时间: {time_val}, 跳过第{idx}条")
                                    continue
                                
                                k_data = {
                                    "t": timestamp_ms,
                                    "o": str(k.get('open', 0)),
                                    "h": str(k.get('high', 0)),
                                    "l": str(k.get('low', 0)),
                                    "c": str(k.get('close', 0)),
                                    "v": str(k.get('volume', 0))
                                }
                            elif isinstance(k, list):
                                # 列表格式: [timestamp, open, high, low, close, volume]
                                # 时间戳可能是字符串或数字
                                timestamp_val = k[0] if len(k) > 0 else 0
                                
                                # 转换为数字（如果是字符串）
                                if isinstance(timestamp_val, str):
                                    try:
                                        timestamp_val = float(timestamp_val)
                                    except (ValueError, TypeError):
                                        logger.warning(f"⚠️ 无法解析时间戳: {timestamp_val}, 跳过第{idx}条")
                                        continue
                                
                                # 判断是秒还是毫秒
                                if timestamp_val < 10000000000:
                                    timestamp_ms = int(timestamp_val * 1000)
                                else:
                                    timestamp_ms = int(timestamp_val)
                                
                                k_data = {
                                    "t": timestamp_ms,
                                    "o": str(k[1]) if len(k) > 1 else "0",
                                    "h": str(k[2]) if len(k) > 2 else "0",
                                    "l": str(k[3]) if len(k) > 3 else "0",
                                    "c": str(k[4]) if len(k) > 4 else "0",
                                    "v": str(k[5]) if len(k) > 5 else "0"
                                }
                            else:
                                logger.warning(f"⚠️ 未知的K线数据格式: {type(k)}, 跳过第{idx}条")
                                continue
                            
                            # 【关键修复】使用基础币种作为缓存键，确保预加载和实时K线使用同一缓存
                            cache_symbol = self._extract_base_currency(symbol)  # ETH_USDC_PERP -> ETH
                            await self.data_manager.add_kline_data(cache_symbol, k_data, interval="1m")
                            success_count += 1
                            
                            # 每100条打印一次进度
                            if (idx + 1) % 100 == 0:
                                logger.info(f"📈 [数据预加载] {symbol} 进度: {idx + 1}/{len(klines)}")
                                
                        except Exception as e:
                            logger.error(f"❌ [数据预加载] 处理第{idx}条K线失败: {e}")
                            continue
                    
                    logger.info(f"✅ [数据预加载] {symbol} 成功加载 {success_count}/{len(klines)} 条历史K线")
                    
                    # 确认缓存数量（【关键修复】使用基础币种查询）
                    cache_symbol = self._extract_base_currency(symbol)  # ETH_USDC_PERP -> ETH
                    final_df = await self.data_manager.fetch_recent_data(cache_symbol, interval="1m", limit=limit)
                    logger.info(f"✅ [数据预加载] {symbol} 缓存验证 ({cache_symbol}_1m_live): 共{len(final_df)}条数据")
                    
                    if len(final_df) < 50:
                        logger.warning(f"⚠️ [数据预加载] {symbol} 数据量不足({len(final_df)}条)，AI策略可能无法正常工作!")
                    
                    # 【新增】预加载后立即触发一次AI分析
                    if symbol in self.strategies and len(final_df) >= 50:
                        logger.info(f"🤖 [数据预加载] 触发 {symbol} 首次AI分析...")
                        try:
                            strategy = self.strategies[symbol]
                            signals = await strategy.calculate_signal({symbol: final_df})
                            if signals:
                                logger.info(f"✅ [数据预加载] {symbol} 首次分析生成 {len(signals)} 个信号")
                                for signal in signals:
                                    await self.execute_signal(signal)
                            else:
                                logger.info(f"📊 [数据预加载] {symbol} 首次分析完成，当前无交易信号")
                        except Exception as e:
                            logger.error(f"❌ [数据预加载] {symbol} 首次分析失败: {e}", exc_info=True)
                else:
                    logger.warning(f"⚠️ [数据预加载] 未能获取 {symbol} 的历史K线数据")
            except Exception as e:
                logger.error(f"❌ [数据预加载] {symbol} 预加载失败: {e}", exc_info=True)
        
        # 【关键修复】关闭临时Backpack客户端
        await backpack_client.close_session()
        logger.debug("✅ [数据预加载] 临时Backpack客户端已关闭")
        
        logger.info("="*80)
        logger.info("✅ [数据预加载] 历史数据预加载完成!")
        logger.info("="*80)

    async def _order_status_loop(self):
        """订单状态监控循环"""
        while self.running:
            try:
                async with self.order_lock:
                    open_orders = [o for o in self.orders.values()
                                  if o.status in [OrderStatus.OPEN, OrderStatus.PENDING]]

                for order in open_orders:
                    try:
                        # 【优化】添加延迟，给 API 一些时间同步订单状态
                        await asyncio.sleep(0.5)
                        order_data = await self.exchange_client.get_order(order.order_id, symbol=order.symbol)
                        new_order = self._parse_order_response(order_data)

                        if new_order.status != order.status:
                            async with self.order_lock:
                                self.orders[order.order_id] = new_order

                            logger.info(f"订单状态更新: {order.order_id} -> {new_order.status.value}")

                            await self._notify_order_update(new_order)

                            if new_order.status == OrderStatus.FILLED:
                                await self._handle_filled_order(new_order)

                    except Exception as e:
                        error_str = str(e)
                        # 【问题4修复】处理404错误：订单不存在（可能已成交或取消）
                        if "404" in error_str or "not found" in error_str.lower():
                            logger.warning(f"⚠️ 订单 {order.order_id} API返回404（可能是API延迟），保留订单等待下次检查")
                            # 【优化】不立即删除订单，等待下次检查
                            # 如果连续多次404，才认为真的不存在
                            if not hasattr(order, '_404_count'):
                                order._404_count = 0
                            order._404_count += 1
                            
                            if order._404_count >= 3:  # 连续3次404
                                logger.info(f"🗑️ 订单 {order.order_id} 连续3次404，假设已成交并移除")
                                async with self.order_lock:
                                    # 假设订单已成交，更新状态
                                    order.status = OrderStatus.FILLED
                                    # 尝试处理成交订单
                                    try:
                                        await self._handle_filled_order(order)
                                    except Exception as e:
                                        # 【修复】记录异常但不中断流程
                                        logger.error(f"❌ 处理404订单成交失败: {order.order_id}, {e}", exc_info=True)
                                    # 从订单列表中移除（无论处理是否成功）
                                    if order.order_id in self.orders:
                                        del self.orders[order.order_id]
                                        logger.info(f"✅ 已移除404订单: {order.order_id}")
                        else:
                            logger.debug(f"检查订单状态失败: {order.order_id}, {e}")

            except Exception as e:
                logger.error(f"订单状态监控异常: {e}")

            await asyncio.sleep(2)

    async def _handle_filled_order(self, order: Order):
        """处理订单成交"""
        try:
            logger.info(f"📦 订单成交: {order.order_id}, 数量: {order.filled_quantity}, 价格: {order.price}")
            logger.debug(f"🔍 开始处理订单成交...")

            await self._notify_trade(order, "fill")
            logger.debug(f"✅ 成交通知完成")

            # 【问题2修复】获取实际成交价格
            actual_price = order.price
            if not actual_price or actual_price == Decimal("0"):
                try:
                    # 【优化】直接使用ticker获取价格，避免404错误
                    logger.debug(f"订单价格为None，使用ticker获取当前市场价格")
                    ticker = await self.exchange_client.get_ticker(order.symbol)
                    actual_price = Decimal(str(ticker.get('lastPrice', 0)))
                    logger.info(f"💰 获取到实际成交价格: {actual_price}")
                    logger.debug(f"✅ 价格获取完成")
                except Exception as e:
                    logger.error(f"获取成交价格失败: {e}")
                    # 【修复】如果无法获取价格，尝试从持仓记录中获取入场价
                    async with self.position_lock:
                        if order.symbol in self.positions:
                            position = self.positions[order.symbol]
                            actual_price = position.entry_price
                            logger.warning(f"⚠️ 使用持仓入场价作为成交价格: {actual_price}")
                        else:
                            actual_price = Decimal("0")
                            logger.error(f"❌ 无法获取成交价格，且无持仓记录，使用0")

            logger.debug(f"🔒 准备更新持仓，actual_price={actual_price}")
            async with self.position_lock:
                logger.debug(f"🔒 已获取持仓锁")
                # 计算持仓数量变化
                quantity_delta = order.filled_quantity if order.side == OrderSide.BUY else -order.filled_quantity
                logger.debug(f"📊 持仓数量变化: {quantity_delta}, 订单方向: {order.side}")
                
                if order.symbol in self.positions:
                    logger.debug(f"📋 更新现有持仓: {order.symbol}")
                    position = self.positions[order.symbol]
                    # 更新持仓数量
                    position.quantity += quantity_delta
                    position.updated_at = datetime.now()
                    logger.debug(f"✅ 持仓数量已更新: {position.quantity}")
                    
                    # 【修复】如果持仓未归零，同步更新策略类和风险管理器
                    if position.quantity > 0:
                        logger.debug(f"📊 持仓未归零，同步更新...")
                        # 同步更新策略类的持仓记录
                        if order.symbol in self.strategies:
                            strategy = self.strategies[order.symbol]
                            from ..strategy.base import Position as StrategyPosition
                            strategy.positions[order.symbol] = StrategyPosition(
                                symbol=order.symbol,
                                side=position.side.value,
                                quantity=float(position.quantity),
                                entry_price=float(position.entry_price),
                                current_price=float(position.mark_price or position.entry_price),
                                stop_loss=order.signal.stop_loss if hasattr(order, 'signal') and order.signal and hasattr(order.signal, 'stop_loss') else None,
                                take_profit=order.signal.take_profit if hasattr(order, 'signal') and order.signal and hasattr(order.signal, 'take_profit') else None
                            )
                        
                        # 【修复】同步更新风险管理器的持仓记录
                        # 注意：update_position 会根据 side 和 quantity 更新持仓
                        # 对于平仓（sell），quantity_delta 是负数，但 update_position 需要正数
                        if order.side == OrderSide.BUY:
                            # 开仓：增加持仓
                            self.risk_manager.update_position(
                                order.symbol,
                                'buy',
                                float(abs(quantity_delta)),
                                float(actual_price)
                            )
                        else:
                            # 平仓：减少持仓
                            self.risk_manager.update_position(
                                order.symbol,
                                'sell',
                                float(abs(quantity_delta)),
                                float(actual_price)
                            )
                    
                    # 如果持仓归零，删除持仓记录并保存平仓记录到数据库
                    if position.quantity <= 0:
                        logger.info(f"🔴 持仓已平仓: {order.symbol}，开始清理...")
                        # 保存平仓持仓记录到数据库
                        try:
                            position_data = {
                                'symbol': position.symbol,
                                'side': position.side.value,
                                'quantity': 0.0,
                                'entry_price': float(position.entry_price),
                                'current_price': float(actual_price),
                                'unrealized_pnl': 0.0,
                                'unrealized_pnl_percent': 0.0,
                                'stop_loss': None,
                                'take_profit': None,
                                'opened_at': position.created_at,
                                'closed_at': datetime.now()
                            }
                            self.db_manager.save_position(position_data)
                            logger.info(f"✅ 平仓记录已保存到数据库: {order.symbol}")
                        except Exception as e:
                            logger.error(f"❌ 保存平仓记录失败: {e}", exc_info=True)
                        
                        # 【修复】同步更新策略类的持仓记录
                        if order.symbol in self.strategies:
                            strategy = self.strategies[order.symbol]
                            if order.symbol in strategy.positions:
                                del strategy.positions[order.symbol]
                                logger.info(f"✅ 已同步删除策略类持仓记录: {order.symbol}")
                        
                        # 【修复】同步更新风险管理器的持仓记录
                        if order.symbol in self.risk_manager.positions:
                            # 计算盈亏
                            entry_price = float(position.entry_price)
                            exit_price = float(actual_price)
                            if position.side == PositionSide.LONG:
                                pnl = (exit_price - entry_price) * float(abs(quantity_delta))
                            else:  # SHORT
                                pnl = (entry_price - exit_price) * float(abs(quantity_delta))
                            
                            self.risk_manager.close_position(order.symbol, exit_price, pnl)
                            logger.info(f"✅ 已同步更新风险管理器持仓记录: {order.symbol}, PnL: {pnl:.2f}")
                        
                        del self.positions[order.symbol]
                        logger.info(f"✅ 持仓记录已清理完毕: {order.symbol}")
                else:
                    logger.debug(f"🆕 创建新持仓: {order.symbol}")
                    # 新建持仓
                    # 【修复】持仓方向判断：根据数量的正负决定
                    # 对于合约交易：BUY产生多头（正数量），SELL产生空头（负数量）
                    if quantity_delta > 0:
                        side = PositionSide.LONG
                        position_quantity = quantity_delta
                    else:
                        side = PositionSide.SHORT
                        position_quantity = abs(quantity_delta)
                    
                    self.positions[order.symbol] = Position(
                        symbol=order.symbol,
                        side=side,
                        quantity=position_quantity,
                        entry_price=actual_price,
                        mark_price=actual_price
                    )
                    logger.info(f"✅ 新建持仓: {order.symbol}, {side.value}, 订单方向={order.side.value}, 数量: {position_quantity}, 价格: {actual_price}")
                    
                    # 【修复】同步更新策略类的持仓记录
                    if order.symbol in self.strategies:
                        strategy = self.strategies[order.symbol]
                        from ..strategy.base import Position as StrategyPosition
                        strategy.positions[order.symbol] = StrategyPosition(
                            symbol=order.symbol,
                            side=side.value,
                            quantity=float(position_quantity),
                            entry_price=float(actual_price),
                            current_price=float(actual_price),
                            stop_loss=order.signal.stop_loss if hasattr(order, 'signal') and order.signal else None,
                            take_profit=order.signal.take_profit if hasattr(order, 'signal') and order.signal else None
                        )
                        logger.info(f"✅ 已同步更新策略类持仓记录: {order.symbol}")
                    
                    # 【修复】同步更新风险管理器的持仓记录
                    position_value = float(position_quantity) * float(actual_price)
                    self.risk_manager.update_position(
                        order.symbol,
                        order.side.value,
                        float(position_quantity),
                        float(actual_price)
                    )
                    margin = position_value / config.trading.LEVERAGE
                    logger.info(f"✅ 已同步更新风险管理器持仓记录: {order.symbol}, 价值: {position_value:.2f}, 保证金: {margin:.4f}")

            # 【问题2修复】保存持仓到数据库
            async with self.position_lock:
                if order.symbol in self.positions:
                    position = self.positions[order.symbol]
                    try:
                        position_data = {
                            'symbol': position.symbol,
                            'side': position.side.value,
                            'quantity': float(position.quantity),
                            'entry_price': float(position.entry_price),
                            'current_price': float(position.mark_price or position.entry_price),
                            'unrealized_pnl': float(position.unrealized_pnl),
                            'unrealized_pnl_percent': 0.0,
                            'stop_loss': None,
                            'take_profit': None,
                            'opened_at': position.created_at
                        }
                        self.db_manager.save_position(position_data)
                        logger.info(f"✅ 持仓已保存到数据库: {position.symbol}, {position.side.value}, 数量: {position.quantity}")
                    except Exception as e:
                        logger.error(f"❌ 保存持仓到数据库失败: {e}", exc_info=True)
                        logger.error(f"持仓数据: {position_data}")

            # 保存交易记录到数据库
            try:
                trade_id = f"trade_{order.order_id}_{int(time.time() * 1000)}"
                trade_data = {
                    'tradeId': trade_id,
                    'orderId': order.order_id,
                    'symbol': order.symbol,
                    'side': order.side.value,
                    'quantity': float(order.filled_quantity),
                    'price': float(actual_price),
                    'commission': float(order.commission),
                    'commissionAsset': 'USDC',
                    'isMaker': False,
                    'timestamp': int(order.updated_at.timestamp() * 1000)
                }
                self.db_manager.save_trade(trade_data)
                logger.info(f"✅ 交易记录已保存到数据库: {trade_id}")
            except Exception as e:
                logger.error(f"❌ 保存交易记录到数据库失败: {e}", exc_info=True)
                logger.error(f"交易数据: {trade_data}")

            if order.symbol in self.positions:
                await self._notify_position_update(self.positions[order.symbol])
            
            logger.info(f"✅✅✅ 订单成交处理完毕: {order.order_id}")
                
        except Exception as e:
            # 【修复】捕获所有异常，防止导致WebSocket循环中断
            logger.error(f"❌ 处理订单成交失败: {order.order_id}, {e}", exc_info=True)
            # 即使处理失败，也尝试清理订单记录，避免重复处理
            try:
                async with self.order_lock:
                    if order.order_id in self.orders:
                        logger.warning(f"⚠️ 清理异常订单记录: {order.order_id}")
                        del self.orders[order.order_id]
            except:
                pass

    async def _price_monitor_loop(self):
        """价格监控循环"""
        while self.running:
            try:
                # 【修复】检查连接状态，如果断开则重连
                if not self.ws_client._is_connected():
                    logger.warning("⚠️ WebSocket未连接，尝试重连...")
                    try:
                        await self.ws_client.connect()
                        logger.info("✅ WebSocket重连成功")
                    except Exception as e:
                        logger.error(f"❌ WebSocket重连失败: {e}")
                        await asyncio.sleep(5)  # 等待5秒后重试
                        continue
                
                message = await self.ws_client.receive()
                
                # 【修复】添加更详细的日志，确保能看到消息接收情况
                if "stream" in message and message.get("stream", "").startswith("kline"):
                    logger.debug(f"📨 收到K线WS消息: {message.get('stream')}")
                else:
                    logger.debug(f"📨 收到WS消息: {json.dumps(message, indent=2) if isinstance(message, dict) else str(message)}")

                # 适配Backpack WS消息格式
                if "stream" in message:
                    stream = message["stream"]
                    if stream.startswith("kline"):
                        try:
                            parts = stream.split(".")
                            if len(parts) >= 3:
                                backpack_symbol = parts[2]  # Backpack格式: ETH_USDT_PERP
                                # 【新增】映射到用户输入的格式
                                symbol = self.symbol_mapping.get(backpack_symbol, backpack_symbol)
                                logger.debug(f"📡 [Backpack] 收到K线: {backpack_symbol} -> {symbol}")
                                # 【修复】确保异常不会中断循环
                                try:
                                    await self._handle_kline_message(message["data"], symbol)
                                    logger.debug(f"✅ K线数据处理完成: {symbol}")
                                except Exception as e:
                                    # 【修复】捕获_handle_kline_message中的异常，防止中断循环
                                    logger.error(f"❌ 处理K线数据失败: {symbol}, {e}", exc_info=True)
                        except Exception as e:
                            logger.error(f"解析K线stream失败: {stream}, {e}", exc_info=True)
                elif "method" in message and message["method"] == "update":
                    update_params = message["params"]
                    for item in update_params:
                        if "ticker" in item:
                            await self._handle_ticker_message(item["ticker"])
                        elif "trades" in item:
                            await self._handle_trade_message(item["trades"])
                        elif "orderBookUpdate" in item:
                            await self._handle_depth_message(item["orderBookUpdate"])
                elif "result" in message:
                    logger.info(f"订阅成功: {message['result']}")
                elif "error" in message:
                    error_data = message['error']
                    if isinstance(error_data, dict):
                        logger.error(f"WS错误: {error_data}")
                    elif isinstance(error_data, str):
                        logger.error(f"WS错误: {error_data}")
                    elif error_data is None:
                        logger.info("WS操作成功")

            except ConnectionError as e:
                # 【修复】WebSocket连接断开，清空ws对象并等待下次循环重连
                logger.warning(f"⚠️ WebSocket连接断开: {e}，将5秒后重连...")
                self.ws_client.ws = None
                await asyncio.sleep(5)
            except Exception as e:
                # 【修复】捕获所有异常，防止WebSocket循环中断
                logger.error(f"❌ 价格监控循环异常: {e}", exc_info=True)
                # 等待一小段时间后继续，避免快速循环导致资源耗尽
                await asyncio.sleep(1)
                # 重置重连延迟
                self.ws_client.reconnect_delay = 1
                # 确保循环继续运行
                logger.info("🔄 价格监控循环继续运行...")

    async def _handle_trade_message(self, data: Dict):
        """处理成交消息（未使用，保留以备将来扩展）"""
        symbol = data.get("symbol", "")
        if symbol not in self.strategies:
            return
        logger.debug(f"收到成交消息: {symbol}")

    async def _handle_ticker_message(self, data: Dict):
        """处理Ticker消息（未使用，保留以备将来扩展）"""
        symbol = data.get("symbol", "")
        logger.debug(f"收到Ticker数据: {symbol} - 最新价: {data.get('lastPrice')}")

    async def _handle_depth_message(self, data: Dict):
        """处理深度消息（未使用，保留以备将来扩展）"""
        symbol = data.get("symbol", "")
        logger.debug(f"收到深度数据: {symbol}")

    async def _handle_kline_message(self, data: Dict, symbol: str = None):
        """处理K线数据"""
        try:
            logger.debug(f"🔍 _handle_kline_message开始: symbol={symbol}, data keys={list(data.keys()) if isinstance(data, dict) else 'N/A'}")
            
            if not symbol:
                symbol = data.get("s", "")
            
            if not symbol:
                logger.debug(f"⚠️ 无法获取symbol，跳过处理")
                return
                
            if symbol not in self.strategies:
                logger.debug(f"⚠️ {symbol} 未注册策略，跳过处理")
                return
                
            logger.info(f"📊 收到K线数据: {symbol} - 时间: {data.get('t')}, 收盘价: {data.get('c')}")
            
            # 【关键修复】使用基础币种作为缓存键，与预加载保持一致
            cache_symbol = self._extract_base_currency(symbol)  # ETH-USDT-SWAP -> ETH
            await self.data_manager.add_kline_data(symbol=cache_symbol, data=data, interval="1m")
            
            # 获取最新的1分钟K线数据（日内交易模式）
            df = await self.data_manager.fetch_recent_data(
                symbol=cache_symbol,  # 使用基础币种查询
                interval="1m",  # 【关键修复】改为1分钟，与订阅周期一致
                limit=1000  # 保持最新1000根1分钟K线
            )
            
            logger.info(f"📊 [K线处理] {symbol} 缓存数据量 ({cache_symbol}_1m_live): {len(df)}条")
            
            if df.empty:
                logger.warning(f"⚠️ [K线处理] {symbol} K线数据为空，跳过信号生成")
                return
            
            # 打印最新的K线时间，用于调试
            if not df.empty:
                latest_time = df.index[-1]
                latest_close = df['close'].iloc[-1]
                logger.info(f"📈 [K线处理] {symbol} 最新K线: 时间={latest_time}, 收盘价={latest_close:.2f}")
            
            # 【关键修复】移除K线处理时的余额和保证金检查
            # 原因：
            # 1. 每次K线推送（每分钟）都检查余额，过于频繁，浪费API调用
            # 2. place_order中已经有完善的风控检查（包括余额、保证金、持仓限制）
            # 3. 在下单时才检查更合理，不需要提前检查
            # 
            # 如果需要定期检查余额，可以在启动时检查一次，或者设置10分钟以上的缓存时间
                
            # 计算技术指标
            logger.info(f"📊 [K线处理] 开始计算 {symbol} 技术指标，数据量: {len(df)}")
            df = self.data_manager.calculate_technical_indicators(df)
            logger.info(f"✅ [K线处理] {symbol} 技术指标计算完成")
            
            # 【修复】在生成信号前，同步策略类的持仓状态
            if symbol not in self.strategies:
                logger.warning(f"⚠️ [K线处理] {symbol} 未注册策略，跳过信号生成")
                return
            
            strategy = self.strategies[symbol]
            logger.info(f"🤖 [策略执行] 准备调用策略: {strategy.__class__.__name__} for {symbol}")

            async with self.position_lock:
                # 同步引擎持仓到策略类
                if symbol in self.positions:
                    engine_position = self.positions[symbol]
                    # 【修复】只有持仓数量大于0时才同步
                    if float(engine_position.quantity) > 0:
                        from ..strategy.base import Position as StrategyPosition
                        strategy.positions[symbol] = StrategyPosition(
                            symbol=symbol,
                            side=engine_position.side.value,
                            quantity=float(engine_position.quantity),
                            entry_price=float(engine_position.entry_price),
                            current_price=float(engine_position.mark_price or engine_position.entry_price)
                        )
                    else:
                        # 如果引擎持仓数量为0，删除策略类的持仓
                        if symbol in strategy.positions:
                            del strategy.positions[symbol]
                            logger.debug(f"已同步删除策略类持仓: {symbol}（引擎持仓为0）")
                elif symbol in strategy.positions:
                    # 如果引擎没有持仓但策略类有，删除策略类的持仓（已平仓）
                    del strategy.positions[symbol]
                    logger.debug(f"已同步删除策略类持仓: {symbol}（引擎无持仓）")
            
            # 【修复】再次检查是否有未成交订单（防止在同步持仓后又有新订单）
            async with self.order_lock:
                pending_orders = [o for o in self.orders.values() 
                                if o.symbol == symbol and o.status in [OrderStatus.OPEN, OrderStatus.PENDING]]
                if pending_orders:
                    logger.warning(f"⚠️ {symbol} 在生成信号前发现 {len(pending_orders)} 个未成交订单，跳过信号生成")
                    return
            
            # 生成交易信号
            logger.info(f"🤖 [策略执行] 调用 {symbol} 策略的 calculate_signal 方法...")
            signals = await strategy.calculate_signal({symbol: df})
            logger.info(f"✅ [策略执行] {symbol} 策略执行完成，生成 {len(signals) if signals else 0} 个信号")
            
            if signals:
                for signal in signals:
                    logger.info(f"✅ 策略生成信号: {symbol} - {signal.action} @ {signal.price}, 数量: {signal.quantity}, 原因: {signal.reason}")
                    
                    order_side = OrderSide.BUY if signal.action == "buy" else OrderSide.SELL
                    # 【修复】强制使用市价单确保立即成交
                    order_type = OrderType.MARKET
                    # === 关键：把“平仓/减仓信号”按 reduce_only 执行，否则容易反手开仓 ===
                    is_close = False
                    reduce_only = False
                    try:
                        # 若引擎当前有持仓，且信号方向与持仓相反，则视为平仓/减仓
                        if symbol in self.positions:
                            pos = self.positions[symbol]
                            if (pos.side == PositionSide.LONG and order_side == OrderSide.SELL) or (pos.side == PositionSide.SHORT and order_side == OrderSide.BUY):
                                is_close = True
                                reduce_only = True
                    except Exception:
                        pass

                    await self.place_order(
                        symbol=symbol,
                        side=order_side,
                        order_type=order_type,
                        quantity=Decimal(str(signal.quantity)),
                        price=None,  # 市价单不需要价格
                        strategy_signal=signal,
                        is_close=is_close,
                        reduce_only=reduce_only,
                    )
            else:
                logger.debug(f"无交易信号: {symbol} - 价格: {df['close'].iloc[-1]:.2f}")
            
            logger.debug(f"✅ _handle_kline_message处理完成: {symbol}")
                
        except Exception as e:
            # 【修复】捕获所有异常，防止导致策略循环中断
            logger.error(f"❌ 处理K线数据异常: {symbol}, {e}", exc_info=True)
            # 【关键修复】即使出现异常，也要确保方法正常返回，不抛出异常
            # 这样不会中断_price_monitor_loop循环

    async def _heartbeat_loop(self):
        """心跳循环
        
        注意: 由于K线数据从Backpack获取,这里的心跳只是保持会话活跃
        不需要频繁调用Deepcoin API(会触发限流)
        """
        while self.running:
            try:
                # 【优化】只在有持仓时才心跳检测(避免频繁调用Deepcoin API)
                async with self.position_lock:
                    has_positions = len(self.positions) > 0
                
                if has_positions:
                    await self.exchange_client.get_server_time()
                    logger.debug("💓 心跳检测成功")
                else:
                    logger.debug("💤 无持仓,跳过心跳检测")
            except Exception as e:
                logger.warning(f"心跳检测失败: {e}")

            await asyncio.sleep(60)  # 改为60秒,减少API调用

    async def _position_monitor_loop(self):
        """【新增】持仓监控循环：监控止盈止损"""
        logger.info("启动持仓监控循环（止盈止损）")
        while self.running:
            try:
                # 【修复】先获取持仓列表副本，立即释放锁
                async with self.position_lock:
                    positions_to_check = list(self.positions.values())
                
                if not positions_to_check:
                    logger.debug("👀 持仓监控: 当前无持仓")
                    await asyncio.sleep(15)  # 无持仓时延长等待时间
                    continue
                
                logger.debug(f"👀 持仓监控: 检查 {len(positions_to_check)} 个持仓")
                
                # 【修复】在锁外处理每个持仓
                for position in positions_to_check:
                    try:
                        # 【说明】持仓在Deepcoin,所以需要从Deepcoin获取实时价格
                        # 但为了减少API调用,只在有持仓时才获取
                        exchange_name = self.exchange_client.__class__.__name__.replace('APIClient', '')
                        ticker = await self.exchange_client.get_ticker(position.symbol)
                        current_price = Decimal(str(ticker.get('lastPrice', 0)))
                        logger.debug(f"📊 [{exchange_name}] 获取 {position.symbol} 价格: {current_price}")
                        
                        logger.debug(f"👀 {position.symbol} 当前价格: {current_price}, 入场价格: {position.entry_price}")
                        
                        # 【修复】更新持仓标记价格（短暂获取锁）
                        async with self.position_lock:
                            # 再次检查持仓是否还存在（可能已被其他线程关闭）
                            if position.symbol not in self.positions:
                                logger.debug(f"⚠️ {position.symbol} 持仓已不存在，跳过")
                                continue
                            
                            self.positions[position.symbol].mark_price = current_price
                        
                        # === 优先使用“策略给出的价位止盈止损”（与 TradingView strategy.exit 更一致）===
                        # 若策略在 strategy.positions[symbol] 里写入了 stop_loss/take_profit，则按价位触发，
                        # 并跳过全局 config.trading 的阈值（避免策略逻辑被引擎提前/错误平仓）。
                        strat_stop = None
                        strat_tp = None
                        try:
                            if position.symbol in self.strategies:
                                strat = self.strategies[position.symbol]
                                sp = getattr(strat, "positions", {}).get(position.symbol)
                                if sp is not None:
                                    strat_stop = getattr(sp, "stop_loss", None)
                                    strat_tp = getattr(sp, "take_profit", None)
                        except Exception:
                            strat_stop = None
                            strat_tp = None

                        if strat_stop is not None or strat_tp is not None:
                            cur_px = float(current_price)
                            stop_px = float(strat_stop) if strat_stop is not None else None
                            tp_px = float(strat_tp) if strat_tp is not None else None

                            if position.side == PositionSide.LONG:
                                if stop_px and cur_px <= stop_px:
                                    logger.warning(f"[止损价位触发] {position.symbol} LONG 当前{cur_px:.4f} <= SL{stop_px:.4f}")
                                    await self._close_position(position, "strategy_stop_loss")
                                    continue
                                if tp_px and cur_px >= tp_px:
                                    logger.info(f"[止盈价位触发] {position.symbol} LONG 当前{cur_px:.4f} >= TP{tp_px:.4f}")
                                    await self._close_position(position, "strategy_take_profit")
                                    continue
                            else:
                                if stop_px and cur_px >= stop_px:
                                    logger.warning(f"[止损价位触发] {position.symbol} SHORT 当前{cur_px:.4f} >= SL{stop_px:.4f}")
                                    await self._close_position(position, "strategy_stop_loss")
                                    continue
                                if tp_px and cur_px <= tp_px:
                                    logger.info(f"[止盈价位触发] {position.symbol} SHORT 当前{cur_px:.4f} <= TP{tp_px:.4f}")
                                    await self._close_position(position, "strategy_take_profit")
                                    continue

                            # 若使用策略价位，则不再走全局阈值（直接更新未实现盈亏即可）
                            entry_price = float(position.entry_price)
                            current_price_float = float(current_price)
                            if entry_price > 0:
                                if position.side == PositionSide.LONG:
                                    pnl_percent = ((current_price_float - entry_price) / entry_price) * config.trading.LEVERAGE
                                    unrealized_pnl = (current_price - position.entry_price) * position.quantity
                                else:
                                    pnl_percent = ((entry_price - current_price_float) / entry_price) * config.trading.LEVERAGE
                                    unrealized_pnl = (position.entry_price - current_price) * position.quantity
                            else:
                                pnl_percent = 0.0
                                unrealized_pnl = Decimal("0")
                            async with self.position_lock:
                                if position.symbol in self.positions:
                                    self.positions[position.symbol].unrealized_pnl = unrealized_pnl
                            # 写库（保持原字段）
                            position_data = {
                                'symbol': position.symbol,
                                'side': position.side.value,
                                'quantity': float(position.quantity),
                                'entry_price': float(position.entry_price),
                                'current_price': float(current_price),
                                'unrealized_pnl': float(unrealized_pnl),
                                'unrealized_pnl_percent': pnl_percent,
                                'stop_loss': stop_px,
                                'take_profit': tp_px,
                                'opened_at': position.created_at
                            }
                            self.db_manager.save_position(position_data)
                            continue

                        # 【修复】计算收益率（在锁外）
                        entry_price = float(position.entry_price)
                        current_price_float = float(current_price)
                        
                        if position.side == PositionSide.LONG:
                            # 多头：计算持仓盈亏比例（含杠杆）
                            # 公式：盈亏% = (当前价 - 入场价) / 入场价 × 杠杆倍数
                            price_change_percent = (current_price_float - entry_price) / entry_price
                            leverage = config.trading.LEVERAGE  # 50倍杠杆
                            pnl_percent = price_change_percent * leverage
                            
                            # 止损/止盈阈值不变
                            stop_loss_percent = -config.trading.STOP_LOSS_PERCENT  # -2%
                            take_profit_percent = config.trading.TAKE_PROFIT_PERCENT  # +3%
                            
                            logger.debug(f"👀 {position.symbol} 多头 价格变动: {price_change_percent*100:.4f}%, 杠杆: {leverage}x, 持仓PnL: {pnl_percent*100:.2f}%, 止损阈值: {stop_loss_percent*100:.1f}%, 止盈阈值: {take_profit_percent*100:.1f}%")
                            
                            # 止损：持仓亏损 >= 2%
                            if pnl_percent <= stop_loss_percent:
                                logger.warning(f"🔴 {position.symbol} 触发止损: 持仓亏损{pnl_percent*100:.2f}% <= 止损阈值{stop_loss_percent*100:.1f}%")
                                await self._close_position(position, "stop_loss")
                            # 止盈：持仓盈利 >= 3%
                            elif pnl_percent >= take_profit_percent:
                                logger.info(f"🟢 {position.symbol} 触发止盈: 持仓盈利{pnl_percent*100:.2f}% >= 止盈阈值{take_profit_percent*100:.1f}%")
                                await self._close_position(position, "take_profit")
                            else:
                                # 更新未实现盈亏
                                unrealized_pnl = (current_price - position.entry_price) * position.quantity
                                async with self.position_lock:
                                    if position.symbol in self.positions:
                                        self.positions[position.symbol].unrealized_pnl = unrealized_pnl
                                
                                # 更新数据库
                                position_data = {
                                    'symbol': position.symbol,
                                    'side': position.side.value,
                                    'quantity': float(position.quantity),
                                    'entry_price': float(position.entry_price),
                                    'current_price': float(current_price),
                                    'unrealized_pnl': float(unrealized_pnl),
                                    'unrealized_pnl_percent': pnl_percent,
                                    'stop_loss': None,
                                    'take_profit': None,
                                    'opened_at': position.created_at
                                }
                                self.db_manager.save_position(position_data)
                                
                        else:  # SHORT
                                    # 空头：计算持仓盈亏比例（含杠杆）
                                    # 公式：盈亏% = (入场价 - 当前价) / 入场价 × 杠杆倍数
                                    # 【修复】空头盈亏：价格下跌 = 盈利，价格上涨 = 亏损
                                    price_change_percent = (entry_price - current_price_float) / entry_price
                                    leverage = config.trading.LEVERAGE  # 50倍杠杆
                                    pnl_percent = price_change_percent * leverage
                                    
                                    # 止损/止盈阈值不变
                                    stop_loss_percent = -config.trading.STOP_LOSS_PERCENT  # -2%
                                    take_profit_percent = config.trading.TAKE_PROFIT_PERCENT  # +3%
                                    
                                    logger.debug(f"👀 {position.symbol} 空头 价格变动: {price_change_percent*100:.4f}%, 杠杆: {leverage}x, 持仓PnL: {pnl_percent*100:.2f}%, 止损阈值: {stop_loss_percent*100:.1f}%, 止盈阈值: {take_profit_percent*100:.1f}%")
                                    logger.info(f"📊 {position.symbol} 空头盈亏明细: 入场价=${entry_price:.2f}, 当前价=${current_price_float:.2f}, 价格差=${entry_price - current_price_float:.2f}, PnL={pnl_percent*100:.2f}%")
                                    
                                    # 止损：持仓亏损 >= 2%
                                    if pnl_percent <= stop_loss_percent:
                                        logger.warning(f"🔴 {position.symbol} 触发止损: 持仓亏损{pnl_percent*100:.2f}% <= 止损阈值{stop_loss_percent*100:.1f}%")
                                        await self._close_position(position, "stop_loss")
                                    # 止盈：持仓盈利 >= 3%
                                    elif pnl_percent >= take_profit_percent:
                                        logger.info(f"🟢 {position.symbol} 触发止盈: 持仓盈利{pnl_percent*100:.2f}% >= 止盈阈值{take_profit_percent*100:.1f}%")
                                        await self._close_position(position, "take_profit")
                                    else:
                                        # 更新未实现盈亏
                                        unrealized_pnl = (position.entry_price - current_price) * position.quantity
                                        self.positions[position.symbol].unrealized_pnl = unrealized_pnl
                                        
                                        # 更新数据库
                                        position_data = {
                                            'symbol': position.symbol,
                                            'side': position.side.value,
                                            'quantity': float(position.quantity),
                                            'entry_price': float(position.entry_price),
                                            'current_price': float(current_price),
                                            'unrealized_pnl': float(unrealized_pnl),
                                            'unrealized_pnl_percent': pnl_percent,
                                            'stop_loss': None,
                                            'take_profit': None,
                                            'opened_at': position.created_at
                                        }
                                        self.db_manager.save_position(position_data)
                                
                    except Exception as e:
                        logger.error(f"监控持仓失败: {position.symbol}, {e}", exc_info=True)
                
            except Exception as e:
                logger.error(f"持仓监控循环异常: {e}", exc_info=True)
            
            await asyncio.sleep(30)  # 每30秒检查一次,避免频繁请求导致限流

    async def _close_position(self, position: Position, reason: str):
        """平仓（全部卖出）"""
        try:
            logger.info(f"🚨 开始平仓: {position.symbol}, 原因: {reason}")
            
            # 【修复1】先从交易所获取真实持仓，避免本地持仓数据不准确
            # 【优化】添加重试机制，避免网络抖动导致获取失败
            has_position = True  # 默认认为有持仓
            try:
                exchange_positions = await self.exchange_client.get_positions(position.symbol)
                logger.info(f"📊 交易所实际持仓数据: {exchange_positions}")
                
                # 检查是否真的有持仓
                has_position = False
                actual_quantity = 0
                actual_side = None
                
                if isinstance(exchange_positions, list):
                    for pos in exchange_positions:
                        if pos.get('symbol') == position.symbol:
                            # 【修复】Backpack API 字段映射：
                            # netQuantity: 净持仓（负数=空头，正数=多头）
                            # netExposureQuantity: 绝对数量
                            net_qty = float(pos.get('netQuantity', 0))
                            abs_qty = float(pos.get('netExposureQuantity', 0))
                            
                            if abs_qty > 0:  # 使用绝对数量判断是否有持仓
                                has_position = True
                                actual_quantity = abs_qty
                                # 根据 netQuantity 的正负判断方向
                                actual_side = 'short' if net_qty < 0 else 'long'
                                logger.info(f"✅ 找到交易所持仓: {position.symbol}, 方向: {actual_side}, 净数量: {net_qty}, 绝对数量: {abs_qty}")
                                break
                
                if not has_position:
                    logger.warning(f"⚠️ 交易所无持仓，本地持仓可能已过期，直接清理: {position.symbol}")
                    # 直接从本地删除持仓
                    async with self.position_lock:
                        if position.symbol in self.positions:
                            del self.positions[position.symbol]
                            logger.info(f"✅ 已清理本地持仓记录: {position.symbol}")
                    return
                    
            except Exception as e:
                logger.error(f"获取交易所持仓失败: {e}，继续使用本地持仓数据")
                # 【优化】如果获取失败，仍然尝试平仓（避免遗漏）
                has_position = True
            
            # 决定平仓方向：多头卖出，空头买入
            close_side = OrderSide.SELL if position.side == PositionSide.LONG else OrderSide.BUY
            
            # 使用市价单立即平仓，【修复】传入 is_close=True 跳过风控检查
            order = await self.place_order(
                symbol=position.symbol,
                side=close_side,
                order_type=OrderType.MARKET,
                quantity=position.quantity,
                price=None,
                is_close=True,
                reduce_only=True  # 【关键】标记为只减少持仓
            )
            
            if order:
                logger.info(f"✅ 平仓订单已提交: {position.symbol}, 订单ID: {order.order_id}")
                
                # 【修复2】平仓订单提交成功后，立即清理本地持仓（避免保证金累积）
                async with self.position_lock:
                    if position.symbol in self.positions:
                        del self.positions[position.symbol]
                        logger.info(f"✅ 已清理本地持仓记录（平仓成功）: {position.symbol}")
            else:
                logger.error(f"❌ 平仓订单提交失败: {position.symbol}")
                # 【修复3】平仓失败，从交易所重新同步持仓状态
                # 【优化】延迟同步，避免平仓时过多API调用
                logger.warning("⚠️ 平仓失败，将5秒后重新同步持仓状态")
                await asyncio.sleep(5)
                await self.load_positions()
                
        except Exception as e:
            logger.error(f"平仓失败: {position.symbol}, {e}", exc_info=True)
            # 异常情况下也尝试同步持仓
            try:
                await asyncio.sleep(5)  # 【优化】延迟同步
                await self.load_positions()
            except:
                pass

    def get_account_summary(self) -> str:
        """获取账户摘要"""
        total_value = sum(bal.total for bal in self.balances.values())
        return f"总资产: {total_value:.4f} USDC"

    def get_positions_summary(self) -> str:
        """获取持仓摘要"""
        if not self.positions:
            return "无持仓"

        summary = []
        for pos in self.positions.values():
            summary.append(
                f"{pos.symbol} {pos.side.value}: {pos.quantity} @ {pos.entry_price}, "
                f"PnL: {pos.unrealized_pnl:.4f}"
            )
        return "; ".join(summary)

    def get_order_summary(self) -> str:
        """获取订单摘要"""
        return f"待成交订单: {len(self.orders)}"

    def get_portfolio_value(self) -> Decimal:
        """计算组合价值（包含 USDC、USDT、USD 等稳定币）"""
        total = Decimal("0")
        for bal in self.balances.values():
            a = (bal.asset or "").upper().replace(" ", "")
            if a in ("USDC", "USDT", "USD") or "USDC" in a or "USDT" in a or a == "USDOLLAR":
                total += bal.total
        for pos in self.positions.values():
            total += pos.quantity * pos.mark_price
        return total

    def _write_balance_to_file(self, portfolio_value: float):
        """将账户余额写入 live_balances.json，供仪表盘 API 读取显示"""
        if not self._instance_id:
            return
        try:
            balances_path = self.config.log_dir / "live_balances.json"
            data = {}
            if balances_path.exists():
                try:
                    data = json.loads(balances_path.read_text(encoding="utf-8"))
                except Exception:
                    pass
            data[self._instance_id] = {"balance": portfolio_value, "updated_at": time.time()}
            balances_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.debug(f"写入余额文件失败: {e}")

    async def _snapshot_loop(self):

        """【新增】资产快照循环：定期记录组合净值"""
        logger.info("📸 启动资产快照监控循环")
        while self.running:
            try:
                # 获取当前总资产价值
                portfolio_value = self.get_portfolio_value()
                
                # 获取现金余额（USDC、USDT、USD）
                cash_balance = 0.0
                async with self.balance_lock:
                    for asset in ['USDC', 'USDT', 'USD']:
                        if asset in self.balances:
                            cash_balance += float(self.balances[asset].available)
                
                # 计算持仓价值
                position_value = float(portfolio_value) - cash_balance
                
                # 保存快照到数据库
                # 【修复】统一转换为float,避免Decimal和float混合运算
                portfolio_value_float = float(portfolio_value)
                cash_balance_float = float(cash_balance)
                position_value_float = float(position_value)
                daily_pnl_float = float(self.risk_manager.daily_pnl)
                daily_return = (daily_pnl_float / portfolio_value_float * 100) if portfolio_value_float > 0 else 0
                
                self.db_manager.save_portfolio_snapshot(
                    portfolio_value=portfolio_value_float,
                    cash_balance=cash_balance_float,
                    position_value=position_value_float,
                    daily_pnl=daily_pnl_float,
                    daily_return=daily_return,
                    source='deepcoin' if hasattr(self.exchange_client, '__class__') and 'Deepcoin' in self.exchange_client.__class__.__name__ else 'backpack'
                )
                self._write_balance_to_file(portfolio_value_float)  # 供仪表盘显示账户余额
                logger.debug(f"📸 资产快照已保存: 总资产=${portfolio_value:.2f}, 现金=${cash_balance:.2f}, 持仓=${position_value:.2f}")
                
            except Exception as e:
                logger.error(f"📸 记录资产快照失败: {e}")
            
            await asyncio.sleep(60) # 每分钟记录一次快照

