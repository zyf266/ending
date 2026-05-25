"""AI 选股卡片现价：多源拉取 + 本地缓存，定时批量更新。"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests

from backpack_quant_trading.core.research_report_hub import get_quote_symbol, list_research_codes

logger = logging.getLogger(__name__)

_DATA = Path(__file__).resolve().parents[1] / "data"
CACHE_PATH = _DATA / "research_card_prices.json"

_HL_COINS = {"ETH", "HYPE"}


def _trust_env() -> bool:
    return os.environ.get("STOCK_NEWS_FORCE_SYSTEM_PROXY", "").lower() in ("1", "true", "yes")


def _session() -> requests.Session:
    s = requests.Session()
    s.trust_env = _trust_env()
    return s


def fetch_yahoo_price(quote_symbol: str) -> Optional[float]:
    sym = str(quote_symbol or "").upper().strip()
    if not sym:
        return None
    try:
        with _session() as sess:
            r = sess.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
                params={"interval": "1d", "range": "1d"},
                timeout=12,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            )
        if r.status_code != 200:
            return None
        meta = (r.json().get("chart") or {}).get("result") or []
        if not meta:
            return None
        price = meta[0].get("meta", {}).get("regularMarketPrice")
        return float(price) if price is not None else None
    except Exception as exc:
        logger.debug("Yahoo 报价失败 %s: %s", sym, exc)
        return None


def fetch_stooq_us_price(ticker: str) -> Optional[float]:
    """美股 Stooq：ticker 如 NVDA -> nvda.us"""
    base = str(ticker or "").upper().strip().split(".")[0]
    if not base:
        return None
    sym = f"{base.lower()}.us"
    try:
        with _session() as sess:
            r = sess.get(
                "https://stooq.com/q/l/",
                params={"s": sym, "f": "sd2t2ohlcv", "h": "", "e": "csv"},
                timeout=20,
            )
        if r.status_code != 200:
            return None
        rows = list(csv.reader(io.StringIO(r.text.strip())))
        if len(rows) < 2:
            return None
        close = rows[1][6] if len(rows[1]) > 6 else rows[1][-1]
        if not close or str(close).upper() in ("N/D", "N/A", ""):
            return None
        return float(close)
    except Exception as exc:
        logger.warning("Stooq 报价失败 %s: %s", sym, exc)
        return None


def fetch_hyperliquid_mid(coin: str) -> Optional[float]:
    c = str(coin or "").upper().strip()
    if not c:
        return None
    try:
        with _session() as sess:
            r = sess.post(
                "https://api.hyperliquid.xyz/info",
                json={"type": "allMids"},
                timeout=25,
            )
        if r.status_code != 200:
            return None
        data = r.json()
        if not isinstance(data, dict):
            return None
        raw = data.get(c)
        return float(raw) if raw is not None else None
    except Exception as exc:
        logger.warning("Hyperliquid 报价失败 %s: %s", c, exc)
        return None


def fetch_market_price(code: str, quote_symbol: str) -> Tuple[Optional[float], str]:
    """
    按标的类型选择数据源，返回 (价格, source)。
    美股：Stooq -> Yahoo；ETH/HYPE：Hyperliquid -> Yahoo。
    """
    sym = str(quote_symbol or code or "").upper().strip()
    base = sym.replace("-USD", "").replace("-USDT", "")

    if base in _HL_COINS or sym.endswith("-USD") and base in _HL_COINS:
        p = fetch_hyperliquid_mid(base)
        if p is not None:
            return p, "hyperliquid"
        p = fetch_yahoo_price(sym)
        return p, "yahoo" if p is not None else "none"

    ticker = base.split(".")[0]
    p = fetch_stooq_us_price(ticker)
    if p is not None:
        return p, "stooq"
    p = fetch_yahoo_price(sym)
    return p, "yahoo" if p is not None else "none"


def load_price_cache() -> Dict[str, Any]:
    if not CACHE_PATH.is_file():
        return {"updated_at": None, "prices": {}}
    try:
        raw = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return {"updated_at": raw.get("updated_at"), "prices": raw.get("prices") or {}}
    except Exception as exc:
        logger.warning("读取价格缓存失败: %s", exc)
    return {"updated_at": None, "prices": {}}


def save_price_cache(data: Dict[str, Any]) -> None:
    _DATA.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_cached_hub_price(code: str) -> Optional[Dict[str, Any]]:
    sym = str(code or "").upper().strip()
    cache = load_price_cache()
    row = (cache.get("prices") or {}).get(sym)
    if not isinstance(row, dict):
        return None
    return {
        "price": row.get("price"),
        "currency": row.get("currency") or "USD",
        "price_updated_at": row.get("fetched_at") or cache.get("updated_at"),
        "quote_symbol": row.get("quote_symbol"),
        "source": row.get("source") or "cache",
    }


def refresh_all_research_prices() -> Dict[str, Any]:
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    prices: Dict[str, Any] = {}
    ok_count = 0
    for code in list_research_codes():
        qsym = get_quote_symbol(code)
        price, source = fetch_market_price(code, qsym)
        entry: Dict[str, Any] = {
            "quote_symbol": qsym,
            "currency": "USD",
            "source": source,
            "fetched_at": now_str,
            "price": price,
        }
        if price is not None:
            ok_count += 1
        prices[code] = entry
        logger.info("research_price %s (%s) [%s] => %s", code, qsym, source, price)

    payload = {"updated_at": now_str, "prices": prices}
    save_price_cache(payload)
    return {"ok": True, "updated_at": now_str, "count": len(prices), "ok_count": ok_count}


def refresh_research_prices_task() -> Dict[str, Any]:
    try:
        return refresh_all_research_prices()
    except Exception as exc:
        logger.exception("批量更新研究卡片价格失败: %s", exc)
        return {"ok": False, "error": str(exc)}
