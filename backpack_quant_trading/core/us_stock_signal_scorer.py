"""美股 Webhook / 手动信号 AI 评分（Massive K 线 + 新闻 + DeepSeek）。"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

from backpack_quant_trading.core.crypto_uptrend_scanner import (
    analyze_uptrend,
    compute_technical_indicators,
    klines_to_df,
)
from backpack_quant_trading.core.crypto_signal_scorer import (
    compose_final_score,
    compute_support_resistance_levels,
    compute_local_buy_score,
    evaluate_hard_gates,
    evaluate_rebound_strength,
    load_config,
    push_score_to_dingtalk,
    score_to_grade,
)
from backpack_quant_trading.core.massive_klines import (
    fetch_klines_us,
    interval_label,
    normalize_us_ticker,
)
from backpack_quant_trading.core.us_stock_news import fetch_us_stock_news_context

_US_STOCK_SYSTEM_PROMPT = """你是美股量化风控分析师，对「买入/卖出信号」做 0–100 评分。须结合技术面与 recent_news 消息面，评分稳定可复现。

## 输出格式
只输出一个 JSON 对象（不要 markdown），字段与加密版相同：
{
  "score": 整数 0-100,
  "grade": "A"|"B"|"C"|"D"|"F",
  "recommendation": "execute"|"caution"|"reject",
  "summary": "一两句话（须提及新闻面若有关键事件）",
  "strengths": ["..."],
  "risks": ["..."],
  "volume_vs_golden_cross": "一句话",
  "rsi_comment": "一句话",
  "macd_comment": "一句话",
  "trend_comment": "一句话",
  "news_comment": "一句话：近期新闻对多空的影响",
  "support_resistance": {
    "summary": "...",
    "stop_hint": "...",
    "target_hint": "..."
  },
  "score_breakdown": {"structure":0-30,"momentum":0-25,"volume":0-20,"risk_penalty":0-25}
}

## 技术面（美股专用校准，见 scoring_guidance.projected_score）
structure / momentum / volume / risk_penalty 四维；**rebound_strength.strength_score** 为 0–100 动能刻度。
综合 score 以 scoring_guidance.projected_score 为准（本地公式计算，勿盲跟模型 95+）。
公式：0.50×动能 + 0.32×锚分 − 0.50×execution_penalty + 微调；**无固定封顶**，靠动能/锚分/penalty/微调拉开差距。
强修复+放量 82–92；强反弹但缩量/贴压/RSI高 68–82 caution；弱修复 52–65。

## 消息面（美股必看 recent_news）
- 业绩 beat/miss、指引上下调、回购/拆股、重大合同 → 调整 momentum 或 risk_penalty
- 监管调查、诉讼、CEO 变动、宏观突发利空 → 提高 risk_penalty，必要时 force_caution_only
- 新闻与技术同向（利好+上升趋势）可适度加分；新闻与技术背离须 caution 或 reject
- 无相关新闻时不臆造，news_comment 写「近期无重大个股新闻」
- 勿参考加密 Top50 池（in_cached_top50_uptrend_scan 等），美股无此概念

## 建议映射
- score>=76 且 execute_eligible 且新闻无重大利空 → execute
- 52–75 或新闻中性/ mixed → caution
- <52 或 hard_gates.force_reject 或重大利空 → reject
"""


def _f_us(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        return float(x)
    except (TypeError, ValueError):
        return default


def _us_stock_differentiation_nudge(metrics: Dict[str, Any]) -> float:
    """个股微调：recent/vol/adx/trend 连续拉开差距（非封顶）。"""
    m = metrics or {}
    recent = _f_us(m.get("recent_change_pct"))
    vol = _f_us(m.get("vol_ratio"), 1.0)
    adx = _f_us(m.get("adx14"))
    trend = _f_us(m.get("trend_score"))
    ret20 = _f_us(m.get("return_20_bars_pct"))
    n = min(12.0, max(-8.0, recent * 0.85))
    if vol < 0.35:
        n *= max(0.45, vol / 0.35)
    n += min(8.0, max(-7.0, (vol - 1.0) * 14.0))
    n += min(6.0, max(-5.0, (adx - 22.0) * 0.50))
    n += min(6.0, max(-6.0, (trend - 50.0) * 0.18))
    n += min(5.0, max(-5.0, ret20 * 0.12))
    gc_vol = m.get("last_golden_cross_vol_vs_prev_avg")
    if gc_vol is not None:
        n += min(5.0, max(-5.0, (_f_us(gc_vol) - 1.0) * 10.0))
    return n


def _us_stock_execution_penalty(
    metrics: Dict[str, Any],
    gates: Dict[str, Any],
    rebound: Dict[str, Any],
    news_ctx: Optional[Dict[str, Any]] = None,
) -> float:
    """美股可执行性扣分（0–32）：极度缩量/贴压/RSI 过高等。"""
    m = metrics or {}
    penalty = 0.0
    vol_ratio = _f_us(m.get("vol_ratio"), 1.0)

    if vol_ratio < 0.12:
        penalty += 18.0 + max(0.0, (0.12 - vol_ratio) * 90.0)
    elif vol_ratio < 0.25:
        penalty += 12.0 + (0.25 - vol_ratio) * 28.0
    elif vol_ratio < 0.35:
        penalty += 6.0 + (0.35 - vol_ratio) * 30.0
    elif vol_ratio < 0.55:
        penalty += (0.55 - vol_ratio) * 12.0
    elif vol_ratio < 0.80:
        penalty += max(0.0, (0.80 - vol_ratio) * 3.0)

    res_dist = m.get("resistance_dist_pct")
    try:
        rd = float(res_dist) if res_dist is not None else None
    except (TypeError, ValueError):
        rd = None
    if rd is not None and 0 < rd < 0.6:
        penalty += 8.0 if vol_ratio >= 0.12 else 4.0
    elif rd is not None and rd < 1.2:
        penalty += 4.0 if vol_ratio >= 0.12 else 2.0

    rsi = _f_us(m.get("rsi14"), 50.0)
    if rsi > 72:
        penalty += 5.0 if rsi > 78 else 3.0

    if gates.get("force_caution_only"):
        penalty += 6.0
    elif not gates.get("execute_eligible"):
        penalty += 3.0

    gc_vol = m.get("last_golden_cross_vol_vs_prev_avg")
    if gc_vol is not None and _f_us(gc_vol) < 0.75:
        penalty += 3.0
    elif vol_ratio >= 1.15:
        penalty = max(0.0, penalty - 3.0)

    if int((gates.get("mtf_boost") or {}).get("count") or 0) >= 2:
        penalty = max(0.0, penalty - 2.0)

    news = news_ctx or {}
    summary = str(news.get("summary_text") or "").lower()
    if any(k in summary for k in ("investigation", "lawsuit", "sec ", "下调", "miss", "cut guidance", "warning")):
        penalty += 8.0
    elif any(k in summary for k in ("beat", "上调", "raise", "buyback", "超预期")):
        penalty = max(0.0, penalty - 4.0)

    return min(32.0, max(0.0, penalty))


def _us_stock_project_score(
    anchor: int,
    rb: int,
    penalty: float,
    metrics: Dict[str, Any],
    *,
    raw: Optional[int] = None,
) -> int:
    raw_cap = min(
        float(raw if raw is not None else anchor),
        float(anchor) + 6.0,
        float(rb) + 6.0,
    )
    return compose_final_score(
        rb,
        anchor,
        raw_cap,
        penalty,
        _us_stock_differentiation_nudge(metrics),
    )


def build_us_stock_score_guidance(
    snapshot: Dict[str, Any],
    news_ctx: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """美股 scoring_guidance（独立于加密 build_score_guidance）。"""
    from backpack_quant_trading.core.crypto_signal_scorer import (
        _pick_recovery_context,
        evaluate_mtf_boost_signals,
        evaluate_signal_tf_bounce,
        evaluate_strong_recovery,
    )

    m = snapshot.get("metrics") or {}
    anchor = compute_local_buy_score(m)
    gates = evaluate_hard_gates(m)
    rebound = evaluate_rebound_strength(m)
    recovery_ctx = gates.get("recovery_context") or _pick_recovery_context(m)
    recovery = gates.get("strong_recovery") or evaluate_strong_recovery(m)
    signal_bounce = gates.get("signal_bounce") or evaluate_signal_tf_bounce(m)
    mtf = gates.get("mtf_boost") or evaluate_mtf_boost_signals(m)
    rb = rebound["strength_score"]
    penalty = _us_stock_execution_penalty(m, gates, rebound, news_ctx)
    proj = _us_stock_project_score(anchor, rb, penalty, m)

    if gates["force_reject"]:
        hint_rec, band = "reject", "35-48"
    elif gates["force_caution_only"]:
        hint_rec, band = "caution", f"{max(50, proj - 10)}-{min(82, proj + 8)}"
    elif rebound["tier"] == "strong":
        hint_rec = "caution" if rebound.get("volume_limited") or not gates["execute_eligible"] else "execute"
        band = f"{max(58, proj - 12)}-{min(94, proj + 10)}"
    elif rebound["tier"] == "moderate":
        hint_rec = "caution" if not gates["execute_eligible"] else "execute"
        band = f"{max(52, proj - 14)}-{min(88, proj + 8)}"
    else:
        hint_rec = "caution"
        band = f"{max(48, proj - 14)}-{min(84, proj + 10)}"

    return {
        "local_anchor_score": anchor,
        "hard_gates": gates,
        "recovery_context": recovery_ctx,
        "strong_recovery": recovery,
        "signal_bounce": signal_bounce,
        "mtf_boost": mtf,
        "rebound_strength": rebound,
        "execution_penalty": round(penalty, 1),
        "projected_score": proj,
        "hint_recommendation": hint_rec,
        "hint_score_band": band,
        "trend_score_local": m.get("trend_score"),
        "us_stock_news_required": True,
    }


def calibrate_us_stock_structured(
    structured: Dict[str, Any],
    metrics: Dict[str, Any],
    news_ctx: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """美股 DeepSeek 输出校准（独立于 calibrate_deepseek_structured）。"""
    st = dict(structured or {})
    anchor = compute_local_buy_score(metrics)
    gates = evaluate_hard_gates(metrics)
    try:
        raw = int(float(st.get("score", anchor)))
    except (TypeError, ValueError):
        raw = anchor

    rebound = evaluate_rebound_strength(metrics)
    rb = rebound["strength_score"]
    penalty = _us_stock_execution_penalty(metrics, gates, rebound, news_ctx)

    if gates["force_reject"]:
        final, rec = min(raw, anchor, 40), "reject"
    elif gates["force_caution_only"]:
        final = max(52, min(72, int(round(0.25 * raw + 0.75 * anchor))))
        rec = "caution"
    else:
        vol_limited = rebound.get("volume_limited")
        final = _us_stock_project_score(anchor, rb, penalty, metrics, raw=raw)
        final = max(0, min(100, final))
        recovery = gates.get("recovery_context") or gates.get("strong_recovery") or {}
        min_anchor_exec = 58 if recovery.get("tier") == "strong" else 62 if recovery.get("detected") else 68
        if (
            final >= 76
            and anchor >= min_anchor_exec
            and gates["execute_eligible"]
            and not vol_limited
            and penalty < 12
        ):
            rec = "execute"
        elif final >= 52:
            rec = "caution"
        else:
            rec = "reject"

    st["score"] = final
    st["grade"] = score_to_grade(final)
    st["recommendation"] = rec
    st["local_anchor_score"] = anchor
    st["execution_penalty"] = round(penalty, 1)
    st["rebound_strength_score"] = rb
    st["model_raw_score"] = raw
    return st


def build_us_stock_deepseek_user_prompt(
    symbol: str,
    action: str,
    snapshot: Dict[str, Any],
    news_ctx: Dict[str, Any],
    *,
    timeframe: str = "",
    webhook_raw: Optional[Dict[str, Any]] = None,
    strategy_label: str = "us_stock",
    signal_note: str = "",
) -> str:
    from backpack_quant_trading.core.crypto_signal_scorer import build_deepseek_user_prompt

    base = build_deepseek_user_prompt(
        symbol,
        action,
        snapshot,
        timeframe=timeframe,
        webhook_raw=webhook_raw,
        strategy_label=strategy_label,
        signal_note=signal_note,
    )
    marker = "结构化数据（JSON）：\n"
    if marker not in base:
        return base

    prefix, json_part = base.split(marker, 1)
    try:
        payload = json.loads(json_part.strip())
    except json.JSONDecodeError:
        return base

    payload["asset_class"] = "us_stock"
    ms = dict(payload.get("market_structure") or {})
    ms.pop("in_cached_top50_uptrend_scan", None)
    payload["market_structure"] = ms
    payload["recent_news"] = {
        "ticker": news_ctx.get("ticker"),
        "count": news_ctx.get("count", 0),
        "fetched_at_utc": news_ctx.get("fetched_at_utc"),
        "summary_text": news_ctx.get("summary_text"),
        "items": news_ctx.get("items") or [],
    }
    tasks = list(payload.get("analysis_tasks") or [])
    tasks.extend([
        "7) 阅读 recent_news：业绩/指引/监管/宏观事件须反映在 news_comment 与 risk_penalty",
        "8) 重大利空时 recommendation 不得为 execute，即使技术面尚可",
        "9) 无新闻时不扣分，但须在 news_comment 说明",
        "10) 美股无加密 Top50 池概念，勿因 in_cached_top50 或类似字段加减分",
    ])
    payload["analysis_tasks"] = tasks
    guidance = build_us_stock_score_guidance(snapshot, news_ctx)
    payload["scoring_guidance"] = guidance

    return (
        f"{prefix}{marker}"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def call_deepseek_score_us_stock(user_prompt: str, temperature: float = 0.2) -> Dict[str, Any]:
    from backpack_quant_trading.core.crypto_signal_scorer import call_deepseek_json_score

    ds = call_deepseek_json_score(_US_STOCK_SYSTEM_PROMPT, user_prompt, temperature)
    if not ds.get("ok"):
        return ds
    return {"ok": True, "raw": ds.get("markdown"), "structured": ds.get("structured"), "model": ds.get("model")}


def build_us_stock_indicator_snapshot(
    symbol: str,
    *,
    interval: Optional[str] = None,
    kline_limit: Optional[int] = None,
) -> Tuple[Optional[Dict[str, Any]], str]:
    cfg = load_config()
    ticker = normalize_us_ticker(symbol)
    iv = interval_label(interval or cfg.get("us_kline_interval") or cfg.get("kline_interval") or "1d")
    limit = int(kline_limit or cfg.get("kline_limit") or 200)

    klines = fetch_klines_us(ticker, iv, total_limit=limit)
    if not klines or len(klines) < 60:
        return None, f"Massive K 线不足: {ticker} {iv} ({len(klines) if klines else 0} 根)"

    df = klines_to_df(klines)
    df = compute_technical_indicators(df)
    # 美股不走 Hyperliquid 三层过滤；仅用当前 Massive K 线算指标
    is_up, metrics, chart = analyze_uptrend(
        df,
        min_bars=min(60, len(df) - 1),
        hl_coin=None,
    )
    metrics = dict(metrics or {})
    sr = compute_support_resistance_levels(
        df,
        signal_timeframe=iv,
        hl_coin=ticker,
        kline_limit=limit,
        fetch_klines_fn=lambda sym, interval, lim: fetch_klines_us(sym, interval, total_limit=lim),
    )
    if sr:
        metrics.update(sr)

    try:
        from backpack_quant_trading.core.crypto_signal_scorer import compute_mtf_scoring_metrics

        mtf = compute_mtf_scoring_metrics(
            ticker,
            kline_limit=limit,
            fetch_klines_fn=lambda sym, iv, lim: fetch_klines_us(sym, iv, total_limit=lim),
        )
        if mtf:
            metrics.update(mtf)
    except Exception as e:
        logger.debug("us mtf metrics failed %s: %s", ticker, e)

    import pandas as pd

    tail = df.tail(10)
    recent_bars = []
    for _, row in tail.iterrows():
        recent_bars.append({
            "time": datetime.fromtimestamp(int(row["time"]) / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "close": round(float(row["close"]), 4),
            "volume": round(float(row["volume"]), 0),
            "rsi14": round(float(row["rsi14"]), 2) if pd.notna(row.get("rsi14")) else None,
            "macd_hist": round(float(row["macd_hist"]), 6) if pd.notna(row.get("macd_hist")) else None,
        })

    snapshot = {
        "symbol": ticker,
        "hl_coin": ticker,
        "data_source": "massive",
        "binance_symbol": ticker,
        "interval": iv,
        "kline_count": len(df),
        "scanner_uptrend": is_up,
        "metrics": metrics,
        "recent_bars": recent_bars,
        "chart_tail": chart[-60:] if chart else [],
    }
    if not df.empty:
        last_ms = int(df.iloc[-1]["time"])
        snapshot["last_bar_time_utc"] = datetime.fromtimestamp(
            last_ms / 1000, tz=timezone.utc,
        ).strftime("%Y-%m-%d %H:%M UTC")
        try:
            from backpack_quant_trading.core.massive_klines import fetch_massive_last_price

            snapshot["latest_quote"] = fetch_massive_last_price(ticker)
        except Exception:
            snapshot["latest_quote"] = None
    return snapshot, ""


def run_us_stock_signal_score(
    symbol: str,
    action: str = "buy",
    *,
    timeframe: str = "",
    webhook_raw: Optional[Dict[str, Any]] = None,
    strategy_label: str = "us_stock",
) -> Dict[str, Any]:
    from backpack_quant_trading.core.crypto_signal_scorer import (
        _get_cached_score_result,
        _get_cross_process_cached_score,
        _resolve_score_dedupe_key,
        _score_dedupe_sec,
        _set_cached_score_result,
        _set_cross_process_cached_score,
        is_live_trade_us_stock_buy_signal,
        is_manual_score_webhook,
        us_stock_score_enabled,
    )

    if not us_stock_score_enabled():
        ticker = normalize_us_ticker(symbol)
        logger.info("[DeepSeek评分] 美股评分已关闭，跳过 %s", ticker)
        return {
            "ok": False,
            "skipped": True,
            "error": "美股 AI 评分已关闭",
            "symbol": ticker,
            "asset_kind": "us_stock",
        }

    if webhook_raw and not is_manual_score_webhook(webhook_raw):
        if not is_live_trade_us_stock_buy_signal(symbol, action, webhook_raw):
            ticker = normalize_us_ticker(symbol)
            logger.info("[DeepSeek评分] 非实盘交易美股买入，跳过 %s", ticker)
            return {
                "ok": False,
                "skipped": True,
                "error": "仅筛选ID=实盘交易的美股买入信号可调用 AI 评分",
                "symbol": ticker,
                "action": (action or "buy").lower().strip(),
                "asset_kind": "us_stock",
            }

    cfg = load_config()
    ticker = normalize_us_ticker(symbol)
    action_l = (action or "buy").lower().strip()
    iv = interval_label(timeframe) if timeframe else interval_label(cfg.get("us_kline_interval") or "1d")

    dedupe_key = _resolve_score_dedupe_key(ticker, action_l, iv, asset_kind="us_stock")
    cached = _get_cached_score_result(dedupe_key)
    if cached is not None:
        logger.info(
            "[DeepSeek评分] 美股去重命中(内存) %s %s %s（%ss 内不重复调 API）",
            ticker, action_l, iv, _score_dedupe_sec(),
        )
        return cached
    cached = _get_cross_process_cached_score(dedupe_key)
    if cached is not None:
        logger.info(
            "[DeepSeek评分] 美股去重命中(跨进程) %s %s %s（%ss 内不重复调 API）",
            ticker, action_l, iv, _score_dedupe_sec(),
        )
        return cached

    snapshot, err = build_us_stock_indicator_snapshot(ticker, interval=iv, kline_limit=cfg.get("kline_limit"))
    if not snapshot:
        return {"ok": False, "error": err or "指标构建失败", "interval": iv}

    news_ctx = fetch_us_stock_news_context(ticker, max_items=int(cfg.get("us_news_max_items") or 12))
    snapshot["news_context"] = news_ctx

    user_prompt = build_us_stock_deepseek_user_prompt(
        ticker,
        action_l,
        snapshot,
        news_ctx,
        timeframe=timeframe or iv,
        webhook_raw=webhook_raw,
        strategy_label=strategy_label,
    )
    ds = call_deepseek_score_us_stock(
        user_prompt,
        temperature=float(cfg.get("deepseek_temperature") or 0.1),
    )
    if not ds.get("ok"):
        return {"ok": False, "error": ds.get("error"), "interval": iv, "user_prompt": user_prompt}

    structured = calibrate_us_stock_structured(
        ds.get("structured") or {},
        snapshot.get("metrics") or {},
        news_ctx,
    )
    score_val = int(structured.get("score") or 0)
    result = {
        "ok": True,
        "symbol": ticker,
        "action": action_l,
        "interval": iv,
        "timeframe": timeframe or iv,
        "score": score_val,
        "grade": structured.get("grade"),
        "recommendation": structured.get("recommendation"),
        "snapshot": snapshot,
        "deepseek": {**ds, "structured": structured},
        "user_prompt": user_prompt,
        "data_source": "massive",
        "asset_kind": "us_stock",
        "news_count": news_ctx.get("count", 0),
    }
    _set_cached_score_result(dedupe_key, result)
    _set_cross_process_cached_score(dedupe_key, result)
    return result


def run_us_stock_signal_score_and_push(
    symbol: str,
    action: str = "buy",
    *,
    timeframe: str = "",
    webhook_raw: Optional[Dict[str, Any]] = None,
    strategy_label: str = "us_stock",
) -> Dict[str, Any]:
    result = run_us_stock_signal_score(
        symbol, action,
        timeframe=timeframe,
        webhook_raw=webhook_raw,
        strategy_label=strategy_label,
    )
    if result.get("ok"):
        ok, msg = push_score_to_dingtalk(result)
        result["dingtalk_ok"] = ok
        result["dingtalk_msg"] = msg
    return result
