"""Hyperliquid 行情：K 线 candleSnapshot + 永续 universe 成交量排名。"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

HL_INFO_URL = "https://api.hyperliquid.xyz/info"

INTERVAL_MS: Dict[str, int] = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "8h": 28_800_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
    "3d": 259_200_000,
    "1w": 604_800_000,
}

_PROXY_KEYS = (
    "HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy",
)


def _hl_direct_network() -> bool:
    return os.getenv("CRYPTO_SIGNAL_DIRECT", "").lower() in ("1", "true", "yes")


def _hl_post(payload: Dict[str, Any], timeout: int = 30) -> Any:
    saved: Dict[str, str] = {}
    proxies = {"http": None, "https": None}
    if _hl_direct_network():
        for k in _PROXY_KEYS:
            if k in os.environ:
                saved[k] = os.environ.pop(k)
    try:
        resp = requests.post(
            HL_INFO_URL,
            json=payload,
            timeout=timeout,
            proxies=proxies,
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()
        return resp.json()
    finally:
        for k, v in saved.items():
            os.environ[k] = v


def normalize_hl_interval(interval: str) -> str:
    iv = (interval or "4h").strip().lower()
    mapping = {
        "1h": "1h", "2h": "2h", "4h": "4h", "1d": "1d", "1w": "1w",
        "60": "1h", "120": "2h", "240": "4h",
    }
    return mapping.get(iv, iv)


def to_hl_coin(symbol: str) -> str:
    """ETHUSDT / ETH-USD / ETH → HL 币种名 ETH。"""
    s = (symbol or "").upper().strip()
    for suffix in ("USDT.P", "USDC.P", "USDT", "USDC", "USD", "PERP", "-USD"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    if ":" in s:
        s = s.split(":")[-1]
    return s.strip()


def fetch_hl_klines_sync(
    coin: str,
    interval: str,
    start_ms: int,
    end_ms: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """同步拉取 HL K 线，返回 [{"t","o","h","l","c","v"}, ...] 升序。"""
    if end_ms is None:
        end_ms = int(time.time() * 1000)
    coin = to_hl_coin(coin)
    interval = normalize_hl_interval(interval)
    payload = {
        "type": "candleSnapshot",
        "req": {"coin": coin, "interval": interval, "startTime": start_ms, "endTime": end_ms},
    }
    try:
        data = _hl_post(payload)
        result: List[Dict[str, Any]] = []
        for item in (data or []):
            try:
                result.append({
                    "t": int(item["t"]),
                    "o": float(item["o"]),
                    "h": float(item["h"]),
                    "l": float(item["l"]),
                    "c": float(item["c"]),
                    "v": float(item["v"]),
                })
            except (KeyError, TypeError, ValueError):
                continue
        result.sort(key=lambda x: x["t"])
        return result
    except Exception as e:
        logger.warning("HL K线拉取失败 coin=%s interval=%s: %s", coin, interval, e)
        return []


def hl_bars_to_ohlcv(bars: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """统一为 scanner 使用的 OHLCV 结构。"""
    return [
        {
            "time": int(b["t"]),
            "open": float(b["o"]),
            "high": float(b["h"]),
            "low": float(b["l"]),
            "close": float(b["c"]),
            "volume": float(b["v"]),
        }
        for b in bars
    ]


def fetch_hl_klines_batch(
    coin: str,
    interval: str,
    total_limit: int = 1000,
    *,
    chunk_bars: int = 500,
) -> Optional[List[Dict[str, Any]]]:
    """分批回溯拉取最多 total_limit 根 K 线（Hyperliquid）。"""
    coin = to_hl_coin(coin)
    interval = normalize_hl_interval(interval)
    ms = INTERVAL_MS.get(interval, 14_400_000)
    end_ms = int(time.time() * 1000)
    merged: Dict[int, Dict[str, Any]] = {}
    remaining = max(1, int(total_limit))
    current_end = end_ms

    while remaining > 0:
        need = min(remaining, chunk_bars)
        start_ms = current_end - ms * (need + 5)
        bars = fetch_hl_klines_sync(coin, interval, start_ms, current_end)
        if not bars:
            break
        for b in bars:
            merged[int(b["t"])] = b
        if len(bars) < need // 2:
            break
        earliest = bars[0]["t"]
        current_end = earliest - 1
        remaining = total_limit - len(merged)
        if remaining <= 0:
            break
        time.sleep(0.15)

    if not merged:
        return None
    ordered = [merged[k] for k in sorted(merged.keys())]
    if len(ordered) > total_limit:
        ordered = ordered[-total_limit:]
    return hl_bars_to_ohlcv(ordered)


def fetch_hl_top_perps_by_volume(limit: int = 50) -> List[Dict[str, Any]]:
    """
    Hyperliquid 永续按 24h 成交额(dayNtlVlm) 排序取 Top N。
    文档: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals
    """
    try:
        data = _hl_post({"type": "metaAndAssetCtxs"})
        if not isinstance(data, list) or len(data) < 2:
            return []
        meta_block = data[0] if isinstance(data[0], dict) else {}
        ctxs = data[1] if isinstance(data[1], list) else []
        universe = meta_block.get("universe") or []
        scored: List[Tuple[float, Dict[str, Any]]] = []
        for i, u in enumerate(universe):
            if not isinstance(u, dict):
                continue
            name = str(u.get("name") or "").strip()
            if not name:
                continue
            ctx = ctxs[i] if i < len(ctxs) and isinstance(ctxs[i], dict) else {}
            try:
                vol = float(ctx.get("dayNtlVlm") or 0)
            except (TypeError, ValueError):
                vol = 0.0
            try:
                mark = float(ctx.get("markPx") or ctx.get("midPx") or 0)
            except (TypeError, ValueError):
                mark = 0.0
            try:
                prev = float(ctx.get("prevDayPx") or 0)
                chg = ((mark - prev) / prev * 100) if prev else 0.0
            except (TypeError, ValueError):
                chg = 0.0
            scored.append((vol, {
                "id": name.lower(),
                "symbol": name,
                "name": name,
                "hl_coin": name,
                "market_cap_rank": None,
                "current_price": mark,
                "price_change_percentage_24h": round(chg, 2),
                "day_ntl_vlm": vol,
            }))
        scored.sort(key=lambda x: x[0], reverse=True)
        out = [x[1] for x in scored[: max(1, limit)]]
        for i, item in enumerate(out, start=1):
            item["market_cap_rank"] = i
        return out
    except Exception as e:
        logger.error("HL metaAndAssetCtxs 失败: %s", e)
        return []
