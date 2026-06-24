"""Massive（原 Polygon.io）美股 K 线 / 报价。"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

# 官方仍可用 api.polygon.io；Massive 文档亦指向同一套 REST
MASSIVE_API_BASE = os.getenv("MASSIVE_API_BASE", "https://api.polygon.io")

_INTERVAL_MS: Dict[str, int] = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
    "1w": 604_800_000,
}


def get_massive_api_key() -> str:
    from backpack_quant_trading.core.env_loader import load_project_env

    load_project_env()
    return (
        os.getenv("MASSIVE_API_KEY")
        or os.getenv("POLYGON_API_KEY")
        or ""
    ).strip()


def normalize_us_ticker(symbol: str) -> str:
    """NVDA / NVDAUSDT / AAPL -> NVDA"""
    s = (symbol or "").upper().strip()
    for suffix in ("USDT", "USD", ".US", ".O", ".P"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    if ":" in s:
        s = s.split(":")[-1]
    return s.strip()


def normalize_massive_interval(interval: str) -> Tuple[int, str]:
    """
    返回 (multiplier, timespan) 供 Polygon aggs API 使用。
    timespan: minute | hour | day | week
    """
    iv = (interval or "1d").strip().upper()
    mapping = {
        "1": ("1", "minute"), "1M": ("1", "minute"), "1m": ("1", "minute"),
        "5": ("5", "minute"), "5M": ("5", "minute"), "5m": ("5", "minute"),
        "15": ("15", "minute"), "15M": ("15", "minute"), "15m": ("15", "minute"),
        "30": ("30", "minute"), "30M": ("30", "minute"), "30m": ("30", "minute"),
        "60": ("1", "hour"), "1H": ("1", "hour"), "1h": ("1", "hour"),
        "120": ("2", "hour"), "2H": ("2", "hour"), "2h": ("2", "hour"),
        "240": ("4", "hour"), "4H": ("4", "hour"), "4h": ("4", "hour"),
        "D": ("1", "day"), "1D": ("1", "day"), "1d": ("1", "day"),
        "W": ("1", "week"), "1W": ("1", "week"), "1w": ("1", "week"),
    }
    if iv in mapping:
        m, t = mapping[iv]
        return int(m), t
    iv_low = iv.lower()
    if iv_low in mapping:
        m, t = mapping[iv_low]
        return int(m), t
    if iv_low.endswith("h") and iv_low[:-1].isdigit():
        return int(iv_low[:-1]), "hour"
    if iv_low.endswith("m") and iv_low[:-1].isdigit():
        return int(iv_low[:-1]), "minute"
    return 1, "day"


def interval_label(interval: str) -> str:
    """统一展示用周期标签，如 1h / 4h / 1d"""
    mult, span = normalize_massive_interval(interval)
    if span == "minute":
        return f"{mult}m"
    if span == "hour":
        return f"{mult}h"
    if span == "week":
        return "1w"
    return "1d"


def _massive_get(path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    key = get_massive_api_key()
    if not key:
        raise ValueError("未配置 MASSIVE_API_KEY（或 POLYGON_API_KEY）")
    p = dict(params or {})
    p["apiKey"] = key
    url = f"{MASSIVE_API_BASE.rstrip('/')}{path}"
    # 与原先一致：requests 默认 trust_env，load_project_env 后自动读 .env / shell 的 HTTP(S)_PROXY
    r = requests.get(url, params=p, timeout=30)
    if r.status_code != 200:
        try:
            detail = r.json()
        except Exception:
            detail = r.text[:300]
        raise RuntimeError(f"Massive API {r.status_code}: {detail}")
    return r.json()


def _lookback_days_for_us_bars(mult: int, span: str, limit: int) -> int:
    """美股非 24h 交易，分钟/小时周期需更长日历回看。"""
    lim = max(int(limit or 200), 30)
    if span == "week":
        return max(52, lim * 7 + 14)
    if span == "day":
        return max(30, int(lim * 1.8) + 10)
    # 常规盘约 6.5h/日、5 日/周
    if span == "hour":
        bars_per_trading_day = max(6.5 / max(mult, 1), 0.5)
    else:
        bars_per_trading_day = max(390 / max(mult, 1), 1.0)
    trading_days = lim / bars_per_trading_day
    calendar_days = int(trading_days * (7 / 5) * 1.45) + 20
    floor = 90 if span == "hour" else 120
    return max(calendar_days, floor)


# Polygon aggs 的 limit 参数：传较小值时部分周期（如 2/hour）会异常少返 bars；
# 统一拉大请求上限，再在客户端截取所需根数。
_POLYGON_AGG_REQUEST_LIMIT = 50_000


def _parse_agg_rows(data: Any, limit: int) -> List[Dict[str, Any]]:
    """解析 aggs；调用方按 sort=desc 取前 limit 根后再 reverse。"""
    rows: List[Dict[str, Any]] = []
    for item in (data.get("results") or []):
        try:
            rows.append({
                "time": int(item["t"]),
                "open": float(item["o"]),
                "high": float(item["h"]),
                "low": float(item["l"]),
                "close": float(item["c"]),
                "volume": float(item.get("v") or 0),
            })
        except (KeyError, TypeError, ValueError):
            continue
    if len(rows) > limit:
        rows = rows[:limit]
    return rows


def _fetch_agg_range(
    ticker: str,
    mult: int,
    span: str,
    from_s: str,
    to_s: str,
    *,
    client_limit: int,
) -> List[Dict[str, Any]]:
    """
    Polygon aggs：sort=asc 时免费套餐常只返最早一段 K 线（缺最新 bar）；
    统一 sort=desc 取最近 N 根，再反转为升序供指标计算。
    """
    path = f"/v2/aggs/ticker/{ticker}/range/{mult}/{span}/{from_s}/{to_s}"
    data = _massive_get(
        path,
        {
            "adjusted": "true",
            "sort": "desc",
            "limit": _POLYGON_AGG_REQUEST_LIMIT,
        },
    )
    rows = _parse_agg_rows(data, _POLYGON_AGG_REQUEST_LIMIT)
    if len(rows) > client_limit:
        rows = rows[:client_limit]
    rows.reverse()
    return rows


def fetch_massive_bars(
    symbol: str,
    interval: str = "1d",
    limit: int = 200,
) -> List[Dict[str, Any]]:
    """
    拉取 OHLCV，返回与 HL/crypto 一致的升序列表：
    [{"time": ms, "open", "high", "low", "close", "volume"}, ...]
    """
    ticker = normalize_us_ticker(symbol)
    if not ticker:
        return []
    mult, span = normalize_massive_interval(interval)
    end = datetime.now(timezone.utc)
    lookback_days = _lookback_days_for_us_bars(mult, span, limit)
    start = end - timedelta(days=lookback_days)
    from_s = start.strftime("%Y-%m-%d")
    to_s = end.strftime("%Y-%m-%d")
    try:
        rows = _fetch_agg_range(
            ticker, mult, span, from_s, to_s, client_limit=int(limit),
        )
    except Exception as e:
        logger.warning("Massive K线失败 %s %s: %s", ticker, interval, e)
        rows = []

    # 分钟/小时仍不足时，再扩一倍回看重试一次
    if len(rows) < 30 and span in ("minute", "hour"):
        start2 = end - timedelta(days=lookback_days * 2)
        try:
            rows2 = _fetch_agg_range(
                ticker,
                mult,
                span,
                start2.strftime("%Y-%m-%d"),
                to_s,
                client_limit=int(limit),
            )
            if len(rows2) > len(rows):
                rows = rows2
        except Exception as e:
            logger.debug("Massive K线扩窗重试失败 %s %s: %s", ticker, interval, e)

    return rows


def fetch_massive_last_price(symbol: str) -> Optional[float]:
    """优先 prev 收盘；失败则取最近一根 K 线收盘价。"""
    ticker = normalize_us_ticker(symbol)
    if not ticker:
        return None
    try:
        data = _massive_get(f"/v2/aggs/ticker/{ticker}/prev", {})
        results = data.get("results") or []
        if results:
            return float(results[0]["c"])
    except Exception as e:
        logger.debug("Massive prev %s: %s", ticker, e)
    bars = fetch_massive_bars(ticker, "1d", limit=2)
    if bars:
        return float(bars[-1]["close"])
    return None


def fetch_klines_us(symbol: str, interval: str, total_limit: int = 200) -> Optional[List[Dict[str, Any]]]:
    """与 fetch_klines_crypto 同签名，供评分模块切换数据源。"""
    bars = fetch_massive_bars(symbol, interval, limit=total_limit)
    return bars if len(bars) >= 30 else None


def fetch_massive_news(symbol: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Polygon/Massive 个股新闻（需 MASSIVE_API_KEY）。"""
    ticker = normalize_us_ticker(symbol)
    if not ticker or not get_massive_api_key():
        return []
    try:
        data = _massive_get(
            "/v2/reference/news",
            {"ticker": ticker, "limit": min(int(limit or 10), 50), "order": "desc"},
        )
    except Exception as e:
        logger.debug("Massive news %s: %s", ticker, e)
        return []

    out: List[Dict[str, Any]] = []
    for item in (data.get("results") or []):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        pub = str(item.get("published_utc") or item.get("published") or "")
        try:
            if pub.endswith("Z"):
                pub = datetime.fromisoformat(pub.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            pass
        publisher = ""
        pubs = item.get("publisher")
        if isinstance(pubs, dict):
            publisher = str(pubs.get("name") or "")
        desc = str(item.get("description") or "")[:280]
        out.append({
            "time": pub,
            "source": publisher or "Massive",
            "title": title,
            "text": f"{title} — {desc}".strip(" —"),
            "url": str(item.get("article_url") or item.get("url") or ""),
            "feed_key": "massive",
        })
    return out


def is_us_stock_ticker(symbol: str) -> bool:
    """委托 signal_asset_router 统一判定（兼容旧调用）。"""
    from backpack_quant_trading.core.signal_asset_router import is_us_stock_signal

    return is_us_stock_signal(symbol)
