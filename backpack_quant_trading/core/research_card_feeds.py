"""AI 选股卡片：按标的聚合新闻/信号（钉钉推送历史 + 手动粘贴 + 策略成交）。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# 研究卡片代码 -> (数据库 symbol, strategy_name, timeframe, 展示用策略名)
_RESEARCH_TRADE_BINDINGS: Dict[str, Tuple[str, Optional[str], Optional[str], str]] = {
    "NVDA": ("NVDAUSDT", "NVDA_KLINE", "2H", "NVDA K线策略"),
    "INTC": ("INTCUSDT", "INTC_KLINE", "1H", "INTC K线策略"),
    "CRCL": ("CRCL", "CRCL_1H", "1H", "CRCL 动量策略"),
    "ETH": ("ETHUSDT", "ETH_2H_TREND", "2h", "ETH 2H 趋势"),
    "HYPE": ("HYPEUSDT", "HYPE_2H_TREND", "4h", "HYPE 2H 趋势"),
}

from backpack_quant_trading.core.manual_card_feeds import (
    format_news_summary,
    format_signal_summary,
    list_news_history,
    list_signal_history,
    parse_signal_paste,
    sync_from_paste_files,
    _load_history,
    _merge_history,
    _save_history,
    NEWS_HISTORY,
    SIGNAL_HISTORY,
)

_SYMBOL_ALIASES: Dict[str, List[str]] = {
    "NVDA": ["nvda", "nvidia", "英伟达", "英伟"],
    "INTC": ["intc", "intel", "英特尔"],
    "SNDK": ["sndk", "sandisk", "闪迪"],
    "MU": ["mu", "micron", "美光"],
    "ETH": ["eth", "ethereum", "以太坊"],
    "HYPE": ["hype", "hyperliquid"],
    "CRCL": ["crcl", "circle"],
    "MSFT": ["msft", "microsoft", "微软"],
    "MRVL": ["mrvl", "marvell", "美满", "美满电子"],
    "NOK": ["nok", "nokia", "诺基亚"],
    "RKLB": ["rklb", "rocket lab", "rocketlab", "火箭实验室"],
    "IBM": ["ibm", "国际商业机器"],
    "GOOGL": ["googl", "goog", "google", "谷歌", "alphabet"],
    "CRDO": ["crdo", "credo"],
    "603986": ["603986", "兆易创新", "gigadevice"],
    "688146": ["688146", "中船特气"],
    "300308": ["300308", "中际旭创", "innolight"],
    "AAPL": ["aapl", "apple", "苹果"],
}


def symbol_aliases(code: str) -> List[str]:
    c = str(code or "").upper().strip()
    base = [c, c.lower()]
    extra = _SYMBOL_ALIASES.get(c, [])
    out: List[str] = []
    seen = set()
    for a in base + extra:
        k = a.casefold()
        if k not in seen:
            seen.add(k)
            out.append(a)
    return out


def text_matches_symbol(blob: str, code: str) -> bool:
    if not blob:
        return False
    b = blob.casefold()
    return any(a.casefold() in b for a in symbol_aliases(code))


def _dingtalk_row_to_news(row: Dict[str, Any]) -> Dict[str, Any]:
    text = str(row.get("text") or "").strip()
    time_s = str(row.get("time") or row.get("pushed_at") or "").strip()
    summary = format_news_summary(text, time_s)
    return {
        "id": str(row.get("id") or ""),
        "feed": str(row.get("feed") or "钉钉"),
        "feed_key": str(row.get("feed_key") or row.get("kind") or ""),
        "time": time_s,
        "text": text,
        "summary": summary,
        "url": str(row.get("url") or ""),
        "source": "dingtalk_push",
        "pushed_at": row.get("pushed_at"),
    }


def _dingtalk_row_to_signal(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    text = str(row.get("text") or "").strip()
    if not text:
        return None
    parsed = parse_signal_paste(text.replace("【提醒】", "").strip())
    if parsed:
        parsed["source"] = "dingtalk_push"
        return parsed
    return None


def ingest_stock_news_feed_item(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """自选快讯推送钉钉成功后写入卡片历史。"""
    text = str(item.get("text") or "").strip()
    if not text:
        return None
    time_s = str(item.get("time") or "").strip()
    entry = {
        "id": str(item.get("dedupe_id") or item.get("id") or ""),
        "feed": str(item.get("feed") or "快讯"),
        "feed_key": str(item.get("feed_key") or ""),
        "time": time_s,
        "text": text,
        "summary": format_news_summary(text, time_s),
        "url": str(item.get("url") or ""),
        "source": "stock_news_alert",
    }
    if not entry["id"]:
        from backpack_quant_trading.core.manual_card_feeds import hashlib_id

        entry["id"] = f"feed:{hashlib_id(entry['summary'])}"
    items = _merge_history(_load_history(NEWS_HISTORY), entry)
    _save_history(NEWS_HISTORY, items)
    return entry


def get_latest_news_for_symbol(code: str) -> Optional[Dict[str, Any]]:
    """优先钉钉已推送记录，再匹配手动历史。"""
    sym = str(code or "").upper().strip()
    if not sym:
        from backpack_quant_trading.core.manual_card_feeds import get_latest_news

        return get_latest_news()

    try:
        from backpack_quant_trading.core.dingtalk_push_history import list_history

        for row in list_history(limit=80, symbol=sym, kinds=["stock_news"]):
            if row.get("text"):
                return _dingtalk_row_to_news(row)
    except Exception:
        pass

    sync_from_paste_files()
    for item in list_news_history(120):
        blob = f"{item.get('summary') or ''} {item.get('text') or ''}"
        if text_matches_symbol(blob, sym):
            return item

    latest = list_news_history(1)
    if latest:
        blob = f"{latest[0].get('summary') or ''} {latest[0].get('text') or ''}"
        if text_matches_symbol(blob, sym):
            return latest[0]
    return None


def _fetch_strategy_trades(code: str) -> List[Dict[str, Any]]:
    """从 strategy_backtest_trades 表读取成交（时间升序）。"""
    from backpack_quant_trading.api.routers.strategy import _query_trades_by_symbol, _trades_to_out

    sym = str(code or "").upper().strip()
    binding = _RESEARCH_TRADE_BINDINGS.get(sym)
    rows = []
    if binding:
        db_sym, strategy_name, timeframe, _ = binding
        rows = _query_trades_by_symbol(db_sym, strategy_name, timeframe)
    else:
        for cand in (f"{sym}USDT", sym, f"{sym}USD", f"{sym}.O"):
            rows = _query_trades_by_symbol(cand, None, None)
            if rows:
                break
    if not rows:
        return []
    outs = _trades_to_out(rows)
    return [x.model_dump() if hasattr(x, "model_dump") else dict(x) for x in outs]


def _trade_row_to_card_signal(
    row: Dict[str, Any],
    *,
    display_code: str,
    strategy_label: str,
) -> Dict[str, Any]:
    """将数据库成交记录格式化为卡片展示结构。"""
    trade_type = str(row.get("trade_type") or "")
    sig_raw = str(row.get("signal") or trade_type or "")
    tt = trade_type.casefold()
    sr = sig_raw.casefold()
    if "空" in tt or "short" in tt or "sell" in sr or "卖" in trade_type:
        side = "sell"
        side_raw = "卖出"
    elif "多" in tt or "long" in tt or "buy" in sr or "买" in trade_type:
        side = "buy"
        side_raw = "买入"
    else:
        side = "buy"
        side_raw = trade_type or sig_raw or "信号"

    tt_at = row.get("trade_time")
    if hasattr(tt_at, "isoformat"):
        triggered_at = tt_at.strftime("%Y-%m-%d %H:%M:%S")
    else:
        triggered_at = str(tt_at or "").strip()

    price = row.get("price")
    try:
        price_s = f"{float(price):.4f}".rstrip("0").rstrip(".") if price is not None else ""
    except (TypeError, ValueError):
        price_s = str(price or "")

    strategy_name = strategy_label
    binding = _RESEARCH_TRADE_BINDINGS.get(display_code.upper())
    timeframe = str(row.get("timeframe") or (binding[2] if binding else "") or "").strip()
    strategy_display = f"{strategy_name} {timeframe}".strip() if timeframe else strategy_name

    display_sym = display_code.upper()
    summary = format_signal_summary(
        symbol=display_sym,
        side=side_raw,
        side_raw=side_raw,
        price=price_s,
        strategy=strategy_display,
        triggered_at=triggered_at,
    )
    trade_no = row.get("trade_no")
    return {
        "id": f"db:{display_sym}:{trade_no}:{triggered_at}",
        "symbol": display_sym,
        "symbol_raw": str(row.get("symbol") or display_sym),
        "side": side_raw,
        "side_key": side,
        "side_display": side_raw,
        "price": price_s,
        "strategy": strategy_display,
        "timeframe": timeframe,
        "triggered_at": triggered_at,
        "trade_type": trade_type,
        "trade_no": trade_no,
        "summary": summary,
        "source": "strategy_db",
    }


def _strategy_label_for(code: str) -> str:
    sym = code.upper()
    if sym in _RESEARCH_TRADE_BINDINGS:
        return _RESEARCH_TRADE_BINDINGS[sym][3]
    return f"{sym} 策略"


def _latest_strategy_signal(code: str) -> Optional[Dict[str, Any]]:
    trades = _fetch_strategy_trades(code)
    if not trades:
        return None
    row = trades[-1]
    return _trade_row_to_card_signal(
        row,
        display_code=code,
        strategy_label=_strategy_label_for(code),
    )


def _list_strategy_signals(code: str, limit: int) -> List[Dict[str, Any]]:
    trades = _fetch_strategy_trades(code)
    if not trades:
        return []
    label = _strategy_label_for(code)
    out: List[Dict[str, Any]] = []
    for row in reversed(trades[-limit:]):
        out.append(_trade_row_to_card_signal(row, display_code=code, strategy_label=label))
    return out


def get_latest_signal_for_symbol(code: str) -> Optional[Dict[str, Any]]:
    """优先数据库最新成交，其次手动粘贴 / 钉钉解析。"""
    sym = str(code or "").upper().strip()
    if not sym:
        return None

    db_sig = _latest_strategy_signal(sym)
    if db_sig:
        return db_sig

    sync_from_paste_files()
    for item in list_signal_history(120):
        blob = f"{item.get('summary') or ''} {item.get('symbol') or ''} {item.get('symbol_raw') or ''}"
        if text_matches_symbol(blob, sym):
            return item

    try:
        from backpack_quant_trading.core.dingtalk_push_history import list_history

        for row in list_history(limit=40, symbol=sym, kinds=["manual", "signal"]):
            parsed = _dingtalk_row_to_signal(row)
            if parsed and text_matches_symbol(parsed.get("symbol") or parsed.get("summary") or "", sym):
                return parsed
    except Exception:
        pass

    return None


def list_dingtalk_news(limit: int = 50) -> List[Dict[str, Any]]:
    try:
        from backpack_quant_trading.core.dingtalk_push_history import list_history

        return [
            _dingtalk_row_to_news(row)
            for row in list_history(limit=limit, kinds=["stock_news"])
            if row.get("text")
        ]
    except Exception:
        return []


def list_news_for_symbol(code: str, limit: int = 50) -> List[Dict[str, Any]]:
    sym = str(code or "").upper().strip()
    sync_from_paste_files()
    out: List[Dict[str, Any]] = []
    seen = set()
    try:
        from backpack_quant_trading.core.dingtalk_push_history import list_history

        for row in list_history(limit=limit * 2, symbol=sym, kinds=["stock_news"]):
            ent = _dingtalk_row_to_news(row)
            eid = ent.get("id")
            if eid and eid not in seen:
                seen.add(eid)
                out.append(ent)
    except Exception:
        pass
    for item in list_news_history(limit * 2):
        blob = f"{item.get('summary') or ''} {item.get('text') or ''}"
        if not text_matches_symbol(blob, sym):
            continue
        eid = item.get("id")
        if eid and eid in seen:
            continue
        if eid:
            seen.add(eid)
        out.append(item)
    return out[: max(1, limit)]


def list_signals_for_symbol(code: str, limit: int = 50) -> List[Dict[str, Any]]:
    sym = str(code or "").upper().strip()
    n = max(1, min(int(limit or 50), 200))
    out: List[Dict[str, Any]] = []
    seen = set()

    for item in _list_strategy_signals(sym, n):
        eid = item.get("id")
        if eid:
            seen.add(eid)
        out.append(item)

    sync_from_paste_files()
    for item in list_signal_history(n * 2):
        blob = f"{item.get('summary') or ''} {item.get('symbol') or ''}"
        if not text_matches_symbol(blob, sym):
            continue
        eid = item.get("id")
        if eid and eid in seen:
            continue
        if eid:
            seen.add(eid)
        out.append(item)

    return out[:n]
