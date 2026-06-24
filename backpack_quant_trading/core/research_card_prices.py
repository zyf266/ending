"""AI 选股卡片现价：多源批量拉取 + 本地缓存（适配国内服务器 Yahoo 不可用）。"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import quote

import requests

from backpack_quant_trading.core.research_report_hub import get_quote_symbol, list_research_codes

logger = logging.getLogger(__name__)

_DATA = Path(__file__).resolve().parents[1] / "data"
CACHE_PATH = _DATA / "research_card_prices.json"

_HL_COINS = {"ETH", "HYPE"}
_A_SHARE_SUFFIX = re.compile(r"\.(SZ|SS|SH)$", re.I)
_YAHOO_CHART_BASES = (
    "https://query1.finance.yahoo.com/v8/finance/chart/",
    "https://query2.finance.yahoo.com/v8/finance/chart/",
)
_YAHOO_SPARK_BASES = (
    "https://query1.finance.yahoo.com/v7/finance/spark",
    "https://query2.finance.yahoo.com/v7/finance/spark",
)
_YAHOO_WARMUP_URL = "https://finance.yahoo.com/"
_YAHOO_BATCH_SIZE = 40
_COINGECKO_IDS = {"ONDO": "ondo-finance"}
_MASSIVE_PREV_DELAY_SEC = 13.0


def _proxy_env_value() -> str:
    for key in (
        "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY",
        "https_proxy", "http_proxy", "all_proxy",
    ):
        val = os.environ.get(key, "").strip()
        if val:
            return val
    return ""


def _trust_env() -> bool:
    """是否让 requests 走系统代理。检测到 HTTP_PROXY 等环境变量时自动启用。"""
    if os.environ.get("STOCK_NEWS_DISABLE_PROXY", "").lower() in ("1", "true", "yes"):
        return False
    if os.environ.get("STOCK_NEWS_FORCE_SYSTEM_PROXY", "").lower() in ("1", "true", "yes"):
        return True
    return bool(_proxy_env_value())


def _session() -> requests.Session:
    s = requests.Session()
    s.trust_env = _trust_env()
    return s


def _direct_session() -> requests.Session:
    """国内源（东方财富等）直连，不走 HTTP_PROXY。"""
    s = requests.Session()
    s.trust_env = False
    return s


def _yahoo_headers() -> Dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://finance.yahoo.com/",
        "Origin": "https://finance.yahoo.com",
    }


def _warmup_yahoo_session(sess: requests.Session) -> None:
    try:
        sess.get(_YAHOO_WARMUP_URL, headers=_yahoo_headers(), timeout=10)
    except Exception:
        pass


def _is_a_share(code: str, quote_symbol: str) -> bool:
    sym = str(quote_symbol or code or "").upper().strip()
    if _A_SHARE_SUFFIX.search(sym):
        return True
    c = str(code or "").strip()
    return c.isdigit() and len(c) == 6


def _is_yahoo_crypto(quote_symbol: str) -> bool:
    sym = str(quote_symbol or "").upper().strip()
    if not sym:
        return False
    base = sym.replace("-USD", "").replace("-USDT", "")
    if base in _HL_COINS:
        return False
    return sym.endswith("-USD") or sym.endswith("-USDT")


def _is_us_stock(code: str, quote_symbol: str) -> bool:
    sym = str(quote_symbol or code or "").upper().strip()
    if _is_a_share(code, sym) or _is_yahoo_crypto(sym):
        return False
    base = sym.replace("-USD", "").replace("-USDT", "").split(".")[0]
    return base not in _HL_COINS and not sym.endswith("-USD")


def _us_ticker(code: str, quote_symbol: str) -> str:
    sym = str(quote_symbol or code or "").upper().strip()
    return sym.replace("-USD", "").replace("-USDT", "").split(".")[0]


def _parse_yahoo_chart_payload(data: dict) -> Tuple[Optional[float], str]:
    meta_list = (data.get("chart") or {}).get("result") or []
    if not meta_list:
        return None, "USD"
    m = meta_list[0].get("meta") or {}
    price = m.get("regularMarketPrice")
    currency = str(m.get("currency") or "USD").upper()
    return (float(price), currency) if price is not None else (None, currency)


def _extract_spark_item(item: dict) -> Tuple[Optional[str], Optional[float], str]:
    if not isinstance(item, dict):
        return None, None, "USD"
    sym = str(item.get("symbol") or "").upper().strip()
    if not sym:
        return None, None, "USD"
    resp_list = item.get("response") or []
    if not resp_list:
        return sym, None, "USD"
    resp = resp_list[0] if isinstance(resp_list[0], dict) else {}
    meta = resp.get("meta") or {}
    currency = str(meta.get("currency") or "USD").upper()
    price = meta.get("regularMarketPrice")
    if price is not None:
        return sym, float(price), currency
    closes = ((resp.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    for c in reversed(closes):
        if c is not None:
            return sym, float(c), currency
    return sym, None, currency


def _parse_yahoo_spark_batch(data: dict) -> Dict[str, Tuple[float, str]]:
    out: Dict[str, Tuple[float, str]] = {}
    for item in (data.get("spark") or {}).get("result") or []:
        sym, price, currency = _extract_spark_item(item)
        if sym and price is not None:
            out[sym] = (price, currency)
    return out


def fetch_yahoo_batch_quotes(
    quote_symbols: List[str],
    *,
    sess: Optional[requests.Session] = None,
) -> Dict[str, Tuple[float, str]]:
    syms: List[str] = []
    seen: Set[str] = set()
    for raw in quote_symbols:
        s = str(raw or "").upper().strip()
        if not s or s in seen:
            continue
        seen.add(s)
        syms.append(s)
    if not syms:
        return {}

    own_sess = sess is None
    if own_sess:
        sess = _session()
        _warmup_yahoo_session(sess)

    headers = _yahoo_headers()
    merged: Dict[str, Tuple[float, str]] = {}
    try:
        for chunk_start in range(0, len(syms), _YAHOO_BATCH_SIZE):
            chunk = syms[chunk_start : chunk_start + _YAHOO_BATCH_SIZE]
            symbols_param = ",".join(chunk)
            got_chunk = False
            for base in _YAHOO_SPARK_BASES:
                try:
                    r = sess.get(
                        base,
                        params={"symbols": symbols_param, "range": "1d", "interval": "1d"},
                        timeout=20,
                        headers=headers,
                    )
                    if r.status_code == 200:
                        merged.update(_parse_yahoo_spark_batch(r.json()))
                        got_chunk = True
                        break
                    if r.status_code in (403, 429):
                        logger.warning("Yahoo batch spark HTTP %s (%s symbols)", r.status_code, len(chunk))
                        time.sleep(1.0)
                except Exception as exc:
                    logger.debug("Yahoo batch spark: %s", exc)
            if not got_chunk:
                logger.warning("Yahoo 批量 spark 失败，chunk=%s", symbols_param[:80])
            if chunk_start + _YAHOO_BATCH_SIZE < len(syms):
                time.sleep(0.5)
    finally:
        if own_sess and sess is not None:
            sess.close()

    return merged


def fetch_yahoo_quote(
    quote_symbol: str,
    *,
    sess: Optional[requests.Session] = None,
) -> Tuple[Optional[float], str]:
    sym = str(quote_symbol or "").upper().strip()
    if not sym:
        return None, "USD"

    batch = fetch_yahoo_batch_quotes([sym], sess=sess)
    if sym in batch:
        return batch[sym]

    encoded = quote(sym, safe="")
    headers = _yahoo_headers()
    own_sess = sess is None
    if own_sess:
        sess = _session()
        _warmup_yahoo_session(sess)

    try:
        for base in _YAHOO_CHART_BASES:
            try:
                r = sess.get(
                    f"{base}{encoded}",
                    params={"interval": "1d", "range": "1d"},
                    timeout=12,
                    headers=headers,
                )
                if r.status_code == 200:
                    price, currency = _parse_yahoo_chart_payload(r.json())
                    if price is not None:
                        return price, currency
            except Exception as exc:
                logger.debug("Yahoo chart %s: %s", sym, exc)
    finally:
        if own_sess and sess is not None:
            sess.close()

    return None, "USD"


def fetch_yahoo_price(quote_symbol: str) -> Optional[float]:
    price, _ = fetch_yahoo_quote(quote_symbol)
    return price


def fetch_hyperliquid_all_mids() -> Dict[str, float]:
    """返回 HL 全部 mid（含 ONDO 等），供加密与非美股标的兜底。"""
    try:
        with _session() as sess:
            r = sess.post(
                "https://api.hyperliquid.xyz/info",
                json={"type": "allMids"},
                timeout=25,
            )
        if r.status_code != 200:
            return {}
        data = r.json()
        if not isinstance(data, dict):
            return {}
        out: Dict[str, float] = {}
        for coin, raw in data.items():
            if raw is None:
                continue
            try:
                out[str(coin).upper().strip()] = float(raw)
            except (TypeError, ValueError):
                continue
        return out
    except Exception as exc:
        logger.warning("Hyperliquid allMids 失败: %s", exc)
        return {}


def fetch_hyperliquid_mid(coin: str) -> Optional[float]:
    return fetch_hyperliquid_all_mids().get(str(coin or "").upper().strip())


def fetch_massive_grouped_us_closes(tickers: List[str]) -> Dict[str, float]:
    """
    Massive/Polygon grouped daily：一次请求拿全日美股收盘（免费套餐可用，取最近交易日）。
    """
    from backpack_quant_trading.core.massive_klines import _massive_get, get_massive_api_key, normalize_us_ticker

    if not get_massive_api_key():
        return {}

    want = {normalize_us_ticker(t) for t in tickers if t}
    if not want:
        return {}

    for days_back in range(1, 10):
        d = (date.today() - timedelta(days=days_back)).isoformat()
        try:
            data = _massive_get(f"/v2/aggs/grouped/locale/us/market/stocks/{d}", {})
            results = data.get("results") or []
            out: Dict[str, float] = {}
            for row in results:
                if not isinstance(row, dict):
                    continue
                t = normalize_us_ticker(str(row.get("T") or ""))
                if t in want and row.get("c") is not None:
                    out[t] = float(row["c"])
            if out:
                logger.info("[研究卡片价格] Massive grouped %s: %s/%s", d, len(out), len(want))
                return out
        except Exception as exc:
            msg = str(exc)
            logger.debug("Massive grouped %s: %s", d, exc)
            if "429" in msg:
                time.sleep(15)
    return {}


def fetch_massive_prev_price(ticker: str) -> Optional[float]:
    from backpack_quant_trading.core.massive_klines import _massive_get, get_massive_api_key, normalize_us_ticker

    if not get_massive_api_key():
        return None
    sym = normalize_us_ticker(ticker)
    if not sym:
        return None
    try:
        data = _massive_get(f"/v2/aggs/ticker/{sym}/prev", {})
        results = data.get("results") or []
        if results:
            return float(results[0]["c"])
    except Exception as exc:
        logger.debug("Massive prev %s: %s", sym, exc)
    return None


def fetch_massive_prev_prices_slow(tickers: List[str]) -> Dict[str, float]:
    """逐只 prev，间隔拉取避免 429（仅补缺）。"""
    from backpack_quant_trading.core.massive_klines import normalize_us_ticker

    out: Dict[str, float] = {}
    uniq = []
    seen: Set[str] = set()
    for t in tickers:
        s = normalize_us_ticker(t)
        if s and s not in seen:
            seen.add(s)
            uniq.append(s)

    for i, sym in enumerate(uniq):
        if i > 0:
            time.sleep(_MASSIVE_PREV_DELAY_SEC)
        p = fetch_massive_prev_price(sym)
        if p is not None:
            out[sym] = p
            logger.info("[研究卡片价格] Massive prev %s => %s", sym, p)
    return out


def _a_share_list_symbol(code: str) -> Optional[str]:
    c = str(code or "").strip()
    if not c.isdigit() or len(c) != 6:
        return None
    return f"sh{c}" if c.startswith("6") else f"sz{c}"


def _fetch_eastmoney_a_share_price(code: str) -> Optional[float]:
    """东方财富 A 股现价（直连）。"""
    c = str(code or "").strip()
    if not c.isdigit() or len(c) != 6:
        return None
    market = "1" if c.startswith("6") else "0"
    secid = f"{market}.{c}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://quote.eastmoney.com/",
        "Accept": "application/json,text/plain,*/*",
    }
    urls = (
        "https://push2.eastmoney.com/api/qt/stock/get",
        "https://push2his.eastmoney.com/api/qt/stock/get",
    )
    for url in urls:
        try:
            with _direct_session() as sess:
                r = sess.get(
                    url,
                    params={"secid": secid, "fields": "f43,f57,f152", "ut": "fa5fd1943c7b386f172d6893dbfba10b"},
                    timeout=15,
                    headers=headers,
                )
            if r.status_code != 200:
                continue
            data = (r.json() or {}).get("data") or {}
            raw = data.get("f43")
            if raw is None:
                continue
            scale = int(data.get("f152") or 2)
            px = float(raw) / (10 ** scale)
            if px > 0:
                return px
        except Exception as exc:
            logger.debug("东方财富 %s (%s): %s", c, url, exc)
    return None


def _fetch_sina_a_share_price(code: str) -> Optional[float]:
    """新浪 hq.sinajs.cn 现价（字段 index 3）。"""
    sym = _a_share_list_symbol(code)
    if not sym:
        return None
    try:
        with _direct_session() as sess:
            r = sess.get(
                f"https://hq.sinajs.cn/list={sym}",
                timeout=15,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Referer": "https://finance.sina.com.cn/",
                },
            )
        if r.status_code != 200:
            return None
        text = r.text
        if '="' not in text:
            return None
        body = text.split('="', 1)[1].rstrip('";')
        parts = body.split(",")
        if len(parts) < 4:
            return None
        px = float(parts[3])
        return px if px > 0 else None
    except Exception as exc:
        logger.debug("新浪 A股现价 %s 失败: %s", code, exc)
        return None


def _fetch_tencent_a_share_price(code: str) -> Optional[float]:
    """腾讯 qt.gtimg.cn 现价（~ 分隔，index 3）。"""
    sym = _a_share_list_symbol(code)
    if not sym:
        return None
    try:
        with _direct_session() as sess:
            r = sess.get(
                f"https://qt.gtimg.cn/q={sym}",
                timeout=15,
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"},
            )
        if r.status_code != 200:
            return None
        text = r.text
        if "~" not in text:
            return None
        body = text.split('"', 1)[-1].strip().strip('"').strip()
        parts = body.split("~")
        if len(parts) < 4:
            return None
        px = float(parts[3])
        return px if px > 0 else None
    except Exception as exc:
        logger.debug("腾讯 A股现价 %s 失败: %s", code, exc)
        return None


def fetch_a_share_price(code: str) -> Tuple[Optional[float], str]:
    """
    A 股现价：东方财富 → 新浪 → 腾讯（云服务器上东财常断连，后两者更稳）。
    返回 (price, source)。
    """
    c = str(code or "").strip()
    for attempt in range(2):
        px = _fetch_eastmoney_a_share_price(c)
        if px is not None:
            return px, "eastmoney"
        if attempt == 0:
            time.sleep(0.35)
    px = _fetch_sina_a_share_price(c)
    if px is not None:
        logger.info("A股现价 %s 走新浪兜底: %s", c, px)
        return px, "sina"
    px = _fetch_tencent_a_share_price(c)
    if px is not None:
        logger.info("A股现价 %s 走腾讯兜底: %s", c, px)
        return px, "tencent"
    logger.warning("A股现价 %s 全部数据源失败", c)
    return None, "none"


def fetch_eastmoney_a_share_price(code: str) -> Optional[float]:
    """兼容旧调用；内部走多源 fetch_a_share_price。"""
    px, _ = fetch_a_share_price(code)
    return px


def fetch_coingecko_usd_price(coin_code: str) -> Optional[float]:
    cg_id = _COINGECKO_IDS.get(str(coin_code or "").upper().strip())
    if not cg_id:
        return None
    try:
        with _session() as sess:
            r = sess.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": cg_id, "vs_currencies": "usd"},
                timeout=12,
            )
        if r.status_code != 200:
            return None
        return float(r.json()[cg_id]["usd"])
    except Exception as exc:
        logger.debug("CoinGecko %s: %s", coin_code, exc)
        return None


def fetch_stooq_us_price(ticker: str) -> Optional[float]:
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
        logger.debug("Stooq 报价失败 %s: %s", sym, exc)
        return None


def fetch_market_price(
    code: str,
    quote_symbol: str,
    *,
    yahoo_quotes: Optional[Dict[str, Tuple[float, str]]] = None,
    hl_mids: Optional[Dict[str, float]] = None,
    massive_closes: Optional[Dict[str, float]] = None,
    yahoo_sess: Optional[requests.Session] = None,
) -> Tuple[Optional[float], str, str]:
    sym = str(quote_symbol or code or "").upper().strip()
    base = sym.replace("-USD", "").replace("-USDT", "")

    mids = hl_mids if hl_mids is not None else fetch_hyperliquid_all_mids()
    if base in _HL_COINS and base in mids:
        return mids[base], "hyperliquid", "USD"

    if _is_yahoo_crypto(sym) and base in mids:
        return mids[base], "hyperliquid", "USD"

    yahoo_map = yahoo_quotes
    if yahoo_map is None:
        yahoo_map = fetch_yahoo_batch_quotes([sym], sess=yahoo_sess)
    if sym in yahoo_map:
        price, currency = yahoo_map[sym]
        return price, "yahoo", currency

    if _is_us_stock(code, sym):
        ticker = _us_ticker(code, sym)
        closes = massive_closes or {}
        if ticker in closes:
            return closes[ticker], "massive", "USD"
        p = fetch_massive_prev_price(ticker)
        if p is not None:
            return p, "massive", "USD"
        p = fetch_stooq_us_price(ticker)
        if p is not None:
            return p, "stooq", "USD"

    if _is_a_share(code, sym):
        p, src = fetch_a_share_price(code)
        if p is not None:
            return p, src, "CNY"

    if _is_yahoo_crypto(sym):
        p = fetch_coingecko_usd_price(base)
        if p is not None:
            return p, "coingecko", "USD"

    if base in mids:
        return mids[base], "hyperliquid", "USD"

    return None, "none", "USD"


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


def list_cached_prices_payload() -> Dict[str, Any]:
    cache = load_price_cache()
    prices_raw = cache.get("prices") or {}
    updated_at = cache.get("updated_at")
    out: Dict[str, Any] = {}
    for code in list_research_codes():
        row = prices_raw.get(code)
        if not isinstance(row, dict) or row.get("price") is None:
            continue
        out[code] = {
            "price": row.get("price"),
            "currency": row.get("currency") or "USD",
            "price_updated_at": row.get("fetched_at") or updated_at,
            "quote_symbol": row.get("quote_symbol"),
            "source": row.get("source") or "cache",
        }
    return {
        "updated_at": updated_at,
        "prices": out,
        "count": len(out),
    }


def refresh_all_research_prices() -> Dict[str, Any]:
    """
    多源批量刷新（国内服务器友好）：
    1. Hyperliquid allMids（加密）
    2. Yahoo spark 批量（海外可用时）
    3. Massive grouped daily 一次拿全部美股昨收
    4. Massive prev 慢速补缺
    5. 东方财富 A 股 / CoinGecko 加密
    6. 失败保留旧缓存
    """
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    prev_cache = load_price_cache()
    prev_prices: Dict[str, Any] = prev_cache.get("prices") or {}

    codes = list_research_codes()
    quote_by_code = {code: get_quote_symbol(code) for code in codes}
    all_quote_syms = list(dict.fromkeys(quote_by_code.values()))

    us_tickers = [_us_ticker(c, quote_by_code[c]) for c in codes if _is_us_stock(c, quote_by_code[c])]
    us_tickers = list(dict.fromkeys(us_tickers))

    hl_mids = fetch_hyperliquid_all_mids()

    if _trust_env():
        logger.info("[研究卡片价格] 走系统代理: %s", _proxy_env_value())
    else:
        logger.info("[研究卡片价格] 未使用代理（如需走 7891 代理请 export HTTP_PROXY/HTTPS_PROXY）")

    yahoo_sess = _session()
    _warmup_yahoo_session(yahoo_sess)
    yahoo_quotes: Dict[str, Tuple[float, str]] = {}
    try:
        yahoo_quotes = fetch_yahoo_batch_quotes(all_quote_syms, sess=yahoo_sess)
    finally:
        yahoo_sess.close()
    logger.info("[研究卡片价格] Yahoo 批量: 请求 %s 只, 返回 %s 只", len(all_quote_syms), len(yahoo_quotes))

    massive_closes = fetch_massive_grouped_us_closes(us_tickers)

    prices: Dict[str, Any] = {}
    ok_count = 0
    stale_count = 0
    need_massive_prev: List[str] = []

    for code in codes:
        qsym = quote_by_code[code]
        price: Optional[float] = None
        source = "none"
        currency = "USD"
        base = qsym.replace("-USD", "").replace("-USDT", "")

        if base in _HL_COINS and base in hl_mids:
            price, source, currency = hl_mids[base], "hyperliquid", "USD"
        elif _is_yahoo_crypto(qsym) and base in hl_mids:
            price, source, currency = hl_mids[base], "hyperliquid", "USD"
        elif qsym in yahoo_quotes:
            price, currency = yahoo_quotes[qsym]
            source = "yahoo"
        elif _is_us_stock(code, qsym):
            ticker = _us_ticker(code, qsym)
            if ticker in massive_closes:
                price, source, currency = massive_closes[ticker], "massive", "USD"
            else:
                need_massive_prev.append(ticker)
        elif _is_a_share(code, qsym):
            p, src = fetch_a_share_price(code)
            if p is not None:
                price, source, currency = p, src, "CNY"
        elif _is_yahoo_crypto(qsym):
            p = fetch_coingecko_usd_price(base)
            if p is not None:
                price, source, currency = p, "coingecko", "USD"

        entry: Dict[str, Any] = {
            "quote_symbol": qsym,
            "currency": currency or "USD",
            "source": source,
            "fetched_at": now_str,
            "price": price,
        }

        if price is not None:
            ok_count += 1
            prices[code] = entry
        else:
            prices[code] = entry

    need_massive_prev = list(dict.fromkeys(need_massive_prev))
    if need_massive_prev:
        logger.info("[研究卡片价格] Massive prev 补缺 %s 只", len(need_massive_prev))
        prev_map = fetch_massive_prev_prices_slow(need_massive_prev)
        for code in codes:
            if prices[code].get("price") is not None:
                continue
            if not _is_us_stock(code, quote_by_code[code]):
                continue
            ticker = _us_ticker(code, quote_by_code[code])
            if ticker in prev_map:
                prices[code] = {
                    **prices[code],
                    "price": prev_map[ticker],
                    "source": "massive",
                    "currency": "USD",
                }
                ok_count += 1

    for code in codes:
        entry = prices[code]
        if entry.get("price") is not None:
            logger.info(
                "research_price %s (%s) [%s] => %s",
                code,
                quote_by_code[code],
                entry.get("source"),
                entry.get("price"),
            )
            continue

        old = prev_prices.get(code)
        if isinstance(old, dict) and old.get("price") is not None:
            prices[code] = {**old, "quote_symbol": quote_by_code[code], "stale": True}
            ok_count += 1
            stale_count += 1
            logger.warning(
                "research_price %s (%s) 拉价失败，保留缓存 %s [%s]",
                code,
                quote_by_code[code],
                old.get("price"),
                old.get("source"),
            )
        else:
            logger.warning(
                "research_price %s (%s) [%s] => None",
                code,
                quote_by_code[code],
                entry.get("source"),
            )

    payload = {"updated_at": now_str, "prices": prices}
    save_price_cache(payload)
    return {
        "ok": True,
        "updated_at": now_str,
        "count": len(prices),
        "ok_count": ok_count,
        "stale_count": stale_count,
    }


def refresh_research_prices_task() -> Dict[str, Any]:
    try:
        return refresh_all_research_prices()
    except Exception as exc:
        logger.exception("批量更新研究卡片价格失败: %s", exc)
        return {"ok": False, "error": str(exc)}
