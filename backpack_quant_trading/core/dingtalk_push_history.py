"""记录发往钉钉群的推送内容，供 AI 选股卡片展示「相关新闻」。"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_DATA_DIR = Path(__file__).resolve().parents[1] / "data"
HISTORY_PATH = _DATA_DIR / "dingtalk_push_history.json"
_MAX_ITEMS = 500


def _load() -> List[Dict[str, Any]]:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not HISTORY_PATH.is_file():
        return []
    try:
        raw = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            return [x for x in raw if isinstance(x, dict)]
    except Exception:
        pass
    return []


def _save(items: List[Dict[str, Any]]) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    trimmed = items[-_MAX_ITEMS:]
    HISTORY_PATH.write_text(json.dumps(trimmed, ensure_ascii=False, indent=2), encoding="utf-8")


def record_stock_news_push(item: Dict[str, Any]) -> Dict[str, Any]:
    entry = {
        "id": str(item.get("dedupe_id") or ""),
        "kind": "stock_news",
        "feed": str(item.get("feed") or ""),
        "feed_key": str(item.get("feed_key") or ""),
        "time": str(item.get("time") or ""),
        "text": str(item.get("text") or ""),
        "url": str(item.get("url") or ""),
        "pushed_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    }
    items = _load()
    if entry["id"] and any(x.get("id") == entry["id"] for x in items):
        return entry
    items.append(entry)
    _save(items)
    return entry


def record_polymarket_push(rule: Dict[str, Any], quote: Dict[str, Any]) -> Dict[str, Any]:
    sym = rule.get("symbol")
    price = rule.get("target_price")
    pct = quote.get("yes_probability_pct")
    text = (
        f"Polymarket · {sym} ${price:g} · Yes 概率 {pct}% "
        f"（低于阈值 {rule.get('threshold_pct')}% 提醒）"
    )
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    entry = {
        "id": f"polymarket:{rule.get('id')}:{entry_ts()}",
        "kind": "polymarket",
        "feed": "Polymarket",
        "feed_key": "polymarket",
        "time": now,
        "text": text,
        "url": "",
        "pushed_at": now,
    }
    items = _load()
    items.append(entry)
    _save(items)
    return entry


def entry_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def record_raw_message(
    *,
    text: str,
    feed: str = "钉钉群",
    kind: str = "manual",
    url: str = "",
) -> Dict[str, Any]:
    """手动或回调写入一条群消息。"""
    entry = {
        "id": f"{kind}:{entry_ts()}",
        "kind": kind,
        "feed": feed,
        "feed_key": kind,
        "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "text": (text or "").strip(),
        "url": url,
        "pushed_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    }
    items = _load()
    items.append(entry)
    _save(items)
    return entry


def parse_dingtalk_body(body: str) -> Optional[Dict[str, str]]:
    """从钉钉正文反解析自选快讯字段。"""
    s = body or ""
    m_feed = re.search(r"【提醒】【自选快讯】([^\n]+)", s)
    m_time = re.search(r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})", s)
    m_url = re.search(r"链接:\s*(\S+)", s)
    lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
    text = ""
    for ln in lines:
        if ln.startswith("【") or re.match(r"\d{4}-\d{2}-\d{2}", ln) or ln.startswith("链接:") or ln.startswith("id:"):
            continue
        text = ln
        break
    if not text and len(lines) >= 3:
        text = lines[2]
    return {
        "feed": (m_feed.group(1) if m_feed else "钉钉"),
        "time": (m_time.group(1) if m_time else ""),
        "text": text,
        "url": (m_url.group(1) if m_url else ""),
    }


def list_history(
    *,
    limit: int = 50,
    symbol: Optional[str] = None,
    kinds: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    items = list(reversed(_load()))
    if kinds:
        allow = {k.lower() for k in kinds}
        items = [x for x in items if str(x.get("kind") or "").lower() in allow]
    if symbol:
        sym = symbol.upper().strip()
        aliases = _symbol_aliases(sym)
        items = [x for x in items if _matches_symbol(x, aliases)]
    n = max(1, min(int(limit or 50), 200))
    return items[:n]


def _symbol_aliases(sym: str) -> List[str]:
    from backpack_quant_trading.core.research_card_feeds import symbol_aliases

    return symbol_aliases(sym)


def _matches_symbol(item: Dict[str, Any], aliases: List[str]) -> bool:
    blob = f"{item.get('text') or ''} {item.get('feed') or ''}".casefold()
    return any(a in blob for a in aliases)


def latest_for_symbol(symbol: str) -> Optional[Dict[str, Any]]:
    rows = list_history(limit=1, symbol=symbol, kinds=["stock_news", "polymarket", "manual"])
    return rows[0] if rows else None
