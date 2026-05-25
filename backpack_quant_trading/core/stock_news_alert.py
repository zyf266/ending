"""
自选关键词 + 多源财经快讯监控：金十 / 同花顺 / 东方财富 / 新浪 / 富途 / 雅虎财经等聚合轮询，匹配后钉钉推送。
轮询摘要写入 log/stock_news_alert.log，并保留最近若干条供前端展示。
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Set, Tuple

import requests

from backpack_quant_trading.core.stock_news_feeds import (
    DEFAULT_JIN10_APP_ID,
    SOURCE_LABELS,
    _normalize_yahoo_search_queries,
    fetch_unified_news_items,
    is_similar_to_items,
    is_similar_to_norms,
    item_already_pushed,
    item_similarity_norm,
    mark_item_pushed,
    normalize_enabled_sources,
)
from backpack_quant_trading.core.stock_news_keyword_i18n import (
    expand_terms,
    text_matches_any_term,
    text_matches_watch_terms,
    watch_names_to_yahoo_queries,
)

DINGTALK_KEYWORD_REMINDER = "提醒"
_POLL_LOG_MAX = 60

logger = logging.getLogger("stock_news_alert")
_poll_log_lock = threading.Lock()
_poll_logs: Deque[Dict[str, Any]] = deque(maxlen=_POLL_LOG_MAX)


def _setup_poll_logger() -> None:
    if logger.handlers:
        return
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", "%Y-%m-%d %H:%M:%S")
    log_dir = Path(__file__).resolve().parents[2] / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(log_dir / "stock_news_alert.log", encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(ch)


_setup_poll_logger()

PROJECT_DATA = Path(__file__).resolve().parents[1] / "data"
CONFIG_PATH = PROJECT_DATA / "stock_news_alert_config.json"
STATE_PATH = PROJECT_DATA / "stock_news_alert_state.json"


def _stock_news_trust_env() -> bool:
    """是否让 requests 使用系统/环境变量里的代理（HTTPS_PROXY 等）。

    默认 False：金十、钉钉直连。许多本机配置了 127.0.0.1:7890 等代理但未启动，
    会触发 ProxyError / WinError 10061。
    若你访问金十或钉钉必须走代理，请设置环境变量 STOCK_NEWS_FORCE_SYSTEM_PROXY=1。
    """
    return os.environ.get("STOCK_NEWS_FORCE_SYSTEM_PROXY", "").lower() in ("1", "true", "yes")

_DEFAULT_IMPACT = (
    "财报,业绩,指引,预增,预减,亏损,盈利,并购,收购,拆分,回购,减持,增持,裁员,罢工,"
    "FDA,NMPA,获批,被拒,诉讼,调查,停牌,复牌,破产,违约,闪崩,大涨,大跌,涨超,跌超,"
    "超预期,不及预期,目标价,评级,突发,召回,制裁,禁令,加息,降息,利率决议,OPEC,原油官方价"
)


def _data_dir() -> Path:
    PROJECT_DATA.mkdir(parents=True, exist_ok=True)
    return PROJECT_DATA


def _default_config() -> Dict[str, Any]:
    return {
        "running": False,
        "watch_names": [],
        "dingtalk_webhook": "",
        "poll_interval_sec": 30,
        "max_news_age_minutes": 120,
        "only_material": True,
        "only_extra_impact_keywords": False,
        "extra_impact_keywords": [],
        "jin10_x_app_id": DEFAULT_JIN10_APP_ID,
        "news_sources": ["jin10", "ths", "eastmoney", "sina", "futu", "yahoo"],
    }


def resolve_dingtalk_webhook(cfg: Dict[str, Any]) -> str:
    wh = str(cfg.get("dingtalk_webhook") or "").strip()
    if wh:
        return wh
    return str(os.environ.get("STOCK_NEWS_DINGTALK_WEBHOOK") or "").strip()


def resolve_jin10_app_id(cfg: Dict[str, Any]) -> str:
    jid = str(cfg.get("jin10_x_app_id") or "").strip()
    if jid:
        return jid
    return str(os.environ.get("JIN10_X_APP_ID") or DEFAULT_JIN10_APP_ID).strip()


def load_config() -> Dict[str, Any]:
    _data_dir()
    if not CONFIG_PATH.is_file():
        base = _default_config()
    else:
        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            base = _default_config()
            if isinstance(raw, dict):
                base.update(raw)
        except Exception as exc:
            logger.warning("读取 stock_news_alert 配置失败: %s", exc)
            base = _default_config()
    if not str(base.get("dingtalk_webhook") or "").strip():
        env_wh = str(os.environ.get("STOCK_NEWS_DINGTALK_WEBHOOK") or "").strip()
        if env_wh:
            base["dingtalk_webhook"] = env_wh
    base["jin10_x_app_id"] = resolve_jin10_app_id(base)
    return base


def save_config(cfg: Dict[str, Any]) -> None:
    _data_dir()
    to_save = dict(cfg)
    if CONFIG_PATH.is_file():
        try:
            old = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if not str(to_save.get("dingtalk_webhook") or "").strip():
                old_wh = str(old.get("dingtalk_webhook") or "").strip()
                if old_wh:
                    to_save["dingtalk_webhook"] = old_wh
            old_watch = old.get("watch_names") or []
            if isinstance(old_watch, str):
                old_watch = [old_watch]
            new_watch = to_save.get("watch_names") or []
            if isinstance(new_watch, str):
                new_watch = [new_watch]
            if not [str(x).strip() for x in new_watch if str(x).strip()] and old_watch:
                to_save["watch_names"] = [str(x).strip() for x in old_watch if str(x).strip()]
        except Exception:
            pass
    CONFIG_PATH.write_text(json.dumps(to_save, ensure_ascii=False, indent=2), encoding="utf-8")


_RECENT_SIM_NORMS_MAX = 120


def load_state() -> Dict[str, Any]:
    _data_dir()
    if not STATE_PATH.is_file():
        return {"pushed_ids": [], "last_poll_ts": None, "recent_similarity_norms": []}
    try:
        raw = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and isinstance(raw.get("pushed_ids"), list):
            out: Dict[str, Any] = {"pushed_ids": [str(x) for x in raw["pushed_ids"]]}
            lpt = raw.get("last_poll_ts")
            if lpt is not None:
                try:
                    out["last_poll_ts"] = int(lpt)
                except (TypeError, ValueError):
                    out["last_poll_ts"] = None
            else:
                out["last_poll_ts"] = None
            norms = raw.get("recent_similarity_norms") or []
            if isinstance(norms, list):
                out["recent_similarity_norms"] = [
                    str(x) for x in norms if isinstance(x, str) and len(x) >= 12
                ][-_RECENT_SIM_NORMS_MAX:]
            else:
                out["recent_similarity_norms"] = []
            return out
    except Exception as exc:
        logger.warning("读取 stock_news_alert 状态失败: %s", exc)
    return {"pushed_ids": [], "last_poll_ts": None, "recent_similarity_norms": []}


def _remember_similarity_norm(norms: List[str], item: Dict[str, Any]) -> None:
    n = item_similarity_norm(item)
    if len(n) < 12:
        return
    if is_similar_to_norms({"text": n}, norms):
        return
    norms.append(n)
    if len(norms) > _RECENT_SIM_NORMS_MAX:
        del norms[: len(norms) - _RECENT_SIM_NORMS_MAX]


def save_state(state: Dict[str, Any]) -> None:
    _data_dir()
    ids: List[str] = state.get("pushed_ids") or []
    if len(ids) > 3000:
        ids = ids[-3000:]
    payload: Dict[str, Any] = {"pushed_ids": ids}
    lpt = state.get("last_poll_ts")
    if lpt is not None:
        try:
            payload["last_poll_ts"] = int(lpt)
        except (TypeError, ValueError):
            pass
    norms = state.get("recent_similarity_norms") or []
    if isinstance(norms, list):
        payload["recent_similarity_norms"] = [
            str(x) for x in norms if isinstance(x, str) and len(x) >= 12
        ][-_RECENT_SIM_NORMS_MAX:]
    STATE_PATH.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _max_news_age_seconds(cfg: Dict[str, Any]) -> int:
    try:
        minutes = int(cfg.get("max_news_age_minutes") or 0)
    except (TypeError, ValueError):
        minutes = 0
    if minutes <= 0:
        poll = int(cfg.get("poll_interval_sec") or 30)
        minutes = max(90, (poll * 2 + 59) // 60)
    return minutes * 60


def _parse_display_time_to_utc_ts(time_s: str) -> Optional[int]:
    s = (time_s or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(s, fmt)
            return int(dt.replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            continue
    return None


def item_published_ts(item: Dict[str, Any]) -> Optional[int]:
    raw = item.get("published_ts")
    if raw is not None:
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
    return _parse_display_time_to_utc_ts(str(item.get("time") or ""))


def is_news_fresh_for_push(
    item: Dict[str, Any],
    cfg: Dict[str, Any],
    last_poll_ts: Optional[int],
) -> bool:
    """仅推送：发布时间在水位线之后，且未超过最大时效（默认约 2 小时）。"""
    pub = item_published_ts(item)
    if pub is None:
        return False
    now_ts = int(datetime.now(timezone.utc).timestamp())
    if now_ts - pub > _max_news_age_seconds(cfg):
        return False
    if last_poll_ts is None:
        return False
    return pub > int(last_poll_ts) - 90


def _impact_keyword_list(cfg: Dict[str, Any]) -> List[str]:
    parts: List[str] = []
    if not cfg.get("only_extra_impact_keywords"):
        parts = [p.strip() for p in _DEFAULT_IMPACT.split(",") if p.strip()]
    extra = cfg.get("extra_impact_keywords") or []
    if isinstance(extra, str):
        extra = [extra]
    if isinstance(extra, list):
        for e in extra:
            s = str(e).strip()
            if s:
                parts.append(s)
    return expand_terms(parts)


def is_material_news(
    text: str,
    important: int,
    keywords: List[str],
    only_material: bool,
    *,
    strict_custom_impact_only: bool = False,
) -> bool:
    """是否满足「重要快讯」过滤。

    strict_custom_impact_only=True（对应 only_extra_impact_keywords）时，
    不再因金十 important 标记放行，必须正文命中自定义影响面词。
    """
    if not only_material:
        return True
    if not strict_custom_impact_only and important and important != 0:
        return True
    return text_matches_any_term(text, keywords)


def matches_watch(text: str, watch_names: List[str], item: Optional[Dict[str, Any]] = None) -> bool:
    if not watch_names:
        return False
    expanded = expand_terms(watch_names)
    if text_matches_watch_terms(text, expanded):
        return True
    if item:
        tickers = item.get("related_tickers") or []
        if isinstance(tickers, list):
            ticker_set = {str(x).strip().casefold() for x in tickers if str(x).strip()}
            for alias in expanded:
                a = str(alias).strip().casefold()
                if a and a in ticker_set:
                    return True
    return False


def ensure_dingtalk_keyword(content: str) -> str:
    """钉钉机器人若开启自定义关键词，正文须包含「提醒」。"""
    text = content or ""
    if DINGTALK_KEYWORD_REMINDER not in text:
        text = f"【{DINGTALK_KEYWORD_REMINDER}】\n{text}"
    return text


def format_dingtalk_push_body(item: Dict[str, Any]) -> str:
    url_line = f"\n链接: {item['url']}" if str(item.get("url") or "").strip() else ""
    return (
        f"【{DINGTALK_KEYWORD_REMINDER}】【自选快讯】{item.get('feed') or '快讯'}\n"
        f"{item.get('time') or ''}\n"
        f"{item.get('text') or ''}"
        f"{url_line}\n"
        f"id: {item.get('dedupe_id') or ''}"
    )


def format_dingtalk_test_body() -> str:
    return (
        f"【{DINGTALK_KEYWORD_REMINDER}】【自选快讯】测试消息：配置成功，"
        f"钉钉关键词「{DINGTALK_KEYWORD_REMINDER}」校验通过。"
    )


def append_poll_log(entry: Dict[str, Any]) -> None:
    with _poll_log_lock:
        _poll_logs.appendleft(entry)


def get_poll_logs(limit: int = 30) -> List[Dict[str, Any]]:
    n = max(1, min(int(limit or 30), _POLL_LOG_MAX))
    with _poll_log_lock:
        return list(_poll_logs)[:n]


def send_dingtalk_text(webhook_url: str, content: str, timeout: float = 8.0) -> Tuple[bool, str]:
    url = (webhook_url or "").strip()
    if not url.startswith("https://oapi.dingtalk.com/robot/send"):
        return False, "钉钉地址需为 https://oapi.dingtalk.com/robot/send?... "
    content = ensure_dingtalk_keyword(content)
    if len(content) > 18000:
        content = content[:17900] + "\n...(截断)"
    payload = {"msgtype": "text", "text": {"content": content}}
    try:
        with requests.Session() as sess:
            sess.trust_env = _stock_news_trust_env()
            r = sess.post(url, json=payload, timeout=timeout)
        if r.status_code != 200:
            return False, f"HTTP {r.status_code} {r.text[:500]}"
        try:
            j = r.json()
        except Exception:
            return True, "ok"
        if isinstance(j, dict) and j.get("errcode") == 0:
            return True, "ok"
        return False, str(j)
    except Exception as exc:
        return False, str(exc)


_instance: Optional["StockNewsAlertService"] = None
_user_stopped = False


def get_stock_news_alert_user_stopped() -> bool:
    return _user_stopped


def set_stock_news_alert_user_stopped(v: bool) -> None:
    global _user_stopped
    _user_stopped = bool(v)


def get_stock_news_alert_instance() -> Optional["StockNewsAlertService"]:
    return _instance


def set_stock_news_alert_instance(inst: Optional["StockNewsAlertService"]) -> None:
    global _instance
    _instance = inst


@dataclass
class StockNewsAlertService:
    """后台线程轮询金十快讯。"""

    _running: bool = field(default=False, init=False)
    _thread: Optional[threading.Thread] = field(default=None, init=False)
    _stop: threading.Event = field(default_factory=threading.Event, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    last_error: Optional[str] = field(default=None, init=False)
    last_poll_at: Optional[str] = field(default=None, init=False)
    last_push_count: int = field(default=0, init=False)
    last_poll_summary: Optional[Dict[str, Any]] = field(default=None, init=False)

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._stop.clear()
            self._running = True
            self._thread = threading.Thread(target=self._loop, name="stock-news-alert", daemon=True)
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
            interval = int(cfg.get("poll_interval_sec") or 30)
            interval = max(10, min(interval, 300))
            try:
                self._tick(cfg)
            except Exception as exc:
                self.last_error = str(exc)
                logger.exception("stock_news_alert tick: %s", exc)
            self.last_poll_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._stop.wait(timeout=interval)

    def _record_poll(
        self,
        *,
        at: str,
        enabled_list: List[str],
        watch: List[str],
        only_material: bool,
        fetch_by_source: Dict[str, int],
        errors: Dict[str, Optional[str]],
        stats: Dict[str, int],
        matched_samples: List[Dict[str, str]],
        message: str,
        error: Optional[str] = None,
    ) -> None:
        entry = {
            "at": at,
            "enabled_sources": enabled_list,
            "watch": watch,
            "only_material": only_material,
            "fetch_by_source": fetch_by_source,
            "fetch_total": sum(fetch_by_source.values()),
            "errors": {k: errors.get(k) for k in enabled_list},
            "stats": stats,
            "matched_samples": matched_samples,
            "message": message,
            "error": error,
        }
        self.last_poll_summary = entry
        append_poll_log(entry)
        logger.info(message)
        if error:
            logger.warning("轮询异常: %s", error)

    def _tick(self, cfg: Dict[str, Any]) -> None:
        at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        watch = cfg.get("watch_names") or []
        if isinstance(watch, str):
            watch = [watch]
        watch = [str(x).strip() for x in watch if str(x).strip()]
        webhook = resolve_dingtalk_webhook(cfg)
        only_material = bool(cfg.get("only_material", True))
        x_app = resolve_jin10_app_id(cfg)
        enabled_list = normalize_enabled_sources(cfg)

        if not watch:
            self.last_error = "未配置自选关键词（请先点「仅保存配置」）"
            self.last_push_count = 0
            self._record_poll(
                at=at,
                enabled_list=enabled_list,
                watch=watch,
                only_material=only_material,
                fetch_by_source={},
                errors={},
                stats={},
                matched_samples=[],
                message="轮询跳过：服务端配置中无自选关键词，请保存后再启动",
                error=self.last_error,
            )
            return
        if not webhook:
            self.last_error = "未配置钉钉 Webhook"
            self.last_push_count = 0
            self._record_poll(
                at=at,
                enabled_list=enabled_list,
                watch=watch,
                only_material=only_material,
                fetch_by_source={},
                errors={},
                stats={},
                matched_samples=[],
                message="轮询跳过：未配置钉钉 Webhook",
                error=self.last_error,
            )
            return

        items, errs = fetch_unified_news_items(cfg, jin10_x_app_id=x_app)
        fetch_by_source: Dict[str, int] = {k: 0 for k in enabled_list}
        for it in items:
            fk = str(it.get("feed_key") or "")
            if fk in fetch_by_source:
                fetch_by_source[fk] += 1
        all_fail = bool(enabled_list) and all(errs.get(k) is not None for k in enabled_list)
        if not items and all_fail:
            self.last_error = "; ".join(f"{k}: {errs[k]}" for k in enabled_list)[:600]
            self.last_push_count = 0
            err_parts = [
                f"{SOURCE_LABELS.get(k, k)}:{errs[k]}"
                for k in enabled_list
                if errs.get(k)
            ]
            self._record_poll(
                at=at,
                enabled_list=enabled_list,
                watch=watch,
                only_material=only_material,
                fetch_by_source=fetch_by_source,
                errors=errs,
                stats={},
                matched_samples=[],
                message=f"轮询失败：全部数据源异常 ({'; '.join(err_parts)})",
                error=self.last_error,
            )
            return

        state = load_state()
        pushed: Set[str] = set(state.get("pushed_ids") or [])
        recent_norms: List[str] = list(state.get("recent_similarity_norms") or [])
        last_poll_ts = state.get("last_poll_ts")
        try:
            last_poll_ts = int(last_poll_ts) if last_poll_ts is not None else None
        except (TypeError, ValueError):
            last_poll_ts = None
        kws = _impact_keyword_list(cfg)
        bootstrap = last_poll_ts is None

        stats = {
            "skipped_pushed": 0,
            "skipped_no_watch": 0,
            "skipped_not_material": 0,
            "skipped_no_id": 0,
            "skipped_not_fresh": 0,
            "skipped_bootstrap_seed": 0,
            "skipped_similar": 0,
            "matched": 0,
            "pushed_ok": 0,
        }
        to_send: List[Dict[str, Any]] = []
        matched_samples: List[Dict[str, str]] = []

        for item in items:
            if not str(item.get("dedupe_id") or "").strip():
                stats["skipped_no_id"] += 1
                continue
            if item_already_pushed(pushed, item):
                stats["skipped_pushed"] += 1
                continue
            if not matches_watch(item["text"], watch, item):
                stats["skipped_no_watch"] += 1
                continue
            imp = int(item.get("important") or 0)
            strict_impact = bool(cfg.get("only_extra_impact_keywords"))
            if not is_material_news(
                item["text"],
                imp,
                kws,
                only_material,
                strict_custom_impact_only=strict_impact,
            ):
                stats["skipped_not_material"] += 1
                continue
            if bootstrap:
                mark_item_pushed(pushed, item)
                _remember_similarity_norm(recent_norms, item)
                stats["skipped_bootstrap_seed"] += 1
                continue
            if not is_news_fresh_for_push(item, cfg, last_poll_ts):
                stats["skipped_not_fresh"] += 1
                continue
            if is_similar_to_norms(item, recent_norms) or is_similar_to_items(item, to_send):
                mark_item_pushed(pushed, item)
                _remember_similarity_norm(recent_norms, item)
                stats["skipped_similar"] += 1
                continue
            stats["matched"] += 1
            to_send.append(item)
            if len(matched_samples) < 5:
                matched_samples.append(
                    {
                        "feed": str(item.get("feed") or ""),
                        "time": str(item.get("time") or ""),
                        "text": (str(item.get("text") or ""))[:200],
                    }
                )

        self.last_push_count = len(to_send)
        self.last_error = None

        src_detail = ", ".join(
            f"{SOURCE_LABELS.get(k, k)}={fetch_by_source.get(k, 0)}"
            for k in enabled_list
        )
        yahoo_q_note = ""
        if "yahoo" in enabled_list:
            yq = watch_names_to_yahoo_queries(watch)
            if not yq:
                yq = _normalize_yahoo_search_queries(None)
            yahoo_q_note = f" | 雅虎搜索词: {', '.join(yq)}"
        fresh_note = ""
        if bootstrap:
            fresh_note = f" | 首轮已标记 {stats['skipped_bootstrap_seed']} 条为已见(不推送)"
        summary_msg = (
            f"轮询完成 @ {at} | 拉取 {len(items)} 条 ({src_detail}) | "
            f"已推送过 {stats['skipped_pushed']} | 非最新 {stats['skipped_not_fresh']} | "
            f"未命中关键词 {stats['skipped_no_watch']} | "
            f"非重要快讯 {stats['skipped_not_material']} | 内容相似去重 {stats['skipped_similar']} | "
            f"新命中 {stats['matched']} | 待推送 {len(to_send)}"
            f"{yahoo_q_note}{fresh_note}"
        )

        # 按时间正序推送（列表接口通常为最新在前，这里反转发）
        for item in reversed(to_send):
            body = format_dingtalk_push_body(item)
            ok, msg = send_dingtalk_text(webhook, body)
            if ok:
                mark_item_pushed(pushed, item)
                _remember_similarity_norm(recent_norms, item)
                stats["pushed_ok"] += 1
                try:
                    from backpack_quant_trading.core.dingtalk_push_history import record_stock_news_push
                    from backpack_quant_trading.core.research_card_feeds import ingest_stock_news_feed_item

                    record_stock_news_push(item)
                    ingest_stock_news_feed_item(item)
                except Exception as exc:
                    logger.warning("记录钉钉推送历史失败: %s", exc)
                logger.info("已推送钉钉 %s | %s", item.get("dedupe_id"), (item.get("text") or "")[:80])
                save_state(
                    {
                        "pushed_ids": sorted(pushed),
                        "last_poll_ts": int(datetime.now(timezone.utc).timestamp()),
                        "recent_similarity_norms": recent_norms,
                    }
                )
            else:
                self.last_error = f"钉钉失败: {msg}"
                logger.error("钉钉推送失败: %s", msg)
                summary_msg += f" | 钉钉失败: {msg}"
                break

        if stats["pushed_ok"]:
            summary_msg += f" | 已成功推送 {stats['pushed_ok']} 条"

        self._record_poll(
            at=at,
            enabled_list=enabled_list,
            watch=watch,
            only_material=only_material,
            fetch_by_source=fetch_by_source,
            errors=errs,
            stats=stats,
            matched_samples=matched_samples,
            message=summary_msg,
            error=self.last_error,
        )
        save_state(
            {
                "pushed_ids": sorted(pushed),
                "last_poll_ts": int(datetime.now(timezone.utc).timestamp()),
                "recent_similarity_norms": recent_norms,
            }
        )


def try_restore_from_disk() -> None:
    """进程启动时：若配置为 running 且用户未主动停止，则恢复线程。"""
    if get_stock_news_alert_user_stopped():
        return
    cfg = load_config()
    if not cfg.get("running"):
        return
    names = cfg.get("watch_names") or []
    if isinstance(names, str):
        names = [names]
    if not [str(x).strip() for x in names if str(x).strip()]:
        logger.warning("stock_news_alert 跳过恢复：配置中无自选关键词")
        return
    if not resolve_dingtalk_webhook(cfg):
        logger.warning("stock_news_alert 跳过恢复：未配置钉钉 Webhook")
        return
    inst = get_stock_news_alert_instance()
    if inst and inst.is_running():
        return
    svc = StockNewsAlertService()
    set_stock_news_alert_instance(svc)
    svc.start()
