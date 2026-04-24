"""
HYPE 自适应做空策略 (TradingView Webhook 开仓 + 平仓版)
- 开仓: 接收 TradingView Webhook sell 信号 → 市价开空
- 平仓: 接收 TradingView Webhook buy 信号  → 市价平空
- 本地实时风控 (5秒轮询):
    1. 止损: 价格 >= 止损价 → 平仓
    2. 止盈: 价格 <= 止盈价 → 平仓
    3. 保本: 盈利 >= break_even_pct(默认3%) → 止损移到成本价
"""

import asyncio
import logging
import os
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Any, Tuple

from pydantic import BaseModel

from backpack_quant_trading.config.settings import config
from backpack_quant_trading.core.hyperliquid_client import HyperliquidAPIClient

# ==================== 日志配置 ====================

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.handlers.clear()

log_dir = Path(config.log_dir) if hasattr(config, 'log_dir') else Path("./log")
log_dir.mkdir(parents=True, exist_ok=True)

log_file = log_dir / "hype_strategy.log"
file_handler = logging.FileHandler(log_file, encoding='utf-8')
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter(
    fmt='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
))
logger.addHandler(file_handler)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter(
    fmt='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%H:%M:%S'
))
logger.addHandler(console_handler)


# ==================== 信号模型 ====================

class TVSignal(BaseModel):
    """TradingView Webhook 信号模型"""
    交易品种: str = "ETH"
    价格: Optional[float] = None
    操作: str = ""              # 'sell' 开空, 'buy' 平空
    仓位方向: Optional[str] = None
    先前仓位大小: str = "0"

    @property
    def symbol(self) -> str:
        return self.交易品种

    @property
    def signal(self) -> str:
        return self.操作.lower()


# ==================== 策略管理器 ====================

class HYPEShortManager:
    """HYPE做空策略全局管理器（前端启动/停止/监控）"""

    def __init__(self):
        self._instances: Dict[str, dict] = {}
        self._lock = threading.Lock()

    def add_and_start(
        self,
        symbol: str,
        private_key: str,
        instance_id: Optional[str] = None,
        stop_loss_pct: float = 0.03,
        take_profit_pct: float = 0.06,
        break_even_pct: float = 0.03,
        margin_amount: float = 20.0,
        leverage: int = 50,
        kline_interval: str = "2h",   # 保留参数兼容前端，不再用于MACD
    ) -> Tuple[bool, str]:
        instance_id = instance_id or f"hype_short_{symbol}_{int(datetime.now().timestamp())}"

        with self._lock:
            if instance_id in self._instances:
                return False, f"实例已存在: {instance_id}"

            strategy = HYPEAdaptiveShortStrategy(
                symbol=symbol,
                private_key=private_key,
                instance_id=instance_id,
                stop_loss_pct=stop_loss_pct,
                take_profit_pct=take_profit_pct,
                break_even_pct=break_even_pct,
                margin_amount=margin_amount,
                leverage=leverage,
            )

            def _run(strat):
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(strat.run())
                except Exception as e:
                    logger.error(f"策略运行错误: {e}")
                finally:
                    loop.close()

            thread = threading.Thread(target=_run, args=(strategy,), daemon=True)
            thread.start()

            self._instances[instance_id] = {
                "strategy": strategy,
                "thread": thread,
                "symbol": symbol,
                "created_at": datetime.now()
            }

            logger.info(f"✅ HYPE做空策略已启动: {instance_id} ({symbol})")
            return True, instance_id

    def stop(self, instance_id: str) -> bool:
        with self._lock:
            if instance_id not in self._instances:
                return False

            instance = self._instances[instance_id]
            strategy = instance["strategy"]
            strategy._stop = True
            strategy.is_enabled = False

            if strategy.position == "SHORT":
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(strategy.close_position("用户停止策略"))
                    loop.close()
                except Exception as e:
                    logger.error(f"平仓失败: {e}")

            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(strategy.close())
                loop.close()
            except Exception as e:
                logger.error(f"关闭策略资源失败: {e}")

            del self._instances[instance_id]
            logger.info(f"🛑 HYPE做空策略已停止: {instance_id}")
            return True

    def get_all(self) -> Dict[str, dict]:
        with self._lock:
            result = {}
            for instance_id, instance in self._instances.items():
                strategy = instance["strategy"]
                result[instance_id] = {
                    "instance_id": instance_id,
                    "symbol": instance["symbol"],
                    "position": strategy.position,
                    "entry_price": strategy.entry_price,
                    "current_sl": strategy.current_sl,
                    "current_tp": strategy.current_tp,
                    "break_even_activated": strategy.break_even_activated,
                    "is_enabled": strategy.is_enabled,
                    "created_at": instance["created_at"].isoformat()
                }
            return result

    def get_status(self, instance_id: str) -> Optional[dict]:
        with self._lock:
            if instance_id not in self._instances:
                return None
            return self._instances[instance_id]["strategy"].get_status()

    def set_enabled(self, instance_id: str, enabled: bool) -> bool:
        with self._lock:
            if instance_id not in self._instances:
                return False
            self._instances[instance_id]["strategy"].set_enabled(enabled)
            return True


# 全局管理器实例
hype_short_manager = HYPEShortManager()


# ==================== 策略核心 ====================

class HYPEAdaptiveShortStrategy:
    """
    HYPE 做空策略
    开仓: TradingView Webhook sell 信号
    平仓: TradingView Webhook buy 信号 | 止损 | 止盈 | 保本止损
    """

    def __init__(
        self,
        symbol: str = "ETH",
        private_key: Optional[str] = None,
        instance_id: str = "",
        stop_loss_pct: float = 0.03,
        take_profit_pct: float = 0.06,
        break_even_pct: float = 0.03,
        margin_amount: float = 20.0,
        leverage: int = 50,
    ):
        self.symbol = symbol.upper()
        self.private_key = private_key or config.hyperliquid.PRIVATE_KEY
        self.client = HyperliquidAPIClient(private_key=self.private_key)
        self.instance_id = instance_id

        # 风险控制参数
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.break_even_pct = break_even_pct

        # 仓位参数
        self.margin_amount = margin_amount
        self.leverage = leverage

        # 防并发平仓标志
        self._closing = False

        # 持仓状态
        self.position: Optional[str] = None
        self.position_size: float = 0.0
        self.entry_price: Optional[float] = None
        self.entry_time: Optional[datetime] = None
        self.current_sl: Optional[float] = None
        self.current_tp: Optional[float] = None
        self.break_even_activated = False
        self.is_enabled = True
        self._stop = False

        # 统计
        self.start_time: datetime = datetime.now()
        self.balance_cache: Optional[float] = None
        self.last_signal: Optional[str] = None
        self.last_intent: Optional[str] = None

        # 异步锁（在事件循环中延迟创建）
        self._lock = None

    async def initialize(self):
        """初始化策略"""
        await self.client._get_session()
        await self.sync_position()

        logger.info("=" * 60)
        logger.info(f"📊 HYPE 做空策略初始化: {self.symbol}")
        logger.info("=" * 60)
        logger.info("🐻 开仓: TradingView Webhook sell 信号")
        logger.info("🟢 平仓: TradingView Webhook buy 信号 | 止损 | 止盈 | 保本止损")
        logger.info(f"📉 止损:   +{self.stop_loss_pct*100:.1f}%  |  止盈: -{self.take_profit_pct*100:.1f}%  |  保本触发: -{self.break_even_pct*100:.1f}%")
        logger.info(f"💰 仓位:  保证金 {self.margin_amount:.1f} USDC × {self.leverage}x = 名义 {self.margin_amount*self.leverage:.1f} USDC")
        logger.info("=" * 60)
        logger.info("✅ 初始化完成，等待 TradingView Webhook 信号...")
        logger.info("=" * 60)

    # ==================== Webhook 信号处理 ====================

    async def execute_signal(self, signal: TVSignal, raw_payload: Optional[Dict[str, Any]] = None):
        """
        处理 TradingView Webhook 信号:
          sell → 开空仓
          buy  → 平空仓
        """
        if self._lock is None:
            self._lock = asyncio.Lock()

        async with self._lock:
            if not self.is_enabled:
                logger.warning("策略已禁用，忽略信号")
                return

            signal_type = signal.signal.lower()
            logger.info(f"📡 收到 Webhook 信号: [{signal_type}] 品种={signal.symbol}")

            # 动态更新交易品种
            if signal.symbol:
                self.symbol = signal.symbol.upper()

            # 同步链上持仓
            await self.sync_position()
            logger.info(f"   当前持仓: {self.position or '无'}")

            self.last_signal = signal_type

            if signal_type == 'sell':
                # sell → 开空
                self.last_intent = "open"
                await self._handle_open_short()

            elif signal_type == 'buy':
                # buy → 平空（TV平仓信号）
                self.last_intent = "close"
                await self._handle_close_by_signal()

            else:
                logger.warning(f"⚠️ 未识别的信号类型: {signal_type}，忽略")

    async def _handle_open_short(self):
        """处理开空仓"""
        if self.position == "SHORT":
            logger.info("⚠️ 已有空头仓位，跳过重复开仓")
            return

        if self.position == "LONG":
            logger.info("⚠️ 检测到多头仓位，先平仓")
            await self.close_position("反向信号平多")

        qty = await self.get_position_size()
        if qty <= 0:
            logger.warning("❌ 仓位计算失败，不开单")
            return

        logger.info(f"🚀 执行开空: {qty:.4f} {self.symbol}")
        await self.open_short_position(qty)

    async def _handle_close_by_signal(self):
        """处理 TV buy 平仓信号"""
        if self.position != "SHORT":
            logger.info(f"⚠️ 当前无空头仓位可平（持仓: {self.position or '无'}），忽略 buy 信号")
            return
        if self._closing:
            logger.info("⚠️ 正在平仓中，忽略重复信号")
            return
        logger.info("📩 TV buy 信号触发平仓")
        await self._safe_close("TV信号平仓(buy)")

    async def _safe_close(self, reason: str):
        """防并发平仓封装"""
        if self.position != "SHORT" or self._closing:
            return
        self._closing = True
        try:
            await self.close_position(reason)
        finally:
            self._closing = False

    # ==================== 持仓管理 ====================

    async def sync_position(self):
        """同步链上持仓状态"""
        try:
            positions = await self.client.get_positions(self.symbol)
            if positions:
                pos = positions[0]
                side = str(pos.get("side", "")).upper()
                self.position = side or None
                self.position_size = abs(float(pos.get("szi", 0) or 0))
                # 若已有仓位但本地无入场价，从链上补充
                if self.position and self.entry_price is None:
                    self.entry_price = float(pos.get("entryPx", 0) or 0)
            else:
                self.position = None
                self.position_size = 0.0
        except Exception as e:
            logger.error(f"同步持仓失败: {e}")

    async def get_position_size(self) -> float:
        """计算仓位数量 = 保证金 × 杠杆 / 当前价格"""
        try:
            price = await self.client.get_price(self.symbol)
            if price <= 0:
                logger.warning(f"⚠️ 价格无效: {price}")
                return 0
            qty = (self.margin_amount * self.leverage) / price
            logger.info(
                f"💰 仓位计算: 价格={price:.4f}  保证金={self.margin_amount:.2f} USDC  "
                f"杠杆={self.leverage}x  数量={qty:.4f} {self.symbol}"
            )
            return qty
        except Exception as e:
            logger.error(f"❌ 仓位计算失败: {e}")
            return 0.0

    async def open_short_position(self, quantity: float) -> bool:
        """市价开空"""
        try:
            available_balance = await self.client.get_balance()
            self.balance_cache = available_balance
            usable = available_balance * 0.9  # 留 10% 给手续费和滑点

            actual_margin = self.margin_amount
            if actual_margin > usable:
                if usable <= 0:
                    logger.error(
                        f"❌ 开空失败: 余额不足 "
                        f"(余额={available_balance:.2f} USDC，需要={self.margin_amount:.2f} USDC)"
                    )
                    return False
                logger.warning(
                    f"⚠️ 余额不足，保证金调整: {self.margin_amount:.2f} → {usable:.2f} USDC"
                )
                actual_margin = round(usable, 2)

            result = await self.client.place_order(
                symbol=self.symbol,
                side="SELL",
                quantity=actual_margin,
                order_type="MARKET",
                leverage=self.leverage
            )
            if isinstance(result, dict) and result.get('status') == 'FAILED':
                logger.error(f"❌ 开空下单失败: {result.get('error')}")
                return False

            # 等待成交后验证
            await asyncio.sleep(1)
            await self.sync_position()

            if self.position != "SHORT":
                logger.error("❌ 开空失败: 链上验证无持仓（可能保证金不足或下单被拒）")
                return False

            # 初始化风控参数
            self.entry_price = float(
                self.entry_price or await self.client.get_price(self.symbol)
            )
            self.entry_time = datetime.now()
            self.current_sl = self.entry_price * (1 + self.stop_loss_pct)
            self.current_tp = self.entry_price * (1 - self.take_profit_pct)
            self.break_even_activated = False
            be_trigger_price = self.entry_price * (1 - self.break_even_pct)

            logger.info("=" * 60)
            logger.info(f"🐻 开空成功: {self.symbol}")
            logger.info(f"   入场价:       {self.entry_price:.4f}")
            logger.info(f"   保证金:       {self.margin_amount:.2f} USDC × {self.leverage}x = {self.margin_amount * self.leverage:.2f} USDC")
            logger.info(f"   实际持仓:     {self.position_size:.4f} {self.symbol}")
            logger.info(f"   止损价:       {self.current_sl:.4f}  (+{self.stop_loss_pct * 100:.1f}%)")
            logger.info(f"   止盈价:       {self.current_tp:.4f}  (-{self.take_profit_pct * 100:.1f}%)")
            logger.info(f"   保本触发价:   {be_trigger_price:.4f}  (盈利达 {self.break_even_pct * 100:.1f}% 时止损移到成本价)")
            logger.info("=" * 60)
            return True

        except Exception as e:
            logger.error(f"开空失败: {e}")
            return False

    async def close_position(self, reason: str = "") -> bool:
        """市价平空并计算盈亏"""
        try:
            await self.sync_position()

            exit_price = await self.client.get_price(self.symbol)
            entry_price = self.entry_price
            real_size = self.position_size

            if real_size > 0:
                result = await self.client.place_order(
                    symbol=self.symbol,
                    side="BUY",
                    quantity=real_size,
                    order_type="MARKET",
                    reduce_only=True,
                )
                if isinstance(result, dict) and result.get('status') == 'FAILED':
                    logger.error(f"平仓下单失败: {result.get('error')}")
                    return False
            else:
                logger.info("链上无持仓，跳过平仓下单")

            # 打印盈亏
            if entry_price and exit_price and real_size > 0:
                pnl = (entry_price - exit_price) * real_size
                pnl_pct = (entry_price - exit_price) / entry_price * 100
                logger.info("=" * 60)
                logger.info(f"✅ 平仓完成: {self.symbol}")
                logger.info(f"   平仓原因: {reason}")
                logger.info(f"   入场价:   {entry_price:.4f}")
                logger.info(f"   出场价:   {exit_price:.4f}")
                logger.info(f"   持仓量:   {real_size:.4f}")
                logger.info(f"   盈亏:     {pnl:.4f} USDC  ({pnl_pct:+.2f}%)")
                logger.info("=" * 60)
            else:
                logger.info(f"平仓完成: {reason}")

            # 重置状态
            self.position = None
            self.position_size = 0.0
            self.entry_price = None
            self.current_sl = None
            self.current_tp = None
            self.break_even_activated = False

            return True

        except Exception as e:
            logger.error(f"平仓失败: {e}")
            return False

    # ==================== 实时风控 ====================

    async def update_stop_loss(self, current_price: float):
        """
        保本逻辑:
        当盈利 >= break_even_pct 时，将止损线移到成本价（入场价）
        """
        if not self.entry_price or self.position != "SHORT":
            return

        profit_pct = (self.entry_price - current_price) / self.entry_price

        if profit_pct >= self.break_even_pct and not self.break_even_activated:
            old_sl = self.current_sl
            self.current_sl = self.entry_price
            self.break_even_activated = True
            logger.info(
                f"✅ [保本激活] 盈利 {profit_pct * 100:.2f}% ≥ {self.break_even_pct * 100:.0f}%，"
                f"止损线: {old_sl:.4f} → 成本价 {self.current_sl:.4f}"
            )

    async def check_stop_loss_take_profit(
        self, current_price: float, silent: bool = False
    ) -> Tuple[bool, str]:
        """
        检查止损/止盈是否触发
        silent=True 时不输出未触发日志（高频轮询时使用）
        """
        if self.position != "SHORT" or self.current_sl is None or self.current_tp is None:
            return False, ""

        pnl_pct = (self.entry_price - current_price) / self.entry_price * 100

        # 止盈: 价格跌破止盈价
        if current_price <= self.current_tp:
            logger.info(
                f"✅ [止盈触发] 当前价 {current_price:.4f} ≤ 止盈价 {self.current_tp:.4f}，"
                f"盈利 {pnl_pct:.2f}%"
            )
            return True, "止盈"

        # 止损/保本: 价格上涨超过止损价
        if current_price >= self.current_sl:
            exit_type = "保本止损" if self.break_even_activated else "止损"
            logger.info(
                f"✅ [{exit_type}触发] 当前价 {current_price:.4f} ≥ 止损价 {self.current_sl:.4f}"
            )
            return True, exit_type

        if not silent:
            logger.info(
                f"📊 监控: 价={current_price:.4f} | 止盈={self.current_tp:.4f} | "
                f"止损={self.current_sl:.4f} | PnL={pnl_pct:+.2f}% | "
                f"保本={'已激活' if self.break_even_activated else '未激活'}"
            )
        return False, ""

    # ==================== 状态/控制 ====================

    def set_enabled(self, enabled: bool):
        self.is_enabled = enabled
        logger.info(f"策略{'启用' if enabled else '禁用'}: {self.instance_id or self.symbol}")

    def get_status(self) -> Dict:
        return {
            "instance_id": self.instance_id,
            "strategy_name": "HYPE做空策略(Webhook版)",
            "symbol": self.symbol,
            "is_enabled": self.is_enabled,
            "position": self.position,
            "entry_price": self.entry_price,
            "current_sl": self.current_sl,
            "current_tp": self.current_tp,
            "break_even_activated": self.break_even_activated,
            "position_size": self.position_size,
            "entry_time": self.entry_time.isoformat() if self.entry_time else None,
            "last_signal": self.last_signal,
            "last_intent": self.last_intent,
            "margin_amount": self.margin_amount,
            "leverage": self.leverage,
            "notional_value": self.margin_amount * self.leverage,
            "stop_loss_pct": self.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
            "break_even_pct": self.break_even_pct,
            "balance": self.balance_cache,
            "start_time": self.start_time.strftime("%m-%d %H:%M"),
        }

    # ==================== 主循环 ====================

    async def run(self):
        """
        策略主运行循环
        - 开平仓由 TradingView Webhook 信号驱动
        - 每 5 秒轮询价格，执行止损/止盈/保本检查
        """
        await self.initialize()

        # 启动时主动获取余额并记录
        try:
            self.balance_cache = await self.client.get_balance()
        except Exception as _e:
            logger.warning(f"⚠️ 启动时获取余额失败: {_e}")
            self.balance_cache = None
        bal_str = f"{self.balance_cache:,.2f} USDC" if self.balance_cache is not None else "获取失败"

        logger.info("=" * 60)
        logger.info(f"🚀 HYPE做空策略运行中: {self.symbol}")
        logger.info(f"💰 账户余额: {bal_str}")
        logger.info(
            f"📊 风控参数: 止损 +{self.stop_loss_pct*100:.0f}% | "
            f"止盈 -{self.take_profit_pct*100:.0f}% | "
            f"保本触发 -{self.break_even_pct*100:.0f}%"
        )
        logger.info("⏳ 等待 TradingView Webhook 信号 (sell=开空, buy=平空)...")
        logger.info("=" * 60)

        while not self._stop:
            try:
                # 刷新余额缓存
                try:
                    self.balance_cache = await self.client.get_balance()
                except Exception:
                    pass

                if not self.is_enabled:
                    await asyncio.sleep(30)
                    continue

                # 持有空仓时进行实时风控
                if self.position == "SHORT" and not self._closing:
                    current_price = await self.client.get_price(self.symbol)

                    # 1. 保本: 盈利达 break_even_pct 时移动止损到成本价
                    await self.update_stop_loss(current_price)

                    # 2. 止损 / 止盈检查
                    exit_flag, exit_reason = await self.check_stop_loss_take_profit(
                        current_price, silent=True
                    )
                    if exit_flag:
                        await self._safe_close(exit_reason)
                        await asyncio.sleep(5)
                        continue

                await asyncio.sleep(5)  # 5秒轮询间隔

            except Exception as e:
                logger.error(f"❌ [策略运行错误] {e}")
                await asyncio.sleep(30)

    async def close(self):
        """关闭策略，清理资源"""
        self._stop = True
        await self.client.close()
        logger.info("HYPE做空策略已关闭")


# ==================== 独立运行入口 ====================

async def main(symbol: str = "ETH"):
    strategy = HYPEAdaptiveShortStrategy(symbol=symbol)
    try:
        await strategy.run()
    finally:
        await strategy.close()


if __name__ == "__main__":
    asyncio.run(main((os.getenv("HYPE_STRATEGY_SYMBOL") or "ETH").upper()))


# ==================== Webhook 服务入口 ====================

def create_webhook_app():
    """创建 FastAPI Webhook 服务（用于接收 TradingView 信号）"""
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
    import uvicorn

    app = FastAPI(title="HYPE Webhook Service")
    strategy_instance: Optional[HYPEAdaptiveShortStrategy] = None

    @app.on_event("startup")
    async def startup():
        nonlocal strategy_instance
        strategy_instance = HYPEAdaptiveShortStrategy(
            symbol=os.getenv("HYPE_STRATEGY_SYMBOL", "ETH")
        )
        asyncio.create_task(strategy_instance.run())
        logger.info(f"✅ HYPE做空策略已启动: {strategy_instance.symbol}")

    @app.on_event("shutdown")
    async def shutdown():
        if strategy_instance:
            await strategy_instance.close()

    @app.post("/webhook")
    async def webhook(request: Request):
        """接收 TradingView Webhook 信号"""
        try:
            data = await request.json()
            logger.info(f"📡 收到 Webhook: {data}")

            signal = TVSignal(
                交易品种=data.get("交易品种", data.get("symbol", "ETH")),
                价格=data.get("价格", data.get("price")),
                操作=data.get("操作", data.get("signal", "")),
                仓位方向=data.get("仓位方向"),
                先前仓位大小=str(data.get("先前仓位大小", "0"))
            )

            if strategy_instance:
                await strategy_instance.execute_signal(signal, data)
                return JSONResponse({
                    "status": "ok",
                    "position": strategy_instance.position,
                    "signal": signal.signal
                })
            else:
                return JSONResponse(
                    {"status": "error", "message": "策略未初始化"}, status_code=500
                )

        except Exception as e:
            logger.error(f"❌ Webhook 错误: {e}")
            return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

    @app.get("/position")
    async def get_position():
        if strategy_instance:
            return strategy_instance.get_status()
        return {"position": None}

    @app.post("/close")
    async def manual_close():
        if strategy_instance and strategy_instance.position:
            await strategy_instance.close_position("手动平仓")
            return {"status": "ok"}
        return {"status": "no_position"}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


def run_webhook_service(port: int = 8005):
    """运行 Webhook 服务"""
    import uvicorn
    app = create_webhook_app()
    logger.info(f"🚀 HYPE Webhook 服务启动: http://0.0.0.0:{port}")
    logger.info("📡 Webhook 端点: POST /webhook")
    uvicorn.run(app, host="0.0.0.0", port=port)
