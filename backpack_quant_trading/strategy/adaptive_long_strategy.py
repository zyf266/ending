"""
自适应做多策略 - 实盘版（TradingView Webhook 信号驱动）

开仓: 接收 Webhook {"操作":"buy"}  信号 → 市价开多
平仓: 接收 Webhook {"操作":"sell"} 信号 → 市价平多（仅当币种匹配时）

信号格式 (TradingView → POST /trading/adaptive-long/webhook):
  {"交易品种":"ETH","操作":"buy","先前仓位大小":"0"}    → 开多
  {"交易品种":"ETH","操作":"sell","先前仓位大小":"0.1"} → 平多

币种不匹配时 sell 信号自动忽略（如持仓 ETH 却收到 HYPE sell，跳过）

风控模式 (Hyperliquid):
  开仓后在交易所直接挂 SL/TP 触发单，不再轮询价格。
  轮询循环（每 5 秒）仅做两件事：
    1. 检测保本条件，激活时撤销旧 SL、重挂保本 SL
    2. 每 3 次循环同步一次交易所真实持仓（判断 TP/SL 是否已被交易所触发）
  Binance 暂保持本地轮询风控方式。
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
        lock_profit_pct: float = 0.0,     # 锁利触发盈利比例，0=不启用
        lock_profit_sl_pct: float = 0.0,  # 锁利后 SL 锁定的盈利比例
        min_ai_score_for_trade: int = 0,  # 0=不启用；买入 Webhook 须 AI 分>=该值才开单
        allow_repeat_open: bool = False,  # K线不限制时：False=同币种已有仓不再开；True=不同周期可加仓
        use_ai_sr_tpsl: bool = False,  # True=用 AI 支撑/压力位挂 SL+分批 TP（50%小级+50%同级）
    ):
        self.exchange = exchange.lower()
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
        self.instance_id = instance_id or f"al_{int(datetime.now().timestamp())}"

        self.margin_amount   = margin_amount
        self.leverage        = leverage
        self.stop_loss_pct   = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.break_even_pct  = break_even_pct
        self.lock_profit_pct    = lock_profit_pct
        self.lock_profit_sl_pct = lock_profit_sl_pct
        self.min_ai_score_for_trade = max(0, int(min_ai_score_for_trade or 0))
        self.allow_repeat_open = bool(allow_repeat_open)
        self.use_ai_sr_tpsl = bool(use_ai_sr_tpsl)
        self.pending_ai_sr_levels: Optional[Dict[str, Any]] = None
        self.symbol_filter   = symbol_filter.upper().strip() if symbol_filter else None
        self.timeframe_filter = timeframe_filter.upper().strip() if timeframe_filter else None
        # 注: XYZ 不是子账户，是 Hyperliquid HIP-3 DEX，同一键包地址可以同时下单 Perps 和 XYZ 资产。
        # 路由通过 client.find_asset_dex() 自动识别资产所属 DEX，无需手动配置地址。

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
        self.lock_profit_activated: bool    = False  # 锁利已激活标志
        self._closing:      bool            = False
        self._opening:      bool            = False  # 开仓防重入标志
        # 交易所挂单 oid
        self._sl_oid: Optional[str] = None
        self._tp_oid: Optional[str] = None
        self._tp_oid_lower: Optional[str] = None
        self._tp_oid_same: Optional[str] = None
        self._sync_count: int = 0   # 持仓同步计数器
        # 本账户上已通过开多信号建仓的 K 线级别（用于：同周期重复 buy 忽略，不同周期可加仓）
        self.position_entry_tfs: set = set()

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
        logger.info(
            "🟢 自适应做多运行中 | instance=%s | 绑定币种=%s | K线过滤=%s | AI开单门槛=%s | 重复开单=%s | AI位阶止盈止损=%s",
            self.instance_id,
            self.symbol_filter or "不限",
            self.timeframe_filter or "不限",
            self.min_ai_score_for_trade,
            "是" if self.allow_repeat_open else "否",
            "是" if self.use_ai_sr_tpsl else "否",
        )
        await self.client._get_session()
        try:
            self.balance_cache = await self._get_balance_float()
        except Exception as e:
            logger.warning(f"⚠️ 启动时获取余额失败（策略仍将运行）: {e}")
            self.balance_cache = None
        perps_str = f"{self.balance_cache:,.2f} {'USDT' if self.exchange == 'binance' else 'USDC'}" if self.balance_cache is not None else "获取失败"
        # 如果是 Hyperliquid，同时显示 XYZ DEX 余额
        xyz_bal_str = ""
        if self.exchange == "hyperliquid":
            try:
                xyz_bal = await self.client.get_balance(dex="xyz")
                xyz_bal_str = f"{xyz_bal:,.2f} USDC"
            except Exception as e:
                xyz_bal_str = f"获取失败({e})"
        logger.info("=" * 60)
        logger.info(f"🚀 自适应做多策略启动  exchange={self.exchange}  instance={self.instance_id}  币种绑定={self.symbol_filter or '任意'}  K线级别={self.timeframe_filter or '不限制'}")
        if self.exchange == "binance":
            logger.info(f"💰 币安合约账户余额: {perps_str}")
        elif self.exchange == "lighter":
            logger.info(f"💰 Lighter 账户余额: {perps_str}")
        else:
            logger.info(f"💰 Perps 主账户余额: {perps_str}")
        if xyz_bal_str:
            logger.info(f"💰 XYZ  HIP-3 余额: {xyz_bal_str}")
        logger.info(f"   SL={self.stop_loss_pct*100:.1f}%  TP={self.take_profit_pct*100:.1f}%  保本={self.break_even_pct*100:.1f}%" +
                    (f"  锁利={self.lock_profit_pct*100:.1f}%触发→SL锁={self.lock_profit_sl_pct*100:.1f}%" if self.lock_profit_pct > 0 else ""))
        logger.info(f"   保证金={self.margin_amount}×{self.leverage}x")
        logger.info(f"   等待 TradingView Webhook 信号...")
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
        """外部调用停止策略"""
        try:
            stack = "".join(traceback.format_stack(limit=8))
            logger.info(f"🧯 stop() 被调用，调用栈(末8帧):\n{stack}")
        except Exception:
            pass
        self._stop = True
        self.is_enabled = False

    # ─── 兼容层: 价格 / 余额 ─────────────────────────────
    async def _get_price(self, symbol: str) -> float:
        """获取币种当前价格（兼容 HL、Binance、Lighter）"""
        if self.exchange == "binance":
            bn_sym = _to_binance_symbol(symbol)
            data = await self.client._get("/fapi/v1/ticker/price", {"symbol": bn_sym})
            return float(data.get("price", 0))
        if self.exchange == "lighter":
            return await self.client.get_price(symbol)
        # Hyperliquid: 自动识别 DEX
        try:
            dex_name, _, _, _ = await self.client.find_asset_dex(symbol)
            return await self.client.get_price(symbol, dex=dex_name)
        except Exception:
            return await self.client.get_price(symbol)

    async def _get_balance_float(self, dex: str = "") -> float:
        """获取可用余额（兼容 HL、Binance、Lighter）
        dex: "" = Perps; "xyz" = XYZ HIP-3 DEX
        """
        if self.exchange == "binance":
            # 读取币安合约账户余额，并输出详细诊断日志
            raw = await self.client.get_balance()
            logger.info(f"[Binance 诊断] get_balance 返回 {len(raw)} 条记录: "
                        f"{[{i['asset']: i['available']} for i in raw[:5]] if raw else '空'}")
            bal_dict = {item["asset"]: item for item in raw if isinstance(item, dict) and item.get("asset")}
            usdt = bal_dict.get("USDT", {})
            result = float(usdt.get("available", 0))
            logger.info(f"[Binance 诊断] USDT 可用余额 = {result}")
            return result
        if self.exchange == "lighter":
            return await self.client.get_balance()
        return await self.client.get_balance(dex=dex)

    # ─── 持仓状态重置 ────────────────────────────────────
    async def _sync_long_position_from_exchange(self, symbol: str) -> bool:
        """从交易所同步多仓到内存（平仓前补救：内存无仓但链上有仓时可恢复）。"""
        symbol = symbol.upper().strip()
        try:
            dex_name = ""
            if self.exchange not in ("binance", "lighter"):
                try:
                    dex_name, _, _, _ = await self.client.find_asset_dex(symbol)
                except Exception:
                    dex_name = await self.client.get_asset_dex(symbol)
            positions = await self.client.get_positions(symbol=symbol, dex=dex_name or None)
            if not positions:
                return False
            pos = positions[0]
            size = abs(float(pos.get("size", 0) or 0))
            if size <= 0:
                return False
            self.symbol = symbol
            self.position = "LONG"
            self.position_size = size
            self.entry_price = float(pos.get("entry_price") or 0) or await self._get_price(symbol)
            if self.entry_price <= 0:
                self.entry_price = await self._get_price(symbol)
            self.entry_time = self.entry_time or datetime.now()
            if not self.sl_price and self.entry_price:
                self.sl_price = self.entry_price * (1 - self.stop_loss_pct)
            if not self.tp_price and self.entry_price:
                self.tp_price = self.entry_price * (1 + self.take_profit_pct)
            logger.info(
                f"🔄 已从交易所同步多仓: {symbol} 数量={size:.6f} 入场≈{self.entry_price:.4f}（内存状态已对齐）"
            )
            return True
        except Exception as e:
            logger.info(f"同步交易所持仓失败({symbol}): {e}")
            return False

    def _reset_position_state(self):
        """重置所有持仓相关字段"""
        self.position             = None
        self.entry_price          = None
        self.entry_time           = None
        self.sl_price             = None
        self.tp_price             = None
        self.break_even_activated = False
        self.lock_profit_activated = False
        self.position_size        = 0.0
        self.symbol               = None
        self._sl_oid              = None
        self._tp_oid              = None
        self._tp_oid_lower        = None
        self._tp_oid_same         = None
        self.pending_ai_sr_levels = None
        self._closing             = False
        self._opening             = False
        self.position_entry_tfs   = set()

    # ─── 交易所 SL/TP 挂单（仅 Hyperliquid）─────────────
    async def _place_exchange_tpsl(self):
        """开仓后在 Hyperliquid 直接挂止损/止盈触发单"""
        if not self.position_size or not self.sl_price or not self.tp_price:
            logger.warning("⚠️ 挂 TP/SL 单条件不足（size/sl/tp 未就绪）")
            return
        try:
            if self.exchange == "hyperliquid":
                sl_res = await self.client.place_tpsl_order(
                    symbol=self.symbol,
                    side="SELL",
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
                    side="SELL",
                    quantity=self.position_size,
                    trigger_price=self.tp_price,
                    tpsl="tp",
                )
                if tp_res.get("status") == "FAILED":
                    logger.error(f"❌ TP 挂单失败: {tp_res.get('error')}")
                else:
                    self._tp_oid = tp_res.get("orderId")

            elif self.exchange == "binance":
                # SL: 不挂交易所条件单（STOP_MARKET 容易因内盘价偏差导致即时触发秒平仓位）
                # 由软件御控周期（_check_risk 每5s）独立负责 SL
                logger.info(f"🛡️ [Binance] SL 由软件御控周期守护  SL={self.sl_price:.4f}  每5s轮询触发")

                # TP: 挂 LIMIT SELL GTC 在目标价，安全可靠
                tp_res = await self.client.place_tpsl_order(
                    symbol=self.symbol,
                    trigger_price=self.tp_price,
                    tpsl="tp",
                    quantity=self.position_size,
                )
                bn_code = tp_res.get("code")
                if bn_code is not None and int(bn_code) < 0:
                    logger.warning(f"⚠️ Binance TP LIMIT 挂单失败（{tp_res.get('msg')}），已由软件御控周期守护（每5s轮询）")
                else:
                    self._tp_oid = tp_res.get("orderId")
                    logger.info(f"📌 Binance TP LIMIT 挂单成功 oid={self._tp_oid}  目标价={self.tp_price:.4f}")

                logger.info(f"🛡️ 软件御控已就位: SL={self.sl_price:.4f}  TP={self.tp_price:.4f}  每5s轮询守护")

            elif self.exchange == "lighter":
                # SL: 交易所原生止损触发单
                sl_res = await self.client.place_tpsl_order(
                    symbol=self.symbol,
                    side="SELL",
                    quantity=self.position_size,
                    trigger_price=self.sl_price,
                    tpsl="sl",
                )
                if sl_res.get("status") == "FAILED":
                    logger.warning(f"⚠️ Lighter SL 挂单失败: {sl_res.get('error')}，转由软件御控")
                else:
                    self._sl_oid = sl_res.get("orderId")
                    logger.info(f"📌 Lighter SL 挂单成功 oid={self._sl_oid}  触发价={self.sl_price:.4f}")

                # TP: 交易所原生止盈触发单
                tp_res = await self.client.place_tpsl_order(
                    symbol=self.symbol,
                    side="SELL",
                    quantity=self.position_size,
                    trigger_price=self.tp_price,
                    tpsl="tp",
                )
                if tp_res.get("status") == "FAILED":
                    logger.warning(f"⚠️ Lighter TP 挂单失败: {tp_res.get('error')}，转由软件御控")
                else:
                    self._tp_oid = tp_res.get("orderId")
                    logger.info(f"📌 Lighter TP 挂单成功 oid={self._tp_oid}  触发价={self.tp_price:.4f}")

            logger.info(f"📌 交易所 SL/TP 挂单完成 — SL oid={self._sl_oid}  TP oid={self._tp_oid}")
        except Exception as e:
            logger.error(f"⚠️ 挂 TP/SL 单异常（风控可能不准确）: {e}")

    async def _cancel_exchange_tpsl(self):
        """撤销交易所上挂的 SL/TP 触发单（支持 Hyperliquid 和 Binance）"""
        for oid, label in [
            (self._sl_oid, "SL"),
            (self._tp_oid, "TP"),
            (self._tp_oid_lower, "TP-小级"),
            (self._tp_oid_same, "TP-同级"),
        ]:
            if oid and self.symbol:
                try:
                    await self.client.cancel_order_async(self.symbol, order_id=oid)
                    logger.info(f"🗑️ 已撤销 {label} 单 oid={oid}")
                except Exception as e:
                    logger.warning(f"撤销 {label} 单失败 oid={oid}: {e}")
        self._sl_oid = None
        self._tp_oid = None
        self._tp_oid_lower = None
        self._tp_oid_same = None

    def _round_position_qty(self, qty: float) -> float:
        q = max(0.0, float(qty))
        if q <= 0:
            return 0.0
        return round(q, 6)

    async def _place_ai_sr_tpsl(self, plan: Dict[str, Any]) -> bool:
        """按 AI 支撑/压力位挂 SL + 两档 TP（各 50% 仓位）。"""
        if not plan or not self.position_size or not self.entry_price:
            return False
        entry = float(self.entry_price)
        support = float(plan.get("support") or 0)
        tp_lower = plan.get("tp_lower_tf")
        tp_same = plan.get("tp_same_tf")
        tp_lower = float(tp_lower) if tp_lower else None
        tp_same = float(tp_same) if tp_same else None

        if support <= 0 or support >= entry * 0.998:
            logger.info("⛔ AI位阶止盈止损: 支撑位无效，回退百分比 SL/TP")
            return False

        targets = []
        if tp_lower and tp_lower > entry * 1.001:
            targets.append(("小级压力", tp_lower))
        if tp_same and tp_same > entry * 1.001 and (not tp_lower or abs(tp_same - tp_lower) / entry > 0.001):
            targets.append(("同级压力", tp_same))
        if not targets:
            logger.info("⛔ AI位阶止盈止损: 无有效压力位，回退百分比 SL/TP")
            return False

        self.sl_price = support
        self.tp_price = targets[-1][1]

        if self.exchange != "hyperliquid":
            logger.info("⚠️ AI位阶止盈止损当前仅支持 Hyperliquid，本实例回退百分比 SL/TP")
            return False

        total = self.position_size
        if len(targets) >= 2:
            half = self._round_position_qty(total / 2.0)
            qty1, qty2 = half, self._round_position_qty(total - half)
        else:
            qty1, qty2 = total, 0.0

        logger.info("=" * 60)
        logger.info("📐 AI位阶止盈止损（Hyperliquid）")
        logger.info(f"   止损(全仓): 支撑 {support:.4f}")
        for name, px in targets:
            logger.info(f"   止盈目标: {name} {px:.4f}")
        logger.info("=" * 60)

        sl_res = await self.client.place_tpsl_order(
            symbol=self.symbol,
            side="SELL",
            quantity=total,
            trigger_price=support,
            tpsl="sl",
        )
        if sl_res.get("status") == "FAILED":
            logger.info(f"⛔ AI止损挂单失败: {sl_res.get('error')}")
            return False
        self._sl_oid = sl_res.get("orderId")

        label0, px0 = targets[0]
        if qty1 > 0:
            tp1 = await self.client.place_tpsl_order(
                symbol=self.symbol,
                side="SELL",
                quantity=qty1,
                trigger_price=px0,
                tpsl="tp",
            )
            if tp1.get("status") != "FAILED":
                self._tp_oid_lower = tp1.get("orderId")
                logger.info(f"✅ AI止盈1(50%): {label0} @ {px0:.4f}  qty={qty1:.6f} oid={self._tp_oid_lower}")
            else:
                logger.info(f"⛔ AI止盈1失败: {tp1.get('error')}")

        if len(targets) >= 2 and qty2 > 0:
            label1, px1 = targets[1]
            tp2 = await self.client.place_tpsl_order(
                symbol=self.symbol,
                side="SELL",
                quantity=qty2,
                trigger_price=px1,
                tpsl="tp",
            )
            if tp2.get("status") != "FAILED":
                self._tp_oid_same = tp2.get("orderId")
                logger.info(f"✅ AI止盈2(50%): {label1} @ {px1:.4f}  qty={qty2:.6f} oid={self._tp_oid_same}")
            else:
                logger.info(f"⛔ AI止盈2失败: {tp2.get('error')}")
        elif qty1 > 0 and len(targets) == 1:
            self._tp_oid = self._tp_oid_lower

        logger.info(
            f"📌 AI位阶挂单完成 SL={self._sl_oid} TP1={self._tp_oid_lower} TP2={self._tp_oid_same}"
        )
        return True

    # ─── 开仓 ────────────────────────────────────────────
    async def _get_vault_address(self, symbol: str) -> Optional[str]:
        """[已废弃] 原子账户路由逻辑已迁移至 client.find_asset_dex()"""
        return None

    async def _open_long(self, symbol: str):
        """市价开多（自动识别 Perps/XYZ HIP-3 DEX 或 Binance）"""
        try:
            if self.exchange == "binance":
                dex_name = ""
                dex_label = "Binance 合约账户"
                # 开仓前先清理残留的旧止损/止盈单，防止上一次 session 的订单影响新仓位
                try:
                    bn_sym = symbol.upper()
                    if not bn_sym.endswith("USDT"):
                        bn_sym = f"{bn_sym}USDT"
                    await self.client.cancel_all_orders(symbol=symbol)
                    logger.info(f"🧹 开仓前已清理 {bn_sym} 所有挂单（防止旧 SL/TP 干扰）")
                except Exception as e:
                    logger.warning(f"清理旧挂单失败（可忽略）: {e}")
            else:
                try:
                    dex_name, _, _, _ = await self.client.find_asset_dex(symbol)
                except (ValueError, Exception) as e:
                    logger.info(f"⛔ 开多未成交: 资产查找失败 ({e})")
                    return
                if dex_name:
                    dex_label = "XYZ HIP-3 DEX"
                elif self.exchange == "lighter":
                    dex_label = "Lighter DEX"
                else:
                    dex_label = "Perps"
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
            bal_unit = "USDT" if self.exchange == "binance" else "USDC"
            logger.info(f"📊 交易所: {dex_label}  余额: {balance:.2f} {bal_unit}")
            # 预留 ~10% 给手续费/价格波动，避免“账面够但下单失败”
            usable = balance * 0.9
            actual_margin = self.margin_amount
            if actual_margin > usable:
                logger.info(
                    f"⛔ 开多未成交: 保证金不足 "
                    f"(DEX={dex_label} 余额={balance:.2f} {bal_unit}，"
                    f"配置保证金={actual_margin:.2f}，可用上限≈{usable:.2f}；"
                    f"请下调「保证金」或充值后再试)"
                )
                return

            if self.exchange == "binance":
                # Binance 期货 quantity 是合约数量（ETH 单位），需要将 USDT 保证金转换
                current_price = await self._get_price(symbol)
                if current_price <= 0:
                    logger.info(f"⛔ 开多未成交: 获取价格异常 {symbol}")
                    return
                # 仓位价値 = 保证金 × 杠杆
                position_value = actual_margin * self.leverage
                # 合约数量 = 仓位价値 / 当前价格，保留 3 位小数
                order_qty = round(position_value / current_price, 3)
                logger.info(f"📊 开仓计算: 保证金={actual_margin:.2f} USDT × {self.leverage}x / 价格={current_price:.2f} = 数量={order_qty:.4f} {symbol}")
                if order_qty <= 0:
                    logger.info("⛔ 开多未成交: 计算数量为 0")
                    return
                result = await self.client.place_order(
                    symbol=symbol,
                    side="BUY",
                    quantity=order_qty,
                    order_type="MARKET",
                    leverage=self.leverage,
                )
            else:
                result = await self.client.place_order(
                    symbol=symbol,
                    side="BUY",
                    quantity=actual_margin,
                    order_type="MARKET",
                    leverage=self.leverage,
                )
            # 检测下单错误（兼容 Hyperliquid status=FAILED 和 Binance code<0）
            if isinstance(result, dict):
                bn_code = result.get("code")
                if result.get("status") == "FAILED" or (bn_code is not None and int(bn_code) < 0):
                    error_msg = result.get("error") or result.get("msg", str(result))
                    logger.info(f"⛔ 开多未成交: 下单失败 {error_msg}")
                    return
            logger.info(f"[Binance 下单响应] {result}")
            # 等待成交后同步持仓状态
            await asyncio.sleep(3)
            positions = await self.client.get_positions(symbol=symbol, dex=dex_name)
            if not positions or abs(positions[0].get("size", 0)) <= 0:
                logger.info("⛔ 开多未成交: 下单后链上无持仓（可能未成交或延迟，请查交易所）")
                return

            pos = positions[0]
            self.symbol        = symbol
            self.position      = "LONG"
            self.position_size = abs(float(pos.get("size", 0)))
            self.entry_price   = float(pos.get("entry_price") or await self._get_price(symbol))
            self.entry_time    = datetime.now()
            self.sl_price      = self.entry_price * (1 - self.stop_loss_pct)
            self.tp_price      = self.entry_price * (1 + self.take_profit_pct)
            self.break_even_activated = False
            self._closing      = False
            self._sync_count   = 0

            plan = self.pending_ai_sr_levels
            placed_ai_sr = False
            if getattr(self, "use_ai_sr_tpsl", False) and plan:
                placed_ai_sr = await self._place_ai_sr_tpsl(plan)
                self.pending_ai_sr_levels = None

            be_trigger = self.entry_price * (1 + self.break_even_pct)
            logger.info("=" * 60)
            logger.info(f"🐂 开多成功: {symbol}")
            logger.info(f"   入场价:     {self.entry_price:.4f}")
            logger.info(f"   保证金:     {actual_margin:.2f} × {self.leverage}x")
            logger.info(f"   实际持仓:   {self.position_size:.6f} {symbol}")
            if placed_ai_sr:
                logger.info(f"   止损价:     {self.sl_price:.4f}  (AI支撑位)")
                logger.info(f"   止盈价:     {self.tp_price:.4f}  (AI同级压力，余仓见交易所TP2)")
            else:
                logger.info(f"   止损价:     {self.sl_price:.4f}  (-{self.stop_loss_pct*100:.1f}%)")
                logger.info(f"   止盈价:     {self.tp_price:.4f}  (+{self.take_profit_pct*100:.1f}%)")
            logger.info(f"   保本触发:   {be_trigger:.4f}  (盈利达 {self.break_even_pct*100:.1f}% 时SL移至成本价)")
            logger.info("=" * 60)

            if not placed_ai_sr and self.exchange in ("hyperliquid", "lighter"):
                await self._place_exchange_tpsl()
            elif not placed_ai_sr and self.exchange == "binance":
                logger.info("🛡️ [Binance] 使用软件轮询 + 百分比止盈止损")

        except Exception as e:
            logger.info(f"⛔ 开多未成交: 异常 {e}")

    # ─── 平仓 ────────────────────────────────────────────
    async def _close_position(self, reason: str):
        """市价平多（自动识别 Perps/XYZ HIP-3 DEX）"""
        try:
            symbol = self.symbol
            # 重新同步链上持仓，获取真实仓位大小
            if self.exchange in ("hyperliquid", "lighter"):
                sym_dex = await self.client.get_asset_dex(symbol)
                positions = await self.client.get_positions(symbol=symbol, dex=sym_dex)
                real_size = abs(float(positions[0].get("size", 0))) if positions else 0.0
            else:
                real_size = self.position_size

            entry_price = self.entry_price
            exit_price  = await self._get_price(symbol) if symbol else 0.0

            if real_size > 0:
                result = await self.client.place_order(
                    symbol=symbol,
                    side="SELL",
                    quantity=real_size,
                    order_type="MARKET",
                    reduce_only=True,
                )
                if isinstance(result, dict) and result.get("status") == "FAILED":
                    logger.error(f"平仓下单失败: {result.get('error')}")
                    return
            else:
                logger.info("链上无持仓，跳过平仓下单")

            # 盈亏统计
            if entry_price and exit_price and real_size > 0:
                pnl     = (exit_price - entry_price) * real_size
                pnl_pct = (exit_price - entry_price) / entry_price * 100
                logger.info("=" * 60)
                logger.info(f"✅ 平多完成: {symbol}  原因={reason}")
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
        """带防重入保护的平仓（先撤交易所挂单再平仓）"""
        if self.position != "LONG" or self._closing:
            return
        self._closing = True
        try:
            await self._cancel_exchange_tpsl()
            await self._close_position(reason)
        finally:
            self._closing = False

    # ─── Webhook 信号处理入口 ─────────────────────────────
    async def execute_signal(
        self,
        symbol: str,
        action: str,
        timeframe: Optional[str] = None,
        ai_sr_levels: Optional[Dict[str, Any]] = None,
    ):
        """
        由 Webhook 路由调用。
        action="buy"  → 开多（已有持仓则忽略）
        action="sell" → 平多（币种不匹配则忽略）
        """
        action = action.lower().strip()
        symbol = symbol.upper().strip()
        tf     = timeframe.upper().strip() if timeframe else ""

        # K线级别过滤：配置了级别且信号带了级别时才校验
        if self.timeframe_filter and tf and tf != self.timeframe_filter:
            logger.info(f"K线级别不匹配: 信号={tf}  策略配置={self.timeframe_filter}，忽略")
            return

        # symbol_filter 校验
        if self.symbol_filter and self.symbol_filter != symbol:
            logger.info(f"⏭️ 信号 {action} {symbol} 与绑定币种 {self.symbol_filter} 不匹配，忽略")
            return

        if action == "buy":
            if self._opening:
                logger.info(f"开仓进行中，忽略重复开仓信号 ({symbol} {tf or '未指定级别'})")
                return
            if self.position == "LONG":
                held = self.symbol or symbol
                if not getattr(self, "allow_repeat_open", False):
                    logger.info(
                        f"不重复开单=否 | 已有 {held} 多仓，忽略 {symbol} {tf or '未指定级别'} 买入（"
                        f"已开仓级别={sorted(self.position_entry_tfs) or ['—']}）"
                    )
                    return
                # 允许重复开单：同 K 线级别不重复；不同级别可加仓（K 线不限制时常用）
                if tf and tf in self.position_entry_tfs:
                    logger.info(
                        f"已有 {held} 多仓，且当前信号 K 线级别={tf} 已开过仓，忽略同级别重复开仓"
                    )
                    return
                if not tf:
                    logger.info(
                        f"已有 {held} 多仓，但信号未带 K 线级别，忽略重复开仓（请为 TradingView 信号添加 timeframe）"
                    )
                    return
                logger.info(
                    f"重复开单=是 | 已有 {held} 多仓，不同 K 线级别={tf}（已开仓级别={sorted(self.position_entry_tfs)}），尝试追加开仓"
                )
            if ai_sr_levels and getattr(self, "use_ai_sr_tpsl", False):
                self.pending_ai_sr_levels = ai_sr_levels
            self._opening = True
            logger.info(f"收到开多信号: {symbol}  K线级别={tf or '未指定'}")
            self.last_signal = f"buy {symbol}"
            try:
                await self._open_long(symbol)
            finally:
                self._opening = False
            if self.position == "LONG" and tf:
                self.position_entry_tfs.add(tf)

        elif action == "sell":
            if self.position != "LONG":
                synced = await self._sync_long_position_from_exchange(symbol)
                if not synced:
                    logger.info(
                        f"无多仓，忽略平仓信号 ({symbol})（策略内存与交易所均无 {symbol} 多仓；"
                        f"若刚发买入，请查日志是否有「⛔ 开多未成交」）"
                    )
                    return
            if self.symbol and self.symbol.upper() != symbol:
                logger.info(f"持仓 {self.symbol} 与信号 {symbol} 不匹配，忽略")
                return
            logger.info(f"收到平仓信号: {symbol}  K线级别={tf or '未指定'}")
            self.last_signal = f"sell {symbol}"
            await self._safe_close("Webhook平仓信号")

        else:
            logger.warning(f"未知信号 action={action}，忽略")

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
        ep = self.entry_price
        if not ep:
            return

        # Binance / Lighter 保留本地轮询风控（均无可靠的交易所原生条件单）
        if self.exchange in ("binance", "lighter"):
            price = await self._get_price(self.symbol)
            if price <= 0:
                return
            async with self._lock:
                if self.position != "LONG":
                    return
                # Lighter: 每3次同步一次持仓（TP LIMIT 可能已被交易所触发）
                if self.exchange == "lighter":
                    self._sync_count += 1
                    if self._sync_count >= 3:
                        self._sync_count = 0
                        try:
                            positions = await self.client.get_positions(symbol=self.symbol)
                            has_pos = any(abs(p.get("size", 0)) > 0 for p in positions)
                            if not has_pos:
                                logger.info("📊 [Lighter] 持仓已不存在（TP LIMIT 已触发），重置内部状态")
                                self._reset_position_state()
                                return
                        except Exception as e:
                            logger.warning(f"[Lighter] 持仓同步异常: {e}")
                if self.sl_price and price <= self.sl_price:
                    if self.lock_profit_activated:
                        reason = "锁利止损"
                    elif self.break_even_activated:
                        reason = "保本止损"
                    else:
                        reason = "止损"
                    logger.info(f"🛑 {reason} 触发: 当前价={price:.4f}  SL={self.sl_price:.4f}")
                    self.last_signal = reason
                    await self._safe_close(reason)
                    return
                if self.tp_price and price >= self.tp_price:
                    logger.info(f"💰 止盈触发: 当前价={price:.4f}  TP={self.tp_price:.4f}")
                    self.last_signal = "止盈"
                    await self._safe_close("止盈")
                    return
                if not self.break_even_activated and price >= ep * (1 + self.break_even_pct):
                    self.break_even_activated = True
                    self.sl_price = ep
                    logger.info(f"🛡️ 保本激活 盈利={((price - ep) / ep * 100):.2f}% → SL={self.sl_price:.4f}")
                # 锁利检测：盈利达到 lock_profit_pct 后 SL 上移到 lock_profit_sl_pct
                if (not self.lock_profit_activated and self.lock_profit_pct > 0
                        and price >= ep * (1 + self.lock_profit_pct)):
                    self.lock_profit_activated = True
                    new_sl = ep * (1 + self.lock_profit_sl_pct)
                    if new_sl > (self.sl_price or 0):
                        self.sl_price = round(new_sl, 6)
                    logger.info(f"🔒 锁利激活 盈利={((price - ep) / ep * 100):.2f}% → SL锁定至={self.sl_price:.4f} (+{self.lock_profit_sl_pct*100:.1f}%)")
            return

        # Hyperliquid: SL/TP 已由交易所接管，只做保本检测 + 持仓同步
        async with self._lock:
            if self.position != "LONG":
                return
            # 1. 每 3 次循环同步一次交易所真实持仓
            self._sync_count += 1
            if self._sync_count >= 3:
                self._sync_count = 0
                try:
                    positions = await self.client.get_positions(symbol=self.symbol, dex=await self.client.get_asset_dex(self.symbol))
                    has_pos = any(abs(p.get("size", 0)) > 0 for p in positions)
                    if not has_pos:
                        logger.info("📊 持仓已不存在（TP/SL 已由交易所触发），重置内部状态")
                        self._reset_position_state()
                        return
                except Exception as e:
                    logger.warning(f"持仓同步异常: {e}")
            # 2. 保本检测
            price = 0.0
            if not self.break_even_activated or (not self.lock_profit_activated and self.lock_profit_pct > 0):
                price = await self._get_price(self.symbol)
            if not self.break_even_activated and price > 0 and price >= ep * (1 + self.break_even_pct):
                self.break_even_activated = True
                new_sl = ep
                self.sl_price = new_sl
                logger.info(f"🛡️ 保本激活 盈利={((price - ep) / ep * 100):.2f}% → SL上移至入场价={new_sl:.4f}")
                # 撒旧 SL 单，重挂保本 SL
                if self._sl_oid:
                    try:
                        await self.client.cancel_order_async(self.symbol, order_id=self._sl_oid)
                        logger.info(f"🗑️ 旧 SL 单已撒销 oid={self._sl_oid}")
                    except Exception as e:
                        logger.warning(f"撒销旧 SL 单失败: {e}")
                    self._sl_oid = None
                try:
                    sl_res = await self.client.place_tpsl_order(
                        symbol=self.symbol,
                        side="SELL",
                        quantity=self.position_size,
                        trigger_price=new_sl,
                        tpsl="sl",
                    )
                    self._sl_oid = sl_res.get("orderId")
                    logger.info(f"📌 保本 SL 重新挂单成功 oid={self._sl_oid}")
                except Exception as e:
                    logger.error(f"保本 SL 重新挂单失败: {e}")
            # 3. 锁利检测
            if (not self.lock_profit_activated and self.lock_profit_pct > 0
                    and price > 0 and price >= ep * (1 + self.lock_profit_pct)):
                self.lock_profit_activated = True
                new_sl = ep * (1 + self.lock_profit_sl_pct)
                self.sl_price = round(new_sl, 6)
                logger.info(f"🔒 锁利激活 盈利={((price - ep) / ep * 100):.2f}% → SL锁定至={self.sl_price:.4f} (+{self.lock_profit_sl_pct*100:.1f}%)")
                # 撒旧旧 SL 单，重挂锁利 SL
                if self._sl_oid:
                    try:
                        await self.client.cancel_order_async(self.symbol, order_id=self._sl_oid)
                        logger.info(f"🗑️ 旧 SL 单已撒销 oid={self._sl_oid}")
                    except Exception as e:
                        logger.warning(f"撒销旧 SL 单失败: {e}")
                    self._sl_oid = None
                try:
                    sl_res = await self.client.place_tpsl_order(
                        symbol=self.symbol,
                        side="SELL",
                        quantity=self.position_size,
                        trigger_price=self.sl_price,
                        tpsl="sl",
                    )
                    self._sl_oid = sl_res.get("orderId")
                    logger.info(f"📌 锁利 SL 挂单成功 oid={self._sl_oid}")
                except Exception as e:
                    logger.error(f"锁利 SL 挂单失败: {e}")
