"""
MACD 金叉形态监控：按 Pine「多级别趋势状态看板」逻辑，
在 K 线收线时检测四种 MACD 状态转换并钉钉预警。
"""
import logging
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

from backpack_quant_trading.core.binance_monitor import (
    fetch_binance_klines,
    macd,
    send_dingtalk_alert,
)

logger = logging.getLogger(__name__)

# 页面选项 -> 币安 interval 或 resample 分钟数
MACD_TF_OPTIONS = {
    "60": {"binance": "1h", "label": "1小时(60)"},
    "120": {"binance": "2h", "label": "2小时(120)"},
    "240": {"binance": "4h", "label": "4小时(240)"},
    "640": {"resample_min": 640, "label": "640分钟"},
    "D": {"binance": "1d", "label": "日线(D)"},
}

PATTERN_OPTIONS = {
    "above_golden_to_death": "水上金叉转死叉",
    "below_golden_to_death": "水下金叉转死叉",
    "death_to_below_golden": "死叉转水下金叉",
    "death_to_above_golden": "死叉转水上金叉",
}

ALERT_RED_DURATION_SEC = 600
POLL_INTERVAL_SEC = 90


def _macd_status(m: float, s: float) -> int:
    """1=水上金叉 2=水下金叉 0=死叉/空头"""
    if m > s:
        return 1 if m > 0 else 2
    return 0


def resample_klines_to_minutes(klines: List[Dict], minutes: int) -> List[Dict]:
    """将较小周期 K 线合并为自定义分钟周期（如 640 分钟）。"""
    if not klines or minutes <= 0:
        return []
    bucket_ms = minutes * 60 * 1000
    buckets: Dict[int, Dict] = {}
    for bar in klines:
        ts = int(bar["open_time"])
        key = ts - (ts % bucket_ms)
        if key not in buckets:
            buckets[key] = {
                "open_time": key,
                "open": float(bar["open"]),
                "high": float(bar["high"]),
                "low": float(bar["low"]),
                "close": float(bar["close"]),
                "volume": float(bar.get("volume", 0)),
                "close_time": int(bar.get("close_time", key + bucket_ms - 1)),
            }
        else:
            b = buckets[key]
            b["high"] = max(b["high"], float(bar["high"]))
            b["low"] = min(b["low"], float(bar["low"]))
            b["close"] = float(bar["close"])
            b["volume"] += float(bar.get("volume", 0))
            b["close_time"] = int(bar.get("close_time", b["close_time"]))
    return [buckets[k] for k in sorted(buckets.keys())]


def fetch_klines_for_tf(symbol: str, tf: str, limit: int = 500) -> Optional[List[Dict]]:
    cfg = MACD_TF_OPTIONS.get(tf)
    if not cfg:
        return None
    if "binance" in cfg:
        return fetch_binance_klines(symbol, cfg["binance"], limit=limit)
    resample_min = cfg.get("resample_min")
    if resample_min:
        need = max(limit * resample_min // 60 + 10, 200)
        raw = fetch_binance_klines(symbol, "1h", limit=min(need, 1500))
        if not raw:
            return None
        return resample_klines_to_minutes(raw, resample_min)[-limit:]
    return None


def detect_macd_pattern_on_close(klines: List[Dict], pattern_id: str) -> bool:
    """
    在最新一根已收线 K 线上检测是否出现指定 MACD 形态转换。
    使用 macd[i-1] -> macd[i] 的状态变化，对齐 Pine [1] 防重绘思路。
    """
    if pattern_id not in PATTERN_OPTIONS or not klines or len(klines) < 50:
        return False

    closes = [b["close"] for b in klines]
    macd_line, signal_line = macd(closes, 12, 26, 9)
    i = len(closes) - 2
    if i < 1:
        return False

    prev_m, prev_s = macd_line[i - 1], signal_line[i - 1]
    curr_m, curr_s = macd_line[i], signal_line[i]
    prev_status = _macd_status(prev_m, prev_s)
    curr_status = _macd_status(curr_m, curr_s)
    gold_cross = prev_m <= prev_s and curr_m > curr_s
    death_cross = prev_m >= prev_s and curr_m < curr_s

    if pattern_id == "above_golden_to_death":
        return prev_status == 1 and curr_status == 0 and death_cross
    if pattern_id == "below_golden_to_death":
        return prev_status == 2 and curr_status == 0 and death_cross
    if pattern_id == "death_to_below_golden":
        return prev_status == 0 and curr_status == 2 and gold_cross
    if pattern_id == "death_to_above_golden":
        return prev_status == 0 and curr_status == 1 and gold_cross
    return False


class MacdPatternMonitorService:
    """后台轮询 MACD 形态，K 线收线时触发钉钉。"""

    def __init__(self, tasks: List[Tuple[str, str, str]] = None):
        self._running = False
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._tasks: List[Tuple[str, str, str]] = [
            (str(s).upper(), str(tf), str(p)) for s, tf, p in (tasks or [])
        ]
        self._last_check: Dict[Tuple[str, str, str], int] = {}
        self._alerted: Dict[Tuple[str, str, str], float] = {}

    @property
    def tasks(self) -> List[Tuple[str, str, str]]:
        return list(self._tasks)

    def _run_loop(self):
        while not self._stop_event.is_set():
            try:
                for symbol, tf, pattern in self._tasks:
                    if self._stop_event.is_set():
                        break
                    self._check_task(symbol, tf, pattern)
            except Exception as e:
                logger.error(f"MACD形态监控循环异常: {e}")
            self._stop_event.wait(POLL_INTERVAL_SEC)

    def _check_task(self, symbol: str, tf: str, pattern: str):
        key = (symbol, tf, pattern)
        klines = fetch_klines_for_tf(symbol, tf, limit=500)
        if not klines:
            return
        last_bar = klines[-1]
        close_time = int(last_bar.get("close_time", 0))
        if key not in self._last_check:
            self._last_check[key] = close_time
            return
        if self._last_check.get(key) == close_time:
            return

        triggered = detect_macd_pattern_on_close(klines, pattern)
        self._last_check[key] = close_time
        if not triggered:
            return

        tf_label = MACD_TF_OPTIONS.get(tf, {}).get("label", tf)
        pat_label = PATTERN_OPTIONS.get(pattern, pattern)
        msg = (
            f"【MACD形态监控】\n"
            f"形态: {pat_label}\n"
            f"级别: {tf_label}\n"
            f"收线价: {last_bar['close']:.6f}"
        )
        logger.info(f"MACD形态触发: {symbol} {tf} {pattern}")
        send_dingtalk_alert(symbol, tf_label, msg)
        self._alerted[key] = time.time()

    def remove_task(self, symbol: str, tf: str, pattern: str) -> bool:
        key = (str(symbol).upper(), str(tf), str(pattern))
        before = len(self._tasks)
        self._tasks = [t for t in self._tasks if t != key]
        self._last_check.pop(key, None)
        self._alerted.pop(key, None)
        return len(self._tasks) < before

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info(f"MACD形态监控已启动: {len(self._tasks)} 个任务")

    def stop(self):
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._thread = None
        logger.info("MACD形态监控已停止")

    def get_alerted_tasks(self) -> Set[Tuple[str, str, str]]:
        now = time.time()
        return {k for k, ts in self._alerted.items() if now - ts < ALERT_RED_DURATION_SEC}


_macd_pattern_instance: Optional[MacdPatternMonitorService] = None
_macd_pattern_user_stopped: bool = False


def get_macd_pattern_instance() -> Optional[MacdPatternMonitorService]:
    return _macd_pattern_instance


def set_macd_pattern_instance(instance: Optional[MacdPatternMonitorService]):
    global _macd_pattern_instance
    _macd_pattern_instance = instance


def set_macd_pattern_user_stopped(stopped: bool):
    global _macd_pattern_user_stopped
    _macd_pattern_user_stopped = stopped


def get_macd_pattern_user_stopped() -> bool:
    return _macd_pattern_user_stopped
