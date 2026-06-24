"""实盘 Webhook 买入信号：Hyperliquid K 线技术指标 + DeepSeek 评分 + 钉钉推送。"""
from __future__ import annotations

import json
import logging
import os
import re
import socket
import threading
import time
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

import pandas as pd
import requests

from backpack_quant_trading.core.crypto_uptrend_scanner import (
    analyze_uptrend,
    compute_technical_indicators,
    fetch_klines_crypto,
    klines_to_df,
    load_scan_cache,
    tv_tf_to_hl,
)
from backpack_quant_trading.core.hyperliquid_klines import to_hl_coin
from backpack_quant_trading.core.stock_news_alert import (
    ensure_dingtalk_keyword,
    send_dingtalk_markdown,
    send_dingtalk_text,
)

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
CONFIG_PATH = DATA_DIR / "crypto_signal_scorer_config.json"
HISTORY_PATH = DATA_DIR / "crypto_signal_scorer_history.json"
USAGE_PATH = DATA_DIR / "deepseek_score_usage.json"
USAGE_LOCK_PATH = DATA_DIR / "deepseek_score_usage.lock"
DEDUP_PATH = DATA_DIR / "deepseek_score_dedup_cache.json"

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
    "deepseek_model": "deepseek-v4-flash",
    "deepseek_score_enabled": True,
    "crypto_score_enabled": False,
    "us_stock_score_enabled": True,
    "deepseek_score_thinking": False,
    "deepseek_score_dedup_sec": 300,
    "deepseek_daily_max_calls": 150,
}

_score_cache_lock = threading.Lock()
_score_result_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_daily_stats_lock = threading.Lock()
_daily_stats: Dict[str, Any] = {
    "date": "",
    "calls": 0,
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0,
    "last_model": "",
    "last_at": "",
    "last_tokens": 0,
    "last_host": "",
    "last_pid": 0,
}


@contextmanager
def _usage_file_lock() -> Iterator[None]:
    """跨进程锁：run_api / tradingview_bot / webhook_service 共用 usage 与去重。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fp = open(USAGE_LOCK_PATH, "a+b")
    try:
        if os.name == "nt":
            import msvcrt

            fp.seek(0)
            msvcrt.locking(fp.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(fp.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt

                fp.seek(0)
                msvcrt.locking(fp.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(fp.fileno(), fcntl.LOCK_UNLOCK)
        except Exception:
            pass
        fp.close()


def _today_cn() -> str:
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")


def _reload_daily_stats_from_file() -> None:
    try:
        if not USAGE_PATH.is_file():
            return
        raw = json.loads(USAGE_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return
        today = _today_cn()
        if str(raw.get("date") or "") != today:
            return
        with _daily_stats_lock:
            for k in ("calls", "prompt_tokens", "completion_tokens", "total_tokens"):
                if k in raw:
                    _daily_stats[k] = int(raw[k] or 0)
            _daily_stats["date"] = today
            _daily_stats["last_model"] = str(raw.get("last_model") or "")
            _daily_stats["last_at"] = str(raw.get("last_at") or "")
            _daily_stats["last_tokens"] = int(raw.get("last_tokens") or 0)
            _daily_stats["last_host"] = str(raw.get("last_host") or "")
            _daily_stats["last_pid"] = int(raw.get("last_pid") or 0)
    except Exception as exc:
        logger.debug("加载 DeepSeek 用量文件失败: %s", exc)


def _load_persisted_usage() -> None:
    _reload_daily_stats_from_file()


def _save_persisted_usage_unlocked() -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with _daily_stats_lock:
            payload = dict(_daily_stats)
        USAGE_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("写入 DeepSeek 用量文件失败: %s", exc)


def _save_persisted_usage() -> None:
    with _usage_file_lock():
        _save_persisted_usage_unlocked()


def _read_dedup_cache() -> Dict[str, Any]:
    if not DEDUP_PATH.is_file():
        return {"keys": {}}
    try:
        raw = json.loads(DEDUP_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and isinstance(raw.get("keys"), dict):
            return raw
    except Exception:
        pass
    return {"keys": {}}


def _write_dedup_cache(data: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    keys = data.get("keys") if isinstance(data.get("keys"), dict) else {}
    now = time.time()
    stale = [k for k, row in keys.items() if float((row or {}).get("expires") or 0) <= now]
    for k in stale:
        keys.pop(k, None)
    if len(keys) > 80:
        ordered = sorted(
            keys.items(),
            key=lambda kv: float((kv[1] or {}).get("expires") or 0),
            reverse=True,
        )
        keys = dict(ordered[:80])
    DEDUP_PATH.write_text(
        json.dumps({"keys": keys}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _get_cross_process_cached_score(key: str) -> Optional[Dict[str, Any]]:
    with _usage_file_lock():
        data = _read_dedup_cache()
        row = (data.get("keys") or {}).get(key)
        if not row:
            return None
        if float(row.get("expires") or 0) <= time.time():
            data["keys"].pop(key, None)
            _write_dedup_cache(data)
            return None
        payload = row.get("result")
        if not isinstance(payload, dict):
            return None
        out = deepcopy(payload)
        out["deduped"] = True
        out["dedup_source"] = "cross_process"
        return out


def _set_cross_process_cached_score(key: str, payload: Dict[str, Any]) -> None:
    ttl = _score_dedupe_sec()
    if ttl <= 0:
        return
    with _usage_file_lock():
        data = _read_dedup_cache()
        keys = data.setdefault("keys", {})
        keys[key] = {"expires": time.time() + ttl, "result": deepcopy(payload)}
        _write_dedup_cache(data)


_load_persisted_usage()

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
  "support_resistance": {
    "summary": "结合 supports（仅信号同级周期）与 resistances（同级+小一级压力）的一句话",
    "stop_hint": "止损参考：须引用 supports 中 signal_timeframe 的支撑位",
    "target_hint": "目标参考：先同级压力，再小一级压力（resistances 两条）"
  },
  "score_breakdown": {"structure":0-30,"momentum":0-25,"volume":0-20,"risk_penalty":0-25}
}

## 评分步骤（必须先算 breakdown 再汇总 score，与 rebound_strength.strength_score 偏差不超过 ±12）
1) **rebound_strength.strength_score**：动能参考 0–100，**不是**最终分。
2) **综合 score** 以本地公式为准：0.48×动能 + 0.34×锚分 − execution_penalty；**勿**因模型输出给 95+。
3) 大周期死叉/三层过滤未过、缩量 → 须明显扣分；此类场景 execute 禁止，score 通常 58–75。

## 强修复/强反转（必读 scoring_guidance.rebound_strength）
- 弱背景 + MACD 抬升 + 站 EMA20 → 强度可达 70–88；缩量时 recommendation 倾向 caution。
- strong_recovery / signal_bounce / mtf_boost 为辅助判定。

## 硬规则（必须遵守 scoring_guidance.hard_gates）
- hard_gates.force_reject=true → score<=42 且 recommendation=reject
- hard_gates.force_caution_only=true → recommendation 不得为 execute（强趋势超买只能 caution）
- hard_gates.execute_eligible=false → recommendation 不得为 execute

## 建议映射（与 score 一致）
- score>=76 且 execute_eligible → execute
- 52–75 → caution
- <52 或 force_reject → reject

## 禁止
- 禁止大量信号都给同一分数；分差须体现 structure/momentum/volume 差异。
- 禁止 execute_eligible=false 时给 execute。
"""


def _f(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        return float(x)
    except (TypeError, ValueError):
        return default


def _macd_on_df_mtf(df: pd.DataFrame) -> pd.DataFrame:
    """MACD(12,26,9)，供多周期金叉判定。"""
    if df.empty or len(df) < 35:
        return df
    close = df["close"]
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal = macd_line.ewm(span=9, adjust=False).mean()
    df = df.copy()
    df["macd"] = macd_line
    df["macd_signal"] = signal
    df["macd_hist"] = macd_line - signal
    return df


def _macd_state_at_close_mtf(df: pd.DataFrame) -> Dict[str, Any]:
    empty = {"is_above": False, "golden": False, "death": False}
    if df.empty or len(df) < 3:
        return empty
    last = df.iloc[-1]
    prev = df.iloc[-2]
    if pd.isna(last.get("macd")) or pd.isna(last.get("macd_signal")):
        return empty
    curr_m = float(last["macd"])
    curr_s = float(last["macd_signal"])
    prev_m = float(prev["macd"])
    prev_s = float(prev["macd_signal"])
    return {
        "is_above": curr_m > curr_s,
        "golden": curr_m > curr_s and prev_m <= prev_s,
        "death": curr_m < curr_s and prev_m >= prev_s,
    }


def _fetch_macd_state_mtf(
    hl_coin: str,
    tv_tf: str,
    kline_limit: int,
    *,
    fetch_klines_fn=None,
) -> Optional[Dict[str, Any]]:
    fetcher = fetch_klines_fn or fetch_klines_crypto
    iv = tv_tf_to_hl(tv_tf)
    klines = fetcher(hl_coin, iv, total_limit=max(50, kline_limit))
    if not klines or len(klines) < 35:
        return None
    df = _macd_on_df_mtf(klines_to_df(klines))
    return _macd_state_at_close_mtf(df)


def _rsi_strengthening_on_df(df: pd.DataFrame, lookback: int = 5) -> Dict[str, Any]:
    """近 lookback 根已收盘 K 的 RSI14 持续走强。"""
    empty: Dict[str, Any] = {
        "rising": False,
        "rsi_start": None,
        "rsi_end": None,
        "rsi_delta": 0.0,
        "rising_bars": 0,
    }
    if df.empty or len(df) < 60:
        return empty
    if "rsi14" not in df.columns:
        df = compute_technical_indicators(df)
    tail = df.dropna(subset=["rsi14"]).tail(lookback + 1)
    if len(tail) < lookback + 1:
        return empty
    rsi_vals = [float(x) for x in tail["rsi14"].tolist()]
    rsi_start = rsi_vals[0]
    rsi_end = rsi_vals[-1]
    rising_bars = sum(
        1 for i in range(1, len(rsi_vals)) if rsi_vals[i] >= rsi_vals[i - 1] - 0.3
    )
    delta = rsi_end - rsi_start
    rising = (
        delta >= 2.0
        and rising_bars >= max(3, len(rsi_vals) - 2)
        and rsi_end >= 45
    )
    return {
        "rising": rising,
        "rsi_start": round(rsi_start, 2),
        "rsi_end": round(rsi_end, 2),
        "rsi_delta": round(delta, 2),
        "rising_bars": rising_bars,
    }


def compute_mtf_scoring_metrics(
    hl_coin: str,
    *,
    kline_limit: int = 100,
    fetch_klines_fn=None,
) -> Dict[str, Any]:
    """
    多周期加分因子（独立于信号周期）：
    - 日线放量（1d vol_ratio >= 1.15）
    - 1h 或 2h MACD 金叉区间
    - 1h 或 2h RSI 近 5 根持续走强
    """
    out: Dict[str, Any] = {
        "daily_vol_ratio": None,
        "daily_volume_expanded": False,
        "h1_golden_cross_zone": False,
        "h2_golden_cross_zone": False,
        "h1_golden_cross_event": False,
        "h2_golden_cross_event": False,
        "h1_or_h2_golden_cross": False,
        "golden_cross_tf": None,
        "h1_rsi_strengthening": False,
        "h2_rsi_strengthening": False,
        "h1_or_h2_rsi_strengthening": False,
        "rsi_strengthen_tf": None,
        "h1_rsi_delta": None,
        "h2_rsi_delta": None,
        "mtf_boost_count": 0,
        "mtf_boost_reasons": [],
    }
    limit = max(60, kline_limit)
    fetcher = fetch_klines_fn or fetch_klines_crypto

    try:
        d_kl = fetcher(hl_coin, "1d", total_limit=limit)
        if d_kl and len(d_kl) >= 60:
            d_df = compute_technical_indicators(klines_to_df(d_kl))
            last = d_df.iloc[-1]
            dvr = float(last["vol_ratio"]) if pd.notna(last.get("vol_ratio")) else None
            if dvr is not None:
                out["daily_vol_ratio"] = round(dvr, 3)
                out["daily_volume_expanded"] = dvr >= 1.15
    except Exception as e:
        logger.debug("mtf daily vol %s: %s", hl_coin, e)

    for tf_key, tv_tf in (("h1", "1h"), ("h2", "2h")):
        st = _fetch_macd_state_mtf(hl_coin, tv_tf, limit, fetch_klines_fn=fetcher)
        if st:
            out[f"{tf_key}_golden_cross_zone"] = bool(st.get("is_above"))
            out[f"{tf_key}_golden_cross_event"] = bool(st.get("golden"))

    gc_tfs: List[str] = []
    if out["h1_golden_cross_zone"]:
        gc_tfs.append("1h")
    if out["h2_golden_cross_zone"]:
        gc_tfs.append("2h")
    out["h1_or_h2_golden_cross"] = bool(gc_tfs)
    out["golden_cross_tf"] = "/".join(gc_tfs) if gc_tfs else None

    for tf_key, iv in (("h1", "1h"), ("h2", "2h")):
        try:
            kl = fetcher(hl_coin, iv, total_limit=limit)
            if kl and len(kl) >= 60:
                rsi_st = _rsi_strengthening_on_df(klines_to_df(kl), lookback=5)
                out[f"{tf_key}_rsi_strengthening"] = bool(rsi_st.get("rising"))
                out[f"{tf_key}_rsi_delta"] = rsi_st.get("rsi_delta")
        except Exception as e:
            logger.debug("mtf rsi %s %s: %s", hl_coin, iv, e)

    rsi_tfs: List[str] = []
    if out["h1_rsi_strengthening"]:
        rsi_tfs.append("1h")
    if out["h2_rsi_strengthening"]:
        rsi_tfs.append("2h")
    out["h1_or_h2_rsi_strengthening"] = bool(rsi_tfs)
    out["rsi_strengthen_tf"] = "/".join(rsi_tfs) if rsi_tfs else None

    reasons: List[str] = []
    if out["daily_volume_expanded"]:
        reasons.append(f"日线放量(vol_ratio={out['daily_vol_ratio']})")
    if out["h1_or_h2_golden_cross"]:
        reasons.append(f"{out['golden_cross_tf']}金叉区间")
    if out["h1_or_h2_rsi_strengthening"]:
        reasons.append(f"{out['rsi_strengthen_tf']}RSI持续走强")
    out["mtf_boost_count"] = sum([
        out["daily_volume_expanded"],
        out["h1_or_h2_golden_cross"],
        out["h1_or_h2_rsi_strengthening"],
    ])
    out["mtf_boost_reasons"] = reasons
    return out


def evaluate_strong_recovery(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """下跌/震荡背景下的强修复（V 型反转、超跌反弹、MACD 负值区抬升）。"""
    m = metrics or {}
    recent = _f(m.get("recent_change_pct"))
    ret20 = _f(m.get("return_20_bars_pct"))
    ret50 = _f(m.get("return_50_bars_pct"))
    macd_hist = _f(m.get("macd_hist"))
    macd_rising = bool(m.get("macd_hist_rising"))
    adx = _f(m.get("adx14"))
    rsi = _f(m.get("rsi14"), 50.0)
    vol_ratio = _f(m.get("vol_ratio"), 1.0)
    above20 = bool(m.get("price_above_ema20"))
    ema20_rising = bool(m.get("ema20_rising"))
    uptrend_any = bool(m.get("uptrend_met") or m.get("is_uptrend"))
    strong_trend = bool(m.get("strong_trend") or m.get("bg_conditions_met"))

    empty: Dict[str, Any] = {
        "detected": False,
        "tier": None,
        "reasons": [],
        "recovery_score_boost": 0,
    }
    if recent < 0.5 or not macd_rising:
        return empty

    # 已是完整多头趋势 → 走常规上涨评分，不算「强修复」
    if strong_trend and above20 and uptrend_any and recent >= 0:
        return empty

    bearish_backdrop = (
        ret20 < -1.5
        or ret50 < -3
        or not above20
        or not uptrend_any
    )
    if not bearish_backdrop:
        return empty

    reasons: List[str] = []
    boost = 0.0

    if recent >= 5:
        boost += 14
        reasons.append(f"近端强反弹 +{recent:.1f}%")
    elif recent >= 3:
        boost += 10
        reasons.append(f"近端反弹 +{recent:.1f}%")
    elif recent >= 1.5:
        boost += 5
        reasons.append(f"近端修复 +{recent:.1f}%")

    if macd_hist < 0 and macd_rising:
        boost += 12
        reasons.append("MACD柱负值区抬升(动能修复)")
    elif macd_hist >= 0 and macd_rising:
        boost += 7
        reasons.append("MACD柱转正且抬升")

    if ret20 < -6 and recent >= 2:
        boost += 10
        reasons.append("中期超跌后强反弹")
    elif ret20 < -3 and recent >= 1.5:
        boost += 6
        reasons.append("短期自回调低点修复")

    if ema20_rising and not above20:
        boost += 5
        reasons.append("EMA20拐头向上")

    if vol_ratio >= 1.15:
        boost += 8
        reasons.append("放量修复")
    elif vol_ratio >= 0.9:
        boost += 3

    gc = m.get("last_golden_cross_vol_vs_prev_avg")
    if gc is not None and _f(gc) >= 1.2:
        boost += 5
        reasons.append("金叉放量")

    if int(m.get("golden_tf_count") or 0) >= 1:
        boost += 4
    if m.get("pine_entry_ready"):
        boost += 4

    if 32 <= rsi <= 55 and macd_rising:
        boost += 4
        reasons.append("RSI自低位回升")

    if adx >= 25:
        boost += 4

    tier: Optional[str] = None
    if boost >= 20 and recent >= 2.0:
        tier = "strong"
    elif boost >= 12 and recent >= 0.8:
        tier = "moderate"

    return {
        "detected": tier in ("strong", "moderate"),
        "tier": tier,
        "reasons": reasons,
        "recovery_score_boost": int(boost),
        "bearish_backdrop": bearish_backdrop,
        "kind": "strong_recovery",
    }


def _dist_to_nearest_support_pct(metrics: Dict[str, Any]) -> Optional[float]:
    """现价相对最近支撑的距离（%），在支撑上方为正。"""
    close = _f(metrics.get("close"))
    sup = metrics.get("nearest_support")
    if sup is None:
        for s in metrics.get("supports") or []:
            try:
                sup = float(s.get("price"))
                break
            except (TypeError, ValueError):
                continue
    if close <= 0 or sup is None:
        return None
    try:
        sup_f = float(sup)
    except (TypeError, ValueError):
        return None
    if sup_f <= 0:
        return None
    return (close - sup_f) / close * 100.0


def evaluate_signal_tf_bounce(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """大周期偏空，但信号周期企稳：站 EMA20 + MACD 柱正 + 贴近支撑 + 部分周期金叉。"""
    m = metrics or {}
    above20 = bool(m.get("price_above_ema20"))
    macd_hist = _f(m.get("macd_hist"))
    macd_rising = bool(m.get("macd_hist_rising"))
    recent = _f(m.get("recent_change_pct"))
    uptrend_any = bool(m.get("uptrend_met") or m.get("is_uptrend"))
    strong_trend = bool(m.get("strong_trend") or m.get("bg_conditions_met"))

    empty: Dict[str, Any] = {
        "detected": False,
        "tier": None,
        "reasons": [],
        "recovery_score_boost": 0,
        "kind": "signal_bounce",
    }
    if strong_trend and uptrend_any:
        return empty
    if not above20:
        return empty
    if macd_hist <= 0 and not macd_rising:
        return empty
    if recent < -4.0:
        return empty

    dist_sup = _dist_to_nearest_support_pct(m)
    near_support = dist_sup is not None and -0.5 <= dist_sup <= 2.5
    gc = int(m.get("golden_tf_count") or 0)
    partial_golden = (
        gc >= 1
        or bool(m.get("bg3_ok"))
        or bool(m.get("pine_bg_met"))
        or bool(m.get("h1_or_h2_golden_cross"))
    )

    reasons: List[str] = []
    boost = 0.0
    boost += 6
    reasons.append("信号周期站EMA20")
    if macd_hist > 0:
        boost += 6
        reasons.append("MACD柱为正")
    if macd_rising:
        boost += 5
        reasons.append("MACD柱抬升")
    if near_support and dist_sup is not None:
        boost += 9
        reasons.append(f"贴近支撑(+{dist_sup:.2f}%)")
    if partial_golden:
        boost += 5
        reasons.append("部分周期金叉/背景")
    if -2.5 <= recent < 0:
        boost += 4
        reasons.append("近端跌幅收敛")
    elif recent >= 0:
        boost += 6
        reasons.append("近端转涨")

    rsi = _f(m.get("rsi14"), 50.0)
    if 42 <= rsi <= 62:
        boost += 4
        reasons.append("RSI中性偏强")

    vol_ratio = _f(m.get("vol_ratio"), 1.0)
    if vol_ratio < 0.4:
        boost -= 5
        reasons.append("量能偏低(降档)")
    elif vol_ratio >= 0.85:
        boost += 3

    tier: Optional[str] = None
    if boost >= 20 and near_support:
        tier = "solid"
    elif boost >= 14:
        tier = "watch"

    return {
        "detected": tier in ("solid", "watch"),
        "tier": tier,
        "reasons": reasons,
        "recovery_score_boost": int(max(0, boost)),
        "support_dist_pct": round(dist_sup, 3) if dist_sup is not None else None,
        "kind": "signal_bounce",
    }


def _pick_recovery_context(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """强修复优先；否则信号周期支撑反弹。"""
    strong = evaluate_strong_recovery(metrics)
    if strong.get("detected"):
        return strong
    bounce = evaluate_signal_tf_bounce(metrics)
    if bounce.get("detected"):
        return bounce
    return {
        "detected": False,
        "tier": None,
        "reasons": [],
        "recovery_score_boost": 0,
        "kind": None,
    }


def evaluate_mtf_boost_signals(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """多周期加分：日线放量、1h/2h 金叉、1h/2h RSI 持续走强。"""
    m = metrics or {}
    reasons: List[str] = []
    boost = 0.0

    if m.get("daily_volume_expanded"):
        boost += 8
        dvr = m.get("daily_vol_ratio")
        reasons.append(f"日线放量({dvr})" if dvr is not None else "日线放量")

    if m.get("h1_or_h2_golden_cross"):
        tf = m.get("golden_cross_tf") or "1h/2h"
        boost += 10
        reasons.append(f"{tf}金叉区间")

    if m.get("h1_or_h2_rsi_strengthening"):
        tf = m.get("rsi_strengthen_tf") or "1h/2h"
        boost += 8
        reasons.append(f"{tf}RSI持续走强")

    count = int(m.get("mtf_boost_count") or 0)
    if count == 0:
        count = sum([
            bool(m.get("daily_volume_expanded")),
            bool(m.get("h1_or_h2_golden_cross")),
            bool(m.get("h1_or_h2_rsi_strengthening")),
        ])

    tier: Optional[str] = None
    if count >= 3:
        tier = "strong"
    elif count >= 2:
        tier = "moderate"
    elif count >= 1:
        tier = "light"

    return {
        "detected": count >= 1,
        "tier": tier,
        "count": count,
        "reasons": reasons or list(m.get("mtf_boost_reasons") or []),
        "score_boost": int(boost),
    }


def evaluate_rebound_strength(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """反弹/修复强度 0–100（连续刻度；低量压分但不封顶）。"""
    m = metrics or {}
    reasons: List[str] = []
    score = 32.0

    recent = _f(m.get("recent_change_pct"))
    ret20 = _f(m.get("return_20_bars_pct"))
    ret50 = _f(m.get("return_50_bars_pct"))
    macd_hist = _f(m.get("macd_hist"))
    macd_rising = bool(m.get("macd_hist_rising"))
    adx = _f(m.get("adx14"))
    rsi = _f(m.get("rsi14"), 50.0)
    vol_ratio = _f(m.get("vol_ratio"), 1.0)
    above20 = bool(m.get("price_above_ema20"))
    above50 = bool(m.get("price_above_ema50"))
    trend = _f(m.get("trend_score"))
    ema20_rising = bool(m.get("ema20_rising"))
    filter_blocked = bool(m.get("filter_name")) and not bool(m.get("uptrend_met"))
    macro_bear = (
        m.get("bg1_ok") is False
        or m.get("bg2_ok") is False
        or filter_blocked
    )

    weak_backdrop = (
        ret20 < -1.0
        or ret50 < -2.5
        or trend < 52
        or not above50
        or not bool(m.get("uptrend_met"))
        or macro_bear
    )
    repair_context = weak_backdrop or ret20 < 0 or filter_blocked

    if above20:
        score += 14
        reasons.append("站EMA20")
    if above50:
        score += 8
    if m.get("ema20_above_ema50"):
        score += 6
    if macd_hist > 0:
        score += 10
        if macd_rising:
            score += 4
            reasons.append("MACD柱抬升")
    elif macd_hist < 0 and macd_rising:
        score += 12
        reasons.append("MACD负值区抬升")
    elif macd_rising:
        score += 8
        reasons.append("MACD柱抬升")
    if ema20_rising:
        score += 4

    if recent >= 8:
        score += 20
        reasons.append(f"近端强反弹+{recent:.1f}%")
    elif recent >= 4:
        score += 14
    elif recent >= 2:
        score += 10
    elif recent >= 0.8:
        score += 6
    elif recent > 0:
        score += 3
    elif recent >= -2.5 and macd_rising and above20:
        score += 4
        reasons.append("跌幅收敛")

    if weak_backdrop and recent > 0 and macd_rising:
        score += 10
        reasons.append("弱背景下的修复")
    if ret20 < -5 and recent >= 1.0:
        score += 8
        reasons.append("超跌后反弹")

    # —— 加密：大周期弱 / 三层过滤 / 部分周期金叉 / 贴支撑 ——
    if filter_blocked and above20 and (macd_hist > 0 or macd_rising):
        score += 8
        reasons.append("三层过滤未过但信号周期修复")
    if macro_bear and above20 and macd_rising:
        score += 6
        reasons.append("大周期弱+信号周期动能修复")
    gc = int(m.get("golden_tf_count") or 0)
    if gc >= 2:
        score += 6
    elif gc >= 1 or m.get("bg3_ok"):
        score += 4
        reasons.append("部分周期金叉")
    dist_sup = _dist_to_nearest_support_pct(m)
    if dist_sup is not None and -0.5 <= dist_sup <= 2.5:
        score += 7
        reasons.append(f"贴近支撑(+{dist_sup:.2f}%)")
    gc_vol = m.get("last_golden_cross_vol_vs_prev_avg")
    if gc_vol is not None and _f(gc_vol) >= 1.15:
        score += 5
        reasons.append("金叉放量")

    recovery_ctx = _pick_recovery_context(m)
    if recovery_ctx.get("detected"):
        score += min(16.0, float(recovery_ctx.get("recovery_score_boost") or 0) * 0.55)

    if adx >= 35:
        score += 12
        reasons.append("ADX强劲")
    elif adx >= 25:
        score += 8
    elif adx >= 20:
        score += 4

    if 45 <= rsi <= 68:
        score += 6
    elif rsi > 72:
        if adx >= 28 and macd_rising and above20:
            score -= 4
        else:
            score -= 8

    if vol_ratio >= 1.2:
        score += 8
    elif vol_ratio >= 0.85:
        score += 3
    elif vol_ratio < 0.12:
        score -= 18
        reasons.append("极度缩量")
    elif vol_ratio < 0.25:
        score -= 12
        reasons.append("量能极低")
    elif vol_ratio < 0.45:
        score -= 6

    mtf = evaluate_mtf_boost_signals(m)
    score += min(12.0, float(mtf.get("score_boost") or 0) * 0.45)

    res_dist = m.get("resistance_dist_pct")
    try:
        rd = float(res_dist) if res_dist is not None else None
    except (TypeError, ValueError):
        rd = None
    if rd is not None and 0 < rd < 0.8:
        score -= 8
        reasons.append("贴近压力位")
    elif rd is not None and rd < 1.5:
        score -= 4

    strength = int(max(0, min(100, round(score))))
    tier = (
        "strong" if strength >= 80
        else "moderate" if strength >= 65
        else "mild" if strength >= 50
        else "weak"
    )
    return {
        "strength_score": strength,
        "tier": tier,
        "repair_context": repair_context,
        "weak_backdrop": weak_backdrop,
        "macro_bear": macro_bear,
        "filter_blocked": filter_blocked,
        "volume_limited": vol_ratio < 0.35,
        "recovery_kind": recovery_ctx.get("kind"),
        "reasons": reasons[:10],
    }


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
    recovery = _pick_recovery_context(m)
    rec_ok = recovery.get("detected")
    rec_strong = recovery.get("tier") == "strong"
    rec_bounce = recovery.get("kind") == "signal_bounce" and rec_ok
    rec_bounce_solid = rec_bounce and recovery.get("tier") == "solid"
    mtf = evaluate_mtf_boost_signals(m)
    mtf_ok = mtf.get("detected")
    mtf_strong = int(mtf.get("count") or 0) >= 2
    rebound = evaluate_rebound_strength(m)
    rebound_repair = bool(rebound.get("repair_context")) and rebound["strength_score"] >= 50
    rebound_strong = rebound["tier"] in ("strong", "moderate")

    force_reject = (
        (
            m.get("uptrend_met") is False
            and m.get("filter_name")
            and not rec_ok
            and not mtf_strong
            and not rebound_repair
        )
        or ((not above20 and recent <= 0) and not uptrend_any and not rec_ok and not rebound_repair)
        or (
            macd_hist < 0
            and not macd_rising
            and adx < 20
            and not uptrend_any
            and not rec_ok
            and not rebound_repair
        )
        or (recent < -1.0 and not above20 and not uptrend_any and not rec_ok and not rebound_repair)
    )
    # 信号周期贴支撑/强修复但量能极低：不 reject，降为 caution
    if (rec_bounce or rebound_repair) and _f(m.get("vol_ratio"), 1.0) < 0.35:
        force_reject = False
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
            or (
                rec_strong
                and recent >= 2.5
                and macd_rising
                and adx >= 18
            )
            or (
                rec_ok
                and recent >= 1.8
                and macd_rising
                and _f(m.get("vol_ratio"), 1.0) >= 0.85
            )
            or (
                rec_bounce_solid
                and macd_hist > 0
                and macd_rising
                and adx >= 18
                and _f(m.get("vol_ratio"), 1.0) >= 0.55
            )
            or (
                rebound_strong
                and above20
                and macd_rising
                and adx >= 18
                and rebound["strength_score"] >= 68
            )
        )
        and not force_caution_only
        and (
            macd_rising
            or _f(m.get("vol_ratio")) >= 0.75
            or strong_trend
            or (rec_ok and recovery.get("kind") == "strong_recovery")
            or (mtf_strong and m.get("daily_volume_expanded"))
            or (rebound_strong and macd_hist > 0)
        )
    )
    return {
        "force_reject": force_reject,
        "force_caution_only": force_caution_only,
        "execute_eligible": execute_eligible,
        "recovery_context": recovery,
        "strong_recovery": recovery if recovery.get("kind") == "strong_recovery" else evaluate_strong_recovery(m),
        "signal_bounce": recovery if recovery.get("kind") == "signal_bounce" else evaluate_signal_tf_bounce(m),
        "mtf_boost": mtf,
        "rebound_strength": rebound,
    }


def compute_local_buy_score(metrics: Dict[str, Any]) -> int:
    """确定性锚分：与回测对齐，供模型参考及输出校准。"""
    m = metrics or {}
    recovery = _pick_recovery_context(m)
    rec_ok = recovery.get("detected")
    rec_strong = recovery.get("tier") == "strong"
    rec_bounce = recovery.get("kind") == "signal_bounce" and rec_ok
    rec_bounce_solid = rec_bounce and recovery.get("tier") == "solid"
    mtf = evaluate_mtf_boost_signals(m)
    score = 38.0

    # —— 结构（约 0–28）——
    if m.get("price_above_ema20"):
        score += 10
    elif rec_ok:
        score += 2
    else:
        score -= 20
    if m.get("price_above_ema50"):
        score += 7
    elif rec_ok:
        score += 1
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
    elif rec_ok and m.get("macd_hist_rising"):
        score += 4
    else:
        score -= 16
    if m.get("macd_hist_rising"):
        score += 6
    elif macd_hist < 0 and not rec_ok:
        score -= 6

    recent = _f(m.get("recent_change_pct"))
    if recent >= 8:
        score += min(12.0, recent * 0.45)
    elif recent >= 3:
        score += 6
    elif recent > 0.5:
        score += 2
    elif recent > 0:
        score -= 2 if not rec_ok else 0
    else:
        if rec_bounce:
            score -= 4
        elif not rec_ok:
            score -= 16
        else:
            score -= 4

    adx = _f(m.get("adx14"))
    if adx >= 35:
        score += 10
    elif adx >= 22:
        score += 5
    elif adx < 18:
        score -= 14 if not rec_ok else -4

    # —— RSI（约 -14 ~ +10）——
    rsi = _f(m.get("rsi14"), 50.0)
    if 48 <= rsi <= 66:
        score += 8
    elif 40 <= rsi < 48:
        score += 2
    elif rsi < 40:
        score -= 12 if not rec_ok else -3
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
        if m.get("daily_volume_expanded"):
            score -= 2 if rec_bounce else 4
        elif rec_bounce:
            score -= 4
        else:
            score -= 10

    if m.get("daily_volume_expanded"):
        score += 7
    if m.get("h1_or_h2_golden_cross"):
        score += 9
    if m.get("h1_or_h2_rsi_strengthening"):
        score += 7
    if int(mtf.get("count") or 0) >= 2:
        score += 4
    elif mtf.get("detected"):
        score += 2

    gc = m.get("last_golden_cross_vol_vs_prev_avg")
    if gc is not None:
        g = _f(gc, 1.0)
        if g >= 1.3:
            score += 7
        elif g >= 1.0:
            score += 3
        elif g < 0.85:
            score -= 8

    # —— 与本地 trend_score 对齐 ——
    trend = _f(m.get("trend_score"))
    if trend >= 75:
        score += 8
    elif trend >= 55:
        score += 3
    elif trend >= 40:
        score -= 2 if not rec_ok else 0
    else:
        score -= 12 if not rec_ok else -2

    if rec_ok:
        score += min(24.0, float(recovery.get("recovery_score_boost") or 0) * 0.42)

    rebound = evaluate_rebound_strength(m)
    rb = rebound["strength_score"]
    if rebound.get("repair_context") or rec_ok or rec_bounce or mtf.get("detected"):
        score = max(score, min(float(rb) - 12.0, score + 12.0))
    elif rebound["tier"] in ("strong", "moderate"):
        score = max(score, min(float(rb) - 16.0, score + 8.0))

    # 弱势震荡封顶（强修复/反弹时放宽）
    if recent < 1.5 and trend < 45 and not rec_ok and rebound["tier"] not in ("strong", "moderate"):
        score = min(score, 58.0)
    if trend < 35 and not rec_strong and rebound["tier"] != "strong":
        score = min(score, 66.0 if rec_ok else 58.0)
    if not rec_ok and rebound["tier"] not in ("strong", "moderate", "mild"):
        if not m.get("price_above_ema20") or (macd_hist < 0 and not m.get("macd_hist_rising")):
            score = min(score, 42.0)
    elif rec_strong:
        score = max(score, 64.0)
    elif rec_bounce_solid or rec_bounce:
        score = max(score, 48.0)
    elif mtf.get("tier") in ("strong", "moderate") and m.get("price_above_ema20"):
        score = max(score, 52.0)
    elif rec_ok:
        score = max(score, 58.0)

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
    rebound = evaluate_rebound_strength(m)
    recovery_ctx = gates.get("recovery_context") or _pick_recovery_context(m)
    recovery = gates.get("strong_recovery") or evaluate_strong_recovery(m)
    signal_bounce = gates.get("signal_bounce") or evaluate_signal_tf_bounce(m)
    mtf = gates.get("mtf_boost") or evaluate_mtf_boost_signals(m)
    rb = rebound["strength_score"]
    if gates["force_reject"]:
        hint_rec = "reject"
        band = "35-48"
    elif gates["force_caution_only"]:
        hint_rec = "caution"
        band = f"{max(52, rb - 10)}-{min(85, rb + 8)}"
    elif rebound["tier"] == "strong":
        hint_rec = "caution" if rebound.get("volume_limited") or not gates["execute_eligible"] else "execute"
        band = f"{max(72, rb - 12)}-{min(92, rb + 8)}"
    elif rebound["tier"] == "moderate":
        hint_rec = "caution"
        band = f"{max(58, rb - 12)}-{min(88, rb + 10)}"
    elif signal_bounce.get("detected") and anchor >= 48:
        hint_rec = "caution"
        band = f"{max(50, rb - 10)}-{min(88, rb + 10)}"
    elif mtf.get("tier") in ("strong", "moderate") and anchor >= 50:
        hint_rec = "caution" if not gates["execute_eligible"] else "execute"
        lo = 55 if mtf.get("tier") == "strong" else 50
        band = f"{max(lo, anchor - 8)}-{min(78, anchor + 10)}"
    elif recovery.get("tier") == "strong" and anchor >= 68:
        hint_rec = "execute" if gates["execute_eligible"] else "caution"
        lo, hi = max(72, anchor - 8), min(88, anchor + 6)
        band = f"{lo}-{hi}" if lo <= hi else f"{hi}-{lo}"
    elif recovery.get("detected") and anchor >= 58:
        hint_rec = "caution" if not gates["execute_eligible"] else "execute"
        lo, hi = max(58, anchor - 8), min(82, anchor + 8)
        band = f"{lo}-{hi}" if lo <= hi else f"{hi}-{lo}"
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
        "recovery_context": recovery_ctx,
        "strong_recovery": recovery,
        "signal_bounce": signal_bounce,
        "mtf_boost": mtf,
        "rebound_strength": rebound,
        "hint_recommendation": hint_rec,
        "hint_score_band": band,
        "trend_score_local": m.get("trend_score"),
    }


def compose_final_score(
    rb: int,
    anchor: int,
    raw_cap: float,
    penalty: float,
    nudge: float,
    *,
    kinetic_bonus: float = 0.0,
) -> int:
    """
    综合分 = 0.50×动能 + 0.32×锚分 + 微调 − 0.50×penalty
    无封顶：靠 rb/anchor/penalty/nudge 自然拉开；penalty 高则压分，防一律 90+。
    """
    base = (
        0.50 * float(rb)
        + 0.32 * float(anchor)
        + 0.03 * float(raw_cap)
        + float(nudge)
        + float(kinetic_bonus)
    )
    final = base - penalty * 0.50
    return int(max(0, min(100, round(final))))


def finalize_score_with_penalty(base: float, penalty: float) -> int:
    """兼容旧调用。"""
    return int(max(0, min(100, round(base - penalty * 0.50))))


def _crypto_execution_penalty(
    metrics: Dict[str, Any],
    gates: Dict[str, Any],
    rebound: Dict[str, Any],
) -> float:
    """加密可执行性扣分：大周期弱/缩量/贴压（不重复扣已在动能里的项）。"""
    m = metrics or {}
    p = 0.0
    vol = _f(m.get("vol_ratio"), 1.0)
    if vol < 0.12:
        p += 18.0 + max(0.0, (0.12 - vol) * 80.0)
    elif vol < 0.25:
        p += 12.0 + (0.25 - vol) * 28.0
    elif vol < 0.35:
        p += 6.0 + (0.35 - vol) * 30.0
    elif vol < 0.55:
        p += (0.55 - vol) * 12.0

    if m.get("bg1_ok") is False:
        p += 5.0
    if m.get("bg2_ok") is False:
        p += 4.0
    if rebound.get("filter_blocked"):
        p += 6.0

    rd = m.get("resistance_dist_pct")
    try:
        rdf = float(rd) if rd is not None else None
    except (TypeError, ValueError):
        rdf = None
    if rdf is not None and 0 < rdf < 0.8:
        p += 8.0
    elif rdf is not None and rdf < 1.5:
        p += 4.0

    rsi = _f(m.get("rsi14"), 50.0)
    if rsi > 75 and not (m.get("macd_hist_rising") and _f(m.get("adx14")) >= 28):
        p += 4.0

    if gates.get("force_caution_only"):
        p += 6.0
    elif not gates.get("execute_eligible"):
        p += 3.0

    if vol >= 1.15:
        p = max(0.0, p - 4.0)
    if (
        rebound.get("repair_context")
        and m.get("price_above_ema20")
        and m.get("macd_hist_rising")
    ):
        p *= 0.85
    return min(32.0, max(0.0, p))


def _crypto_score_nudge(metrics: Dict[str, Any]) -> float:
    m = metrics or {}
    vol = _f(m.get("vol_ratio"), 1.0)
    recent = _f(m.get("recent_change_pct"))
    adx = _f(m.get("adx14"))
    trend = _f(m.get("trend_score"))
    ret20 = _f(m.get("return_20_bars_pct"))
    n = min(12.0, max(-8.0, recent * 0.85))
    if vol < 0.35:
        n *= max(0.45, vol / 0.35)
    n += min(8.0, max(-7.0, (vol - 1.0) * 14.0))
    n += min(6.0, max(-5.0, (adx - 22.0) * 0.50))
    n += min(6.0, max(-6.0, (trend - 50.0) * 0.18))
    n += min(5.0, max(-5.0, ret20 * 0.12))
    if m.get("bg1_ok") is False:
        n -= 3.0
    if m.get("bg2_ok") is False:
        n -= 2.0
    return n


def _compose_calibrated_summary(
    metrics: Dict[str, Any],
    rebound: Dict[str, Any],
    recommendation: str,
) -> str:
    """与最终 recommendation 一致的研判摘要（覆盖模型自相矛盾的文案）。"""
    m = metrics or {}
    pros: List[str] = []
    if m.get("price_above_ema20"):
        pros.append("信号周期站EMA20")
    if _f(m.get("macd_hist")) > 0:
        pros.append("MACD柱为正")
    elif m.get("macd_hist_rising"):
        pros.append("MACD抬升")
    if rebound.get("repair_context"):
        pros.append("贴近支撑反弹")

    cons: List[str] = []
    if m.get("bg1_ok") is False:
        cons.append("大周期死叉")
    if m.get("bg2_ok") is False:
        cons.append("背景层未确认")
    if rebound.get("filter_blocked"):
        cons.append("三层过滤未过")
    if rebound.get("volume_limited"):
        cons.append("缩量限制动能")

    body = "，".join(pros) if pros else "信号周期结构一般"
    if cons:
        body += "，但" + "、".join(cons)

    rec = (recommendation or "caution").lower()
    if rec == "execute":
        tail = "，建议执行"
    elif rec == "reject":
        tail = "，建议拒绝"
    else:
        tail = "，建议谨慎观望"
    return body + tail + "。"


def _apply_recommendation_consistency(
    st: Dict[str, Any],
    metrics: Dict[str, Any],
    gates: Dict[str, Any],
    rebound: Dict[str, Any],
) -> None:
    """建议与摘要对齐：大周期弱/缩量时可高分，但不给 execute；不改分数。"""
    if gates.get("force_reject"):
        st["summary"] = _compose_calibrated_summary(metrics, rebound, "reject")
        return

    m = metrics or {}
    weak_macro = (
        m.get("bg1_ok") is False
        or m.get("bg2_ok") is False
        or rebound.get("filter_blocked")
    )
    vol_limited = bool(rebound.get("volume_limited"))
    rec = str(st.get("recommendation") or "caution")

    if rec == "execute" and (weak_macro or vol_limited):
        rec = "caution"

    st["recommendation"] = rec
    st["summary"] = _compose_calibrated_summary(metrics, rebound, rec)


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

    rebound = evaluate_rebound_strength(metrics)
    penalty = _crypto_execution_penalty(metrics, gates, rebound)

    if gates["force_reject"]:
        final = min(raw, anchor, 40)
        rec = "reject"
    elif gates["force_caution_only"]:
        blended = int(round(0.25 * raw + 0.75 * anchor))
        final = max(52, min(72, blended))
        rec = "caution"
    else:
        rb = rebound["strength_score"]
        vol_limited = rebound.get("volume_limited")
        raw_cap = min(raw, max(anchor, rb) + 6)
        final = compose_final_score(
            rb, anchor, float(raw_cap), penalty, _crypto_score_nudge(metrics),
        )
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
    if not gates["force_reject"]:
        st["execution_penalty"] = round(penalty, 1)
        st["rebound_strength_score"] = rebound["strength_score"]
        st["model_raw_score"] = raw
    _apply_recommendation_consistency(st, metrics, gates, rebound)
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


def _fmt_price_level(price: Any) -> str:
    try:
        p = float(price)
    except (TypeError, ValueError):
        return "—"
    if p >= 1000:
        return f"{p:,.2f}"
    if p >= 1:
        return f"{p:.4f}"
    return f"{p:.6f}"


# 信号周期 → 小一级周期（用于第二压力位，如 4h→2h）
_SMALLER_TF_MAP: Dict[str, str] = {
    "1w": "1d",
    "3d": "1d",
    "1d": "4h",
    "12h": "4h",
    "8h": "4h",
    "4h": "2h",
    "2h": "1h",
    "1h": "30m",
    "30m": "15m",
    "15m": "5m",
    "5m": "3m",
    "3m": "1m",
}


def extract_ai_sr_tpsl_plan(
    metrics: Optional[Dict[str, Any]],
    entry_price: float,
) -> Optional[Dict[str, Any]]:
    """
    从 AI 评分指标提取止盈止损方案（做多）：
    - 止损：信号同级支撑位
    - 止盈1（50%）：小一级压力位
    - 止盈2（50%）：同级压力位
    """
    if not metrics or entry_price <= 0:
        return None
    m = metrics
    support = m.get("nearest_support")
    for s in m.get("supports") or []:
        if s.get("role") == "signal_tf" or support is None:
            try:
                support = float(s.get("price"))
            except (TypeError, ValueError):
                continue
            break
    if support is None:
        return None
    try:
        support = float(support)
    except (TypeError, ValueError):
        return None

    tp_same = None
    tp_lower = None
    for r in m.get("resistances") or []:
        role = r.get("role")
        try:
            p = float(r.get("price"))
        except (TypeError, ValueError):
            continue
        if role == "same_tf":
            tp_same = p
        elif role == "lower_tf":
            tp_lower = p
    if tp_same is None and m.get("nearest_resistance") is not None:
        try:
            tp_same = float(m.get("nearest_resistance"))
        except (TypeError, ValueError):
            pass
    if tp_lower is None and m.get("nearest_resistance_lower_tf") is not None:
        try:
            tp_lower = float(m.get("nearest_resistance_lower_tf"))
        except (TypeError, ValueError):
            pass

    if support >= entry_price * 0.998:
        return None
    targets = [p for p in (tp_lower, tp_same) if p and p > entry_price * 1.001]
    if not targets:
        return None
    # 近的目标先止盈 50%（通常为小级别压力）
    if tp_lower and tp_same and tp_lower > tp_same:
        tp_lower, tp_same = tp_same, tp_lower

    return {
        "support": support,
        "tp_lower_tf": tp_lower,
        "tp_same_tf": tp_same,
        "sr_signal_timeframe": m.get("sr_signal_timeframe"),
        "sr_lower_timeframe": m.get("sr_lower_timeframe"),
    }


def normalize_sr_interval(interval: str) -> str:
    iv = _tf_map_webhook(interval) or (interval or "").strip().lower()
    if not iv:
        return "4h"
    if iv.endswith("H") and iv[:-1].isdigit():
        return f"{int(iv[:-1])}h"
    if iv.endswith("D") and iv[:-1].isdigit():
        return f"{int(iv[:-1])}d" if int(iv[:-1]) > 1 else "1d"
    return iv


def smaller_trading_interval(interval: str) -> Optional[str]:
    """返回比信号周期小一级的 K 线周期（如 4h→2h）。"""
    iv = normalize_sr_interval(interval)
    return _SMALLER_TF_MAP.get(iv)


def _sr_dist_pct(close: float, level: float) -> float:
    if close <= 0:
        return 0.0
    return round((level - close) / close * 100.0, 2)


def _swing_levels_single_tf(
    df: pd.DataFrame,
    *,
    swing_window: int = 3,
    lookback: int = 80,
    want: str,
    max_levels: int = 3,
    include_ema: bool = True,
) -> List[float]:
    """单周期 K 线上的摆动支撑/压力候选价（不含其他周期）。"""
    if df is None or len(df) < 25:
        return []
    work = df.tail(min(lookback, len(df))).copy()
    close = float(work.iloc[-1]["close"])
    if close <= 0:
        return []

    swing_highs: List[float] = []
    swing_lows: List[float] = []
    w = max(2, int(swing_window))
    for i in range(w, len(work) - w):
        hi = float(work.iloc[i]["high"])
        lo = float(work.iloc[i]["low"])
        seg_h = work.iloc[i - w : i + w + 1]["high"]
        seg_l = work.iloc[i - w : i + w + 1]["low"]
        if hi >= float(seg_h.max()):
            swing_highs.append(hi)
        if lo <= float(seg_l.min()):
            swing_lows.append(lo)

    if want == "support":
        swing_lows.extend([
            float(work.tail(10)["low"].min()),
            float(work.tail(30)["low"].min()),
        ])
        if include_ema:
            for col in ("ema20", "ema50", "ema200"):
                if col not in work.columns:
                    continue
                v = work.iloc[-1].get(col)
                if v is None or (isinstance(v, float) and pd.isna(v)):
                    continue
                val = float(v)
                if val < close:
                    swing_lows.append(val)
        prices = sorted({round(x, 10) for x in swing_lows if x < close * 0.9995}, reverse=True)
    else:
        swing_highs.extend([
            float(work.tail(10)["high"].max()),
            float(work.tail(30)["high"].max()),
        ])
        if include_ema:
            for col in ("ema20", "ema50", "ema200"):
                if col not in work.columns:
                    continue
                v = work.iloc[-1].get(col)
                if v is None or (isinstance(v, float) and pd.isna(v)):
                    continue
                val = float(v)
                if val > close:
                    swing_highs.append(val)
        prices = sorted({round(x, 10) for x in swing_highs if x > close * 1.0005})

    return prices[:max_levels]


def compute_support_resistance_levels(
    df: pd.DataFrame,
    *,
    signal_timeframe: str = "",
    hl_coin: str = "",
    kline_limit: int = 200,
    swing_window: int = 3,
    lookback: int = 80,
    fetch_klines_fn: Optional[Callable[[str, str, int], Optional[List[Dict[str, Any]]]]] = None,
) -> Dict[str, Any]:
    """
    支撑：仅信号同级周期 K 线。
    压力：同级最近一处 + 小一级周期最近一处（如 4h 信号 → 4h 与 2h 各一个压力位）。
    """
    if df is None or len(df) < 25:
        return {}

    signal_tf = normalize_sr_interval(signal_timeframe) or "4h"
    close = float(df.iloc[-1]["close"])
    if close <= 0:
        return {}

    sup_prices = _swing_levels_single_tf(
        df, swing_window=swing_window, lookback=lookback, want="support", max_levels=3,
    )
    res_same = _swing_levels_single_tf(
        df, swing_window=swing_window, lookback=lookback, want="resistance", max_levels=1,
    )

    supports: List[Dict[str, Any]] = []
    for i, p in enumerate(sup_prices):
        supports.append({
            "label": f"S{i + 1}",
            "price": p,
            "dist_pct": _sr_dist_pct(close, p),
            "timeframe": signal_tf,
            "role": "signal_tf",
        })

    resistances: List[Dict[str, Any]] = []
    if res_same:
        resistances.append({
            "label": "R同级",
            "price": res_same[0],
            "dist_pct": _sr_dist_pct(close, res_same[0]),
            "timeframe": signal_tf,
            "role": "same_tf",
        })

    lower_tf = smaller_trading_interval(signal_tf)
    if lower_tf and lower_tf != signal_tf and hl_coin:
        fetcher = fetch_klines_fn if fetch_klines_fn is not None else fetch_klines_crypto
        try:
            kl = fetcher(hl_coin, lower_tf, kline_limit)
            if kl and len(kl) >= 25:
                df_low = compute_technical_indicators(klines_to_df(kl))
                res_low = _swing_levels_single_tf(
                    df_low, swing_window=swing_window, lookback=lookback,
                    want="resistance", max_levels=1, include_ema=False,
                )
                if res_low:
                    p = res_low[0]
                    if not resistances or abs(p - resistances[0]["price"]) / close > 0.001:
                        resistances.append({
                            "label": "R小级",
                            "price": p,
                            "dist_pct": _sr_dist_pct(close, p),
                            "timeframe": lower_tf,
                            "role": "lower_tf",
                        })
        except Exception as e:
            logger.debug("小级别压力 K 线拉取失败 %s %s: %s", hl_coin, lower_tf, e)

    comment_parts: List[str] = []
    if supports:
        s0 = supports[0]
        comment_parts.append(
            f"{signal_tf} 支撑 {_fmt_price_level(s0['price'])}（下方 {abs(s0['dist_pct']):.2f}%）"
        )
    for r in resistances:
        tag = "同级压力" if r.get("role") == "same_tf" else "小级压力"
        comment_parts.append(
            f"{r.get('timeframe')} {tag} {_fmt_price_level(r['price'])}（上方 +{r['dist_pct']:.2f}%）"
        )
    if not comment_parts:
        comment = f"{signal_tf} 周期暂无清晰支撑/压力位"
    else:
        comment = "；".join(comment_parts)
        if supports and resistances:
            cushion = abs(supports[0]["dist_pct"])
            room = resistances[0]["dist_pct"]
            if cushion > 0.01:
                comment += f"；至同级压力空间比约 {round(room / cushion, 2)}:1"

    return {
        "sr_close": close,
        "sr_signal_timeframe": signal_tf,
        "sr_lower_timeframe": lower_tf,
        "supports": supports,
        "resistances": resistances,
        "nearest_support": supports[0]["price"] if supports else None,
        "nearest_resistance": resistances[0]["price"] if resistances else None,
        "nearest_resistance_lower_tf": (
            resistances[1]["price"] if len(resistances) > 1 else None
        ),
        "support_dist_pct": supports[0]["dist_pct"] if supports else None,
        "resistance_dist_pct": resistances[0]["dist_pct"] if resistances else None,
        "support_resistance_comment": comment,
    }


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
    metrics = dict(metrics or {})
    sr = compute_support_resistance_levels(
        df,
        signal_timeframe=iv,
        hl_coin=hl_coin,
        kline_limit=limit,
    )
    if sr:
        metrics.update(sr)

    try:
        mtf = compute_mtf_scoring_metrics(hl_coin, kline_limit=limit)
        if mtf:
            metrics.update(mtf)
    except Exception as e:
        logger.debug("mtf scoring metrics failed %s: %s", hl_coin, e)

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
        "mtf_boost": {
            "daily_volume_expanded": m.get("daily_volume_expanded"),
            "daily_vol_ratio": m.get("daily_vol_ratio"),
            "h1_or_h2_golden_cross": m.get("h1_or_h2_golden_cross"),
            "golden_cross_tf": m.get("golden_cross_tf"),
            "h1_or_h2_rsi_strengthening": m.get("h1_or_h2_rsi_strengthening"),
            "rsi_strengthen_tf": m.get("rsi_strengthen_tf"),
            "mtf_boost_count": m.get("mtf_boost_count"),
            "mtf_boost_reasons": m.get("mtf_boost_reasons") or [],
            "evaluation": guidance.get("mtf_boost") or evaluate_mtf_boost_signals(m),
        },
        "rebound_strength_detail": guidance.get("rebound_strength") or evaluate_rebound_strength(m),
        "scoring_guidance": guidance,
        "indicators_latest": m,
        "support_resistance": {
            "signal_timeframe": m.get("sr_signal_timeframe"),
            "lower_timeframe": m.get("sr_lower_timeframe"),
            "supports": m.get("supports") or [],
            "resistances": m.get("resistances") or [],
            "nearest_support": m.get("nearest_support"),
            "nearest_resistance": m.get("nearest_resistance"),
            "nearest_resistance_lower_tf": m.get("nearest_resistance_lower_tf"),
            "local_comment": m.get("support_resistance_comment"),
        },
        "analysis_tasks": [
            "1) score 须与 scoring_guidance.rebound_strength.strength_score 接近（±12），0–100 连续刻度",
            "2) 加密强修复：大周期死叉/三层过滤未过 + 信号周期站EMA20 + MACD抬升 → 强度 65–88，勿 reject",
            "3) MACD负值区抬升 + 近端反弹 → momentum 高分；低 vol_ratio 压分但不封顶在 65",
            "4) mtf_boost：日线放量 / 1h或2h金叉 / RSI持续走强 → strengths 须体现",
            "5) 金叉量能：last_golden_cross_vol_vs_prev_avg 与 vol_ratio",
            "6) RSI>75 且 ADX>=35、MACD抬升 → 仅轻罚",
            "7) 必须填写 support_resistance",
            "8) recommendation：缩量时强度可高但倾向 caution 非 execute",
        ],
    }
    return (
        f"请对以下「{symbol} {action}」买入信号评分。务必使用 scoring_guidance 锚分与硬规则。\n\n"
        f"结构化数据（JSON）：\n{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"
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


def _score_dedupe_sec() -> int:
    cfg = load_config()
    env = os.getenv("DEEPSEEK_SCORE_DEDUP_SEC", "").strip()
    if env:
        return max(0, int(env))
    return max(0, int(cfg.get("deepseek_score_dedup_sec") or 120))


def _daily_max_calls() -> int:
    cfg = load_config()
    env = os.getenv("DEEPSEEK_SCORE_DAILY_MAX", "").strip()
    if env:
        return max(0, int(env))
    return max(0, int(cfg.get("deepseek_daily_max_calls") or 800))


def _score_dedupe_key(symbol: str, action: str, timeframe: str) -> str:
    bucket = int(time.time() // max(1, _score_dedupe_sec()))
    return f"{symbol}|{(action or '').lower()}|{timeframe or ''}|{bucket}"


def _get_cached_score_result(key: str) -> Optional[Dict[str, Any]]:
    now = time.time()
    with _score_cache_lock:
        row = _score_result_cache.get(key)
        if not row:
            return None
        expires_at, payload = row
        if expires_at <= now:
            _score_result_cache.pop(key, None)
            return None
        out = deepcopy(payload)
        out["deduped"] = True
        return out


def _set_cached_score_result(key: str, payload: Dict[str, Any]) -> None:
    ttl = _score_dedupe_sec()
    if ttl <= 0:
        return
    with _score_cache_lock:
        _score_result_cache[key] = (time.time() + ttl, deepcopy(payload))
        if len(_score_result_cache) > 200:
            now = time.time()
            stale = [k for k, (exp, _) in _score_result_cache.items() if exp <= now]
            for k in stale:
                _score_result_cache.pop(k, None)


def _record_deepseek_usage(
    usage: Optional[Dict[str, Any]],
    *,
    prompt_chars: int,
    model: str,
    request_model: str = "",
) -> None:
    from zoneinfo import ZoneInfo

    today = _today_cn()
    now_s = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")
    u = usage or {}
    pt = int(u.get("prompt_tokens") or 0)
    ct = int(u.get("completion_tokens") or 0)
    tt = int(u.get("total_tokens") or pt + ct)
    host = socket.gethostname()
    pid = os.getpid()
    with _usage_file_lock():
        _reload_daily_stats_from_file()
        with _daily_stats_lock:
            if _daily_stats.get("date") != today:
                _daily_stats.update({
                    "date": today,
                    "calls": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "last_model": "",
                    "last_at": "",
                    "last_tokens": 0,
                    "last_host": "",
                    "last_pid": 0,
                })
            _daily_stats["prompt_tokens"] += pt
            _daily_stats["completion_tokens"] += ct
            _daily_stats["total_tokens"] += tt
            _daily_stats["last_model"] = model
            _daily_stats["last_request_model"] = request_model or model
            _daily_stats["last_at"] = now_s
            _daily_stats["last_tokens"] = tt
            _daily_stats["last_host"] = host
            _daily_stats["last_pid"] = pid
            calls = _daily_stats["calls"]
            total_t = _daily_stats["total_tokens"]
        _save_persisted_usage_unlocked()
    req = request_model or model
    logger.info(
        "[DeepSeek评分] request_model=%s billed_model=%s host=%s pid=%s 调用 #%s/%s | prompt≈%s chars | tokens in=%s out=%s total=%s | 今日累计 tokens=%s",
        req,
        model,
        host,
        pid,
        calls,
        _daily_max_calls() or "∞",
        prompt_chars,
        pt,
        ct,
        tt,
        total_t,
    )
    if "pro" in str(model).lower() and "flash" not in str(model).lower():
        logger.error(
            "[DeepSeek评分] 本次计入 v4-pro 账单 request=%s billed=%s host=%s pid=%s",
            req,
            model,
            host,
            pid,
        )


def _compose_local_score_summary(metrics: Dict[str, Any], st: Dict[str, Any]) -> str:
    m = metrics or {}
    vol = _f(m.get("vol_ratio"), 1.0)
    recent = _f(m.get("recent_change_pct"))
    rb = st.get("rebound_strength_score")
    pen = st.get("execution_penalty")
    rec = st.get("recommendation") or "caution"
    score = st.get("score")
    parts = [f"本地评分 {score}（{rec}）"]
    if rb is not None:
        parts.append(f"动能{rb}")
    if pen is not None:
        parts.append(f"执行风险扣{pen}")
    parts.append(f"vol={vol:.2f} recent={recent:+.1f}%")
    return "；".join(parts) + "。"


def build_local_score_structured(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """不调 API，纯本地公式产出 structured（与 calibrate 后字段一致）。"""
    anchor = compute_local_buy_score(metrics)
    st = calibrate_deepseek_structured({"score": anchor}, metrics)
    st["summary"] = _compose_local_score_summary(metrics, st)
    st["local_score_only"] = True
    return st


def log_score_runtime_config() -> None:
    """启动时打印评分模型配置（便于 grep / 对账）。"""
    crypto_on = crypto_score_enabled()
    us_on = us_stock_score_enabled()
    model = get_deepseek_score_model()
    thinking = _deepseek_score_thinking_enabled()
    logger.info(
        "[DeepSeek评分] 启动配置 host=%s pid=%s crypto=%s us_stock=%s model=%s thinking=%s dedup=%ss daily_max=%s usage_file=%s",
        socket.gethostname(),
        os.getpid(),
        crypto_on,
        us_on,
        model,
        thinking,
        _score_dedupe_sec(),
        _daily_max_calls(),
        USAGE_PATH,
    )
    if (crypto_on or us_on) and model not in ("deepseek-v4-flash",):
        logger.warning(
            "[DeepSeek评分] 当前 model=%s 可能计入 v4-pro 账单，建议改为 deepseek-v4-flash",
            model,
        )
    if thinking:
        logger.warning("[DeepSeek评分] Thinking 已开启，token 与费用会显著上升")


def get_deepseek_score_usage_stats() -> Dict[str, Any]:
    with _daily_stats_lock:
        return dict(_daily_stats)


def _try_consume_daily_call_slot() -> Optional[str]:
    """跨进程占用一次日配额（在发 API 前调用，防止 bot+run_api 双份打满）。"""
    limit = _daily_max_calls()
    if limit <= 0:
        return None
    today = _today_cn()
    with _usage_file_lock():
        _reload_daily_stats_from_file()
        with _daily_stats_lock:
            if _daily_stats.get("date") != today:
                _daily_stats.update({
                    "date": today,
                    "calls": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "last_model": "",
                    "last_at": "",
                    "last_tokens": 0,
                    "last_host": "",
                    "last_pid": 0,
                })
            calls = int(_daily_stats.get("calls") or 0)
            if calls >= limit:
                return f"已达今日 DeepSeek 评分上限 {limit} 次（防循环/重复调用）"
            _daily_stats["calls"] = calls + 1
        _save_persisted_usage_unlocked()
    return None


def _peek_daily_budget() -> Optional[str]:
    """只读检查日限额（不占用配额）。"""
    limit = _daily_max_calls()
    if limit <= 0:
        return None
    today = _today_cn()
    with _usage_file_lock():
        _reload_daily_stats_from_file()
        with _daily_stats_lock:
            if _daily_stats.get("date") != today:
                return None
            calls = int(_daily_stats.get("calls") or 0)
            if calls >= limit:
                return f"已达今日 DeepSeek 评分上限 {limit} 次（防循环/重复调用）"
    return None


def _check_daily_budget() -> Optional[str]:
    return _try_consume_daily_call_slot()


def _resolve_score_dedupe_key(
    symbol: str,
    action: str,
    timeframe: str,
    *,
    asset_kind: str = "crypto",
) -> str:
    cfg = load_config()
    action_l = (action or "").lower().strip()
    if asset_kind == "us_stock":
        from backpack_quant_trading.core.us_stock_signal_scorer import (
            interval_label,
            normalize_us_ticker,
        )

        sym = normalize_us_ticker(symbol)
        iv = interval_label(timeframe) if timeframe else interval_label(cfg.get("us_kline_interval") or "1d")
        return f"us|{_score_dedupe_key(sym, action_l, iv)}"
    sym = _normalize_symbol(symbol)
    iv = _tf_map_webhook(timeframe) or cfg.get("kline_interval") or "4h"
    return _score_dedupe_key(sym, action_l, iv)


def _peek_dedupe_score(
    symbol: str,
    action: str,
    timeframe: str = "",
    *,
    asset_kind: str = "crypto",
) -> Optional[Dict[str, Any]]:
    """去重命中则返回缓存评分，不调用 DeepSeek。"""
    key = _resolve_score_dedupe_key(symbol, action, timeframe, asset_kind=asset_kind)
    cached = _get_cached_score_result(key)
    if cached is not None:
        return cached
    return _get_cross_process_cached_score(key)


def get_webhook_filter_id(webhook_raw: Optional[Dict[str, Any]]) -> str:
    """从 Webhook JSON 提取筛选 ID（兼容 TradingView 多种字段名）。"""
    if not webhook_raw:
        return ""
    for key in (
        "筛选ID",
        "筛选id",
        "filter_id",
        "filterId",
        "filterID",
        "ID",
        "id",
        "alert_id",
        "提醒ID",
        "提醒id",
        "提醒Id",
    ):
        val = webhook_raw.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return ""


def enrich_webhook_raw_for_scoring(
    webhook_raw: Dict[str, Any],
    parsed: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """合并文本/JSON 解析结果，确保评分门禁能读到筛选ID、品种、方向等。"""
    merged = dict(webhook_raw)
    if not parsed:
        return merged

    if not get_webhook_filter_id(merged):
        alt = str(parsed.get("id") or parsed.get("alert_id") or "").strip()
        if alt:
            merged["筛选ID"] = alt

    sym = str(
        merged.get("交易品种")
        or merged.get("symbol")
        or merged.get("ticker")
        or merged.get("coin")
        or ""
    ).strip()
    if not sym or sym.upper() in ("未知品种", "N/A"):
        psym = str(parsed.get("symbol") or "").strip()
        if psym and psym not in ("未知品种", "N/A"):
            merged["交易品种"] = psym

    act = str(
        merged.get("方向")
        or merged.get("操作")
        or merged.get("action")
        or merged.get("signal")
        or merged.get("side")
        or ""
    ).strip()
    if not act or act in ("信号", "N/A"):
        pact = str(parsed.get("signal") or parsed.get("action") or "").strip()
        if pact and pact not in ("信号", "N/A"):
            merged["方向"] = pact

    tf = str(
        merged.get("周期")
        or merged.get("K线级别")
        or merged.get("timeframe")
        or merged.get("interval")
        or merged.get("tf")
        or ""
    ).strip()
    if not tf:
        ptf = str(parsed.get("timeframe") or "").strip()
        if ptf:
            merged["周期"] = ptf

    st = str(
        merged.get("策略名称")
        or merged.get("策略名")
        or merged.get("strategy_name")
        or merged.get("strategy")
        or ""
    ).strip()
    if not st or st in ("未知策略", "N/A"):
        pst = str(parsed.get("strategy") or "").strip()
        if pst and pst not in ("未知策略", "N/A"):
            merged["策略名称"] = pst

    return merged


def extract_webhook_tv_fields(payload: Dict[str, Any]) -> Tuple[str, str, str, str]:
    """返回 (symbol, action, timeframe, strategy_name)。"""
    action = str(
        payload.get("方向")
        or payload.get("操作")
        or payload.get("action")
        or payload.get("signal")
        or payload.get("side")
        or ""
    ).lower().strip()
    symbol = str(
        payload.get("交易品种")
        or payload.get("symbol")
        or payload.get("coin")
        or payload.get("ticker")
        or ""
    ).strip()
    tf = str(
        payload.get("周期")
        or payload.get("K线级别")
        or payload.get("timeframe")
        or payload.get("interval")
        or payload.get("tf")
        or ""
    ).strip()
    strategy_name = str(
        payload.get("策略名称")
        or payload.get("策略名")
        or payload.get("strategy_name")
        or payload.get("strategyName")
        or payload.get("strategy")
        or payload.get("strategy_label")
        or ""
    ).strip()
    return symbol, action, tf, strategy_name


def schedule_live_trade_score_from_webhook(
    payload: Dict[str, Any],
    *,
    parsed: Optional[Dict[str, Any]] = None,
) -> bool:
    """若满足实盘交易+美股+买入，后台调度评分（并记录完整入站 JSON）。"""
    if not isinstance(payload, dict):
        return False
    merged = enrich_webhook_raw_for_scoring(payload, parsed)
    sym, action, tf, strategy_name = extract_webhook_tv_fields(merged)
    fid = get_webhook_filter_id(merged)
    try:
        body_preview = json.dumps(merged, ensure_ascii=False)[:1000]
    except Exception:
        body_preview = str(merged)[:1000]
    logger.info(
        "[DeepSeek评分] Webhook入站 filter_id=%s symbol=%s action=%s strategy=%s tf=%s | %s",
        fid or "—",
        sym or "—",
        action or "—",
        strategy_name or "—",
        tf or "—",
        body_preview,
    )
    if not is_live_trade_us_stock_buy_signal(sym, action, merged):
        return False
    schedule_webhook_dingtalk_score(
        sym,
        action,
        timeframe=tf,
        webhook_raw=merged,
        strategy_label=strategy_name or "live_trade",
        strategy_name=strategy_name or None,
        strategy_side="long",
    )
    return True


def is_live_trade_webhook(webhook_raw: Optional[Dict[str, Any]]) -> bool:
    """筛选 ID 为「实盘交易」的 Webhook 信号。"""
    fid = get_webhook_filter_id(webhook_raw)
    return fid == "实盘交易" or fid.lower() == "live_trade"


def is_manual_score_webhook(webhook_raw: Optional[Dict[str, Any]]) -> bool:
    """前端/脚本显式触发的测试评分，不受实盘交易门禁限制。"""
    if not webhook_raw:
        return False
    return bool(webhook_raw.get("test") or webhook_raw.get("manual_test"))


def is_live_trade_us_stock_buy_signal(
    symbol: str,
    action: str,
    webhook_raw: Optional[Dict[str, Any]] = None,
) -> bool:
    """唯一允许调用 DeepSeek 评分的 Webhook 条件：实盘交易 + 美股 + 买入。"""
    if not is_live_trade_webhook(webhook_raw):
        return False
    from backpack_quant_trading.core.signal_asset_router import is_us_stock_signal

    if not is_us_stock_signal(symbol, webhook_raw):
        return False
    a = (action or "").lower().strip()
    return a in ("buy", "long") or "买" in a


def score_request_gate(
    symbol: str,
    action: str,
    *,
    timeframe: str = "",
    webhook_raw: Optional[Dict[str, Any]] = None,
    asset_kind: str = "crypto",
    strategy_name: str | None = None,
    strategy_side: str | None = None,
    require_dingtalk: bool = False,
    require_webhook_action: bool = False,
    for_trade_gate: bool = False,
    skip_live_trade_gate: bool = False,
) -> Tuple[str, Dict[str, Any]]:
    """评分预检：skip / cached 均不得调 DeepSeek；仅 call_api 可继续拉 K 线并请求 API。

    Returns:
        ("skip", payload) — 直接返回，零 API
        ("cached", payload) — 用缓存，零 API（可推送钉钉）
        ("call_api", {}) — 允许后续 run_signal_score
    """
    sym_display = str(symbol or "").strip().upper()
    action_l = (action or "").lower().strip()
    is_manual = is_manual_score_webhook(webhook_raw)
    if is_manual:
        skip_live_trade_gate = True

    if not skip_live_trade_gate and not is_manual:
        if not is_live_trade_us_stock_buy_signal(symbol, action, webhook_raw):
            logger.info(
                "[DeepSeek评分] 预检跳过(仅实盘交易美股买入): %s %s 筛选ID=%s",
                sym_display,
                action_l,
                get_webhook_filter_id(webhook_raw) or "—",
            )
            return "skip", {
                "ok": False,
                "skipped": True,
                "error": "仅筛选ID=实盘交易的美股买入信号可调用 AI 评分",
                "symbol": sym_display,
                "action": action_l,
                "asset_kind": asset_kind,
                "filter_id": get_webhook_filter_id(webhook_raw) or None,
            }

    if require_webhook_action and not is_manual and not should_score_webhook_action(
        action,
        strategy_name=strategy_name,
        strategy_side=strategy_side,
    ):
        logger.info(
            "[DeepSeek评分] 预检跳过(推送条件/平仓): %s %s strategy=%s",
            sym_display, action_l, strategy_name or "—",
        )
        return "skip", {
            "ok": False,
            "skipped": True,
            "error": "未满足 Webhook 评分条件（平仓或方向不符）",
            "symbol": sym_display,
            "action": action_l,
            "asset_kind": asset_kind,
        }

    if require_dingtalk and not for_trade_gate and not dingtalk_webhook_enabled():
        logger.info("[DeepSeek评分] 预检跳过(钉钉已关): %s %s", sym_display, action_l)
        return "skip", {
            "ok": False,
            "skipped": True,
            "error": "钉钉推送已关闭，跳过 AI 评分",
            "symbol": sym_display,
            "action": action_l,
            "asset_kind": asset_kind,
        }

    if asset_kind == "us_stock":
        if not us_stock_score_enabled():
            logger.info("[DeepSeek评分] 预检跳过(美股已关): %s", sym_display)
            return "skip", {
                "ok": False,
                "skipped": True,
                "error": "美股 AI 评分已关闭",
                "symbol": sym_display,
                "action": action_l,
                "asset_kind": "us_stock",
            }
    elif not crypto_score_enabled() and not is_manual:
        logger.info("[DeepSeek评分] 预检跳过(加密已关): %s", sym_display)
        return "skip", {
            "ok": False,
            "skipped": True,
            "error": "加密 AI 评分已关闭",
            "symbol": sym_display,
            "action": action_l,
            "asset_kind": "crypto",
        }

    budget_err = _peek_daily_budget()
    if budget_err:
        logger.info("[DeepSeek评分] 预检跳过(日限额): %s %s | %s", sym_display, action_l, budget_err)
        return "skip", {
            "ok": False,
            "skipped": True,
            "error": budget_err,
            "symbol": sym_display,
            "action": action_l,
            "asset_kind": asset_kind,
        }

    cached = _peek_dedupe_score(symbol, action, timeframe, asset_kind=asset_kind)
    if cached is not None:
        cfg = load_config()
        iv = _tf_map_webhook(timeframe) or cfg.get("kline_interval") or "4h"
        logger.info(
            "[DeepSeek评分] 预检去重命中，不调 API: %s %s %s（%ss）",
            sym_display, action_l, iv, _score_dedupe_sec(),
        )
        return "cached", cached

    return "call_api", {}


def deepseek_score_enabled() -> bool:
    """全局 DeepSeek 开关（兼容旧配置）；加密/美股请用 crypto_score_enabled / us_stock_score_enabled。"""
    return crypto_score_enabled() or us_stock_score_enabled()


def crypto_score_enabled() -> bool:
    cfg = load_config()
    env = os.getenv("CRYPTO_SCORE_ENABLED", "").strip().lower()
    if env in ("0", "false", "no", "off", "disabled"):
        return False
    if env in ("1", "true", "yes", "on", "enabled"):
        return True
    if "crypto_score_enabled" in cfg:
        return bool(cfg.get("crypto_score_enabled"))
    env_all = os.getenv("DEEPSEEK_SCORE_ENABLED", "").strip().lower()
    if env_all in ("0", "false", "no", "off", "disabled"):
        return False
    if env_all in ("1", "true", "yes", "on", "enabled"):
        return True
    if "deepseek_score_enabled" in cfg:
        return bool(cfg.get("deepseek_score_enabled"))
    return True


def us_stock_score_enabled() -> bool:
    cfg = load_config()
    env = os.getenv("US_STOCK_SCORE_ENABLED", "").strip().lower()
    if env in ("0", "false", "no", "off", "disabled"):
        return False
    if env in ("1", "true", "yes", "on", "enabled"):
        return True
    if "us_stock_score_enabled" in cfg:
        return bool(cfg.get("us_stock_score_enabled"))
    env_all = os.getenv("DEEPSEEK_SCORE_ENABLED", "").strip().lower()
    if env_all in ("0", "false", "no", "off", "disabled"):
        return False
    return True


_SCORE_MODEL_ALLOWED = "deepseek-v4-flash"


def get_deepseek_score_model() -> str:
    """信号评分硬锁 flash；配置/环境若写 pro 一律忽略（v4-pro 贵数倍）。"""
    env = os.getenv("DEEPSEEK_SCORE_MODEL", "").strip().lower()
    cfg = str(load_config().get("deepseek_model") or "").strip().lower()
    for raw in (env, cfg):
        if not raw:
            continue
        if "pro" in raw and "flash" not in raw:
            logger.warning("[DeepSeek评分] 忽略 pro 配置 %s，硬锁 %s", raw, _SCORE_MODEL_ALLOWED)
            continue
        if "flash" in raw:
            return raw if raw.startswith("deepseek") else _SCORE_MODEL_ALLOWED
    if env or cfg:
        logger.warning(
            "[DeepSeek评分] 忽略非 flash 配置 env=%s cfg=%s → %s",
            env or "—",
            cfg or "—",
            _SCORE_MODEL_ALLOWED,
        )
    return _SCORE_MODEL_ALLOWED


def _deepseek_score_thinking_enabled() -> bool:
    cfg = load_config()
    env = os.getenv("DEEPSEEK_SCORE_THINKING", "").strip().lower()
    if env in ("1", "true", "yes", "on", "enabled"):
        return True
    if env in ("0", "false", "no", "off", "disabled"):
        return False
    if "deepseek_score_thinking" in cfg:
        return bool(cfg.get("deepseek_score_thinking"))
    return False


def build_deepseek_score_payload(
    system_prompt: str,
    user_prompt: str,
    *,
    temperature: float = 0.2,
) -> Dict[str, Any]:
    model = get_deepseek_score_model()
    payload: Dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
    }
    # V4 默认开启 thinking；评分必须显式 disabled，否则 token/费用暴涨
    if _deepseek_score_thinking_enabled():
        payload["thinking"] = {"type": "enabled"}
    else:
        payload["thinking"] = {"type": "disabled"}
    return payload


def call_deepseek_json_score(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.2,
) -> Dict[str, Any]:
    """加密/美股信号评分共用的 DeepSeek 调用。"""
    budget_err = _check_daily_budget()
    if budget_err:
        return {"ok": False, "error": budget_err}

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        return {"ok": False, "error": "未配置 DEEPSEEK_API_KEY"}

    model = get_deepseek_score_model()
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = build_deepseek_score_payload(system_prompt, user_prompt, temperature=temperature)
    prompt_chars = len(system_prompt) + len(user_prompt)
    try:
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
        return {"ok": False, "error": f"DeepSeek 失败({model}): {err}"}

    billed_model = str(data.get("model") or model)
    request_model = model
    msg = data["choices"][0].get("message") or {}
    reasoning = msg.get("reasoning_content") or ""
    if reasoning:
        logger.warning(
            "[DeepSeek评分] 响应含 reasoning_content（%s chars），thinking 未关闭，费用会飙升",
            len(str(reasoning)),
        )
    if "pro" in billed_model.lower() and "flash" not in billed_model.lower():
        logger.error(
            "[DeepSeek评分] ⚠️ 请求=%s 但 API 计费=%s（请重启三进程并 grep 此日志）",
            request_model,
            billed_model,
        )

    _record_deepseek_usage(
        data.get("usage"),
        prompt_chars=prompt_chars,
        model=billed_model,
        request_model=request_model,
    )

    content = msg.get("content") or ""
    structured = _extract_json_block(content)
    if not structured and content.strip().startswith("{"):
        try:
            structured = json.loads(content.strip())
        except Exception:
            structured = {}
    return {
        "ok": True,
        "markdown": content,
        "structured": structured,
        "model": billed_model,
        "request_model": model,
        "usage": data.get("usage"),
    }


def call_deepseek_score(user_prompt: str, temperature: float = 0.2) -> Dict[str, Any]:
    return call_deepseek_json_score(_SYSTEM_PROMPT, user_prompt, temperature)


def _poster_fmt_num(v: Any, digits: int = 2) -> str:
    try:
        if v is None or v == "":
            return "—"
        x = float(v)
        if abs(x) >= 1000:
            return f"{x:,.{max(0, digits)}f}"
        return f"{x:.{digits}f}"
    except (TypeError, ValueError):
        return str(v) if v is not None else "—"


def _poster_score_bar(score_val: int) -> str:
    n = max(0, min(100, int(score_val)))
    filled = n // 10
    return "█" * filled + "░" * (10 - filled) + f"  {n}%"


def _poster_rec_label(rec: str) -> tuple[str, str]:
    r = (rec or "").lower().strip()
    if r == "execute":
        return "✅", "建议执行"
    if r == "caution":
        return "⚠️", "谨慎观望"
    if r == "reject":
        return "⛔", "建议拒绝"
    return "🔔", rec or "—"


def _poster_grade_badge(grade: str) -> str:
    g = str(grade or "—").upper().strip()
    icons = {"A": "🏆", "B": "🥈", "C": "🥉", "D": "📉", "F": "🚫"}
    return f"{icons.get(g, '📊')} {g}"


def _poster_action_cn(action: str) -> str:
    a = (action or "").lower().strip()
    if "buy" in a or "long" in a or "买" in a:
        return "买入"
    if "sell" in a or "short" in a or "卖" in a:
        return "卖出"
    return action or "—"


def format_dingtalk_message(
    symbol: str,
    action: str,
    snapshot: Dict[str, Any],
    deepseek: Dict[str, Any],
    *,
    timeframe: str = "",
) -> str:
    """钉钉 Markdown：海报式排版（手机端可读）。"""
    cfg = load_config()
    kw = cfg.get("dingtalk_keyword") or "提醒"
    m = snapshot.get("metrics") or {}
    st = deepseek.get("structured") or {}
    try:
        score_val = int(float(st.get("score") or 0))
    except (TypeError, ValueError):
        score_val = 0
    grade = st.get("grade", "—")
    rec = st.get("recommendation", "—")
    summary = (st.get("summary") or deepseek.get("markdown", "") or "").strip()
    if len(summary) > 280:
        summary = summary[:277] + "…"

    tf = timeframe or snapshot.get("interval", "—")
    action_l = (action or "").lower()
    is_buy = "buy" in action_l or "long" in action_l or "买" in action
    is_sell = "sell" in action_l or "short" in action_l or "卖" in action
    dir_ico = "🟢" if is_buy else ("🔴" if is_sell else "🔔")
    dir_cn = _poster_action_cn(action)
    rec_ico, rec_cn = _poster_rec_label(str(rec))
    grade_line = _poster_grade_badge(str(grade))
    bar = _poster_score_bar(score_val)
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    close = _poster_fmt_num(m.get("close"), 2)
    rsi = _poster_fmt_num(m.get("rsi14"), 2)
    macd = _poster_fmt_num(m.get("macd_hist"), 4)
    adx = _poster_fmt_num(m.get("adx14"), 2)
    volr = _poster_fmt_num(m.get("vol_ratio"), 3)
    ret20 = _poster_fmt_num(m.get("return_20_bars_pct"), 2)
    uptrend = "通过 ✅" if snapshot.get("scanner_uptrend") else "未通过 —"
    top50 = "在池 ✅" if snapshot.get("in_top50_uptrend_list") else "不在 —"

    strengths = [str(x).strip() for x in (st.get("strengths") or []) if str(x).strip()][:4]
    risks = [str(x).strip() for x in (st.get("risks") or []) if str(x).strip()][:4]

    sep = "━━━━━━━━━━━━━━━━━━━━━━"
    sep_thin = "──────────────────────"

    lines = [
        f"## {kw} · AI 信号评分",
        "",
        f"#### 🎯 信号档案",
        sep_thin,
        f"- **品种** {symbol}",
        f"- **方向** {dir_ico} {dir_cn}",
        f"- **周期** {tf}",
        f"- **时间** {now_utc}",
        "",
        f"#### ⭐ 综合评分",
        sep,
        "",
        f"## {score_val} / 100",
        "",
        f"> {bar}",
        "",
        f"- **等级** {grade_line}",
        f"- **结论** {rec_ico} {rec_cn}",
        "",
    ]

    if summary:
        lines += [
            f"#### 💬 研判摘要",
            sep_thin,
            f"> {summary}",
            "",
        ]

    # 美股消息面（Massive/Yahoo + AI news_comment）
    news_ctx = snapshot.get("news_context")
    news_comment = str(st.get("news_comment") or "").strip()
    if news_ctx or news_comment:
        try:
            from backpack_quant_trading.core.us_stock_news import format_news_for_dingtalk

            news_lines = format_news_for_dingtalk(
                news_ctx if isinstance(news_ctx, dict) else None,
                ticker=symbol,
                news_comment=news_comment,
                max_items=6,
            )
        except Exception:
            news_lines = []
        if news_lines:
            lines += [f"#### 📰 消息面", sep_thin, *news_lines, ""]

    # 支撑 / 压力位（本地计算 + AI 补充）
    sr_block = st.get("support_resistance") if isinstance(st.get("support_resistance"), dict) else {}
    sr_summary = (sr_block.get("summary") or m.get("support_resistance_comment") or "").strip()
    sr_stop = (sr_block.get("stop_hint") or "").strip()
    sr_target = (sr_block.get("target_hint") or "").strip()
    supports = m.get("supports") or []
    resistances = m.get("resistances") or []

    sr_tf = m.get("sr_signal_timeframe") or tf
    sr_low = m.get("sr_lower_timeframe") or ""

    lines += [f"#### 📐 支撑 / 压力位", sep_thin]
    lines.append(f"- **信号周期** `{sr_tf}`" + (f"　小一级 `{sr_low}`" if sr_low else ""))
    if supports:
        for s in supports[:3]:
            p = _fmt_price_level(s.get("price"))
            d = s.get("dist_pct")
            stf = s.get("timeframe") or sr_tf
            lines.append(f"- **支撑 {s.get('label', 'S')}** `{p}`（**{stf}**）　距现价 **{d}%**")
    else:
        lines.append(f"- **支撑** 暂无（**{sr_tf}** 下方无显著摆动低点）")
    if resistances:
        for r in resistances[:2]:
            p = _fmt_price_level(r.get("price"))
            d = r.get("dist_pct")
            sign = "+" if (d or 0) >= 0 else ""
            rtf = r.get("timeframe") or "—"
            role_cn = "同级" if r.get("role") == "same_tf" else "小一级"
            lines.append(
                f"- **压力·{role_cn}** `{p}`（**{rtf}**）　距现价 **{sign}{d}%**"
            )
    else:
        lines.append("- **压力** 暂无（现价上方无显著摆动高点）")
    if sr_summary:
        lines.append(f"> {sr_summary}")
    if sr_stop:
        lines.append(f"- **止损参考** {sr_stop}")
    if sr_target:
        lines.append(f"- **目标参考** {sr_target}")
    lines.append("")

    lines += [f"#### 📊 技术快照", sep_thin]
    is_us_massive = snapshot.get("data_source") == "massive"
    last_bar = snapshot.get("last_bar_time_utc")
    latest_quote = snapshot.get("latest_quote")
    if is_us_massive and last_bar:
        lines.append(f"> **K线截止** {last_bar}　**{tf} 收盘** {close}")
        if latest_quote is not None:
            lines.append(f"> **最新昨收** {_poster_fmt_num(latest_quote, 2)}（Massive/Polygon）")
        lines.append(f"> RSI **{rsi}**　　MACD **{macd}**　　ADX **{adx}**")
        lines.append(f"> 量比 **{volr}**　　20K **{ret20}%**")
    else:
        lines.append(f"> 收盘 **{close}**　　RSI **{rsi}**")
        lines.append(f"> MACD **{macd}**　　ADX **{adx}**")
        lines.append(f"> 量比 **{volr}**　　20K **{ret20}%**")
    lines += [
        "",
        f"- **趋势扫描** {uptrend}",
    ]
    if not is_us_massive:
        lines.append(f"- **Top50池** {top50}")
    mtf_reasons = m.get("mtf_boost_reasons") or []
    if mtf_reasons:
        lines.append(f"- **多周期** {' · '.join(mtf_reasons)}")
    else:
        mtf_n = int(m.get("mtf_boost_count") or 0)
        if mtf_n:
            lines.append(f"- **多周期加分** {mtf_n}/3")
    lines += [""]

    if strengths:
        lines += ["", f"#### ✅ 亮点", sep_thin]
        for s in strengths:
            lines.append(f"- {s}")

    if risks:
        lines += ["", f"#### ⚠️ 风险", sep_thin]
        for r in risks:
            lines.append(f"- {r}")

    lines += [
        "",
        sep,
        f"**沐龙量化** · `{symbol}` · `{tf}`",
    ]
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


def is_close_signal(action: str, *, strategy_name: str | None = None) -> bool:
    """平仓信号：做空策略的买入 / 做多策略的卖出。"""
    if not (strategy_name or "").strip():
        return False
    if infer_strategy_is_short(strategy_name):
        return is_buy_action(action)
    return is_sell_action(action)


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
    if not crypto_score_enabled() and not is_manual_score_webhook(webhook_raw):
        sym = _normalize_symbol(symbol)
        logger.info("[DeepSeek评分] 加密评分已关闭，跳过 %s", sym)
        return {
            "ok": False,
            "skipped": True,
            "error": "加密 AI 评分已关闭",
            "symbol": sym,
            "action": (action or "").lower().strip(),
            "asset_kind": "crypto",
        }

    cfg = load_config()
    sym = _normalize_symbol(symbol)
    action_l = (action or "").lower().strip()
    iv = _tf_map_webhook(timeframe) or cfg.get("kline_interval") or "4h"

    dedupe_key = _resolve_score_dedupe_key(sym, action_l, iv, asset_kind="crypto")
    cached = _get_cached_score_result(dedupe_key)
    if cached is not None:
        logger.info(
            "[DeepSeek评分] 去重命中(内存) %s %s %s（%ss 内不重复调 API）",
            sym, action_l, iv, _score_dedupe_sec(),
        )
        return cached
    cached = _get_cross_process_cached_score(dedupe_key)
    if cached is not None:
        logger.info(
            "[DeepSeek评分] 去重命中(跨进程) %s %s %s（%ss 内不重复调 API）",
            sym, action_l, iv, _score_dedupe_sec(),
        )
        return cached

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

    result = {
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
    _set_cached_score_result(dedupe_key, result)
    _set_cross_process_cached_score(dedupe_key, result)
    return result


def push_score_to_dingtalk(
    score_result: Dict[str, Any],
    *,
    webhook_url: str | None = None,
) -> Tuple[bool, str]:
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

    webhook_url = (webhook_url or cfg.get("dingtalk_webhook") or DEFAULT_WEBHOOK).strip()
    if not webhook_url:
        return False, "未配置钉钉 Webhook"
    body = format_dingtalk_message(sym, action_l, snapshot, ds, timeframe=tf)
    st = ds.get("structured") or {}
    _, rec_cn = _poster_rec_label(str(st.get("recommendation") or ""))
    title = f"{sym} {_poster_action_cn(action_l)} · AI {score_val}分 · {rec_cn}"
    return send_dingtalk_markdown(webhook_url, title, body)


def run_signal_score_and_push_dingtalk(
    symbol: str,
    action: str,
    *,
    timeframe: str = "",
    webhook_raw: Optional[Dict[str, Any]] = None,
    strategy_label: str = "adaptive_long",
    strategy_name: str | None = None,
    strategy_side: str | None = None,
    dingtalk_webhook_url: str | None = None,
    skip_live_trade_gate: bool = False,
) -> Dict[str, Any]:
    """路径2：Webhook → 预检 →（可选）DeepSeek → 钉钉。"""
    from backpack_quant_trading.core.signal_asset_router import (
        classify_signal_asset,
        run_signal_score_routed,
    )

    kind = classify_signal_asset(symbol, webhook_raw)
    mode, early = score_request_gate(
        symbol,
        action,
        timeframe=timeframe,
        webhook_raw=webhook_raw,
        asset_kind=kind,
        strategy_name=strategy_name,
        strategy_side=strategy_side,
        require_dingtalk=True,
        require_webhook_action=True,
        skip_live_trade_gate=skip_live_trade_gate,
    )
    if mode == "skip":
        return early
    if mode == "cached":
        result = early
    else:
        result = run_signal_score_routed(
            symbol,
            action,
            timeframe=timeframe,
            webhook_raw=webhook_raw,
            strategy_label=strategy_label,
            skip_gate=True,
        )

    ding_ok, ding_msg = False, "skipped"
    if result.get("ok"):
        ding_ok, ding_msg = push_score_to_dingtalk(
            result,
            webhook_url=dingtalk_webhook_url,
        )
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
        "deduped": result.get("deduped"),
    }
    if result.get("ok") or result.get("deduped"):
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
    skip_live_trade_gate: bool = False,
) -> Dict[str, Any]:
    """兼容：测试接口可传 skip_live_trade_gate=True 绕过实盘交易门禁。"""
    return run_signal_score_and_push_dingtalk(
        symbol, action,
        timeframe=timeframe,
        webhook_raw=webhook_raw,
        strategy_label=strategy_label,
        skip_live_trade_gate=skip_live_trade_gate,
    )


def should_score_webhook_action(
    action: str,
    *,
    strategy_name: str | None = None,
    strategy_side: str | None = None,
) -> bool:
    """是否应对该 Webhook 信号做 AI 评分（钉钉旁路）。"""
    if not dingtalk_webhook_enabled():
        return False

    side = (strategy_side or "").strip().lower()
    if side == "long":
        return is_buy_action(action)
    if side == "short":
        return is_sell_action(action)

    # 策略名称决定开仓方向；反向信号视为平仓，不做 AI 评分
    # - 含「做空」（如 eth2h做空）→ 只评卖出；买入=平仓，跳过
    # - 不含（如 6h进6h出）→ 只评买入；卖出=平仓，跳过
    if strategy_name:
        if is_close_signal(action, strategy_name=strategy_name):
            return False
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
    strategy_side: str | None = None,
) -> None:
    """路径2：Webhook 后台线程 → 预检 → 钉钉推送（与实盘开单无关）。"""
    from backpack_quant_trading.core.signal_asset_router import classify_signal_asset

    kind = classify_signal_asset(symbol, webhook_raw)
    mode, early = score_request_gate(
        symbol,
        action,
        timeframe=timeframe,
        webhook_raw=webhook_raw,
        asset_kind=kind,
        strategy_name=strategy_name,
        strategy_side=strategy_side,
        require_dingtalk=True,
        require_webhook_action=True,
    )
    if mode == "skip":
        return

    def _job():
        try:
            if mode == "cached":
                ok, msg = push_score_to_dingtalk(early)
                logger.info(
                    "[DeepSeek评分] 去重缓存仅推送钉钉 %s: ok=%s %s",
                    symbol, ok, msg,
                )
                return
            run_signal_score_and_push_dingtalk(
                symbol,
                action,
                timeframe=timeframe,
                webhook_raw=webhook_raw,
                strategy_label=strategy_label,
                strategy_name=strategy_name,
                strategy_side=strategy_side,
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
