"""
币安 USD-M 合约 (USDT-M Futures) API 客户端
实现 ExchangeClient 协议，支持下单、平仓、查询持仓/余额/K线等。

文档: https://developers.binance.com/docs/derivatives/usds-margined-futures
Base URL: https://fapi.binance.com
"""
import os
import urllib.request
import time
import hmac
import hashlib
import logging
import asyncio
import aiohttp
from datetime import datetime
from typing import Dict, Any, Optional, List
from urllib.parse import urlencode

from ..config.settings import config

logger = logging.getLogger(__name__)

# 币安 USDT-M 合约 REST 基础地址
BINANCE_FAPI_BASE = "https://fapi.binance.com"
# 币安 Portfolio Margin REST 基础地址（UM 条件单用此）
BINANCE_PAPI_BASE = "https://papi.binance.com"

# 内部统一格式 -> 币安合约格式映射
# 规则: ETH_USDC_PERP / ETH_USDT_PERP / ETH/USDC / ETH -> ETHUSDT
_QUOTE_ALIASES = ["USDC", "USDT", "USD", "PERP", "SWAP"]


def _to_binance_symbol(symbol: str) -> str:
    """将内部通用交易对格式转换为币安合约符号（如 ETHUSDT）。

    支持以下输入:
      - ETH_USDC_PERP  -> ETHUSDT
      - ETH_USDT_PERP  -> ETHUSDT
      - ETH/USDC       -> ETHUSDT
      - ETHUSDT        -> ETHUSDT (已经是标准格式，直接返回)
      - ETH             -> ETHUSDT
      - HYPE            -> HYPEUSDT
    """
    s = symbol.strip().upper()

    # 已经是合约格式（不含分隔符且以 USDT/BUSD 结尾）
    if (s.endswith("USDT") or s.endswith("BUSD")) and "_" not in s and "/" not in s and "-" not in s:
        return s

    # 分割并取基础币
    for sep in ["_", "/", "-"]:
        if sep in s:
            parts = s.split(sep)
            base = parts[0]
            return f"{base}USDT"

    # 纯基础币（如 ETH、HYPE、BTC）
    return f"{s}USDT"


def _from_binance_symbol(symbol: str) -> str:
    """将币安符号（ETHUSDT）转回内部格式（ETH_USDC_PERP）。"""
    s = symbol.strip().upper()
    for suffix in ["USDT", "BUSD"]:
        if s.endswith(suffix):
            base = s[: -len(suffix)]
            return f"{base}_USDC_PERP"
    return s


class BinanceAPIClient:
    """币安 USD-M 合约 API 客户端，实现 ExchangeClient 协议。

    使用 HMAC-SHA256 签名认证。
    API Key / Secret 优先从参数传入，否则读取配置文件。
    """

    def __init__(self, api_key: str = None, secret_key: str = None):
        self.base_url = BINANCE_FAPI_BASE
        self.api_key = api_key or config.binance.API_KEY
        self.secret_key = secret_key or config.binance.SECRET_KEY
        self.session: Optional[aiohttp.ClientSession] = None
        self.recv_window = 5000  # 请求有效窗口(ms)
        # 代理支持（国内访问币安需要）
        # 优先级: 环境变量 HTTPS_PROXY / HTTP_PROXY → Windows 系统代理 → 无代理
        self.proxy = (
            os.environ.get("HTTPS_PROXY")
            or os.environ.get("https_proxy")
            or os.environ.get("HTTP_PROXY")
            or os.environ.get("http_proxy")
            or urllib.request.getproxies().get("https")
            or urllib.request.getproxies().get("http")
            or None
        )
        if self.proxy:
            logger.info(f"[Binance] 使用代理: {self.proxy}")

    # ─────────────────────────── session 管理 ───────────────────────────

    async def get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    # 兼容 HyperliquidClient 接口，供 AdaptiveLongStrategy 统一调用
    async def _get_session(self) -> aiohttp.ClientSession:
        return await self.get_session()

    async def close_session(self):
        if self.session and not self.session.closed:
            await self.session.close()

    # 兼容 HyperliquidClient 的 close() 接口
    async def close(self):
        await self.close_session()

    # ─────────────────────────── 签名 ───────────────────────────────────

    def _sign(self, params: Dict) -> str:
        """HMAC-SHA256 签名，返回 hex 字符串。"""
        query = urlencode(params)
        return hmac.new(
            self.secret_key.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _auth_headers(self) -> Dict[str, str]:
        return {
            "X-MBX-APIKEY": self.api_key,
            "Content-Type": "application/x-www-form-urlencoded",
        }

    def _add_signature(self, params: Dict) -> Dict:
        """在 params dict 中添加 timestamp 和 signature，返回新 dict。"""
        p = dict(params)
        p["timestamp"] = int(time.time() * 1000)
        p["recvWindow"] = self.recv_window
        p["signature"] = self._sign(p)
        return p

    # ─────────────────────────── HTTP 封装 ──────────────────────────────

    async def _get(self, path: str, params: Dict = None, signed: bool = False) -> Any:
        session = await self.get_session()
        p = dict(params or {})
        headers = {}
        if signed:
            headers = self._auth_headers()
            p = self._add_signature(p)
        url = f"{self.base_url}{path}"
        async with session.get(url, params=p, headers=headers, ssl=False, proxy=self.proxy) as resp:
            data = await resp.json()
            if isinstance(data, dict) and data.get("code") and data["code"] != 200:
                logger.error(f"[Binance GET] {path} error: {data}")
            return data

    async def _post(self, path: str, params: Dict = None, signed: bool = True) -> Any:
        session = await self.get_session()
        p = dict(params or {})
        headers = self._auth_headers()
        if signed:
            p = self._add_signature(p)
        url = f"{self.base_url}{path}"
        async with session.post(url, data=urlencode(p), headers=headers, ssl=False, proxy=self.proxy) as resp:
            data = await resp.json()
            if isinstance(data, dict) and data.get("code") and int(data["code"]) < 0:
                logger.error(f"[Binance POST] {path} error: {data}")
            return data

    async def _post_papi(self, path: str, params: Dict = None, signed: bool = True) -> Any:
        """Portfolio Margin 专用 POST（使用 papi.binance.com 基址）。"""
        session = await self.get_session()
        p = dict(params or {})
        headers = self._auth_headers()
        if signed:
            p = self._add_signature(p)
        url = f"{BINANCE_PAPI_BASE}{path}"
        async with session.post(url, data=urlencode(p), headers=headers, ssl=False, proxy=self.proxy) as resp:
            data = await resp.json()
            if isinstance(data, dict) and data.get("code") and int(data.get("code", 0)) < 0:
                logger.error(f"[Binance PAPI POST] {path} error: {data}")
            return data

    async def _delete(self, path: str, params: Dict = None, signed: bool = True) -> Any:
        session = await self.get_session()
        p = dict(params or {})
        headers = self._auth_headers()
        if signed:
            p = self._add_signature(p)
        url = f"{self.base_url}{path}"
        async with session.delete(url, params=p, headers=headers, ssl=False, proxy=self.proxy) as resp:
            data = await resp.json()
            return data

    # ─────────────────────────── 公共行情 ───────────────────────────────

    async def get_markets(self) -> Dict[str, Dict]:
        """获取所有合约交易对信息。"""
        data = await self._get("/fapi/v1/exchangeInfo")
        result = {}
        for s in data.get("symbols", []):
            sym = s.get("symbol", "")
            result[sym] = {
                "symbol": sym,
                "base_asset": s.get("baseAsset"),
                "quote_asset": s.get("quoteAsset"),
                "status": s.get("status"),
                "price_precision": s.get("pricePrecision"),
                "quantity_precision": s.get("quantityPrecision"),
            }
        return result

    async def get_ticker(self, symbol: str) -> Dict:
        """获取最新价格。"""
        bn_sym = _to_binance_symbol(symbol)
        data = await self._get("/fapi/v1/ticker/price", {"symbol": bn_sym})
        return {
            "symbol": symbol,
            "lastPrice": float(data.get("price", 0)),
            "price": float(data.get("price", 0)),
        }

    async def get_depth(self, symbol: str, limit: int = 20) -> Dict:
        """获取订单簿。"""
        bn_sym = _to_binance_symbol(symbol)
        data = await self._get("/fapi/v1/depth", {"symbol": bn_sym, "limit": limit})
        return {
            "bids": [[float(p), float(q)] for p, q in data.get("bids", [])],
            "asks": [[float(p), float(q)] for p, q in data.get("asks", [])],
        }

    async def get_klines(
        self,
        symbol: str,
        interval: str = "1h",
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 100,
    ) -> List[Dict]:
        """获取 K 线数据，返回统一格式列表。"""
        bn_sym = _to_binance_symbol(symbol)
        params: Dict = {"symbol": bn_sym, "interval": interval, "limit": limit}
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time
        data = await self._get("/fapi/v1/klines", params)
        result = []
        for bar in data:
            result.append({
                "time": int(bar[0]),
                "open": float(bar[1]),
                "high": float(bar[2]),
                "low": float(bar[3]),
                "close": float(bar[4]),
                "volume": float(bar[5]),
                "close_time": int(bar[6]),
            })
        return result

    async def get_server_time(self) -> int:
        """获取服务器时间（ms）。"""
        data = await self._get("/fapi/v1/time")
        return data.get("serverTime", int(time.time() * 1000))

    # ─────────────────────────── 账户 ───────────────────────────────────

    async def get_account(self) -> Dict:
        """获取账户详情。"""
        data = await self._get("/fapi/v2/account", signed=True)
        return data

    async def get_balance(self) -> List[Dict]:
        """获取余额列表（统一格式）。"""
        data = await self._get("/fapi/v2/balance", signed=True)
        if not isinstance(data, list):  # API 返回错误 dict 时抛出异常以便调用方输出详细错误
            code = data.get("code", "?") if isinstance(data, dict) else "?"
            msg  = data.get("msg",  str(data)) if isinstance(data, dict) else str(data)
            raise RuntimeError(f"[Binance API 错误] code={code} msg={msg}")
        result = []
        for item in data:
            if not isinstance(item, dict):
                continue
            result.append({
                "asset": item.get("asset"),
                "available": float(item.get("availableBalance", 0)),
                "total": float(item.get("balance", 0)),
                "locked": float(item.get("balance", 0)) - float(item.get("availableBalance", 0)),
            })
        return result

    async def get_balances(self) -> Dict[str, Dict]:
        """获取余额字典（key=asset）。"""
        items = await self.get_balance()
        return {item["asset"]: item for item in items if isinstance(item, dict) and item.get("asset")}

    async def get_usdt_balance(self) -> float:
        """获取 USDT 可用余额（常用于显示）。"""
        balances = await self.get_balances()
        usdt = balances.get("USDT", {})
        return float(usdt.get("available", 0))

    async def get_positions(self, symbol: Optional[str] = None, **kwargs) -> List[Dict]:
        """获取持仓列表（统一格式）。kwargs 中的 dex 等参数兼容 Hyperliquid 调用方忽略。"""
        params: Dict = {}
        if symbol:
            params["symbol"] = _to_binance_symbol(symbol)
        data = await self._get("/fapi/v2/positionRisk", params, signed=True)
        if not isinstance(data, list):
            logger.error(f"[Binance] get_positions 返回非列表: {data}")
            return []
        result = []
        for pos in data:
            amt = float(pos.get("positionAmt", 0))
            if amt == 0:
                continue
            result.append({
                "symbol": _from_binance_symbol(pos.get("symbol", "")),
                "binance_symbol": pos.get("symbol"),
                "side": "LONG" if amt > 0 else "SHORT",
                "size": abs(amt),
                "entry_price": float(pos.get("entryPrice", 0)),
                "entryPrice": float(pos.get("entryPrice", 0)),
                "markPrice": float(pos.get("markPrice", 0)),
                "unrealizedProfit": float(pos.get("unRealizedProfit", 0)),
                "leverage": int(pos.get("leverage", 1)),
                "marginType": pos.get("marginType", "isolated"),
                "positionAmt": amt,
            })
        return result

    # ─── 兼容 HyperliquidClient 接口（供 AdaptiveLongStrategy 统一调用）──────

    async def find_asset_dex(self, symbol: str):
        """币安无 DEX 路由，统一返回空 dex，兼容 HL 的 find_asset_dex 签名。
        返回: (dex_name, bn_symbol, asset_info_dict, sz_decimals)
        """
        bn_sym = _to_binance_symbol(symbol)
        return ("", bn_sym, {"name": symbol}, 3)

    async def get_asset_dex(self, symbol: str) -> str:
        """币安无 DEX 路由，统一返回空字符串，兼容 HL 的 get_asset_dex 签名。"""
        return ""

    # ─────────────────────────── 杠杆/保证金设置 ─────────────────────────

    async def set_leverage(self, symbol: str, leverage: int) -> Dict:
        """设置合约杠杆倍数。"""
        bn_sym = _to_binance_symbol(symbol)
        data = await self._post("/fapi/v1/leverage", {
            "symbol": bn_sym,
            "leverage": leverage,
        })
        logger.info(f"[Binance] 设置杠杆 {bn_sym} -> {leverage}x: {data}")
        return data

    async def set_margin_type(self, symbol: str, margin_type: str = "ISOLATED") -> Dict:
        """设置保证金模式: ISOLATED / CROSSED。"""
        bn_sym = _to_binance_symbol(symbol)
        try:
            data = await self._post("/fapi/v1/marginType", {
                "symbol": bn_sym,
                "marginType": margin_type.upper(),
            })
        except Exception as e:
            # 已经是目标模式时币安会返回错误码 -4046，忽略
            logger.debug(f"[Binance] 设置保证金模式忽略: {e}")
            return {}
        return data

    # ─────────────────────────── 下单 ───────────────────────────────────

    async def place_order(
        self,
        symbol: str = None,
        side: str = "BUY",
        quantity: float = 0.0,
        order_type: str = "MARKET",
        leverage: int = None,
        reduce_only: bool = False,
        price: Optional[float] = None,
        order_data: Dict = None,
        **kwargs,
    ) -> Dict:
        """兼容 AdaptiveLongStrategy 的调用方式，支持关键字参数传入。
        若只传入 order_data 字典，则直接发送到币安原生接口。
        """
        if order_data is not None:
            # 居合层调用（直接传币安原生参数字典）
            if "symbol" in order_data:
                order_data = dict(order_data)
                order_data["symbol"] = _to_binance_symbol(order_data["symbol"])
            return await self._post("/fapi/v1/order", order_data)

        # 关键字参数调用（AdaptiveLongStrategy 方式）
        return await self.execute_order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type=order_type,
            price=price,
            max_leverage=leverage,
            reduce_only=reduce_only,
        )

    async def execute_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "MARKET",
        price: Optional[float] = None,
        max_leverage: Optional[int] = None,
        reduce_only: bool = False,
        position_side: str = "BOTH",
    ) -> Dict:
        """执行订单（统一接口）。

        Args:
            symbol:        交易对（内部格式，如 ETH_USDC_PERP 或 ETH）
            side:          BUY / SELL
            quantity:      数量（合约数量，非保证金）
            order_type:    MARKET / LIMIT
            price:         限价单价格（MARKET 不需要）
            max_leverage:  设置杠杆（下单前自动调用 set_leverage）
            reduce_only:   只减仓
            position_side: BOTH（单向持仓）/ LONG / SHORT（双向持仓）
        """
        bn_sym = _to_binance_symbol(symbol)

        # 设置杠杆
        if max_leverage:
            await self.set_leverage(symbol, max_leverage)

        params: Dict = {
            "symbol": bn_sym,
            "side": side.upper(),
            "type": order_type.upper(),
            "quantity": quantity,
            "positionSide": position_side.upper(),
        }
        if reduce_only:
            params["reduceOnly"] = "true"
        if order_type.upper() == "LIMIT" and price:
            params["price"] = price
            params["timeInForce"] = "GTC"

        data = await self._post("/fapi/v1/order", params)
        logger.info(f"[Binance] 下单 {side} {quantity} {bn_sym}: {data}")
        return data

    async def close_position(self, symbol: str, position_side: str = "BOTH") -> Dict:
        """平仓（市价反向下单全量平仓）。"""
        positions = await self.get_positions(symbol)
        if not positions:
            logger.info(f"[Binance] 无持仓可平: {symbol}")
            return {"msg": "no position"}

        pos = positions[0]
        amt = abs(pos["positionAmt"])
        side = "SELL" if pos["positionAmt"] > 0 else "BUY"
        return await self.execute_order(
            symbol=symbol,
            side=side,
            quantity=amt,
            order_type="MARKET",
            reduce_only=True,
            position_side=position_side,
        )

    # ─────────────────────────── 订单管理 ───────────────────────────────

    async def place_tpsl_order(
        self,
        symbol: str,
        trigger_price: float,
        tpsl: str = "sl",
        side: str = "SELL",
        quantity: float = None,
        position_side: str = "BOTH",
        **kwargs,
    ) -> Dict:
        """挂币安原生止损/止盈单。

        币安策略：
          - SL: 不挂交易所原生条件单（STOP_MARKET 易误触发），由软件御控周期负责
          - TP: 挂 LIMIT SELL GTC 在目标价，安全可靠
        """
        bn_sym = _to_binance_symbol(symbol)
        is_sl = tpsl.lower() == "sl"

        if is_sl:
            # SL 不挂交易所单，完全交由软件御控周期处理
            # （STOP_MARKET 在无 workingType 时容易因内耶价偏差导致即时触发）
            logger.info(f"[Binance] SL 由软件御控周期守护（每5s轮询），不挂交易所条件单")
            return {"sl_mode": "software_monitor", "trigger_price": trigger_price}

        # TP: 挂 LIMIT SELL GTC 在目标价
        limit_params: Dict = {
            "symbol":      bn_sym,
            "side":        side.upper(),
            "type":        "LIMIT",
            "price":       round(trigger_price, 2),
            "timeInForce": "GTC",
            "reduceOnly":  "true",
        }
        if quantity:
            limit_params["quantity"] = round(quantity, 3)
        data = await self._post("/fapi/v1/order", limit_params)
        logger.info(f"[Binance] TP LIMIT 挂单 {bn_sym} @{trigger_price:.2f} qty={quantity}: {data}")
        return data

    async def cancel_order_async(
        self,
        symbol: str,
        order_id: Optional[str] = None,
        **kwargs,
    ) -> Dict:
        """撤销订单（兼容 HyperliquidClient 接口）。"""
        return await self.cancel_order(symbol=symbol, order_id=order_id)

    async def cancel_order(
        self,
        symbol: str,
        order_id: Optional[str] = None,
        client_id: Optional[str] = None,
    ) -> Dict:
        """撤销指定订单。"""
        bn_sym = _to_binance_symbol(symbol)
        params: Dict = {"symbol": bn_sym}
        if order_id:
            params["orderId"] = order_id
        if client_id:
            params["origClientOrderId"] = client_id
        data = await self._delete("/fapi/v1/order", params)
        return data

    async def cancel_all_orders(self, symbol: Optional[str] = None) -> Dict:
        """撤销指定交易对的所有挂单。"""
        if symbol:
            bn_sym = _to_binance_symbol(symbol)
            data = await self._delete("/fapi/v1/allOpenOrders", {"symbol": bn_sym})
        else:
            # 没有 symbol 时无法批量撤单（Binance 不支持），只能逐一撤
            data = {"msg": "symbol required for cancel_all_orders"}
            logger.warning("[Binance] cancel_all_orders 需要传入 symbol")
        return data

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict]:
        """获取当前挂单列表。"""
        params: Dict = {}
        if symbol:
            params["symbol"] = _to_binance_symbol(symbol)
        data = await self._get("/fapi/v1/openOrders", params, signed=True)
        result = []
        for o in data:
            result.append({
                "orderId": str(o.get("orderId")),
                "symbol": _from_binance_symbol(o.get("symbol", "")),
                "side": o.get("side"),
                "type": o.get("type"),
                "price": float(o.get("price", 0)),
                "origQty": float(o.get("origQty", 0)),
                "executedQty": float(o.get("executedQty", 0)),
                "status": o.get("status"),
                "time": o.get("time"),
            })
        return result

    async def get_order(self, order_id: str, symbol: Optional[str] = None) -> Dict:
        """查询指定订单。"""
        params: Dict = {"orderId": order_id}
        if symbol:
            params["symbol"] = _to_binance_symbol(symbol)
        data = await self._get("/fapi/v1/order", params, signed=True)
        return data

    async def get_order_history(
        self, symbol: Optional[str] = None, limit: int = 100
    ) -> List[Dict]:
        """获取历史订单列表。"""
        params: Dict = {"limit": limit}
        if symbol:
            params["symbol"] = _to_binance_symbol(symbol)
        data = await self._get("/fapi/v1/allOrders", params, signed=True)
        return data

    # ─────────────────────────── 工具方法 ───────────────────────────────

    def map_symbol(self, symbol: str) -> str:
        """公开的符号转换（供外部调用）。"""
        return _to_binance_symbol(symbol)

    def unmap_symbol(self, symbol: str) -> str:
        """币安符号转回内部格式。"""
        return _from_binance_symbol(symbol)

    async def ping(self) -> bool:
        """连通性测试。"""
        try:
            await self._get("/fapi/v1/ping")
            return True
        except Exception:
            return False
