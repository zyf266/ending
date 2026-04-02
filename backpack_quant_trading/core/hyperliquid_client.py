import time
import json
import logging
import asyncio
import hashlib
import struct
import msgpack
from typing import Dict, List, Optional, Any, Union
from decimal import Decimal
from collections import OrderedDict
import aiohttp
from eth_account import Account
from eth_account.messages import encode_typed_data
from web3 import Web3

logger = logging.getLogger(__name__)

class HyperliquidAPIClient:
    """Hyperliquid API 客户端 (参考 OstiumClient 实现风格)"""
    
    def __init__(self, private_key: str = None, base_url: str = "https://api.hyperliquid.xyz"):
        self.private_key = private_key
        self.base_url = base_url
        self.info_url = f"{base_url}/info"
        self.exchange_url = f"{base_url}/exchange"
        
        if private_key:
            # 清理私钥格式
            pk = private_key.strip()
            # 移除 0x 前缀（如果存在）
            if pk.startswith('0x') or pk.startswith('0X'):
                pk = pk[2:]
            # 验证私钥长度（64位十六进制字符）
            if len(pk) != 64:
                raise ValueError(f"私钥长度错误: 应为64位十六进制字符(不含0x前缀)，当前{len(pk)}位")
            # 验证是否为有效的十六进制
            try:
                int(pk, 16)
            except ValueError:
                raise ValueError("私钥包含非十六进制字符，请检查私钥格式")
            
            self.account = Account.from_key(pk)
            # 【核心修复】地址统一转小写，Hyperliquid API 内部索引对大小写极度敏感
            self.address = self.account.address.lower().strip()
            logger.info(f"Hyperliquid 账户已加载: {self.address}")
        else:
            self.account = None
            self.address = None
            
        self.session: Optional[aiohttp.ClientSession] = None
        # 缓存 meta 数据以获取资产 ID
        self._meta = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    async def close(self):
        """关闭 aiohttp session，避免 Unclosed client session 警告"""
        if self.session and not self.session.closed:
            await self.session.close()

    async def post_info(self, data: Dict) -> Any:
        """调用 /info 接口"""
        session = await self._get_session()
        async with session.post(self.info_url, json=data, headers={'Content-Type': 'application/json'}) as resp:
            text = await resp.text()
            try:
                return json.loads(text)
            except:
                logger.error(f"Hyperliquid Info 响应解析失败 ({resp.status}): {text}")
                return {}

    async def get_meta(self) -> Dict:
        """获取交易所元数据（包含资产映射）"""
        if not self._meta:
            self._meta = await self.post_info({"type": "meta"})
        return self._meta

    async def get_price(self, symbol: str) -> float:
        """获取实时价格"""
        # Hyperliquid 的 symbol 通常直接是 'ETH' 或 'BTC'
        asset = symbol.replace("-USD", "").replace("-USDT", "").split("_")[0]
        all_mids = await self.post_info({"type": "allMids"})
        return float(all_mids.get(asset, 0.0))

    async def get_klines(self, symbol: str, interval: str, limit: int = 500) -> List[Dict]:
        """
        获取历史 K 线数据（使用 Hyperliquid candleSnapshot 接口）
        返回格式: [{"t", "o", "h", "l", "c", "v"}, ...]
        """
        INTERVAL_MS = {
            "1m":  60_000,      "3m":  180_000,     "5m":  300_000,
            "15m": 900_000,     "30m": 1_800_000,
            "1h":  3_600_000,   "2h":  7_200_000,   "4h":  14_400_000,
            "8h":  28_800_000,  "12h": 43_200_000,
            "1d":  86_400_000,  "3d":  259_200_000,  "1w": 604_800_000,
        }
        interval_ms = INTERVAL_MS.get(interval, 3_600_000)
        end_time = int(time.time() * 1000)
        start_time = end_time - interval_ms * (limit + 10)  # 多拉 10 根做缓冲

        asset = symbol.replace("-USD", "").replace("-USDT", "").split("_")[0]
        data = await self.post_info({
            "type": "candleSnapshot",
            "req": {
                "coin": asset,
                "interval": interval,
                "startTime": start_time,
                "endTime": end_time,
            }
        })

        result = []
        for item in (data or []):
            try:
                result.append({
                    "t": item["t"],
                    "o": float(item["o"]),
                    "h": float(item["h"]),
                    "l": float(item["l"]),
                    "c": float(item["c"]),
                    "v": float(item["v"]),
                })
            except (KeyError, TypeError, ValueError):
                continue
        # 按时间升序，返回最新 limit 根
        result.sort(key=lambda x: x["t"])
        return result[-limit:] if len(result) > limit else result

    async def check_user_exists(self) -> bool:
        """检查用户账户是否存在于 Hyperliquid"""
        if not self.address:
            return False
        try:
            user_state = await self.post_info({"type": "clearinghouseState", "user": self.address})
            # 如果返回了数据（即使是空的），说明账户存在
            return user_state is not None and isinstance(user_state, dict)
        except Exception as e:
            logger.error(f"检查用户存在性失败: {e}")
            return False

    async def get_balance(self) -> float:
        """获取可用余额 (USDC)"""
        if not self.address:
            return 0.0
        user_state = await self.post_info({"type": "clearinghouseState", "user": self.address})
        return float(user_state.get('withdrawable', 0.0))

    async def get_positions(self, symbol: Optional[str] = None) -> List[Dict]:
        """获取当前持仓。symbol 可选，如 ETH 或 ETH-USD，用于过滤。"""
        if not self.address:
            return []
        user_state = await self.post_info({"type": "clearinghouseState", "user": self.address})
        if user_state is None or not isinstance(user_state, dict):
            logger.debug("get_positions: clearinghouseState 返回空或非 dict，视为无持仓")
            return []
        positions = []
        coin_filter = None
        if symbol:
            # 提取资产名（如 ETH-USDT-SWAP -> ETH），与 API 返回的 coin 一致
            coin_filter = (symbol or "").split("-")[0].split("_")[0].upper()
        asset_positions = user_state.get('assetPositions') or []
        for p in asset_positions:
            if p is None:
                continue
            pos_data = p.get('position') if isinstance(p, dict) else {}
            if not isinstance(pos_data, dict):
                continue
            s_size = float(pos_data.get('szi') or 0)
            if s_size != 0:
                coin = pos_data.get('coin')
                if coin_filter and coin != coin_filter:
                    continue
                lev = pos_data.get('leverage')
                leverage_val = float((lev.get('value', 1) if isinstance(lev, dict) else lev) or 1)
                positions.append({
                    'symbol': coin,
                    'size': s_size,
                    'side': 'long' if s_size > 0 else 'short',
                    'entry_price': float(pos_data.get('entryPx') or 0),
                    'unrealized_pnl': float(pos_data.get('unrealizedPnl') or 0),
                    'leverage': leverage_val
                })
        # 诊断：若 symbol 过滤后为 0 条但 API 有持仓，便于排查过滤问题
        if symbol and not positions and asset_positions:
            first_coin = (asset_positions[0].get('position') or {}).get('coin', '?')
            logger.warning(f"Hyperliquid get_positions(symbol={symbol}) coin_filter={coin_filter} 过滤后 0 条，API 首条 coin={first_coin}")
        return positions

    async def get_sz_decimals(self, symbol: str) -> int:
        """获取资产的小数位数限制"""
        asset = symbol.replace("-USD", "").replace("-USDT", "").split("_")[0]
        meta = await self.get_meta()
        for i, c in enumerate(meta['universe']):
            if c['name'] == asset:
                # szDecimals 通常在 meta 的 universe 中
                return c.get('szDecimals', 4)
        return 4

    async def place_order(self, symbol: str, side: str, quantity: float, order_type: str = 'MARKET', 
                    price: Optional[float] = None, leverage: int = 5, reduce_only: bool = False) -> Dict[str, Any]:
        """下单 (包含 EIP-712 签名逻辑)"""
        if not self.account:
            raise ValueError("未配置私钥，无法下单")
        
        # 【优化】移除 check_user_exists 预检。
        # 理由：该预检依赖 clearinghouseState，在账户无余额或 API 延迟时会返回 null 导致误报“账户不存在”。
        # 真正的存在性检查应由交易所执行下单请求时返回。
        
        # 1. 准备资产 ID 和精度
        asset = symbol.replace("-USD", "").replace("-USDT", "").split("_")[0]
        meta = await self.get_meta()
        asset_info = next((c for c in meta['universe'] if c['name'] == asset), None)
        if asset_info is None:
            raise ValueError(f"不支持的资产: {asset}")
        
        asset_id = meta['universe'].index(asset_info)
        sz_decimals = asset_info.get('szDecimals', 4)

        # 2. 如果是市价单，获取当前价并加滑点；限价单必须传入 price，否则用当前价
        if order_type.upper() == 'MARKET':
            current_price = await self.get_price(asset)
            # 买入加 1%，卖出减 1% 确保成交
            price = current_price * 1.01 if side.upper() == 'BUY' else current_price * 0.99
        elif price is None or price <= 0:
            price = await self.get_price(asset)
            logger.warning(f"Hyperliquid 限价单未传 price，使用当前价 {price}")
        if reduce_only and order_type.upper() == 'LIMIT':
            logger.info(f"📊 Hyperliquid 限价平仓: {side} @ {price} (reduce_only)")
        
        # 3. 设置杠杆 (仅开仓时需要；平仓 reduce_only 时可选，保留以兼容)
        if not reduce_only:
            await self._set_leverage(asset_id, leverage)

        # 4. 构建下单载荷 (Hyperliquid 协议规范)
        timestamp = int(time.time() * 1000)
        is_buy = side.upper() == 'BUY'
        
        # 【关键】平仓时 quantity 为持仓数量(币数)；开仓时 quantity 为保证金
        if reduce_only:
            coin_size = quantity  # 平仓：直接使用持仓数量 (ETH 等)
        else:
            notional_value = quantity * leverage
            coin_size = notional_value / price if order_type.upper() == 'MARKET' else quantity
        
        # 检查最小下单数量
        formatted_sz = f"{float(f'{coin_size:.{sz_decimals}f}'):g}"
        
        if reduce_only:
            logger.info(f"📊 Hyperliquid 平仓: 数量={formatted_sz} {asset} (reduce_only)")
        else:
            logger.info(f"📊 Hyperliquid 下单计算: 保证金={quantity}, 杠杆={leverage}x, 名义价值=${quantity * leverage}, 目标数量={formatted_sz} {asset}")
        if float(formatted_sz) <= 0:
            logger.error(f"❌ 下单数量过小: {coin_size} (截断后为 0)，请增加保证金金额或检查平仓数量")
            return {'status': 'FAILED', 'error': f'Order size too small: {coin_size}'}

        # 【终极对齐】严格遵循 Hyperliquid SDK 的字段构造顺序和 Msgpack 规范
        # 1. order 对象内部顺序：a, b, p, s, r, t (根据 1.txt 第 1042 行)
        # 注意：s (size) 必须在 r (reduceOnly) 前面
        order = OrderedDict([
            ("a", asset_id),
            ("b", is_buy),
            ("p", self._format_price(price)),
            ("s", formatted_sz),
            ("r", reduce_only),
            ("t", {"limit": {"tif": "Ioc"}} if order_type.upper() == 'MARKET' else {"limit": {"tif": "Gtc"}})
        ])

        # 2. action 顶级对象顺序：type, orders, grouping
        action = OrderedDict([
            ("type", "order"),
            ("orders", [order]),
            ("grouping", "na")
        ])

        # 5. 签名并发送
        try:
            signature = self._sign_action(action, timestamp)
            payload = {
                "action": action,
                "nonce": timestamp,
                "signature": signature
            }
            
            session = await self._get_session()
            # 发送时使用紧凑格式即可，因为服务器接收的是 JSON
            async with session.post(self.exchange_url, json=payload, headers={'Content-Type': 'application/json'}) as resp:
                text = await resp.text()
                if resp.status != 200:
                    logger.error(f"Hyperliquid API 错误 ({resp.status}): {text}")
                    return {'status': 'FAILED', 'error': f"HTTP {resp.status}: {text}"}
                    
                try:
                    result = json.loads(text)
                except:
                    raise Exception(f"无法解析 JSON 响应: {text}")

                if result.get('status') == 'ok':
                    resp = result.get('response') or {}
                    resp_data = resp.get('data') or resp
                    # 兼容 response.data.statuses 与 response.statuses
                    statuses = resp_data.get('statuses') if isinstance(resp_data, dict) else []
                    if not statuses and isinstance(resp.get('data'), dict):
                        statuses = resp['data'].get('statuses') or []
                    statuses = statuses or [{}]
                    data = statuses[0] if statuses else {}
                    # 交易所返回 status=ok 但 statuses[0] 里可能是 error（如保证金不足）
                    if isinstance(data, dict) and data.get('error'):
                        err_msg = data.get('error') or str(data)
                        logger.error(f"❌ Hyperliquid 下单被拒: {err_msg}")
                        return {'status': 'FAILED', 'error': err_msg}
                    order_id = None
                    if isinstance(data, dict):
                        order_id = (data.get('resting') or {}).get('oid') or (data.get('filled') or {}).get('oid')
                    if order_id is None and isinstance(resp_data, dict):
                        order_id = resp_data.get('oid')
                    if order_id is None and isinstance(resp, dict):
                        order_id = resp.get('oid')
                    if order_id is not None:
                        order_id = str(order_id)
                    else:
                        logger.warning(
                            f"Hyperliquid 下单成功但未解析到 oid，response 键: {list(resp.keys()) if isinstance(resp, dict) else 'n/a'}, "
                            f"data 键: {list(resp_data.keys()) if isinstance(resp_data, dict) else 'n/a'}, "
                            f"statuses[0]: {data}"
                        )
                    return {
                        'status': 'FILLED',
                        'orderId': order_id,
                        'symbol': asset,
                        'side': side.upper(),
                        'quantity': quantity,
                        'price': price,
                        'raw': result
                    }
                else:
                    error_response = result.get('response', '')
                    error_msg = str(error_response) if error_response else str(result)
                    
                    # 检查是否是账户不存在的错误
                    if 'does not exist' in error_msg or 'User or API Wallet' in error_msg:
                        detailed_error = (
                            f"❌ Hyperliquid 账户不存在错误\n"
                            f"错误信息: {error_msg}\n"
                            f"签名地址: {self.address}\n"
                            f"可能原因：\n"
                            f"1. 账户地址 {self.address} 在 Hyperliquid 上未初始化\n"
                            f"2. 账户需要先进行首次存款或交易才能激活\n"
                            f"3. 如果使用 API Wallet，需要先通过 approveAgent 注册\n"
                            f"解决方案：\n"
                            f"- 访问 Hyperliquid 网站，使用该地址进行首次存款\n"
                            f"- 或使用主账户私钥进行签名（source='Main'）"
                        )
                        logger.error(detailed_error)
                        return {'status': 'FAILED', 'error': detailed_error}
                    
                    raise Exception(f"Hyperliquid 下单失败: {result}")
        except Exception as e:
            logger.error(f"Hyperliquid 下单异常: {e}")
            return {'status': 'FAILED', 'error': str(e)}

    async def execute_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = 'MARKET',
        price: Optional[float] = None,
        max_leverage: Optional[int] = None,
        reduce_only: bool = False,
    ) -> Dict[str, Any]:
        """网格/统一入口：执行下单，兼容 ExchangeClient 协议。"""
        leverage = int(max_leverage) if max_leverage is not None else 5
        return await self.place_order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type=order_type,
            price=price,
            leverage=leverage,
            reduce_only=reduce_only,
        )

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """返回当前挂单列表，用于网格策略避免同价重复挂单。每项含 oid, limitPx, side(B/A), reduce_only(若有)。"""
        if not self.address:
            return []
        try:
            raw = await self.post_info({"type": "openOrders", "user": self.address})
            out = []
            asset = (symbol or "").replace("-USD", "").replace("-USDT", "").split("_")[0].upper() if symbol else None
            for o in (raw or []):
                if not isinstance(o, dict):
                    continue
                coin = o.get("coin") or ""
                if asset and coin != asset:
                    continue
                oid = o.get("oid")
                limit_px = o.get("limitPx")
                side = "B" if (o.get("side") or "").upper() in ("B", "BUY") else "A"
                reduce_only = bool(o.get("reduceOnly", o.get("r", False)))
                out.append({
                    "oid": oid,
                    "limitPx": limit_px,
                    "price": float(limit_px) if limit_px is not None else None,
                    "side": "BUY" if side == "B" else "SELL",
                    "reduce_only": reduce_only,
                })
            return out
        except Exception as e:
            logger.warning(f"get_open_orders 失败: {e}")
            return []

    async def get_order(self, order_id: str, symbol: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """查询订单状态（网格用）。order_id 为 oid。在挂单中则返回 NEW；不在挂单则查 orderStatus 区分 filled / cancelled / unknown，便于策略对“已取消或丢失”的平仓单重新挂单。"""
        if not self.address:
            return {'status': 'UNKNOWN', 'error': 'no address'}
        oid_str = str(order_id).strip()
        try:
            open_orders = await self.post_info({"type": "openOrders", "user": self.address})
            for o in (open_orders or []):
                oid = o.get('oid')
                if oid is not None and str(oid) == oid_str:
                    return {'status': 'NEW', 'orderId': order_id}
            # 不在挂单里：用 orderStatus 区分是已成交还是已取消/未知（便于策略对平仓单“不见了”时重新挂单）
            try:
                oid_val = int(oid_str) if oid_str.isdigit() else oid_str
                status_resp = await self.post_info({"type": "orderStatus", "user": self.address, "oid": oid_val})
            except (ValueError, TypeError):
                status_resp = {}
            if isinstance(status_resp, dict) and status_resp.get("status") == "unknownOid":
                return None
            order_block = status_resp.get("order") if isinstance(status_resp, dict) else None
            if isinstance(order_block, dict):
                st = (order_block.get("status") or "").lower()
                if st == "filled":
                    return {'status': 'FILLED', 'orderId': order_id}
                if st in ("canceled", "cancelled", "rejected", "marginCanceled", "reduceOnlyCanceled",
                          "selfTradeCanceled", "expired", "triggered"):
                    return {'status': 'CANCELLED', 'orderId': order_id}
            # 无法确定则视为“不存在”，让策略重新挂平仓单
            return None
        except Exception as e:
            logger.warning(f"get_order 失败: {e}")
            return None

    async def close_position(self, symbol: str, **kwargs) -> Dict[str, Any]:
        """按交易对平仓（网格/实盘用）。无 pair_id/trade_index，按 symbol 查持仓后 reduce_only 下单。"""
        positions = await self.get_positions(symbol=symbol)
        target = next((p for p in positions if p.get('symbol')), None)
        if not target:
            logger.info(f"Hyperliquid 无 {symbol} 持仓，无需平仓")
            return {'status': 'CLOSED', 'symbol': symbol}
        side = 'SELL' if target['side'] == 'long' else 'BUY'
        sz = abs(target['size'])
        return await self.place_order(
            symbol=target['symbol'],
            side=side,
            quantity=sz,
            order_type='MARKET',
            reduce_only=True,
        )

    async def cancel_order_async(self, symbol: str, order_id: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """撤销订单（网格用）。order_id 为 oid。"""
        if not self.account or not order_id:
            return {'status': 'FAILED', 'error': 'no account or order_id'}
        asset = (symbol or "").replace("-USD", "").replace("-USDT", "").split("_")[0]
        meta = await self.get_meta()
        asset_info = next((c for c in meta['universe'] if c['name'] == asset), None)
        if asset_info is None:
            return {'status': 'FAILED', 'error': f'unknown asset: {asset}'}
        asset_id = meta['universe'].index(asset_info)
        try:
            oid = int(order_id)
        except (ValueError, TypeError):
            return {'status': 'FAILED', 'error': f'invalid oid: {order_id}'}
        action = OrderedDict([
            ("type", "cancel"),
            ("cancels", [OrderedDict([("a", asset_id), ("o", oid)])])
        ])
        timestamp = int(time.time() * 1000)
        signature = self._sign_action(action, timestamp)
        payload = {"action": action, "nonce": timestamp, "signature": signature}
        session = await self._get_session()
        async with session.post(self.exchange_url, json=payload) as resp:
            text = await resp.text()
            try:
                result = json.loads(text)
            except Exception:
                return {'status': 'FAILED', 'error': text}
            if result.get('status') == 'ok':
                statuses = (result.get('response') or {}).get('data') or {}
                statuses = statuses.get('statuses', [statuses])
                if statuses and statuses[0] == 'success':
                    return {'status': 'CANCELED', 'orderId': order_id}
                return {'status': 'CANCELED', 'orderId': order_id}
            return {'status': 'FAILED', 'error': str(result)}

    async def _set_leverage(self, asset_id: int, leverage: int):
        """设置杠杆"""
        timestamp = int(time.time() * 1000)
        # 严格遵守字段顺序：type, asset, isCross, leverage (字母序: a, i, l)
        action = OrderedDict([
            ("type", "updateLeverage"),
            ("asset", asset_id),
            ("isCross", True),
            ("leverage", leverage)
        ])
        signature = self._sign_action(action, timestamp)
        payload = {"action": action, "nonce": timestamp, "signature": signature}
        session = await self._get_session()
        # 发送紧凑 JSON
        async with session.post(self.exchange_url, json=payload) as resp:
            text = await resp.text()
            try:
                res_data = json.loads(text)
                if res_data.get('status') == 'ok':
                    logger.info(f"✅ 杠杆设置成功: {leverage}x (asset_id={asset_id})")
                else:
                    logger.error(f"❌ 杠杆设置动作失败: {res_data}")
            except:
                logger.error(f"❌ 杠杆设置响应解析失败: {text}")

    def _sign_action(self, action: Union[Dict, OrderedDict], nonce: int) -> Dict:
        """生成 EIP-712 签名 (Hyperliquid 规范)"""
        if not self.account:
            raise ValueError("未配置私钥，无法进行签名")
            
        try:
            # 1. connectionId = keccak(msgpack(action) + nonce(8) + vault_flag(1))，与官方 SDK 完全一致
            # 无 vault 时必须在 nonce 后追加 b"\x00"，否则恢复出的地址会错误
            data_bytes = msgpack.packb(action, use_bin_type=False)
            data_bytes += nonce.to_bytes(8, "big")
            data_bytes += b"\x00"
            msg_hash_bytes = Web3.keccak(data_bytes)
            connection_id = "0x" + msg_hash_bytes.hex()

            logger.info(f"✍️ 正在签名动作: {action['type']} | 地址: {self.address} | Nonce: {nonce}")

            # 2. source 主网必须为 "a"、测试网为 "b"，不能用 "Main"
            is_mainnet = "testnet" not in (self.base_url or "").lower()
            domain = {
                "name": "Exchange",
                "version": "1",
                "chainId": 1337,
                "verifyingContract": "0x0000000000000000000000000000000000000000"
            }
            types = {
                "Agent": [
                    {"name": "source", "type": "string"},
                    {"name": "connectionId", "type": "bytes32"}
                ]
            }
            message = {
                "source": "a" if is_mainnet else "b",
                "connectionId": connection_id
            }
            
            # 3. 执行签名
            signable_msg = encode_typed_data(
                domain_data=domain,
                message_types=types,
                message_data=message
            )
            signed_msg = self.account.sign_message(signable_msg)
            
            return {
                "r": hex(signed_msg.r),
                "s": hex(signed_msg.s),
                "v": signed_msg.v
            }
        except Exception as e:
            logger.error(f"❌ 签名过程中出现异常: {e}", exc_info=True)
            raise

    def _format_price(self, price: float) -> str:
        # Hyperliquid 价格有效数字通常为 5 位
        return f"{float(f'{price:.5g}'):g}"

    def _format_size(self, size: float) -> str:
        # 数量精度处理
        return f"{float(f'{size:.8g}'):g}"

    async def close(self):
        if self.session:
            await self.session.close()
