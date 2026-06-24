"""钉钉群内「回复信号 + @机器人」触发的手动 AI 评分。"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

_SCORE_TRIGGERS = ("评分", "打分", "分析", "score", "evaluate")


def extract_user_text_from_raw(raw: Dict[str, Any]) -> str:
    """从钉钉回调 raw 提取用户输入（含 richText / text）。"""
    if not isinstance(raw, dict):
        return ""
    chunks: list[str] = []

    text_block = raw.get("text")
    if isinstance(text_block, dict):
        content = str(text_block.get("content") or "").strip()
        if content:
            chunks.append(content)

    msgtype = str(raw.get("msgtype") or "").lower()
    content = raw.get("content") or {}
    if msgtype == "richtext" or content.get("richText"):
        rich = content.get("richText") or []
        if isinstance(rich, list):
            for item in rich:
                if not isinstance(item, dict):
                    continue
                t = str(item.get("text") or "").strip()
                if t and not t.startswith("@"):
                    chunks.append(t)

    # 去重保序
    seen: set[str] = set()
    out: list[str] = []
    for c in chunks:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return " ".join(out).strip()


def is_manual_score_command(text: str) -> bool:
    plain = re.sub(r"@[^\s@　]+", " ", text or "", flags=re.IGNORECASE)
    plain = plain.strip().lower()
    if not plain:
        return False
    if any(k in plain for k in _SCORE_TRIGGERS):
        return True
    if re.search(r"评[一下个]*分", plain):
        return True
    if re.search(r"打[一下个]*分", plain):
        return True
    if re.search(r"(帮|给|帮忙).{0,6}评", plain):
        return True
    if "信号" in plain and any(v in plain for v in ("评", "分析", "看下", "看看")):
        return True
    return False


def _has_explicit_symbol(text: str) -> bool:
    plain = re.sub(r"@[^\s@　]+", " ", text or "", flags=re.IGNORECASE)
    if re.search(r"[A-Za-z]{2,15}(?:USDT|USDC)?", plain):
        return True
    if re.search(r"[A-Za-z]{2,15}\d+[hHdDmMwW]", plain, re.I):
        return True
    return False


def manual_dingtalk_score_enabled() -> bool:
    import os

    return os.getenv("DINGTALK_MANUAL_SCORE_ENABLED", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
        "enabled",
    )


def _pick(pattern: str, text: str, flags: int = re.IGNORECASE) -> str:
    m = re.search(pattern, text or "", flags)
    return (m.group(1).strip() if m else "")


def normalize_dingtalk_markdown(text: str) -> str:
    s = re.sub(r"\*+", "", text or "")
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def _summarize_replied_msg(replied: Any) -> str:
    if not isinstance(replied, dict):
        return ""
    msgtype = str(replied.get("msgtype") or replied.get("msgType") or "").lower()
    content = replied.get("content")
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, dict):
        content = replied

    # 钉钉 Stream 常见路径：repliedMsg.content.text
    text_field = content.get("text")
    if isinstance(text_field, str) and text_field.strip():
        return _decode_dingtalk_reply_text(text_field)
    if isinstance(text_field, dict):
        inner = str(text_field.get("content") or text_field.get("text") or "").strip()
        if inner:
            return _decode_dingtalk_reply_text(inner)

    if msgtype in ("", "text"):
        inner = str(content.get("content") or "").strip()
        if inner:
            return _decode_dingtalk_reply_text(inner)

    if msgtype == "markdown":
        md = content.get("markdown") if isinstance(content.get("markdown"), dict) else content
        if isinstance(md, dict):
            parts = [str(md.get("title") or "").strip(), str(md.get("text") or "").strip()]
            return "\n".join(p for p in parts if p)
        return str(content.get("text") or "").strip()

    if msgtype == "richtext" or content.get("richText"):
        rich = content.get("richText") or content.get("rich_text") or []
        chunks = []
        if isinstance(rich, list):
            for item in rich:
                if isinstance(item, dict) and item.get("text"):
                    chunks.append(str(item["text"]))
        return " ".join(chunks).strip()

    return str(content).strip()


def _decode_dingtalk_reply_text(text: str) -> str:
    """部分多行引用正文会被钉钉编码，尽量保留可解析片段。"""
    s = (text or "").strip()
    if not s:
        return ""
    if "交易品种" in s or "信号类型" in s or "USDT" in s.upper():
        return s
    # 编码垃圾里有时仍夹带可读字段
    if "||" in s:
        for part in s.split("||"):
            if "交易品种" in part or re.search(r"[A-Za-z]{2,15}USDT", part, re.I):
                return part
    return s


def _is_reply_message(raw: Dict[str, Any]) -> bool:
    text_block = raw.get("text")
    if isinstance(text_block, dict):
        if text_block.get("isReplyMsg") or text_block.get("repliedMsg"):
            return True
    if raw.get("originalMsgId") or raw.get("quoteMessage") or raw.get("repliedMsg"):
        return True
    return False


def _has_explicit_direction(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in ("买入", "卖出", "做多", "做空", "buy", "sell", "long", "short", "看空", "看多"))


def _deep_find_signal_text(raw: Dict[str, Any]) -> str:
    """钉钉有时把引用正文藏在深层字段，递归扫描含「交易品种」的字符串。"""
    candidates: list[str] = []

    def walk(obj: Any, depth: int = 0) -> None:
        if depth > 12:
            return
        if isinstance(obj, str):
            s = obj.strip()
            if len(s) >= 12:
                candidates.append(s)
            return
        if isinstance(obj, dict):
            for v in obj.values():
                walk(v, depth + 1)
        elif isinstance(obj, list):
            for v in obj:
                walk(v, depth + 1)

    walk(raw)
    for s in candidates:
        if "交易品种" in s and ("信号类型" in s or "USDT" in s.upper()):
            return s
    for s in candidates:
        if re.search(r"交易品种", s) and re.search(r"[A-Za-z]{2,15}USDT", s, re.I):
            return s
    return ""


def _extract_embedded_quote_line(user_text: str) -> str:
    """用户消息里自带的引用预览行，如「2h进2h出信号」。"""
    for line in re.split(r"[\n\r]+", user_text or ""):
        line = line.strip()
        if not line or line.startswith("@"):
            continue
        if re.search(r"信号|USDT|交易品种|买入|卖出|做空|做多", line, re.I):
            return line
        if re.search(r"\d+[hHdDmMwW]", line) and re.search(r"进|出", line):
            return line
    return ""


def _collect_quote_hints(user_text: str, raw: Dict[str, Any]) -> list[str]:
    hints: list[str] = []
    for src in (
        extract_quoted_signal_text(raw),
        _deep_find_signal_text(raw),
        _extract_embedded_quote_line(user_text),
        _extract_rich_text_quote(raw),
    ):
        s = (src or "").strip()
        if s and s not in hints:
            hints.append(s)
    text_block = raw.get("text")
    if isinstance(text_block, dict) and text_block.get("repliedMsg"):
        s = _summarize_replied_msg(text_block["repliedMsg"]).strip()
        if s and s not in hints:
            hints.append(s)
    return hints


def _merge_partial_with_cache(
    partial: Dict[str, Any],
    cached: Optional[Dict[str, Any]],
    *,
    source: str = "quote_hint+cache",
) -> Optional[Dict[str, Any]]:
    if not cached or not cached.get("symbol"):
        return None
    out = dict(partial or {})
    out["symbol"] = (out.get("symbol") or cached.get("symbol") or "").upper()
    out["timeframe"] = out.get("timeframe") or cached.get("timeframe") or ""
    out["strategy"] = out.get("strategy") or cached.get("strategy") or ""
    partial_blob = str(out.get("raw_text") or out.get("strategy") or "")
    cached_act = _action_to_api(str(cached.get("action") or ""), "")
    if _has_explicit_direction(partial_blob):
        act = _action_to_api(partial_blob, "")
    else:
        act = cached_act or _action_to_api("", "")
    out["action"] = act
    out["resolve_source"] = source
    return out


def _parsed_from_cache(cached: Dict[str, Any], *, source: str) -> Dict[str, Any]:
    parsed = {
        "symbol": cached.get("symbol"),
        "action": _action_to_api(cached.get("action") or "", ""),
        "timeframe": cached.get("timeframe") or "",
        "strategy": cached.get("strategy") or "",
        "raw_text": cached.get("raw_text") or "",
        "resolve_source": source,
    }
    return enrich_parsed_signal(parsed)


def _extract_rich_text_quote(raw: Dict[str, Any]) -> str:
    """回复消息有时是 richText，引用预览在 content.richText 里。"""
    content = raw.get("content") or {}
    rich = content.get("richText") or content.get("rich_text") or []
    if not isinstance(rich, list):
        return ""
    chunks: list[str] = []
    for item in rich:
        if not isinstance(item, dict):
            continue
        t = str(item.get("text") or "").strip()
        if not t:
            continue
        if t.startswith("@"):
            continue
        chunks.append(t)
    return "\n".join(chunks).strip()


def extract_quoted_signal_text(raw: Dict[str, Any]) -> str:
    """从钉钉回调 raw 中提取被回复的那条消息正文。"""
    if not isinstance(raw, dict):
        return ""

    text_block = raw.get("text")
    if isinstance(text_block, dict):
        if text_block.get("repliedMsg"):
            body = _summarize_replied_msg(text_block["repliedMsg"])
            if body and _looks_like_signal_text(body):
                return body
        if text_block.get("isReplyMsg") and text_block.get("repliedMsg"):
            body = _summarize_replied_msg(text_block["repliedMsg"])
            if body:
                return body
        for key in ("extensions",):
            ext = text_block.get(key) or {}
            if isinstance(ext, dict) and ext.get("repliedMsg"):
                body = _summarize_replied_msg(ext["repliedMsg"])
                if body:
                    return body

    quote = raw.get("quoteMessage")
    if isinstance(quote, dict):
        tb = quote.get("text")
        if isinstance(tb, dict):
            body = str(tb.get("content") or "").strip()
            if body:
                return body
        body = _summarize_replied_msg(quote)
        if body:
            return body

    for key in ("repliedMsg", "quoteMessage", "quotedMessage"):
        if raw.get(key):
            body = _summarize_replied_msg(raw[key])
            if body:
                return body

    rich_quote = _extract_rich_text_quote(raw)
    if rich_quote:
        return rich_quote

    return ""


def _looks_like_signal_text(text: str) -> bool:
    t = text or ""
    if "交易品种" in t or "信号类型" in t:
        return True
    if re.search(r"[A-Za-z]{2,15}USDT", t, re.I):
        return True
    if re.search(r"\d+[hHdDmMwW]", t) and re.search(r"[A-Za-z]{2,}", t):
        return True
    if re.search(r"\d+[hHdDmMwW]进\d+[hHdDmMwW]出", t, re.I):
        return True
    return bool(t.strip())


def parse_inline_score_request(user_text: str) -> Dict[str, Any]:
    """
    从 @ 消息正文直接解析，例如：
    - 对 eth 2h 的买入信号进行评分
    - BTCUSDT 8h 买入 评分
    """
    plain = re.sub(r"@[^\s@　]+", " ", user_text or "", flags=re.IGNORECASE)
    plain = plain.strip()
    parsed: Dict[str, Any] = {
        "symbol": "",
        "action": "",
        "timeframe": "",
        "strategy": "",
        "raw_text": plain[:500],
    }
    if not plain or not is_manual_score_command(plain):
        return parsed

    if re.search(r"这[个条]?信号", plain) and not re.search(
        r"[A-Za-z]{2,15}(?:USDT|USDC)?", plain, re.I
    ):
        return parsed

    patterns = [
        r"(?:对|将|把)?\s*([A-Za-z]{2,15})(\d+[hHdDmMwW])(?:USDT|USDC)?",
        r"(?:对|将|把)?\s*([A-Za-z]{2,15})(?:USDT|USDC)?\s*(\d+[hHdDmMwW])?\s*(?:的)?\s*(买入|卖出|做多|做空|buy|sell|long|short)?",
        r"([A-Za-z]{2,15})(?:USDT|USDC)?\s+(\d+[hHdDmMwW])\s*(买入|卖出|做多|做空|buy|sell|long|short)?",
        r"([A-Za-z]{2,15}USDT(?:\.P)?)\s*(\d+[hHdDmMwW])?",
    ]
    for pat in patterns:
        m = re.search(pat, plain, re.IGNORECASE)
        if not m:
            continue
        sym = m.group(1).upper().replace(".P", "")
        if not sym.endswith(("USDT", "USDC")) and classify_maybe_crypto(sym):
            sym = f"{sym}USDT"
        tf = (m.group(2) or "").strip() if m.lastindex and m.lastindex >= 2 else ""
        act_raw = m.group(3) if m.lastindex and m.lastindex >= 3 else ""
        parsed.update(
            {
                "symbol": sym,
                "timeframe": tf,
                "action": _action_to_api(act_raw or plain, ""),
            }
        )
        break

    if not parsed["action"]:
        parsed["action"] = _action_to_api(plain, "")
    return parsed


def _extract_symbol_from_text(text: str) -> str:
    m = re.search(r"([A-Za-z]{2,15}(?:USDT|USDC)?)", text or "", re.I)
    if not m:
        return ""
    sym = m.group(1).upper().replace(".P", "")
    if not sym.endswith(("USDT", "USDC")) and classify_maybe_crypto(sym):
        sym = f"{sym}USDT"
    return sym


def _extract_replied_timestamp(replied: Any) -> Optional[float]:
    if not isinstance(replied, dict):
        return None
    for key in ("createAt", "sendTime", "sentTime", "msgTime", "createdAt"):
        raw = replied.get(key)
        if raw is None:
            continue
        try:
            ts = float(raw)
            if ts > 1e12:
                ts /= 1000.0
            if ts > 0:
                return ts
        except (TypeError, ValueError):
            continue
    return None


def _get_replied_msg(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    text_block = raw.get("text")
    if isinstance(text_block, dict) and isinstance(text_block.get("repliedMsg"), dict):
        return text_block["repliedMsg"]
    for key in ("repliedMsg", "quoteMessage", "quotedMessage"):
        if isinstance(raw.get(key), dict):
            return raw[key]
    return None


def _ambiguous_symbols_from_hints(hints: list[str], *, max_age_sec: int = 7200) -> list[str]:
    from backpack_quant_trading.core.dingtalk_signal_cache import find_cached_signals_by_hint

    symbols: set[str] = set()
    for hint in hints:
        matches = find_cached_signals_by_hint(hint, max_age_sec=max_age_sec)
        syms = {str(m.get("symbol") or "").upper() for m in matches if m.get("symbol")}
        if len(syms) > 1:
            return sorted(syms)
        symbols.update(syms)
    return []
    from backpack_quant_trading.core.signal_asset_router import classify_signal_asset

    return classify_signal_asset(sym) == "crypto"


def resolve_signal_for_scoring(
    user_text: str,
    raw: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], str]:
    """
    综合引用正文 / 用户指令 / 缓存信号，返回 (parsed, source_hint)。
    不会盲目使用「最新一条」——多信号并存时必须能唯一匹配。
    """
    hints = _collect_quote_hints(user_text, raw)
    hint_blob = " | ".join(hints)[:300]

    inline = parse_inline_score_request(user_text)
    if inline.get("symbol"):
        inline["resolve_source"] = "inline"
        return enrich_parsed_signal(inline), "inline"

    for hint in hints:
        parsed = parse_dingtalk_signal_text(hint)
        if parsed.get("symbol"):
            parsed["resolve_source"] = "quoted"
            return enrich_parsed_signal(parsed), hint_blob or "quoted"

    ambiguous = _ambiguous_symbols_from_hints(hints)
    if ambiguous:
        return None, f"ambiguous:{','.join(ambiguous)}"

    matched_cache: Optional[Dict[str, Any]] = None
    for hint in hints:
        sym = _extract_symbol_from_text(hint)
        if sym:
            from backpack_quant_trading.core.dingtalk_signal_cache import find_cached_signal_by_symbol

            by_sym = find_cached_signal_by_symbol(sym)
            if by_sym:
                matched_cache = by_sym
                break
        by_hint = find_cached_signal_by_hint(hint)
        if by_hint:
            matched_cache = by_hint
            break

    if matched_cache:
        for hint in hints:
            partial = parse_dingtalk_signal_text(hint)
            merged = _merge_partial_with_cache(
                partial, matched_cache, source="quote_hint+cache"
            )
            if merged and merged.get("symbol"):
                merged["resolve_source"] = "quote_hint+cache"
                return enrich_parsed_signal(merged), hint_blob or "partial+cache"
        return enrich_parsed_signal(_parsed_from_cache(matched_cache, source="hint+cache")), hint_blob or "hint+cache"

    if _is_reply_message(raw):
        replied = _get_replied_msg(raw)
        if replied:
            from backpack_quant_trading.core.dingtalk_signal_cache import find_cached_signal_by_reply_time

            ts = _extract_replied_timestamp(replied)
            if ts:
                by_time = find_cached_signal_by_reply_time(ts)
                if by_time:
                    return _parsed_from_cache(by_time, source="reply_time"), hint_blob or "reply_time"

    if is_manual_score_command(user_text) and not _has_explicit_symbol(user_text):
        from backpack_quant_trading.core.dingtalk_signal_cache import cache_signal_count, get_latest_cached_signal

        if cache_signal_count(max_age_sec=7200) == 1:
            only = get_latest_cached_signal(max_age_sec=7200)
            if only and only.get("symbol"):
                return _parsed_from_cache(only, source="cache_only_one"), hint_blob or "cache_only_one"

    return None, hint_blob


def get_latest_cached_signal(*, max_age_sec: int = 7200) -> Optional[Dict[str, Any]]:
    from backpack_quant_trading.core.dingtalk_signal_cache import get_latest_cached_signal as _get

    return _get(max_age_sec=max_age_sec)


def find_cached_signal_by_hint(hint: str, *, max_age_sec: int = 7200) -> Optional[Dict[str, Any]]:
    from backpack_quant_trading.core.dingtalk_signal_cache import find_cached_signal_by_hint as _find

    return _find(hint, max_age_sec=max_age_sec)


def classify_maybe_crypto(sym: str) -> bool:
    from backpack_quant_trading.core.signal_asset_router import classify_signal_asset

    return classify_signal_asset(sym) == "crypto"


def _action_to_api(signal_type: str, strategy: str = "") -> str:
    """
    从「信号类型」解析 buy/sell。
    策略名里的「做空/做多」表示策略方向，不直接当作 action（与 crypto_signal_scorer 一致）。
    """
    s = (signal_type or "").strip()
    slow = s.lower()
    if not s:
        return ""
    if any(k in slow for k in ("sell", "short")) or "卖" in s or "看空" in s:
        return "sell"
    if any(k in slow for k in ("buy", "long")) or "买" in s or "看多" in s:
        return "buy"
    if "清空" in s or "平仓" in s:
        return "sell"
    return ""


def infer_strategy_side(strategy: str) -> str:
    """策略名称含「做空」→ short，否则 long。"""
    from backpack_quant_trading.core.crypto_signal_scorer import infer_strategy_is_short

    return "short" if infer_strategy_is_short(strategy) else "long"


def is_open_signal(action: str, strategy: str) -> bool:
    """开仓：做空策略的卖出 / 做多策略的买入。"""
    from backpack_quant_trading.core.crypto_signal_scorer import is_close_signal

    if not (strategy or "").strip():
        return True
    return not is_close_signal(action, strategy_name=strategy)


def describe_signal_role(action: str, strategy: str) -> str:
    """人类可读：做多开仓 / 做空开仓 / 平多 / 平空。"""
    side = infer_strategy_side(strategy)
    if is_open_signal(action, strategy):
        return "做空开仓" if side == "short" else "做多开仓"
    return "平空" if side == "short" else "平多"


def enrich_parsed_signal(parsed: Dict[str, Any]) -> Dict[str, Any]:
    """补全 action、策略方向、是否开仓。"""
    out = dict(parsed or {})
    strategy = str(out.get("strategy") or "").strip()
    raw_action = str(out.get("action") or out.get("signal") or "").strip()
    if not raw_action or raw_action.lower() in ("buy", "sell"):
        api_action = raw_action.lower() if raw_action.lower() in ("buy", "sell") else _action_to_api(raw_action, "")
    else:
        api_action = _action_to_api(raw_action, "")
    if api_action:
        out["action"] = api_action
    out["strategy_side"] = infer_strategy_side(strategy) if strategy else ""
    out["is_open_signal"] = is_open_signal(out.get("action") or "", strategy) if strategy else True
    out["signal_role"] = describe_signal_role(out.get("action") or "", strategy) if strategy else ""
    return out


def _infer_symbol_from_strategy(strategy: str) -> str:
    if not strategy:
        return ""
    m = re.search(
        r"策略[:：]?\s*([A-Za-z]{2,15})(?=(?:USDT)?(?:买入|卖出|做空|做多|信号|$))",
        strategy,
        re.IGNORECASE,
    )
    if m:
        base = m.group(1).upper()
        return base if base.endswith(("USDT", "USDC")) else f"{base}USDT"
    m2 = re.search(r"^([A-Za-z]{2,15})(\d+[hHdDmMwW])", strategy.strip())
    if m2:
        base = m2.group(1).upper()
        return base if base.endswith(("USDT", "USDC")) else f"{base}USDT"
    return ""


def _infer_timeframe(strategy: str, explicit: str = "") -> str:
    if explicit:
        return explicit.strip()
    m = re.search(r"(\d+[hHdDmMwW])", strategy or "")
    return m.group(1) if m else ""


def parse_dingtalk_signal_text(text: str) -> Dict[str, Any]:
    """
    解析钉钉信号卡片（沐龙基金 / tradingview_bot markdown 格式）。
    支持字段：交易品种、信号类型、策略名称、周期。
    """
    clean = normalize_dingtalk_markdown(text)
    parsed: Dict[str, Any] = {
        "symbol": "",
        "action": "",
        "timeframe": "",
        "strategy": "",
        "raw_text": clean[:2000],
    }
    if not clean:
        return parsed

    symbol = _pick(r"交易品种[:：]\s*([A-Za-z0-9.]+)", clean)
    signal_type = _pick(r"信号类型[:：]\s*([^\s，,。]+)", clean)
    strategy = _pick(r"策略名称[:：]\s*([^\n，,。]+)", clean)
    timeframe = _pick(r"周期[:：]\s*([^\s，,。]+)", clean)

    if not strategy:
        # 引用条可能只有「沐龙基金: eth2h做空信号」或「2h进2h出信号」
        strategy = _pick(r"[:：]\s*([A-Za-z0-9\u4e00-\u9fff]+信号?)", clean)
        strategy = re.sub(r"信号$", "", strategy).strip()
    if not strategy:
        strategy = _pick(r"([\d]+\s*[hHdDmMwW]\s*进\s*[\d]+\s*[hHdDmMwW]\s*出)", clean)
        strategy = re.sub(r"\s+", "", strategy)

    if not symbol:
        symbol = _pick(r"成交币种[:：]\s*([A-Za-z0-9.]+)", clean) or _pick(
            r"([A-Za-z]{2,15}USDT(?:\.P)?)", clean
        )

    if not symbol and strategy:
        symbol = _infer_symbol_from_strategy(strategy)

    if not timeframe:
        timeframe = _infer_timeframe(strategy)

    direction = _pick(r"方向[:：]\s*(\w+)", clean)
    action = _action_to_api(signal_type or direction, strategy)

    parsed.update(
        {
            "symbol": (symbol or "").upper().replace(".P", ""),
            "action": action,
            "timeframe": timeframe,
            "strategy": strategy,
        }
    )
    return enrich_parsed_signal(parsed)


def build_manual_webhook_raw(parsed: Dict[str, Any], *, sender_id: str = "") -> Dict[str, Any]:
    return {
        "manual_test": True,
        "test": True,
        "dingtalk_manual": True,
        "source": "dingtalk_reply",
        "sender_id": sender_id,
        "策略名称": parsed.get("strategy"),
        "交易品种": parsed.get("symbol"),
        "方向": parsed.get("action"),
        "周期": parsed.get("timeframe"),
    }


def run_manual_score_from_parsed(
    parsed: Dict[str, Any],
    *,
    sender_id: str = "",
) -> Dict[str, Any]:
    from backpack_quant_trading.core.crypto_signal_scorer import format_dingtalk_message
    from backpack_quant_trading.core.signal_asset_router import run_signal_score_routed

    symbol = (parsed.get("symbol") or "").strip()
    action = (parsed.get("action") or "buy").strip().lower()
    timeframe = (parsed.get("timeframe") or "").strip()
    strategy = (parsed.get("strategy") or "").strip()
    parsed = enrich_parsed_signal(parsed)
    action = (parsed.get("action") or action).strip().lower()
    strategy = (parsed.get("strategy") or strategy).strip()

    if not symbol:
        return {
            "ok": False,
            "error": "未能从被回复的消息中识别交易品种，请回复完整信号卡片后再 @我",
        }

    if strategy and not parsed.get("is_open_signal", True):
        role = parsed.get("signal_role") or "平仓"
        return {
            "ok": False,
            "error": (
                f"这是{role}信号，手动评分仅支持开仓："
                f"做空策略的「卖出」、做多策略的「买入」。"
            ),
        }

    webhook_raw = build_manual_webhook_raw(parsed, sender_id=sender_id)
    result = run_signal_score_routed(
        symbol,
        action,
        timeframe=timeframe,
        webhook_raw=webhook_raw,
        strategy_label="dingtalk_manual",
        strategy_name=strategy or None,
        skip_gate=True,
    )
    if not result.get("ok"):
        return result

    snapshot = result.get("snapshot") or {}
    ds = result.get("deepseek") or {}
    reply_md = format_dingtalk_message(
        result.get("symbol") or symbol,
        result.get("action") or action,
        snapshot,
        ds,
        timeframe=result.get("timeframe") or timeframe,
    )
    result["reply_markdown"] = reply_md
    st = ds.get("structured") or {}
    score_val = int(result.get("score") or st.get("score") or 0)
    from backpack_quant_trading.core.crypto_signal_scorer import (
        _poster_action_cn,
        _poster_rec_label,
    )

    _, rec_cn = _poster_rec_label(str(st.get("recommendation") or ""))
    result["reply_title"] = (
        f"{result.get('symbol') or symbol} {_poster_action_cn(action)} · AI {score_val}分 · {rec_cn}"
    )
    return result


def score_manual_parsed(
    parsed: Dict[str, Any],
    *,
    sender_id: str = "",
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """已解析好的信号直接评分，返回 (回复正文, result)。"""
    result = run_manual_score_from_parsed(parsed, sender_id=sender_id)
    if not result.get("ok"):
        err = result.get("error") or "评分失败"
        return f"评分未完成：{err}", result
    return result.get("reply_markdown") or "评分完成", result


def parse_and_score_from_dingtalk_reply(
    user_text: str,
    quoted_text: str,
    *,
    sender_id: str = "",
    raw: Optional[Dict[str, Any]] = None,
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    Returns:
        (reply_text_or_markdown, score_result)
        若第二条为 dict 且含 reply_markdown，调用方应 reply_markdown。
    """
    if not is_manual_score_command(user_text):
        return (
            "请回复一条交易信号，并 @我 发送「评分」或「对这个信号进行评分」。\n"
            "也可直接写：@我 对 ETH 2h 买入 评分",
            None,
        )

    parsed: Optional[Dict[str, Any]] = None
    resolve_hint = quoted_text
    if raw:
        parsed, resolve_hint = resolve_signal_for_scoring(user_text, raw)
    elif quoted_text and quoted_text.strip():
        parsed = parse_dingtalk_signal_text(quoted_text)
        if parsed.get("symbol"):
            parsed["resolve_source"] = "quoted"

    if not parsed or not parsed.get("symbol"):
        return (
            "没能认出要评哪条信号。你可以：\n"
            "· 回复信号后 @我「评一下分」\n"
            "· 或直接 @我：对 ETH 2h 买入 评分",
            None,
        )

    logger.info(
        "[钉钉手动评分] 解析 source=%s symbol=%s action=%s tf=%s strategy=%s hint=%s",
        parsed.get("resolve_source"),
        parsed.get("symbol"),
        parsed.get("action"),
        parsed.get("timeframe"),
        parsed.get("strategy"),
        (resolve_hint or "")[:120],
    )
    return score_manual_parsed(parsed, sender_id=sender_id)
