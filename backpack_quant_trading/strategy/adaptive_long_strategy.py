"""
自适应做多策略 - 实盘版（TradingView Webhook 信号驱动）

开仓: 接收 Webhook {"操作":"buy"}  信号 → 市价开多
平仓: 接收 Webhook {"操作":"sell"} 信号 → 市价平多（仅当币种匹配时）

信号格式 (TradingView → POST /trading/adaptive-long/webhook):
  {"交易品种":"ETH","操作":"buy","先前仓位大小":"0"}    → 开多
  {"交易品种":"ETH","操作":"sell","先前仓位大小":"0.1"} → 平多

币种不匹配时 sell 信号自动忽略（如持仓 ETH 却收到 HYPE sell，跳过）

本地风控 (每 5 秒轮询实时价格):
  止损: 价格 <= 止损价 → 平仓
  止盈: 价格 >= 止盈价 → 平仓
  保本: 盈利 >= break_even_pct → 止损上移至入场价
"""

import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from backpack_quant_trading.config.settings import config
from backpack_quant_trading.core.hyperliquid_client import HyperliquidAPIClient

# ─── 日志 ──────────────────────────────────────────────────────────────────────
logger = logging.getLogger("adaptive_long")
logger.setLevel(logging.INFO)
if not logger.handlers:
    log_dir = Path(config.log_dir) if hasattr(config, "log_dir") else Path("./log")
    log_dir.mkdir(parents=True, exist_ok=True)
    _fh = logging.FileHandler(log_dir / "adaptive_long.log", encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", "%Y-%m-%d %H:%M:%S"))
    logger.addHandler(_fh)
    _ch = logging.StreamHandler(sys.stdout)
    _ch.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", "%H:%M:%S"))
    logger.addHandler(_ch)


# ─── 策略主类 ──────────────────────────────────────────────────────────────────
class AdaptiveLongStrategy:
    """
    自适应做多策略 - 实盘版
    开仓/平仓均由 TradingView Webhook 驱动，本地只做 SL/TP/保本 风控。
    symbol 动态从 Webhook 信号中获取，无需提前配置。
    """

    def __init__(
        self,
        private_key: Optional[str] = None,
        instance_id: str = "",
        margin_amount: float = 20.0,
        leverage: int = 50,
        stop_loss_pct: float = 0.03,
        take_profit_pct: float = 0.06,
        break_even_pct: float = 0.03,
    ):
        self.private_key = private_key or config.hyperliquid.PRIVATE_KEY
        self.client      = HyperliquidAPIClient(private_key=self.private_key)
        self.instance_id = instance_id or f"al_{int(datetime.now().timestamp())}"

        self.margin_amount   = margin_amount
        self.leverage        = leverage
        self.stop_loss_pct   = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.break_even_pct  = break_even_pct

        # 动态币种（从 Webhook 信号获取）
        self.symbol: Optional[str] = None

        # 持仓状态
        self.position:      Optional[str]   = None   # "LONG" | None
        self.position_size: float           = 0.0
        self.entry_price:   Optional[float] = None
        self.entry_time:    Optional[datetime] = None
        self.sl_price:      Optional[float] = None
        self.tp_price:      Optional[float] = None
        self.break_even_activated: bool     = False
        self._closing:      bool            = False

        # 运行控制
        self._stop      = False
        self.is_enabled = True
        self.start_time = datetime.now()
        self.balance_cache: Optional[float] = None
        self.last_signal: str = "—"
        self._lock = None

    # ─── 主循环 ─────────────────────────────────────────
    async def run(self):
        self._lock = asyncio.Lock()
        await self.client._get_session()
        self.balance_cache = await self.client.get_balance()
        logger.info("=" * 60)
        logger.info(f"🚀 自适应做多策略启动  instance={self.instance_id}")
        logger.info(f"   SL={self.stop_loss_pct*100:.1f}%  TP={self.take_profit_pct*100:.1f}%  保本={self.break_even_pct*100:.1f}%")
        logger.info(f"   保证金={self.margin_amount}×{self.leverage}x")
        logger.info(f"   等待 TradingView Webhook 信号...")
        logger.info("=" * 60)

        risk_task = asyncio.create_task(self._risk_loop())
        try:
            await risk_task
        except asyncio.CancelledError:
            pass
        finally:
            await self.client.close()
            logger.info(f"✅ 策略已停止: {self.instance_id}")

    # ─── 风控循环（每 5 秒检查 SL/TP/保本）──────────────
    async def _risk_loop(self):
        while not self._stop:
            try:
                if self.is_enabled and self.position == "LONG" and self.symbol:
                    await self._check_risk()
            except Exception as e:
                logger.error(f"风控循环异常: {e}")
            await asyncio.sleep(5)

    async def _check_risk(self):
        price = await self.client.get_price(self.symbol)
        if price <= 0 or self.entry_price is None:
            return

        ep = self.entry_price
        async with self._lock:
            if self.position != "LONG":
                return

            # 止损触发（做多：价格跌破止损价）
            if self.sl_price and price <= self.sl_price:
                reason = "保本止损" if self.break_even_activated else "止损"
                logger.info(f"🛑 {reason} 触发: 当前价={price:.4f}  SL={self.sl_price:.4f}")
                self.last_signal = reason
                await self._safe_close(reason)
                return

            # 止盈触发（做多：价格升过止盈价）
            if self.tp_price and price >= self.tp_price:
                logger.info(f"💰 止盈触发: 当前价={price:.4f}  TP={self.tp_price:.4f}")
                self.last_signal = "止盈"
                await self._safe_close("止盈")
                return

            # 保本激活（做多：盈利 >= break_even_pct → 止损上移至入场价）
            if not self.break_even_activated and price >= ep * (1 + self.break_even_pct):
                self.break_even_activated = True
                new_sl = ep   # 止损移到成本价
                if self.sl_price is None or new_sl > self.sl_price:
                    self.sl_price = new_sl
                    logger.info(f"🛡️ 保本激活 盈利={((price - ep) / ep * 100):.2f}% → SL={self.sl_price:.4f}")

    # ─── Webhook 信号处理 ───────────────────────────────
    async def execute_signal(self, signal_symbol: str, action: str):
        """
        处理 TradingView Webhook 信号:
          buy  → 开多（若无持仓）
          sell → 平多（仅当持仓币种匹配时）
        """
        if self._lock is None:
            self._lock = asyncio.Lock()

        async with self._lock:
            if not self.is_enabled:
                logger.warning("策略已禁用，忽略信号")
                return

            action = action.lower().strip()
            logger.info(f"📡 Webhook 信号: action={action}  symbol={signal_symbol}")

            if action == "buy":
                if self.position is None:
                    self.symbol = signal_symbol.upper()
                    logger.info(f"  ↳ 🟢 开多信号: {self.symbol}")
                    self.last_signal = f"buy({self.symbol})"
                    await self._open_long()
                else:
                    logger.info(f"  ↳ ⚠️ 已有 {self.symbol} 持仓，忽略 buy 信号")

            elif action == "sell":
                if self.position != "LONG":
                    # 内部无仓位时，去交易所核查一次真实持仓（防止状态不同步）
                    try:
                        sym = (self.symbol or signal_symbol).upper()
                        positions = await self.client.get_positions(symbol=sym)
                        long_pos = next(
                            (p for p in positions
                             if str(p.get('side', '')).lower() == 'long' and abs(p.get('size', 0)) > 0),
                            None
                        )
                        if long_pos:
                            logger.warning(f"  ↳ 内部无仓位记录，但交易所有多头持仓，同步状态后平仓")
                            self.symbol         = sym
                            self.position       = "LONG"
                            self.position_size  = abs(long_pos.get('size', 0))
                            ep = long_pos.get('entry_price') or long_pos.get('entryPx')
                            self.entry_price    = float(ep) if ep else None
                        else:
                            logger.info(f"  ↳ 无多头仓位（内部+交易所均无），忽略 sell 信号")
                            return
                    except Exception as e:
                        logger.error(f"  ↳ 查询交易所持仓失败: {e}，忽略 sell 信号")
                        return

                if self.position == "LONG":
                    if self.symbol and self.symbol.upper() == signal_symbol.upper():
                        logger.info(f"  ↳ 🔴 平多信号: {signal_symbol}")
                        self.last_signal = f"sell({signal_symbol})"
                        await self._safe_close("Webhook平仓信号")
                    else:
                        logger.warning(
                            f"  ↳ ⚠️ 币种不匹配: 当前持仓={self.symbol}  信号={signal_symbol}，忽略"
                        )

    # ─── 开仓/平仓 ──────────────────────────────────────
    async def _open_long(self):
        if self.position == "LONG":
            logger.info("⚠️ 已有多头仓位，跳过")
            return
        try:
            price = await self.client.get_price(self.symbol)
            self.balance_cache = await self.client.get_balance()

            logger.info(
                f"🚀 开多 {self.symbol}: 价格={price:.4f}  "
                f"保证金={self.margin_amount}×{self.leverage}x"
            )
            result = await self.client.place_order(
                symbol=self.symbol,
                side="BUY",
                quantity=self.margin_amount,
                order_type="MARKET",
                leverage=self.leverage,
            )
            if result.get("status") == "FILLED":
                self.position      = "LONG"
                self.entry_price   = price
                self.entry_time    = datetime.now()
                self.sl_price      = round(price * (1 - self.stop_loss_pct), 6)
                self.tp_price      = round(price * (1 + self.take_profit_pct), 6)
                self.break_even_activated = False
                self.position_size = round((self.margin_amount * self.leverage) / price, 4)
                logger.info(
                    f"   ✅ 开仓成功  EP={self.entry_price:.4f}  "
                    f"SL={self.sl_price:.4f}  TP={self.tp_price:.4f}"
                )
            else:
                logger.warning(f"   ❌ 开仓失败: {result.get('error', '未知错误')}")
        except Exception as e:
            logger.error(f"开仓异常: {e}")

    async def _safe_close(self, reason: str):
        if self.position != "LONG" or self._closing:
            return
        self._closing = True
        try:
            await self._close_position(reason)
        finally:
            self._closing = False

    async def _close_position(self, reason: str):
        try:
            price = await self.client.get_price(self.symbol)
            logger.info(f"🟢 平多 [{reason}]: 当前价={price:.4f}  入场={self.entry_price:.4f}")
            result = await self.client.close_position(self.symbol)
            if result.get("status") in ("FILLED", "CLOSED"):
                if self.entry_price:
                    pnl_pct = (price - self.entry_price) / self.entry_price * 100
                    logger.info(f"   ✅ 平仓成功  盈亏={pnl_pct:+.2f}%  原因={reason}")
                self.position             = None
                self.entry_price          = None
                self.entry_time           = None
                self.sl_price             = None
                self.tp_price             = None
                self.break_even_activated = False
                self.position_size        = 0.0
                self.symbol               = None    # 清空，等待下次 webhook 信号
                self.balance_cache        = await self.client.get_balance()
            else:
                logger.warning(f"   ❌ 平仓失败: {result}")
        except Exception as e:
            logger.error(f"平仓异常: {e}")

    # ─── 状态接口 ────────────────────────────────────────
    def get_status(self) -> Dict[str, Any]:
        return {
            "instance_id":         self.instance_id,
            "symbol":              self.symbol or "—",
            "is_enabled":          self.is_enabled,
            "position":            self.position or "无",
            "position_size":       self.position_size,
            "entry_price":         self.entry_price,
            "sl_price":            self.sl_price,
            "tp_price":            self.tp_price,
            "break_even_activated": self.break_even_activated,
            "balance":             self.balance_cache,
            "last_signal":         self.last_signal,
            "start_time":          self.start_time.strftime("%m-%d %H:%M"),
        }

    def set_enabled(self, enabled: bool):
        self.is_enabled = enabled
        logger.info(f"策略{'开启' if enabled else '暂停'}: {self.instance_id}")

    def stop(self):
        self._stop = True
