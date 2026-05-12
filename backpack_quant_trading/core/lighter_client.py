"""
Lighter DEX API 客户端
文档: https://apidocs.lighter.xyz

接口与 HyperliquidAPIClient 对齐，供 AdaptiveLongStrategy 使用。
"""
import asyncio
import json
import logging
import os
import time
import string
import math
from typing import Dict, List, Optional, Any

import aiohttp

logger = logging.getLogger("adaptive_long")

LIGHTER_BASE_URL = "https://mainnet.zklighter.elliot.ai"

# lighter-sdk 内部使用 aiohttp，但默认不会读取 HTTP(S)_PROXY/ALL_PROXY。
# 这里全局打补丁让所有 ClientSession 默认 trust_env=True，从而走你在 shell/.env 里配置的代理。
if not getattr(aiohttp, "_lighter_trust_env_patched", False):
    _orig_client_session = aiohttp.ClientSession

    def _patched_client_session(*args, **kwargs):
        kwargs.setdefault("trust_env", True)
        return _orig_client_session(*args, **kwargs)

    aiohttp.ClientSession = _patched_client_session  # type: ignore[assignment]
    aiohttp._lighter_trust_env_patched = True  # type: ignore[attr-defined]

# 已知市场索引（通过 orderBooks 获取精确映射）
DEFAULT_MARKET_MAP: Dict[str, int] = {
    "ETH": 0,
    "BTC": 1,
}


class LighterAPIClient:
    """
    Lighter DEX API 客户端。
    认证方式：API 私钥（lighter SDK SignerClient）。
    接口与 HyperliquidAPIClient 对齐，供 AdaptiveLongStrategy 使用。
    """

    def __init__(
        self,
        private_key: str,
        account_index: int,
        api_key_index: int = 2,
        base_url: str = LIGHTER_BASE_URL,
    ):
        self.private_key    = private_key
        self.account_index  = account_index
        self.api_key_index  = api_key_index
        self.base_url       = base_url

        # 懒加载 SignerClient（避免导入时立即报错）
        self._signer: Any = None

        # 市场精度缓存
        self._market_map:     Dict[str, int] = dict(DEFAULT_MARKET_MAP)
        self._price_decimals: Dict[int, int] = {}
        self._size_decimals:  Dict[int, int] = {}
        self._market_loaded   = False

        # 全局唯一 client_order_index（每次自增）
        self._order_counter = int(time.time() * 1000) % (2 ** 30)

        self.session: Optional[aiohttp.ClientSession] = None
        # 行情兜底：缓存最近一次成功价格，避免代理/网络短抖导致下单保护价=0
        # { "ETH": {"price": 2300.12, "ts": 1710000000.0} }
        self._last_price: Dict[str, Dict[str, float]] = {}
        # 余额兜底：缓存最近一次成功余额（应对 Lighter 503 短抖）
        self._last_balance: Dict[str, float] = {"value": 0.0, "ts": 0.0}

    @staticmethod
    def _exc_detail(e: Exception) -> str:
        """尽可能从 lighter-sdk 异常里提取可读信息"""
        try:
            detail = getattr(e, "body", None) or getattr(e, "message", None) or getattr(e, "reason", None)
            if detail:
                return str(detail)
        except Exception:
            pass
        return repr(e)

    # ─── 内部工具 ────────────────────────────────────────

    @staticmethod
    def _is_hex_key(s: str) -> bool:
        raw = (s or "").strip()
        if raw.startswith("0x") or raw.startswith("0X"):
            raw = raw[2:]
        if not raw:
            return False
        hexdigits = set(string.hexdigits)
        return all(c in hexdigits for c in raw)

    def _is_eth_private_key(self) -> bool:
        """判断是否是 ETH 私钥（32字节=64 hex），而非 Lighter API 私钥（40字节=80 hex）"""
        key = (self.private_key or "").strip()
        if key.startswith("0x") or key.startswith("0X"):
            key = key[2:]
        return len(key) == 64 and self._is_hex_key(key)  # ETH 私钥（必须 hex）

    def _validate_key_format(self):
        """在调用 lighter-sdk 之前做强校验，避免 TxClient 报 hex invalid byte"""
        k = (self.private_key or "").strip()
        if not k:
            raise ValueError("Lighter 私钥/API Key 为空")
        raw = k[2:] if k.lower().startswith("0x") else k
        if not self._is_hex_key(raw):
            raise ValueError(
                "Lighter 私钥/API Key 含非十六进制字符（仅允许 0-9 a-f A-F），"
                "请检查是否传入了 'none/null' 或复制混入空格换行"
            )
        if len(raw) not in (64, 80):
            raise ValueError(
                f"Lighter 私钥/API Key 长度不正确：期望 64(ETH私钥) 或 80(L2 API Key) hex，实际 {len(raw)}"
            )

    def _lighter_key_cache_path(self) -> str:
        cache_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(cache_dir, f".lighter_apikey_{self.account_index}_{self.api_key_index}.json")

    async def _ensure_signer(self):
        """懒加载 lighter.SignerClient，若传入的是 ETH 私钥则自动生成并注册 Lighter API 密钥"""
        if self._signer is not None:
            return self._signer
        try:
            import lighter
            self._validate_key_format()
            api_key = self.private_key  # 默认直接用传入值

            if self._is_eth_private_key():
                api_key = await self._get_or_create_lighter_api_key()

            self._signer = lighter.SignerClient(
                url=self.base_url,
                api_private_keys={self.api_key_index: api_key},
                account_index=self.account_index,
            )
            logger.info(f"✅ Lighter SignerClient 初始化完成 (account_index={self.account_index})")
        except ImportError:
            raise ImportError("请安装 lighter-sdk: pip install lighter-sdk")
        return self._signer

    async def _get_or_create_lighter_api_key(self) -> str:
        """
        若传入的是 ETH 私钥（32字节），自动生成 Lighter L2 API 密钥并注册，
        注册成功后缓存到本地文件，避免重复注册。
        返回 Lighter API 私钥（40字节=80 hex）。
        """
        import lighter

        cache_path = self._lighter_key_cache_path()
        # 读取缓存
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r") as f:
                    data = json.load(f)
                cached = data.get("api_private_key", "")
                if cached and len(cached.lstrip("0x")) == 80:
                    logger.info(f"[Lighter] 使用缓存 API Key (index={self.api_key_index})")
                    return cached
            except Exception as e:
                logger.warning(f"[Lighter] 读取缓存 API Key 失败: {e}")

        # 生成新密钥对
        logger.info("[Lighter] 正在生成 Lighter L2 API Key...")
        api_priv, api_pub, err = lighter.create_api_key()
        if err:
            raise Exception(f"生成 Lighter API Key 失败: {err}")
        logger.info(f"[Lighter] API Key 生成完成，公钥={api_pub[:16]}...，正在注册到账户 {self.account_index}...")

        # 用 ETH 私钥将新公钥注册到账户
        temp_signer = lighter.SignerClient(
            url=self.base_url,
            api_private_keys={self.api_key_index: api_priv},
            account_index=self.account_index,
        )
        _, reg_err = await temp_signer.change_api_key(
            eth_private_key=self.private_key,
            new_pubkey=api_pub,
            api_key_index=self.api_key_index,
        )
        if reg_err:
            raise Exception(f"注册 Lighter API Key 失败: {reg_err}")

        # 缓存
        try:
            with open(cache_path, "w") as f:
                json.dump({"api_private_key": api_priv, "api_public_key": api_pub,
                           "account_index": self.account_index, "api_key_index": self.api_key_index}, f)
            logger.info(f"[Lighter] API Key 注册成功，已缓存至 {cache_path}")
        except Exception as e:
            logger.warning(f"[Lighter] 缓存 API Key 失败（不影响使用）: {e}")

        return api_priv

    async def _get_api_client(self):
        """创建临时 lighter.ApiClient（只读，无需签名）"""
        import lighter
        return lighter.ApiClient(lighter.Configuration(host=self.base_url))

    def _next_order_idx(self) -> int:
        self._order_counter += 1
        return self._order_counter

    async def _get_session(self):
        """兼容 HyperliquidAPIClient 接口，启动时初始化市场数据"""
        await self._load_markets()
        # 只有在未显式传入 account_index（默认 0）时才自动识别，避免覆盖用户输入的真实 index
        if self.account_index == 0:
            await self._auto_discover_account_index()

    async def _auto_discover_account_index(self):
        """从私鑰推导 ETH 地址，在 Lighter 中自动查找对应的 account_index"""
        try:
            from eth_account import Account as EthAccount
            eth_address = EthAccount.from_key(self.private_key).address.lower()
            logger.info(f"[Lighter] 钟包地址: {eth_address}")
        except ImportError:
            logger.warning("[Lighter] 请安装 eth-account: pip install eth-account，无法自动识别账户")
            return
        except Exception as e:
            logger.warning(f"[Lighter] 推导钉包地址失败: {e}")
            return

        import lighter
        try:
            api_client  = await self._get_api_client()
            account_api = lighter.AccountApi(api_client)

            # 尝试通过 L1 key 直接查找
            for method_name in ('account_by_l1_key', 'get_account_by_address', 'account_by_address'):
                fn = getattr(account_api, method_name, None)
                if fn:
                    try:
                        result = await fn(l1_key=eth_address)
                        idx = (getattr(result, 'index', None)
                               or getattr(result, 'account_index', None)
                               or getattr(result, 'id', None))
                        if idx is not None:
                            self.account_index = int(idx)
                            logger.info(f"[Lighter] 自动识别 account_index={self.account_index}")
                            await api_client.close()
                            return
                    except Exception:
                        pass

            # fallback: 无法通过地址直接查找时，提示手动输入
            logger.warning(
                f"[Lighter] 无法自动识别 account_index！"
                f"请到 https://app.lighter.xyz 进入你的账户，"
                f"URL中的数字就是 account_index（如 /explorer/accounts/723233 则填 723233）"
            )
        except Exception as e:
            logger.warning(f"[Lighter] 自动识别账户失败: {e}")

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    # ─── 市场信息 ────────────────────────────────────────

    async def _load_markets(self):
        """加载所有市场的精度信息"""
        if self._market_loaded:
            return
        api_client = None
        try:
            import lighter
            api_client = await self._get_api_client()
            order_api  = lighter.OrderApi(api_client)
            books      = await order_api.order_books()

            for book in (getattr(books, "order_books", None) or []):
                idx = getattr(book, "market_id", None)
                if idx is None:
                    idx = getattr(book, "market_index", None)
                if idx is None:
                    continue
                # 跳过 spot 市场（避免覆盖 perp ETH:0 为 spot ETH:2048）
                market_type = (getattr(book, "market_type", "") or "").lower()
                if market_type == "spot":
                    continue
                # 尝试多种字段名
                sym = (
                    getattr(book, "symbol", None)
                    or getattr(book, "market_symbol", None)
                    or ""
                ).upper().split("/")[0].split("-")[0]
                if sym:
                    self._market_map[sym] = idx
                # 优先使用模型自带精度字段
                p_dec = (
                    getattr(book, "price_decimals", None)
                    or getattr(book, "price_decimal_places", None)
                    or getattr(book, "price_precision", None)
                    or 2
                )
                s_dec = (
                    getattr(book, "size_decimals", None)
                    or getattr(book, "amount_decimal_places", None)
                    or getattr(book, "size_precision", None)
                    or 4
                )
                self._price_decimals[idx] = int(p_dec)
                self._size_decimals[idx]  = int(s_dec)
            self._market_loaded = True
            logger.info(f"[Lighter] 市场加载完成: {self._market_map}")
        except Exception as e:
            logger.warning(f"[Lighter] 加载市场失败，使用默认精度: {e}")
            self._market_loaded = True  # 避免重复失败
        finally:
            if api_client is not None:
                try:
                    await api_client.close()
                except Exception:
                    pass

    async def _get_market_index(self, symbol: str) -> int:
        asset = symbol.upper().split("/")[0].split("-")[0].split("_")[0]
        if asset not in self._market_map:
            await self._load_markets()
        if asset in self._market_map:
            return self._market_map[asset]
        raise ValueError(f"Lighter: 未知资产 {asset}，请检查 market_map")

    def _price_decimals_for(self, market_index: int) -> int:
        return self._price_decimals.get(market_index, 2)

    def _size_decimals_for(self, market_index: int) -> int:
        return self._size_decimals.get(market_index, 4)

    def _to_price_int(self, market_index: int, price: float) -> int:
        dec = self._price_decimals_for(market_index)
        return int(round(price * (10 ** dec)))

    def _to_size_int(self, market_index: int, size: float) -> int:
        dec = self._size_decimals_for(market_index)
        return int(round(size * (10 ** dec)))

    def _from_price_int(self, market_index: int, price_int: int) -> float:
        dec = self._price_decimals_for(market_index)
        return price_int / (10 ** dec)

    def _from_size_int(self, market_index: int, size_int: int) -> float:
        dec = self._size_decimals_for(market_index)
        return size_int / (10 ** dec)

    # ─── 行情 ─────────────────────────────────────────────

    async def get_price(self, symbol: str, dex: str = "") -> float:
        """获取实时价格（将过最近成交价作为当前价）"""
        sym = (symbol or "").upper().split("/")[0].split("-")[0].split("_")[0]
        # 短抖动重试几次（代理偶发断连）
        last_err: Optional[Exception] = None
        for attempt in range(3):
            try:
                import lighter
                market_index = await self._get_market_index(symbol)
                await self._load_markets()

                api_client = await self._get_api_client()
                try:
                    order_api  = lighter.OrderApi(api_client)
                    details    = await order_api.order_book_details(market_id=market_index)
                finally:
                    await api_client.close()

                # 内层 perp 详情列表
                inner_list = getattr(details, "order_book_details", None) or []
                inner = inner_list[0] if inner_list else None

                # 方案 1：从内层对象取 asks/bids
                if inner is not None:
                    asks = getattr(inner, "asks", None) or []
                    bids = getattr(inner, "bids", None) or []
                    if asks and bids:
                        best_ask = self._from_price_int(market_index, int(asks[0].price))
                        best_bid = self._from_price_int(market_index, int(bids[0].price))
                        price = (best_ask + best_bid) / 2
                        if price > 0:
                            self._last_price[sym] = {"price": float(price), "ts": float(time.time())}
                        return price
                    if asks:
                        price = self._from_price_int(market_index, int(asks[0].price))
                        if price > 0:
                            self._last_price[sym] = {"price": float(price), "ts": float(time.time())}
                        return price
                    if bids:
                        price = self._from_price_int(market_index, int(bids[0].price))
                        if price > 0:
                            self._last_price[sym] = {"price": float(price), "ts": float(time.time())}
                        return price

                    # 方案 2：使用 last_trade_price（已是小数格式，直接使用）
                    ltp = getattr(inner, "last_trade_price", None)
                    if ltp is not None:
                        try:
                            price = float(ltp)  # 已是 USDC 小数，无需除以 price_decimals
                            if price > 0:
                                self._last_price[sym] = {"price": float(price), "ts": float(time.time())}
                                logger.info(f"[Lighter] 使用 last_trade_price={ltp} 价格={price}")
                                return price
                        except Exception:
                            pass

                # 方案 3：外层对象直接找 asks/bids
                asks = getattr(details, "asks", None) or []
                bids = getattr(details, "bids", None) or []
                if asks and bids:
                    best_ask = self._from_price_int(market_index, int(asks[0].price))
                    best_bid = self._from_price_int(market_index, int(bids[0].price))
                    price = (best_ask + best_bid) / 2
                    if price > 0:
                        self._last_price[sym] = {"price": float(price), "ts": float(time.time())}
                    return price
                if asks:
                    price = self._from_price_int(market_index, int(asks[0].price))
                    if price > 0:
                        self._last_price[sym] = {"price": float(price), "ts": float(time.time())}
                    return price
                if bids:
                    price = self._from_price_int(market_index, int(bids[0].price))
                    if price > 0:
                        self._last_price[sym] = {"price": float(price), "ts": float(time.time())}
                    return price

                logger.warning(
                    f"[Lighter] get_price({symbol}) 无法获取价格, market_index={market_index}, details_type={type(details)}"
                )
                break
            except Exception as e:
                last_err = e
                # 轻量重试
                await asyncio.sleep(0.3 * (2 ** attempt))
                continue

        if last_err:
            logger.error(f"[Lighter] get_price({symbol}) 失败: {last_err}")
        # 兜底：用最近一次成功价（30秒内）
        cached = self._last_price.get(sym) if sym else None
        if cached:
            age = float(time.time()) - float(cached.get("ts") or 0)
            if age <= 30 and float(cached.get("price") or 0) > 0:
                logger.warning(f"[Lighter] get_price({symbol}) 使用缓存价格兜底: {cached['price']} (age={age:.1f}s)")
                return float(cached["price"])
        return 0.0

    # ─── 账户 / 余额 / 持仓 ──────────────────────────────

    async def get_balance(self, dex: str = "") -> float:
        """获取可用 USDC 余额"""
        try:
            import lighter
            logger.info(f"[Lighter] 查询余额 account_index={self.account_index}")
            api_client = await self._get_api_client()
            try:
                account_api = lighter.AccountApi(api_client)

                # account 查询偶发 503/网络抖动：做多次重试 + 退避
                account = None
                last_err: Optional[Exception] = None
                for attempt in range(3):
                    for by_val in ("index", "account_index", "id"):
                        try:
                            account = await account_api.account(by=by_val, value=str(self.account_index))
                            logger.info(f"[Lighter] account 调用成功 by={by_val} value={self.account_index}")
                            break
                        except Exception as e:
                            last_err = e
                    if account is not None:
                        break
                    await asyncio.sleep(0.4 * (2 ** attempt))

                if account is None:
                    logger.error(f"[Lighter] account API 调用失败: {self._exc_detail(last_err or Exception('unknown'))}")
                    # 兜底：30 秒内有成功余额则返回缓存
                    age = float(time.time()) - float(self._last_balance.get("ts") or 0)
                    if age <= 30 and float(self._last_balance.get("value") or 0) > 0:
                        logger.warning(f"[Lighter] get_balance 使用缓存余额兜底: {self._last_balance['value']} (age={age:.1f}s)")
                        return float(self._last_balance["value"])
                    return 0.0
            finally:
                await api_client.close()

            # API 返回 DetailedAccounts 包装对象，真实账户在 accounts[0]
            # 结构: {'code': 200, 'accounts': [{..., 'available_balance': '20.000000', ...}]}
            try:
                all_attrs = account.to_dict() if hasattr(account, 'to_dict') else \
                    {k: v for k, v in account.__dict__.items() if not k.startswith('_')}
                logger.info(f"[Lighter] account 全字段: {all_attrs}")
            except Exception as ex:
                logger.info(f"[Lighter] 打印字段异常: {ex}")

            # 取 accounts 列表中第一个账户
            inner = None
            accounts_list = getattr(account, "accounts", None)
            if accounts_list and len(accounts_list) > 0:
                inner = accounts_list[0]
            else:
                inner = account  # 兜底：直接用外层对象

            bal_raw = (
                getattr(inner, "available_balance", None)
                or getattr(inner, "free_collateral", None)
                or getattr(inner, "collateral", None)
                or getattr(inner, "equity", None)
                or getattr(inner, "wallet_balance", None)
                or getattr(inner, "total_balance", None)
                or getattr(inner, "usdc_balance", None)
                or getattr(inner, "margin_balance", None)
                or getattr(inner, "balance", None)
                or 0
            )
            bal = float(bal_raw)
            logger.info(f"[Lighter] 最终余额: {bal} USDC")
            self._last_balance = {"value": float(bal), "ts": float(time.time())}
            return bal
        except Exception as e:
            logger.error(f"[Lighter] get_balance 异常: {self._exc_detail(e)}")
            return 0.0

    async def get_positions(self, symbol: Optional[str] = None, dex: str = "") -> List[Dict]:
        """获取当前持仓列表"""
        try:
            import lighter
            await self._load_markets()
            api_client = await self._get_api_client()
            try:
                account_api = lighter.AccountApi(api_client)
                account = None
                last_err: Optional[Exception] = None
                for attempt in range(3):
                    try:
                        account = await account_api.account(by="index", value=str(self.account_index))
                        break
                    except Exception as e:
                        last_err = e
                        await asyncio.sleep(0.4 * (2 ** attempt))
            finally:
                await api_client.close()
            if account is None:
                logger.error(f"[Lighter] get_positions account API 失败: {self._exc_detail(last_err or Exception('unknown'))}")
                return []

            # 取 accounts[0] 内层对象
            accounts_list = getattr(account, "accounts", None)
            inner = accounts_list[0] if accounts_list and len(accounts_list) > 0 else account

            raw_positions = (
                getattr(inner, "positions", None)
                or getattr(inner, "perp_positions", None)
                or []
            )
            result: List[Dict] = []
            for pos in raw_positions:
                # Lighter AccountPosition 字段: position(大小,浮点), avg_entry_price(浮点), sign(+1=多/-1=空)
                size_raw = (
                    getattr(pos, "position", None)
                    or getattr(pos, "size", None)
                    or 0
                )
                size_float = float(size_raw) if size_raw else 0.0
                if abs(size_float) <= 1e-9:
                    continue

                sign = getattr(pos, "sign", None)
                if sign is not None:
                    try:
                        if int(sign) < 0:
                            size_float = -abs(size_float)
                    except Exception:
                        pass

                market_idx = (
                    getattr(pos, "market_id", None)
                    or getattr(pos, "market_index", None)
                    or 0
                )
                # 按 symbol 过滤
                if symbol:
                    asset = symbol.upper().split("/")[0].split("-")[0]
                    expected_idx = self._market_map.get(asset)
                    if expected_idx is not None and market_idx != expected_idx:
                        continue

                entry_raw = (
                    getattr(pos, "avg_entry_price", None)
                    or getattr(pos, "entry_price", None)
                    or 0
                )
                # avg_entry_price 已是小数格式，直接用
                entry_px = float(entry_raw) if entry_raw else 0.0

                result.append({
                    "symbol":        symbol or getattr(pos, "symbol", f"market_{market_idx}"),
                    "size":          size_float,
                    "side":          "long" if size_float > 0 else "short",
                    "entry_price":   entry_px,
                    "unrealized_pnl": float(getattr(pos, "unrealized_pnl", 0) or 0),
                    "leverage":      float(getattr(pos, "leverage", 1) or 1),
                    "market_index":  market_idx,
                })
            return result
        except Exception as e:
            logger.error(f"[Lighter] get_positions 失败: {e}")
            return []

    # ─── 下单 ─────────────────────────────────────────────

    async def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "MARKET",
        price: Optional[float] = None,
        leverage: int = 10,
        reduce_only: bool = False,
    ) -> Dict[str, Any]:
        """
        下单。
        - 开仓时 quantity = 保证金(USDC)，内部自动换算为合约数量。
        - 平仓时 reduce_only=True，quantity = 持仓数量(币)。
        """
        try:
            import lighter
            client       = await self._ensure_signer()
            market_index = await self._get_market_index(symbol)
            await self._load_markets()

            is_ask = side.upper() == "SELL"

            # 开仓前先设置杠杆倍数（仅开仓时）
            if not reduce_only and leverage > 0:
                try:
                    # lighter-sdk 不同版本可能返回 2/3 个值，这里做兼容解包
                    lev_res = await client.update_leverage(
                        market_index=market_index,
                        margin_mode=lighter.SignerClient.CROSS_MARGIN_MODE,
                        leverage=int(leverage),
                    )
                    lev_err = None
                    if isinstance(lev_res, tuple):
                        # 常见：(result, err) 或 (result, tx_hash, err)
                        lev_err = lev_res[-1] if len(lev_res) >= 2 else None
                    if lev_err:
                        logger.warning(f"[Lighter] 设置杠杆失败: {lev_err}")
                    else:
                        logger.info(f"[Lighter] 杠杆已设置为 {leverage}x")
                except Exception as e:
                    logger.warning(f"[Lighter] 设置杠杆异常: {e}")
            current_price: float = 0.0
            if not reduce_only:
                current_price = await self.get_price(symbol)
                if current_price <= 0:
                    return {"status": "FAILED", "error": "无法获取 Lighter 实时价格（下单前）"}
                notional = quantity * leverage
                coin_size = notional / current_price
            else:
                coin_size = quantity

            # 计算委托价格（市价单使用最差可接受价）
            if order_type.upper() == "MARKET":
                # 复用上面已拉到的 current_price，避免二次请求导致 0→价格过小(400)
                cur_price = current_price if current_price > 0 else await self.get_price(symbol)
                if cur_price <= 0:
                    return {"status": "FAILED", "error": "无法获取 Lighter 实时价格（计算市价保护价）"}
                # 市价单保护价（防止极端滑点）：
                # - 开仓：用较紧保护（BUY 1.03 / SELL 0.97）
                # - 平仓(reduce_only)：用更宽保护，避免只吃到部分流动性导致“只平掉一部分仓位”
                if reduce_only:
                    # BUY 平空：允许更高保护价；SELL 平多：允许更低保护价
                    # 这里刻意给更宽的保护价，尽量实现“一笔吃完”的效果（仍受限于盘口流动性）
                    worst_price = cur_price * 1.50 if not is_ask else cur_price * 0.50
                else:
                    worst_price = cur_price * 1.03 if not is_ask else cur_price * 0.97
            else:
                if price is None or price <= 0:
                    worst_price = await self.get_price(symbol)
                else:
                    worst_price = price
            if worst_price <= 0:
                return {"status": "FAILED", "error": f"委托价格无效: {worst_price}"}

            price_int = self._to_price_int(market_index, worst_price)
            # reduce_only 平仓：**向上取整**到最小单位，避免“每次少平一点”导致残仓
            dec = self._size_decimals_for(market_index)
            if reduce_only:
                size_int = int(math.ceil(float(coin_size) * (10 ** dec)))
            else:
                size_int = self._to_size_int(market_index, coin_size)

            if size_int <= 0:
                min_unit = 1 / (10 ** dec)
                return {
                    "status": "FAILED",
                    "error": f"下单数量过小: {coin_size} (size_decimals={dec}, 最小单位≈{min_unit})",
                }

            client_order_idx = self._next_order_idx()

            if order_type.upper() == "MARKET":
                tx, tx_hash, err = await client.create_order(
                    market_index=market_index,
                    client_order_index=client_order_idx,
                    base_amount=size_int,
                    price=price_int,
                    is_ask=is_ask,
                    order_type=client.ORDER_TYPE_MARKET,
                    time_in_force=client.ORDER_TIME_IN_FORCE_IMMEDIATE_OR_CANCEL,
                    reduce_only=reduce_only,
                    order_expiry=client.DEFAULT_IOC_EXPIRY,
                )
            else:
                tx, tx_hash, err = await client.create_order(
                    market_index=market_index,
                    client_order_index=client_order_idx,
                    base_amount=size_int,
                    price=price_int,
                    is_ask=is_ask,
                    order_type=client.ORDER_TYPE_LIMIT,
                    time_in_force=client.ORDER_TIME_IN_FORCE_GOOD_TILL_TIME,
                    reduce_only=reduce_only,
                    order_expiry=client.DEFAULT_28_DAY_ORDER_EXPIRY,
                )

            if err:
                logger.error(f"[Lighter] 下单错误: {err}")
                return {"status": "FAILED", "error": str(err)}

            logger.info(
                f"[Lighter] 下单成功: {side} {coin_size:.4f} {symbol} "
                f"@{worst_price:.2f}  client_order_idx={client_order_idx}  tx={tx_hash}"
            )
            return {
                "status":   "FILLED",
                "orderId":  str(client_order_idx),
                "symbol":   symbol,
                "side":     side.upper(),
                # 返回实际提交的数量（按整数精度换算回来），避免日志里看到 0.00061 但实际提交 0.0006 的错觉
                "quantity": self._from_size_int(market_index, size_int),
                "price":    worst_price,
                "raw":      tx_hash,
            }
        except Exception as e:
            # lighter-sdk 有时会把 HTTP 错误包装成仅含状态码的异常（例如 "(400)"），需要更详细的 repr
            logger.error(f"[Lighter] place_order 异常: {repr(e)}  type={type(e)}  args={getattr(e, 'args', None)}")
            # 尝试从常见字段提取更详细信息
            detail = getattr(e, "body", None) or getattr(e, "message", None) or getattr(e, "reason", None)
            if detail:
                logger.error(f"[Lighter] place_order 异常详情: {detail}")
            return {"status": "FAILED", "error": str(detail or e)}

    # ─── TP/SL 挂单 ──────────────────────────────────────

    async def place_tpsl_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        trigger_price: float,
        tpsl: str,  # "tp" or "sl"
        **kwargs,
    ) -> Dict[str, Any]:
        """
        挂止盈/止损单。
        使用 Lighter 原生触发单 create_sl_order / create_tp_order。
        """
        is_sl = tpsl.lower() == "sl"
        try:
            import lighter
            client       = await self._ensure_signer()
            market_index = await self._get_market_index(symbol)

            # TP/SL 的方向取决于持仓方向：平多=SELL，平空=BUY
            is_ask = str(side or "").upper() == "SELL"
            size_int  = self._to_size_int(market_index, quantity)
            trig_int  = self._to_price_int(market_index, trigger_price)

            # 与普通下单保持一致：全局唯一 client_order_index（便于排查）
            client_order_idx = self._next_order_idx()

            if is_sl:
                # SL: SELL 用更低限价确保成交；BUY 用更高限价确保成交
                sl_limit = trigger_price * (0.95 if is_ask else 1.05)
                sl_lim_int = self._to_price_int(market_index, sl_limit)
                tx, tx_hash, err = await client.create_sl_order(
                    market_index=market_index,
                    client_order_index=client_order_idx,
                    base_amount=size_int,
                    trigger_price=trig_int,
                    price=sl_lim_int,
                    is_ask=is_ask,
                    reduce_only=True,
                )
                label = "SL"
            else:
                # TP: SELL 略低限价确保成交；BUY 略高限价确保成交
                tp_limit = trigger_price * (0.97 if is_ask else 1.03)
                tp_lim_int = self._to_price_int(market_index, tp_limit)
                tx, tx_hash, err = await client.create_tp_order(
                    market_index=market_index,
                    client_order_index=client_order_idx,
                    base_amount=size_int,
                    trigger_price=trig_int,
                    price=tp_lim_int,
                    is_ask=is_ask,
                    reduce_only=True,
                )
                label = "TP"

            if err:
                logger.warning(f"[Lighter] {label} 挂单失败: {err}")
                return {"status": "FAILED", "error": str(err)}

            # lighter-sdk 可能返回不同结构，这里尽量提取可用于撤单/展示的 order_index
            order_index = None
            try:
                order_index = (
                    getattr(tx, "order_index", None)
                    or getattr(tx, "order_id", None)
                    or getattr(tx, "orderIndex", None)
                )
                if isinstance(tx, dict):
                    order_index = tx.get("order_index") or tx.get("orderId") or tx.get("order_id") or order_index
            except Exception:
                order_index = None

            logger.info(
                f"[Lighter] {label} 触发单成功: {side.upper()} {quantity:.4f} {symbol} "
                f"触发@{trigger_price:.2f}  client_order_idx={client_order_idx}  "
                f"order_index={order_index}  tx={tx_hash}"
            )
            return {"status": "OK", "orderId": str(order_index or client_order_idx), "raw": tx_hash}
        except Exception as e:
            logger.error(
                f"[Lighter] place_tpsl_order 异常: {repr(e)}  type={type(e)}  args={getattr(e, 'args', None)}"
            )
            detail = getattr(e, "body", None) or getattr(e, "message", None) or getattr(e, "reason", None)
            if detail:
                logger.error(f"[Lighter] place_tpsl_order 异常详情: {detail}")
            return {"status": "FAILED", "error": str(detail or e)}

    # ─── 撤单 ─────────────────────────────────────────────

    async def cancel_order_async(
        self,
        symbol: str,
        order_id: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """撤销订单（兼容 HyperliquidAPIClient 接口）"""
        if not order_id:
            return {"status": "FAILED", "error": "no order_id"}
        try:
            import lighter
            client       = await self._ensure_signer()
            market_index = await self._get_market_index(symbol)
            tx, tx_hash, err = await client.cancel_order(
                market_index=market_index,
                order_index=int(order_id),
            )
            if err:
                logger.error(f"[Lighter] 撤单错误: {err}")
                return {"status": "FAILED", "error": str(err)}
            logger.info(f"[Lighter] 撤单成功: oid={order_id}")
            return {"status": "CANCELED", "orderId": order_id}
        except Exception as e:
            logger.error(f"[Lighter] cancel_order_async 异常: {e}")
            return {"status": "FAILED", "error": str(e)}

    # ─── 兼容 HyperliquidAPIClient 接口 ──────────────────

    async def find_asset_dex(self, symbol: str):
        """兼容接口：Lighter 无 DEX 分层"""
        market_index = await self._get_market_index(symbol)
        await self._load_markets()
        sz_dec = self._size_decimals_for(market_index)
        return ("", market_index, {"name": symbol}, sz_dec)

    async def get_asset_dex(self, symbol: str) -> str:
        """兼容接口：Lighter 无 DEX"""
        return ""
