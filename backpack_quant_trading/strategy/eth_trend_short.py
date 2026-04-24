"""
ETH 趋势做空策略 - 实盘版（基于 hype_backtest.py 逻辑）

进场: (4H MACD死叉[1]  OR  2H收盘下穿日线WMA15)  AND  2H MACD[1]偏空
离场: 2H MACD金叉[1]  |  止盈  |  止损  |  锁利  |  保本

参数默认值:
  SL=3%  TP=10%  锁利触发=4%→保护2%  保本=5%  价格下限=2000

数据源: Hyperliquid API  |  周期: 2H进场 + 2H离场
"""

import asyncio
import json
import logging
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List

import aiohttp

import numpy as np
import pandas as pd

from backpack_quant_trading.config.settings import config
from backpack_quant_trading.core.hyperliquid_client import HyperliquidAPIClient
from backpack_quant_trading.core.binance_client import BinanceAPIClient, _to_binance_symbol

# ─── 日志 ──────────────────────────────────────────────────────────────────────
logger = logging.getLogger("eth_trend_short")
logger.setLevel(logging.INFO)
if not logger.handlers:
    log_dir = Path(config.log_dir) if hasattr(config, "log_dir") else Path("./log")
    log_dir.mkdir(parents=True, exist_ok=True)
    _fh = logging.FileHandler(log_dir / "eth_trend_short.log", encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", "%Y-%m-%d %H:%M:%S"))
    logger.addHandler(_fh)
    _ch = logging.StreamHandler(sys.stdout)
    _ch.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", "%H:%M:%S"))
    logger.addHandler(_ch)

# ─── 指标工具 ──────────────────────────────────────────────────────────────────
_MACD_FAST, _MACD_SLOW, _MACD_SIG = 12, 26, 9
_WMA_LEN = 15


def _wma(s: pd.Series, p: int) -> pd.Series:
    w = np.arange(1, p + 1, dtype=float)
    return s.rolling(p).apply(lambda x: np.dot(x, w) / w.sum(), raw=True)


def _macd(s: pd.Series):
    ef = s.ewm(span=_MACD_FAST, adjust=False).mean()
    es = s.ewm(span=_MACD_SLOW, adjust=False).mean()
    macd = ef - es
    sig  = macd.ewm(span=_MACD_SIG, adjust=False).mean()
    return macd, sig


def _compute_signals(bars_2h: list, bars_4h: list, bars_1d: list):
    """
    计算最新 2H bar 的进场/离场信号。
    返回: (entry_signal: bool, exit_signal: bool, macd_bias: bool, debug: dict)
    """
    if len(bars_2h) < 40 or len(bars_4h) < 40 or len(bars_1d) < 20:
        return False, False, False, {"error": "K线数量不足"}

    df2 = pd.DataFrame(bars_2h)
    df4 = pd.DataFrame(bars_4h)
    d1  = pd.DataFrame(bars_1d)

    # ── 日线 WMA15 ─────────────────────────────────────
    d1["wma"] = _wma(d1["c"], _WMA_LEN)
    d1["wma_s1"] = d1["wma"].shift(1)

    # ── 4H MACD死叉[1] ──────────────────────────────────
    m4, s4 = _macd(df4["c"])
    df4["m_s1"] = m4.shift(1); df4["s_s1"] = s4.shift(1)
    df4["m_s2"] = m4.shift(2); df4["s_s2"] = s4.shift(2)
    df4["dc4h"] = (df4["m_s2"] >= df4["s_s2"]) & (df4["m_s1"] < df4["s_s1"])

    # ── 2H MACD ─────────────────────────────────────────
    m2, s2 = _macd(df2["c"])
    df2["m_s1"] = m2.shift(1); df2["s_s1"] = s2.shift(1)
    df2["m_s2"] = m2.shift(2); df2["s_s2"] = s2.shift(2)
    df2["gc2h"]      = (df2["m_s2"] <= df2["s_s2"]) & (df2["m_s1"] > df2["s_s1"])
    df2["macd_bias"] = df2["m_s1"] < df2["s_s1"]   # D条件: 偏空=True

    # ── 对齐到 2H 时间轴 ────────────────────────────────
    for df in [df2, df4, d1]:
        df.sort_values("t", inplace=True)

    # 日线WMA下穿（在2H时间轴上）
    _merged_wma = pd.merge_asof(
        df2[["t"]].copy(),
        d1[["t", "wma_s1"]].rename(columns={"wma_s1": "_dw"}),
        on="t", direction="backward"
    )
    df2["_dw"] = _merged_wma["_dw"].values
    df2["crossunder_wma"] = (
        (df2["c"].shift(1) >= df2["_dw"].shift(1)) &
        (df2["c"] < df2["_dw"])
    ).fillna(False)

    # 4H dc4h → 2H
    df2 = pd.merge_asof(df2, df4[["t", "dc4h"]], on="t", direction="backward")

    # 4H边沿检测：第2根2H bar
    _4H_MS = 14_400_000
    df2["_4h_start"] = (df2["t"] // _4H_MS) * _4H_MS
    _is_second = (
        (df2["_4h_start"] == df2["_4h_start"].shift(1).fillna(-1)) &
        (df2["_4h_start"] != df2["_4h_start"].shift(2).fillna(-1))
    )
    df2["dc4h"] = df2["dc4h"].fillna(False) & _is_second

    # 取最后一根已完成的 bar（index -2，-1 是当前未完成 bar）
    row = df2.iloc[-2]

    entry_sig = (bool(row["dc4h"]) or bool(row["crossunder_wma"])) and bool(row["macd_bias"])
    exit_sig  = bool(row["gc2h"])
    bias      = bool(row["macd_bias"])

    debug = {
        "bar_time": int(row["t"]),
        "bar_close": float(row["c"]),
        "dc4h": bool(row["dc4h"]),
        "crossunder_wma": bool(row["crossunder_wma"]),
        "macd_bias": bias,
        "gc2h": bool(row["gc2h"]),
    }
    return entry_sig, exit_sig, bias, debug


# ─── 策略主类 ──────────────────────────────────────────────────────────────────
class ETHTrendShortStrategy:
    """
    ETH 趋势做空策略 - 实盘版
    每 5 分钟扫描一次，检测 2H bar 是否有新信号；每 30 秒轮询风控。
    """

    def __init__(
        self,
        symbol: str = "ETH",
        private_key: Optional[str] = None,
        exchange: str = "hyperliquid",
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        instance_id: str = "",
        margin_amount: float = 20.0,
        leverage: int = 50,
        stop_loss_pct: float = 0.03,
        take_profit_pct: float = 0.10,
        lockin_trig_pct: float = 0.04,
        lockin_prot_pct: float = 0.02,
        breakeven_pct: float = 0.03,
        price_filter_min: float = 2000.0,
    ):
        self.symbol        = symbol.upper()
        self.exchange      = exchange.lower()
        self.instance_id   = instance_id or f"eth_trend_{int(datetime.now().timestamp())}"
        if self.exchange == "binance":
            self.client = BinanceAPIClient(api_key=api_key, secret_key=api_secret)
        else:
            self.private_key = private_key or config.hyperliquid.PRIVATE_KEY
            self.client = HyperliquidAPIClient(private_key=self.private_key)

        self.margin_amount   = margin_amount
        self.leverage        = leverage
        self.stop_loss_pct   = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.lockin_trig_pct = lockin_trig_pct
        self.lockin_prot_pct = lockin_prot_pct
        self.breakeven_pct   = breakeven_pct
        self.price_filter_min = price_filter_min

        # 持仓状态
        self.position:     Optional[str]   = None   # "SHORT" | None
        self.position_size: float          = 0.0
        self.entry_price:  Optional[float] = None
        self.entry_time:   Optional[datetime] = None
        self.sl_price:     Optional[float] = None
        self.tp_price:     Optional[float] = None
        self.lockin_on:    bool            = False
        self.be_on:        bool            = False
        self._closing:     bool            = False

        # 运行状态
        self._stop     = False
        self.is_enabled = True
        self.start_time = datetime.now()
        self.balance_cache: Optional[float] = None
        self.last_signal: str = "—"
        self.last_debug: dict = {}
        self._lock = None

        # K线缓存（启动时预加载500根，WebSocket持续更新）
        self._bars_2h: List[dict] = []
        self._bars_4h: List[dict] = []
        self._bars_1d: List[dict] = []
        self._ws_last_bar_ts: int = 0   # 用于检测2H新bar出现

    # ─── 主循环 ─────────────────────────────────────────
    async def run(self):
        self._lock = asyncio.Lock()
        await self.client._get_session()
        await self._sync_position()
        logger.info("=" * 60)
        logger.info(f"🚀 ETH趋势做空策略启动  exchange={self.exchange}  symbol={self.symbol}  instance={self.instance_id}")
        logger.info(f"   SL={self.stop_loss_pct*100:.0f}%  TP={self.take_profit_pct*100:.0f}%  "
                    f"锁利={self.lockin_trig_pct*100:.0f}%→{self.lockin_prot_pct*100:.0f}%  "
                    f"保本={self.breakeven_pct*100:.0f}%  价格下限={self.price_filter_min}")
        bal_str = f"{self.balance_cache:,.2f} USDC" if self.balance_cache is not None else "--"
        logger.info(f"💰 账户余额: {bal_str}")
        logger.info("=" * 60)

        # ① 预加载历史K线
        if self.exchange == "binance":
            await self._preload_bars_binance(500)
        else:
            await self._preload_bars(500)

        # ② 两个并发任务：WebSocket实时K线 + 30s风控轮询
        if self.exchange == "binance":
            signal_task = asyncio.create_task(self._ws_loop_binance())
        else:
            signal_task = asyncio.create_task(self._ws_loop())
        risk_task = asyncio.create_task(self._risk_loop())
        try:
            await asyncio.gather(signal_task, risk_task)
        except asyncio.CancelledError:
            pass
        finally:
            await self.client.close()
            logger.info(f"✅ 策略已停止: {self.instance_id}")

    # ─── 格式转换 ────────────────────────────────────────
    @staticmethod
    def _norm_bar(bar: dict) -> dict:
        """将 Binance K线格式 {time,open,...} 统一为内部格式 {t,o,h,l,c,v}"""
        if "t" in bar:
            return bar  # 已是 HL 格式
        return {
            "t": int(bar.get("time", 0)),
            "o": float(bar.get("open", 0)),
            "h": float(bar.get("high", 0)),
            "l": float(bar.get("low", 0)),
            "c": float(bar.get("close", 0)),
            "v": float(bar.get("volume", 0)),
        }

    # ─── 兼容层：价格 / 余额 / 下单 ────────────────────────
    async def _get_price(self) -> float:
        """获取标记价格（兼容 HL 和 Binance）"""
        if self.exchange == "binance":
            bn_sym = _to_binance_symbol(self.symbol)
            data = await self.client._get("/fapi/v1/ticker/price", {"symbol": bn_sym})
            return float(data.get("price", 0))
        return await self.client.get_price(self.symbol)

    async def _get_balance_float(self) -> float:
        """获取 USDT 可用余额（兼容 HL 和 Binance）"""
        if self.exchange == "binance":
            return await self.client.get_usdt_balance()
        return await self.client.get_balance()

    async def _open_short_order(self, qty: float) -> bool:
        """开空仓（兼容 HL 和 Binance）"""
        if self.exchange == "binance":
            try:
                await self.client.set_leverage(self.symbol, self.leverage)
                await self.client.set_margin_type(self.symbol, "ISOLATED")
                data = await self.client.execute_order(
                    self.symbol, "SELL", qty, order_type="MARKET"
                )
                return bool(data.get("orderId") or data.get("status") in ("FILLED", "NEW"))
            except Exception as e:
                logger.error(f"[Binance] 开空失败: {e}")
                return False
        return await self.client.open_short_position(qty)

    async def _close_short_order(self) -> bool:
        """平空仓（兼容 HL 和 Binance）"""
        if self.exchange == "binance":
            try:
                result = await self.client.close_position(self.symbol)
                return True  # close_position 不报错即视为成功
            except Exception as e:
                logger.error(f"[Binance] 平空失败: {e}")
                return False
        return await self.client.close_position(self.symbol)

    # ─── 预加载历史K线 ──────────────────────────────────
    async def _preload_bars(self, limit: int = 500):
        """启动时预加载历史K线（Hyperliquid），为指标计算预热"""
        logger.info(f"📦 预加载历史K线(HL): 2H×{limit}  4H×{limit}  1D×200 ...")
        try:
            self._bars_2h = await self.client.get_klines(self.symbol, "2h", limit=limit)
            self._bars_4h = await self.client.get_klines(self.symbol, "4h", limit=limit)
            self._bars_1d = await self.client.get_klines(self.symbol, "1d", limit=200)
            logger.info(f"   ✅ 预加载完成  2H={len(self._bars_2h)}根  "
                        f"4H={len(self._bars_4h)}根  1D={len(self._bars_1d)}根")
        except Exception as e:
            logger.error(f"   ❌ 预加载失败: {e}")

    async def _preload_bars_binance(self, limit: int = 500):
        """启动时预加载历史K线（Binance），为指标计算预热"""
        logger.info(f"📦 预加载历史K线(Binance): 2H×{limit}  4H×{limit}  1D×200 ...")
        try:
            raw_2h = await self.client.get_klines(self.symbol, "2h", limit=limit)
            raw_4h = await self.client.get_klines(self.symbol, "4h", limit=limit)
            raw_1d = await self.client.get_klines(self.symbol, "1d", limit=200)
            self._bars_2h = [self._norm_bar(b) for b in raw_2h]
            self._bars_4h = [self._norm_bar(b) for b in raw_4h]
            self._bars_1d = [self._norm_bar(b) for b in raw_1d]
            logger.info(f"   ✅ 预加载完成  2H={len(self._bars_2h)}根  "
                        f"4H={len(self._bars_4h)}根  1D={len(self._bars_1d)}根")
        except Exception as e:
            logger.error(f"   ❌ 预加载失败: {e}")

    # ─── Binance WebSocket 实时K线循环 ─────────────────────
    async def _ws_loop_binance(self):
        """
        订阅 Binance USD-M Futures 2H K线，断线自动重连。
        wss://fstream.binance.com/ws/{symbol}@kline_2h
        """
        bn_sym = _to_binance_symbol(self.symbol).lower()
        WS_URL = f"wss://fstream.binance.com/ws/{bn_sym}@kline_2h"
        _raw_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
        proxy = _raw_proxy if _raw_proxy and "127.0.0.1" not in _raw_proxy and "localhost" not in _raw_proxy else None

        while not self._stop:
            try:
                logger.info(f"🔌 [Binance WS] 正在连接: {WS_URL} proxy={proxy or '无'}")
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(
                        WS_URL,
                        proxy=proxy,
                        heartbeat=20,
                        timeout=aiohttp.ClientWSTimeout(ws_close=30.0),
                    ) as ws:
                        logger.info(f"📡 [Binance WS] 已连接，订阅 {bn_sym.upper()}/2H K线")

                        async for msg in ws:
                            if self._stop:
                                break
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                try:
                                    data = json.loads(msg.data)
                                except Exception:
                                    continue

                                kline = data.get("k")
                                if not kline:
                                    continue

                                bar_ts = int(kline.get("t", 0))
                                if bar_ts == 0:
                                    continue

                                # 更新 2H 缓存（统一格式）
                                self._update_bar_cache(self._bars_2h, {
                                    "t": bar_ts,
                                    "o": float(kline.get("o", 0)),
                                    "h": float(kline.get("h", 0)),
                                    "l": float(kline.get("l", 0)),
                                    "c": float(kline.get("c", 0)),
                                    "v": float(kline.get("v", 0)),
                                })

                                # 新bar出现（时间戳变化）→ 上一根已完成
                                if self._ws_last_bar_ts != 0 and bar_ts != self._ws_last_bar_ts:
                                    logger.info(
                                        f"🕯️ [Binance] 新2H bar: "
                                        f"{datetime.fromtimestamp(bar_ts/1000).strftime('%m-%d %H:%M')}  "
                                        f"close={kline.get('c')}"
                                    )
                                    await self._refresh_slow_bars()
                                    if self.is_enabled:
                                        await self._on_new_bar()

                                self._ws_last_bar_ts = bar_ts

                            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                logger.warning(f"⚠️ [Binance WS] 连接中断 type={msg.type.name}，5s后重连")
                                break

                if not self._stop:
                    logger.warning("⚠️ [Binance WS] 服务器关闭连接，5s后重连")
                    await asyncio.sleep(5)

            except asyncio.CancelledError:
                break
            except Exception as e:
                if not self._stop:
                    logger.warning(f"⚠️ [Binance WS] 异常({type(e).__name__}: {e!r})，5s后重连")
                    await asyncio.sleep(5)

    # ─── Hyperliquid WebSocket 实时K线循环 ───────────────────
    async def _ws_loop(self):
        """
        订阅 Hyperliquid WebSocket 2H K线（使用 aiohttp，自动走代理）。
        检测到新bar出现（bar时间戳变化）→ 刷新4H/1D → 计算信号。
        断线自动重连。
        """
        HL_WS = "wss://api.hyperliquid.xyz/ws"
        asset  = self.symbol.upper()
        # 自动读取环境变量中的代理设置（过滤 127.0.0.1 本地代理，服务器上无效）
        _raw_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
        proxy = _raw_proxy if _raw_proxy and "127.0.0.1" not in _raw_proxy and "localhost" not in _raw_proxy else None

        while not self._stop:
            try:
                logger.info(f"🔌 正在连接 WebSocket: {HL_WS} proxy={proxy or '无'}")
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(
                        HL_WS,
                        proxy=proxy,
                        heartbeat=20,
                        timeout=aiohttp.ClientWSTimeout(ws_close=30.0),
                    ) as ws:
                        sub_msg = json.dumps({
                            "method": "subscribe",
                            "subscription": {"type": "candle", "coin": asset, "interval": "2h"}
                        })
                        await ws.send_str(sub_msg)
                        logger.info(f"📡 WebSocket 已连接，订阅 {asset}/2H K线")

                        async for msg in ws:
                            if self._stop:
                                break

                            if msg.type == aiohttp.WSMsgType.TEXT:
                                try:
                                    data = json.loads(msg.data)
                                except Exception:
                                    continue

                                if data.get("channel") != "candle":
                                    ch = data.get("channel") or data.get("type") or "unknown"
                                    if ch not in ("subscriptionResponse", "pong"):
                                        logger.debug(f"WS msg channel={ch}: {str(data)[:120]}")
                                    continue

                                bar    = data.get("data", {})
                                bar_ts = int(bar.get("t", 0))
                                if bar_ts == 0:
                                    continue

                                # 更新2H缓存
                                self._update_bar_cache(self._bars_2h, {
                                    "t": bar_ts,
                                    "o": float(bar.get("o", 0)),
                                    "h": float(bar.get("h", 0)),
                                    "l": float(bar.get("l", 0)),
                                    "c": float(bar.get("c", 0)),
                                    "v": float(bar.get("v", 0)),
                                })

                                # 新bar出现（时间戳变化）→ 上一根bar已完成
                                if self._ws_last_bar_ts != 0 and bar_ts != self._ws_last_bar_ts:
                                    logger.info(
                                        f"🕯️ 新2H bar: "
                                        f"{datetime.fromtimestamp(bar_ts/1000).strftime('%m-%d %H:%M')}  "
                                        f"close={bar.get('c')}"
                                    )
                                    await self._refresh_slow_bars()
                                    if self.is_enabled:
                                        await self._on_new_bar()

                                self._ws_last_bar_ts = bar_ts

                            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                logger.warning(f"⚠️ WebSocket连接中断 type={msg.type.name}，5s后重连")
                                break

                # 正常退出 async for → 服务器关闭了连接
                if not self._stop:
                    logger.warning("⚠️ WebSocket连接已被服务器关闭，5s后重连")
                    await asyncio.sleep(5)

            except asyncio.CancelledError:
                break
            except Exception as e:
                if not self._stop:
                    logger.warning(f"⚠️ WebSocket异常({type(e).__name__}: {e!r})，5s后重连")
                    await asyncio.sleep(5)



    @staticmethod
    def _update_bar_cache(cache: list, bar: dict, max_size: int = 600):
        """追加或更新最后一根K线，超出上限时移除最旧的"""
        if cache and cache[-1]["t"] == bar["t"]:
            cache[-1] = bar          # 更新当前未完成bar
        else:
            cache.append(bar)        # 追加新bar
        if len(cache) > max_size:
            del cache[0]

    async def _refresh_slow_bars(self):
        """新2H bar出现时，通过REST刷新4H和1D K线缓存"""
        try:
            if self.exchange == "binance":
                raw_4h = await self.client.get_klines(self.symbol, "4h", limit=500)
                raw_1d = await self.client.get_klines(self.symbol, "1d", limit=200)
                self._bars_4h = [self._norm_bar(b) for b in raw_4h]
                self._bars_1d = [self._norm_bar(b) for b in raw_1d]
            else:
                self._bars_4h = await self.client.get_klines(self.symbol, "4h", limit=500)
                self._bars_1d = await self.client.get_klines(self.symbol, "1d", limit=200)
        except Exception as e:
            logger.warning(f"刷新4H/1D K线失败: {e}")

    async def _on_new_bar(self):
        """新2H bar确认后计算进/离场信号"""
        entry_sig, exit_sig, bias, debug = _compute_signals(
            self._bars_2h, self._bars_4h, self._bars_1d
        )
        self.last_debug = debug
        if "error" in debug:
            logger.warning(f"信号计算失败: {debug['error']}")
            return

        bar_ts    = debug["bar_time"]
        bar_close = debug["bar_close"]
        logger.info(
            f"📊 信号  bar={datetime.fromtimestamp(bar_ts/1000).strftime('%m-%d %H:%M')}  "
            f"close={bar_close:.4f}  dc4h={debug['dc4h']}  "
            f"cross={debug['crossunder_wma']}  bias={bias}  gc2h={debug['gc2h']}"
        )

        async with self._lock:
            if self.position is None and entry_sig:
                if self.price_filter_min > 0 and bar_close < self.price_filter_min:
                    logger.info(f"  ↳ 价格 {bar_close:.2f} < 下限 {self.price_filter_min}，跳过进场")
                else:
                    logger.info("  ↳ 🔴 进场信号，准备开空")
                    self.last_signal = "进场信号"
                    await self._open_short()

            elif self.position == "SHORT" and exit_sig:
                logger.info("  ↳ 🟢 2H金叉离场信号")
                self.last_signal = "金叉离场"
                await self._safe_close("2H MACD金叉离场")

    # ─── 风控循环（每 30 秒检查 SL/TP/LOCKIN/BE）───────
    async def _risk_loop(self):
        while not self._stop:
            try:
                if self.is_enabled and self.position == "SHORT":
                    await self._check_risk()
            except Exception as e:
                logger.error(f"风控循环异常: {e}")
            await asyncio.sleep(30)

    async def _check_risk(self):
        price = await self._get_price()
        if price <= 0 or self.entry_price is None:
            return

        ep = self.entry_price
        sl = self.sl_price
        tp = self.tp_price
        async with self._lock:
            if self.position != "SHORT":
                return

            # 止损触发
            if sl and price >= sl:
                reason = "保本止损" if self.be_on else ("锁利止损" if self.lockin_on else "止损")
                logger.info(f"🛑 {reason} 触发: 当前价={price:.4f} SL={sl:.4f}")
                self.last_signal = reason
                await self._safe_close(reason)
                return

            # 止盈触发
            if tp and price <= tp:
                logger.info(f"💰 止盈触发: 当前价={price:.4f} TP={tp:.4f}")
                self.last_signal = "止盈"
                await self._safe_close("止盈")
                return

            # 锁利激活
            if not self.lockin_on and price <= ep * (1 - self.lockin_trig_pct):
                self.lockin_on = True
                new_sl = round(ep * (1 - self.lockin_prot_pct), 6)
                if new_sl < sl:
                    self.sl_price = new_sl
                    logger.info(f"🔒 锁利激活 盈利={((ep-price)/ep*100):.2f}% → SL={self.sl_price:.4f}")

            # 保本激活
            if not self.be_on and price <= ep * (1 - self.breakeven_pct):
                self.be_on = True
                new_sl = ep
                if new_sl < self.sl_price:
                    self.sl_price = new_sl
                    logger.info(f"🛡️ 保本激活 → SL={self.sl_price:.4f}")

    # ─── 开仓/平仓 ──────────────────────────────────────
    async def _open_short(self):
        if self.position == "SHORT":
            logger.info("⚠️ 已有空头仓位，跳过")
            return
        try:
            price = await self._get_price()
            self.balance_cache = await self._get_balance_float()
            qty = round((self.margin_amount * self.leverage) / price, 4)
            if qty <= 0:
                logger.warning("❌ 仓位计算失败")
                return

            logger.info(f"🚀 开空 {self.symbol}: 价格={price:.4f} 数量={qty:.4f} "
                        f"保证金={self.margin_amount}×{self.leverage}x")
            ok = await self._open_short_order(qty)
            if ok:
                self.position    = "SHORT"
                self.entry_price = price
                self.entry_time  = datetime.now()
                self.sl_price    = round(price * (1 + self.stop_loss_pct), 6)
                self.tp_price    = round(price * (1 - self.take_profit_pct), 6)
                self.lockin_on   = False
                self.be_on       = False
                self.position_size = qty
                logger.info(f"   ✅ 开仓成功  EP={self.entry_price:.4f}  SL={self.sl_price:.4f}  TP={self.tp_price:.4f}")
            else:
                logger.warning("   ❌ 开仓失败（API返回非OK）")
        except Exception as e:
            logger.error(f"开仓异常: {e}")

    async def _safe_close(self, reason: str):
        if self.position != "SHORT" or self._closing:
            return
        self._closing = True
        try:
            await self._close_position(reason)
        finally:
            self._closing = False

    async def _close_position(self, reason: str):
        try:
            price = await self._get_price()
            logger.info(f"🟢 平空 [{reason}]: 当前价={price:.4f} 入场={self.entry_price:.4f}")
            ok = await self._close_short_order()
            if ok:
                if self.entry_price:
                    pnl_pct = (self.entry_price - price) / self.entry_price * 100
                    logger.info(f"   ✅ 平仓成功  盈亏={pnl_pct:+.2f}%  原因={reason}")
                self.position    = None
                self.entry_price = None
                self.entry_time  = None
                self.sl_price    = None
                self.tp_price    = None
                self.lockin_on   = False
                self.be_on       = False
                self.position_size = 0.0
                self.balance_cache = await self._get_balance_float()
            else:
                logger.warning("   ❌ 平仓失败（API返回非OK）")
        except Exception as e:
            logger.error(f"平仓异常: {e}")

    # ─── 持仓同步 ────────────────────────────────────────
    async def _sync_position(self):
        try:
            positions = await self.client.get_positions(self.symbol)
            if positions:
                pos = positions[0]
                side = str(pos.get("side", "")).upper()
                self.position      = "SHORT" if side == "SHORT" else ("LONG" if side == "LONG" else None)
                self.position_size = abs(float(pos.get("size", 0) or 0))
                if self.position and not self.entry_price:
                    # Binance 用 entryPrice，Hyperliquid 用 entry_price
                    ep = float(pos.get("entryPrice") or pos.get("entry_price") or 0)
                    self.entry_price = ep
                    if self.entry_price:
                        self.sl_price = round(self.entry_price * (1 + self.stop_loss_pct), 6)
                        self.tp_price = round(self.entry_price * (1 - self.take_profit_pct), 6)
            else:
                self.position = None
                self.position_size = 0.0
            self.balance_cache = await self._get_balance_float()
            logger.info(f"📌 同步持仓: {self.position or '无持仓'}  余额: {self.balance_cache:.2f}")
        except Exception as e:
            logger.error(f"同步持仓失败: {e}")

    # ─── 状态接口 ────────────────────────────────────────
    def get_status(self) -> Dict[str, Any]:
        pnl_pct = None
        if self.position == "SHORT" and self.entry_price:
            import asyncio as _aio
            try:
                loop = _aio.get_event_loop()
                if loop.is_running():
                    # 在异步环境中无法同步等待，用缓存价格估算
                    pnl_pct = None
            except Exception:
                pass

        return {
            "instance_id":   self.instance_id,
            "symbol":        self.symbol,
            "is_enabled":    self.is_enabled,
            "position":      self.position or "无",
            "position_size": self.position_size,
            "entry_price":   self.entry_price,
            "sl_price":      self.sl_price,
            "tp_price":      self.tp_price,
            "lockin_on":     self.lockin_on,
            "be_on":         self.be_on,
            "balance":       self.balance_cache,
            "last_signal":   self.last_signal,
            "start_time":    self.start_time.strftime("%m-%d %H:%M"),
            "last_debug":    self.last_debug,
        }

    def set_enabled(self, enabled: bool):
        self.is_enabled = enabled
        logger.info(f"策略{'开启' if enabled else '暂停'}: {self.instance_id}")

    def stop(self):
        self._stop = True

