"""Hyperliquid 永续 Top50（24h 成交额）上涨趋势扫描。"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from backpack_quant_trading.core.hyperliquid_klines import (
    fetch_hl_klines_batch,
    fetch_hl_top_perps_by_volume,
    to_hl_coin,
)

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
SCAN_CACHE_PATH = DATA_DIR / "crypto_uptrend_scan_cache.json"
SCAN_CONFIG_PATH = DATA_DIR / "crypto_uptrend_scan_config.json"

# TradingView 周期 → Hyperliquid（与 Pine 默认一致）
TV_TF_TO_HL: Dict[str, str] = {
    "D": "1d", "1D": "1d", "1d": "1d", "1W": "1w", "W": "1w", "1w": "1w", "周线": "1w",
    "240": "4h", "4H": "4h", "4h": "4h",
    "120": "2h", "2H": "2h", "2h": "2h",
    "480": "8h", "8H": "8h", "8h": "8h",
    "60": "1h", "1H": "1h", "1h": "1h",
}

_DEFAULT_SCAN_CONFIG: Dict[str, Any] = {
    "filter_name": "三层过滤交易策略",
    "uptrend_tf1": "1w",
    "uptrend_cond1": "金叉区间",
    "uptrend_tf2": "1d",
    "uptrend_cond2": "金叉区间",
    "strong_tf": "8h",
    "strong_cond": "金叉区间",
    "bg_tf1": "1w",
    "bg_cond1": "金叉区间",
    "bg_tf2": "1d",
    "bg_cond2": "金叉区间",
    "bg_tf3": "8h",
    "bg_cond3": "金叉区间",
    "pine_bg_logic": "且",
    "pine_bg_cond1": "金叉区间",
    "pine_bg_cond2": "无",
    "pine_bg_cond3": "无",
    "entry_tf": "8h",
    "entry_cond": "死叉后",
    "exit_tf1": "1d",
    "exit_cond1": "金叉后",
    "exit_tf2": "4h",
    "exit_cond2": "无",
    "exit_logic": "或",
    "uptrend_requires_entry": False,
    "display_interval": "4h",
    "kline_limit": 100,
    "min_bars": 60,
}


def fetch_klines_crypto(symbol: str, interval: str, total_limit: int = 1000):
    """从 Hyperliquid 拉取 K 线（与实盘同源）。"""
    return fetch_hl_klines_batch(symbol, interval, total_limit=total_limit)


def load_scan_config() -> Dict[str, Any]:
    cfg = dict(_DEFAULT_SCAN_CONFIG)
    if SCAN_CONFIG_PATH.is_file():
        try:
            raw = json.loads(SCAN_CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                cfg.update(raw)
        except Exception:
            pass
    return cfg


def tv_tf_to_hl(tf: str) -> str:
    t = (tf or "4h").strip()
    return TV_TF_TO_HL.get(t, TV_TF_TO_HL.get(t.upper(), t.lower()))


def fetch_top_market_cap_coins(limit: int = 50) -> List[Dict[str, Any]]:
    """HL 永续按 24h 成交额(dayNtlVlm) Top N（替代市值榜）。"""
    return fetch_hl_top_perps_by_volume(limit)


def klines_to_df(klines: List[Dict]) -> pd.DataFrame:
    df = pd.DataFrame(klines)
    if df.empty:
        return df
    df = df.sort_values("time").reset_index(drop=True)
    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def compute_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """在 OHLCV 上计算技术指标。"""
    if df.empty or len(df) < 60:
        return df
    close = df["close"]
    high = df["high"]
    low = df["low"]
    vol = df["volume"]

    df["ema12"] = close.ewm(span=12, adjust=False).mean()
    df["ema26"] = close.ewm(span=26, adjust=False).mean()
    df["ema20"] = close.ewm(span=20, adjust=False).mean()
    df["ema50"] = close.ewm(span=50, adjust=False).mean()
    df["ema200"] = close.ewm(span=200, adjust=False).mean()

    ema12 = df["ema12"]
    ema26 = df["ema26"]
    macd_line = ema12 - ema26
    signal = macd_line.ewm(span=9, adjust=False).mean()
    df["macd"] = macd_line
    df["macd_signal"] = signal
    df["macd_hist"] = macd_line - signal

    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    df["rsi14"] = 100 - (100 / (1 + rs))

    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    df["atr14"] = atr

    up = high.diff()
    down = -low.diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr_s = tr.rolling(14).sum()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).rolling(14).sum() / tr_s
    minus_di = 100 * pd.Series(minus_dm, index=df.index).rolling(14).sum() / tr_s
    dx = (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan) * 100
    df["adx14"] = dx.rolling(14).mean()

    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    df["bb_upper"] = bb_mid + 2 * bb_std
    df["bb_lower"] = bb_mid - 2 * bb_std
    df["bb_pct_b"] = (close - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"]).replace(0, np.nan)

    df["vol_ma20"] = vol.rolling(20).mean()
    df["vol_ratio"] = vol / df["vol_ma20"].replace(0, np.nan)

    df["obv"] = (np.sign(close.diff().fillna(0)) * vol).fillna(0).cumsum()
    df["obv_slope10"] = df["obv"].diff(10)

    return df


def _detect_golden_crosses(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """EMA12 上穿 EMA26 的金叉事件及量能。"""
    if "ema12" not in df.columns or len(df) < 30:
        return []
    cross_up = (df["ema12"] > df["ema26"]) & (df["ema12"].shift(1) <= df["ema26"].shift(1))
    events = []
    for idx in df.index[cross_up.fillna(False)]:
        row = df.loc[idx]
        events.append({
            "time": int(row["time"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]),
            "vol_ratio": float(row["vol_ratio"]) if pd.notna(row.get("vol_ratio")) else None,
        })
    return events


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _macd_on_df(df: pd.DataFrame) -> pd.DataFrame:
    """MACD(12,26,9)，与 Pine ta.macd 一致。"""
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


def _macd_state_at_close(df: pd.DataFrame) -> Dict[str, Any]:
    """已收盘 K 线 MACD 状态（金叉/死叉/区间，对齐 Pine 无重绘）。"""
    empty = {
        "is_above": False,
        "golden": False,
        "death": False,
        "macd": None,
        "macd_signal": None,
        "zone": "—",
    }
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
    is_above = curr_m > curr_s
    golden = curr_m > curr_s and prev_m <= prev_s
    death = curr_m < curr_s and prev_m >= prev_s
    zone = "金叉区间" if is_above else "死叉区间"
    cross = "金叉" if golden else ("死叉" if death else "—")
    return {
        "is_above": is_above,
        "golden": golden,
        "death": death,
        "macd": round(curr_m, 6),
        "macd_signal": round(curr_s, 6),
        "zone": zone,
        "cross": cross,
    }


def _bg_cond_active(cond_type: str, is_above: bool) -> bool:
    if cond_type == "金叉区间":
        return is_above
    if cond_type == "死叉区间":
        return not is_above
    if cond_type == "无":
        return True
    return False


def _cross_event_trigger(cond_type: str, golden: bool, death: bool) -> bool:
    """Pine「金叉后/死叉后」：交叉事件，可用于进场或离场，语义由配置决定。"""
    if cond_type == "金叉后":
        return golden
    if cond_type == "死叉后":
        return death
    return False


def _eval_pine_background(
    cfg: Dict[str, Any],
    bg1: Dict[str, Any],
    bg2: Dict[str, Any],
    bg3: Dict[str, Any],
) -> bool:
    """Pine §4 交易背景：区间判定 + bg_logic（默认且；bg2/bg3 可为无）。"""
    logic = str(cfg.get("pine_bg_logic") or cfg.get("bg_logic") or "且")
    flags = [
        _bg_cond_active(
            str(cfg.get("pine_bg_cond1") or cfg.get("bg_cond1") or "金叉区间"),
            bg1["is_above"],
        ),
        _bg_cond_active(
            str(cfg.get("pine_bg_cond2") or cfg.get("bg_cond2") or "无"),
            bg2["is_above"],
        ),
        _bg_cond_active(
            str(cfg.get("pine_bg_cond3") or cfg.get("bg_cond3") or "无"),
            bg3["is_above"],
        ),
    ]
    return all(flags) if logic == "且" else any(flags)


def _eval_pine_exit(
    cfg: Dict[str, Any],
    exit1: Optional[Dict[str, Any]],
    exit2: Optional[Dict[str, Any]],
) -> Tuple[bool, bool, bool]:
    """Pine §6 离场：exit_cond + exit_logic（默认 D 金叉后，或）。"""
    c1 = str(cfg.get("exit_cond1") or "金叉后")
    c2 = str(cfg.get("exit_cond2") or "无")
    logic = str(cfg.get("exit_logic") or "或")
    t1 = (
        _cross_event_trigger(c1, exit1["golden"], exit1["death"])
        if exit1 and c1 != "无"
        else False
    )
    t2 = (
        _cross_event_trigger(c2, exit2["golden"], exit2["death"])
        if exit2 and c2 != "无"
        else False
    )
    if logic == "且":
        has1, has2 = c1 != "无", c2 != "无"
        if has1 and has2:
            met = t1 and t2
        elif has1:
            met = t1
        elif has2:
            met = t2
        else:
            met = False
    else:
        met = t1 or t2
    return met, t1, t2


def _fetch_macd_state(hl_coin: str, tv_tf: str, kline_limit: int) -> Tuple[Optional[Dict[str, Any]], str]:
    iv = tv_tf_to_hl(tv_tf)
    klines = fetch_klines_crypto(hl_coin, iv, total_limit=max(50, kline_limit))
    if not klines or len(klines) < 35:
        return None, f"{hl_coin} {iv} K线不足"
    df = _macd_on_df(klines_to_df(klines))
    return _macd_state_at_close(df), ""


def _resolve_bg_layers(
    cfg: Dict[str, Any],
    states: Dict[str, Optional[Dict[str, Any]]],
) -> Tuple[List[bool], List[str]]:
    """收集参与判定的背景层（cond≠无）的通过情况。"""
    ok_flags: List[bool] = []
    labels: List[str] = []
    for key, tf_key, cond_key in (
        ("bg1", "bg_tf1", "bg_cond1"),
        ("bg2", "bg_tf2", "bg_cond2"),
        ("bg3", "bg_tf3", "bg_cond3"),
    ):
        cond = str(cfg.get(cond_key) or "无")
        if cond == "无":
            continue
        st = states.get(key)
        if not st:
            continue
        tf = cfg.get(tf_key) or key
        ok = _bg_cond_active(cond, st["is_above"])
        ok_flags.append(ok)
        labels.append(f"{tf}({cond})")
    return ok_flags, labels


def evaluate_three_layer_filter(
    hl_coin: str,
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, Dict[str, Any], List[str]]:
    """
    上涨趋势扫描（MACD 金叉区间）：
    - is_uptrend：周线 且 日线 同时金叉区间
    - strong_trend：在上述基础上，8h 也处于金叉区间

    Pine 进场/离场（entry 8h 死叉、exit 日线金叉）仍单独计算，见 layer 字段。
    返回 (is_uptrend, layer_metrics, errors)
    """
    cfg = config or load_scan_config()
    limit = int(cfg.get("kline_limit") or 100)
    errors: List[str] = []

    def _state(label: str, tf: str) -> Optional[Dict[str, Any]]:
        st, err = _fetch_macd_state(hl_coin, tf, limit)
        if err:
            errors.append(err)
        return st

    tf_w = cfg.get("uptrend_tf1") or cfg.get("bg_tf1") or "1w"
    tf_d = cfg.get("uptrend_tf2") or cfg.get("bg_tf2") or "1d"
    tf_8h = cfg.get("strong_tf") or cfg.get("bg_tf3") or "8h"
    cond_w = str(cfg.get("uptrend_cond1") or cfg.get("bg_cond1") or "金叉区间")
    cond_d = str(cfg.get("uptrend_cond2") or cfg.get("bg_cond2") or "金叉区间")
    cond_8h = str(cfg.get("strong_cond") or cfg.get("bg_cond3") or "金叉区间")

    w_st = _state("1w", tf_w)
    d_st = _state("1d", tf_d)
    h8_st = _state("8h", tf_8h)
    entry_st = _state("entry", cfg.get("entry_tf") or "8h")
    exit1_st = _state("exit1", cfg.get("exit_tf1") or "1d")
    exit2_st = _state("exit2", cfg.get("exit_tf2") or "4h")

    if not w_st or not d_st or not h8_st:
        return False, {"reject_reason": "周线/日线/8h K线不足"}, errors

    w_ok = _bg_cond_active(cond_w, w_st["is_above"])
    d_ok = _bg_cond_active(cond_d, d_st["is_above"])
    h8_ok = _bg_cond_active(cond_8h, h8_st["is_above"])

    uptrend_met = bool(w_ok and d_ok)
    strong_met = bool(uptrend_met and h8_ok)

    # Pine 实盘背景 gate（默认仅日线金叉，4h/2h 配置为「无」）
    pine_bg_met = _eval_pine_background(
        cfg, d_st, {"is_above": True}, {"is_above": True},
    )

    # Pine 进场：8h「死叉后」= 死叉交叉事件（开多，不是离场）
    entry_trigger = False
    if entry_st:
        entry_trigger = _cross_event_trigger(
            str(cfg.get("entry_cond") or "死叉后"),
            entry_st["golden"],
            entry_st["death"],
        )

    exit_met, exit1_trigger, exit2_trigger = _eval_pine_exit(cfg, exit1_st, exit2_st)
    pine_entry_ready = bool(pine_bg_met and entry_trigger)

    requires_entry = bool(cfg.get("uptrend_requires_entry"))
    is_uptrend = bool(uptrend_met and (entry_trigger if requires_entry else True))

    reasons: List[str] = []
    if not w_ok:
        reasons.append(f"周线({tf_w})非{cond_w}")
    if not d_ok:
        reasons.append(f"日线({tf_d})非{cond_d}")
    if uptrend_met and not h8_ok:
        reasons.append(f"8h({tf_8h})非{cond_8h}（强趋势须三周期同时金叉）")
    if requires_entry and not entry_trigger:
        reasons.append(
            f"进场({cfg.get('entry_tf')})未出现{cfg.get('entry_cond')}交叉（Pine开多条件）"
        )

    golden_count = sum(1 for x in (w_ok, d_ok, h8_ok) if x)

    layer = {
        "filter_name": cfg.get("filter_name"),
        "uptrend_rule": "周线且日线金叉区间",
        "strong_rule": "周线且日线且8h金叉区间",
        "uptrend_met": uptrend_met,
        "strong_trend": strong_met,
        "bg_conditions_met": strong_met,
        "pine_bg_met": pine_bg_met,
        "pine_entry_ready": pine_entry_ready,
        "golden_tf_count": golden_count,
        "weekly_ok": w_ok,
        "daily_ok": d_ok,
        "h8_ok": h8_ok,
        "entry_trigger": entry_trigger,
        "entry_role": "进场",
        "exit_conditions_met": exit_met,
        "exit1_trigger": exit1_trigger,
        "exit2_trigger": exit2_trigger,
        "exit_role": "离场",
        "uptrend_requires_entry": requires_entry,
        "bg1_tf": tf_w,
        "bg1_cond": cond_w,
        "bg1_zone": w_st.get("zone"),
        "bg1_ok": w_ok,
        "bg2_tf": tf_d,
        "bg2_cond": cond_d,
        "bg2_zone": d_st.get("zone"),
        "bg2_ok": d_ok,
        "bg3_tf": tf_8h,
        "bg3_cond": cond_8h,
        "bg3_zone": h8_st.get("zone"),
        "bg3_ok": h8_ok,
        "entry_tf": cfg.get("entry_tf"),
        "entry_cond": cfg.get("entry_cond"),
        "entry_cross": entry_st.get("cross") if entry_st else "—",
        "entry_zone": entry_st.get("zone") if entry_st else "—",
        "exit_tf1": cfg.get("exit_tf1"),
        "exit_cond1": cfg.get("exit_cond1"),
        "exit1_cross": exit1_st.get("cross") if exit1_st else "—",
        "exit_tf2": cfg.get("exit_tf2"),
        "exit_cond2": cfg.get("exit_cond2"),
        "exit2_cross": exit2_st.get("cross") if exit2_st else "—",
        "reject_reason": "；".join(reasons) if reasons else None,
    }
    return is_uptrend, layer, errors


def _compute_trend_score(metrics: Dict[str, Any], df: pd.DataFrame) -> float:
    """
    连续型趋势分 0–100，用于 Top50 内排序区分强弱（非布尔累加）。
    权重：近 20 根动量 35 + EMA 结构 25 + RSI 15 + MACD 15 + ADX 10。
    """
    last = df.iloc[-1]
    score = 0.0

    # 近 N 根涨幅：0%→0 分，5%→约 18，10%+→满分 35
    recent_pct = float(metrics.get("recent_change_pct") or 0)
    if recent_pct > 0:
        score += 35.0 * _clamp(recent_pct / 10.0, 0.0, 1.0)
    else:
        score += max(0.0, 10.0 + recent_pct * 2.0)  # 小幅回撤仍给少量分便于排序

    close = float(metrics.get("close") or 0)
    ema20 = metrics.get("ema20")
    ema50 = metrics.get("ema50")
    if ema20 and float(ema20) > 0:
        dist20 = (close / float(ema20) - 1.0) * 100.0
        score += 12.0 * _clamp(dist20 / 4.0, 0.0, 1.0)  # 站上 EMA20 约 4% 满分
    if ema20 and ema50 and float(ema50) > 0:
        spread = (float(ema20) / float(ema50) - 1.0) * 100.0
        score += 8.0 * _clamp(spread / 2.0, 0.0, 1.0)
    if metrics.get("ema20_rising"):
        score += 5.0

    rsi = metrics.get("rsi14")
    if rsi is not None:
        r = float(rsi)
        if 45 <= r <= 75:
            score += 15.0 * (1.0 - abs(r - 60.0) / 15.0)  # 60 附近最强
        elif r > 75:
            score += max(0.0, 8.0 - (r - 75.0) * 0.4)  # 过热扣分
        else:
            score += max(0.0, r / 45.0 * 6.0)

    macd_hist = float(last["macd_hist"]) if pd.notna(last.get("macd_hist")) else None
    if macd_hist is not None:
        atr = float(last["atr14"]) if pd.notna(last.get("atr14")) and float(last["atr14"]) > 0 else close * 0.02
        norm = macd_hist / atr if atr > 0 else 0.0
        if macd_hist > 0:
            score += 10.0 * _clamp(norm, 0.0, 1.0)
        if metrics.get("macd_hist_rising"):
            score += 5.0

    adx = metrics.get("adx14")
    if adx is not None:
        score += 10.0 * _clamp((float(adx) - 15.0) / 25.0, 0.0, 1.0)  # ADX 15–40 映射

    # 周线+日线=上涨；再加8h=强趋势
    if metrics.get("uptrend_met") or metrics.get("is_uptrend"):
        score += 12.0
    if metrics.get("strong_trend") or metrics.get("bg_conditions_met"):
        score += 28.0
    gc = int(metrics.get("golden_tf_count") or 0)
    score += gc * 6.0
    if metrics.get("pine_entry_ready"):
        score += 10.0
    if metrics.get("exit_conditions_met"):
        score -= 8.0

    return round(min(100.0, max(0.0, score)), 1)


# 近期趋势窗口（根 K 线数；4h×20 ≈ 3.3 天）
RECENT_UPTREND_BARS = 20
DEFAULT_KLINE_LIMIT = 100
MIN_KLINES_FOR_SCAN = 60


def analyze_uptrend(
    df: pd.DataFrame,
    *,
    min_bars: int = 55,
    hl_coin: Optional[str] = None,
    scan_config: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, Dict[str, Any], List[Dict[str, float]]]:
    """
    上涨趋势判定：周线且日线 MACD 金叉区间；强趋势再加 8h。
    展示周期 K 线仍用于 RSI/EMA 等指标与图表；is_uptrend 由三层过滤决定。
    """
    empty_metrics: Dict[str, Any] = {}
    if df.empty or len(df) < min_bars:
        return False, empty_metrics, []

    df = compute_technical_indicators(df)
    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else last

    golden = _detect_golden_crosses(df)
    last_gc_vol = None
    prev_gc_vols: List[float] = []
    if golden:
        last_gc = golden[-1]
        last_gc_vol = last_gc.get("volume")
        prev_gc_vols = [e["volume"] for e in golden[:-1][-3:] if e.get("volume")]

    ret_20 = float((last["close"] / df["close"].iloc[-21] - 1) * 100) if len(df) > 21 else 0.0
    ret_50 = float((last["close"] / df["close"].iloc[-51] - 1) * 100) if len(df) > 51 else 0.0

    n_recent = min(RECENT_UPTREND_BARS, len(df) - 1)
    recent_slice = df.tail(n_recent + 1)
    recent_start_close = float(recent_slice.iloc[0]["close"])
    recent_end_close = float(recent_slice.iloc[-1]["close"])
    recent_change_pct = (
        (recent_end_close / recent_start_close - 1) * 100 if recent_start_close > 0 else 0.0
    )
    ema20_now = float(last["ema20"]) if pd.notna(last.get("ema20")) else None
    ema20_prev = (
        float(df.iloc[-4]["ema20"])
        if len(df) >= 4 and pd.notna(df.iloc[-4].get("ema20"))
        else None
    )
    ema20_rising = (
        ema20_now is not None and ema20_prev is not None and ema20_now > ema20_prev
    )

    metrics = {
        "close": float(last["close"]),
        "rsi14": round(float(last["rsi14"]), 2) if pd.notna(last.get("rsi14")) else None,
        "macd": round(float(last["macd"]), 6) if pd.notna(last.get("macd")) else None,
        "macd_signal": round(float(last["macd_signal"]), 6) if pd.notna(last.get("macd_signal")) else None,
        "macd_hist": round(float(last["macd_hist"]), 6) if pd.notna(last.get("macd_hist")) else None,
        "adx14": round(float(last["adx14"]), 2) if pd.notna(last.get("adx14")) else None,
        "atr14": round(float(last["atr14"]), 6) if pd.notna(last.get("atr14")) else None,
        "bb_pct_b": round(float(last["bb_pct_b"]), 3) if pd.notna(last.get("bb_pct_b")) else None,
        "vol_ratio": round(float(last["vol_ratio"]), 3) if pd.notna(last.get("vol_ratio")) else None,
        "ema20": round(float(last["ema20"]), 6) if pd.notna(last.get("ema20")) else None,
        "ema50": round(float(last["ema50"]), 6) if pd.notna(last.get("ema50")) else None,
        "ema200": round(float(last["ema200"]), 6) if pd.notna(last.get("ema200")) else None,
        "recent_bars": n_recent,
        "recent_change_pct": round(recent_change_pct, 2),
        "return_20_bars_pct": round(ret_20, 2),
        "return_50_bars_pct": round(ret_50, 2),
        "golden_cross_count": len(golden),
        "last_golden_cross_volume": last_gc_vol,
        "prev_golden_cross_volumes": prev_gc_vols,
        "last_golden_cross_vol_vs_prev_avg": (
            round(last_gc_vol / (sum(prev_gc_vols) / len(prev_gc_vols)), 3)
            if last_gc_vol and prev_gc_vols and sum(prev_gc_vols) > 0
            else None
        ),
        "price_above_ema20": bool(last["close"] > last["ema20"]) if pd.notna(last.get("ema20")) else False,
        "price_above_ema50": bool(last["close"] > last["ema50"]) if pd.notna(last.get("ema50")) else False,
        "ema20_above_ema50": bool(last["ema20"] > last["ema50"]) if pd.notna(last.get("ema20")) else False,
        "macd_bullish": bool(last["macd_hist"] > 0) if pd.notna(last.get("macd_hist")) else False,
        "macd_hist_rising": bool(last["macd_hist"] > prev["macd_hist"]) if pd.notna(last.get("macd_hist")) else False,
        "ema20_rising": ema20_rising,
    }

    # 三层过滤（Pine 策略）
    is_uptrend = False
    layer: Dict[str, Any] = {}
    if hl_coin:
        is_uptrend, layer, _layer_errs = evaluate_three_layer_filter(hl_coin, scan_config)
        metrics.update(layer)
    else:
        # 无币种时回退：仅背景近似（单周期 MACD 金叉区间）
        macd_above = bool(metrics.get("macd_bullish"))
        is_uptrend = macd_above and metrics.get("price_above_ema20", False)
        metrics["reject_reason"] = None if is_uptrend else "需 hl_coin 才能跑完整三层过滤"

    metrics["trend_score"] = _compute_trend_score(metrics, df)
    metrics["is_uptrend"] = is_uptrend
    if not is_uptrend and not metrics.get("reject_reason"):
        metrics["reject_reason"] = "三层过滤未通过"

    tail = df.tail(min(100, len(df)))
    chart = []
    for _, row in tail.iterrows():
        chart.append({
            "time": int(row["time"]),
            "close": float(row["close"]),
            "ema20": float(row["ema20"]) if pd.notna(row.get("ema20")) else None,
            "ema50": float(row["ema50"]) if pd.notna(row.get("ema50")) else None,
        })

    return is_uptrend, metrics, chart


def scan_top50_uptrend(
    *,
    top_n: int = 50,
    interval: str = "4h",
    kline_limit: int = DEFAULT_KLINE_LIMIT,
    max_workers: int = 1,
) -> Dict[str, Any]:
    """
    扫描 Hyperliquid 永续 24h 成交额 Top N，筛选上涨趋势。
    max_workers 保留参数兼容；顺序拉取避免 HL 限流。
    """
    del max_workers
    t0 = time.time()
    scan_cfg = load_scan_config()
    display_iv = str(scan_cfg.get("display_interval") or interval)
    candidates = fetch_top_market_cap_coins(top_n)

    uptrend_list: List[Dict[str, Any]] = []
    snapshot_list: List[Dict[str, Any]] = []
    errors: List[str] = []

    for i, item in enumerate(candidates):
        hl_coin = item.get("hl_coin") or to_hl_coin(item.get("symbol") or "")
        try:
            klines = fetch_klines_crypto(hl_coin, display_iv, total_limit=kline_limit)
            if not klines or len(klines) < MIN_KLINES_FOR_SCAN:
                errors.append(f"{hl_coin}: K线不足({len(klines) if klines else 0})")
                continue
            df = klines_to_df(klines)
            ok, metrics, chart = analyze_uptrend(
                df, hl_coin=hl_coin, scan_config=scan_cfg,
            )
            row = {
                "symbol": item["symbol"],
                "hl_coin": hl_coin,
                "binance_symbol": hl_coin,
                "name": item.get("name"),
                "market_cap_rank": item.get("market_cap_rank"),
                "day_ntl_vlm": item.get("day_ntl_vlm"),
                "is_uptrend": ok,
                "metrics": metrics,
                "chart": chart,
            }
            snapshot_list.append(row)
            if ok:
                uptrend_list.append(row)
        except Exception as e:
            errors.append(f"{hl_coin}: {e!r}")
        if (i + 1) % 3 == 0:
            time.sleep(0.35)

    snapshot_list.sort(
        key=lambda x: (x.get("metrics") or {}).get("trend_score") or 0,
        reverse=True,
    )
    uptrend_list.sort(key=lambda x: x.get("market_cap_rank") or 999)

    result = {
        "scanned_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "data_source": "hyperliquid",
        "interval": display_iv,
        "kline_limit": kline_limit,
        "filter": scan_cfg,
        "top_n": top_n,
        "total_candidates": len(candidates),
        "analyzed_count": len(snapshot_list),
        "uptrend_count": len(uptrend_list),
        "uptrend_symbols": [x["symbol"] for x in uptrend_list],
        "uptrend_list": uptrend_list,
        "snapshot_list": snapshot_list,
        "errors": errors[:30],
        "duration_sec": round(time.time() - t0, 1),
        "note": (
            "上涨=周线且日线金叉区间；强趋势=再加8h金叉区间。"
            "Pine进场=背景且+8h死叉交叉；Pine离场=D金叉交叉。不调用DeepSeek。"
        ),
    }
    _save_scan_cache(result)
    return result


def _save_scan_cache(data: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SCAN_CACHE_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def load_scan_cache() -> Optional[Dict[str, Any]]:
    if not SCAN_CACHE_PATH.is_file():
        return None
    try:
        return json.loads(SCAN_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
