"""
自动平仓策略（TradingView Webhook 信号驱动）

需求：
- 启动时：用用户输入的私钥/API Key + 币种，检查当前是否有该币种持仓（多/空均可）。
- 运行中：收到 TradingView 的 sell 信号时，若币种匹配则平掉该币种仓位；buy 信号忽略。
"""

import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from backpack_quant_trading.config.settings import config
from backpack_quant_trading.core.hyperliquid_client import HyperliquidAPIClient
from backpack_quant_trading.core.binance_client import BinanceAPIClient
from backpack_quant_trading.core.lighter_client import LighterAPIClient

logger = logging.getLogger("auto_close")
logger.setLevel(logging.INFO)
if not logger.handlers:
    log_dir = Path(config.log_dir) if hasattr(config, "log_dir") else Path("./log")
    log_dir.mkdir(parents=True, exist_ok=True)
    _fh = logging.FileHandler(log_dir / "auto_close.log", encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", "%Y-%m-%d %H:%M:%S"))
    logger.addHandler(_fh)
    _ch = logging.StreamHandler(sys.stdout)
    _ch.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", "%H:%M:%S"))
    logger.addHandler(_ch)


class AutoCloseStrategy:
    def __init__(
        self,
        coin: str,
        exchange: str = "hyperliquid",
        private_key: Optional[str] = None,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        account_index: int = 0,
        api_key_index: int = 2,
        instance_id: str = "",
        wallet_memo: str = "",
    ):
        self.exchange = (exchange or "hyperliquid").lower().strip()
        # 统一规范化币种：支持 "NVDAUSDT.P" / "NVDA-USD" / "xyz:NVDA" / "XYZ:NVDA"
        _c = (coin or "").strip()
        _c = _c.split(":")[-1]
        if _c.upper().endswith(".P"):
            _c = _c[:-2]
        for suffix in ["USDT.P", "USDC.P", "USDT", "USDC", "USD", "PERP", "/USDT", "/USD"]:
            if _c.upper().endswith(suffix.upper()):
                _c = _c[: -len(suffix)]
                break
        self.symbol_filter = _c.upper().strip()
        if not self.symbol_filter:
            self.symbol_filter = "ETH"

        self.instance_id = instance_id or f"ac_{int(datetime.now().timestamp())}"
        self.wallet_memo = wallet_memo or ""

        if self.exchange == "binance":
            self.client = BinanceAPIClient(api_key=api_key, secret_key=api_secret)
        elif self.exchange == "lighter":
            pk = (private_key or "").strip()
            if not pk:
                raise ValueError("请提供 Lighter 私鑰")
            self.client = LighterAPIClient(
                private_key=pk,
                account_index=int(account_index or 0),
                api_key_index=int(api_key_index or 2),
            )
        else:
            pk = (private_key or "").strip() or getattr(config.hyperliquid, "PRIVATE_KEY", "")
            self.client = HyperliquidAPIClient(private_key=pk)

        self._stop = False
        self.is_enabled = True
        self.start_time = datetime.now()
        self.last_signal: str = "—"
        self.has_position: bool = False
        self.position_side: Optional[str] = None  # long / short / None
        self.position_size: float = 0.0
        self._lock: Optional[asyncio.Lock] = None

    async def run(self):
        self._lock = asyncio.Lock()
        await self.client._get_session()
        await self._sync_position()
        logger.info("=" * 60)
        logger.info(
            f"🚀 自动平仓策略启动 exchange={self.exchange} instance={self.instance_id} 币种={self.symbol_filter}"
            + (f" memo={self.wallet_memo}" if self.wallet_memo else "")
        )
        if self.has_position:
            logger.info(f"📌 启动检测：当前有持仓 side={self.position_side} size={self.position_size}")
        else:
            logger.info("📌 启动检测：当前无持仓（收到 sell 时仍会再次检查并尝试平仓）")
        logger.info("📡 等待 TradingView Webhook 信号...")
        logger.info("   规则：若当前为多仓(long) → 收到 sell 才平仓；若当前为空仓(short) → 收到 buy 才平仓；其余信号忽略")
        logger.info("=" * 60)

        # 简单同步循环：避免用户手动平仓后状态不刷新
        while not self._stop:
            try:
                await asyncio.sleep(10)
                await self._sync_position()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"同步持仓失败: {repr(e)}")
                await asyncio.sleep(3)

        try:
            await self.client.close()
        except Exception:
            pass
        logger.info(f"✅ 策略已停止: {self.instance_id}")

    def stop(self):
        self._stop = True
        self.is_enabled = False

    async def _sync_position(self):
        try:
            if self.exchange == "binance":
                positions = await self.client.get_positions(self.symbol_filter)
                if positions:
                    p = positions[0]
                    amt = float(p.get("positionAmt") or 0.0)
                    self.has_position = abs(amt) > 0
                    self.position_size = abs(amt)
                    self.position_side = "long" if amt > 0 else ("short" if amt < 0 else None)
                else:
                    self.has_position = False
                    self.position_side = None
                    self.position_size = 0.0
                return

            if self.exchange == "lighter":
                positions = await self.client.get_positions(symbol=self.symbol_filter)
            else:
                # Hyperliquid: 可能在 Perps 或 XYZ HIP-3 DEX 持仓，先识别 dex 再查持仓
                try:
                    dex_name = await self.client.get_asset_dex(self.symbol_filter)
                except Exception:
                    dex_name = ""
                positions = await self.client.get_positions(symbol=self.symbol_filter, dex=dex_name)
            target = next((p for p in positions if p.get("symbol")), None)
            if target:
                self.has_position = True
                self.position_side = str(target.get("side") or "").lower() or None
                self.position_size = float(abs(target.get("size") or 0.0))
            else:
                self.has_position = False
                self.position_side = None
                self.position_size = 0.0
        except Exception:
            # 不抛出，交由上层日志
            raise

    async def execute_signal(self, signal_symbol: str, action: str):
        """由 Webhook 路由调用。"""
        if self._stop or not self.is_enabled:
            return
        if not self._lock:
            self._lock = asyncio.Lock()

        act = (action or "").lower().strip()
        sym = (signal_symbol or "").upper().strip()
        self.last_signal = f"{sym}:{act}" if sym else (act or "—")

        # 仅识别 buy/sell；其它动作忽略
        if act not in ("buy", "sell"):
            return

        # 币种不匹配直接忽略
        if sym and sym != self.symbol_filter:
            logger.info(f"⏭️ 忽略信号：symbol 不匹配 {sym} != {self.symbol_filter}")
            return

        async with self._lock:
            # 触发前再同步一次，确保当前确实有仓位，并据此决定“平仓信号方向”
            await self._sync_position()
            if not self.has_position:
                logger.info(f"🟡 收到 {act} 但当前无 {self.symbol_filter} 持仓，忽略")
                return

            pos_side = (self.position_side or "").lower().strip()
            # 规则：
            # - 多仓 long：sell 平仓，buy 忽略
            # - 空仓 short：buy 平仓，sell 忽略
            close_action = "sell" if pos_side != "short" else "buy"
            if act != close_action:
                logger.info(
                    f"⏭️ 忽略信号：当前仓位={pos_side or 'unknown'}，仅 {close_action} 触发平仓，本次={act}"
                )
                return

            logger.info(
                f"🔥 收到 {act}，执行平仓: {self.symbol_filter} side={self.position_side} size={self.position_size}"
            )
            try:
                if self.exchange == "lighter":
                    # Lighter: 市价 IOC reduce_only 可能部分成交，这里循环补单直到仓位归零或达到重试上限
                    max_attempts = 20
                    # Lighter 最小下单单位（按市场 size_decimals 推算）
                    try:
                        _, _, _, sz_dec = await self.client.find_asset_dex(self.symbol_filter)
                        min_unit = 1 / (10 ** int(sz_dec or 4))
                    except Exception:
                        min_unit = 0.0001
                    for attempt in range(1, max_attempts + 1):
                        positions = await self.client.get_positions(symbol=self.symbol_filter)
                        target = next((p for p in positions if p.get("symbol")), None)
                        if not target:
                            logger.info(f"✅ Lighter 已无 {self.symbol_filter} 持仓（attempt={attempt}）")
                            break
                        t_side = str(target.get("side") or "").lower()
                        t_sz = float(abs(target.get("size") or 0.0))
                        if t_sz <= 0:
                            logger.info(f"✅ Lighter 已无 {self.symbol_filter} 持仓（size<=0, attempt={attempt}）")
                            break
                        if t_sz < min_unit:
                            # 小于最小下单单位：无法再通过交易接口继续平仓，属于 dust 残仓
                            logger.warning(
                                f"⚠️ Lighter 残仓小于最小单位，无法继续平仓: symbol={self.symbol_filter} "
                                f"side={t_side} size={t_sz} < min_unit≈{min_unit}。"
                                f"这通常只能在平台 UI 侧处理或等待系统结算/对齐。"
                            )
                            break

                        # 平仓侧：多仓->SELL；空仓->BUY
                        side = "SELL" if t_side == "long" else "BUY"
                        logger.info(f"📌 Lighter 平仓前持仓: side={t_side} size={t_sz} (attempt={attempt}/{max_attempts})")
                        # attempt=1 尽量“一笔扫完”：reduce_only 允许 quantity 超出持仓，交易所会按实际持仓截断
                        qty = t_sz * 5 if attempt == 1 else t_sz
                        res = await self.client.place_order(
                            symbol=self.symbol_filter,
                            side=side,
                            quantity=qty,
                            order_type="MARKET",
                            reduce_only=True,
                        )
                        logger.info(f"🧾 Lighter 平仓下单返回(attempt={attempt}): {res}")
                        if isinstance(res, dict) and str(res.get("status") or "").upper() not in ("FILLED", "OK", "SUCCESS"):
                            logger.warning(f"⚠️ Lighter 平仓下单失败(attempt={attempt}): {res.get('error') or res}")
                            break
                        # 给链上撮合/索引一点时间，然后再次检查是否还有剩余仓位
                        await asyncio.sleep(1.0 if attempt < 3 else 2.0)
                else:
                    await self.client.close_position(self.symbol_filter)
            except Exception as e:
                logger.error(f"❌ 平仓失败: {repr(e)}")
                raise

            # 平仓后刷新状态
            await self._sync_position()

    def get_status(self) -> dict:
        return {
            "instance_id": self.instance_id,
            "exchange": self.exchange,
            "symbol_filter": self.symbol_filter,
            "wallet_memo": self.wallet_memo,
            "start_time": self.start_time.isoformat(),
            "running": not self._stop,
            "enabled": bool(self.is_enabled),
            "has_position": bool(self.has_position),
            "position_side": self.position_side,
            "position_size": self.position_size,
            "last_signal": self.last_signal,
        }

