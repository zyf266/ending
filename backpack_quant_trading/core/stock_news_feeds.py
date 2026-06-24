"""
多源财经快讯：金十、同花顺、东方财富、新浪、富途、雅虎财经等（免费公开接口，仅供个人研究）。
雅虎默认直连（与本地一致，走 query1 Search）；仅直连失败且配置了 HTTP_PROXY 时才自动改用代理。
国内云可设 STOCK_NEWS_FORCE_SYSTEM_PROXY=1 跳过直连；金十/钉钉等仍默认不走代理。
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional, Set, Tuple

import requests

from backpack_quant_trading.core.stock_news_keyword_i18n import (
    is_watch_all_us_stocks,
    watch_names_to_yahoo_queries,
)

logger = logging.getLogger(__name__)

ALL_SOURCE_KEYS: Tuple[str, ...] = ("jin10", "ths", "eastmoney", "sina", "futu", "yahoo")
SOURCE_LABELS: Dict[str, str] = {
    "jin10": "金十数据",
    "ths": "同花顺",
    "eastmoney": "东方财富",
    "sina": "新浪财经",
    "futu": "富途牛牛",
    "yahoo": "雅虎财经",
}

YAHOO_SEARCH_BASES: Tuple[str, ...] = (
    "https://query1.finance.yahoo.com/v1/finance/search",
    "https://query2.finance.yahoo.com/v1/finance/search",
)
DEFAULT_YAHOO_NEWS_QUERY = os.environ.get("YAHOO_NEWS_SEARCH_Q") or "finance"
_YAHOO_WARMUP_URL = "https://finance.yahoo.com/"
_YAHOO_NCP_URL = "https://finance.yahoo.com/xhr/ncp?queryRef=latestNews&serviceKey=ncp_fin"
_YAHOO_RSS_HEADLINE = "https://feeds.finance.yahoo.com/rss/2.0/headline"
_YAHOO_RSS_INDEX = "https://finance.yahoo.com/news/rssindex"
_YAHOO_TICKER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9.^=-]{0,11}$")

JIN10_FLASH_URL = "https://flash-api.jin10.com/get_flash_list"
DEFAULT_JIN10_APP_ID = os.environ.get("JIN10_X_APP_ID") or "fiXF2nOnDycGutVA"

_HTML_RE = re.compile(r"<[^>]+>")


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
    return os.environ.get("STOCK_NEWS_FORCE_SYSTEM_PROXY", "").lower() in ("1", "true", "yes")


def _yahoo_proxy_disabled() -> bool:
    return os.environ.get("STOCK_NEWS_DISABLE_PROXY", "").lower() in ("1", "true", "yes")


def _yahoo_force_proxy() -> bool:
    if os.environ.get("STOCK_NEWS_FORCE_SYSTEM_PROXY", "").lower() in ("1", "true", "yes"):
        return True
    # 云服务器直连雅虎必 403，跳过直连避免每 30s 白打一轮
    return os.environ.get("TRADING_SERVER", "").strip().lower() in ("1", "true", "yes")


def _session() -> requests.Session:
    s = requests.Session()
    s.trust_env = _trust_env()
    return s


def _yahoo_session(*, use_proxy: bool) -> requests.Session:
    s = requests.Session()
    s.trust_env = use_proxy
    return s


def _yahoo_headers() -> Dict[str, str]:
    return {
        **_ua_headers(),
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://finance.yahoo.com/",
        "Origin": "https://finance.yahoo.com",
    }


def _yahoo_warmup(sess: requests.Session, *, use_proxy: bool) -> None:
    try:
        _yahoo_request(
            sess, "GET", _YAHOO_WARMUP_URL,
            headers=_yahoo_headers(), timeout=10, use_proxy=use_proxy,
        )
    except Exception:
        pass


def _yahoo_timeout(timeout: float, *, use_proxy: bool) -> Tuple[float, float]:
    t = max(5.0, float(timeout or 12.0))
    if use_proxy:
        return (min(5.0, t * 0.25), min(t, 15.0))
    return (min(8.0, t * 0.35), t)


def _yahoo_proxies_for(use_proxy: bool) -> Optional[Dict[str, str]]:
    if not use_proxy or _yahoo_proxy_disabled():
        return None
    p = _proxy_env_value()
    if not p:
        return None
    return {"http": p, "https": p}


def _yahoo_request(
    sess: requests.Session,
    method: str,
    url: str,
    *,
    timeout: float,
    use_proxy: bool = False,
    **kwargs: Any,
) -> requests.Response:
    kw = dict(kwargs)
    proxies = _yahoo_proxies_for(use_proxy)
    if proxies:
        kw["proxies"] = proxies
    kw.setdefault("timeout", _yahoo_timeout(timeout, use_proxy=use_proxy))
    return sess.request(method, url, **kw)


def _parse_pub_ts(raw: Any) -> Optional[int]:
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        pass
    s = str(raw).strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return int(datetime.fromisoformat(s).timestamp())
    except (TypeError, ValueError, OSError):
        pass
    try:
        return int(parsedate_to_datetime(s).timestamp())
    except (TypeError, ValueError, OSError):
        return None


def _yahoo_ticker_symbols(queries: List[str]) -> List[str]:
    out: List[str] = []
    seen: Set[str] = set()
    for raw in queries:
        s = str(raw).strip()
        if not s or s.casefold() == "finance":
            continue
        if not _YAHOO_TICKER_RE.fullmatch(s):
            continue
        key = s.upper() if s.isalpha() and len(s) <= 6 else s
        kf = key.casefold()
        if kf in seen:
            continue
        seen.add(kf)
        out.append(key)
    return out[:8]


def _strip_html(s: str) -> str:
    if not s:
        return ""
    t = _HTML_RE.sub("", str(s))
    return re.sub(r"\s+", " ", t).strip()


def _ua_headers() -> Dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }


def _stable_dedupe_id(feed_key: str, time_s: str, text: str) -> str:
    raw = f"{feed_key}|{time_s}|{text[:400]}"
    h = hashlib.md5(raw.encode("utf-8", errors="ignore")).hexdigest()[:20]
    return f"{feed_key}:{h}"


def normalize_enabled_sources(cfg: Dict[str, Any]) -> List[str]:
    raw = cfg.get("news_sources")
    if not isinstance(raw, list) or not raw:
        return list(ALL_SOURCE_KEYS)
    out: List[str] = []
    for x in raw:
        k = str(x).strip().lower()
        if k in ALL_SOURCE_KEYS and k not in out:
            out.append(k)
    return out or list(ALL_SOURCE_KEYS)


def fetch_jin10_flash_rows(
    x_app_id: str,
    channel: str = "-8200",
    vip: str = "1",
    timeout: float = 15.0,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    headers = {
        **_ua_headers(),
        "x-app-id": x_app_id,
        "x-version": "1.0.0",
        "Referer": "https://www.jin10.com/",
        "Origin": "https://www.jin10.com",
        "Accept": "application/json, text/plain, */*",
    }
    params = {"channel": channel, "vip": vip}
    try:
        with _session() as sess:
            r = sess.get(JIN10_FLASH_URL, params=params, headers=headers, timeout=timeout)
        if r.status_code != 200:
            return [], f"HTTP {r.status_code}"
        body = r.json()
    except Exception as exc:
        return [], str(exc)
    if not isinstance(body, dict):
        return [], "响应非 JSON 对象"
    if body.get("status") != 200:
        return [], str(body.get("message") or body)
    data = body.get("data")
    if not isinstance(data, list):
        return [], "data 非列表"
    return data, None


def jin10_row_to_unified(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(row, dict):
        return None
    nid = str(row.get("id") or "").strip()
    if not nid:
        return None
    d = row.get("data")
    title, content, src = "", "", ""
    if isinstance(d, dict):
        title = str(d.get("title") or "")
        content = str(d.get("content") or "")
        src = str(d.get("source") or "")
    full = _strip_html(f"{title} {content} {src}".strip())
    if not full:
        return None
    important = row.get("important")
    try:
        imp_num = int(important) if important is not None else 0
    except (TypeError, ValueError):
        imp_num = 0
    return {
        "dedupe_id": f"jin10:{nid}",
        "feed_key": "jin10",
        "feed": SOURCE_LABELS["jin10"],
        "time": str(row.get("time") or ""),
        "text": full,
        "important": imp_num,
        "url": "",
    }


def _fetch_ths(timeout: float) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    url = "https://news.10jqka.com.cn/tapp/news/push/stock"
    params = {"page": "1", "tag": "", "track": "website"}
    try:
        with _session() as sess:
            r = sess.get(url, params=params, headers=_ua_headers(), timeout=timeout)
        r.raise_for_status()
        data_json = r.json()
        lst = data_json.get("data", {}).get("list") or []
    except Exception as exc:
        return [], str(exc)
    out: List[Dict[str, Any]] = []
    for it in lst[:80]:
        if not isinstance(it, dict):
            continue
        title = _strip_html(str(it.get("title") or ""))
        digest = _strip_html(str(it.get("digest") or ""))
        rtime = it.get("rtime")
        try:
            ts = int(rtime)
            tm = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError, OSError):
            tm = str(rtime or "")
        text = f"{title} {digest}".strip() or digest or title
        if not text:
            continue
        url_s = str(it.get("url") or "")
        did = _stable_dedupe_id("ths", tm, text)
        row: Dict[str, Any] = {
            "dedupe_id": did,
            "feed_key": "ths",
            "feed": SOURCE_LABELS["ths"],
            "time": tm,
            "text": text,
            "important": 0,
            "url": url_s,
        }
        try:
            row["published_ts"] = int(rtime)
        except (TypeError, ValueError):
            pass
        out.append(row)
    return out, None


def _fetch_eastmoney(timeout: float) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    url = "https://np-weblist.eastmoney.com/comm/web/getFastNewsList"
    params = {
        "client": "web",
        "biz": "web_724",
        "fastColumn": "102",
        "sortEnd": "",
        "pageSize": "80",
        "req_trace": "1710315450384",
    }
    try:
        with _session() as sess:
            r = sess.get(url, params=params, headers=_ua_headers(), timeout=timeout)
        r.raise_for_status()
        data_json = r.json()
        lst = data_json.get("data", {}).get("fastNewsList") or []
    except Exception as exc:
        return [], str(exc)
    out: List[Dict[str, Any]] = []
    for it in lst:
        if not isinstance(it, dict):
            continue
        title = _strip_html(str(it.get("title") or ""))
        summary = _strip_html(str(it.get("summary") or ""))
        tm = str(it.get("showTime") or "")
        code = str(it.get("code") or "")
        link = f"https://finance.eastmoney.com/a/{code}.html" if code else ""
        text = f"{title} {summary}".strip() or summary or title
        if not text:
            continue
        did = _stable_dedupe_id("eastmoney", tm, text)
        out.append(
            {
                "dedupe_id": did,
                "feed_key": "eastmoney",
                "feed": SOURCE_LABELS["eastmoney"],
                "time": tm,
                "text": text,
                "important": 0,
                "url": link,
            }
        )
    return out, None


def _fetch_sina(timeout: float) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    url = "https://zhibo.sina.com.cn/api/zhibo/feed"
    params = {
        "page": "1",
        "page_size": "30",
        "zhibo_id": "152",
        "tag_id": "0",
        "dire": "f",
        "dpc": "1",
        "pagesize": "30",
        "type": "1",
    }
    try:
        with _session() as sess:
            r = sess.get(url, params=params, headers=_ua_headers(), timeout=timeout)
        r.raise_for_status()
        data_json = r.json()
        feed_list = data_json.get("result", {}).get("data", {}).get("feed", {}).get("list") or []
    except Exception as exc:
        return [], str(exc)
    out: List[Dict[str, Any]] = []
    for it in feed_list:
        if not isinstance(it, dict):
            continue
        tm = str(it.get("create_time") or "")
        rich = _strip_html(str(it.get("rich_text") or ""))
        if not rich:
            continue
        did = _stable_dedupe_id("sina", tm, rich)
        out.append(
            {
                "dedupe_id": did,
                "feed_key": "sina",
                "feed": SOURCE_LABELS["sina"],
                "time": tm,
                "text": rich,
                "important": 0,
                "url": "",
            }
        )
    return out, None


def _fetch_futu(timeout: float) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    url = "https://news.futunn.com/news-site-api/main/get-flash-list"
    params = {"pageSize": "40"}
    h = {
        **_ua_headers(),
    }
    try:
        with _session() as sess:
            r = sess.get(url, params=params, headers=h, timeout=timeout)
        r.raise_for_status()
        data_json = r.json()
        news = data_json.get("data", {}).get("data", {}).get("news") or []
    except Exception as exc:
        return [], str(exc)
    out: List[Dict[str, Any]] = []
    for it in news:
        if not isinstance(it, dict):
            continue
        title = _strip_html(str(it.get("title") or ""))
        content = _strip_html(str(it.get("content") or ""))
        tm_raw = it.get("time")
        try:
            tm = datetime.fromtimestamp(int(tm_raw)).strftime("%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError, OSError):
            tm = str(tm_raw or "")
        text = f"{title} {content}".strip() or content or title
        if not text:
            continue
        link = str(it.get("detailUrl") or "")
        did = _stable_dedupe_id("futu", tm, text)
        out.append(
            {
                "dedupe_id": did,
                "feed_key": "futu",
                "feed": SOURCE_LABELS["futu"],
                "time": tm,
                "text": text,
                "important": 0,
                "url": link,
            }
        )
    return out, None


def _normalize_yahoo_search_queries(search_queries: Optional[List[str]]) -> List[str]:
    """去重后的 Yahoo 搜索词；无自选时用默认 finance。"""
    out: List[str] = []
    seen: Set[str] = set()
    if search_queries:
        for raw in search_queries:
            s = str(raw).strip()
            if not s or len(s) > 40:
                continue
            k = s.casefold()
            if k in seen:
                continue
            seen.add(k)
            out.append(s)
    if not out:
        fallback = (DEFAULT_YAHOO_NEWS_QUERY or "finance").strip() or "finance"
        out.append(fallback)
    return out[:8]


def _yahoo_ncp_fetch(
    symbols: List[str],
    timeout: float,
    *,
    sess: requests.Session,
    use_proxy: bool,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    if not symbols:
        return [], "无 ticker"
    body = {"serviceConfig": {"snippetCount": 50, "s": symbols}}
    h = {**_yahoo_headers(), "Content-Type": "application/json"}
    try:
        r = _yahoo_request(
            sess, "POST", _YAHOO_NCP_URL, json=body, headers=h,
            timeout=timeout, use_proxy=use_proxy,
        )
        if r.status_code != 200:
            return [], f"NCP HTTP {r.status_code}"
        stream = (
            (((r.json().get("data") or {}).get("tickerStream") or {}).get("stream")) or []
        )
        rows: List[Dict[str, Any]] = []
        for item in stream:
            if not isinstance(item, dict) or item.get("ad"):
                continue
            content = item.get("content") or {}
            title = _strip_html(str(content.get("title") or ""))
            if not title:
                continue
            provider = str((content.get("provider") or {}).get("displayName") or "")
            link = str((content.get("canonicalUrl") or {}).get("url") or "")
            pub_ts = _parse_pub_ts(content.get("pubDate"))
            rows.append(
                {
                    "title": title,
                    "publisher": provider,
                    "link": link,
                    "uuid": str(item.get("id") or ""),
                    "providerPublishTime": pub_ts,
                    "relatedTickers": list(symbols),
                }
            )
        if rows:
            return rows, None
        return [], "NCP 无新闻"
    except Exception as exc:
        return [], f"NCP {exc}"


def _yahoo_rss_parse(xml_bytes: bytes) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []
    for item in root.findall(".//item"):
        title = _strip_html(item.findtext("title") or "")
        if not title:
            continue
        link = item.findtext("link") or ""
        pub_ts = _parse_pub_ts(item.findtext("pubDate") or "")
        guid = item.findtext("guid") or ""
        rows.append(
            {
                "title": title,
                "publisher": "",
                "link": link,
                "uuid": guid,
                "providerPublishTime": pub_ts,
                "relatedTickers": [],
            }
        )
    return rows


def _yahoo_rss_fetch(
    symbols: Optional[List[str]],
    timeout: float,
    *,
    sess: requests.Session,
    use_proxy: bool,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    h = {**_yahoo_headers(), "Accept": "application/rss+xml, application/xml, text/xml, */*"}
    last_err: Optional[str] = None
    merged: List[Dict[str, Any]] = []
    if symbols:
        for sym in symbols[:4]:
            try:
                r = _yahoo_request(
                    sess,
                    "GET",
                    _YAHOO_RSS_HEADLINE,
                    params={"s": sym, "region": "US", "lang": "en-US"},
                    headers=h,
                    timeout=timeout,
                    use_proxy=use_proxy,
                )
                if r.status_code == 429:
                    last_err = "RSS HTTP 429"
                    break
                if r.status_code != 200:
                    last_err = f"RSS HTTP {r.status_code}"
                    continue
                chunk = _yahoo_rss_parse(r.content)
                for row in chunk:
                    row["relatedTickers"] = [sym]
                merged.extend(chunk)
            except Exception as exc:
                last_err = f"RSS {exc}"
        if merged:
            return merged, None
        return [], last_err or "RSS 无条目"
    try:
        r = _yahoo_request(
            sess, "GET", _YAHOO_RSS_INDEX, headers=h,
            timeout=timeout, use_proxy=use_proxy,
        )
        if r.status_code != 200:
            return [], f"RSS HTTP {r.status_code}"
        rows = _yahoo_rss_parse(r.content)
        if rows:
            return rows, None
        return [], "RSS 无条目"
    except Exception as exc:
        return [], f"RSS {exc}"


def _yahoo_search_fetch(
    q: str,
    timeout: float,
    *,
    sess: requests.Session,
    use_proxy: bool,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """v1 finance/search（本地直连通常走这条即可）。"""
    params = {"q": q, "quotesCount": "0", "newsCount": "50", "enableFuzzyQuery": "false"}
    h = _yahoo_headers()
    last_err: Optional[str] = None
    for base in YAHOO_SEARCH_BASES:
        try:
            r = _yahoo_request(
                sess, "GET", base, params=params, headers=h,
                timeout=timeout, use_proxy=use_proxy,
            )
            if r.status_code == 403:
                last_err = "Search HTTP 403"
                continue
            if r.status_code != 200:
                last_err = f"Search HTTP {r.status_code}"
                continue
            chunk = r.json().get("news")
            if isinstance(chunk, list) and chunk:
                return chunk, None
            last_err = "news 为空"
        except Exception as exc:
            last_err = str(exc)
    return [], last_err


def _yahoo_rows_to_unified(news: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for it in news[:80]:
        if not isinstance(it, dict):
            continue
        title = _strip_html(str(it.get("title") or ""))
        if not title:
            continue
        publisher = _strip_html(str(it.get("publisher") or ""))
        tickers = it.get("relatedTickers") or []
        ticker_s = ""
        if isinstance(tickers, list) and tickers:
            ticker_s = " ".join(str(t).strip() for t in tickers[:6] if str(t).strip())
        text = title
        if publisher:
            text = f"[{publisher}] {title}"
        if ticker_s:
            text = f"{text} ({ticker_s})"
        ts_raw = it.get("providerPublishTime")
        pub_ts: Optional[int] = None
        try:
            pub_ts = int(ts_raw)
            tm = datetime.fromtimestamp(pub_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError, OSError):
            tm = str(ts_raw or "")
        link = str(it.get("link") or "")
        uid = str(it.get("uuid") or "").strip()
        did = f"yahoo:{uid}" if uid else _stable_dedupe_id("yahoo", tm, text)
        row: Dict[str, Any] = {
            "dedupe_id": did,
            "feed_key": "yahoo",
            "feed": SOURCE_LABELS["yahoo"],
            "time": tm,
            "text": text,
            "important": 0,
            "url": link,
            "related_tickers": tickers if isinstance(tickers, list) else [],
        }
        if pub_ts is not None:
            row["published_ts"] = pub_ts
        out.append(row)
    return out


def fetch_yahoo_news_for_ticker(
    ticker: str,
    timeout: float = 12.0,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """按 ticker 搜索 Yahoo 财经新闻（供美股 AI 评分等）。"""
    q = str(ticker or "").upper().strip()
    if not q:
        return [], "ticker 为空"
    return _fetch_yahoo(timeout, search_queries=[q])


def _yahoo_merge_rows(
    merged: List[Dict[str, Any]],
    seen_ids: Set[str],
    news: List[Dict[str, Any]],
) -> None:
    for it in _yahoo_rows_to_unified(news):
        did = str(it.get("dedupe_id") or "")
        if did and did not in seen_ids:
            seen_ids.add(did)
            merged.append(it)


def _yahoo_fetch_attempt(
    queries: List[str],
    tickers: List[str],
    timeout: float,
    *,
    use_proxy: bool,
    search_first: bool,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """单次拉取：search_first=True 时与本地一致（Search 优先）。"""
    merged: List[Dict[str, Any]] = []
    seen_ids: Set[str] = set()
    errors: List[str] = []
    sess = _yahoo_session(use_proxy=use_proxy)
    _yahoo_warmup(sess, use_proxy=use_proxy)

    if search_first:
        for q in queries:
            news, err = _yahoo_search_fetch(q, timeout, sess=sess, use_proxy=use_proxy)
            if err:
                errors.append(f"{q}: {err}")
                continue
            _yahoo_merge_rows(merged, seen_ids, news)
        if merged:
            return merged, errors

    if tickers:
        news, err = _yahoo_ncp_fetch(tickers, timeout, sess=sess, use_proxy=use_proxy)
        if news:
            _yahoo_merge_rows(merged, seen_ids, news)
        elif err:
            errors.append(err)

    if len(merged) < 5:
        rss_syms = tickers if tickers else None
        news, err = _yahoo_rss_fetch(
            rss_syms, timeout, sess=sess, use_proxy=use_proxy,
        )
        if news:
            _yahoo_merge_rows(merged, seen_ids, news)
        elif err and not merged:
            errors.append(err)

    if not merged and not search_first:
        for q in queries:
            news, err = _yahoo_search_fetch(q, timeout, sess=sess, use_proxy=use_proxy)
            if err:
                errors.append(f"{q}: {err}")
                continue
            _yahoo_merge_rows(merged, seen_ids, news)

    return merged, errors


def _fetch_yahoo(
    timeout: float,
    search_queries: Optional[List[str]] = None,
    *,
    broad_us: bool = False,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """雅虎：先直连 Search（本地路径）→ 失败再用代理 NCP/RSS。

    broad_us=True（全美股监控）时优先 RSS 宽表，避免搜「全美股」或 finance 少量结果即返回。
    """
    if broad_us:
        queries: List[str] = []
        tickers: List[str] = []
        search_first = False
    else:
        queries = _normalize_yahoo_search_queries(search_queries)
        tickers = _yahoo_ticker_symbols(queries)
        search_first = True
    proxy = _proxy_env_value()
    force_proxy = _yahoo_force_proxy() and not _yahoo_proxy_disabled()
    errors: List[str] = []

    if not force_proxy:
        merged, errors = _yahoo_fetch_attempt(
            queries, tickers, timeout, use_proxy=False, search_first=search_first,
        )
        if merged:
            logger.debug("[雅虎财经] 直连 Search 获取 %s 条", len(merged))
            return merged, None

    if not proxy:
        if force_proxy:
            return [], "已设 STOCK_NEWS_FORCE_SYSTEM_PROXY 但未配置 HTTP_PROXY"
        if errors:
            return [], "; ".join(errors[:3])
        return [], "雅虎无数据"

    if force_proxy:
        logger.info("[雅虎财经] 强制走代理: %s", proxy)
    else:
        logger.info("[雅虎财经] 直连失败，改用代理: %s", proxy)
    merged, errors = _yahoo_fetch_attempt(
        queries, tickers, timeout, use_proxy=True, search_first=False,
    )
    if merged:
        logger.info("[雅虎财经] 代理模式获取 %s 条", len(merged))
        return merged, None
    if errors:
        return [], "; ".join(errors[:3])
    return [], "雅虎无数据"


def fetch_unified_for_source(
    key: str,
    *,
    jin10_x_app_id: str,
    timeout: float = 12.0,
    yahoo_search_queries: Optional[List[str]] = None,
    yahoo_broad_us: bool = False,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    if key == "jin10":
        rows, err = fetch_jin10_flash_rows(jin10_x_app_id, timeout=timeout)
        if err:
            return [], err
        items: List[Dict[str, Any]] = []
        for row in rows:
            u = jin10_row_to_unified(row)
            if u:
                items.append(u)
        return items, None
    if key == "ths":
        return _fetch_ths(timeout)
    if key == "eastmoney":
        return _fetch_eastmoney(timeout)
    if key == "sina":
        return _fetch_sina(timeout)
    if key == "futu":
        return _fetch_futu(timeout)
    if key == "yahoo":
        return _fetch_yahoo(
            timeout,
            search_queries=yahoo_search_queries,
            broad_us=yahoo_broad_us,
        )
    return [], "未知数据源"


def fetch_unified_news_items(
    cfg: Dict[str, Any],
    *,
    jin10_x_app_id: Optional[str] = None,
    timeout_per_source: float = 12.0,
) -> Tuple[List[Dict[str, Any]], Dict[str, Optional[str]]]:
    """
    按配置拉取并合并多源快讯（统一结构）。
    返回 (items, errors_by_source)，errors 中 None 表示该源成功（可能 0 条）。
    """
    enabled = normalize_enabled_sources(cfg)
    x_app = (jin10_x_app_id or str(cfg.get("jin10_x_app_id") or DEFAULT_JIN10_APP_ID)).strip()
    watch_raw = cfg.get("watch_names") or []
    if isinstance(watch_raw, str):
        watch_raw = [watch_raw]
    yahoo_broad_us = is_watch_all_us_stocks(watch_raw)
    yahoo_q = watch_names_to_yahoo_queries(watch_raw) if "yahoo" in enabled else None
    all_items: List[Dict[str, Any]] = []
    errors: Dict[str, Optional[str]] = {}
    for key in enabled:
        items, err = fetch_unified_for_source(
            key,
            jin10_x_app_id=x_app,
            timeout=timeout_per_source,
            yahoo_search_queries=yahoo_q,
            yahoo_broad_us=yahoo_broad_us,
        )
        errors[key] = err
        if items:
            all_items.extend(items)
        elif err:
            logger.warning("stock_news_feeds %s: %s", key, err)
    return all_items, errors


def probe_sources_status(cfg: Dict[str, Any], *, timeout: float = 8.0) -> Dict[str, Any]:
    """各源连通性与条数，供前端展示。"""
    enabled = normalize_enabled_sources(cfg)
    x_app = str(cfg.get("jin10_x_app_id") or DEFAULT_JIN10_APP_ID).strip()
    out: Dict[str, Any] = {}
    for key in ALL_SOURCE_KEYS:
        active = key in enabled
        if not active:
            out[key] = {"enabled": False, "ok": None, "count": 0, "error": None}
            continue
        yahoo_q = None
        if key == "yahoo":
            wr = cfg.get("watch_names") or []
            if isinstance(wr, str):
                wr = [wr]
            yahoo_q = watch_names_to_yahoo_queries(wr) or None
        yahoo_timeout = max(timeout, 18.0) if key == "yahoo" else timeout
        items, err = fetch_unified_for_source(
            key, jin10_x_app_id=x_app, timeout=yahoo_timeout, yahoo_search_queries=yahoo_q
        )
        probe_extra: Dict[str, Any] = {}
        if key == "yahoo":
            probe_extra["search_queries"] = _normalize_yahoo_search_queries(yahoo_q)
        out[key] = {
            "enabled": True,
            "ok": err is None,
            "count": len(items),
            "error": err,
            "label": SOURCE_LABELS.get(key, key),
            **probe_extra,
        }
    return {"sources": out, "enabled_order": enabled}


def build_feeds_preview(
    cfg: Dict[str, Any],
    *,
    per_source: int = 12,
    timeout: float = 10.0,
) -> Dict[str, Any]:
    """聚合预览：各源状态 + 每个源截取若干条（含来源字段）。"""
    status = probe_sources_status(cfg, timeout=timeout)
    x_app = str(cfg.get("jin10_x_app_id") or DEFAULT_JIN10_APP_ID).strip()
    rows: List[Dict[str, Any]] = []
    enabled = normalize_enabled_sources(cfg)
    wr = cfg.get("watch_names") or []
    if isinstance(wr, str):
        wr = [wr]
    yahoo_q = watch_names_to_yahoo_queries(wr)
    for key in enabled:
        items, err = fetch_unified_for_source(
            key,
            jin10_x_app_id=x_app,
            timeout=timeout,
            yahoo_search_queries=yahoo_q if key == "yahoo" else None,
        )
        if err:
            continue
        for it in items[: max(1, min(per_source, 50))]:
            rows.append(
                {
                    "feed": it["feed"],
                    "feed_key": it["feed_key"],
                    "time": it["time"],
                    "text": it["text"][:500] + ("…" if len(it["text"]) > 500 else ""),
                    "url": it.get("url") or "",
                    "important": it.get("important") or 0,
                }
            )
    return {
        "sources": status["sources"],
        "enabled_order": enabled,
        "rows": rows,
        "per_source_cap": per_source,
    }


def _normalize_title_fingerprint(text: str) -> str:
    return _normalize_for_similarity(text)[:240]


def _normalize_for_similarity(text: str) -> str:
    """多源转载时正文格式不同，归一化后用于相似比对。"""
    t = _strip_html(str(text or ""))
    t = re.sub(r"【[^】]*】", " ", t)
    t = re.sub(r"\[[^\]]*\]", " ", t)
    if "(" in t and ")" in t:
        t = re.sub(r"\([^)]{0,40}\)", " ", t)
    parts = re.split(r"[。！？；\n]+", t)
    seen: Set[str] = set()
    chunks: List[str] = []
    for p in parts:
        p = re.sub(r"\s+", "", p.strip())
        if len(p) < 4:
            continue
        key = p.casefold()
        if key in seen:
            continue
        seen.add(key)
        chunks.append(p)
    t = "".join(chunks)
    t = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9%]+", "", t)
    return t.casefold()


def texts_are_similar(a: str, b: str, threshold: float = 0.72) -> bool:
    na = _normalize_for_similarity(a)
    nb = _normalize_for_similarity(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    short, long = (na, nb) if len(na) <= len(nb) else (nb, na)
    if len(short) >= 18 and short in long:
        return True
    if len(na) >= 12 and len(nb) >= 12:
        return SequenceMatcher(None, na, nb).ratio() >= threshold
    return False


def item_similarity_norm(item: Dict[str, Any]) -> str:
    return _normalize_for_similarity(str(item.get("text") or ""))


def is_similar_to_items(
    item: Dict[str, Any],
    others: List[Dict[str, Any]],
    *,
    threshold: float = 0.72,
) -> bool:
    text = str(item.get("text") or "")
    for other in others:
        if texts_are_similar(text, str(other.get("text") or ""), threshold):
            return True
    return False


def is_similar_to_norms(
    item: Dict[str, Any],
    norms: List[str],
    *,
    threshold: float = 0.72,
) -> bool:
    text = str(item.get("text") or "")
    for n in norms:
        if texts_are_similar(text, n, threshold):
            return True
    return False


def item_dedupe_keys(item: Dict[str, Any]) -> List[str]:
    """同一新闻可能 uuid/链接略有差异，用多键去重。"""
    keys: List[str] = []
    did = str(item.get("dedupe_id") or "").strip()
    if did:
        keys.append(did)
        if did.startswith("jin10:"):
            legacy = did.split(":", 1)[1]
            if legacy:
                keys.append(legacy)
    url = str(item.get("url") or "").strip()
    if url:
        url_base = url.split("?", 1)[0].casefold()
        h = hashlib.md5(url_base.encode("utf-8", errors="ignore")).hexdigest()[:20]
        keys.append(f"url:{h}")
    title_fp = _normalize_title_fingerprint(str(item.get("text") or ""))
    if len(title_fp) >= 12:
        th = hashlib.md5(title_fp.encode("utf-8", errors="ignore")).hexdigest()[:20]
        keys.append(f"title:{th}")
        keys.append(f"sim:{th}")
    pub = item.get("published_ts")
    if title_fp and pub is not None:
        try:
            keys.append(f"pubtitle:{int(pub)}:{hashlib.md5(title_fp.encode()).hexdigest()[:16]}")
        except (TypeError, ValueError):
            pass
    seen: Set[str] = set()
    out: List[str] = []
    for k in keys:
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out


def item_already_pushed(pushed: Set[str], item: Dict[str, Any]) -> bool:
    return any(k in pushed for k in item_dedupe_keys(item))


def mark_item_pushed(pushed: Set[str], item: Dict[str, Any]) -> None:
    for k in item_dedupe_keys(item):
        pushed.add(k)
