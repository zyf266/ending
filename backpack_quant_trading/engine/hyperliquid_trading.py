import asyncio
import logging
import random
import pytz
import os
from datetime import datetime
from typing import Optional, Dict, List, Any
from pydantic import BaseModel

from backpack_quant_trading.config.settings import config
from backpack_quant_trading.core.hyperliquid_client import HyperliquidAPIClient
from backpack_quant_trading.database.models import db_manager, Position, Trade

logger = logging.getLogger(__name__)

class TradingViewSignal(BaseModel):
    """信号模型（与 Ostium WebhookTradingEngine 一致，含意图解析字段）"""
    signal: str  # 'buy' 或 'sell' 或 'close'
    symbol: str  # 交易对，如 'ETH'
    price: Optional[float] = None
    strategy_name: Optional[str] = None
    instance_id: Optional[str] = None
    # TradingView 意图解析：先前仓位=long/short+大小≠0 → 平仓意图
    先前仓位: Optional[str] = None
    先前仓位大小: Optional[str] = None

class HyperliquidTradingEngine:
    """Hyperliquid Webhook 交易引擎 (参考 WebhookTradingEngine)"""
    
    def __init__(self, private_key: str = None, stop_loss_ratio: Optional[float] = None, 
                 take_profit_ratio: Optional[float] = None, 
                 instance_id: str = "", strategy_name: str = ""):
        # 优先使用传入的私钥，否则从配置中获取
        pk = private_key or config.hyperliquid.PRIVATE_KEY
        if not pk:
            logger.warning("⚠️ 未配置 Hyperliquid 私钥，将无法进行交易操作")
        self.client = HyperliquidAPIClient(private_key=pk)
        self.source = 'hyperliquid'
        self.symbol = config.ostium.SYMBOL # 默认
        self.leverage = config.ostium.LEVERAGE
        self.instance_id = instance_id
        self.strategy_name = strategy_name
            
        # 风险控制
        self.stop_loss_percent = stop_loss_ratio if stop_loss_ratio is not None else config.trading.STOP_LOSS_PERCENT
        self.take_profit_percent = take_profit_ratio if take_profit_ratio is not None else config.trading.TAKE_PROFIT_PERCENT
            
        # 状态变量
        self.current_position = None  # 'LONG', 'SHORT', or None
        self.is_stopped = False
        self.lock = None
        self.beijing_tz = pytz.timezone('Asia/Shanghai')
        self.forbidden_hours = [3, 4, 5, 6, 7, 13, 14, 19, 20]
        # 自愈逻辑（与 Ostium 一致）：连续相同开仓信号视为信号丢失
        self.last_signal = None   # 上一笔 signal：'buy'/'sell'/'close'
        self.last_intent = None  # 上一笔意图：'open'/'close'
        self.skip_next_opposite = False  # 强平自愈后跳过下一笔信号

    async def initialize(self):
        if self.lock is None:
            self.lock = asyncio.Lock()
        await self.sync_position()
        logger.info("Hyperliquid 交易引擎已初始化")

    async def sync_position(self):
        """同步持仓状态"""
        try:
            positions = await self.client.get_positions()
            # 简化逻辑：寻找匹配 symbol 的第一个持仓
            target_pos = next((p for p in positions if p['symbol'] == self.symbol), None)
            if target_pos:
                self.current_position = target_pos['side'].upper()
                logger.info(f"Hyperliquid 发现现有持仓: {self.current_position}")
            else:
                self.current_position = None
        except Exception as e:
            logger.error(f"同步 Hyperliquid 持仓失败: {e}")

    async def execute_signal(self, signal: TradingViewSignal, raw_payload: Optional[Dict[str, Any]] = None, *args, **kwargs):
        """执行 TV 信号。raw_payload 为 Webhook 原始 body，优先用于解析 先前仓位/先前仓位大小。"""
        if self.is_stopped:
            logger.warning("🛑 系统已熔断，停止接收信号")
            return

        try:
            async with self.lock:
                # 兼容性处理：如果信号中包含 symbol，且与当前引擎绑定的 symbol 不符，则跳过
                if signal.symbol and signal.symbol != self.symbol:
                    # 尝试进行模糊匹配 (如 ETH vs ETH/USD)
                    clean_signal_symbol = signal.symbol.split('/')[0].split('-')[0].upper()
                    clean_self_symbol = self.symbol.split('/')[0].split('-')[0].upper()
                    if clean_signal_symbol != clean_self_symbol:
                        logger.info(f"⏭️ 信号交易对 {signal.symbol} 与引擎交易对 {self.symbol} 不匹配，跳过")
                        return

                logger.info(f"🔔 收到信号: {signal.signal} ({signal.symbol})")

                # 与 Ostium 一致：根据「先前仓位」+「先前仓位大小」解析意图（开仓 vs 平仓）
                # 优先使用 Webhook 传入的 raw_payload，确保意图不丢失
                if isinstance(raw_payload, dict):
                    prev_pos = str(raw_payload.get('先前仓位') or 'flat').strip().lower()
                    prev_size = str(raw_payload.get('先前仓位大小') or '0').strip()
                else:
                    _dump = getattr(signal, 'model_dump', None) or getattr(signal, 'dict', None)
                    _raw = _dump() if callable(_dump) else {}
                    prev_pos = str(_raw.get('先前仓位') or getattr(signal, '先前仓位', None) or 'flat').strip().lower()
                    prev_size = str(_raw.get('先前仓位大小') or getattr(signal, '先前仓位大小', None) or '0').strip()
                if prev_pos == 'flat' and (prev_size == '0' or prev_size == '0.0'):
                    intent = "open"
                elif prev_pos in ['long', 'short'] and prev_size not in ('0', '0.0'):
                    intent = "close"
                else:
                    intent = "unknown"
                logger.info(f"解析意图: {intent} (先前仓位: {prev_pos}, 先前仓位大小: {prev_size})")

                signal_type = 'buy' if signal.signal in ['buy', 'long'] else ('sell' if signal.signal in ['sell', 'short'] else 'close')

                # === 信号丢失自愈逻辑（与 Ostium 一致）===
                # 1. 检测信号丢失：已有持仓 + 连续收到相同开仓信号 → 说明中间丢了平仓信号，强平自愈
                if self.current_position is not None and signal_type == self.last_signal and intent == "open" and self.last_intent == "open":
                    logger.warning(f"检测到信号丢失(已有{self.current_position}且收到重复{signal_type})，尝试强平自愈")
                    await self._close_position("信号丢失自愈强平")
                    self.skip_next_opposite = True
                    if callable(getattr(self, 'send_dingtalk_notification', None)):
                        await self.send_dingtalk_notification("检测到信号丢失：已尝试强平并进入同步模式。")
                    self.last_signal = signal_type
                    self.last_intent = intent
                    return

                # 2. 自愈模式：强平后跳过下一个信号，等待同步
                if self.skip_next_opposite:
                    logger.info(f"自愈中：跳过信号 {signal_type}，等待同步")
                    self.skip_next_opposite = False
                    self.last_signal = signal_type
                    self.last_intent = intent
                    return
                # ============================

                if signal.signal == 'close' or intent == "close":
                    self.last_signal = signal_type
                    self.last_intent = intent
                    await self._close_position("TV 信号平仓" if signal.signal == 'close' else "先前有仓位，按平仓逻辑")
                    return
                if intent == "open":
                    self.last_signal = signal_type
                    self.last_intent = intent
                    if signal.signal in ['buy', 'long']:
                        await self._handle_open('BUY')
                    elif signal.signal in ['sell', 'short']:
                        await self._handle_open('SELL')
                    return
                # 兼容：未识别意图时仍按 signal 开仓
                self.last_signal = signal_type
                self.last_intent = intent
                if signal.signal in ['buy', 'long']:
                    await self._handle_open('BUY')
                elif signal.signal in ['sell', 'short']:
                    await self._handle_open('SELL')
        except Exception as e:
            logger.error(f"❌ 执行信号失败 (实例 {self.instance_id}): {e}", exc_info=True)

    async def _handle_open(self, side: str):
        target_side = 'LONG' if side == 'BUY' else 'SHORT'
        
        # 1. 互平逻辑
        if self.current_position and self.current_position != target_side:
            await self._close_position(f"反向信号 {side} 触发平仓")
        
        if self.current_position == target_side:
            logger.info(f"已有 {target_side} 仓位，跳过")
            return

        # 2. 计算金额 (从环境变量获取，避免 "None" 导致 float 报错)
        raw = os.getenv(f"WEBHOOK_MARGIN_AMOUNT_{getattr(self, 'instance_id', '')}", "10.0")
        try:
            amount = float(raw) if raw and str(raw).strip().lower() != "none" else 10.0
        except (ValueError, TypeError):
            amount = 10.0
        if amount <= 0:
            amount = 10.0

        # 3. 执行下单
        logger.info(f"Hyperliquid 执行开仓: {target_side}, 金额: {amount}")
        res = await self.client.place_order(
            symbol=self.symbol,
            side=side,
            quantity=amount,
            order_type='MARKET',
            leverage=self.leverage
        )
        
        if res.get('status') == 'FILLED':
            self.current_position = target_side
            logger.info(f"✅ Hyperliquid 开仓成功: {res.get('orderId')}")

    async def _close_position(self, reason: str):
        if not self.current_position:
            logger.info("当前无仓位，无需平仓")
            return

        logger.info(f"🔥 执行平仓: {reason}")
        # Hyperliquid 平仓即发送反向 reduce_only 订单
        # 这里简化处理：获取当前所有仓位并针对 self.symbol 进行平仓
        positions = await self.client.get_positions()
        target_pos = next((p for p in positions if p['symbol'] == self.symbol), None)
        
        if target_pos:
            side = 'SELL' if target_pos['side'] == 'long' else 'BUY'
            # 数量即为持仓大小
            sz = abs(target_pos['size'])
            res = await self.client.place_order(
                symbol=self.symbol,
                side=side,
                quantity=sz,
                order_type='MARKET',
                reduce_only=True
            )
            if res.get('status') == 'FILLED':
                self.current_position = None
                logger.info("✅ Hyperliquid 平仓成功")
        else:
            self.current_position = None

    async def run_risk_monitor(self):
        """实时止损监控 (逻辑参考 WebhookTradingEngine)"""
        while not self.is_stopped:
            await asyncio.sleep(30)
            if self.current_position:
                # 监控逻辑...
                pass

    async def close(self):
        """关闭引擎，释放资源"""
        self.is_stopped = True
        try:
            await self.client.close()
            logger.info("Hyperliquid 引擎已关闭")
        except Exception as e:
            logger.error(f"关闭 Hyperliquid 客户端失败: {e}")
