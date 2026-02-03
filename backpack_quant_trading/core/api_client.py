import asyncio  #python异步I/O架构
import websockets #WebSocket客户端库
from typing import Dict, List, Optional, Any, Callable, Protocol   #类型注释
from dataclasses import dataclass, field #数据类装饰器
from enum import Enum #枚举类
import logging #日志模块
from queue import Queue #线程安全队列
from collections import defaultdict #带默认值的字典
import base64 #base64编码解码
import time #时间模块
import json  #json编解码
from urllib.parse import urlencode  #URL参数编码
import requests #HTTP请求库
from cryptography.hazmat.primitives.asymmetric import ed25519  #ED25519加密算法


from ..config.settings import config

logger = logging.getLogger(__name__)


class ExchangeClient(Protocol):
    """交易所抽象接口

    为了后续无缝切换交易所，下单相关能力通过该接口抽象；
    行情与K线（不需要认证的实时数据）仍统一从 Backpack WebSocket 获取。
    """

    async def get_markets(self) -> Dict[str, Dict]:
        ...

    async def get_ticker(self, symbol: str) -> Dict:
        ...

    async def get_depth(self, symbol: str, limit: int = 1000) -> Dict:
        ...

    async def get_klines(self, symbol: str, interval: str, start_time: Optional[int] = None, end_time: Optional[int] = None, limit: int = 100) -> List[Dict]:
        ...

    async def get_account(self) -> Dict:
        ...

    async def get_balances(self) -> Dict[str, Dict]:
        ...

    async def get_server_time(self) -> int:
        ...

    async def get_balance(self) -> List[Dict]:
        ...

    async def get_positions(self, symbol: Optional[str] = None) -> List[Dict]:
        ...

    async def place_order(self, order_data: Dict) -> Dict:
        ...

    async def execute_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str,
        price: Optional[float] = None,
        max_leverage: Optional[int] = None,
        reduce_only: bool = False,
    ) -> Dict:
        ...

    async def cancel_order(self, symbol: str, order_id: Optional[str] = None, client_id: Optional[str] = None) -> Dict:
        ...

    async def cancel_all_orders(self, symbol: Optional[str] = None) -> Dict:
        ...

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict]:
        ...

    async def get_order(self, order_id: str, symbol: Optional[str] = None) -> Dict:
        ...

    async def get_order_history(self, symbol: Optional[str] = None, limit: int = 100) -> List[Dict]:
        ...


class BackpackAPIClient:
    """Backpack Exchange API 客户端"""

    def __init__(self, access_key: str = None, refresh_key: str = None, public_only: bool = False):
        self.base_url = config.backpack.API_BASE_URL
        self.public_only = public_only  # 标记：是否仅用于公共接口
        
        # Cookie认证
        if not public_only:
            self.access_key = access_key or config.backpack.ACCESS_KEY
            self.refresh_key = refresh_key or config.backpack.REFRESH_KEY
        else:
            self.access_key = None
            self.refresh_key = None
        
        # ED25519密钥认证（可选）
        self.private_key = None
        self.public_key = None
        self.ed25519_key = None
        
        if not public_only:
            private_key_b64 = config.backpack.PRIVATE_KEY
            public_key_b64 = config.backpack.PUBLIC_KEY
            
            if private_key_b64 and public_key_b64:
                try:
                    self.private_key = base64.b64decode(private_key_b64)
                    self.public_key = base64.b64decode(public_key_b64)
                    self.ed25519_key = ed25519.Ed25519PrivateKey.from_private_bytes(
                        self.private_key
                    )
                    logger.info("ED25519密钥已加载，将使用密钥认证")
                except Exception as e:
                    logger.warning(f"ED25519密钥加载失败，将使用Cookie认证: {e}")
            else:
                logger.info("未配置ED25519密钥，将使用Cookie认证")
        else:
            logger.info("🔓 Backpack客户端初始化为公共模式（仅获取行情）")
        
        self.session = requests.Session()
        self._markets_cache = None
        self._markets_cache_time = 0

    async def get_session(self):
        """获取会话（异步包装）"""
        # requests.Session是同步的，但为了兼容异步接口，使用asyncio.to_thread包装
        return self.session

    async def close_session(self):
        """关闭会话（异步包装）"""
        # requests.Session.close是同步的，但为了兼容异步接口，使用asyncio.to_thread包装
        if self.session:
            self.session.close()

    def _generate_signature(self, instruction: str, params: Dict[str, Any]) -> Dict[str, str]:
        """生成请求签名"""
        #获取当前时间戳(毫秒)
        timestamp = int(time.time() * 1000)
        window = config.backpack.DEFAULT_WINDOW

        # 创建一个新的参数字典，确保所有值都是字符串
        sign_params = {}
        for key, value in params.items():
            if isinstance(value, bool):
                # boolean值转换为小写字符串
                sign_params[key] = str(value).lower()
            elif isinstance(value, (int, float)):
                sign_params[key] = str(value)
            else:
                sign_params[key] = value

        # 1. 对参数按字母顺序排序
        sorted_params = dict(sorted(sign_params.items()))

        # 2. 转换为查询字符串
        # 注意：Backpack API 对签名参数的编码有特殊要求，urlencode 默认会把空格转成 +，
        # 但有些交易所要求 %20，Backpack 通常要求原样或严格遵循 RFC 3986。
        # 且 Backpack 签名时，某些 GET 参数如果值为空或为 0，可能影响签名。
        
        # 强制将所有值转为字符串，并处理 boolean
        processed_params = {}
        for k, v in sorted_params.items():
            if v is None: continue
            processed_params[k] = v

        query_str = urlencode(processed_params)

        # 3. 构建签名字符串
        # 格式：instruction=<指令>&<参数串>&timestamp=<时间戳>&window=<时间窗口>
        sign_str = f"instruction={instruction}"
        if query_str:
            sign_str += f"&{query_str}"
        sign_str += f"&timestamp={timestamp}&window={window}"

        # 4. 使用ED25519私钥对字符串进行签名
        # sign_str.encode() 将字符串转为bytes
        # .sign() 使用私钥签名
        # base64.b64encode() 将签名转为base64字符串
        signature = self.ed25519_key.sign(sign_str.encode())
        signature_b64 = base64.b64encode(signature).decode()

        # 5. 返回请求头
        return {
            "X-API-Key": base64.b64encode(self.public_key).decode(),  # base64编码的公钥
            "X-Signature": signature_b64, # 签名
            "X-Timestamp": str(timestamp), # 时间戳
            "X-Window": str(window) # 时间窗口
        }

    def _request(self, method: str, endpoint: str, 
                 instruction: str = None, 
                 params: Dict = None, 
                 data: Any = None) -> Dict:
        """发送请求"""
        url = f"{self.base_url}{endpoint}"
        headers = {"Content-Type": "application/json; charset=utf-8"}

        # 认证处理
        if instruction and self.ed25519_key:
            # 使用ED25519签名认证
            sign_params = params.copy() if params else {}
            
            # 如果data是字典，直接更新到sign_params
            # 如果data是列表，我们需要提取列表中的第一个订单数据用于签名（API要求）
            if data:
                if isinstance(data, dict):
                    sign_params.update(data)
                elif isinstance(data, list) and data:
                    # 对于订单列表，我们只使用第一个订单的数据进行签名
                    sign_params.update(data[0])
            
            auth_headers = self._generate_signature(instruction, sign_params)
            headers.update(auth_headers)
        elif self.access_key:
            # 使用Cookie认证
            if self.refresh_key:
                headers["Cookie"] = f"accessKey={self.access_key}; refreshKey={self.refresh_key}"
            else:
                headers["Cookie"] = f"accessKey={self.access_key}"

        try:
            response = self.session.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=data
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"API请求失败: {e}")
            if 'response' in locals():
                logger.error(f"响应状态码: {response.status_code}")
                logger.error(f"响应内容: {response.text}")
                logger.error(f"请求URL: {url}")
                logger.error(f"请求头: {headers}")
                # 【修复】如果是 400 错误，可能是签名问题或参数错误
                if response.status_code == 400:
                    logger.error(f"⚠️ 400 Bad Request - 可能原因：")
                    logger.error("  1. API签名错误（检查 instruction 参数）")
                    logger.error("  2. 时间戳过期（检查系统时间）")
                    logger.error("  3. API请求频率限制")
                    logger.error("  4. 缺少必要参数")
            raise

    async def get_quantity_precision(self, symbol: str) -> int:
        """获取交易对的数量精度（basePrecision）"""
        try:
            markets = await self.get_markets()
            market = markets.get(symbol)
            if market:
                # Backpack API 返回的字段通常是 basePrecision
                return int(market.get('basePrecision', 4))
        except Exception as e:
            logger.warning(f"获取 {symbol} 数量精度失败: {e}")
        return 4

    async def get_price_precision(self, symbol: str) -> int:
        """获取交易对的价格精度（quotePrecision）"""
        try:
            markets = await self.get_markets()
            market = markets.get(symbol)
            if market:
                # Backpack API 返回的字段通常是 quotePrecision
                return int(market.get('quotePrecision', 2))
        except Exception as e:
            logger.warning(f"获取 {symbol} 价格精度失败: {e}")
        return 2

    # 市场数据接口
    async def get_markets(self) -> Dict[str, Dict]:
        """获取所有市场 (带缓存)"""
        now = time.time()
        if self._markets_cache and now - self._markets_cache_time < 3600:
            return self._markets_cache
            
        markets_list = await asyncio.to_thread(self._request, "GET", "/api/v1/markets")
        # 将列表转换为字典，以symbol为键
        markets_dict = {}
        for market in markets_list:
            if 'symbol' in market:
                markets_dict[market['symbol']] = market
        
        self._markets_cache = markets_dict
        self._markets_cache_time = now
        return markets_dict

    async def get_ticker(self, symbol: str) -> Dict:
        """获取ticker数据"""
        # 构造查询参数：symbol=交易对
        return await asyncio.to_thread(self._request, "GET", "/api/v1/ticker", params={"symbol": symbol})

    async def get_depth(self, symbol: str, limit: int = 1000) -> Dict:
        """获取深度数据"""
        return await asyncio.to_thread(self._request, "GET", "/api/v1/depth",
                             params={"symbol": symbol, "limit": limit})

    async def get_klines(self, symbol: str, interval: str,
                   start_time: Optional[int] = None, end_time: Optional[int] = None, limit: int = 100) -> List[Dict]:
        """获取K线数据 (注意：Backpack API 要求 startTime 为秒级时间戳)"""
        params = {
            "symbol": symbol, #交易对
            "interval": interval, #时间间隔:1m,5m,1h等
            "limit": limit
        }
        if start_time is not None:
            # 如果是 13 位毫秒，转为秒
            if start_time > 10000000000:
                start_time //= 1000
            params["startTime"] = start_time
        if end_time is not None:
            if end_time > 10000000000:
                end_time //= 1000
            params["endTime"] = end_time
        return await asyncio.to_thread(self._request, "GET", "/api/v1/klines", params=params)

    # 账户接口
    async def get_account(self) -> Dict:
        """获取账户信息  需要签名"""
        return await asyncio.to_thread(self._request, "GET", "/api/v1/account", instruction="accountQuery")

    async def get_balances(self) -> Dict[str, Dict]:
        """获取余额  需要签名"""
        return await asyncio.to_thread(self._request, "GET", "/api/v1/capital", instruction="balanceQuery")

    async def get_balance(self) -> Dict[str, float]:
        """获取余额（兼容 Backpack 的 list 返回格式）"""
        balances = await self.get_balances()
        # Backpack 返回格式通常是: [{'asset': 'USDC', 'available': '100.0', 'locked': '0.0'}, ...]
        # 或者是一个以资产名为键的字典
        
        result = {}
        if isinstance(balances, list):
            for item in balances:
                if isinstance(item, dict) and 'asset' in item:
                    asset = item['asset']
                    available = float(item.get('available') or 0)
                    result[asset] = available
        elif isinstance(balances, dict):
            for asset, info in balances.items():
                if isinstance(info, dict):
                    result[asset] = float(info.get('available') or info.get('limit', 0))
                else:
                    result[asset] = float(info)
        
        return result

    async def get_server_time(self) -> int:
        """获取服务器时间"""
        try:
            # 尝试获取市场数据来获取服务器时间
            markets = await self.get_markets()
            # 如果响应中有时区信息，可以从中提取时间
            # 否则使用当前时间戳
            return int(time.time() * 1000)
        except Exception as e:
            logger.warning(f"获取服务器时间失败，使用本地时间: {e}")
            return int(time.time() * 1000)

    async def get_positions(self, symbol: str = None) -> List[Dict]:
        """获取仓位 需要签名"""
        params = {}
        if symbol:
            params["symbol"] = symbol
        return await asyncio.to_thread(self._request, "GET", "/api/v1/position",
                             instruction="positionQuery", params=params)

    # 订单接口
    async def place_order(self, order_data: Dict) -> Dict:
        """下单"""
        return await asyncio.to_thread(self._request, "POST", "/api/v1/orders",
                             instruction="orderExecute", data=order_data)
                             
    async def execute_order(self, symbol, side, quantity, order_type, price=None, max_leverage=None, reduce_only=False):
        """执行订单"""
        try:
            # Backpack 规范：BUY/SELL -> Bid/Ask; LIMIT/MARKET -> Limit/Market
            side_map = {'BUY': 'Bid', 'SELL': 'Ask', 'BID': 'Bid', 'ASK': 'Ask'}
            type_map = {'LIMIT': 'Limit', 'MARKET': 'Market', 'limit': 'Limit', 'market': 'Market'}
            
            side = side_map.get(side.upper(), side)
            order_type = type_map.get(order_type, order_type)
            
            # 构建订单参数
            order_data = {
                'symbol': symbol,
                'side': side,
                'quantity': str(quantity),
                'orderType': order_type
            }
            
            # 如果是限价单，添加价格参数
            if order_type == 'Limit' and price is not None:
                order_data['price'] = str(price)
            
            # 添加仅减少持仓参数（根据API文档，reduceOnly应该是boolean类型）
            if reduce_only:
                order_data['reduceOnly'] = True
            
            # 注意：根据openapi.json，OrderExecutePayload中没有maxLeverage字段
            # 杠杆应该在账户层面设置，而不是在订单层面
            
            # 使用_request方法发送请求，保持与其他API方法一致
            # 注意：API要求orderExecute接口的请求体是一个订单列表
            order_list = [order_data]
            logger.info(f"准备发送订单数据: {order_list}")
            response = await asyncio.to_thread(self._request,
                method="POST",
                endpoint="/api/v1/orders",
                instruction="orderExecute",
                data=order_list
            )
            
            # Backpack 的订单执行结果处理
            # 兼容：如果是列表，取第一个；确保包含 orderId
            res_data = response[0] if isinstance(response, list) and response else response
            
            # 统一字段名，确保网格策略能读到
            if isinstance(res_data, dict):
                res_data['orderId'] = res_data.get('orderId') or res_data.get('id')
                status_upper = (res_data.get('status') or '').upper()
                if status_upper in ('FILLED', 'COMPLETE'):
                    res_data['status'] = 'FILLED'
                elif status_upper in ('OPEN', 'RESTING', 'PENDING'):
                    res_data['status'] = 'PENDING'
                else:
                    res_data['status'] = status_upper
            
            logger.info(f"执行订单成功: {symbol} {side} {quantity} {order_type} (仅减少: {reduce_only}) - {res_data}")
            return res_data
        except Exception as e:
            logger.error(f"执行订单失败: {e}")
            raise

    async def cancel_order(self, symbol: str, order_id: str = None,
                     client_id: str = None) -> Dict:
        """取消订单"""
        data = {"symbol": symbol}
        if order_id:
            data["orderId"] = order_id
        if client_id:
            data["clientId"] = client_id
        return await asyncio.to_thread(self._request, "DELETE", "/api/v1/order",
                             instruction="orderCancel", data=data)
                             
    async def cancel_all_orders(self, symbol: str = None) -> Dict:
        """取消所有订单"""
        data = {}
        if symbol:
            data["symbol"] = symbol
        return await asyncio.to_thread(self._request, "DELETE", "/api/v1/orders",
                             instruction="orderCancel", data=data)

    async def get_open_orders(self, symbol: str = None) -> List[Dict]:
        """获取未成交订单"""
        params = {}
        if symbol:
            params["symbol"] = symbol
        return await asyncio.to_thread(self._request, "GET", "/api/v1/orders",
                             instruction="orderQueryAll", params=params)

    async def get_order(self, order_id: str, symbol: str = None) -> Dict:
        """获取单个订单 (强化版：活跃库查不到则去历史库搜寻)
        Backpack API: GET /api/v1/order?orderId=xxx&symbol=xxx (非路径参数)
        """
        try:
            # 1. 尝试从活跃库查询（仅返回未成交挂单，已成交/已取消会 404）
            params = {"orderId": order_id}
            if symbol:
                params["symbol"] = symbol
            return await asyncio.to_thread(self._request, "GET", "/api/v1/order",
                                 instruction="orderQuery", params=params)
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                # 2. 活跃库查不到，尝试从历史库中搜寻该订单
                try:
                    history = await self.get_order_history(symbol=symbol, limit=50)
                    for h_order in history:
                        if str(h_order.get('id') or h_order.get('orderId')) == str(order_id):
                            logger.debug(f"【API】在历史记录中找到订单 {order_id}, 状态: {h_order.get('status')}")
                            return h_order
                except Exception as hist_err:
                    logger.debug(f"查询历史订单失败: {hist_err}")
                
                # 3. 如果两边都查不到，再返回 NOT_FOUND
                return {
                    'orderId': order_id,
                    'status': 'NOT_FOUND',
                    'message': 'Order not found in active or history'
                }
            raise
        except Exception:
            raise

    async def get_order_history(self, symbol: str = None, limit: int = 100) -> List[Dict]:
        """获取订单历史（使用 /wapi/v1/history/orders，与 /api/v1/orders 开放订单不同）"""
        params = {"limit": limit}
        if symbol:
            params["symbol"] = symbol
        return await asyncio.to_thread(self._request, "GET", "/wapi/v1/history/orders",
                             instruction="orderHistoryQueryAll", params=params)



class WSMessageType(Enum):
    """WebSocket消息类型"""
    SUBSCRIBE = "SUBSCRIBE"   #订阅消息
    UNSUBSCRIBE = "UNSUBSCRIBE"  #取消订阅
    PING = "ping" #心跳ping
    PONG = "pong" #心跳pong响应


@dataclass
class WSStream:
    """WebSocket流定义
    表示一个WebSocket数据流
    如：
    - ticker.BTC_USDC
    - depth.BTC_USDC
    - kline.1m.BTC_USDC
    - account.orderUpdate

    """
    name: str   #流名称，如：ticker，depth，kline
    symbol: Optional[str] = None  #交易对，可选
    interval: Optional[str] = None #时间间隔（仅k、线需要）
    is_private: bool = False  #是否为私有流

    def __str__(self) -> str:
        """转换为流名称字符串"""
        if self.interval:
            #kline流格式：kline.1m.BTC_usdc
            return f"{self.name}.{self.interval}.{self.symbol}"
        elif self.symbol:
            return f"{self.name}.{self.symbol}"
        else:
            return self.name

    @classmethod
    def from_string(cls, stream_str: str) -> 'WSStream':
        """从字符串解析流"""
        parts = stream_str.split('.')   #按点分割

        if len(parts) == 1:
            #格式:liquidation
            return cls(name=parts[0])
        elif len(parts) == 2:
            return cls(name=parts[0], symbol=parts[1])
        elif len(parts) == 3:
            return cls(name=parts[0], interval=parts[1], symbol=parts[2])
        else:
            raise ValueError(f"Invalid stream format: {stream_str}")


class BackpackWebSocketClient:
    """Backpack Exchange WebSocket客户端"""

    def __init__(self,
                 ws_url: str = "wss://ws.backpack.exchange",
                 private_key: bytes = None,
                 public_key: bytes = None,
                 reconnect_interval: int = 5,
                 heartbeat_interval: int = 30,
                 max_reconnect_attempts: int = 10):
        """
               初始化WebSocket客户端

               Args:
                   ws_url: WebSocket服务器URL
                   private_key: ED25519私钥（字节）
                   public_key: ED25519公钥（字节）
                   reconnect_interval: 重连间隔（秒）
                   heartbeat_interval: 心跳间隔（秒）
                   max_reconnect_attempts: 最大重连次数
               """

        self.ws_url = ws_url
        self.private_key = private_key
        self.public_key = public_key
        self.reconnect_interval = reconnect_interval
        self.heartbeat_interval = heartbeat_interval
        self.max_reconnect_attempts = max_reconnect_attempts

        # 连接状态
        self.websocket = None
        self.connected = False
        self.reconnect_attempts = 0
        self.last_pong = None

        # 订阅管理
        self.subscriptions = set()  # 当前订阅的流
        self.pending_subscriptions = set()  # 待订阅的流
        self.callbacks = defaultdict(list)  # 回调函数

        # 消息队列
        self.message_queue = Queue(maxsize=1000)

        # 线程和任务
        self.heartbeat_task = None  #心跳任务
        self.message_handler_task = None #消息处理任务
        self.reconnect_task = None #重连任务
        self.event_loop = None #事件循环

    async def connect(self):
        """连接到WebSocket服务器"""
        try:
            logger.info(f"正在连接到WebSocket: {self.ws_url}")

            # --- 【新增】自适应代理支持 ---
            import os
            proxy_url = os.environ.get('HTTPS_PROXY') or os.environ.get('http_proxy') or os.environ.get('HTTP_PROXY')
            # ---------------------------

            # 创建连接
            self.websocket = await websockets.connect(
                self.ws_url,
                ping_interval=None,  # 禁用自动ping
                close_timeout=10,
                max_size=2 ** 23,  # 8MB
                proxy=proxy_url    # 【新增】通过代理连接
            )

            self.connected = True
            self.reconnect_attempts = 0
            logger.info("WebSocket连接成功")

            # 启动心跳任务
            self.heartbeat_task = asyncio.create_task(self._heartbeat())

            # 启动消息处理任务
            self.message_handler_task = asyncio.create_task(self._message_handler())

            # 恢复之前的订阅
            if self.subscriptions:
                await self._resubscribe()

            return True

        except Exception as e:
            logger.error(f"WebSocket连接失败: {e}")
            await self._handle_reconnect()
            return False

    async def _handle_reconnect(self):
        """处理重连逻辑"""
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            logger.error("达到最大重连次数，停止重连")
            return

        self.reconnect_attempts += 1
        wait_time = min(self.reconnect_interval * (2 ** (self.reconnect_attempts - 1)), 60)

        logger.info(f"{wait_time}秒后尝试重连... (尝试 {self.reconnect_attempts}/{self.max_reconnect_attempts})")
        await asyncio.sleep(wait_time)

        try:
            await self.connect()
        except Exception as e:
            logger.error(f"重连失败: {e}")

    async def _heartbeat(self):
        """心跳检测"""
        while self.connected:
            try:
                # 发送ping
                if self.websocket:
                    await self.websocket.ping()
                    logger.debug("发送ping")

                # 检查pong响应
                if self.last_pong and time.time() - self.last_pong > self.heartbeat_interval * 2:
                    logger.warning("心跳超时，重新连接")
                    await self._close_and_reconnect()

                await asyncio.sleep(self.heartbeat_interval)

            except Exception as e:
                logger.error(f"心跳任务错误: {e}")
                await self._close_and_reconnect()
                break

    async def _message_handler(self):
        """处理接收到的消息"""
        while self.connected:
            try:
                if not self.websocket:
                    await asyncio.sleep(1)
                    continue

                message = await self.websocket.recv()
                await self._process_message(message)

            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"WebSocket连接已关闭: {e}")
                self.connected = False
                await self._handle_reconnect()
                break

            except Exception as e:
                logger.error(f"消息处理错误: {e}")
                await asyncio.sleep(1)

    async def _process_message(self, message: str):
        """处理单条消息"""
        try:
            data = json.loads(message)   #解析为json

            # 处理pong响应
            if isinstance(data, str) and data == "pong":
                self.last_pong = time.time()
                logger.debug("收到pong")
                return

            # 处理结构化消息
            stream = data.get("stream")
            message_data = data.get("data", {})

            if stream:
                # 调用对应的回调函数
                await self._call_callbacks(stream, message_data)

                # 记录日志
                if stream.startswith("account."):
                    logger.debug(f"收到私有流消息 [{stream}]")
                else:
                    logger.debug(f"收到公共流消息 [{stream}]: {json.dumps(message_data)[:200]}...")
            else:
                logger.warning(f"收到无流标识的消息: {message}")

        except json.JSONDecodeError:
            logger.error(f"JSON解析失败: {message}")
        except Exception as e:
            logger.error(f"处理消息异常: {e}")

    async def _call_callbacks(self, stream: str, data: Dict):
        """调用回调函数"""
        if stream in self.callbacks:
            for callback in self.callbacks[stream]:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(stream, data)
                    else:
                        # 如果是同步函数，在线程池中执行
                        loop = asyncio.get_event_loop()
                        await loop.run_in_executor(None, callback, stream, data)
                except Exception as e:
                    logger.error(f"回调函数执行错误 [{stream}]: {e}")

    async def subscribe(self, streams: List[str]):
        """订阅数据流"""
        if not self.connected:
            logger.warning("WebSocket未连接，添加到待订阅列表")
            self.pending_subscriptions.update(streams)
            return

        try:
            # 分离私有流和公共流
            private_streams = [s for s in streams if s.startswith("account.")]
            public_streams = [s for s in streams if not s.startswith("account.")]

            # 订阅公共流
            if public_streams:
                await self._send_subscribe(public_streams)
                self.subscriptions.update(public_streams)
                logger.info(f"已订阅公共流: {public_streams}")

            # 订阅私有流（需要签名）
            if private_streams:
                for stream in private_streams:
                    await self._send_private_subscribe(stream)
                    self.subscriptions.add(stream)
                    logger.info(f"已订阅私有流: {stream}")

        except Exception as e:
            logger.error(f"订阅失败: {e}")

    async def _send_subscribe(self, streams: List[str]):
        """发送订阅请求"""
        message = {
            "method": "SUBSCRIBE",
            "params": streams
        }
        await self.websocket.send(json.dumps(message))

    async def _send_private_subscribe(self, stream: str):
        """发送私有流订阅请求（需要签名）"""
        if not self.private_key or not self.public_key:
            raise ValueError("私有流订阅需要提供API密钥")

        # 生成签名
        timestamp = int(time.time() * 1000)
        window = 5000

        # 构建签名字符串
        sign_str = f"instruction=subscribe&timestamp={timestamp}&window={window}"

        # 使用ED25519签名
        from cryptography.hazmat.primitives.asymmetric import ed25519

        private_key = ed25519.Ed25519PrivateKey.from_private_bytes(self.private_key)
        signature = private_key.sign(sign_str.encode())
        signature_b64 = base64.b64encode(signature).decode()
        public_key_b64 = base64.b64encode(self.public_key).decode()

        # 构建订阅消息
        message = {
            "method": "SUBSCRIBE",
            "params": [stream],
            "signature": [
                public_key_b64,
                signature_b64,
                str(timestamp),
                str(window)
            ]
        }

        await self.websocket.send(json.dumps(message))

    async def unsubscribe(self, streams: List[str]):
        """取消订阅"""
        if not self.connected:
            logger.warning("WebSocket未连接，无法取消订阅")
            return

        try:
            message = {
                "method": "UNSUBSCRIBE",
                "params": streams
            }
            await self.websocket.send(json.dumps(message))

            # 更新订阅列表
            for stream in streams:
                self.subscriptions.discard(stream)
                self.pending_subscriptions.discard(stream)

            logger.info(f"已取消订阅: {streams}")

        except Exception as e:
            logger.error(f"取消订阅失败: {e}")

    async def _resubscribe(self):
        """重新订阅所有流"""
        if not self.subscriptions:
            return

        logger.info(f"重新订阅 {len(self.subscriptions)} 个流")
        await self.subscribe(list(self.subscriptions))

    def register_callback(self, stream: str, callback: Callable):
        """注册回调函数"""
        self.callbacks[stream].append(callback)
        logger.debug(f"已为流 [{stream}] 注册回调函数")

    def unregister_callback(self, stream: str, callback: Callable = None):
        """注销回调函数"""
        if callback:
            if callback in self.callbacks[stream]:
                self.callbacks[stream].remove(callback)
        else:
            self.callbacks[stream].clear()

    async def close(self):
        """关闭连接"""
        self.connected = False

        # 取消任务
        if self.heartbeat_task:
            self.heartbeat_task.cancel()
        if self.message_handler_task:
            self.message_handler_task.cancel()

        # 关闭WebSocket连接
        if self.websocket:
            await self.websocket.close()
            self.websocket = None

        logger.info("WebSocket连接已关闭")

    async def _close_and_reconnect(self):
        """关闭并重新连接"""
        await self.close()
        await self._handle_reconnect()

    # ==================== 工具方法 ====================

    def get_subscribed_streams(self) -> List[str]:
        """获取当前订阅的所有流"""
        return list(self.subscriptions)

    def is_subscribed(self, stream: str) -> bool:
        """检查是否已订阅某个流"""
        return stream in self.subscriptions

    def clear_subscriptions(self):
        """清除所有订阅"""
        self.subscriptions.clear()
        self.pending_subscriptions.clear()
        logger.info("已清除所有订阅")


# ==================== 流定义工具 ====================

def create_streams(symbols: List[str],
                   stream_types: List[str] = None,
                   intervals: List[str] = None) -> List[str]:
    """
    创建流列表

    Args:
        symbols: 交易对列表，如 ["BTC_USDC", "ETH_USDC"]
        stream_types: 流类型列表，默认包含所有公共流
        intervals: K线间隔列表，如 ["1m", "5m", "1h"]

    Returns:
        流名称列表
    """
    if stream_types is None:
        stream_types = ["ticker", "depth", "trade", "markPrice", "openInterest"]

    streams = []

    for symbol in symbols:
        for stream_type in stream_types:
            if stream_type in ["ticker", "depth", "trade", "markPrice", "openInterest"]:
                streams.append(f"{stream_type}.{symbol}")
            elif stream_type == "kline" and intervals:
                for interval in intervals:
                    streams.append(f"kline.{interval}.{symbol}")
            elif stream_type == "liquidation":
                streams.append("liquidation")

    return streams


def create_private_streams(symbols: List[str] = None,
                           stream_types: List[str] = None) -> List[str]:
    """
    创建私有流列表

    Args:
        symbols: 交易对列表，如果为None则订阅所有市场
        stream_types: 私有流类型，默认 ["orderUpdate", "positionUpdate"]

    Returns:
        私有流名称列表
    """
    if stream_types is None:
        stream_types = ["orderUpdate", "positionUpdate", "rfqUpdate"]

    streams = []

    for stream_type in stream_types:
        if symbols:
            for symbol in symbols:
                streams.append(f"account.{stream_type}.{symbol}")
        else:
            streams.append(f"account.{stream_type}")

    return streams


# ==================== 使用示例 ====================

async def example_usage():
    """使用示例"""

    # 初始化客户端
    ws_client = BackpackWebSocketClient(
        ws_url="wss://ws.backpack.exchange",
        private_key=base64.b64decode("your_private_key_base64"),
        public_key=base64.b64decode("your_public_key_base64")
    )

    # 定义回调函数
    def on_ticker(stream: str, data: Dict):
        print(f"收到ticker数据 [{stream}]: {data}")

    def on_order_update(stream: str, data: Dict):
        print(f"收到订单更新 [{stream}]: {data}")

    # 注册回调
    ws_client.register_callback("ticker.BTC_USDC", on_ticker)
    ws_client.register_callback("account.orderUpdate", on_order_update)

    # 创建订阅列表
    symbols = ["BTC_USDC", "ETH_USDC"]

    # 订阅公共流
    public_streams = create_streams(
        symbols=symbols,
        stream_types=["ticker", "depth", "trade"],
        intervals=["1m", "5m"]
    )

    # 订阅私有流
    private_streams = create_private_streams(
        symbols=symbols,
        stream_types=["orderUpdate", "positionUpdate"]
    )

    # 连接并订阅
    await ws_client.connect()

    # 先订阅公共流
    await ws_client.subscribe(public_streams)

    # 等待连接稳定后再订阅私有流
    await asyncio.sleep(2)
    await ws_client.subscribe(private_streams)

    try:
        # 保持连接运行
        while True:
            await asyncio.sleep(1)

            # 可以动态添加/删除订阅
            # await ws_client.subscribe(["ticker.SOL_USDC"])
            # await ws_client.unsubscribe(["ticker.BTC_USDC"])

    except KeyboardInterrupt:
        print("用户中断")
    finally:
        await ws_client.close()


# ==================== 集成到BackpackAPIClient ====================

class EnhancedBackpackAPIClient(BackpackAPIClient):
    """增强的Backpack API客户端，包含完整WebSocket功能"""

    def __init__(self):
        super().__init__()

        # 初始化WebSocket客户端
        self.ws_client = BackpackWebSocketClient(
            ws_url="wss://ws.backpack.exchange",
            private_key=self.private_key,
            public_key=self.public_key
        )

        self._ws_connected = False

    async def connect_websocket(self) -> bool:
        """连接WebSocket"""
        try:
            self._ws_connected = await self.ws_client.connect()
            return self._ws_connected
        except Exception as e:
            logger.error(f"连接WebSocket失败: {e}")
            return False

    def subscribe_ws(self, streams: List[str], callback: Callable = None):
        """订阅WebSocket流（异步方法）"""
        if not self._ws_connected:
            logger.warning("WebSocket未连接")
            return

        # 如果有回调函数，先注册
        if callback:
            for stream in streams:
                self.ws_client.register_callback(stream, callback)

        # 异步订阅
        asyncio.create_task(self.ws_client.subscribe(streams))

    def register_ws_callback(self, stream: str, callback: Callable):
        """注册WebSocket回调"""
        self.ws_client.register_callback(stream, callback)

    async def disconnect_websocket(self):
        """断开WebSocket连接"""
        await self.ws_client.close()
        self._ws_connected = False

    def is_websocket_connected(self) -> bool:
        """检查WebSocket连接状态"""
        return self._ws_connected and self.ws_client.connected


# ==================== 事件处理器示例 ====================

class WebSocketEventHandler:
    """WebSocket事件处理器"""

    def __init__(self, trading_engine=None):
        self.trading_engine = trading_engine
        self.order_book = {}
        self.tickers = {}
        self.positions = {}

    async def handle_order_update(self, stream: str, data: Dict):
        """处理订单更新"""
        event_type = data.get("e")
        symbol = data.get("s")
        order_id = data.get("i")

        logger.info(f"订单更新: {event_type} - {symbol} - {order_id}")

        if self.trading_engine:
            # 通知交易引擎
            await self.trading_engine.on_order_update(data)

        # 记录到数据库
        self._save_order_update(data)

    async def handle_position_update(self, stream: str, data: Dict):
        """处理仓位更新"""
        symbol = data.get("s")
        quantity = float(data.get("q", 0))
        unrealized_pnl = float(data.get("P", 0))

        self.positions[symbol] = {
            "quantity": quantity,
            "unrealized_pnl": unrealized_pnl,
            "timestamp": time.time()
        }

        logger.info(f"仓位更新: {symbol} - 数量: {quantity} - 未实现盈亏: {unrealized_pnl}")

    async def handle_ticker(self, stream: str, data: Dict):
        """处理ticker数据"""
        symbol = data.get("s")
        last_price = float(data.get("c", 0))

        if symbol not in self.tickers:
            self.tickers[symbol] = {
                "prices": [],
                "timestamps": []
            }

        # 保留最近100个价格
        self.tickers[symbol]["prices"].append(last_price)
        self.tickers[symbol]["timestamps"].append(time.time())

        if len(self.tickers[symbol]["prices"]) > 100:
            self.tickers[symbol]["prices"].pop(0)
            self.tickers[symbol]["timestamps"].pop(0)

    async def handle_depth(self, stream: str, data: Dict):
        """处理深度数据"""
        symbol = data.get("s")
        bids = data.get("b", [])
        asks = data.get("a", [])

        if symbol not in self.order_book:
            self.order_book[symbol] = {"bids": {}, "asks": {}}

        # 更新买单
        for bid in bids:
            price = float(bid[0])
            quantity = float(bid[1])
            if quantity > 0:
                self.order_book[symbol]["bids"][price] = quantity
            else:
                self.order_book[symbol]["bids"].pop(price, None)

        # 更新卖单
        for ask in asks:
            price = float(ask[0])
            quantity = float(ask[1])
            if quantity > 0:
                self.order_book[symbol]["asks"][price] = quantity
            else:
                self.order_book[symbol]["asks"].pop(price, None)

        # 计算指标
        best_bid = max(self.order_book[symbol]["bids"].keys()) if self.order_book[symbol]["bids"] else 0
        best_ask = min(self.order_book[symbol]["asks"].keys()) if self.order_book[symbol]["asks"] else 0

        if best_bid and best_ask:
            spread = best_ask - best_bid
            spread_percent = (spread / best_bid) * 100

            logger.debug(f"深度更新: {symbol} - 买一: {best_bid} - 卖一: {best_ask} - 价差: {spread_percent:.2f}%")

    def _save_order_update(self, data: Dict):
        """保存订单更新到数据库"""
        # 这里可以集成到数据库
        pass


# ==================== 异步启动器 ====================

async def start_websocket_service(config: Dict = None):
    """启动WebSocket服务"""

    # 创建事件处理器
    event_handler = WebSocketEventHandler()

    # 创建WebSocket客户端
    ws_client = BackpackWebSocketClient(
        ws_url=config.get("ws_url", "wss://ws.backpack.exchange"),
        private_key=base64.b64decode(config.get("private_key", "")),
        public_key=base64.b64decode(config.get("public_key", ""))
    )

    # 注册事件处理器
    ws_client.register_callback("account.orderUpdate", event_handler.handle_order_update)
    ws_client.register_callback("account.positionUpdate", event_handler.handle_position_update)
    ws_client.register_callback("ticker.*", event_handler.handle_ticker)
    ws_client.register_callback("depth.*", event_handler.handle_depth)

    # 订阅流
    symbols = config.get("symbols", ["BTC_USDC", "ETH_USDC"])

    # 公共流
    public_streams = create_streams(
        symbols=symbols,
        stream_types=["ticker", "depth", "trade"],
        intervals=["1m", "5m"]
    )

    # 私有流
    private_streams = create_private_streams(symbols=symbols)

    # 连接
    await ws_client.connect()

    # 订阅
    await ws_client.subscribe(public_streams)
    await asyncio.sleep(2)
    await ws_client.subscribe(private_streams)

    logger.info("WebSocket服务已启动")

    # 保持运行
    try:
        while True:
            await asyncio.sleep(10)

            # 定期检查连接状态
            if not ws_client.connected:
                logger.warning("WebSocket连接断开，尝试重连...")
                await ws_client.connect()

    except KeyboardInterrupt:
        logger.info("正在关闭WebSocket服务...")
    except Exception as e:
        logger.error(f"WebSocket服务异常: {e}")
    finally:
        await ws_client.close()
        logger.info("WebSocket服务已关闭")


if __name__ == "__main__":
    import asyncio

    # 配置
    config = {
        "ws_url": "wss://ws.backpack.exchange",
        "private_key": "your_private_key_base64",
        "public_key": "your_public_key_base64",
        "symbols": ["BTC_USDC", "ETH_USDC"]
    }

    # 启动服务
    asyncio.run(start_websocket_service(config))