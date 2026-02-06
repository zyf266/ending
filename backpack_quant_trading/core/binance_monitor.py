"""
币种监视模块：从币安获取K线数据，运行特别K-倍数判定策略，触发钉钉预警。
不修改任何原有逻辑，仅作为新增功能。
"""
import logging
import threading
import time
import hmac
import hashlib
import base64
import urllib.parse
from datetime import datetime
from typing import List, Dict, Optional, Set, Tuple
ALERT_RED_DURATION_SEC = 600  # 异动变红持续 10 分钟
import requests

from backpack_quant_trading.config.settings import config

logger = logging.getLogger(__name__)

# 币安 REST API
# 【修复】改用合约 API，获取更多币种（包括 1000SHIB、PEPE 等）
BINANCE_API_BASE = "https://fapi.binance.com"  # 合约 API
# BINANCE_API_BASE = "https://api.binance.com"  # 现货 API（已弃用）

# K线级别映射：页面选项 -> 币安 interval
TIMEFRAME_MAP = {
    "1小时": "1h",
    "2小时": "2h",
    "4小时": "4h",
    "天": "1d",
    "周": "1w",
}

# 策略默认参数（与 Pine Script 一致）
DEFAULT_LOOKBACK = 4
DEFAULT_ETH_RATIO = 1.5


def fetch_binance_klines_batch(
    symbol: str,
    interval: str,
    total_limit: int = 1500,
    batch_size: int = 1000,
) -> Optional[List[Dict]]:
    """
    分批次从币安获取 K 线数据（永续合约），单次最多 1000 根，可获取 1000-2000 根。
    symbol: 如 ETHUSDT, BTCUSDT
    interval: 如 15m, 1h, 4h, 1d
    返回: [{"time": ts_ms, "open", "high", "low", "close", "volume"}, ...] 按时间升序
    """
    result: List[Dict] = []
    end_time: Optional[int] = None
    url = f"{BINANCE_API_BASE}/fapi/v1/klines"
    symbol = symbol.upper()
    remaining = total_limit

    while remaining > 0:
        limit = min(remaining, batch_size)
        params: Dict = {"symbol": symbol, "interval": interval, "limit": limit}
        if end_time is not None:
            params["endTime"] = end_time
        try:
            resp = requests.get(url, params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            if not data:
                break
            batch = []
            for bar in data:
                batch.append({
                    "time": int(bar[0]),
                    "open": float(bar[1]),
                    "high": float(bar[2]),
                    "low": float(bar[3]),
                    "close": float(bar[4]),
                    "volume": float(bar[5]),
                })
            result = batch + result  # 更早的数据放前面
            if len(batch) < limit:
                break
            end_time = int(data[0][0]) - 1
            remaining -= len(batch)
            if remaining > 0:
                time.sleep(1.0)  # 分批间隔，避免限流
        except Exception as e:
            logger.error(f"币安 K 线批量获取失败 {symbol} {interval}: {e}")
            return result if result else None
    return result


def fetch_binance_klines(symbol: str, interval: str, limit: int = 500) -> Optional[List[Dict]]:
    """
    从币安获取K线数据（永续合约）。
    symbol: 如 ETHUSDT, BTCUSDT, 1000SHIBUSDT
    interval: 如 2h, 4h, 1d, 1w
    返回: [{"open_time": ts, "open": float, "high": float, "low": float, "close": float, ...}, ...]
    """
    try:
        # 【修复】使用合约 API 的 klines endpoint
        url = f"{BINANCE_API_BASE}/fapi/v1/klines"
        params = {"symbol": symbol.upper(), "interval": interval, "limit": limit}
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        result = []
        for bar in data:
            result.append({
                "open_time": bar[0],
                "open": float(bar[1]),
                "high": float(bar[2]),
                "low": float(bar[3]),
                "close": float(bar[4]),
                "volume": float(bar[5]),
                "close_time": bar[6],
            })
        return result
    except Exception as e:
        logger.error(f"获取币安K线失败 {symbol} {interval}: {e}")
        return None


# 币种列表缓存：避免每次从交易所拉取 exchangeInfo（约 300KB）
_SYMBOLS_CACHE: Optional[List[str]] = None
_SYMBOLS_CACHE_TIME: float = 0
SYMBOLS_CACHE_TTL_SEC = 3600  # 缓存 1 小时，交易所上新不频繁


def fetch_binance_symbols_usdt() -> List[str]:
    """获取币安所有 USDT 永续合约交易对列表（带缓存，默认 1 小时内复用）"""
    global _SYMBOLS_CACHE, _SYMBOLS_CACHE_TIME
    now = time.time()
    if _SYMBOLS_CACHE is not None and (now - _SYMBOLS_CACHE_TIME) < SYMBOLS_CACHE_TTL_SEC:
        return _SYMBOLS_CACHE
    try:
        # 【修复】使用合约 API 的 exchangeInfo endpoint
        url = f"{BINANCE_API_BASE}/fapi/v1/exchangeInfo"
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        symbols = []
        for s in data.get("symbols", []):
            # 合约市场：筛选 USDT 永续合约 (contractType=PERPETUAL)
            if s.get("quoteAsset") == "USDT" and s.get("status") == "TRADING" and s.get("contractType") == "PERPETUAL":
                symbols.append(s["symbol"])
        result = sorted(symbols)
        _SYMBOLS_CACHE = result
        _SYMBOLS_CACHE_TIME = now
        logger.info(f"币种列表已缓存，共 {len(result)} 个 USDT 永续合约")
        return result
    except Exception as e:
        logger.error(f"获取币安交易对失败: {e}")
        if _SYMBOLS_CACHE is not None:
            return _SYMBOLS_CACHE
        # 兜底：返回常用合约交易对
        return ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "1000SHIBUSDT", "1000PEPEUSDT", "DOGEUSDT"]


def macd(close_prices: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[List[float], List[float]]:
    """计算 MACD 线 和 信号线"""
    import numpy as np
    closes = np.array(close_prices, dtype=float)
    ema_fast = np.zeros_like(closes)
    ema_slow = np.zeros_like(closes)
    ema_fast[0] = closes[0]
    ema_slow[0] = closes[0]
    k_fast = 2 / (fast + 1)
    k_slow = 2 / (slow + 1)
    for i in range(1, len(closes)):
        ema_fast[i] = closes[i] * k_fast + ema_fast[i - 1] * (1 - k_fast)
        ema_slow[i] = closes[i] * k_slow + ema_slow[i - 1] * (1 - k_slow)
    macd_line = ema_fast - ema_slow
    signal_line = np.zeros_like(macd_line)
    signal_line[0] = macd_line[0]
    k_sig = 2 / (signal + 1)
    for i in range(1, len(macd_line)):
        signal_line[i] = macd_line[i] * k_sig + signal_line[i - 1] * (1 - k_sig)
    return macd_line.tolist(), signal_line.tolist()


def run_special_k_strategy(
    symbol_klines: List[Dict],
    eth_klines: List[Dict],
    lookback_bars: int = DEFAULT_LOOKBACK,
    eth_ratio: float = DEFAULT_ETH_RATIO,
) -> bool:
    """
    运行特别K-倍数判定策略（Pine Script 逻辑）。
    返回 True 表示在最新一根K线收线时触发异动信号。
    """
    if not symbol_klines or not eth_klines or len(symbol_klines) < 50 or len(eth_klines) < 50:
        return False

    closes = [b["close"] for b in symbol_klines]
    opens = [b["open"] for b in symbol_klines]
    eth_closes = [b["close"] for b in eth_klines]

    macd_line, signal_line = macd(closes, 12, 26, 9)

    is_monitoring = False
    bull_count = 0
    start_price = 0.0
    eth_start_price = 0.0
    last_trigger_bar = -1

    for i in range(1, len(closes)):
        # 金叉
        gold_cross = macd_line[i - 1] <= signal_line[i - 1] and macd_line[i] > signal_line[i]
        # 死叉
        death_cross = macd_line[i - 1] >= signal_line[i - 1] and macd_line[i] < signal_line[i]

        if gold_cross:
            is_monitoring = True
            bull_count = 0
            start_price = opens[i] if i < len(opens) else opens[-1]
            eth_start_price = eth_closes[i] if i < len(eth_closes) else eth_closes[-1]

        if death_cross:
            is_monitoring = False
            bull_count = 0

        if is_monitoring:
            if closes[i] > opens[i]:
                bull_count += 1
            else:
                bull_count = 0
                start_price = opens[i] if i < len(opens) else opens[-1]
                eth_start_price = eth_closes[i] if i < len(eth_closes) else eth_closes[-1]

        # 计算涨幅
        current_change = ((closes[i] - start_price) / start_price) * 100 if start_price else 0
        eth_change = ((eth_closes[i] - eth_start_price) / eth_start_price) * 100 if eth_start_price else 0

        ratio_check = False
        if eth_change > 0:
            if current_change >= (eth_change * eth_ratio):
                ratio_check = True
        elif current_change > 0:
            ratio_check = True

        trigger = is_monitoring and bull_count == lookback_bars and ratio_check
        if trigger:
            last_trigger_bar = i

    # 仅当最新一根K线触发时才返回 True（避免历史异动重复推送）
    return last_trigger_bar == len(closes) - 1 if last_trigger_bar >= 0 else False


def send_dingtalk_alert(symbol: str, timeframe: str, message: str = "") -> bool:
    """发送钉钉异动预警"""
    token = config.webhook.DINGTALK_TOKEN
    secret = config.webhook.DINGTALK_SECRET
    if not token:
        logger.warning("钉钉预警跳过：未配置 DINGTALK_TOKEN")
        return False

    try:
        url = f"https://oapi.dingtalk.com/robot/send?access_token={token}"
        if secret:
            timestamp = str(round(datetime.now().timestamp() * 1000))
            string_to_sign = f"{timestamp}\n{secret}"
            hmac_code = hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
            sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
            url += f"&timestamp={timestamp}&sign={sign}"

        content = f"\n{symbol} {timeframe} 异动\n时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n{message}"
        data = {"msgtype": "text", "text": {"content": content}}

        resp = requests.post(url, json=data, timeout=5)
        if resp.status_code == 200:
            logger.info(f"钉钉预警已发送: {symbol} {timeframe}")
            return True
        logger.error(f"钉钉预警发送失败: {resp.text}")
        return False
    except Exception as e:
        logger.error(f"钉钉预警异常: {e}")
        return False


class BinanceMonitorService:
    """
    币种监视服务：后台轮询K线收线，运行策略，触发钉钉。
    通过 start/stop 控制，不阻塞主线程。
    """

    def __init__(
        self,
        symbols: List[str] = None,
        timeframes: List[str] = None,
        pairs: List[Tuple[str, str]] = None,
        lookback_bars: int = DEFAULT_LOOKBACK,
        eth_ratio: float = DEFAULT_ETH_RATIO,
        user_id: Optional[int] = None,
    ):
        self.user_id = user_id  # 启动者用户ID，用于账户隔离
        self.lookback_bars = lookback_bars
        self.eth_ratio = eth_ratio
        self._running = False
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._alerted: Dict[Tuple[str, str], float] = {}  # (symbol, timeframe) -> 触发时间戳，用于 10 分钟变红
        self._last_check: Dict[Tuple[str, str], int] = {}  # 上次检查的 K 线 close_time
        
        # 核心修复：优先使用显式配对，否则才进行组合（兼容旧调用）
        if pairs is not None:
            self._pairs = [(str(s).upper(), str(t)) for (s, t) in pairs]
        else:
            self._pairs: List[Tuple[str, str]] = [
                (s.upper(), t) for s in (symbols or []) for t in (timeframes or [])
            ]

    @property
    def symbols(self) -> List[str]:
        seen = set()
        out = []
        for s, _ in self._pairs:
            if s not in seen:
                seen.add(s)
                out.append(s)
        return out

    @property
    def timeframes(self) -> List[str]:
        seen = set()
        out = []
        for _, t in self._pairs:
            if t not in seen:
                seen.add(t)
                out.append(t)
        return out

    def _interval_to_binance(self, tf: str) -> str:
        return TIMEFRAME_MAP.get(tf, tf)

    def _run_loop(self):
        while not self._stop_event.is_set():
            try:
                for symbol, tf in self._pairs:
                    if self._stop_event.is_set():
                        break
                    interval = self._interval_to_binance(tf)
                    self._check_symbol_timeframe(symbol, tf, interval)
            except Exception as e:
                logger.error(f"币种监视循环异常: {e}")
            self._stop_event.wait(60)  # 可被立即中断的睡眠

    def _check_symbol_timeframe(self, symbol: str, tf: str, interval: str):
        key = (symbol, tf)
        symbol_klines = fetch_binance_klines(symbol, interval, limit=500)
        eth_klines = fetch_binance_klines("ETHUSDT", interval, limit=500)
        if not symbol_klines or not eth_klines:
            return

        last_bar = symbol_klines[-1]
        close_time = last_bar["close_time"]
        if self._last_check.get(key) == close_time:
            return
        self._last_check[key] = close_time

        triggered = run_special_k_strategy(
            symbol_klines, eth_klines,
            lookback_bars=self.lookback_bars,
            eth_ratio=self.eth_ratio,
        )
        if triggered:
            if key not in self._alerted or (time.time() - self._alerted[key]) > ALERT_RED_DURATION_SEC:
                send_dingtalk_alert(symbol, tf, "品种涨幅强于ETH且满足连阳")
            self._alerted[key] = time.time()  # 记录触发时间，变红持续 10 分钟

    def remove_pair(self, symbol: str, timeframe: str) -> bool:
        """移除单个监视对，返回是否成功移除"""
        key = (str(symbol).upper(), str(timeframe))
        before = len(self._pairs)
        self._pairs = [(s, t) for (s, t) in self._pairs if (s, t) != key]
        self._last_check.pop(key, None)
        self._alerted.pop(key, None)
        return len(self._pairs) < before

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info(f"币种监视已启动: {self.symbols}, {self.timeframes}")

    def stop(self):
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._thread = None
        logger.info("币种监视已停止")

    def get_alerted_pairs(self) -> Set[Tuple[str, str]]:
        """返回 10 分钟内触发异动的 (symbol, timeframe)，供前端显示红色"""
        now = time.time()
        return {(s, t) for (s, t), ts in self._alerted.items() if now - ts < ALERT_RED_DURATION_SEC}

    def add_alerted_for_test(self, symbols: List[str], timeframes: List[str]):
        """模拟测试：将选中币种/级别加入异动，用于页面变红测试"""
        now = time.time()
        for s in (symbols or []):
            for t in (timeframes or []):
                self._alerted[(str(s).upper(), str(t))] = now

    def clear_alerted(self, symbol: str = None, timeframe: str = None):
        """清除已触发记录，可指定 symbol/timeframe 或全部"""
        if symbol and timeframe:
            self._alerted.pop((symbol.upper(), timeframe), None)
        else:
            self._alerted.clear()


# 币种监视全局共享，不按用户隔离
_monitor_instance: Optional[BinanceMonitorService] = None


def get_monitor_instance() -> Optional[BinanceMonitorService]:
    return _monitor_instance


def set_monitor_instance(instance: Optional[BinanceMonitorService]):
    global _monitor_instance
    _monitor_instance = instance
