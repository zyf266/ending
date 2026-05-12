"""
自适应做空策略 - 实盘版（TradingView Webhook 信号驱动）

开仓: 接收 Webhook {"操作":"sell"} 信号 → 市价开空
平仓: 接收 Webhook {"操作":"buy"}  信号 → 市价平空（仅当币种匹配时）

其余逻辑与 adaptive_long_strategy 保持一致：包含 K 线级别过滤、多实例路由配合、以及本地轮询风控
（Binance/Lighter 轮询；Hyperliquid 挂交易所 TP/SL + 轮询保本/同步）。
"""

import asyncio
import logging
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from backpack_quant_trading.config.settings import config
from backpack_quant_trading.core.hyperliquid_client import HyperliquidAPIClient
from backpack_quant_trading.core.binance_client import BinanceAPIClient, _to_binance_symbol

logger = logging.getLogger("adaptive_short")
logger.setLevel(logging.INFO)
if not logger.handlers:
    log_dir = Path(config.log_dir) if hasattr(config, "log_dir") else Path("./log")
    log_dir.mkdir(parents=True, exist_ok=True)
    _fh = logging.FileHandler(log_dir / "adaptive_short.log", encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", "%Y-%m-%d %H:%M:%S"))
    logger.addHandler(_fh)
    _ch = logging.StreamHandler(sys.stdout)
    _ch.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", "%H:%M:%S"))
    logger.addHandler(_ch)


class AdaptiveShortStrategy:
    """
    自适应做空策略 - 实盘版
    开仓/平仓均由 TradingView Webhook 驱动，本地只做 SL/TP/保本/锁利 风控。
    """

    def __init__(
        self,
        private_key: Optional[str] = None,
        exchange: str = "hyperliquid",
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        instance_id: str = "",
        margin_amount: float = 20.0,
        leverage: int = 50,
        stop_loss_pct: float = 0.03,
        take_profit_pct: float = 0.06,
        break_even_pct: float = 0.03,
        symbol_filter: Optional[str] = None,
        account_index: int = 0,
        api_key_index: int = 2,
        timeframe_filter: Optional[str] = None,
        lock_profit_pct: float = 0.0,
        lock_profit_sl_pct: float = 0.0,
    ):
        self.exchange = (exchange or "hyperliquid").lower()
        if self.exchange == "binance":
            self.client = BinanceAPIClient(api_key=api_key, secret_key=api_secret)
        elif self.exchange == "lighter":
            from backpack_quant_trading.core.lighter_client import LighterAPIClient
            self.client = LighterAPIClient(
                private_key=private_key,
                account_index=account_index,
                api_key_index=api_key_index,
            )
        else:
            self.private_key = private_key or config.hyperliquid.PRIVATE_KEY
            self.client = HyperliquidAPIClient(private_key=self.private_key)

        self.instance_id = instance_id or f"as_{int(datetime.now().timestamp())}"
                # 供 /api/trading/instances 展示用
        self.start_time = datetime.now()
        self.balance_cache: Optional[float] = None
        self.margin_amount = margin_amount
        self.leverage = leverage
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.break_even_pct = break_even_pct
        self.lock_profit_pct = lock_profit_pct
        self.lock_profit_sl_pct = lock_profit_sl_pct

        self.symbol_filter = symbol_filter.upper().strip() if symbol_filter else None
        self.timeframe_filter = timeframe_filter.upper().strip() if timeframe_filter else None

        self.symbol: Optional[str] = None
        self.position: Optional[str] = None  # "SHORT" | None
        self.position_size: float = 0.0
        self.entry_price: Optional[float] = None
        self.entry_time: Optional[datetime] = None
        self.sl_price: Optional[float] = None
        self.tp_price: Optional[float] = None
        self.break_even_activated: bool = False
        self.lock_profit_activated: bool = False
        self._closing: bool = False
        self._opening: bool = False
        self._sl_oid: Optional[str] = None
        self._tp_oid: Optional[str] = None
        self._sync_count: int = 0
        self.position_entry_tfs: set = set()

        self._stop: bool = False
        self.is_enabled: bool = True
        self.last_signal: str = ""
        self._lock = asyncio.Lock()

    async def run(self):
        try:
            self.balance_cache = await self._get_balance_float()
        except Exception:
            self.balance_cache = None
        perps = self.balance_cache if self.balance_cache is not None else 0.0
        unit = "USDT" if self.exchange == "binance" else "USDC"
        perps_str = f"{perps:,.2f} {unit}" if self.balance_cache is not None else "获取失败"
        logger.info("=" * 60)
        logger.info(
            f"🚀 自适应做空策略启动  exchange={self.exchange}  instance={self.instance_id}  "
            f"币种绑定={self.symbol_filter or '未绑定'}  K线级别={self.timeframe_filter or '不限制'}"
        )
        if self.exchange == "binance":
            logger.info(f"💰 币安合约账户余额: {perps_str}")
        elif self.exchange == "lighter":
            logger.info(f"💰 Lighter 账户余额: {perps_str}")
        else:
            logger.info(f"💰 Perps 主账户余额: {perps_str}")
        logger.info(
            f"   SL={self.stop_loss_pct*100:.1f}%  TP={self.take_profit_pct*100:.1f}%  保本={self.break_even_pct*100:.1f}%"
            + (
                f"  锁利={self.lock_profit_pct*100:.1f}%触发→SL锁={self.lock_profit_sl_pct*100:.1f}%"
                if self.lock_profit_pct > 0
                else ""
            )
        )
        logger.info(f"   保证金={self.margin_amount}×{self.leverage}x")
        logger.info("   等待 TradingView Webhook 信号...")
        logger.info("=" * 60)

        risk_task = asyncio.create_task(self._risk_loop())
        def _on_done(t: asyncio.Task):
            try:
                if t.cancelled():
                    logger.warning(f"⚠️ risk_task 被取消: instance={self.instance_id} _stop={self._stop}")
                else:
                    exc = t.exception()
                    if exc:
                        logger.error(f"⚠️ risk_task 异常结束: instance={self.instance_id} _stop={self._stop} err={repr(exc)}")
                    else:
                        logger.warning(f"⚠️ risk_task 正常结束: instance={self.instance_id} _stop={self._stop}")
            except Exception:
                pass
        risk_task.add_done_callback(_on_done)
        try:
            await risk_task
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"⚠️ run() await risk_task 异常: instance={self.instance_id} _stop={self._stop} err={repr(e)}")
        finally:
            await self.client.close()
            logger.info(f"✅ 策略已停止: {self.instance_id}")

    def stop(self):
        try:
            stack = "".join(traceback.format_stack(limit=8))
            logger.info(f"🧯 stop() 被调用，调用栈(末8帧):\n{stack}")
        except Exception:
            pass
        self._stop = True
        self.is_enabled = False

    async def _get_price(self, symbol: str) -> float:
        if self.exchange == "binance":
            bn_sym = _to_binance_symbol(symbol)
            data = await self.client._get("/fapi/v1/ticker/price", {"symbol": bn_sym})
            return float(data.get("price", 0))
        if self.exchange == "lighter":
            return await self.client.get_price(symbol)
        try:
            dex_name, _, _, _ = await self.client.find_asset_dex(symbol)
            return await self.client.get_price(symbol, dex=dex_name)
        except Exception:
            return await self.client.get_price(symbol)

    async def _get_balance_float(self, dex: str = "") -> float:
        if self.exchange == "binance":
            raw = await self.client.get_balance()
            bal_dict = {item["asset"]: item for item in raw if isinstance(item, dict) and item.get("asset")}
            usdt = bal_dict.get("USDT", {})
            return float(usdt.get("available", 0))
        if self.exchange == "lighter":
            return await self.client.get_balance()
        return await self.client.get_balance(dex=dex)

    def _reset_position_state(self):
        self.position = None
        self.entry_price = None
        self.entry_time = None
        self.sl_price = None
        self.tp_price = None
        self.break_even_activated = False
        self.lock_profit_activated = False
        self.position_size = 0.0
        self.symbol = None
        self._sl_oid = None
        self._tp_oid = None
        self._closing = False
        self._opening = False
        self.position_entry_tfs = set()

    async def _place_exchange_tpsl(self):
        if not self.position_size or not self.sl_price or not self.tp_price:
            logger.warning("⚠️ 挂 TP/SL 单条件不足（size/sl/tp 未就绪）")
            return
        try:
            if self.exchange == "hyperliquid":
                # SHORT: SL/TP 都是 BUY（平空）
                sl_res = await self.client.place_tpsl_order(
                    symbol=self.symbol,
                    side="BUY",
                    quantity=self.position_size,
                    trigger_price=self.sl_price,
                    tpsl="sl",
                )
                if sl_res.get("status") == "FAILED":
                    logger.error(f"❌ SL 挂单失败: {sl_res.get('error')}")
                else:
                    self._sl_oid = sl_res.get("orderId")

                tp_res = await self.client.place_tpsl_order(
                    symbol=self.symbol,
                    side="BUY",
                    quantity=self.position_size,
                    trigger_price=self.tp_price,
                    tpsl="tp",
                )
                if tp_res.get("status") == "FAILED":
                    logger.error(f"❌ TP 挂单失败: {tp_res.get('error')}")
                else:
                    self._tp_oid = tp_res.get("orderId")
            elif self.exchange == "binance":
                logger.info(f"🛡️ [Binance] SL 由软件御控周期守护  SL={self.sl_price:.4f}  每5s轮询触发")
                tp_res = await self.client.place_tpsl_order(
                    symbol=self.symbol,
                    trigger_price=self.tp_price,
                    tpsl="tp",
                    side="BUY",
                    quantity=self.position_size,
                )
                if tp_res.get("status") == "FAILED":
                    logger.error(f"❌ TP 挂单失败: {tp_res.get('error')}")
                else:
                    self._tp_oid = tp_res.get("orderId")
            elif self.exchange == "lighter":
                # Lighter 原生触发单：SHORT 的 SL/TP 都是 BUY（平空）
                sl_res = await self.client.place_tpsl_order(
                    symbol=self.symbol,
                    side="BUY",
                    quantity=self.position_size,
                    trigger_price=self.sl_price,
                    tpsl="sl",
                )
                if sl_res.get("status") == "FAILED":
                    logger.warning(f"⚠️ Lighter SL 挂单失败: {sl_res.get('error')}，转由软件御控")
                else:
                    self._sl_oid = sl_res.get("orderId")
                    logger.info(f"📌 Lighter SL 挂单成功 oid={self._sl_oid}  触发价={self.sl_price:.4f}")

                tp_res = await self.client.place_tpsl_order(
                    symbol=self.symbol,
                    side="BUY",
                    quantity=self.position_size,
                    trigger_price=self.tp_price,
                    tpsl="tp",
                )
                if tp_res.get("status") == "FAILED":
                    logger.warning(f"⚠️ Lighter TP 挂单失败: {tp_res.get('error')}，转由软件御控")
                else:
                    self._tp_oid = tp_res.get("orderId")
                    logger.info(f"📌 Lighter TP 挂单成功 oid={self._tp_oid}  触发价={self.tp_price:.4f}")
        except Exception as e:
            logger.error(f"挂交易所 TP/SL 异常: {e}")

    async def _cancel_exchange_tpsl(self):
        for oid, label in [(self._sl_oid, "SL"), (self._tp_oid, "TP")]:
            if oid and self.symbol:
                try:
                    await self.client.cancel_order_async(self.symbol, order_id=oid)
                    logger.info(f"🗑️ 已撤销 {label} 单 oid={oid}")
                except Exception as e:
                    logger.warning(f"撤销 {label} 单失败 oid={oid}: {e}")
        self._sl_oid = None
        self._tp_oid = None

    async def _open_short(self, symbol: str):
        """市价开空"""
        try:
            async with self._lock:
                if self.position == "SHORT":
                    logger.info("已有空仓，忽略开仓")
                    return
                self.symbol = symbol

            dex_name = ""
            if self.exchange == "hyperliquid":
                try:
                    dex_name, _, _, _ = await self.client.find_asset_dex(symbol)
                except Exception as e:
                    logger.error(f"❌ 开空失败: 资产查找失败 ({e})")
                    return

            # Lighter 偶发 503/网络抖动时 get_balance 可能短暂返回 0，这里做重试避免误判“余额不足”
            balance = 0.0
            if self.exchange == "lighter":
                last_exc = None
                for attempt in range(5):
                    try:
                        balance = await self._get_balance_float(dex=dex_name)
                        if balance > 0:
                            break
                    except Exception as e:
                        last_exc = e
                    await asyncio.sleep(0.5 * (2 ** attempt))
                if balance <= 0 and last_exc:
                    logger.warning(f"[Lighter] 余额查询多次失败，可能为临时 503/代理抖动: {last_exc}")
            else:
                balance = await self._get_balance_float(dex=dex_name)
            self.balance_cache = balance
            usable = balance * 0.9
            if self.margin_amount > usable:
                logger.error(
                    f"❌ 开空失败: 配置保证金超过安全可用额度 (DEX={dex_name or 'Perps'} 账户余额={balance:.2f}，"
                    f"配置保证金={self.margin_amount:.2f}，按余额 90% 计可用上限={usable:.2f})"
                )
                return

            price = await self._get_price(symbol)
            if price <= 0:
                logger.error(f"❌ 开空失败: 获取价格异常 {symbol}")
                return

            notional = self.margin_amount * self.leverage
            qty = notional / price
            if qty <= 0:
                logger.error("❌ 开空失败: 计算数量为 0")
                return

            if self.exchange == "binance":
                res = await self.client.place_order(symbol, "SELL", qty, leverage=self.leverage)
            elif self.exchange == "lighter":
                res = await self.client.place_order(symbol, "SELL", self.margin_amount, leverage=self.leverage)
            elif self.exchange == "hyperliquid":
                # Hyperliquid 下单接口 quantity=保证金（USDC），内部会按 leverage 计算币数；
                # 这里不能传币数 qty，否则会被再次乘 leverage 导致下单量异常
                res = await self.client.place_order(symbol, "SELL", self.margin_amount, leverage=self.leverage)
            else:
                res = await self.client.place_order(symbol, "SELL", qty, leverage=self.leverage)

            if res.get("status") == "FAILED":
                error_msg = res.get("error", "")
                logger.error(f"❌ 开空下单失败: {error_msg}")
                return

            # Hyperliquid：等待成交后同步真实持仓（用于挂 TP/SL 触发单）
            entry_price = price
            position_size = float(qty)
            if self.exchange == "hyperliquid":
                await asyncio.sleep(3)
                try:
                    positions = await self.client.get_positions(symbol=symbol, dex=dex_name)
                    if positions:
                        pos = positions[0]
                        position_size = abs(float(pos.get("size", 0) or 0))
                        if float(pos.get("entry_price") or 0) > 0:
                            entry_price = float(pos.get("entry_price"))
                except Exception as e:
                    logger.warning(f"同步 Hyperliquid 持仓失败（将使用估算值继续）: {e}")

            async with self._lock:
                self.position = "SHORT"
                self.position_size = position_size
                self.entry_price = entry_price
                self.entry_time = datetime.now()
                self.sl_price = self.entry_price * (1 + self.stop_loss_pct)
                self.tp_price = self.entry_price * (1 - self.take_profit_pct)
                self.break_even_activated = False
                self.lock_profit_activated = False

            # Hyperliquid / Lighter：开仓后在交易所挂 TP/SL 触发单（若失败会降级为软件御控）
            if self.exchange in ("hyperliquid", "lighter"):
                await self._place_exchange_tpsl()

            logger.info(f"🐻 开空成功: {symbol}")
        except Exception as e:
            logger.error(f"开空异常: {e}")

    async def _close_position(self, reason: str):
        """市价平空"""
        try:
            symbol = self.symbol
            if not symbol or self.position != "SHORT" or self.position_size <= 0:
                logger.info("无空仓，忽略平仓")
                self._reset_position_state()
                return

            real_size = self.position_size
            entry_price = self.entry_price or 0.0
            exit_price = await self._get_price(symbol) if symbol else 0.0

            dex_name = ""
            if self.exchange == "hyperliquid":
                try:
                    dex_name, _, _, _ = await self.client.find_asset_dex(symbol)
                except Exception:
                    dex_name = ""

            if self.exchange == "binance":
                await self.client.place_order(symbol, "BUY", real_size, reduce_only=True)
            elif self.exchange == "lighter":
                await self.client.place_order(symbol, "BUY", real_size, reduce_only=True)
            else:
                await self.client.place_order(symbol, "BUY", real_size, reduce_only=True)

            if entry_price > 0 and exit_price > 0:
                pnl = (entry_price - exit_price) * real_size
                pnl_pct = (entry_price - exit_price) / entry_price * 100
                logger.info("=" * 60)
                logger.info(f"✅ 平空完成: {symbol}  原因={reason}")
                logger.info(f"   入场价: {entry_price:.4f}  出场价: {exit_price:.4f}")
                logger.info(f"   持仓量: {real_size:.6f}  盈亏: {pnl:.4f} ({pnl_pct:+.2f}%)")
                logger.info("=" * 60)
            else:
                logger.info(f"平仓完成: {reason}")

            self._reset_position_state()
        except Exception as e:
            logger.error(f"平仓异常: {e}")
            self._reset_position_state()

    async def _safe_close(self, reason: str):
        if self.position != "SHORT" or self._closing:
            return
        self._closing = True
        try:
            await self._cancel_exchange_tpsl()
            await self._close_position(reason)
        finally:
            self._closing = False

    async def execute_signal(self, symbol: str, action: str, timeframe: Optional[str] = None):
        """
        action="sell" → 开空
        action="buy"  → 平空
        """
        action = (action or "").lower().strip()
        symbol = (symbol or "").upper().strip()
        tf = timeframe.upper().strip() if timeframe else ""

        if self.timeframe_filter and tf and tf != self.timeframe_filter:
            logger.info(f"K线级别不匹配: 信号={tf}  策略配置={self.timeframe_filter}，忽略")
            return

        if self.symbol_filter and self.symbol_filter != symbol:
            logger.info(f"⏭️ 信号 {action} {symbol} 与绑定币种 {self.symbol_filter} 不匹配，忽略")
            return

        if action == "sell":
            if self._opening:
                logger.info(f"开仓进行中，忽略重复开仓信号 ({symbol} {tf or '未指定级别'})")
                return
            if self.position == "SHORT":
                if tf and tf in self.position_entry_tfs:
                    logger.info(f"已有 {self.symbol or symbol} 空仓，且当前信号 K 线级别={tf} 已开过仓，忽略同级别重复开仓")
                    return
                if not tf:
                    logger.info("已有空仓，但信号未带 K 线级别，忽略重复开仓（请为 TradingView 信号添加 timeframe）")
                    return
                logger.info(
                    f"已有 {self.symbol or symbol} 空仓，收到不同 K 线级别={tf}（已开仓级别={sorted(self.position_entry_tfs)}），尝试追加开仓"
                )
            self._opening = True
            logger.info(f"收到开空信号: {symbol}  K线级别={tf or '未指定'}")
            self.last_signal = f"sell {symbol}"
            try:
                await self._open_short(symbol)
            finally:
                self._opening = False
            if self.position == "SHORT" and tf:
                self.position_entry_tfs.add(tf)

        elif action == "buy":
            if self.position != "SHORT":
                logger.info(f"无空仓，忽略平仓信号 ({symbol})")
                return
            if self.symbol and self.symbol.upper() != symbol:
                logger.info(f"持仓 {self.symbol} 与信号 {symbol} 不匹配，忽略")
                return
            logger.info(f"收到平仓信号: {symbol}  K线级别={tf or '未指定'}")
            self.last_signal = f"buy {symbol}"
            await self._safe_close("Webhook平仓信号")
        else:
            logger.warning(f"未知信号 action={action}，忽略")

    async def _risk_loop(self):
        while not self._stop:
            try:
                if self.is_enabled and self.position == "SHORT" and self.symbol:
                    await self._check_risk()
            except Exception as e:
                logger.error(f"风控循环异常: {e}")
            await asyncio.sleep(5)

    async def _check_risk(self):
        ep = self.entry_price
        if not ep:
            return

        if self.exchange in ("binance", "lighter"):
            price = await self._get_price(self.symbol)
            if price <= 0:
                return
            async with self._lock:
                if self.position != "SHORT":
                    return
                if self.exchange == "lighter":
                    self._sync_count += 1
                    if self._sync_count >= 3:
                        self._sync_count = 0
                        try:
                            pos = await self.client.get_position(self.symbol)
                            if not pos or float(pos.get("size") or 0) == 0:
                                logger.info("🧾 [Lighter] 检测到持仓已为 0（可能 TP 已成交），自动重置状态")
                                self._reset_position_state()
                                return
                        except Exception:
                            pass

                # SHORT: 止损在上方；止盈在下方
                if self.sl_price and price >= self.sl_price:
                    await self._safe_close("止损触发")
                    return
                if self.tp_price and price <= self.tp_price:
                    await self._safe_close("止盈触发")
                    return

                # 保本：盈利达到 break_even_pct → SL 下移到入场价
                if (not self.break_even_activated) and self.break_even_pct > 0:
                    trig = ep * (1 - self.break_even_pct)
                    if price <= trig:
                        self.break_even_activated = True
                        self.sl_price = ep
                        logger.info(f"🟦 保本触发: price={price:.4f} <= {trig:.4f}，SL 下移到入场价 {ep:.4f}")

                # 锁利：盈利达到 lock_profit_pct → SL 锁定在入场价 * (1 - lock_profit_sl_pct)
                if (not self.lock_profit_activated) and self.lock_profit_pct > 0 and self.lock_profit_sl_pct > 0:
                    trig = ep * (1 - self.lock_profit_pct)
                    if price <= trig:
                        self.lock_profit_activated = True
                        new_sl = ep * (1 - self.lock_profit_sl_pct)
                        self.sl_price = round(new_sl, 6)
                        logger.info(f"🟩 锁利触发: price={price:.4f} <= {trig:.4f}，SL 锁定到 {self.sl_price:.4f}")
            return

        # Hyperliquid：交易所原生 TP/SL，轮询做保本/锁利 & 同步
        price = await self._get_price(self.symbol)
        if price <= 0:
            return
        async with self._lock:
            if self.position != "SHORT":
                return

            self._sync_count += 1
            if self._sync_count >= 3:
                self._sync_count = 0
                try:
                    pos = await self.client.get_position(self.symbol)
                    if not pos or float(pos.get("size") or 0) == 0:
                        logger.info("🧾 [HL] 检测到持仓已为 0（可能 TP/SL 已触发），自动重置状态")
                        self._reset_position_state()
                        return
                except Exception:
                    pass

            # 保本/锁利：需要撤销旧 SL，重挂新的 SL
            if (not self.break_even_activated) and self.break_even_pct > 0:
                trig = ep * (1 - self.break_even_pct)
                if price <= trig:
                    self.break_even_activated = True
                    await self._cancel_exchange_tpsl()
                    self.sl_price = ep
                    await self._place_exchange_tpsl()
                    logger.info(f"🟦 保本触发(HL): SL 下移到入场价 {ep:.4f}")

            if (not self.lock_profit_activated) and self.lock_profit_pct > 0 and self.lock_profit_sl_pct > 0:
                trig = ep * (1 - self.lock_profit_pct)
                if price <= trig:
                    self.lock_profit_activated = True
                    await self._cancel_exchange_tpsl()
                    self.sl_price = round(ep * (1 - self.lock_profit_sl_pct), 6)
                    await self._place_exchange_tpsl()
                    logger.info(f"🟩 锁利触发(HL): SL 锁定到 {self.sl_price:.4f}")

    def get_status(self) -> Dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "exchange": self.exchange,
            "symbol_filter": self.symbol_filter,
            "timeframe_filter": self.timeframe_filter,
            "margin_amount": self.margin_amount,
            "leverage": self.leverage,
            "position": self.position,
            "symbol": self.symbol,
            "position_size": self.position_size,
            "entry_price": self.entry_price,
            "sl_price": self.sl_price,
            "tp_price": self.tp_price,
            "last_signal": self.last_signal,
        }

