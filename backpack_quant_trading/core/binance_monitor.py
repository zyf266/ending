"""
币种监视模块：从币安获取K线数据，运行特别K-倍数判定策略，触发钉钉预警。
不修改任何原有逻辑，仅作为新增功能。
"""
import json
import logging
import threading
import time
import hmac
import hashlib
import base64
import urllib.parse
import asyncio
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Set, Tuple, Any
ALERT_RED_DURATION_SEC = 600  # 异动变红持续 10 分钟
import requests
import math
import os
import aiohttp
import subprocess

from backpack_quant_trading.config.settings import config

logger = logging.getLogger(__name__)

# 分钟预警专用钉钉 Webhook（仅 1 分钟预警使用，不影响其他告警逻辑）
MINUTE_ALERT_WEBHOOK = "https://oapi.dingtalk.com/robot/send?access_token=3bedccd203d2ed11882431c3250ed31af4090591fdb6a87aaf04f8953fdbc1dc"

# 币安 REST API
# 【修复】改用合约 API，获取更多币种（包括 1000SHIB、PEPE 等）
BINANCE_API_BASE = "https://fapi.binance.com"  # 合约 API
BINANCE_SPOT_API_BASE = "https://api.binance.com"  # 现货 API
# BINANCE_API_BASE = "https://api.binance.com"  # 现货 API（已弃用）


def _binance_api_base(market: str = "futures") -> str:
    return BINANCE_SPOT_API_BASE if (market or "futures").lower() == "spot" else BINANCE_API_BASE


def _klines_path(market: str = "futures") -> str:
    return "/api/v3/klines" if (market or "futures").lower() == "spot" else "/fapi/v1/klines"


def _depth_path(market: str = "futures") -> str:
    return "/api/v3/depth" if (market or "futures").lower() == "spot" else "/fapi/v1/depth"


def _requests_proxies() -> Optional[Dict[str, str]]:
    """显式给 requests 注入代理，避免某些运行方式下环境变量不生效。"""
    https = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    http = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy") or https
    allp = os.environ.get("ALL_PROXY") or os.environ.get("all_proxy")
    # 兜底：只配置了 ALL_PROXY 的情况（常见于 socks5）
    if not (http or https) and allp:
        http = allp
        https = allp
    if not (http or https):
        return None
    p: Dict[str, str] = {}
    if http:
        p["http"] = http
    if https:
        p["https"] = https
    return p or None


def _http_get_json_sync(url: str, params: Dict, timeout_sec: int) -> object:
    """
    用 aiohttp 拉取 JSON（支持 proxy + ssl=False），避免 requests 在部分机房/代理链路下出现 SSLEOFError。
    这是同步包装：运行在 FastAPI 的线程池线程内（无 event loop）是安全的。
    """
    # aiohttp 的 proxy 仅支持 http(s) 代理；这里优先使用 HTTP(S)_PROXY（你本机 mihomo mixed-port 即 http 代理）
    proxy = (
        os.environ.get("HTTPS_PROXY")
        or os.environ.get("https_proxy")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("http_proxy")
        or None
    )
    # 兜底：若仅设置了 ALL_PROXY（且是 http 代理），也尝试使用
    if not proxy:
        ap = os.environ.get("ALL_PROXY") or os.environ.get("all_proxy") or ""
        if ap.startswith("http://") or ap.startswith("https://"):
            proxy = ap

    def _curl_get_json_sync() -> object:
        """
        兜底方案：直接调用系统 curl（支持 -x 代理），再 json 解析。
        你已验证 curl -x 127.0.0.1:7891 可以稳定访问币安，这条路最抗网络栈/SSL 异常。
        """
        proxy = (
            os.environ.get("HTTPS_PROXY")
            or os.environ.get("https_proxy")
            or os.environ.get("HTTP_PROXY")
            or os.environ.get("http_proxy")
            or ""
        )
        # 拼接 query
        from urllib.parse import urlencode
        full_url = url
        if params:
            full_url = f"{url}?{urlencode(params)}"
        cmd = [
            "curl",
            "-fsSL",
            "--max-time",
            str(timeout_sec),
            "-A",
            "Mozilla/5.0",
        ]
        if proxy:
            cmd += ["-x", proxy]
        cmd.append(full_url)
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        import json as _json
        return _json.loads(out.decode("utf-8", errors="ignore"))

    async def _run_aiohttp():
        t = aiohttp.ClientTimeout(total=timeout_sec)
        async with aiohttp.ClientSession(timeout=t) as session:
            async with session.get(
                url,
                params=params,
                proxy=proxy,
                ssl=False,
                headers={"User-Agent": "Mozilla/5.0"},
            ) as resp:
                resp.raise_for_status()
                return await resp.json(content_type=None)

    try:
        # 你的环境里 curl -x 代理是最稳定的；只要配置了 proxy，就优先走 curl，避免 requests/urllib3 的 SSLEOF
        if proxy:
            return _curl_get_json_sync()
        return asyncio.run(_run_aiohttp())
    except Exception:
        # 兜底顺序：curl → aiohttp → requests，并把错误尽量保留在日志里
        try:
            return _curl_get_json_sync()
        except Exception as e1:
            logger.warning(f"币安行情 curl 兜底失败: {e1}")
        try:
            return asyncio.run(_run_aiohttp())
        except Exception as e2:
            logger.warning(f"币安行情 aiohttp 兜底失败: {e2}")
        resp = requests.get(
            url,
            params=params,
            timeout=timeout_sec,
            proxies=_requests_proxies(),
            verify=False,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp.raise_for_status()
        return resp.json()

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

# K 线 interval 对应的毫秒数（用于分批拉取时计算下一批 startTime）
INTERVAL_MS = {
    "1m": 60 * 1000,
    "3m": 3 * 60 * 1000,
    "5m": 5 * 60 * 1000,
    "15m": 15 * 60 * 1000,
    "30m": 30 * 60 * 1000,
    "1h": 3600 * 1000,
    "2h": 2 * 3600 * 1000,
    "4h": 4 * 3600 * 1000,
    "1d": 24 * 3600 * 1000,
    "1w": 7 * 24 * 3600 * 1000,
}


def fetch_binance_klines_from_start(
    symbol: str,
    interval: str,
    start_time_ms: int,
    end_time_ms: Optional[int] = None,
    batch_size: int = 1000,
) -> List[Dict]:
    """
    从指定起始时间分批次从币安拉取 K 线直到 end_time_ms（不传则拉到当前时间）。
    返回: [{"time": ts_ms, "open", "high", "low", "close", "volume"}, ...] 按时间升序
    """
    result: List[Dict] = []
    url = f"{BINANCE_API_BASE}/fapi/v1/klines"
    symbol = symbol.upper()
    interval_ms = INTERVAL_MS.get(interval.lower(), 2 * 3600 * 1000)  # 默认 2h
    current_start = start_time_ms
    end_ts = end_time_ms or (int(time.time()) * 1000)

    while current_start < end_ts:
        params: Dict = {
            "symbol": symbol,
            "interval": interval,
            "limit": batch_size,
            "startTime": current_start,
        }
        try:
            data = _http_get_json_sync(url, params=params, timeout_sec=30)
            if not data:
                break
            if not isinstance(data, list):
                logger.error(f"币安 K 线返回异常（非数组） {symbol} {interval}: {data}")
                break
            batch = []
            for bar in data:
                t = int(bar[0])
                if t >= end_ts:
                    break
                batch.append({
                    "time": t,
                    "open": float(bar[1]),
                    "high": float(bar[2]),
                    "low": float(bar[3]),
                    "close": float(bar[4]),
                    "volume": float(bar[5]),
                })
            result.extend(batch)
            if len(batch) < batch_size:
                break
            # 下一批从本批最后一根 K 线的下一根开始
            current_start = int(data[-1][0]) + interval_ms
            time.sleep(0.5)  # 限流
        except Exception as e:
            logger.error(f"币安 K 线从起点拉取失败 {symbol} {interval}: {e}")
            break
    return result


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
            data = _http_get_json_sync(url, params=params, timeout_sec=20)
            if not data:
                break
            if not isinstance(data, list):
                logger.error(f"币安 K 线返回异常（非数组） {symbol} {interval}: {data}")
                return result if result else None
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


def fetch_binance_klines(
    symbol: str,
    interval: str,
    limit: int = 500,
    *,
    market: str = "futures",
) -> Optional[List[Dict]]:
    """
    从币安获取K线数据（永续合约或现货）。
    symbol: 如 ETHUSDT, BTCUSDT, 1000SHIBUSDT
    interval: 如 2h, 4h, 1d, 1w
    market: futures | spot
    返回: [{"open_time": ts, "open": float, "high": float, "low": float, "close": float, ...}, ...]
    """
    try:
        base = _binance_api_base(market)
        url = f"{base}{_klines_path(market)}"
        params = {"symbol": symbol.upper(), "interval": interval, "limit": limit}
        data = _http_get_json_sync(url, params=params, timeout_sec=15)
        if not isinstance(data, list):
            logger.error(f"获取币安K线返回异常（非数组） {market} {symbol} {interval}: {data}")
            return None
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
        logger.error(f"获取币安K线失败 {market} {symbol} {interval}: {e}")
        return None


def fetch_binance_depth(
    symbol: str,
    limit: int = 50,
    *,
    market: str = "futures",
) -> Optional[Dict]:
    """获取币安订单簿深度（合约或现货）。"""
    try:
        base = _binance_api_base(market)
        url = f"{base}{_depth_path(market)}"
        params = {"symbol": symbol.upper(), "limit": int(limit)}
        data = _http_get_json_sync(url, params=params, timeout_sec=10)
        if not isinstance(data, dict):
            return None
        return data
    except Exception as e:
        logger.error(f"获取币安深度失败 {market} {symbol}: {e}")
        return None


def _parse_depth_levels(levels) -> List[Tuple[float, float]]:
    out: List[Tuple[float, float]] = []
    if not isinstance(levels, list):
        return out
    for lv in levels:
        try:
            px = float(lv[0])
            qty = float(lv[1])
            out.append((px, qty))
        except Exception:
            continue
    return out


def detect_minute_alerts(
    symbol: str,
    klines: List[Dict],
    depth: Optional[Dict],
    *,
    interval_label: str = "1m",
    vol_pct_threshold: float = 5.0,
    volume_mult_threshold: float = 20.0,
    ob_notional_threshold: float = 200000.0,
    ob_distance_pct: float = 0.003,
    depth_levels: int = 50,
) -> List[Dict]:
    """检测短周期预警条件，返回触发原因列表（可多条）。

    条件：
    - 一根K线内波动 >= vol_pct_threshold（%）
    - 当前成交量 >= 上一根成交量 * volume_mult_threshold
    - 订单簿出现大额买墙/卖墙（名义价值 >= ob_notional_threshold）
    """
    reasons: List[Dict] = []
    if not klines or len(klines) < 2:
        return reasons

    cur = klines[-1]
    prev = klines[-2]
    o = float(cur.get("open") or 0)
    h = float(cur.get("high") or 0)
    l = float(cur.get("low") or 0)
    v = float(cur.get("volume") or 0)
    pv = float(prev.get("volume") or 0)

    # 波动（用 high-low / open）
    if o > 0 and h > 0 and l > 0:
        rng_pct = (h - l) / o * 100
        if rng_pct >= vol_pct_threshold:
            reasons.append({
                "key": "VOLATILITY",
                "text": f"原因：{interval_label}波动率 {rng_pct:.2f}% ≥ {vol_pct_threshold:.2f}%",
            })

    # 成交量倍数
    if pv > 0:
        mult = v / pv
        if mult >= volume_mult_threshold:
            reasons.append({
                "key": "VOLUME_MULT",
                "text": f"原因：{interval_label}成交量 {v:.4g} 是前一根 {pv:.4g} 的 {mult:.1f}x ≥ {volume_mult_threshold:.1f}x",
            })

    # 订单簿大额挂单（买墙/卖墙）：只看“距离盘口很近”的墙（按 ob_distance_pct）。
    # 按用户要求：这是偶发情况，不做冷却，检测到就推送。
    if depth and isinstance(depth, dict):
        bids = _parse_depth_levels(depth.get("bids"))
        asks = _parse_depth_levels(depth.get("asks"))
        if bids and asks:
            best_bid = bids[0][0]
            best_ask = asks[0][0]
            if best_bid > 0 and best_ask > 0:
                mid = (best_bid + best_ask) / 2
                max_dist = mid * float(ob_distance_pct)

                wall_hits: List[str] = []
                # 扫描前 N 档（仅近盘口范围）
                for side_name, arr in (("买墙(BID)", bids[:depth_levels]), ("卖墙(ASK)", asks[:depth_levels])):
                    for idx, (px, qty) in enumerate(arr, start=1):
                        if px <= 0 or qty <= 0:
                            continue
                        if abs(px - mid) > max_dist:
                            continue
                        notional = px * qty
                        if notional >= ob_notional_threshold:
                            wall_hits.append(
                                f"{side_name} 第{idx}档 @ {px:.2f} qty={qty:.4g} 名义={notional:,.0f}USDT ≥ {ob_notional_threshold:,.0f}"
                            )
                            break
                if wall_hits:
                    reasons.append({
                        "key": "ORDERBOOK_WALL",
                        "text": (
                            f"原因：订单簿大单（距离盘口≤{float(ob_distance_pct)*100:.2f}%）"
                            + "（" + " ｜ ".join(wall_hits) + "）"
                        ),
                    })

    return reasons


class BinanceMinuteAlertService:
    """短周期预警服务：每分钟从币安获取K线、成交量、订单簿，触发钉钉告警。"""

    def __init__(
        self,
        symbols: List[str],
        *,
        interval: str = "1m",
        vol_pct_threshold: float = 5.0,
        volume_mult_threshold: float = 20.0,
        ob_notional_threshold: float = 200000.0,
        ob_distance_pct: float = 0.003,
        depth_levels: int = 50,
        cooldown_sec: int = 300,
        market: str = "futures",
    ):
        self.symbols = [str(s).upper() for s in (symbols or []) if str(s).strip()]
        self.interval = (interval or "1m").strip()
        self.market = (market or "futures").lower()
        self.vol_pct_threshold = float(vol_pct_threshold)
        self.volume_mult_threshold = float(volume_mult_threshold)
        self.ob_notional_threshold = float(ob_notional_threshold)
        self.ob_distance_pct = float(ob_distance_pct)
        self.depth_levels = int(depth_levels)
        self.cooldown_sec = int(cooldown_sec)

        self._running = False
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # (symbol, reason_key) -> ts
        self._last_alert_ts: Dict[Tuple[str, str], float] = {}
        # symbol -> last close_time（避免 interval>1m 时重复检测）
        self._last_bar_close_time: Dict[str, int] = {}

    def _cooldown_ok(self, symbol: str, key: str) -> bool:
        now = time.time()
        last = self._last_alert_ts.get((symbol, key), 0)
        if now - last >= self.cooldown_sec:
            self._last_alert_ts[(symbol, key)] = now
            return True
        return False

    def _run_loop(self):
        # 尽量对齐分钟边界
        while not self._stop_event.is_set():
            try:
                for sym in self.symbols:
                    if self._stop_event.is_set():
                        break
                    kl = fetch_binance_klines(sym, self.interval, limit=2, market=self.market)
                    if kl and len(kl) >= 1:
                        ct = int(kl[-1].get("close_time") or 0)
                        if ct and self._last_bar_close_time.get(sym) == ct:
                            continue
                        if ct:
                            self._last_bar_close_time[sym] = ct
                    depth = fetch_binance_depth(sym, limit=max(5, self.depth_levels), market=self.market)
                    reasons = detect_minute_alerts(
                        sym,
                        kl or [],
                        depth,
                        interval_label=self.interval,
                        vol_pct_threshold=self.vol_pct_threshold,
                        volume_mult_threshold=self.volume_mult_threshold,
                        ob_notional_threshold=self.ob_notional_threshold,
                        ob_distance_pct=self.ob_distance_pct,
                        depth_levels=self.depth_levels,
                    )
                    if not reasons:
                        continue
                    # 分原因冷却，避免刷屏
                    msg_lines = []
                    for r in reasons:
                        key = str(r.get("key") or "")
                        text = str(r.get("text") or "")
                        if not text:
                            continue
                        # 订单簿大单：按需求不走冷却（偶发，看到就推）
                        if key == "ORDERBOOK_WALL":
                            msg_lines.append(text)
                            continue
                        if self._cooldown_ok(sym, key):
                            msg_lines.append(text)
                    if msg_lines:
                        label = "现货" if self.market == "spot" else "合约"
                        send_dingtalk_alert_for_minute(
                            sym,
                            f"{label}{self.interval}预警",
                            "\n".join(msg_lines),
                        )
            except Exception as e:
                logger.error(f"1分钟预警循环异常: {e}")

            # 睡到下一分钟（可中断）
            now = time.time()
            sleep_s = 60 - (now % 60)
            if sleep_s < 1:
                sleep_s = 1
            self._stop_event.wait(sleep_s)

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info(f"✅ {self.market}分钟预警已启动: {self.symbols}")

    def stop(self):
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._thread = None
        logger.info(f"🛑 {self.market}分钟预警已停止")


_minute_alert_instance: Optional[BinanceMinuteAlertService] = None
_spot_minute_alert_instance: Optional[BinanceMinuteAlertService] = None


def get_minute_alert_instance() -> Optional[BinanceMinuteAlertService]:
    return _minute_alert_instance


def set_minute_alert_instance(instance: Optional[BinanceMinuteAlertService]):
    global _minute_alert_instance
    _minute_alert_instance = instance


def get_spot_minute_alert_instance() -> Optional[BinanceMinuteAlertService]:
    return _spot_minute_alert_instance


def set_spot_minute_alert_instance(instance: Optional[BinanceMinuteAlertService]):
    global _spot_minute_alert_instance
    _spot_minute_alert_instance = instance


def probe_spot_minute_alert(
    symbol: str,
    *,
    interval: str = "1m",
    vol_pct_threshold: float = 5.0,
    volume_mult_threshold: float = 20.0,
    ob_notional_threshold: float = 200000.0,
) -> Dict[str, Any]:
    """单次探测现货分钟预警数据源（不触发钉钉）。"""
    sym = str(symbol or "BTCUSDT").upper().strip()
    kl = fetch_binance_klines(sym, interval, limit=2, market="spot")
    depth = fetch_binance_depth(sym, limit=50, market="spot")
    proxy = (
        os.environ.get("HTTPS_PROXY")
        or os.environ.get("https_proxy")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("http_proxy")
        or ""
    )
    out: Dict[str, Any] = {
        "ok": kl is not None and len(kl or []) >= 1,
        "symbol": sym,
        "market": "spot",
        "interval": interval,
        "proxy_configured": bool(proxy),
        "proxy": proxy or None,
        "klines_ok": kl is not None and len(kl or []) >= 1,
        "klines_count": len(kl or []),
        "depth_ok": depth is not None,
        "latest_bar": None,
        "would_alert": [],
    }
    if not out["klines_ok"]:
        out["error"] = "无法拉取现货 K 线"
        out["hint"] = (
            "若环境变量设置了 HTTP_PROXY/HTTPS_PROXY 但本地代理未启动，会连接失败；"
            "请启动代理或临时 unset 代理后重试"
        )
        return out
    bar = kl[-1]
    out["latest_bar"] = {
        "open": bar.get("open"),
        "high": bar.get("high"),
        "low": bar.get("low"),
        "close": bar.get("close"),
        "volume": bar.get("volume"),
        "close_time": bar.get("close_time"),
    }
    reasons = detect_minute_alerts(
        sym,
        kl,
        depth,
        interval_label=interval,
        vol_pct_threshold=vol_pct_threshold,
        volume_mult_threshold=volume_mult_threshold,
        ob_notional_threshold=ob_notional_threshold,
    )
    out["would_alert"] = [r.get("text") for r in reasons if r.get("text")]
    out["message"] = (
        f"现货数据正常；当前 K 线未触发预警"
        if not out["would_alert"]
        else f"若在生产环境会触发 {len(out['would_alert'])} 条预警"
    )
    return out


def send_spot_minute_test_dingtalk(symbol: str = "BTCUSDT") -> Tuple[bool, str]:
    ok = send_dingtalk_alert_for_minute(
        symbol.upper(),
        "现货连通性测试",
        "这是一条现货分钟预警的测试消息。若收到说明钉钉 Webhook 配置正常。",
    )
    return ok, "已发送测试消息" if ok else "发送失败，请检查分钟预警 Webhook"


# 币种列表缓存：避免每次从交易所拉取 exchangeInfo（约 300KB）
_SYMBOLS_CACHE: Optional[List[str]] = None
_SYMBOLS_CACHE_TIME: float = 0
SYMBOLS_CACHE_TTL_SEC = 24 * 3600  # 缓存 24 小时，交易所上新不频繁
_SYMBOLS_CACHE_FILE = Path(__file__).resolve().parent.parent / "data" / "symbols_cache.json"
_SPOT_SYMBOLS_CACHE_FILE = Path(__file__).resolve().parent.parent / "data" / "symbols_spot_cache.json"
_SPOT_SYMBOLS_CACHE: Optional[List[str]] = None
_SPOT_SYMBOLS_CACHE_TIME: float = 0


def _load_symbols_from_file() -> Optional[List[str]]:
    """从本地文件加载币种列表（含时间戳，用于 TTL 判断）"""
    global _SYMBOLS_CACHE, _SYMBOLS_CACHE_TIME
    if not _SYMBOLS_CACHE_FILE.exists():
        return None
    try:
        raw = _SYMBOLS_CACHE_FILE.read_text(encoding="utf-8")
        data = json.loads(raw)
        symbols = data.get("symbols")
        updated_at = data.get("updated_at", 0)
        if isinstance(symbols, list) and len(symbols) > 0:
            _SYMBOLS_CACHE = symbols
            _SYMBOLS_CACHE_TIME = float(updated_at)
            logger.info(f"币种列表从文件加载，共 {len(symbols)} 个，更新于 {updated_at}")
            return symbols
    except Exception as e:
        logger.debug(f"读取币种缓存文件失败: {e}")
    return None


def _save_symbols_to_file(symbols: List[str]) -> None:
    """将币种列表写入本地文件"""
    try:
        _SYMBOLS_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {"symbols": symbols, "updated_at": time.time()}
        _SYMBOLS_CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")
    except Exception as e:
        logger.debug(f"写入币种缓存文件失败: {e}")


def fetch_binance_symbols_usdt() -> List[str]:
    """获取币安所有 USDT 永续合约交易对列表（内存+文件缓存，24 小时更新一次）"""
    global _SYMBOLS_CACHE, _SYMBOLS_CACHE_TIME
    now = time.time()
    if _SYMBOLS_CACHE is not None and (now - _SYMBOLS_CACHE_TIME) < SYMBOLS_CACHE_TTL_SEC:
        return _SYMBOLS_CACHE
    # 内存未命中时先尝试从文件恢复（重启后或首次调用可避免立即请求 API）
    if _SYMBOLS_CACHE is None:
        _load_symbols_from_file()
        if _SYMBOLS_CACHE is not None and (now - _SYMBOLS_CACHE_TIME) < SYMBOLS_CACHE_TTL_SEC:
            return _SYMBOLS_CACHE
    try:
        url = f"{BINANCE_API_BASE}/fapi/v1/exchangeInfo"
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        symbols = []
        for s in data.get("symbols", []):
            if s.get("quoteAsset") == "USDT" and s.get("status") == "TRADING" and s.get("contractType") == "PERPETUAL":
                symbols.append(s["symbol"])
        result = sorted(symbols)
        _SYMBOLS_CACHE = result
        _SYMBOLS_CACHE_TIME = now
        _save_symbols_to_file(result)
        logger.info(f"币种列表已缓存，共 {len(result)} 个 USDT 永续合约")
        return result
    except Exception as e:
        logger.error(f"获取币安交易对失败: {e}")
        if _SYMBOLS_CACHE is not None:
            return _SYMBOLS_CACHE
        loaded = _load_symbols_from_file()
        if loaded is not None:
            return loaded
        return ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "1000SHIBUSDT", "1000PEPEUSDT", "DOGEUSDT"]


def fetch_binance_spot_symbols_usdt() -> List[str]:
    """获取币安现货 USDT 交易对列表。"""
    global _SPOT_SYMBOLS_CACHE, _SPOT_SYMBOLS_CACHE_TIME
    now = time.time()
    if _SPOT_SYMBOLS_CACHE is not None and (now - _SPOT_SYMBOLS_CACHE_TIME) < SYMBOLS_CACHE_TTL_SEC:
        return _SPOT_SYMBOLS_CACHE
    if _SPOT_SYMBOLS_CACHE_FILE.exists():
        try:
            data = json.loads(_SPOT_SYMBOLS_CACHE_FILE.read_text(encoding="utf-8"))
            symbols = data.get("symbols")
            updated_at = float(data.get("updated_at", 0))
            if isinstance(symbols, list) and symbols and (now - updated_at) < SYMBOLS_CACHE_TTL_SEC:
                _SPOT_SYMBOLS_CACHE = symbols
                _SPOT_SYMBOLS_CACHE_TIME = updated_at
                return symbols
        except Exception:
            pass
    try:
        url = f"{BINANCE_SPOT_API_BASE}/api/v3/exchangeInfo"
        data = _http_get_json_sync(url, params={}, timeout_sec=20)
        symbols = []
        for s in (data or {}).get("symbols", []):
            if s.get("quoteAsset") == "USDT" and s.get("status") == "TRADING":
                symbols.append(s["symbol"])
        result = sorted(symbols)
        _SPOT_SYMBOLS_CACHE = result
        _SPOT_SYMBOLS_CACHE_TIME = now
        try:
            _SPOT_SYMBOLS_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            _SPOT_SYMBOLS_CACHE_FILE.write_text(
                json.dumps({"symbols": result, "updated_at": now}, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass
        logger.info(f"现货币种列表已缓存，共 {len(result)} 个")
        return result
    except Exception as e:
        logger.error(f"获取币安现货交易对失败: {e}")
        if _SPOT_SYMBOLS_CACHE:
            return _SPOT_SYMBOLS_CACHE
        return ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "LINKUSDT"]


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
    """发送钉钉异动预警（币种监视、MACD形态监控等共用 DINGTALK_TOKEN）"""
    token = config.webhook.DINGTALK_TOKEN
    secret = config.webhook.DINGTALK_SECRET
    if not token:
        logger.warning("钉钉预警跳过：未配置 DINGTALK_TOKEN")
        return False

    try:
        from backpack_quant_trading.core.stock_news_alert import ensure_dingtalk_keyword

        url = f"https://oapi.dingtalk.com/robot/send?access_token={token}"
        if secret:
            timestamp = str(round(datetime.now().timestamp() * 1000))
            string_to_sign = f"{timestamp}\n{secret}"
            hmac_code = hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
            sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
            url += f"&timestamp={timestamp}&sign={sign}"

        content = ensure_dingtalk_keyword(
            f"{symbol} {timeframe} 异动\n"
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"{message}"
        )
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


def send_dingtalk_alert_for_minute(symbol: str, timeframe: str, message: str = "") -> bool:
    """
    分钟预警专用钉钉推送：使用前端截图中配置的监控 Webhook。
    仅被 BinanceMinuteAlertService 使用，避免影响其它使用 DINGTALK_TOKEN 的告警。
    """
    if not MINUTE_ALERT_WEBHOOK:
        logger.warning("分钟预警钉钉跳过：未配置 MINUTE_ALERT_WEBHOOK")
        return False
    try:
        content = f"\n{symbol} {timeframe} 异动\n时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n{message}"
        data = {"msgtype": "text", "text": {"content": content}}
        resp = requests.post(MINUTE_ALERT_WEBHOOK, json=data, timeout=5)
        if resp.status_code == 200:
            logger.info(f"分钟预警钉钉已发送: {symbol} {timeframe}")
            return True
        logger.error(f"分钟预警钉钉发送失败: {resp.text}")
        return False
    except Exception as e:
        logger.error(f"分钟预警钉钉异常: {e}")
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
            self._stop_event.wait(1800)  # 30 分钟轮询一次，降低调用频率

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
# 用户主动停止后为 True，避免 get_status 从 DB 恢复导致“停止后仍继续监控”
_currency_monitor_user_stopped: bool = False


def get_monitor_instance() -> Optional[BinanceMonitorService]:
    return _monitor_instance


def set_monitor_instance(instance: Optional[BinanceMonitorService]):
    global _monitor_instance
    _monitor_instance = instance


def set_currency_monitor_user_stopped(stopped: bool):
    """停止/启动时设置，防止停止后通过 DB 缓存再次拉起监控"""
    global _currency_monitor_user_stopped
    _currency_monitor_user_stopped = stopped


def get_currency_monitor_user_stopped() -> bool:
    return _currency_monitor_user_stopped
