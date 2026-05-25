"""AI 选股卡片：手动粘贴的新闻/信号（编辑 data/manual_*_paste.txt）。"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_DATA = Path(__file__).resolve().parents[1] / "data"
NEWS_PASTE = _DATA / "manual_news_paste.txt"
SIGNAL_PASTE = _DATA / "manual_signal_paste.txt"
NEWS_HISTORY = _DATA / "manual_news_history.json"
SIGNAL_HISTORY = _DATA / "manual_signal_history.json"
_MAX_HISTORY = 200


def _read_text(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()


def _load_history(path: Path) -> List[Dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and isinstance(raw.get("items"), list):
            return [x for x in raw["items"] if isinstance(x, dict)]
        if isinstance(raw, list):
            return [x for x in raw if isinstance(x, dict)]
    except Exception:
        pass
    return []


def _save_history(path: Path, items: List[Dict[str, Any]]) -> None:
    _DATA.mkdir(parents=True, exist_ok=True)
    trimmed = items[:_MAX_HISTORY]
    path.write_text(json.dumps({"items": trimmed}, ensure_ascii=False, indent=2), encoding="utf-8")


def _split_blocks(raw: str) -> List[str]:
    if not raw.strip():
        return []
    parts = re.split(r"\n\s*---\s*\n", raw.strip())
    return [p.strip() for p in parts if p.strip()]


def parse_news_paste(raw: str) -> Optional[Dict[str, Any]]:
    """解析钉钉自选快讯粘贴块。"""
    block = (raw or "").strip()
    if not block:
        return None
    lines = [ln.strip() for ln in block.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    if not lines:
        return None

    feed = ""
    time_s = ""
    text = ""
    dedupe_id = ""

    for ln in lines:
        if ln.startswith("id:"):
            dedupe_id = ln.split(":", 1)[1].strip()
            continue
        if re.match(r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}", ln):
            time_s = ln
            continue
        if "【提醒】" in ln or "自选快讯" in ln:
            m = re.search(r"【自选快讯】(.+)$", ln)
            feed = (m.group(1) if m else ln).strip()
            continue
        if not text:
            text = ln

    if not text:
        for ln in reversed(lines):
            if not ln.startswith("id:") and not re.match(r"^\d{4}-\d{2}-\d{2}", ln) and "【" not in ln:
                text = ln
                break

    if not text:
        return None

    summary = format_news_summary(text, time_s)
    entry_id = dedupe_id or f"manual:{hashlib_id(summary)}"

    return {
        "id": entry_id,
        "feed": feed or "快讯",
        "time": time_s,
        "text": text,
        "summary": summary,
        "raw": block,
        "saved_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    }


def hashlib_id(s: str) -> str:
    import hashlib

    return hashlib.md5(s.encode("utf-8", errors="ignore")).hexdigest()[:16]


def format_news_summary(text: str, time_s: str) -> str:
    """例：花旗：2026-05-19 18:31:35 将闪迪目标价从1300美元上调至2025美元。"""
    t = (text or "").strip()
    tm = (time_s or "").strip()
    m = re.match(r"^([^：:]+)[：:](.+)$", t)
    if m:
        head, body = m.group(1).strip(), m.group(2).strip()
        return f"{head}：{tm} {body}" if tm else f"{head}：{body}"
    return f"{tm} {t}".strip() if tm else t


def parse_signal_paste(raw: str) -> Optional[Dict[str, Any]]:
    """解析策略信号粘贴块（键: 值 行）。"""
    block = (raw or "").strip()
    if not block:
        return None
    fields: Dict[str, str] = {}
    for ln in block.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        if ":" in ln:
            k, v = ln.split(":", 1)
        elif "：" in ln:
            k, v = ln.split("：", 1)
        else:
            continue
        fields[k.strip()] = v.strip()

    symbol = fields.get("交易品种") or fields.get("symbol") or ""
    side_raw = fields.get("信号类型") or fields.get("side") or ""
    price = fields.get("成交价格") or fields.get("price") or ""
    strategy = fields.get("策略名称") or fields.get("strategy") or ""
    timeframe = fields.get("周期") or fields.get("timeframe") or ""
    triggered_at = fields.get("触发时间") or fields.get("triggered_at") or ""

    if not symbol and not triggered_at:
        return None

    side = "买入" if "买" in side_raw else "卖出" if "卖" in side_raw else side_raw
    summary = format_signal_summary(
        symbol=symbol,
        side=side,
        side_raw=side_raw,
        price=price,
        strategy=strategy,
        triggered_at=triggered_at,
    )
    entry_id = f"sig:{hashlib_id(summary)}"

    return {
        "id": entry_id,
        "symbol": symbol.replace("USDT", "").strip() or symbol,
        "symbol_raw": symbol,
        "side": side,
        "side_display": side_raw or side,
        "price": price,
        "strategy": strategy,
        "timeframe": timeframe,
        "triggered_at": triggered_at,
        "summary": summary,
        "raw": block,
        "saved_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    }


def format_signal_summary(
    *,
    symbol: str,
    side: str,
    side_raw: str,
    price: str,
    strategy: str,
    triggered_at: str,
) -> str:
    """例：2026-05-20 14:00:14 VIRTUALUSDT 买入 🟢 成交价格: 0.7181 策略名称: 2h 进1h出"""
    emoji = "🟢" if "买" in (side_raw or side) else "🔴" if "卖" in (side_raw or side) else ""
    side_txt = side or side_raw
    parts = [triggered_at, symbol, side_txt]
    if emoji:
        parts.append(emoji)
    parts.append(f"成交价格: {price}")
    parts.append(f"策略名称: {strategy}")
    return " ".join(p for p in parts if p)


def _merge_history(items: List[Dict[str, Any]], new_item: Dict[str, Any]) -> List[Dict[str, Any]]:
    nid = str(new_item.get("id") or "")
    out = [new_item]
    for x in items:
        if str(x.get("id") or "") != nid:
            out.append(x)
    return out[:_MAX_HISTORY]


def _strip_comment_lines(raw: str) -> str:
    lines = []
    for ln in (raw or "").splitlines():
        s = ln.strip()
        if s.startswith("#"):
            continue
        lines.append(ln)
    return "\n".join(lines).strip()


def sync_from_paste_files() -> None:
    """读取 txt 粘贴区，解析并写入 history（新 id 才追加）。"""
    _DATA.mkdir(parents=True, exist_ok=True)

    news_raw = _strip_comment_lines(_read_text(NEWS_PASTE))
    news_blocks = _split_blocks(news_raw)
    news_items = _load_history(NEWS_HISTORY)
    for block in news_blocks:
        parsed = parse_news_paste(block)
        if parsed:
            news_items = _merge_history(news_items, parsed)
    if news_items:
        _save_history(NEWS_HISTORY, news_items)

    sig_raw = _strip_comment_lines(_read_text(SIGNAL_PASTE))
    sig_blocks = _split_blocks(sig_raw)
    sig_items = _load_history(SIGNAL_HISTORY)
    for block in sig_blocks:
        parsed = parse_signal_paste(block)
        if parsed:
            sig_items = _merge_history(sig_items, parsed)
    if sig_items:
        _save_history(SIGNAL_HISTORY, sig_items)


def get_latest_news() -> Optional[Dict[str, Any]]:
    sync_from_paste_files()
    raw = _read_text(NEWS_PASTE)
    if raw:
        p = parse_news_paste(_split_blocks(raw)[0] if _split_blocks(raw) else raw)
        if p:
            return p
    items = _load_history(NEWS_HISTORY)
    return items[0] if items else None


def get_latest_signal() -> Optional[Dict[str, Any]]:
    sync_from_paste_files()
    raw = _read_text(SIGNAL_PASTE)
    if raw:
        blocks = _split_blocks(raw)
        p = parse_signal_paste(blocks[0] if blocks else raw)
        if p:
            return p
    items = _load_history(SIGNAL_HISTORY)
    return items[0] if items else None


def list_news_history(limit: int = 100) -> List[Dict[str, Any]]:
    sync_from_paste_files()
    items = _load_history(NEWS_HISTORY)
    n = max(1, min(int(limit or 100), _MAX_HISTORY))
    return items[:n]


def list_signal_history(limit: int = 100) -> List[Dict[str, Any]]:
    sync_from_paste_files()
    items = _load_history(SIGNAL_HISTORY)
    n = max(1, min(int(limit or 100), _MAX_HISTORY))
    return items[:n]


def save_news_paste(raw: str) -> Dict[str, Any]:
    _DATA.mkdir(parents=True, exist_ok=True)
    NEWS_PASTE.write_text((raw or "").strip() + "\n", encoding="utf-8")
    parsed = parse_news_paste(raw)
    if not parsed:
        raise ValueError("无法解析新闻粘贴内容，请检查格式")
    items = _merge_history(_load_history(NEWS_HISTORY), parsed)
    _save_history(NEWS_HISTORY, items)
    return parsed


def save_signal_paste(raw: str) -> Dict[str, Any]:
    _DATA.mkdir(parents=True, exist_ok=True)
    SIGNAL_PASTE.write_text((raw or "").strip() + "\n", encoding="utf-8")
    parsed = parse_signal_paste(raw)
    if not parsed:
        raise ValueError("无法解析信号粘贴内容，请检查格式")
    items = _merge_history(_load_history(SIGNAL_HISTORY), parsed)
    _save_history(SIGNAL_HISTORY, items)
    return parsed
