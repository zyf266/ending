import time
import hmac
import hashlib
import base64
import json
import logging
import asyncio
import aiohttp
from datetime import datetime
from typing import Dict, Any, Optional, List
from urllib.parse import urlencode

from .api_client import BackpackAPIClient
from ..config.settings import config

logger = logging.getLogger(__name__)

class DeepcoinAPIClient:
    """Deepcoin API 客户端，实现 ExchangeClient 协议"""
    
    def __init__(self, api_key: str = None, secret_key: str = None, passphrase: str = None):
        self.base_url = config.deepcoin.API_BASE_URL
        self.api_key = api_key or config.deepcoin.API_KEY
        self.secret_key = secret_key or config.deepcoin.SECRET_KEY
        self.passphrase = passphrase or config.deepcoin.PASSPHRASE
        self.session: Optional[aiohttp.ClientSession] = None
        self.debug = False  # 调试模式标志
        
        # 内部行情客户端，固定使用 Backpack (根据用户需求)
        self.data_client = BackpackAPIClient()
        
    async def get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    async def close_session(self):
        if self.session and not self.session.closed:
            await self.session.close()
        await self.data_client.close_session()

    def _generate_signature(self, timestamp: str, method: str, request_path: str, body: str = "") -> str:
        """生成签名"""
        message = timestamp + method + request_path + body
        mac = hmac.new(
            bytes(self.secret_key, encoding='utf8'),
            bytes(message, encoding='utf8'),
            digestmod=hashlib.sha256
        )
        return base64.b64encode(mac.digest()).decode()
    
    def _get_headers(self, method: str, request_path: str, body: str = "", auth: bool = True) -> Dict[str, str]:
        """获取请求头"""
        if not auth:
            return {'Content-Type': 'application/json'}
            
        timestamp = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
        signature = self._generate_signature(timestamp, method, request_path, body)
        
        return {
            'DC-ACCESS-KEY': self.api_key,
            'DC-ACCESS-SIGN': signature,
            'DC-ACCESS-TIMESTAMP': timestamp,
            'DC-ACCESS-PASSPHRASE': self.passphrase,
            'Content-Type': 'application/json'
        }
    
    def _map_symbol(self, symbol: str) -> str:
        """将 Backpack 格式转换为 Deepcoin 格式
        例如: ETH_USDC_PERP -> ETH-USDC-SWAP
        """
        if not symbol:
            return symbol
        
        # 如果已经是 Deepcoin 格式，直接返回
        if "-" in symbol and ("-SWAP" in symbol or "-SPOT" in symbol):
            return symbol
            
        mapped = symbol.replace("_", "-")
        if mapped.endswith("-PERP"):
            mapped = mapped.replace("-PERP", "-SWAP")
        elif "-SWAP" not in mapped and "-SPOT" not in mapped:
            # 默认假设是 SWAP 如果没有指定
            mapped = f"{mapped}-SWAP"
            
        return mapped

    def _unmap_symbol(self, symbol: str) -> str:
        """将 Deepcoin 格式转换回 Backpack 格式
        例如: ETH-USDC-SWAP -> ETH_USDC_PERP
        """
        if not symbol:
            return symbol
            
        # 如果包含 SWAP，转换为 PERP 并替换 - 为 _
        if "-SWAP" in symbol:
            unmapped = symbol.replace("-SWAP", "_PERP")
            unmapped = unmapped.replace("-", "_")
            return unmapped
        
        # 如果包含 SPOT，去掉并替换 - 为 _
        if "-SPOT" in symbol:
            unmapped = symbol.replace("-SPOT", "")
            unmapped = unmapped.replace("-", "_")
            return unmapped
            
        # 如果没有特殊后缀，尝试直接转换
        return symbol.replace("-", "_")

    async def _request(self, method: str, endpoint: str, params: Optional[Dict] = None, 
                       data: Optional[Dict] = None) -> Dict[str, Any]:
        """发送异步请求"""
        session = await self.get_session()
        
        # 判定是否需要认证
        is_auth_required = endpoint.startswith("/deepcoin/account") or \
                          endpoint.startswith("/deepcoin/trade") or \
                          endpoint.startswith("/deepcoin/asset")
        
        # 构造完整的 URL 和 用于签名的 request_path
        if method == "GET" and params:
            # 关键：对参数进行排序，并过滤掉 None 值，以保证签名一致性
            clean_params = {k: str(v) for k, v in sorted(params.items()) if v is not None}
            query_string = urlencode(clean_params)
            request_path = f"{endpoint}?{query_string}"
            url = f"{self.base_url}{request_path}"
            body = ""
        else:
            request_path = endpoint
            url = f"{self.base_url}{endpoint}"
            # 关键：使用 separators=(',', ':') 确保 JSON 紧凑无空格，与大多数 API 签名预期一致
            body = json.dumps(data, separators=(',', ':')) if data else ""
        
        headers = self._get_headers(method, request_path, body, auth=is_auth_required)
        
        try:
            logger.debug(f"Deepcoin Request: {method} {url} params={params} data={data}")
            
            # 核心修正：避免 aiohttp 再次对 url 中的参数进行编码
            # 我们直接控制 URL 和 Body 字符串
            request_kwargs = {
                "headers": headers,
                "timeout": 15
            }
            if method != "GET" and body:
                request_kwargs["data"] = body
                headers["Content-Type"] = "application/json"
            
            async with session.request(method, url, **request_kwargs) as response:
                if response.status == 429:
                    logger.warning(f"Rate limit hit on {endpoint}")
                    return {"code": "429", "msg": "Rate limit exceeded"}
                
                response_text = await response.text()
                try:
                    result = json.loads(response_text)
                except json.JSONDecodeError:
                    logger.error(f"Deepcoin 返回了非 JSON 数据: {response_text}")
                    return {"code": "-1", "msg": "Invalid JSON response", "data": None}
                
                if self.debug:
                    logger.debug(f"Deepcoin Response: {result}")
                
                if result.get("code") != "0":
                    logger.error(f"Deepcoin API Error: {result.get('msg')}, code: {result.get('code')}")
                    return result
                
                return result.get("data", {})
        except Exception as e:
            logger.error(f"Deepcoin Request failed: {endpoint}, error: {str(e)}")
            return {"code": "-1", "msg": str(e)}

    # ========== 市场数据接口 (优先使用 Deepcoin 原生接口以确保准确性) ==========
    async def get_markets(self) -> Dict[str, Dict]:
        """获取所有市场"""
        data = await self._request("GET", "/deepcoin/market/instruments", params={"instType": "SWAP"})
        markets = {}
        if isinstance(data, list):
            for item in data:
                # 转换 Deepcoin 格式回系统内部格式 (Backpack 风格)
                unmapped_symbol = self._unmap_symbol(item.get("instId"))
                native_symbol = item.get("instId")
                
                market_info = {
                    "symbol": unmapped_symbol,
                    "native_symbol": native_symbol,
                    "baseAsset": item.get("baseCcy"),
                    "quoteAsset": item.get("quoteCcy"),
                    "priceTick": item.get("tickSz"),
                    "lotSize": item.get("lotSz"),
                    "minQuantity": item.get("minSz"),
                    "raw": item
                }
                # 同时也支持使用原生名称和解映射后的名称进行查找
                markets[unmapped_symbol] = market_info
                if native_symbol != unmapped_symbol:
                    markets[native_symbol] = market_info
                    
        return markets

    async def get_ticker(self, symbol: str) -> Dict:
        """获取 Ticker 数据"""
        params = {"instType": "SWAP", "instId": self._map_symbol(symbol)}
        data = await self._request("GET", "/deepcoin/market/tickers", params=params)
        
        # 【新增调试日志】记录API返回的原始数据
        logger.debug(f"🔍 [Deepcoin Ticker] 请求: {symbol} -> {self._map_symbol(symbol)}")
        logger.debug(f"🔍 [Deepcoin Ticker] API返回: {data}")
        
        if isinstance(data, list) and len(data) > 0:
            ticker = data[0]
            result = {
                "symbol": symbol,
                "lastPrice": ticker.get("last"),
                "highPrice": ticker.get("high24h"),
                "lowPrice": ticker.get("low24h"),
                "volume": ticker.get("vol24h"),
                "quoteVolume": ticker.get("volCcy24h"),
                "ts": ticker.get("ts")
            }
            logger.info(f"✅ [Deepcoin Ticker] {symbol} 最新价格: {result.get('lastPrice')}")
            return result
        
        logger.warning(f"⚠️ [Deepcoin Ticker] {symbol} 未返回数据")
        return {}

    async def get_depth(self, symbol: str, limit: int = 100) -> Dict:
        """获取深度数据"""
        params = {"instId": self._map_symbol(symbol), "sz": min(limit, 400)}
        data = await self._request("GET", "/deepcoin/market/books", params=params)
        
        if isinstance(data, dict):
            return {
                "bids": data.get("bids", []),
                "asks": data.get("asks", [])
            }
        return {"bids": [], "asks": []}

    async def get_klines(self, symbol: str, interval: str, start_time: Optional[int] = None, end_time: Optional[int] = None, limit: int = 100) -> List[List]:
        """获取 K 线数据"""
        # 映射时间粒度
        bar_map = {
            "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
            "1h": "1H", "4h": "4H", "1d": "1D", "1w": "1W"
        }
        params = {
            "instId": self._map_symbol(symbol),
            "bar": bar_map.get(interval, "1m"),
            "limit": min(limit, 300)
        }
        # Deepcoin 使用 after 获取更早的数据，如果没有 after 则返回最新的
        # 如果我们需要特定时间段，逻辑会更复杂，但对于冷启动拉取 100 条，直接请求即可
        data = await self._request("GET", "/deepcoin/market/candles", params=params)
        
        if isinstance(data, list):
            # Deepcoin 返回的是最新到最旧，策略引擎通常期望最旧到最新，所以需要反转
            return data[::-1]
        return []

    async def get_server_time(self) -> int:
        """获取服务器时间"""
        data = await self._request("GET", "/deepcoin/market/time")
        if isinstance(data, dict) and data.get("ts"):
            return int(data["ts"])
        return int(time.time() * 1000)

    # ========== 账户与持仓接口 (Deepcoin) ==========
    async def get_account(self) -> Dict:
        """获取账户信息"""
        return await self._request("GET", "/deepcoin/account/account-info")

    async def get_balances(self) -> Dict[str, Dict]:
        """获取余额 (映射为协议要求的格式)"""
        balances = await self.get_balance()
        # 协议期望: {asset: {available: float, locked: float}}
        result = {}
        for bal in balances:
            asset = bal.get("asset")
            if asset:
                result[asset] = {
                    "available": float(bal.get("available", 0)),
                    "locked": float(bal.get("locked", 0))
                }
        return result

    async def get_balance(self, ccy: str = None) -> List[Dict]:
        """获取余额列表"""
        params = {"instType": "SWAP"}
        if ccy:
            params["ccy"] = ccy
        data = await self._request("GET", "/deepcoin/account/balances", params=params)
        
        # 兼容协议要求的格式: [{asset, available, locked}]
        result = []
        if isinstance(data, list):
            for item in data:
                asset_name = item.get("ccy")
                if asset_name:
                    result.append({
                        "asset": asset_name,
                        "available": float(item.get("availBal", 0)),
                        "locked": float(item.get("frozenBal", 0))
                    })
        elif isinstance(data, dict) and data.get("ccy"):
             result.append({
                    "asset": data.get("ccy"),
                    "available": float(data.get("availBal", 0)),
                    "locked": float(data.get("frozenBal", 0))
                })
        
        if not result:
            logger.warning(f"Deepcoin get_balance returned no results for {params}. Raw data: {data}")
            
        return result
    
    async def get_positions(self, symbol: Optional[str] = None) -> List[Dict]:
        """获取持仓列表"""
        params = {"instType": "SWAP"}
        if symbol:
            params["instId"] = self._map_symbol(symbol)
        data = await self._request("GET", "/deepcoin/account/positions", params=params)
        
        # 转换 Deepcoin 格式为协议通用格式
        # 协议期望包含: symbol, side, quantity, entry_price, markPrice, unrealizedPnl
        positions = []
        if isinstance(data, list):
            for p in data:
                positions.append({
                    "symbol": p.get("instId"),
                    "side": p.get("posSide", "long").lower(),
                    "quantity": abs(float(p.get("pos", 0))),
                    "entryPrice": float(p.get("avgPx", 0)),
                    "markPrice": float(p.get("markPx", 0)),
                    "pnlUnrealized": float(p.get("upl", 0)),
                    "pnlRealized": float(p.get("realizedPnl", 0))
                })
        return positions

    # ========== 交易接口 (Deepcoin) ==========
    async def place_order(self, order_data: Dict) -> Dict:
        """底层下单接口"""
        return await self._request("POST", "/deepcoin/trade/order", data=order_data)

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
        """执行订单 (适配实盘引擎)"""
        # 将协议参数映射到 Deepcoin API
        # side: buy/sell
        # ordType: market/limit
        mapped_symbol = self._map_symbol(symbol)
        data = {
            "instId": mapped_symbol,
            "tdMode": config.deepcoin.DEFAULT_MARGIN_MODE,
            "side": side.lower(),
            "ordType": order_type.lower(),
            "sz": str(quantity),
            "posSide": "long" if side.lower() == "buy" else "short", # 默认单向开仓逻辑
            "mrgPosition": config.deepcoin.DEFAULT_MERGE_POSITION,
            "reduceOnly": reduce_only
        }
        
        # 处理平仓时的方向逻辑：如果是平多(Sell + reduce_only)，posSide 应为 long
        if reduce_only:
            data["posSide"] = "long" if side.lower() == "sell" else "short"

        if price:
            data["px"] = str(price)
            
        res = await self.place_order(data)
        
        # 返回适配 _parse_order_response 的格式
        if res.get('ordId'):
            return {
                "id": res['ordId'],
                "symbol": symbol,
                "side": "Bid" if side.lower() == "buy" else "Ask",
                "orderType": order_type.capitalize(),
                "quantity": str(quantity),
                "price": str(price) if price else "0",
                "status": "New",
                "createdAt": int(time.time() * 1000),
                "executedQuantity": "0",
                "commission": "0"
            }
        raise Exception(f"Deepcoin Order Failed: {res.get('msg', 'Unknown error')}")

    async def cancel_order(self, symbol: str, order_id: Optional[str] = None, client_id: Optional[str] = None) -> Dict:
        data = {"instId": self._map_symbol(symbol), "ordId": order_id}
        return await self._request("POST", "/deepcoin/trade/cancel-order", data=data)

    async def cancel_all_orders(self, symbol: Optional[str] = None) -> Dict:
        # Deepcoin 没有直接的 cancel_all，需要先获取 pending 列表再批量取消
        pending = await self.get_open_orders(symbol)
        results = []
        for order in pending:
            res = await self.cancel_order(order.get("symbol"), order.get("orderId"))
            results.append(res)
        return {"status": "success", "results": results}

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict]:
        params = {
            "limit": 100,
            "index": "1"  # 【关键修复】Deepcoin API必填参数，默认1表示从第一页开始
        }
        if symbol:
            params["instId"] = self._map_symbol(symbol)
        data = await self._request("GET", "/deepcoin/trade/v2/orders-pending", params=params)
        
        orders = []
        if isinstance(data, list):
            for o in data:
                orders.append({
                    "id": o.get("ordId"),
                    "symbol": self._unmap_symbol(o.get("instId")),
                    "side": "Bid" if o.get("side") == "buy" else "Ask",
                    "orderType": o.get("ordType", "").capitalize(),
                    "quantity": o.get("sz"),
                    "price": o.get("px"),
                    "status": "New",
                    "createdAt": int(o.get("cTime", time.time()*1000)),
                    "executedQuantity": o.get("accFillSz", "0"),
                    "commission": "0"
                })
        return orders

    async def get_order(self, order_id: str, symbol: Optional[str] = None) -> Dict:
        """获取单个订单"""
        if not symbol:
            logger.warning("get_order called without symbol, Deepcoin requires instId")
            return {}
            
        params = {
            "instId": self._map_symbol(symbol),
            "ordId": order_id
        }
        # 尝试从活跃订单查询
        res = await self._request("GET", "/deepcoin/trade/orderByID", params=params)
        
        # 如果活跃订单没找到，尝试从历史订单查询
        if not res or (isinstance(res, list) and len(res) == 0):
             res = await self._request("GET", "/deepcoin/trade/finishOrderByID", params=params)

        order_data = None
        if isinstance(res, list) and len(res) > 0:
            order_data = res[0]
        elif isinstance(res, dict) and res.get("ordId"):
            order_data = res
            
        if order_data:
            state = order_data.get("state", "").lower()
            status = "New"
            if state == "filled":
                status = "Filled"
            elif state == "canceled":
                status = "Cancelled"
            elif state == "partially_filled":
                status = "PartiallyFilled"

            return {
                "id": order_data["ordId"],
                "symbol": symbol,
                "side": "Bid" if order_data.get("side") == "buy" else "Ask",
                "orderType": order_data.get("ordType", "").capitalize(),
                "quantity": order_data.get("sz"),
                "price": order_data.get("px"),
                "status": status,
                "createdAt": int(order_data.get("cTime", time.time()*1000)),
                "executedQuantity": order_data.get("accFillSz", "0"),
                "commission": order_data.get("fee", "0")
            }
        return {}

    async def get_order_history(self, symbol: Optional[str] = None, limit: int = 100) -> List[Dict]:
        params = {"limit": limit}
        if symbol:
            params["instId"] = self._map_symbol(symbol)
        data = await self._request("GET", "/deepcoin/trade/fills", params=params)
        return data if isinstance(data, list) else []

