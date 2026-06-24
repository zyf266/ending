"""缓存最近推送的钉钉交易信号，供「回复 @ 评分」在钉钉未回传引用正文时兜底。"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_CACHE_PATH = Path(__file__).resolve().parents[1] / "data" / "dingtalk_recent_signals.json"
_LOCK = threading.Lock()
_MAX_ITEMS = 40
_DEFAULT_TTL_SEC = 7200


def _load() -> List[Dict[str, Any]]:
    if not _CACHE_PATH.is_file():
        return []
    try:
        data = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
        return list(data.get("items") or [])
    except Exception:
        return []


def _save(items: List[Dict[str, Any]]) -> None:
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(
        json.dumps({"items": items[-_MAX_ITEMS:]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def cache_dingtalk_signal(parsed: Dict[str, Any], *, source: str = "tradingview_bot") -> None:
    """推送钉钉成功后写入最近信号列表。"""
    symbol = str(parsed.get("symbol") or "").strip().upper().replace(".P", "")
    if not symbol or symbol == "未知品种":
        return
    action = str(parsed.get("signal") or parsed.get("action") or "").strip()
    entry = {
        "at": time.time(),
        "at_iso": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": source,
        "symbol": symbol,
        "action": action,
        "timeframe": str(parsed.get("timeframe") or "").strip(),
        "strategy": str(parsed.get("strategy") or "").strip(),
        "price": parsed.get("price"),
        "raw_text": str(parsed.get("raw_message") or "")[:1500],
    }
    with _LOCK:
        items = _load()
        items.append(entry)
        _save(items)


def get_latest_cached_signal(*, max_age_sec: int = _DEFAULT_TTL_SEC) -> Optional[Dict[str, Any]]:
    now = time.time()
    with _LOCK:
        items = _load()
    for row in reversed(items):
        try:
            if now - float(row.get("at") or 0) <= max_age_sec:
                return dict(row)
        except (TypeError, ValueError):
            continue
    return None


def list_recent_cached_signals(*, max_age_sec: int = _DEFAULT_TTL_SEC) -> List[Dict[str, Any]]:
    now = time.time()
    with _LOCK:
        items = _load()
    out: List[Dict[str, Any]] = []
    for row in reversed(items):
        try:
            if now - float(row.get("at") or 0) <= max_age_sec:
                out.append(dict(row))
        except (TypeError, ValueError):
            continue
    return out


def find_cached_signal_by_symbol(
    symbol: str,
    *,
    max_age_sec: int = _DEFAULT_TTL_SEC,
) -> Optional[Dict[str, Any]]:
    sym = str(symbol or "").strip().upper().replace(".P", "")
    if not sym:
        return None
    if not sym.endswith(("USDT", "USDC")) and len(sym) <= 10:
        sym_usdt = f"{sym}USDT"
    else:
        sym_usdt = sym
    for row in list_recent_cached_signals(max_age_sec=max_age_sec):
        row_sym = str(row.get("symbol") or "").upper().replace(".P", "")
        if row_sym in (sym, sym_usdt):
            return row
    return None


def find_cached_signal_by_reply_time(
    replied_ts: float,
    *,
    window_sec: int = 900,
    max_age_sec: int = _DEFAULT_TTL_SEC,
) -> Optional[Dict[str, Any]]:
    """按被回复消息的发送时间，找时间最接近的一条缓存（避免误用最新一条）。"""
    if not replied_ts:
        return None
    best: Optional[Dict[str, Any]] = None
    best_delta: Optional[float] = None
    for row in list_recent_cached_signals(max_age_sec=max_age_sec):
        try:
            at = float(row.get("at") or 0)
        except (TypeError, ValueError):
            continue
        delta = abs(at - replied_ts)
        if delta > window_sec:
            continue
        if best_delta is None or delta < best_delta:
            best_delta = delta
            best = row
    return best


def _norm_hint_key(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").lower()).replace("信号", "")


def _score_hint_match(needle: str, row: Dict[str, Any]) -> int:
    needle_l = needle.lower()
    needle_core = re.sub(r"信号$", "", needle_l).strip()
    needle_norm = _norm_hint_key(needle_core)
    strategy = str(row.get("strategy") or "").lower()
    raw_text = str(row.get("raw_text") or "").lower()
    strategy_norm = _norm_hint_key(strategy)
    if needle_norm and (needle_norm in strategy_norm or strategy_norm in needle_norm):
        return 110 + len(needle_norm)
    if needle_core and needle_core in strategy:
        return 100 + len(needle_core)
    if needle_core and needle_core in raw_text:
        return 80 + len(needle_core)
    if needle_l in strategy or needle_l in raw_text:
        return 60
    return 0


def find_cached_signals_by_hint(
    hint: str,
    *,
    max_age_sec: int = _DEFAULT_TTL_SEC,
    min_score: int = 60,
) -> List[Dict[str, Any]]:
    """返回所有匹配该引用的缓存条目（按分数、时间倒序）。"""
    needle = (hint or "").strip()
    if not needle:
        return []
    scored: list[tuple[int, float, Dict[str, Any]]] = []
    for row in list_recent_cached_signals(max_age_sec=max_age_sec):
        score = _score_hint_match(needle, row)
        if score >= min_score:
            try:
                at = float(row.get("at") or 0)
            except (TypeError, ValueError):
                at = 0.0
            scored.append((score, at, row))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [row for _, _, row in scored]


def find_cached_signal_by_hint(
    hint: str,
    *,
    max_age_sec: int = _DEFAULT_TTL_SEC,
) -> Optional[Dict[str, Any]]:
    """按策略名/引用预览找唯一匹配；多品种同名策略时返回 None（由调用方提示歧义）。"""
    matches = find_cached_signals_by_hint(hint, max_age_sec=max_age_sec)
    if not matches:
        return None
    symbols = {str(m.get("symbol") or "").upper() for m in matches}
    if len(symbols) > 1:
        return None
    return dict(matches[0])


def cache_signal_count(*, max_age_sec: int = _DEFAULT_TTL_SEC) -> int:
    now = time.time()
    with _LOCK:
        items = _load()
    n = 0
    for row in items:
        try:
            if now - float(row.get("at") or 0) <= max_age_sec:
                n += 1
        except (TypeError, ValueError):
            continue
    return n
