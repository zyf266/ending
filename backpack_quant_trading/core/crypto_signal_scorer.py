"""实盘 Webhook 买入信号：Hyperliquid K 线技术指标 + DeepSeek 评分 + 钉钉推送。"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests

from backpack_quant_trading.core.crypto_uptrend_scanner import (
    analyze_uptrend,
    compute_technical_indicators,
    fetch_klines_crypto,
    klines_to_df,
    load_scan_cache,
)
from backpack_quant_trading.core.hyperliquid_klines import to_hl_coin
from backpack_quant_trading.core.stock_news_alert import ensure_dingtalk_keyword, send_dingtalk_text

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
CONFIG_PATH = DATA_DIR / "crypto_signal_scorer_config.json"
HISTORY_PATH = DATA_DIR / "crypto_signal_scorer_history.json"

DEFAULT_WEBHOOK = (
    "https://oapi.dingtalk.com/robot/send?"
    "access_token=5c0c5fc145b217a7a10ec0d6356ae24d9dd31b620ccb4be0251ff729e5cd0adb"
)

_DEFAULT_CONFIG: Dict[str, Any] = {
    "webhook_scorer_enabled": True,
    "dingtalk_webhook": DEFAULT_WEBHOOK,
    "dingtalk_keyword": "提醒",
    "kline_interval": "4h",
    "kline_limit": 100,
    "min_deepseek_score": 0,
    "scan_top_n": 50,
    "only_actions": ["buy", "买入", "long"],
    "deepseek_temperature": 0.2,
}

_SYSTEM_PROMPT = """你是一名严谨的加密货币量化交易风控分析师。
根据用户提供的结构化技术指标与买入信号上下文，对「当前是否适合执行该买入」进行评分与说明。

你必须只输出一个 JSON 对象（不要 markdown 代码块），字段：
{
  "score": 0-100 的整数（越高越建议执行买入）,
  "grade": "A"|"B"| "C"|"D"|"F",
  "recommendation": "execute"|"caution"|"reject",
  "summary": "一两句话结论",
  "strengths": ["..."],
  "risks": ["..."],
  "volume_vs_golden_cross": "对金叉量能与前几次金叉量能对比的一句话",
  "rsi_comment": "RSI 解读",
  "macd_comment": "MACD 解读",
  "trend_comment": "趋势结构解读"
}

评分参考：
- 金叉量能明显放大、MACD 柱转正且抬升、RSI 45-65、ADX>20、价在 EMA20/50 上方 → 加分
- RSI>75 或 <35、MACD 死叉、量能萎缩、远离均线追高 → 减分
"""

_history_lock = threading.Lock()


def load_config() -> Dict[str, Any]:
    cfg = dict(_DEFAULT_CONFIG)
    if CONFIG_PATH.is_file():
        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                cfg.update(raw)
        except Exception:
            pass
    return cfg


def save_config(updates: Dict[str, Any]) -> Dict[str, Any]:
    cfg = load_config()
    cfg.update(updates or {})
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return cfg


def _normalize_symbol(symbol: str) -> str:
    s = (symbol or "").upper().strip()
    for suffix in ("USDT.P", "USDC.P", "USDT", "USDC", "USD", "PERP"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    return s


def to_binance_futures_symbol(symbol: str) -> str:
    """兼容旧名：实际返回 Hyperliquid 币种名。"""
    return to_hl_coin(_normalize_symbol(symbol))


def _tf_map_webhook(tf: str) -> str:
    t = (tf or "").strip().upper()
    mapping = {
        "1": "1m", "3": "3m", "5": "5m", "15": "15m", "30": "30m", "45": "45m",
        "60": "1h", "120": "2h", "240": "4h", "360": "6h", "480": "8h", "720": "12h",
        "1440": "1d", "D": "1d", "1D": "1d", "1W": "1w", "W": "1w",
        "1H": "1h", "2H": "2h", "4H": "4h",
    }
    return mapping.get(t, t.lower() if t else "")


def build_indicator_snapshot(
    symbol: str,
    *,
    interval: Optional[str] = None,
    kline_limit: Optional[int] = None,
) -> Tuple[Optional[Dict[str, Any]], str]:
    """拉取 Hyperliquid K 线并生成指标快照（供 DeepSeek 与钉钉）。"""
    cfg = load_config()
    hl_coin = to_hl_coin(symbol)
    iv = interval or cfg.get("kline_interval") or "4h"
    limit = int(kline_limit or cfg.get("kline_limit") or 100)

    klines = fetch_klines_crypto(hl_coin, iv, total_limit=limit)
    if not klines or len(klines) < 100:
        return None, f"Hyperliquid K 线不足: {hl_coin} {iv} ({len(klines) if klines else 0} 根)"

    df = klines_to_df(klines)
    df = compute_technical_indicators(df)
    is_up, metrics, chart = analyze_uptrend(df, min_bars=min(60, len(df) - 1))

    # 最近 10 根摘要
    tail = df.tail(10)
    recent_bars = []
    for _, row in tail.iterrows():
        recent_bars.append({
            "time": datetime.fromtimestamp(int(row["time"]) / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "close": round(float(row["close"]), 6),
            "volume": round(float(row["volume"]), 2),
            "rsi14": round(float(row["rsi14"]), 2) if pd.notna(row.get("rsi14")) else None,
            "macd_hist": round(float(row["macd_hist"]), 6) if pd.notna(row.get("macd_hist")) else None,
        })

    scan_cache = load_scan_cache() or {}
    in_top50_uptrend = _normalize_symbol(symbol) in (scan_cache.get("uptrend_symbols") or [])

    snapshot = {
        "symbol": _normalize_symbol(symbol),
        "hl_coin": hl_coin,
        "data_source": "hyperliquid",
        "binance_symbol": hl_coin,
        "interval": iv,
        "kline_count": len(df),
        "scanner_uptrend": is_up,
        "in_top50_uptrend_list": in_top50_uptrend,
        "metrics": metrics,
        "recent_bars": recent_bars,
        "chart_tail": chart[-60:] if chart else [],
    }
    return snapshot, ""


def build_deepseek_user_prompt(
    symbol: str,
    action: str,
    snapshot: Dict[str, Any],
    *,
    timeframe: str = "",
    webhook_raw: Optional[Dict[str, Any]] = None,
    strategy_label: str = "adaptive_long",
) -> str:
    """生成交给 DeepSeek 的用户提示词。"""
    m = snapshot.get("metrics") or {}
    payload = {
        "signal": {
            "symbol": symbol,
            "action": action,
            "timeframe": timeframe or snapshot.get("interval"),
            "strategy": strategy_label,
            "webhook_raw": webhook_raw or {},
            "received_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        },
        "market_structure": {
            "scanner_rule_uptrend": snapshot.get("scanner_uptrend"),
            "in_cached_top50_uptrend_scan": snapshot.get("in_top50_uptrend_list"),
        },
        "indicators_latest": m,
        "analysis_tasks": [
            "1) 对比最近一次金叉与前 1-3 次金叉的成交量(vol_ratio / last_golden_cross_vol_vs_prev_avg)，判断放量是否支持突破",
            "2) RSI14 是否处于健康多头区间(约45-70)，是否超买/超卖",
            "3) MACD 柱体方向与 ema20/ema50 结构是否一致",
            "4) ADX、ATR、布林带%B、20/50 根收益率、量能比 vol_ratio",
            "5) OBV 近 10 根斜率(见 recent_bars)",
            "6) 综合给出 score 与 recommendation",
        ],
        "recent_bars": snapshot.get("recent_bars"),
    }
    return (
        f"请对以下「{symbol} {action}」实盘 Webhook 买入信号进行量化评分。\n\n"
        f"结构化数据（JSON）：\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def _extract_json_block(text: str) -> Dict[str, Any]:
    if not text:
        return {}
    m = re.search(r"```json\s*(\{[\s\S]*?\})\s*```", text)
    if not m:
        m = re.search(r"(\{[\s\S]*\})\s*$", text.strip())
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except Exception:
        return {}


def call_deepseek_score(user_prompt: str, temperature: float = 0.2) -> Dict[str, Any]:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        return {"ok": False, "error": "未配置 DEEPSEEK_API_KEY"}

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
    }
    try:
        r = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=120,
        )
        data = r.json()
    except Exception as e:
        return {"ok": False, "error": f"DeepSeek 网络错误: {e!r}"}

    if r.status_code != 200 or not data.get("choices"):
        err = data.get("error", {})
        if isinstance(err, dict):
            err = err.get("message", str(data))
        return {"ok": False, "error": f"DeepSeek 失败: {err}"}

    content = data["choices"][0]["message"]["content"] or ""
    structured = _extract_json_block(content)
    if not structured and content.strip().startswith("{"):
        try:
            structured = json.loads(content.strip())
        except Exception:
            structured = {}
    return {"ok": True, "markdown": content, "structured": structured}


def format_dingtalk_message(
    symbol: str,
    action: str,
    snapshot: Dict[str, Any],
    deepseek: Dict[str, Any],
    *,
    timeframe: str = "",
) -> str:
    cfg = load_config()
    kw = cfg.get("dingtalk_keyword") or "提醒"
    m = snapshot.get("metrics") or {}
    st = deepseek.get("structured") or {}
    score = st.get("score", "—")
    grade = st.get("grade", "—")
    rec = st.get("recommendation", "—")
    summary = st.get("summary") or deepseek.get("markdown", "")[:400]

    lines = [
        f"【{kw}】【买入信号 AI 评分】",
        f"标的: {symbol} | 方向: {action} | 周期: {timeframe or snapshot.get('interval', '—')}",
        f"评分: {score}/100 ({grade}) | 建议: {rec}",
        f"结论: {summary}",
        "",
        "— 关键指标 —",
        f"收盘: {m.get('close')} | RSI14: {m.get('rsi14')} | MACD柱: {m.get('macd_hist')}",
        f"ADX: {m.get('adx14')} | 量比(vol/MA20): {m.get('vol_ratio')} | BB%B: {m.get('bb_pct_b')}",
        f"20根涨跌%: {m.get('return_20_bars_pct')} | 金叉次数: {m.get('golden_cross_count')}",
        f"最近金叉量能 vs 前几次均量: {m.get('last_golden_cross_vol_vs_prev_avg')}",
        f"规则扫描上涨趋势: {'是' if snapshot.get('scanner_uptrend') else '否'}",
        f"Top50上涨池: {'是' if snapshot.get('in_top50_uptrend_list') else '否'}",
    ]
    risks = st.get("risks") or []
    if risks:
        lines.append("风险: " + "；".join(str(x) for x in risks[:4]))
    return "\n".join(lines)


def _append_history(entry: Dict[str, Any]) -> None:
    with _history_lock:
        items: List[Dict[str, Any]] = []
        if HISTORY_PATH.is_file():
            try:
                items = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
            except Exception:
                items = []
        if not isinstance(items, list):
            items = []
        items.insert(0, entry)
        items = items[:200]
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        HISTORY_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def list_score_history(limit: int = 50) -> List[Dict[str, Any]]:
    if not HISTORY_PATH.is_file():
        return []
    try:
        items = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        return items[: max(1, limit)] if isinstance(items, list) else []
    except Exception:
        return []


def run_signal_score_and_push(
    symbol: str,
    action: str,
    *,
    timeframe: str = "",
    webhook_raw: Optional[Dict[str, Any]] = None,
    strategy_label: str = "adaptive_long",
) -> Dict[str, Any]:
    """同步执行：指标 → DeepSeek → 钉钉。供 API 测试与后台线程。"""
    cfg = load_config()
    sym = _normalize_symbol(symbol)
    action_l = (action or "").lower().strip()

    snapshot, err = build_indicator_snapshot(
        sym,
        interval=_tf_map_webhook(timeframe) or cfg.get("kline_interval"),
        kline_limit=cfg.get("kline_limit"),
    )
    if not snapshot:
        return {"ok": False, "error": err or "指标构建失败"}

    user_prompt = build_deepseek_user_prompt(
        sym, action_l, snapshot,
        timeframe=timeframe,
        webhook_raw=webhook_raw,
        strategy_label=strategy_label,
    )
    ds = call_deepseek_score(user_prompt, temperature=float(cfg.get("deepseek_temperature") or 0.2))
    if not ds.get("ok"):
        return {"ok": False, "error": ds.get("error"), "snapshot": snapshot, "user_prompt": user_prompt}

    st = ds.get("structured") or {}
    min_score = int(cfg.get("min_deepseek_score") or 0)
    score_val = int(st.get("score") or 0) if str(st.get("score", "")).isdigit() else 0

    ding_ok, ding_msg = False, "skipped"
    webhook_url = (cfg.get("dingtalk_webhook") or DEFAULT_WEBHOOK).strip()
    if webhook_url and score_val >= min_score:
        body = format_dingtalk_message(sym, action_l, snapshot, ds, timeframe=timeframe)
        ding_ok, ding_msg = send_dingtalk_text(webhook_url, body)

    entry = {
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "symbol": sym,
        "action": action_l,
        "timeframe": timeframe,
        "score": st.get("score"),
        "grade": st.get("grade"),
        "recommendation": st.get("recommendation"),
        "dingtalk_ok": ding_ok,
        "dingtalk_msg": ding_msg,
        "deepseek_summary": st.get("summary"),
    }
    _append_history(entry)

    return {
        "ok": True,
        "symbol": sym,
        "action": action_l,
        "snapshot": snapshot,
        "deepseek": ds,
        "user_prompt": user_prompt,
        "dingtalk_ok": ding_ok,
        "dingtalk_msg": ding_msg,
    }


def should_score_webhook_action(action: str) -> bool:
    cfg = load_config()
    if not cfg.get("webhook_scorer_enabled", True):
        return False
    a = (action or "").lower().strip()
    allowed = [str(x).lower() for x in (cfg.get("only_actions") or ["buy"])]
    return a in allowed or "买" in a


def schedule_webhook_signal_score(
    symbol: str,
    action: str,
    *,
    timeframe: str = "",
    webhook_raw: Optional[Dict[str, Any]] = None,
    strategy_label: str = "adaptive_long",
) -> None:
    """Webhook 快速返回后，后台线程执行评分推送。"""
    if not should_score_webhook_action(action):
        return

    def _job():
        try:
            run_signal_score_and_push(
                symbol,
                action,
                timeframe=timeframe,
                webhook_raw=webhook_raw,
                strategy_label=strategy_label,
            )
        except Exception as e:
            logger.exception("Webhook 信号 AI 评分失败 %s %s: %s", symbol, action, e)

    threading.Thread(target=_job, daemon=True, name=f"signal-score-{symbol}").start()
