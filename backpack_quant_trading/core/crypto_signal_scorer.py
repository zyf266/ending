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
    # 钉钉推送（与实盘开单无关）
    "dingtalk_on_webhook_enabled": True,
    "webhook_scorer_enabled": True,  # 兼容旧字段，等同 dingtalk_on_webhook_enabled
    "dingtalk_webhook": DEFAULT_WEBHOOK,
    "dingtalk_keyword": "提醒",
    "min_deepseek_score_for_dingtalk": 0,
    "min_deepseek_score": 0,  # 兼容旧字段
    "kline_interval": "4h",
    "kline_limit": 200,
    "scan_top_n": 50,
    "only_actions": ["buy", "买入", "long"],
    "deepseek_temperature": 0.1,
}

_SYSTEM_PROMPT = """你是加密货币量化风控分析师，对「买入信号」做 0–100 评分。评分必须稳定、可复现，禁止凭感觉给分。

## 输出格式
只输出一个 JSON 对象（不要 markdown），字段：
{
  "score": 整数 0-100,
  "grade": "A"|"B"|"C"|"D"|"F",
  "recommendation": "execute"|"caution"|"reject",
  "summary": "一两句话",
  "strengths": ["..."],
  "risks": ["..."],
  "volume_vs_golden_cross": "一句话",
  "rsi_comment": "一句话",
  "macd_comment": "一句话",
  "trend_comment": "一句话",
  "score_breakdown": {"structure":0-30,"momentum":0-25,"volume":0-20,"risk_penalty":0-25}
}

## 评分步骤（必须先算 breakdown 再汇总 score，并与 local_anchor_score 偏差不超过 ±15）
1) structure 0–30：价在 EMA20/50/200 上方、EMA20>EMA50 加分；uptrend_any_tf(任一周期的或)加分；strong_trend_all_tf(三周期且)大幅加分。
2) momentum 0–25：MACD 柱>0 且 macd_hist_rising 加分；recent_change_pct>0 加分；ADX>=25 加分。
3) volume 0–20：vol_ratio>=1 或 last_golden_cross_vol_vs_prev_avg>=1.2 加分；量能萎缩扣分。
4) risk_penalty 0–25（从满分扣）：RSI<40 扣；RSI>75 时：若 ADX>=35 且 MACD 柱仍在抬升，仅轻扣（强势趋势允许超买，勿因 RSI 单独 reject）；若 ADX<25 且 RSI>75 重扣。

## 硬规则（必须遵守 scoring_guidance.hard_gates）
- hard_gates.force_reject=true → score<=42 且 recommendation=reject
- hard_gates.force_caution_only=true → recommendation 不得为 execute（强趋势超买只能 caution）
- hard_gates.execute_eligible=false → recommendation 不得为 execute

## 建议映射（与 score 一致）
- score>=76 且 execute_eligible → execute
- 52–75 → caution
- <52 或 force_reject → reject

## 禁止
- 禁止大量信号都给 70–72 分；分差须体现 structure/momentum/volume 差异。
- 禁止在 ADX>=35、价在 EMA 上方、MACD 抬升时仅因 RSI>75 就给 reject 或低于 50 分。
"""


def _f(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        return float(x)
    except (TypeError, ValueError):
        return default


def evaluate_hard_gates(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """本地硬规则：约束模型输出，减少随意打分。"""
    m = metrics or {}
    above20 = bool(m.get("price_above_ema20"))
    above50 = bool(m.get("price_above_ema50"))
    recent = _f(m.get("recent_change_pct"))
    macd_hist = _f(m.get("macd_hist"))
    macd_rising = bool(m.get("macd_hist_rising"))
    adx = _f(m.get("adx14"))
    rsi = _f(m.get("rsi14"), 50.0)

    uptrend_any = bool(m.get("uptrend_met") or m.get("is_uptrend"))
    strong_trend = bool(m.get("strong_trend") or m.get("bg_conditions_met"))
    force_reject = (
        (m.get("uptrend_met") is False and m.get("filter_name"))
        or ((not above20 and recent <= 0) and not uptrend_any)
        or (macd_hist < 0 and not macd_rising and adx < 20 and not uptrend_any)
        or (recent < -1.0 and not above20 and not uptrend_any)
    )
    force_caution_only = rsi > 82 and adx >= 30 and above20 and macd_hist > 0
    execute_eligible = (
        (
            strong_trend
            or (
                uptrend_any
                and above20
                and above50
                and recent > 0
                and (macd_hist > 0 or macd_rising)
            )
            or (
                above20
                and above50
                and recent > 0
                and (macd_hist > 0 or macd_rising)
                and adx >= 20
                and rsi >= 42
            )
        )
        and not force_caution_only
        and (macd_rising or _f(m.get("vol_ratio")) >= 0.75 or strong_trend)
    )
    return {
        "force_reject": force_reject,
        "force_caution_only": force_caution_only,
        "execute_eligible": execute_eligible,
    }


def compute_local_buy_score(metrics: Dict[str, Any]) -> int:
    """确定性锚分：与回测对齐，供模型参考及输出校准。"""
    m = metrics or {}
    score = 38.0

    # —— 结构（约 0–28）——
    if m.get("price_above_ema20"):
        score += 10
    else:
        score -= 20
    if m.get("price_above_ema50"):
        score += 7
    else:
        score -= 8
    if m.get("ema20_above_ema50"):
        score += 5
    if m.get("uptrend_met") or m.get("is_uptrend"):
        score += 6
    if m.get("strong_trend") or m.get("bg_conditions_met"):
        score += 14
    gc = int(m.get("golden_tf_count") or 0)
    if gc >= 3:
        score += 8
    elif gc == 2:
        score += 4

    # —— 动能（约 0–28）——
    macd_hist = _f(m.get("macd_hist"))
    if macd_hist > 0:
        score += 8
    else:
        score -= 16
    if m.get("macd_hist_rising"):
        score += 6
    elif macd_hist < 0:
        score -= 6

    recent = _f(m.get("recent_change_pct"))
    if recent >= 8:
        score += min(12.0, recent * 0.45)
    elif recent >= 3:
        score += 6
    elif recent > 0.5:
        score += 2
    elif recent > 0:
        score -= 2
    else:
        score -= 16

    adx = _f(m.get("adx14"))
    if adx >= 35:
        score += 10
    elif adx >= 22:
        score += 5
    elif adx < 18:
        score -= 14

    # —— RSI（约 -14 ~ +10）——
    rsi = _f(m.get("rsi14"), 50.0)
    if 48 <= rsi <= 66:
        score += 8
    elif 40 <= rsi < 48:
        score += 2
    elif rsi < 40:
        score -= 12
    elif rsi > 75:
        if adx >= 35 and m.get("macd_hist_rising") and m.get("price_above_ema20"):
            score -= 4
        elif adx >= 25:
            score -= 9
        else:
            score -= 16

    # —— 量能（约 -12 ~ +12）——
    vol_ratio = _f(m.get("vol_ratio"), 1.0)
    if vol_ratio >= 1.15:
        score += 7
    elif vol_ratio >= 0.85:
        score += 2
    elif vol_ratio < 0.65:
        score -= 10

    gc = m.get("last_golden_cross_vol_vs_prev_avg")
    if gc is not None:
        g = _f(gc, 1.0)
        if g >= 1.3:
            score += 7
        elif g >= 1.0:
            score += 3
        elif g < 0.85:
            score -= 8

    # —— 与本地 trend_score 对齐（避免「均线多头但趋势分很低」仍高分）——
    trend = _f(m.get("trend_score"))
    if trend >= 75:
        score += 8
    elif trend >= 55:
        score += 3
    elif trend >= 40:
        score -= 2
    else:
        score -= 12

    # 弱势震荡封顶：近 20 根几乎不涨 + 趋势分偏低
    if recent < 1.5 and trend < 45:
        score = min(score, 58.0)
    if trend < 35:
        score = min(score, 66.0)
    # 极弱结构封顶
    if not m.get("price_above_ema20") or (macd_hist < 0 and not m.get("macd_hist_rising")):
        score = min(score, 42.0)

    return int(max(0, min(100, round(score))))


def score_to_grade(score: int) -> str:
    if score >= 85:
        return "A"
    if score >= 76:
        return "B"
    if score >= 60:
        return "C"
    if score >= 45:
        return "D"
    return "F"


def build_score_guidance(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    m = snapshot.get("metrics") or {}
    anchor = compute_local_buy_score(m)
    gates = evaluate_hard_gates(m)
    if gates["force_reject"]:
        hint_rec = "reject"
        band = "35-48"
    elif gates["force_caution_only"]:
        hint_rec = "caution"
        band = f"{max(52, anchor - 8)}-{min(74, anchor + 8)}"
    elif (
        gates["execute_eligible"]
        and anchor >= 72
        and (m.get("strong_trend") or not m.get("filter_name"))
    ):
        hint_rec = "execute"
        band = f"{max(76, anchor - 5)}-{min(92, anchor + 10)}"
    else:
        hint_rec = "caution"
        band = f"{max(48, anchor - 12)}-{min(75, anchor + 10)}"
    return {
        "local_anchor_score": anchor,
        "hard_gates": gates,
        "hint_recommendation": hint_rec,
        "hint_score_band": band,
        "trend_score_local": m.get("trend_score"),
    }


def calibrate_deepseek_structured(
    structured: Dict[str, Any],
    metrics: Dict[str, Any],
) -> Dict[str, Any]:
    """融合模型分与锚分，使评分稳定并与硬规则一致。"""
    st = dict(structured or {})
    anchor = compute_local_buy_score(metrics)
    gates = evaluate_hard_gates(metrics)
    try:
        raw = int(float(st.get("score", anchor)))
    except (TypeError, ValueError):
        raw = anchor

    if gates["force_reject"]:
        final = min(raw, anchor, 40)
        rec = "reject"
    elif gates["force_caution_only"]:
        blended = int(round(0.25 * raw + 0.75 * anchor))
        final = max(52, min(72, blended))
        rec = "caution"
    else:
        blended = int(round(0.25 * raw + 0.75 * anchor))
        final = max(anchor - 12, min(anchor + 12, blended))
        final = max(0, min(100, final))
        # execute 需锚分也不低，避免模型抬分
        if final >= 76 and anchor >= 68 and gates["execute_eligible"]:
            rec = "execute"
        elif final >= 52:
            rec = "caution"
        else:
            rec = "reject"

    st["score"] = final
    st["grade"] = score_to_grade(final)
    st["recommendation"] = rec
    st["local_anchor_score"] = anchor
    return st

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
    limit = int(kline_limit or cfg.get("kline_limit") or 200)

    klines = fetch_klines_crypto(hl_coin, iv, total_limit=limit)
    # Hyperliquid 有时会返回略少于请求的根数；只要满足指标计算的最小样本即可
    if not klines or len(klines) < 60:
        return None, f"Hyperliquid K 线不足: {hl_coin} {iv} ({len(klines) if klines else 0} 根)"

    df = klines_to_df(klines)
    df = compute_technical_indicators(df)
    is_up, metrics, chart = analyze_uptrend(
        df,
        min_bars=min(60, len(df) - 1),
        hl_coin=hl_coin,
    )

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
    signal_note: str = "",
) -> str:
    """生成交给 DeepSeek 的用户提示词。"""
    m = snapshot.get("metrics") or {}
    guidance = build_score_guidance(snapshot)
    payload = {
        "signal": {
            "symbol": symbol,
            "action": action,
            "timeframe": timeframe or snapshot.get("interval"),
            "strategy": strategy_label,
            "webhook_raw": webhook_raw or {},
            "received_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "note": signal_note or None,
        },
        "market_structure": {
            "scanner_rule_uptrend": snapshot.get("scanner_uptrend"),
            "uptrend_any_tf": m.get("uptrend_met"),
            "strong_trend_all_tf": m.get("strong_trend"),
            "golden_tf_count": m.get("golden_tf_count"),
            "bg1_ok": m.get("bg1_ok"),
            "bg2_ok": m.get("bg2_ok"),
            "bg3_ok": m.get("bg3_ok"),
            "pine_bg_met": m.get("pine_bg_met"),
            "pine_entry_ready": m.get("pine_entry_ready"),
            "entry_trigger_8h_death_cross": m.get("entry_trigger"),
            "exit_conditions_met": m.get("exit_conditions_met"),
            "in_cached_top50_uptrend_scan": snapshot.get("in_top50_uptrend_list"),
        },
        "scoring_guidance": guidance,
        "indicators_latest": m,
        "analysis_tasks": [
            "1) 先填 score_breakdown 四维，再算 score（须落在 hint_score_band 附近）",
            "2) 金叉量能：last_golden_cross_vol_vs_prev_avg 与 vol_ratio",
            "3) MACD 柱方向须与 EMA 结构一致",
            "4) RSI：ADX>=35 且 MACD 抬升时，RSI>75 仅轻罚",
            "5) recommendation 必须符合 hard_gates 与 score 映射",
        ],
        "recent_bars": snapshot.get("recent_bars"),
    }
    return (
        f"请对以下「{symbol} {action}」买入信号评分。务必使用 scoring_guidance 锚分与硬规则。\n\n"
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
        # 默认不信任系统代理：很多机器环境变量里有 127.0.0.1:789x 但代理未启动，会导致 WinError 10061。
        s = requests.Session()
        s.trust_env = False
        r = s.post(
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

    tf = timeframe or snapshot.get("interval", "—")
    action_l = (action or "").lower()
    direction_ico = "🟢" if ("buy" in action_l or "long" in action_l or "买" in action) else ("🔴" if ("sell" in action_l or "short" in action_l or "卖" in action) else "🔔")
    score_ico = "🧠"
    grade_badge = f"`{grade}`" if grade not in (None, "", "—") else "`—`"

    header = f"**{direction_ico} {symbol} · {action} · {tf}**"
    headline = f"**{score_ico} {score}/100**  {grade_badge}  |  **建议**：`{rec}`"

    # 关键指标（紧凑、手机友好）
    close = m.get("close")
    rsi = m.get("rsi14")
    macd = m.get("macd_hist")
    adx = m.get("adx14")
    volr = m.get("vol_ratio")
    ret20 = m.get("return_20_bars_pct")
    uptrend = "✅" if snapshot.get("scanner_uptrend") else "—"
    top50 = "✅" if snapshot.get("in_top50_uptrend_list") else "—"

    strengths = st.get("strengths") or []
    risks = st.get("risks") or []

    lines = [
        f"**【{kw}】AI 评分**",
        header,
        headline,
        "",
        f"> {summary}",
        "",
        "**📌 关键指标**",
        f"- **收盘**：`{close}`   **RSI14**：`{rsi}`   **MACD柱**：`{macd}`",
        f"- **ADX**：`{adx}`   **量比**：`{volr}`   **20根涨跌%**：`{ret20}`",
        f"- **趋势扫描**：{uptrend}   **Top50 上涨池**：{top50}",
    ]

    if strengths:
        lines += [
            "",
            "**✅ 亮点**",
            *[f"- {str(x)}" for x in strengths[:4]],
        ]
    if risks:
        lines += [
            "",
            "**⚠️ 风险**",
            *[f"- {str(x)}" for x in risks[:4]],
        ]

    # 末尾轻量分隔，避免过长
    lines += ["", f"_{symbol} · {tf}_"]
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


def is_buy_action(action: str) -> bool:
    a = (action or "").lower().strip()
    return a in ("buy", "long") or "买" in a


def is_sell_action(action: str) -> bool:
    a = (action or "").lower().strip()
    return a in ("sell", "short") or "卖" in a


def infer_strategy_is_short(strategy_name: str | None) -> bool:
    """按约定：策略名称包含「做空」视为做空策略；否则视为做多。"""
    name = (strategy_name or "").strip()
    return bool(name) and ("做空" in name)


def dingtalk_webhook_enabled() -> bool:
    cfg = load_config()
    if "dingtalk_on_webhook_enabled" in cfg:
        return bool(cfg.get("dingtalk_on_webhook_enabled"))
    return bool(cfg.get("webhook_scorer_enabled", True))


def min_score_for_dingtalk() -> int:
    cfg = load_config()
    return int(
        cfg.get("min_deepseek_score_for_dingtalk")
        if cfg.get("min_deepseek_score_for_dingtalk") is not None
        else (cfg.get("min_deepseek_score") or 0)
    )


def run_signal_score(
    symbol: str,
    action: str,
    *,
    timeframe: str = "",
    webhook_raw: Optional[Dict[str, Any]] = None,
    strategy_label: str = "adaptive_long",
) -> Dict[str, Any]:
    """同步 AI 评分：按 Webhook 币种 + K 线级别从 HL 拉 K 线，不调钉钉、不拦截开单。"""
    cfg = load_config()
    sym = _normalize_symbol(symbol)
    action_l = (action or "").lower().strip()
    iv = _tf_map_webhook(timeframe) or cfg.get("kline_interval") or "4h"

    snapshot, err = build_indicator_snapshot(
        sym,
        interval=iv,
        kline_limit=cfg.get("kline_limit"),
    )
    if not snapshot:
        return {"ok": False, "error": err or "指标构建失败", "interval": iv}

    user_prompt = build_deepseek_user_prompt(
        sym, action_l, snapshot,
        timeframe=timeframe or iv,
        webhook_raw=webhook_raw,
        strategy_label=strategy_label,
    )
    ds = call_deepseek_score(user_prompt, temperature=float(cfg.get("deepseek_temperature") or 0.1))
    if not ds.get("ok"):
        return {
            "ok": False,
            "error": ds.get("error"),
            "snapshot": snapshot,
            "user_prompt": user_prompt,
            "interval": iv,
        }

    m = snapshot.get("metrics") or {}
    st = calibrate_deepseek_structured(ds.get("structured") or {}, m)
    ds["structured"] = st
    ds["local_anchor_score"] = st.get("local_anchor_score")
    try:
        score_val = int(float(st.get("score") or 0))
    except (TypeError, ValueError):
        score_val = 0

    return {
        "ok": True,
        "symbol": sym,
        "action": action_l,
        "interval": iv,
        "timeframe": timeframe or iv,
        "score": score_val,
        "grade": st.get("grade"),
        "recommendation": st.get("recommendation"),
        "snapshot": snapshot,
        "deepseek": ds,
        "user_prompt": user_prompt,
    }


def push_score_to_dingtalk(score_result: Dict[str, Any]) -> Tuple[bool, str]:
    """将已有评分结果推送到钉钉（与实盘开单无关）。"""
    if not score_result.get("ok"):
        return False, score_result.get("error") or "评分失败"
    cfg = load_config()
    min_score = min_score_for_dingtalk()
    score_val = int(score_result.get("score") or 0)
    if score_val < min_score:
        return False, f"skipped: score {score_val} < min {min_score}"

    sym = score_result.get("symbol") or ""
    action_l = score_result.get("action") or "buy"
    snapshot = score_result.get("snapshot") or {}
    ds = score_result.get("deepseek") or {}
    tf = score_result.get("timeframe") or ""

    webhook_url = (cfg.get("dingtalk_webhook") or DEFAULT_WEBHOOK).strip()
    if not webhook_url:
        return False, "未配置钉钉 Webhook"
    body = format_dingtalk_message(sym, action_l, snapshot, ds, timeframe=tf)
    return send_dingtalk_text(webhook_url, body)


def run_signal_score_and_push_dingtalk(
    symbol: str,
    action: str,
    *,
    timeframe: str = "",
    webhook_raw: Optional[Dict[str, Any]] = None,
    strategy_label: str = "adaptive_long",
) -> Dict[str, Any]:
    """路径2：Webhook 买入 → HL K线(信号周期) → DeepSeek → 钉钉（不决定是否开单）。"""
    result = run_signal_score(
        symbol, action,
        timeframe=timeframe,
        webhook_raw=webhook_raw,
        strategy_label=strategy_label,
    )
    ding_ok, ding_msg = False, "skipped"
    if result.get("ok"):
        ding_ok, ding_msg = push_score_to_dingtalk(result)
    st = (result.get("deepseek") or {}).get("structured") or {}
    entry = {
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "symbol": result.get("symbol"),
        "action": result.get("action"),
        "timeframe": result.get("timeframe"),
        "score": result.get("score"),
        "grade": result.get("grade") or st.get("grade"),
        "recommendation": result.get("recommendation") or st.get("recommendation"),
        "dingtalk_ok": ding_ok,
        "dingtalk_msg": ding_msg,
        "deepseek_summary": st.get("summary"),
        "channel": "dingtalk",
    }
    _append_history(entry)
    result["dingtalk_ok"] = ding_ok
    result["dingtalk_msg"] = ding_msg
    return result


def run_signal_score_and_push(
    symbol: str,
    action: str,
    *,
    timeframe: str = "",
    webhook_raw: Optional[Dict[str, Any]] = None,
    strategy_label: str = "adaptive_long",
) -> Dict[str, Any]:
    """兼容：测试接口仍走评分+钉钉。"""
    return run_signal_score_and_push_dingtalk(
        symbol, action,
        timeframe=timeframe,
        webhook_raw=webhook_raw,
        strategy_label=strategy_label,
    )


def should_score_webhook_action(action: str, *, strategy_name: str | None = None) -> bool:
    if not dingtalk_webhook_enabled():
        return False

    # 新规则：策略名称决定信号方向
    # - 名称含「做空」→ 只分析卖出信号
    # - 不含 → 只分析买入信号
    if strategy_name:
        if infer_strategy_is_short(strategy_name):
            return is_sell_action(action)
        return is_buy_action(action)

    # 兼容旧逻辑：仅对买入信号评分（并受 only_actions 控制）
    if not is_buy_action(action):
        return False
    allowed = [str(x).lower() for x in (load_config().get("only_actions") or ["buy"])]
    a = (action or "").lower().strip()
    return a in allowed or "买" in a


def schedule_webhook_dingtalk_score(
    symbol: str,
    action: str,
    *,
    timeframe: str = "",
    webhook_raw: Optional[Dict[str, Any]] = None,
    strategy_label: str = "adaptive_long",
    strategy_name: str | None = None,
) -> None:
    """路径2：Webhook 后台线程 → 钉钉推送（与实盘开单无关）。"""
    if not should_score_webhook_action(action, strategy_name=strategy_name):
        return

    def _job():
        try:
            run_signal_score_and_push_dingtalk(
                symbol,
                action,
                timeframe=timeframe,
                webhook_raw=webhook_raw,
                strategy_label=strategy_label,
            )
        except Exception as e:
            logger.exception("Webhook 钉钉 AI 评分失败 %s %s: %s", symbol, action, e)

    threading.Thread(
        target=_job, daemon=True, name=f"dingtalk-score-{symbol}",
    ).start()


def schedule_webhook_signal_score(
    symbol: str,
    action: str,
    *,
    timeframe: str = "",
    webhook_raw: Optional[Dict[str, Any]] = None,
    strategy_label: str = "adaptive_long",
) -> None:
    """兼容旧名：仅钉钉推送。"""
    schedule_webhook_dingtalk_score(
        symbol, action,
        timeframe=timeframe,
        webhook_raw=webhook_raw,
        strategy_label=strategy_label,
    )
