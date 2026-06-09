"""美股 Webhook / 手动信号 AI 评分（Massive K 线 + 新闻 + DeepSeek）。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from backpack_quant_trading.core.crypto_uptrend_scanner import (
    analyze_uptrend,
    compute_technical_indicators,
    klines_to_df,
)
from backpack_quant_trading.core.crypto_signal_scorer import (
    calibrate_deepseek_structured,
    compute_support_resistance_levels,
    load_config,
    push_score_to_dingtalk,
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

## 技术面（与加密相同）
structure / momentum / volume / risk_penalty 四维，须遵守 scoring_guidance.hard_gates。

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
    from backpack_quant_trading.core.crypto_signal_scorer import (
        build_deepseek_user_prompt,
        build_score_guidance,
    )

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
    guidance = build_score_guidance(snapshot)
    guidance["us_stock_news_required"] = True
    payload["scoring_guidance"] = guidance

    return (
        f"{prefix}{marker}"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def call_deepseek_score_us_stock(user_prompt: str, temperature: float = 0.2) -> Dict[str, Any]:
    import os
    import re

    import requests

    from backpack_quant_trading.core.crypto_signal_scorer import _extract_json_block

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        return {"ok": False, "error": "未配置 DEEPSEEK_API_KEY"}

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": _US_STOCK_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
    }
    try:
        s = requests.Session()
        s.trust_env = False
        r = s.post(
            "https://api.deepseek.com/chat/completions",
            headers=headers,
            json=payload,
            timeout=90,
        )
        r.raise_for_status()
        content = (r.json().get("choices") or [{}])[0].get("message", {}).get("content") or ""
        structured = _extract_json_block(content)
        return {"ok": True, "raw": content, "structured": structured}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


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
    cfg = load_config()
    ticker = normalize_us_ticker(symbol)
    action_l = (action or "buy").lower().strip()
    iv = interval_label(timeframe) if timeframe else interval_label(cfg.get("us_kline_interval") or "1d")

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

    structured = calibrate_deepseek_structured(
        ds.get("structured") or {},
        snapshot.get("metrics") or {},
    )
    score_val = int(structured.get("score") or 0)
    return {
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
