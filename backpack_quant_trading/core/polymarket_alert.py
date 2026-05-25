"""Polymarket 股价触及概率监控：Yes 概率低于阈值时钉钉提醒。"""
from __future__ import annotations

import json
import logging
import os
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Set, Tuple

import requests

from backpack_quant_trading.core.stock_news_alert import (
    DINGTALK_KEYWORD_REMINDER,
    send_dingtalk_text,
)

logger = logging.getLogger("polymarket_alert")

_DATA_DIR = Path(__file__).resolve().parents[1] / "data"
CONFIG_PATH = _DATA_DIR / "polymarket_alert_config.json"
STATE_PATH = _DATA_DIR / "polymarket_alert_state.json"

GAMMA_HOST = "https://gamma-api.polymarket.com"
CLOB_HOST = "https://clob.polymarket.com"

_poll_logs: Deque[Dict[str, Any]] = deque(maxlen=80)
_poll_log_lock = threading.Lock()
_instance: Optional["PolymarketAlertService"] = None
_user_stopped = False


def _trust_env() -> bool:
    return str(os.environ.get("STOCK_NEWS_TRUST_ENV", "")).strip().lower() in ("1", "true", "yes")


def _session() -> requests.Session:
    s = requests.Session()
    s.trust_env = _trust_env()
    s.headers.update({"User-Agent": "Mozilla/5.0 (compatible; backpack-quant/1.0)"})
    return s


def _default_config() -> Dict[str, Any]:
    return {
        "running": False,
        "poll_interval_sec": 60,
        "dingtalk_webhook": "",
        "alert_cooldown_minutes": 30,
        "rules": [],
    }


def load_config() -> Dict[str, Any]:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.is_file():
        base = _default_config()
    else:
        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            base = _default_config()
            if isinstance(raw, dict):
                base.update(raw)
        except Exception as exc:
            logger.warning("读取 polymarket_alert 配置失败: %s", exc)
            base = _default_config()
    if not str(base.get("dingtalk_webhook") or "").strip():
        wh = _fallback_dingtalk_from_stock_news()
        if wh:
            base["dingtalk_webhook"] = wh
    return base


def _fallback_dingtalk_from_stock_news() -> str:
    env = str(os.environ.get("STOCK_NEWS_DINGTALK_WEBHOOK") or "").strip()
    if env:
        return env
    try:
        from backpack_quant_trading.core.stock_news_alert import load_config as load_sn_cfg

        return str(load_sn_cfg().get("dingtalk_webhook") or "").strip()
    except Exception:
        return ""


def resolve_dingtalk_webhook(cfg: Dict[str, Any]) -> str:
    wh = str(cfg.get("dingtalk_webhook") or "").strip()
    if wh:
        return wh
    return _fallback_dingtalk_from_stock_news()


def save_config(cfg: Dict[str, Any]) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    to_save = dict(cfg)
    if CONFIG_PATH.is_file():
        try:
            old = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if not str(to_save.get("dingtalk_webhook") or "").strip():
                old_wh = str(old.get("dingtalk_webhook") or "").strip()
                if old_wh:
                    to_save["dingtalk_webhook"] = old_wh
        except Exception:
            pass
    CONFIG_PATH.write_text(json.dumps(to_save, ensure_ascii=False, indent=2), encoding="utf-8")


def load_state() -> Dict[str, Any]:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not STATE_PATH.is_file():
        return {"rule_alerts": {}}
    try:
        raw = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            alerts = raw.get("rule_alerts")
            if isinstance(alerts, dict):
                return {"rule_alerts": alerts}
    except Exception as exc:
        logger.warning("读取 polymarket_alert 状态失败: %s", exc)
    return {"rule_alerts": {}}


def save_state(state: Dict[str, Any]) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_rules(rules: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not isinstance(rules, list):
        return out
    for i, r in enumerate(rules):
        if not isinstance(r, dict):
            continue
        sym = str(r.get("symbol") or "").strip().upper()
        try:
            price = float(r.get("target_price") or r.get("price") or 0)
        except (TypeError, ValueError):
            continue
        try:
            threshold_pct = float(r.get("threshold_pct") or r.get("probability_pct") or 0)
        except (TypeError, ValueError):
            continue
        if not sym or price <= 0:
            continue
        rid = str(r.get("id") or f"{sym}_{int(price * 100)}").strip()
        out.append(
            {
                "id": rid,
                "symbol": sym,
                "target_price": price,
                "threshold_pct": max(0.0, min(threshold_pct, 100.0)),
                "label": str(r.get("label") or "").strip() or f"{sym} @ ${price:g}",
                "event_id": str(r.get("event_id") or "").strip() or None,
            }
        )
    return out


def _price_tokens(target: float) -> Set[str]:
    t = f"{target:g}"
    return {t, f"${t}", f"${target:.0f}", f"{target:.0f}", f"{target:.2f}"}


def _market_text(m: Dict[str, Any]) -> str:
    return f"{m.get('groupItemTitle') or ''} {m.get('question') or ''}"


def _parse_outcome_prices(raw: Any) -> List[float]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if not isinstance(raw, list):
        return []
    out: List[float] = []
    for x in raw:
        try:
            out.append(float(x))
        except (TypeError, ValueError):
            out.append(0.0)
    return out


def _yes_probability(m: Dict[str, Any]) -> Optional[float]:
    outcomes = m.get("outcomes")
    if isinstance(outcomes, str):
        try:
            outcomes = json.loads(outcomes)
        except json.JSONDecodeError:
            outcomes = []
    prices = _parse_outcome_prices(m.get("outcomePrices"))
    if not prices:
        ltp = m.get("lastTradePrice")
        if ltp is not None:
            try:
                return float(ltp)
            except (TypeError, ValueError):
                pass
        return None
    if isinstance(outcomes, list) and outcomes:
        for idx, name in enumerate(outcomes):
            if str(name).strip().lower() == "yes" and idx < len(prices):
                return prices[idx]
    return prices[0]


def _match_market(markets: List[Dict[str, Any]], symbol: str, target_price: float) -> Optional[Dict[str, Any]]:
    tokens = _price_tokens(target_price)
    sym = symbol.upper()
    best: Optional[Dict[str, Any]] = None
    for m in markets:
        if m.get("closed"):
            continue
        text = _market_text(m)
        if sym not in text.upper() and sym not in (m.get("question") or "").upper():
            # groupItemTitle 可能只有价格箭头，父 event 已含 symbol
            pass
        if not any(tok in text for tok in tokens):
            continue
        best = m
        break
    if best:
        return best
    # 仅按价格匹配（event 已按 symbol 筛过）
    for m in markets:
        if m.get("closed"):
            continue
        text = _market_text(m)
        if any(tok in text for tok in tokens):
            return m
    return None


def search_event_for_symbol(symbol: str, target_price: float) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    sym = symbol.upper()
    q = f"{sym} {target_price:g}"
    try:
        with _session() as sess:
            r = sess.get(f"{GAMMA_HOST}/public-search", params={"q": q}, timeout=20)
        if r.status_code != 200:
            return None, f"搜索失败 HTTP {r.status_code}"
        data = r.json()
        events = data.get("events") if isinstance(data, dict) else []
        if not isinstance(events, list):
            return None, "搜索无结果"
        for ev in events:
            if not isinstance(ev, dict):
                continue
            title = str(ev.get("title") or "")
            ticker = str(ev.get("ticker") or "")
            if sym in title.upper() or sym in ticker.upper() or "hit" in ticker.lower():
                return ev, None
        if events and isinstance(events[0], dict):
            return events[0], None
        return None, f"未找到 {sym} 相关 Polymarket 事件"
    except Exception as exc:
        return None, str(exc)


def fetch_event_markets(event_id: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    try:
        with _session() as sess:
            r = sess.get(f"{GAMMA_HOST}/events", params={"id": event_id}, timeout=20)
        if r.status_code != 200:
            return [], f"事件详情 HTTP {r.status_code}"
        data = r.json()
        if isinstance(data, list):
            ev = data[0] if data else {}
        else:
            ev = data if isinstance(data, dict) else {}
        markets = ev.get("markets") or []
        if not isinstance(markets, list):
            return [], "事件无子市场"
        return markets, None
    except Exception as exc:
        return [], str(exc)


def resolve_rule_market(rule: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[str]]:
    """返回 (event, market, error)。"""
    sym = rule["symbol"]
    price = float(rule["target_price"])
    event_id = rule.get("event_id")
    ev: Optional[Dict[str, Any]] = None
    if event_id:
        markets, err = fetch_event_markets(str(event_id))
        if err:
            return None, None, err
        m = _match_market(markets, sym, price)
        if not m:
            return None, None, f"事件 {event_id} 中未找到 ${price:g} 档位"
        ev = {"id": event_id, "title": rule.get("label") or ""}
        return ev, m, None

    ev, err = search_event_for_symbol(sym, price)
    if err or not ev:
        return None, None, err or "未找到事件"
    eid = str(ev.get("id") or "")
    if not eid:
        return None, None, "事件缺少 id"
    markets, err = fetch_event_markets(eid)
    if err:
        return None, None, err
    m = _match_market(markets, sym, price)
    if not m:
        return None, None, f"未找到 {sym} ${price:g} 对应市场档位"
    rule["event_id"] = eid
    return ev, m, None


def quote_rule(rule: Dict[str, Any]) -> Dict[str, Any]:
    ev, m, err = resolve_rule_market(rule)
    if err or not m:
        return {
            "rule_id": rule.get("id"),
            "symbol": rule.get("symbol"),
            "target_price": rule.get("target_price"),
            "threshold_pct": rule.get("threshold_pct"),
            "ok": False,
            "error": err or "未知错误",
        }
    yes_prob = _yes_probability(m)
    threshold = float(rule.get("threshold_pct") or 0) / 100.0
    triggered = yes_prob is not None and yes_prob < threshold
    return {
        "rule_id": rule.get("id"),
        "symbol": rule.get("symbol"),
        "target_price": rule.get("target_price"),
        "threshold_pct": rule.get("threshold_pct"),
        "label": rule.get("label"),
        "ok": True,
        "event_id": str(ev.get("id") if ev else rule.get("event_id") or ""),
        "event_title": str(ev.get("title") if ev else ""),
        "event_slug": str(ev.get("slug") if ev else ""),
        "market_question": _market_text(m),
        "market_slug": m.get("slug"),
        "yes_probability": yes_prob,
        "yes_probability_pct": round((yes_prob or 0) * 100, 2) if yes_prob is not None else None,
        "triggered": triggered,
        "outcomes": m.get("outcomes"),
        "outcome_prices": m.get("outcomePrices"),
    }


def format_dingtalk_body(rule: Dict[str, Any], quote: Dict[str, Any]) -> str:
    pct = quote.get("yes_probability_pct")
    th = rule.get("threshold_pct")
    sym = rule.get("symbol")
    price = rule.get("target_price")
    title = quote.get("event_title") or rule.get("label") or f"{sym} ${price:g}"
    q = quote.get("market_question") or ""
    slug = quote.get("event_slug") or quote.get("market_slug") or ""
    url = f"https://polymarket.com/event/{slug}" if slug else "https://polymarket.com"
    return (
        f"【{DINGTALK_KEYWORD_REMINDER}】【Polymarket 概率提醒】\n"
        f"{title}\n"
        f"标的: {sym} · 价位 ${price:g}\n"
        f"档位: {q.strip()}\n"
        f"当前 Yes 概率: {pct}%（低于阈值 {th}% 触发提醒）\n"
        f"链接: {url}"
    )


def format_dingtalk_test_body() -> str:
    return (
        f"【{DINGTALK_KEYWORD_REMINDER}】【Polymarket 概率提醒】测试消息："
        f"钉钉关键词「{DINGTALK_KEYWORD_REMINDER}」校验通过。"
    )


def append_poll_log(entry: Dict[str, Any]) -> None:
    with _poll_log_lock:
        _poll_logs.appendleft(entry)


def get_poll_logs(limit: int = 30) -> List[Dict[str, Any]]:
    n = max(1, min(int(limit or 30), 60))
    with _poll_log_lock:
        return list(_poll_logs)[:n]


def get_polymarket_alert_user_stopped() -> bool:
    return _user_stopped


def set_polymarket_alert_user_stopped(v: bool) -> None:
    global _user_stopped
    _user_stopped = bool(v)


def get_polymarket_alert_instance() -> Optional["PolymarketAlertService"]:
    return _instance


def set_polymarket_alert_instance(inst: Optional["PolymarketAlertService"]) -> None:
    global _instance
    _instance = inst


@dataclass
class PolymarketAlertService:
    _running: bool = field(default=False, init=False)
    _thread: Optional[threading.Thread] = field(default=None, init=False)
    _stop: threading.Event = field(default_factory=threading.Event, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    last_error: Optional[str] = field(default=None, init=False)
    last_poll_at: Optional[str] = field(default=None, init=False)
    last_push_count: int = field(default=0, init=False)
    last_poll_summary: Optional[Dict[str, Any]] = field(default=None, init=False)
    last_quotes: List[Dict[str, Any]] = field(default_factory=list, init=False)

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._stop.clear()
            self._running = True
            self._thread = threading.Thread(target=self._loop, name="polymarket-alert", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            self._stop.set()
            self._running = False
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=5.0)
        self._thread = None

    def is_running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    def _loop(self) -> None:
        while not self._stop.is_set():
            cfg = load_config()
            interval = max(30, min(int(cfg.get("poll_interval_sec") or 60), 600))
            try:
                self._tick(cfg)
            except Exception as exc:
                self.last_error = str(exc)
                logger.exception("polymarket_alert tick: %s", exc)
            self.last_poll_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._stop.wait(timeout=interval)

    def _tick(self, cfg: Dict[str, Any]) -> None:
        at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rules = normalize_rules(cfg.get("rules"))
        webhook = resolve_dingtalk_webhook(cfg)
        cooldown_min = max(5, int(cfg.get("alert_cooldown_minutes") or 30))

        if not rules:
            self.last_error = "未配置监控规则"
            self.last_push_count = 0
            self.last_quotes = []
            append_poll_log({"at": at, "message": "跳过：无规则", "error": self.last_error})
            return
        if not webhook:
            self.last_error = "未配置钉钉 Webhook"
            self.last_push_count = 0
            append_poll_log({"at": at, "message": "跳过：无钉钉", "error": self.last_error})
            return

        state = load_state()
        alerts: Dict[str, Any] = dict(state.get("rule_alerts") or {})
        quotes: List[Dict[str, Any]] = []
        pushed = 0
        now_ts = int(datetime.now(timezone.utc).timestamp())

        for rule in rules:
            q = quote_rule(rule)
            quotes.append(q)
            if not q.get("ok"):
                continue
            rid = str(rule.get("id") or "")
            yes_prob = q.get("yes_probability")
            if yes_prob is None:
                continue
            threshold = float(rule.get("threshold_pct") or 0) / 100.0
            prev = alerts.get(rid) or {}
            prev_prob = prev.get("last_yes_prob")
            try:
                prev_f = float(prev_prob) if prev_prob is not None else None
            except (TypeError, ValueError):
                prev_f = None
            last_alert_ts = int(prev.get("last_alert_ts") or 0)
            crossed = prev_f is not None and prev_f >= threshold > yes_prob
            first_below = prev_f is None and yes_prob < threshold
            repeat = (
                yes_prob < threshold
                and last_alert_ts > 0
                and (now_ts - last_alert_ts) >= cooldown_min * 60
            )
            should_alert = yes_prob < threshold and (crossed or first_below or repeat)

            alerts[rid] = {
                "last_yes_prob": yes_prob,
                "last_quote_at": at,
                "last_yes_pct": q.get("yes_probability_pct"),
            }

            if should_alert:
                body = format_dingtalk_body(rule, q)
                ok, msg = send_dingtalk_text(webhook, body)
                if ok:
                    pushed += 1
                    alerts[rid]["last_alert_ts"] = now_ts
                    try:
                        from backpack_quant_trading.core.dingtalk_push_history import record_polymarket_push

                        record_polymarket_push(rule, q)
                    except Exception as exc:
                        logger.warning("记录 Polymarket 推送历史失败: %s", exc)
                    logger.info("Polymarket 钉钉已推送 %s Yes=%.2f%%", rid, yes_prob * 100)
                else:
                    self.last_error = f"钉钉失败: {msg}"
                    logger.error("Polymarket 钉钉失败: %s", msg)

        save_state({"rule_alerts": alerts})
        merged = normalize_rules(cfg.get("rules"))
        eid_map = {str(r.get("id")): r.get("event_id") for r in rules if r.get("event_id")}
        for mr in merged:
            eid = eid_map.get(str(mr.get("id")))
            if eid:
                mr["event_id"] = eid
        cfg["rules"] = merged
        save_config(cfg)

        self.last_quotes = quotes
        self.last_push_count = pushed
        self.last_error = None
        triggered_n = sum(1 for q in quotes if q.get("triggered"))
        summary = {
            "at": at,
            "rules": len(rules),
            "triggered": triggered_n,
            "pushed": pushed,
            "quotes": quotes,
            "message": f"轮询 @ {at} | 规则 {len(rules)} | 低于阈值 {triggered_n} | 推送 {pushed}",
        }
        self.last_poll_summary = summary
        append_poll_log(summary)
        logger.info(summary["message"])


def try_restore_from_disk() -> None:
    if get_polymarket_alert_user_stopped():
        return
    cfg = load_config()
    if not cfg.get("running"):
        return
    if not normalize_rules(cfg.get("rules")):
        logger.warning("polymarket_alert 跳过恢复：无规则")
        return
    if not resolve_dingtalk_webhook(cfg):
        logger.warning("polymarket_alert 跳过恢复：无钉钉")
        return
    inst = get_polymarket_alert_instance()
    if inst and inst.is_running():
        return
    svc = PolymarketAlertService()
    set_polymarket_alert_instance(svc)
    svc.start()
