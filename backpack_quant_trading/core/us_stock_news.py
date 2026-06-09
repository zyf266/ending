"""美股信号评分：拉取并整理相关新闻上下文。"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backpack_quant_trading.core.massive_klines import fetch_massive_news, normalize_us_ticker

logger = logging.getLogger(__name__)


def _news_row(
    *,
    time_s: str,
    title: str,
    source: str,
    url: str = "",
    summary: str = "",
    feed_key: str = "",
) -> Dict[str, Any]:
    text = (title or "").strip()
    if summary and summary not in text:
        text = f"{text} — {summary.strip()}" if text else summary.strip()
    return {
        "time": time_s,
        "source": source,
        "title": (title or "").strip(),
        "text": text[:500],
        "url": url or "",
        "feed_key": feed_key or source,
    }


def _fetch_yahoo_ticker_news(ticker: str, limit: int = 8) -> List[Dict[str, Any]]:
    try:
        from backpack_quant_trading.core.stock_news_feeds import fetch_yahoo_news_for_ticker

        rows, err = fetch_yahoo_news_for_ticker(ticker, timeout=12.0)
        if err:
            logger.debug("yahoo news %s: %s", ticker, err)
        out: List[Dict[str, Any]] = []
        t_up = ticker.upper()
        for it in rows or []:
            tickers = it.get("related_tickers") or []
            blob = f"{it.get('text') or ''} {' '.join(str(x) for x in tickers)}"
            if t_up not in blob.upper() and tickers:
                rel = [str(x).upper() for x in tickers]
                if t_up not in rel:
                    continue
            out.append(_news_row(
                time_s=str(it.get("time") or ""),
                title=str(it.get("text") or "").split("] ", 1)[-1][:200],
                source=str(it.get("feed") or "雅虎财经"),
                url=str(it.get("url") or ""),
                feed_key="yahoo",
            ))
            if len(out) >= limit:
                break
        if not out and rows:
            for it in rows[:limit]:
                out.append(_news_row(
                    time_s=str(it.get("time") or ""),
                    title=str(it.get("text") or "")[:200],
                    source=str(it.get("feed") or "雅虎财经"),
                    url=str(it.get("url") or ""),
                    feed_key="yahoo",
                ))
        return out
    except Exception as exc:
        logger.debug("yahoo news fetch failed %s: %s", ticker, exc)
        return []


def fetch_us_stock_news_context(
    symbol: str,
    *,
    max_items: int = 12,
) -> Dict[str, Any]:
    """合并 Massive/Polygon 与 Yahoo 个股新闻，供 DeepSeek 评分使用。"""
    ticker = normalize_us_ticker(symbol)
    merged: List[Dict[str, Any]] = []
    seen: set[str] = set()

    def _add(rows: List[Dict[str, Any]]) -> None:
        for row in rows:
            key = (row.get("title") or row.get("text") or "")[:120].lower()
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(row)

    _add(fetch_massive_news(ticker, limit=8))
    _add(_fetch_yahoo_ticker_news(ticker, limit=8))

    merged = merged[: max(1, int(max_items or 12))]
    summary_lines = []
    for i, row in enumerate(merged, 1):
        t = row.get("time") or "—"
        src = row.get("source") or "—"
        title = row.get("title") or row.get("text") or ""
        summary_lines.append(f"{i}. [{t}] ({src}) {title}")

    return {
        "ticker": ticker,
        "count": len(merged),
        "items": merged,
        "summary_text": "\n".join(summary_lines) if summary_lines else "（近期未拉到与该 ticker 直接相关的新闻）",
        "fetched_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    }


def _news_affects_ticker(item: Dict[str, Any], ticker: str) -> bool:
    """过滤与个股直接相关、可能影响股价的快讯。"""
    sym = (ticker or "").upper().strip()
    if not sym:
        return False
    if str(item.get("feed_key") or "").lower() == "massive":
        return True
    blob = f"{item.get('title') or ''} {item.get('text') or ''}".upper()
    if sym not in blob:
        return False
    # 标题含 ticker 或括号内 ticker 列表（Yahoo 常见格式）
    title = (item.get("title") or item.get("text") or "").upper()
    if sym in title:
        return True
    if re.search(rf"\({sym}(?:\s+[A-Z]{{1,5}})*\)", blob):
        return True
    if re.search(rf"\b{sym}\b", title):
        return True
    return sym in blob[:120]


def format_news_for_dingtalk(
    news_ctx: Optional[Dict[str, Any]],
    *,
    ticker: str = "",
    news_comment: str = "",
    max_items: int = 6,
) -> List[str]:
    """生成钉钉「消息面」Markdown 行。"""
    ctx = news_ctx or {}
    sym = (ticker or ctx.get("ticker") or "").upper().strip()
    items = [
        it for it in (ctx.get("items") or [])
        if isinstance(it, dict) and _news_affects_ticker(it, sym)
    ][: max(1, int(max_items or 6))]

    comment = (news_comment or "").strip()
    if len(comment) > 220:
        comment = comment[:217] + "…"

    if not comment and not items:
        return []

    lines: List[str] = []
    if comment:
        lines.append(f"> **AI 解读** {comment}")
    for it in items:
        t = str(it.get("time") or "—").strip()
        src = str(it.get("source") or "—").strip()
        title = str(it.get("title") or it.get("text") or "").strip()
        if len(title) > 100:
            title = title[:97] + "…"
        if title:
            lines.append(f"- **[{t}]** ({src}) {title}")
    return lines
