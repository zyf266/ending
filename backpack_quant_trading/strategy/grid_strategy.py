"""
合约网格交易策略
类似欧易（OKX）合约网格，自动在价格区间内高抛低吸
"""
import asyncio
import sys
import time
import threading
import websockets
import json
import uuid
from asyncio import Lock
from typing import List, Dict, Optional
from decimal import Decimal
from datetime import datetime
from dataclasses import dataclass
import pandas as pd

from ..core.api_client import ExchangeClient
from ..utils.logger import get_logger
logger = get_logger("grid_strategy")


@dataclass
class GridLevel:
    """网格层级"""
    price: float  # 价格
    order_id: Optional[str] = None  # 订单ID
    quantity: float = 0  # 数量
    side: str = "buy"  # buy/sell
    status: str = "idle"  # 状态机：idle -> pending -> closing -> idle
    filled_time: Optional[datetime] = None
    # Ostium 专用
    trade_index: Optional[int] = None
    pair_id: Optional[int] = None


class GridTradingStrategy:
    """合约网格交易策略"""
    
    def __init__(
        self,
        symbol: str,
        price_lower: float,
        price_upper: float,
        grid_count: int,
        investment_per_grid: float,
        leverage: int,
        api_client: ExchangeClient,
        data_client: Optional[ExchangeClient] = None,
        grid_mode: str = "long_short",
        instance_id: Optional[str] = None
    ):
        """
        初始化网格策略
        
        Args:
            symbol: 交易对（如ETH-USDT-SWAP）
            price_lower: 价格下限
            price_upper: 价格上限
            grid_count: 网格数量
            investment_per_grid: 单格投资（USDT）
            leverage: 杠杆倍数
            api_client: 交易执行客户端 (如 Ostium)
            data_client: 行情数据客户端 (固定使用 Backpack)，如果不提供则使用 api_client
            grid_mode: 网格类型 long_short=双向, long_only=做多网格, short_only=做空网格
            instance_id: 实例标识（多网格时用于区分，如 "ETH_long"）
        """
        self.instance_id = instance_id or f"{symbol}_{(grid_mode or 'long_short').strip().lower()}"
        self.symbol = symbol
        self.grid_mode = (grid_mode or "long_short").strip().lower()
        if self.grid_mode not in ("long_short", "long_only", "short_only"):
            self.grid_mode = "long_short"
        # 如果是 Ostium 交易，需要映射 symbol (例如 ETH-USDT-SWAP -> ETH-USD)
        # 这里暂时保留原始 symbol，在具体调用 API 时由各 Client 内部映射
        
        self.price_lower = price_lower
        self.price_upper = price_upper
        self.grid_count = grid_count
        self.investment_per_grid = investment_per_grid
        self.leverage = leverage
        
        self.api_client = api_client  # 执行端
        self.data_client = data_client or api_client  # 行情端 (默认 Backpack)
        
        # 根据执行端选择 WebSocket 与行情符号：Hyper / HIP-3 用 Hy 平台 WS，否则 Backpack
        client_name = getattr(api_client, '__class__', None).__name__
        self._is_hyper = client_name == 'HyperliquidAPIClient'
        self._is_backpack = 'Backpack' in client_name
        
        if self._is_hyper:
            self.data_symbol = self._map_to_hyper_coin(symbol)
            base_url = getattr(api_client, "base_url", None)
            ws_url = None
            if base_url:
                ws_url = base_url.replace("https://", "wss://").replace("http://", "wss://").rstrip("/") + "/ws"
            self.ws_client = HyperliquidWebSocketClient(self.data_symbol, ws_url=ws_url)
        else:
            self.data_symbol = self._map_to_data_symbol(symbol) if data_client else symbol
            self.ws_client = WebSocketClient("wss://ws.backpack.exchange")
        
        # 计算网格参数
        self.price_range = price_upper - price_lower
        self.grid_spacing = self.price_range / grid_count
        
        # 生成网格价格层级
        self.grid_levels: List[GridLevel] = []
        self._generate_grid_levels()
        
        # 运行状态
        self.running = False
        self.current_price = 0.0
        self._qty_precision = 4
        self._px_precision = 2
        self._monitor_task: Optional[asyncio.Task] = None
        
        # 冷却追踪：避免同一档位在短时间内反复开平
        self._grid_cooldown: Dict[int, float] = {}
        # --- 【新增】429 频率限制保护 ---
        self._429_cooldown_until = 0.0
        
        # 统计数据
        self.total_trades = 0
        self.total_profit = 0.0  # 【增强】累计已实现利润（平仓时更新）
        self.buy_count = 0
        self.sell_count = 0
        self.total_fees = 0.0  # 【新增】累计手续费
        self.unrealized_pnl = 0.0  # 【新增】未实现盈亏（估算）
        self.peak_profit = 0.0  # 【新增】峰值利润（用于回撤计算）
        self.max_drawdown = 0.0  # 【新增】最大回撤
        
        # 【新增】边界保护参数
        self.stop_loss_pct = 0.50  # 总亏损超过 50% 触发停止
        self.max_position_size = 0  # 最大持仓价值限制（启动时动态计算为余额的 20%）
        self.max_position_pct = 0.20  # 持仓占余额比例上限 20%
        self.current_position_value = 0.0  # 当前持仓总价值
        self.daily_loss_limit = investment_per_grid * grid_count * 0.30  # 日内最大亏损 30%
        self.daily_realized_pnl = 0.0  # 当日已实现盈亏
        self.last_reset_date = datetime.now().date()  # 日盈亏重置日期
        
        # 策略层缓存：Subgraph 返回空时用 pair_id 尝试平仓，避免「平仓不了」
        self._cached_pair_id: Optional[int] = None
        # 当 API 未返回 trade_index 时，按下单顺序给每个订单分配本地 index，用于平仓
        self._next_local_close_index: int = 0
        # 平仓单追踪：开仓成交后在相邻档挂限价平仓单；只有平仓成交后，才补回同价位开仓挂单。
        # order_id -> {'open_level_price': float, 'side': 'buy'|'sell', 'qty': float, 'open_price': float}
        self._closing_orders: Dict[str, dict] = {}
        
        logger.info(f"✅ 网格策略初始化完成 [{self.instance_id}]: {symbol}")
        logger.info(f"   网格类型: {self.grid_mode} (long_short=双向, long_only=做多, short_only=做空)")
        logger.info(f"   价格区间: ${price_lower:.2f} - ${price_upper:.2f}")
        logger.info(f"   网格数量: {grid_count}")
        logger.info(f"   网格间距: ${self.grid_spacing:.2f}")
        logger.info(f"   单格投资: ${investment_per_grid:.2f}")
        logger.info(f"   杠杆倍数: {leverage}x")
    
    def _generate_grid_levels(self):
        """生成网格价格层级"""
        self.grid_levels = []
        
        for i in range(self.grid_count + 1):
            price = self.price_lower + (i * self.grid_spacing)
            if self.grid_mode == "long_only":
                side = "buy"
            elif self.grid_mode == "short_only":
                side = "sell"
            else:
                # long_short: 由当前价决定下方买/上方卖，先给默认值
                side = "buy" if i < self.grid_count else "sell"
            grid = GridLevel(
                price=price,
                quantity=self.investment_per_grid * self.leverage / price,
                side=side
            )
            self.grid_levels.append(grid)
        
        logger.info(f"📊 生成 {len(self.grid_levels)} 个网格层级")
    
    async def start(self):
        """启动网格交易"""
        if self.running:
            logger.warning("⚠️ 网格策略已在运行中")
            return False
        
        logger.info("🚀 启动网格交易...")
        self.running = True
        
        # 【新增】获取资产数量和价格精度并修正网格
        try:
            qty_precision = 4 
            px_precision = 2
            
            if hasattr(self.api_client, 'get_quantity_precision'):
                qty_precision = await self.api_client.get_quantity_precision(self.symbol)
            elif self._is_hyper and hasattr(self.api_client, 'get_sz_decimals'):
                qty_precision = await self.api_client.get_sz_decimals(self.symbol)
                
            if hasattr(self.api_client, 'get_price_precision'):
                px_precision = await self.api_client.get_price_precision(self.symbol)
            
            logger.info(f"🎯 资产精度: 数量={qty_precision}, 价格={px_precision}")
            self._qty_precision = qty_precision
            self._px_precision = px_precision
            
            for grid in self.grid_levels:
                grid.quantity = round(grid.quantity, qty_precision)
                grid.price = round(grid.price, px_precision)
        except Exception as e:
            logger.warning(f"⚠️ 获取精度失败: {e}")
        
        # 查询余额（参考实盘交易）
        try:
            if hasattr(self.api_client, 'get_balance'):
                balance = await self.api_client.get_balance()
                # 修复：balance 可能是 dict 或 tuple，需要正确处理
                if isinstance(balance, dict):
                    usdc_balance = balance.get('USDC', 0)
                    logger.info(f"💰 账户余额: {usdc_balance:.2f} USDC")
                    # 【用户要求】取消策略端“保证金/持仓价值上限”限制：不再基于余额设置上限
                    self.max_position_size = 0
                    
                    # 计算总投资需求
                    total_investment = self.investment_per_grid * self.grid_count
                    if usdc_balance < total_investment:
                        logger.warning(f"⚠️ 余额可能不足: 需要 {total_investment:.2f} USDC, 当前 {usdc_balance:.2f} USDC")
                else:
                    logger.warning(f"⚠️ 余额返回格式异常: {type(balance)}, 跳过余额检查")
                    self.max_position_size = 0
        except Exception as e:
            logger.warning(f"⚠️ 查询余额失败: {e}，跳过余额检查")
            self.max_position_size = 0
        
        # 连接 WebSocket 并订阅价格（完全参考实盘）
        ws_connected = False
        try:
            logger.info("🔌 正在连接 WebSocket...")
            await self.ws_client.connect()
            # Hyper 在 connect() 内已订阅 allMids，这里仅 Backpack 需再订阅 ticker
            if not self._is_hyper:
                await self.ws_client.subscribe("ticker", self.data_symbol)
            
            # 等待接收首条价格数据
            for _ in range(5):  # 最多等待5次
                msg = await self.ws_client.receive()
                if self.ws_client.last_price > 0:
                    self.current_price = self.ws_client.last_price
                    logger.info(f"💰 初始价格 (WebSocket): ${self.current_price:.2f}")
                    ws_connected = True
                    break
                await asyncio.sleep(0.5)
            
            if not ws_connected:
                raise Exception("WebSocket 未返回有效价格")
                
        except Exception as e:
            logger.warning(f"⚠️ WebSocket 连接失败: {e}")
            logger.info("🔄 降级到 REST API 轮询模式...")
            
            # 备用方案：使用 REST API
            try:
                if hasattr(self.api_client, 'get_price'):
                    self.current_price = await self.api_client.get_price(self.symbol)
                    logger.info(f"💰 初始价格 (REST API): ${self.current_price:.2f}")
                else:
                    ticker = await self.data_client.get_ticker(self.data_symbol)
                    self.current_price = float(ticker.get('lastPrice') or ticker.get('price') or 0)
                    logger.info(f"💰 初始价格 (REST API): ${self.current_price:.2f}")
            except Exception as e2:
                logger.error(f"❌ REST API 也失败: {e2}")
                self.running = False
                return False
        
        # 在当前价格附近布置初始订单
        await self._place_initial_orders()
        
        # 启动监控循环（保存 task 以便 stop 时取消）
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        
        logger.info("✅ 网格交易启动成功")
        return True
    
    async def stop(self):
        """停止网格交易"""
        if not self.running:
            logger.warning("⚠️ 网格策略未运行")
            return False
        
        logger.info("🛑 停止网格交易...")
        self.running = False
        
        # 先取消监控任务，再关 WebSocket，避免 "Task was destroyed but it is pending"
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await asyncio.wait_for(self._monitor_task, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            self._monitor_task = None
        
        # 取消所有未成交订单
        await self._cancel_all_orders()
        
        # 平掉所有持仓（Ostium 等支持 get_positions + close_position 的客户端）
        await self._close_all_positions()
        
        # 关闭 WebSocket 连接
        await self.ws_client.close()
        # 关闭 Hyperliquid aiohttp session，避免 Unclosed client session
        if hasattr(self.api_client, 'close') and asyncio.iscoroutinefunction(getattr(self.api_client, 'close', None)):
            try:
                await self.api_client.close()
            except Exception as e:
                logger.debug(f"关闭 api_client: {e}")
        
        # 给 gql/aiohttp 等收尾时间，减少 shutdown 时 pycares 回调触发的 RuntimeError: Event loop is closed
        try:
            await asyncio.sleep(0.6)
        except (asyncio.CancelledError, RuntimeError):
            pass
        
        logger.info("✅ 网格交易已停止")
        return True
    
    async def _close_all_positions(self):
        """平掉当前交易对下所有持仓（用于停止网格时清仓）。仅当 api_client 支持 get_positions 与 close_position 时执行。
        停止时不再调 get_positions，避免 gql 触发 DNS 导致 RuntimeError: Event loop is closed。
        仅用订单缓存的 (pair_id, trade_index) 平仓；若界面仍有持仓未平，请单独运行: python test_grid_close.py --close-only"""
        if not hasattr(self.api_client, 'get_positions') or not hasattr(self.api_client, 'close_position'):
            logger.debug("当前客户端不支持「停止时平仓」，跳过平仓步骤")
            return
        # Hyper：按 symbol 平仓（实盘逻辑，get_positions + reduce_only）
        if self._is_hyper:
            try:
                positions = await self.api_client.get_positions(symbol=self.symbol)
                for pos in positions:
                    sym = pos.get('symbol')
                    if not sym:
                        continue
                    try:
                        res = await self.api_client.close_position(sym)
                        if res.get('status') in ('CLOSED', 'FILLED', 'closed', 'filled'):
                            logger.info(f"✅ 平仓成功(Hyper): {sym}")
                        else:
                            logger.warning(f"⚠️ 平仓结果(Hyper): {res}")
                    except Exception as e:
                        logger.error(f"❌ 平仓失败 Hyper {sym}: {e}")
            except Exception as e:
                logger.error(f"❌ Hyper 获取持仓/平仓失败: {e}")
            logger.info("🔄 网格平仓步骤结束（Hyper 按 symbol 平仓）")
            return
        # Ostium：停止时不调 get_positions，仅用订单缓存的 (pair_id, trade_index) 逐个平
        seen: set = set()
        for grid in self.grid_levels:
            pid, idx = grid.pair_id, grid.trade_index
            if pid is None or idx is None:
                continue
            key = (int(pid), int(idx))
            if key in seen:
                continue
            seen.add(key)
            try:
                res = await self.api_client.close_position(key[0], key[1])
                if res.get('status') in ('CLOSED', 'FILLED', 'closed', 'filled'):
                    logger.info(f"✅ 平仓成功(订单缓存): pair_id={key[0]}, index={key[1]}")
                else:
                    logger.warning(f"⚠️ 平仓结果(订单缓存): {res}")
            except Exception as e:
                logger.debug(f"平仓 pair_id={key[0]} index={key[1]} 失败(可能已平或链上 index 不一致): {e}")
        logger.info(
            "🔄 网格平仓步骤结束（仅用订单缓存平仓，未调 get_positions 以免 Event loop is closed）。"
            "若界面仍有持仓未平，请单独运行: python test_grid_close.py --close-only"
        )
    
    async def _place_initial_orders(self):
        """布置初始订单。
        long_only: 区间内全部挂多单（用户要求：上下限之间全多）；
        short_only: 区间内全部挂空单（用户要求：上下限之间全空）；
        long_short: 下方多单、上方空单。
        """
        logger.info(f"📝 开始布置初始网格订单 (模式: {self.grid_mode}, 当前价: ${self.current_price:.2f})...")
        
        for grid in self.grid_levels:
            if self.grid_mode == "long_only":
                grid.side = "buy"
                await self._place_grid_order(grid)
            elif self.grid_mode == "short_only":
                grid.side = "sell"
                await self._place_grid_order(grid)
            else:
                # long_short 双向：维持原样（下方买、上方卖）
                if grid.price < self.current_price:
                    grid.side = "buy"
                    await self._place_grid_order(grid)
                elif grid.price > self.current_price:
                    grid.side = "sell"
                    await self._place_grid_order(grid)
        
        logger.info(f"✅ 初始订单布置完成 ({self.grid_mode})")
    
    async def _place_grid_order(self, grid: GridLevel):
        """下网格订单。增加 429 限频处理与挂单间隔。"""
        try:
            # 【边界保护 1】检查日内亏损限制
            await self._check_daily_loss_limit()
            
            # 【边界保护 2】检查总亏损限制
            if not await self._check_total_loss_limit():
                logger.error(f"⚠️ 【边界保护】总亏损超限，拒绝开仓")
                grid.status = "error"
                return
            
            # 【用户要求】取消“网格下单保证金/持仓价值限制”以及 long_only/short_only 的价格方向拦截。
            # 说明：交易所自身仍会有最小下单额/保证金/风控限制，策略端无法绕过。

            # 【重要】避免“可成交限价单”导致无限循环成交（你截图里反复 2083 成交的根因）：
            # - BUY 必须挂在当前价下方；SELL 必须挂在当前价上方；否则交易所会立刻按盘口最优价成交
            if self.current_price and self.current_price > 0:
                if grid.side == "buy" and grid.price >= self.current_price:
                    grid.status = "idle"
                    return
                if grid.side == "sell" and grid.price <= self.current_price:
                    grid.status = "idle"
                    return

            # 强制添加挂单间隔，避免 429
            await asyncio.sleep(0.2)
            
            # 避免重复逻辑：如果已有同价位的挂单，直接复用
            if (self._is_hyper or self._is_backpack) and hasattr(self.api_client, "get_open_orders"):
                try:
                    opens = await self.api_client.get_open_orders(symbol=self.symbol)
                    side_want = "BUY" if grid.side == "buy" else "SELL"
                    for o in opens:
                        if o.get("reduce_only") or o.get("post_only") is True: # 平仓单不复用作开仓单
                            continue
                        if (o.get("side") or "").upper() != side_want:
                            continue
                        px = float(o.get("price") or 0)
                        if abs(px - grid.price) <= max(0.5 * self.grid_spacing, 0.01):
                            # 【修复】兼容 Backpack 的 ID 字段
                            oid = o.get("id") or o.get("orderId") or o.get("oid")
                            if oid is not None:
                                grid.order_id = str(oid)
                                grid.status = "pending"
                                logger.warning(f"【网格】♻️ 成功复用已有挂单: {grid.side.upper()} @ ${grid.price:.2f}, ID={oid}")
                                return
                except Exception as e:
                    logger.debug(f"检查已有挂单失败: {e}")

            logger.info(f"📝 准备下单: {grid.side.upper()} @ ${grid.price:.2f}, 数量: {grid.quantity:.4f} {self.symbol.split('_')[0] if '_' in self.symbol else self.symbol}")
            
            # 【Backpack 特殊处理】检查最小下单金额 (通常需 > 5 USDC)
            if self._is_backpack:
                order_value = grid.quantity * grid.price
                if order_value < 5.0:
                    logger.error(f"❌ Backpack 下单金额 ${order_value:.2f} 太小 (需 > 5 USDC)，请调高投资额或杠杆")
                    grid.status = "error"
                    return

            response = await self.api_client.execute_order(
                symbol=self.symbol,
                side='BUY' if grid.side == 'buy' else 'SELL',
                quantity=grid.quantity,
                order_type='LIMIT',
                price=grid.price,
                max_leverage=self.leverage
            )
            
            if isinstance(response, dict) and response.get('status') in ('FAILED',):
                err = str(response.get('error') or response.get('message') or '未知')
                if "429" in err:
                    logger.warning("⚠️ 触发 API 限频 (429)，等待 5 秒...")
                    await asyncio.sleep(5)
                logger.error(f"❌ 挂单被交易所拒绝: {grid.side.upper()} @ ${grid.price:.2f} — {err}")
                grid.status = "error"
                return

            if isinstance(response, dict):
                grid.order_id = response.get('orderId') or response.get('tx_hash') or response.get('id')
                grid.trade_index = response.get('trade_index') or response.get('index')
                grid.pair_id = response.get('pair_id')
                if grid.pair_id is not None and self._cached_pair_id is None:
                    self._cached_pair_id = grid.pair_id
                if grid.trade_index is None and grid.pair_id is not None:
                    grid.trade_index = self._next_local_close_index
                    self._next_local_close_index += 1
            
            grid.status = "pending"
            logger.info(f"📌 挂单成功: {grid.side.upper()} @ ${grid.price:.2f}, ID: {grid.order_id or '(待确认)'}")
            
        except Exception as e:
            if "429" in str(e):
                logger.warning("⚠️ 触发 API 限频 (429)，休眠 5 秒...")
                await asyncio.sleep(5)
            logger.error(f"❌ 挂单异常: {grid.side.upper()} @ ${grid.price:.2f} — {e}")
            grid.status = "error"
            # 只有在真正异常时才标记为 error，不再在异常处理里打印“成功”日志
            
    def _map_to_hyper_coin(self, symbol: str) -> str:
        """将交易对映射为 Hyperliquid 的 coin（如 ETH、BTC），用于 WS allMids 与下单。"""
        s = (symbol or "").upper().replace("-", "").replace("_", "").replace("USDT", "").replace("USDC", "").replace("USD", "")
        if not s:
            return "ETH"
        for c in ["ETH", "BTC", "SOL", "AVAX", "ARB", "OP", "DOGE", "XRP", "LINK", "MATIC", "SUI", "APT", "PEPE", "WIF", "BNB", "ATOM", "NEAR", "INJ", "TIA", "SEI", "JUP", "STRK", "ENA", "ETC", "FIL", "LTC", "BCH", "ADA", "DOT", "UNI", "AAVE", "CRV", "MKR", "SNX", "COMP"]:
            if c in s or s in c:
                return c
        return s[:6] if len(s) > 6 else s

    def _map_to_data_symbol(self, symbol: str) -> str:
        """将交易对映射为 Backpack 格式行情对
        
        映射规则：
        - ETH-USD, ETH-USDT-SWAP, ETH-USDT -> ETH_USDC_PERP
        - SOL-USD, SOL-USDT-SWAP, SOL-USDT -> SOL_USDC_PERP
        - BTC-USD, BTC-USDT-SWAP, BTC-USDT -> BTC_USDC_PERP
        """
        # 标准化：转大写，统一分隔符
        normalized = symbol.upper().replace("-", "_").replace("USDT", "USDC")
        
        # 提取币种名称
        if "ETH" in normalized:
            return "ETH_USDC_PERP"
        elif "SOL" in normalized:
            return "SOL_USDC_PERP"
        elif "BTC" in normalized:
            return "BTC_USDC_PERP"
        else:
            # 兜底：如果无法识别，返回处理后的格式
            logger.warning(f"⚠️ 未识别的交易对格式: {symbol}，使用默认映射: {normalized}")
            return normalized

    async def _monitor_loop(self):
        """监控循环（WebSocket 优先，REST API 备用）"""
        logger.info("👀 开始监控网格订单...")
        
        # 判断是否使用 WebSocket
        use_websocket = self.ws_client._is_connected()
        if use_websocket:
            logger.info("✅ 使用 WebSocket 实时数据")
        else:
            logger.info("⚠️ 使用 REST API 轮询（2秒间隔）")
        
        while self.running:
            try:
                # --- 【新增】429 频率限制熔断 ---
                now = time.time()
                if now < self._429_cooldown_until:
                    await asyncio.sleep(5)
                    continue
                # ----------------------------
                if use_websocket:
                    # WebSocket 模式
                    if not self.ws_client._is_connected():
                        logger.warning("⚠️ WebSocket 断开，尝试重连...")
                        try:
                            await self.ws_client.connect()
                            await self.ws_client.subscribe("ticker" if not self._is_hyper else "allMids", self.data_symbol)
                        except Exception as e:
                            logger.error(f"❌ 重连失败: {e}，切换到 REST API")
                            use_websocket = False
                            continue
                    
                    msg = await self.ws_client.receive()
                    if msg and self.ws_client.last_price > 0:
                        self.current_price = self.ws_client.last_price
                else:
                    # REST API 模式
                    if hasattr(self.api_client, 'get_price'):
                        self.current_price = await self.api_client.get_price(self.symbol)
                    else:
                        ticker = await self.data_client.get_ticker(self.data_symbol)
                        self.current_price = float(ticker.get('lastPrice') or ticker.get('price') or 0)
                    
                    await asyncio.sleep(2)  # REST API 需要间隔
                
                if self.current_price == 0:
                    logger.warning(f"⚠️ 无法获取 {self.data_symbol} 实时价格，跳过监控...")
                    await asyncio.sleep(2)
                    continue

                # 检查订单状态 (在执行端 api_client 上检查)
                await self._check_filled_orders()
                
                # 每 10 秒打一条当前价（INFO），便于确认 WebSocket 在持续更新
                if self._is_hyper:
                    last_log = getattr(self, "_last_price_log_time", 0)
                    if time.time() - last_log >= 10:
                        logger.info(f"📡 Hy WebSocket 最新价: ${self.current_price:.2f} ({self.data_symbol})")
                        self._last_price_log_time = time.time()
                    elif last_log == 0:
                        self._last_price_log_time = time.time()
                
            except Exception as e:
                logger.error(f"❌ 监控循环错误: {e}")
                await asyncio.sleep(10)
        
        logger.info("✅ 监控循环已停止")
    
    async def _check_filled_orders(self):
        """检查成交订单。严格区分：固定网格档位(开仓) 和 追踪字典(平仓)"""
        now = time.time()
        
        # 1. 抓取快照
        active_oids = None
        if self._is_backpack:
            try:
                opens = await self.api_client.get_open_orders(symbol=self.symbol)
                active_oids = {str(o.get('orderId') or o.get('id')) for o in opens}
            except Exception as e:
                logger.debug(f"获取挂单列表失败: {e}")

        # 2. 处理【开多/开空】档位的成交 -> 挂平仓单
        for grid in self.grid_levels:
            if grid.status == "pending" and grid.order_id:
                try:
                    is_filled = False
                    # 优先查快照 (仅限 Backpack)
                    if self._is_backpack and active_oids is not None:
                        if str(grid.order_id) not in active_oids:
                            order = await self.api_client.get_order(grid.order_id, symbol=self.symbol)
                            status = (order.get('status') or '').upper()
                            if status in ['FILLED', 'COMPLETE', 'CLOSED', 'NOT_FOUND']:
                                is_filled = True
                    
                    if not is_filled:
                        order = await self.api_client.get_order(grid.order_id, symbol=self.symbol)
                        status = (order.get('status') or '').upper()
                        # HY 平台保留其原始判定：仅限 FILLED 类状态
                        if status in ['FILLED', 'COMPLETE', 'CLOSED']:
                            is_filled = True
                        elif self._is_backpack and status == 'NOT_FOUND':
                            is_filled = True
                    
                    if is_filled:
                        if now - self._grid_cooldown.get(id(grid), 0) < 5: continue
                        self._grid_cooldown[id(grid)] = now
                        # 为 HY 平台提取成交价，Backpack 使用网格价
                        f_px = float(order.get('price') or 0) if order else None
                        await self._handle_filled_order(grid, fill_price=f_px)
                except Exception as e:
                    err_msg = str(e)
                    if "429" in err_msg:
                        logger.warning(f"⚠️ [网格] 触发 Backpack 频率限制 (429)，熔断 60 秒...")
                        self._429_cooldown_until = time.time() + 60
                        break # 退出当前检查，进入大循环冷却
                    logger.debug(f"检查开多/开空单 {grid.order_id} 失败: {e}")

        # 3. 处理【平仓单】的成交 -> 统计利润 + 平仓后补回同档位开仓单
        for oid, info in list(self._closing_orders.items()):
            try:
                if oid.startswith("_no_oid_"):
                    if now - info.get("_ts", 0) > 10:
                        # 无 oid 的平仓单：重试补挂
                        open_price = float(info.get("open_price") or 0)
                        open_level_price = float(info.get("open_level_price") or 0)
                        open_side = info.get("side")
                        qty = float(info.get("qty") or 0)
                        if open_price > 0 and open_side in ("buy", "sell") and qty > 0:
                            close_side = "SELL" if open_side == "buy" else "BUY"
                            close_price = self._get_close_price_by_level(open_level_price or open_price, open_side)
                            close_price = round(close_price, self._px_precision)
                            logger.warning(f"🔄 自动重试：补挂平仓单 {close_side} @ ${close_price:.2f} (qty={qty:.4f})")
                            new_oid = await self._place_closing_order(close_price, close_side, qty, open_price=open_price, urgent=True)
                            if new_oid:
                                del self._closing_orders[oid]
                                self._closing_orders[str(new_oid)] = info
                            else:
                                info["_ts"] = time.time()
                    continue
                
                is_filled = False
                order = None

                # Backpack：如果快照里已经不存在该 oid，才去查详情确认成交/取消
                if self._is_backpack and active_oids is not None:
                    if oid not in active_oids:
                        order = await self.api_client.get_order(oid, symbol=self.symbol)
                else:
                    # 其它平台/或快照不可用：直接查订单状态
                    order = await self.api_client.get_order(oid, symbol=self.symbol)

                if order:
                    st = (order.get('status') or '').upper()
                    if st in ['FILLED', 'COMPLETE', 'CLOSED'] or (self._is_backpack and st == 'NOT_FOUND'):
                        is_filled = True
                    elif st == 'CANCELLED':
                        logger.warning(f"【网格】⚠️ 平仓单 {oid} 被取消，重新补挂")
                        del self._closing_orders[oid]
                        # 重新补挂平仓单（不重新触发开仓逻辑）
                        open_price = float(info.get("open_price") or 0)
                        open_level_price = float(info.get("open_level_price") or 0)
                        open_side = info.get("side")
                        qty = float(info.get("qty") or 0)
                        if open_price > 0 and open_side in ("buy", "sell") and qty > 0:
                            close_side = "SELL" if open_side == "buy" else "BUY"
                            close_price = self._get_close_price_by_level(open_level_price or open_price, open_side)
                            close_price = round(close_price, self._px_precision)
                            new_oid = await self._place_closing_order(close_price, close_side, qty, open_price=open_price, urgent=True)
                            if new_oid:
                                self._closing_orders[str(new_oid)] = info
                        continue

                if is_filled:
                    del self._closing_orders[oid]
                    
                    # 【新增】计算并统计利润
                    await self._calculate_and_record_profit(info, order)
                    lvl = info.get("open_level_price") or info.get("open_price") or 0
                    logger.warning(f"【网格】✅ 平仓成交: 档位 ${float(lvl):.2f} 已记录利润")

                    # 【按用户要求】只有平仓后才补回同价位开仓挂单
                    open_level_price = float(info.get("open_level_price") or 0)
                    open_side = info.get("side")  # 'buy'|'sell'
                    if open_level_price > 0 and open_side in ("buy", "sell"):
                        # 找到最接近该档位的 GridLevel
                        target = None
                        best = None
                        for g in self.grid_levels:
                            d = abs(float(g.price) - float(open_level_price))
                            if best is None or d < best:
                                best = d
                                target = g
                        if target is not None:
                            target.side = open_side
                            target.order_id = None
                            target.status = "idle"
                            self._grid_cooldown[id(target)] = time.time()
                            await self._place_grid_order(target)
            except Exception as e:
                logger.debug(f"检查平仓单 {oid} 失败: {e}")

        # 4. 安全补位：仅对 idle 档位（例如撤单/异常导致）进行下单
        for grid in self.grid_levels:
            if grid.status == "idle" and not grid.order_id:
                # 缩短保护，避免长时间空档
                if now - self._grid_cooldown.get(id(grid), 0) < 2:
                    continue
                
                should_place = False
                if self.grid_mode == "long_only":
                    grid.side = "buy"
                    should_place = True
                elif self.grid_mode == "short_only":
                    grid.side = "sell"
                    should_place = True
                elif self.grid_mode == "long_short":
                    if grid.price < self.current_price: grid.side = "buy"; should_place = True
                    elif grid.price > self.current_price: grid.side = "sell"; should_place = True
                
                if should_place:
                    grid.status = "placing" # 状态锁
                    self._grid_cooldown[id(grid)] = now
                    await self._place_grid_order(grid)
    
    async def _place_closing_order(
        self,
        price: float,
        side: str,
        quantity: float,
        open_price: Optional[float] = None,
        urgent: bool = False,
    ) -> Optional[str]:
        """挂一笔限价平仓单。
        
        - 默认包含防重检查与轻微节流，减少重复 reduce-only 挂单与 429。
        - urgent=True：用于开仓成交后的“关键路径”，尽量跳过耗时检查、缩短 sleep，使平仓单更快出来。
        """
        if not hasattr(self.api_client, 'execute_order'):
            return None
        try:
            # 【防重检查】挂平仓单前，也查一次是否有同价位的 ReduceOnly 订单
            if (not urgent) and hasattr(self.api_client, "get_open_orders"):
                try:
                    opens = await self.api_client.get_open_orders(symbol=self.symbol)
                    for o in opens:
                        if not o.get("reduceOnly") and not o.get("reduce_only"):
                            continue
                        if (o.get("side") or "").upper() != side.upper():
                            continue
                        px = float(o.get("price") or 0)
                        if abs(px - price) < 0.1:
                            oid = o.get("id") or o.get("orderId")
                            logger.warning(f"【网格】♻️ 成功复用已有平仓挂单: {side} @ ${price:.2f}, ID={oid}")
                            return str(oid)
                except Exception:
                    pass

            # 平仓单：尽量快（尤其 urgent），但仍保留极小延迟避免过猛触发限频
            await asyncio.sleep(0.05 if urgent else 0.3)
            logger.warning(
                f"【网格】挂限价平仓单{'(urgent)' if urgent else ''}: {side} @ ${price:.2f}, 数量={quantity:.4f}"
            )
            resp = await self.api_client.execute_order(
                symbol=self.symbol,
                side=side.upper(),
                quantity=quantity,
                order_type='LIMIT',
                price=price,
                max_leverage=self.leverage,
                reduce_only=True,
            )
            if not isinstance(resp, dict) or resp.get('status') in ('FAILED',):
                err = str(resp.get('error') or resp.get('message') or resp)
                if "429" in err:
                    logger.warning("⚠️ 平仓单触发 429，等待中...")
                    await asyncio.sleep(1.5 if urgent else 5)
                logger.warning(f"【网格】挂限价平仓单失败: {err}")
                return None
            
            oid = resp.get('orderId') or resp.get('order_id') or resp.get('id')
            return str(oid) if oid else None
        except Exception as e:
            if "429" in str(e):
                await asyncio.sleep(1.5 if urgent else 5)
            logger.warning(f"【网格】挂平仓单异常: {e}")
        return None

    async def _handle_filled_order(self, grid: GridLevel, fill_price: Optional[float] = None):
        """处理【开仓单】成交：挂相邻平仓单；等待平仓成交后再补同档位开仓单。"""
        # 严格锁定，防止重复触发成交判定
        if grid.status in ("handling_fill", "closing"):
            return
        grid.status = "handling_fill"
        grid.filled_time = datetime.now()
        self.total_trades += 1
        base = grid.price if self._is_backpack else (fill_price if fill_price and fill_price > 0 else grid.price)
        
        # 【新增】更新持仓价值
        position_value = grid.quantity * base
        self.current_position_value += position_value
        logger.info(f"📊 【持仓统计】开仓 ${position_value:.2f}，总持仓: ${self.current_position_value:.2f}")

        if grid.side == "buy":
            self.buy_count += 1
            # 平仓价严格使用相邻网格价位，避免 round 后“偏档”（例如 2083 应该平到 2081）
            upper = self._find_next_upper_grid(grid)
            close_price = float(upper.price) if upper else round(base + self.grid_spacing, self._px_precision)
            logger.warning(f"【网格】✅ 开多成交: ${grid.price:.2f} -> 挂平多单 @ ${close_price:.2f}")
            oid = None
            for attempt in range(3):
                oid = await self._place_closing_order(close_price, "SELL", grid.quantity, open_price=base, urgent=True)
                if oid:
                    break
                # 快速重试，避免偶发网络/撮合延迟导致没挂上
                await asyncio.sleep(0.12 * (attempt + 1))
            info = {"open_level_price": grid.price, "side": "buy", "qty": grid.quantity, "_ts": time.time(), "open_price": base}
            if oid:
                self._closing_orders[str(oid)] = info
            else:
                self._closing_orders[f"_no_oid_{id(grid)}"] = info
        else:
            self.sell_count += 1
            lower = self._find_next_lower_grid(grid)
            close_price = float(lower.price) if lower else round(base - self.grid_spacing, self._px_precision)
            logger.warning(f"【网格】✅ 开空成交: ${grid.price:.2f} -> 挂平空单 @ ${close_price:.2f}")
            oid = None
            for attempt in range(3):
                oid = await self._place_closing_order(close_price, "BUY", grid.quantity, open_price=base, urgent=True)
                if oid:
                    break
                await asyncio.sleep(0.12 * (attempt + 1))
            info = {"open_level_price": grid.price, "side": "sell", "qty": grid.quantity, "_ts": time.time(), "open_price": base}
            if oid:
                self._closing_orders[str(oid)] = info
            else:
                self._closing_orders[f"_no_oid_{id(grid)}"] = info

        # 【按用户要求】不立即补同价位开仓单；该档位进入“等待平仓”状态
        grid.order_id = None
        grid.status = "closing"
    
    def _find_upper_grid(self, current_grid: GridLevel) -> Optional[GridLevel]:
        """找到上方的网格（仅用于旧逻辑：要求 status != pending）"""
        for grid in self.grid_levels:
            if grid.price > current_grid.price and grid.status != "pending":
                return grid
        return None

    def _find_next_upper_grid(self, current_grid: GridLevel) -> Optional[GridLevel]:
        """找到正上方相邻一档（仅按价格，用于挂限价平仓单）。开多后在此档挂限价卖平仓。"""
        cand = None
        for grid in self.grid_levels:
            if grid.price > current_grid.price:
                if cand is None or grid.price < cand.price:
                    cand = grid
        return cand

    def _find_next_lower_grid(self, current_grid: GridLevel) -> Optional[GridLevel]:
        """找到正下方相邻一档（仅按价格，用于挂限价平仓单）。开空后在此档挂限价买平仓。"""
        cand = None
        for grid in self.grid_levels:
            if grid.price < current_grid.price:
                if cand is None or grid.price > cand.price:
                    cand = grid
        return cand

    def _get_close_price_by_level(self, open_level_price: float, open_side: str) -> float:
        """根据开仓所在档位价格，返回应挂的平仓档位价格（严格相邻档）。"""
        if not open_level_price or open_level_price <= 0:
            return open_level_price
        # 找到最接近的档位
        cur = None
        best = None
        for g in self.grid_levels:
            d = abs(float(g.price) - float(open_level_price))
            if best is None or d < best:
                best = d
                cur = g
        if cur is None:
            return open_level_price
        if open_side == "buy":
            up = self._find_next_upper_grid(cur)
            return float(up.price) if up else float(open_level_price + self.grid_spacing)
        else:
            low = self._find_next_lower_grid(cur)
            return float(low.price) if low else float(open_level_price - self.grid_spacing)

    def _find_lower_grid(self, current_grid: GridLevel) -> Optional[GridLevel]:
        """找到下方的网格（仅用于旧逻辑：要求 status != pending）"""
        for grid in reversed(self.grid_levels):
            if grid.price < current_grid.price and grid.status != "pending":
                return grid
        return None
    
    async def _cancel_all_orders(self):
        """取消所有订单（含网格开仓单与平仓单）"""
        logger.info("🚫 取消所有网格订单...")
        
        cancelled_count = 0
        for oid in list(self._closing_orders.keys()):
            try:
                if isinstance(oid, str) and oid.startswith("_no_oid_"):
                    del self._closing_orders[oid]
                    cancelled_count += 1
                    continue
                if hasattr(self.api_client, 'cancel_order_async'):
                    await self.api_client.cancel_order_async(symbol=self.symbol, order_id=oid)
                else:
                    await self.api_client.cancel_order(symbol=self.symbol, order_id=oid)
                del self._closing_orders[oid]
                cancelled_count += 1
                logger.info(f"✅ 取消平仓单: {oid}")
            except Exception as e:
                logger.debug(f"取消平仓单 {oid}: {e}")
        for grid in self.grid_levels:
            if grid.status == "pending" and grid.order_id:
                try:
                    # 兼容性处理: 如果是 Ostium, 优先使用 pair_id:index 格式撤单
                    cancel_id = grid.order_id
                    if grid.pair_id is not None and grid.trade_index is not None:
                        cancel_id = f"{grid.pair_id}:{grid.trade_index}"
                    
                    # 检查客户端是否有异步撤单方法
                    if hasattr(self.api_client, 'cancel_order_async'):
                        await self.api_client.cancel_order_async(symbol=self.symbol, order_id=cancel_id)
                    else:
                        await self.api_client.cancel_order(symbol=self.symbol, order_id=cancel_id)
                        
                    grid.status = "cancelled"
                    cancelled_count += 1
                    logger.info(f"✅ 取消订单: {cancel_id}")
                except Exception as e:
                    logger.error(f"❌ 取消订单 {grid.order_id} 失败: {e}")
        
        logger.info(f"✅ 共取消 {cancelled_count} 个订单")
    
    # ==================== 【新增】边界保护方法 ====================
    
    async def _check_daily_loss_limit(self):
        """检查并重置日内亏损限制"""
        today = datetime.now().date()
        if today != self.last_reset_date:
            self.daily_realized_pnl = 0.0
            self.last_reset_date = today
            logger.info(f"📅 日内盈亏已重置，新的一天开始: {today}")
        
        if self.daily_realized_pnl < -self.daily_loss_limit:
            logger.error(f"⚠️ 【边界保护】日内亏损超限: ${self.daily_realized_pnl:.2f} < -${self.daily_loss_limit:.2f}，正在停止策略...")
            await self.stop()
    
    async def _check_total_loss_limit(self) -> bool:
        """检查总亏损是否超限"""
        total_investment = self.investment_per_grid * self.grid_count
        loss_threshold = total_investment * self.stop_loss_pct
        
        if self.total_profit < -loss_threshold:
            logger.error(f"⚠️ 【边界保护】总亏损超限: ${self.total_profit:.2f} < -${loss_threshold:.2f} (投资 ${total_investment:.2f} 的 {self.stop_loss_pct*100:.0f}%)")
            await self.stop()
            return False
        return True
    
    async def _calculate_and_record_profit(self, close_info: dict, order_data: dict = None):
        """平仓后计算并记录利润，更新统计数据"""
        open_price = float(close_info.get("open_price") or 0)
        open_level_price = float(close_info.get("open_level_price") or 0)
        qty = float(close_info.get("qty") or 0)
        open_side = close_info.get("side")  # 'buy' 或 'sell'
        if not open_side or qty <= 0:
            return
        if open_price <= 0:
            open_price = open_level_price
        
        # 尝试从订单数据获取平仓价格
        close_price = None
        if order_data and isinstance(order_data, dict):
            close_price = float(order_data.get('price') or order_data.get('avgPrice') or 0)
        
        # 如果没有平仓价，使用理论平仓价（根据网格间距计算）
        if not close_price or close_price == 0:
            if open_side == "buy":
                close_price = open_price + self.grid_spacing
            else:
                close_price = open_price - self.grid_spacing
        
        # 计算利润
        if open_side == "buy":
            # 多单: 平仓价 - 开仓价
            profit = (close_price - open_price) * qty
        else:
            # 空单: 开仓价 - 平仓价
            profit = (open_price - close_price) * qty
        
        # 计算手续费（假设 0.04% 的 taker 费率）
        fee_rate = 0.0004
        open_fee = open_price * qty * fee_rate
        close_fee = close_price * qty * fee_rate
        total_fee = open_fee + close_fee
        
        # 净利润 = 毛利 - 手续费
        net_profit = profit - total_fee
        
        # 更新统计
        self.total_profit += net_profit
        self.total_fees += total_fee
        self.daily_realized_pnl += net_profit
        
        # 更新持仓价值
        position_value = qty * open_price
        self.current_position_value = max(0, self.current_position_value - position_value)
        
        # 更新峰值和回撤
        if self.total_profit > self.peak_profit:
            self.peak_profit = self.total_profit
        drawdown = self.peak_profit - self.total_profit
        if drawdown > self.max_drawdown:
            self.max_drawdown = drawdown
        
        logger.info(f"💰 【盈亏统计】平仓: {open_side.upper()} 开${open_price:.2f} 平${close_price:.2f} | "
                   f"单笔毛利: ${profit:.2f} | 手续费: ${total_fee:.2f} | 净利: ${net_profit:.2f}")
        logger.info(f"📊 【累计统计】总盈亏: ${self.total_profit:.2f} | 总手续费: ${self.total_fees:.2f} | "
                   f"峰值: ${self.peak_profit:.2f} | 最大回撤: ${self.max_drawdown:.2f} | 持仓: ${self.current_position_value:.2f}")
        logger.info(f"📅 【日内统计】已实现盈亏: ${self.daily_realized_pnl:.2f} / 限制: ${self.daily_loss_limit:.2f}")
    
    def get_status(self) -> Dict:
        """获取运行状态（增强版，包含详细盈亏统计）"""
        pending_orders = sum(1 for g in self.grid_levels if g.status == "pending")
        filled_orders = sum(1 for g in self.grid_levels if g.status == "filled")
        
        return {
            'running': self.running,
            'current_price': self.current_price,
            'total_trades': self.total_trades,
            'total_profit': self.total_profit,
            'buy_count': self.buy_count,
            'sell_count': self.sell_count,
            'pending_orders': pending_orders,
            'filled_orders': filled_orders,
            'grid_levels': len(self.grid_levels),
            # 【新增】详细统计
            'total_fees': self.total_fees,
            'unrealized_pnl': self.unrealized_pnl,
            'peak_profit': self.peak_profit,
            'max_drawdown': self.max_drawdown,
            'current_position_value': self.current_position_value,
            'daily_realized_pnl': self.daily_realized_pnl,
            'daily_loss_limit': self.daily_loss_limit,
            'max_position_size': self.max_position_size,
            'net_profit': self.total_profit - self.total_fees,
            'win_rate': (self.total_profit / (self.total_trades * self.grid_spacing * self.investment_per_grid / self.current_price) if self.total_trades > 0 else 0)
        }
    
    def get_grid_levels_df(self) -> pd.DataFrame:
        """获取网格层级DataFrame"""
        data = []
        for grid in self.grid_levels:
            data.append({
                'price': grid.price,
                'side': grid.side,
                'quantity': grid.quantity,
                'status': grid.status,
                'order_id': grid.order_id,
                'filled_time': grid.filled_time
            })
        
        return pd.DataFrame(data)


class HyperliquidWebSocketClient:
    """Hyperliquid / HIP-3 WebSocket 客户端：订阅 allMids 获取实时价格，用于网格行情。"""
    HYPER_WS_URL = "wss://api.hyperliquid.xyz/ws"
    HYPER_WS_TESTNET = "wss://api.hyperliquid-testnet.xyz/ws"

    def __init__(self, coin: str = "ETH", ws_url: str = None):
        self.base_url = (ws_url or self.HYPER_WS_URL).rstrip("/")
        if not self.base_url.endswith("/ws"):
            self.base_url = self.base_url + "/ws"
        self.coin = (coin or "ETH").upper()
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.running = False
        self.last_price = 0.0
        self._subscribed = False

    def _is_connected(self) -> bool:
        try:
            if self.ws is None:
                return False
            if hasattr(self.ws, 'state'):
                return self.ws.state == 1
            if hasattr(self.ws, 'open'):
                return self.ws.open
            return True
        except Exception:
            return False

    async def connect(self, max_retries: int = 3):
        if self._is_connected():
            return
        
        # --- 【新增】自适应代理支持 ---
        import os
        proxy_url = os.environ.get('HTTPS_PROXY') or os.environ.get('http_proxy') or os.environ.get('HTTP_PROXY')
        # ---------------------------

        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"正在连接 Hyperliquid WebSocket: {self.base_url} (第{attempt}/{max_retries}次)")
                self.ws = await asyncio.wait_for(
                    websockets.connect(
                        self.base_url,
                        ping_interval=30,
                        ping_timeout=30,
                        open_timeout=20,
                        proxy=proxy_url  # 【新增】支持代理
                    ),
                    timeout=30
                )
                logger.info("✅ Hyperliquid WebSocket 已连接")
                await self.subscribe("allMids", self.coin)
                return
            except Exception as e:
                last_error = e
                logger.warning(f"Hyper WebSocket 连接失败 (第{attempt}次): {e}")
                self.ws = None
                if attempt < max_retries:
                    await asyncio.sleep(2 ** attempt)
        raise ConnectionError(f"Hyperliquid WebSocket 连接失败: {last_error}")

    async def subscribe(self, channel: str, symbol: str):
        if not self._is_connected():
            return
        if channel == "allMids" or channel == "ticker":
            msg = {"method": "subscribe", "subscription": {"type": "allMids"}}
            await self.ws.send(json.dumps(msg))
            self._subscribed = True
            logger.info("✅ Hyperliquid 已订阅 allMids")

    async def receive(self):
        if not self._is_connected():
            raise ConnectionError("WebSocket未连接")
        try:
            message = await asyncio.wait_for(self.ws.recv(), timeout=60)
            data = json.loads(message)
            if isinstance(data, dict):
                ch = data.get("channel")
                payload = data.get("data")
                if ch == "allMids" and isinstance(payload, dict) and "mids" in payload:
                    mids = payload["mids"]
                    if isinstance(mids, dict) and self.coin in mids:
                        self.last_price = float(mids[self.coin])
                        if not getattr(self, "_logged_first_price", False):
                            self._logged_first_price = True
                            logger.info(f"📡 已接到 Hyperliquid WebSocket 价格: {self.coin}=${self.last_price:.2f}")
                        now = time.time()
                        if now - getattr(self, "_last_ws_info_log", 0) >= 10:
                            self._last_ws_info_log = now
                            logger.info(f"📡 Hy WS 最新价: {self.coin}=${self.last_price:.2f}")
                        logger.debug(f"Hy WS 价格更新: {self.coin}={self.last_price:.2f}")
                elif ch == "subscriptionResponse":
                    logger.debug("Hy WS 已确认订阅 allMids")
            return data
        except asyncio.TimeoutError:
            logger.warning("⚠️ Hyper WebSocket 接收超时")
            return None
        except json.JSONDecodeError:
            return None

    async def close(self):
        self.running = False
        if self.ws:
            try:
                await asyncio.wait_for(self.ws.close(), timeout=3.0)
            except (asyncio.TimeoutError, RuntimeError, Exception):
                pass
            self.ws = None


class WebSocketClient:
    """WebSocket客户端（完全参考live_trading.py实现）"""
    def __init__(self, base_url: str = "wss://ws.backpack.exchange"):
        self.base_url = base_url
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.subscriptions: Dict[str, set] = {}
        self.reconnect_delay = 1
        self.max_reconnect_delay = 60
        self.running = False
        self._lock = Lock()
        self.last_price = 0.0  # 保存最新价格

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
        """建立WebSocket连接"""
        if self._is_connected():
            logger.info("WebSocket已连接，跳过连接步骤")
            return

        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"正在连接WebSocket服务器: {self.base_url} (第{attempt}/{max_retries}次尝试)")
                self.ws = await asyncio.wait_for(
                    websockets.connect(
                        self.base_url,
                        ping_interval=30,
                        ping_timeout=30,
                        open_timeout=20
                    ),
                    timeout=30
                )
                logger.info("✅ WebSocket连接已建立")
                
                # 重连时需要重新订阅
                old_subscriptions = self.subscriptions.copy()
                self.subscriptions = {}
                for channel, symbols in old_subscriptions.items():
                    for symbol in symbols:
                        await self.subscribe(channel, symbol)
                self.reconnect_delay = 1
                return
                
            except asyncio.TimeoutError:
                last_error = "WebSocket连接超时"
                logger.error(f"❌ 连接超时 (第{attempt}/{max_retries}次尝试)")
                self.ws = None
                
                if attempt < max_retries:
                    wait_time = 2 ** attempt
                    logger.info(f"⏱️ {wait_time}秒后重试...")
                    await asyncio.sleep(wait_time)
                    
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                logger.error(f"❌ WebSocket连接失败: {last_error} (第{attempt}/{max_retries}次尝试)")
                self.ws = None
                
                if attempt < max_retries:
                    wait_time = 2 ** attempt
                    logger.info(f"⏱️ {wait_time}秒后重试...")
                    await asyncio.sleep(wait_time)
        
        error_msg = f"WebSocket连接失败，已重试{max_retries}次: {last_error}"
        logger.error(f"❌ {error_msg}")
        raise ConnectionError(error_msg)

    async def subscribe(self, channel: str, symbol: str):
        """订阅频道"""
        if not symbol:
            logger.error("订阅必须指定交易对symbol")
            return
        
        # 格式化频道名称
        formatted_channel = channel.replace(":", "_")
        
        # 标准化交易对格式
        standard_symbol = symbol if "_" in symbol else f"{symbol[:3]}_{symbol[3:]}"
        
        subscribe_key = f"{formatted_channel}.{standard_symbol}"
        
        subscribe_msg = {
            "id": str(uuid.uuid4()),
            "method": "SUBSCRIBE",
            "params": [subscribe_key]
        }
        
        msg_str = json.dumps(subscribe_msg, separators=(",", ":"), ensure_ascii=True)
        logger.info(f"发送订阅消息: {msg_str}")

        if self._is_connected():
            await self.ws.send(msg_str)
            if channel not in self.subscriptions:
                self.subscriptions[channel] = set()
            self.subscriptions[channel].add(standard_symbol)
            logger.info(f"✅ 订阅成功: {subscribe_key}")
        else:
            logger.error("WebSocket未连接，订阅失败")

    async def receive(self):
        """接收WebSocket消息"""
        if not self._is_connected():
            raise ConnectionError("WebSocket未连接")
        
        try:
            message = await asyncio.wait_for(self.ws.recv(), timeout=60)
            data = json.loads(message)
            
            # 解析价格数据
            if isinstance(data, dict) and 'data' in data:
                price_data = data['data']
                if isinstance(price_data, dict):
                    # Backpack ticker 格式
                    if 'c' in price_data:  # 最新价
                        self.last_price = float(price_data['c'])
                    elif 'lastPrice' in price_data:
                        self.last_price = float(price_data['lastPrice'])
                    elif 'price' in price_data:
                        self.last_price = float(price_data['price'])
            
            return data
        except asyncio.TimeoutError:
            logger.warning("⚠️ WebSocket接收超时")
            return None
        except json.JSONDecodeError:
            return None

    async def close(self):
        """关闭 WebSocket 连接，带超时和异常保护，避免 shutdown 时 RuntimeError: no running event loop"""
        self.running = False
        if self.ws:
            try:
                await asyncio.wait_for(self.ws.close(), timeout=3.0)
            except (asyncio.TimeoutError, RuntimeError, Exception):
                pass
            self.ws = None


# ==================== 多网格管理器 ====================

from typing import Dict, Optional, Tuple


class GridManager:
    """多网格管理器：支持同一账户运行多个网格（如多单+空单），或多账户多网格"""

    def __init__(self):
        self._grids: Dict[str, dict] = {}
        self._lock = threading.Lock()

    def _make_key(self, symbol: str, grid_mode: str, exchange: str = "", instance_id: Optional[str] = None) -> str:
        """生成网格唯一键。instance_id 用于同平台多账户区分"""
        if instance_id:
            return str(instance_id)
        base = f"{symbol}_{grid_mode}"
        return f"{base}_{exchange}" if exchange else base

    def add_and_start(
        self,
        symbol: str,
        price_lower: float,
        price_upper: float,
        grid_count: int,
        investment_per_grid: float,
        leverage: int,
        api_client: ExchangeClient,
        data_client: Optional[ExchangeClient] = None,
        grid_mode: str = "long_short",
        exchange: str = "backpack",
        instance_id: Optional[str] = None
    ) -> Tuple[bool, str]:
        """添加并启动一个网格。instance_id 可选，用于多账户/多平台时区分。返回 (成功, grid_id 或错误信息)"""
        grid_mode = (grid_mode or "long_short").strip().lower()
        key = self._make_key(symbol, grid_mode, exchange, instance_id)

        with self._lock:
            if key in self._grids and self._grids[key]["strategy"].running:
                return False, f"该网格已在运行: {key}"

            strategy = GridTradingStrategy(
                symbol=symbol,
                price_lower=price_lower,
                price_upper=price_upper,
                grid_count=grid_count,
                investment_per_grid=investment_per_grid,
                leverage=leverage,
                api_client=api_client,
                data_client=data_client,
                grid_mode=grid_mode,
                instance_id=key
            )

            def _run(strat):
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(strat.start())
                    if strat._monitor_task and not strat._monitor_task.done():
                        try:
                            loop.run_until_complete(strat._monitor_task)
                        except asyncio.CancelledError:
                            pass
                finally:
                    loop.close()

            thread = threading.Thread(target=_run, args=(strategy,), daemon=True)
            thread.start()

            self._grids[key] = {
                "strategy": strategy,
                "thread": thread,
                "exchange": exchange,
                "symbol": symbol,
                "grid_mode": grid_mode,
            }

        logger.info(f"📌 多网格: 已添加并启动 [{key}]")
        return True, key

    def stop(self, grid_id: str) -> bool:
        with self._lock:
            if grid_id not in self._grids:
                return False
            entry = self._grids[grid_id]
            strat = entry["strategy"]

        if not strat.running:
            with self._lock:
                if grid_id in self._grids:
                    del self._grids[grid_id]
            return True

        strat.running = False
        if strat._monitor_task and not strat._monitor_task.done():
            strat._monitor_task.cancel()

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(strat.stop())
        except Exception as e:
            logger.warning(f"停止网格 {grid_id} 时异常: {e}")
        finally:
            loop.close()

        with self._lock:
            if grid_id in self._grids:
                del self._grids[grid_id]

        logger.info(f"📌 多网格: 已停止 [{grid_id}]")
        return True

    def stop_all(self) -> int:
        with self._lock:
            keys = list(self._grids.keys())
        return sum(1 for k in keys if self.stop(k))

    def get_all(self) -> Dict[str, dict]:
        with self._lock:
            return {
                k: {
                    "symbol": v["symbol"],
                    "grid_mode": v["grid_mode"],
                    "exchange": v["exchange"],
                    "running": v["strategy"].running,
                    "current_price": getattr(v["strategy"], "current_price", 0),
                    "total_trades": getattr(v["strategy"], "total_trades", 0),
                }
                for k, v in self._grids.items()
            }

    def get_strategy(self, grid_id: str) -> Optional[GridTradingStrategy]:
        with self._lock:
            if grid_id in self._grids:
                return self._grids[grid_id]["strategy"]
        return None

    def get_primary_for_display(self) -> Optional[GridTradingStrategy]:
        with self._lock:
            for v in self._grids.values():
                if v["strategy"].running:
                    return v["strategy"]
        return None


grid_manager = GridManager()
