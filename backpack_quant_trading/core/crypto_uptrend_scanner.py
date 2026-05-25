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


def fetch_klines_crypto(symbol: str, interval: str, total_limit: int = 1000):
    """从 Hyperliquid 拉取 K 线（与实盘同源）。"""
    return fetch_hl_klines_batch(symbol, interval, total_limit=total_limit)


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

    return round(min(100.0, max(0.0, score)), 1)


# 近期趋势窗口（根 K 线数；4h×20 ≈ 3.3 天）
RECENT_UPTREND_BARS = 20
DEFAULT_KLINE_LIMIT = 100
MIN_KLINES_FOR_SCAN = 60


def analyze_uptrend(
    df: pd.DataFrame,
    *,
    min_bars: int = 55,
) -> Tuple[bool, Dict[str, Any], List[Dict[str, float]]]:
    """
    近期上涨趋势：最近 20 根收盘走高 + 现价在 EMA20 上方。
    趋势分为连续计分，用于 Top50 内区分强弱排序。
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

    # 近期上涨趋势（宽松）：最近 N 根走高 + 站在 EMA20 上方
    recent_up = recent_change_pct > 0
    above_ema20 = metrics["price_above_ema20"]
    is_uptrend = bool(recent_up and above_ema20)

    metrics["trend_score"] = _compute_trend_score(metrics, df)
    metrics["is_uptrend"] = is_uptrend
    if not is_uptrend:
        reasons = []
        if not recent_up:
            reasons.append(f"近{n_recent}根未上涨")
        if not above_ema20:
            reasons.append("低于EMA20")
        metrics["reject_reason"] = "；".join(reasons)

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
    candidates = fetch_top_market_cap_coins(top_n)

    uptrend_list: List[Dict[str, Any]] = []
    snapshot_list: List[Dict[str, Any]] = []
    errors: List[str] = []

    for i, item in enumerate(candidates):
        hl_coin = item.get("hl_coin") or to_hl_coin(item.get("symbol") or "")
        try:
            klines = fetch_klines_crypto(hl_coin, interval, total_limit=kline_limit)
            if not klines or len(klines) < MIN_KLINES_FOR_SCAN:
                errors.append(f"{hl_coin}: K线不足({len(klines) if klines else 0})")
                continue
            df = klines_to_df(klines)
            ok, metrics, chart = analyze_uptrend(df)
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
        if (i + 1) % 5 == 0:
            time.sleep(0.2)

    snapshot_list.sort(
        key=lambda x: (x.get("metrics") or {}).get("trend_score") or 0,
        reverse=True,
    )
    uptrend_list.sort(key=lambda x: x.get("market_cap_rank") or 999)

    result = {
        "scanned_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "data_source": "hyperliquid",
        "interval": interval,
        "kline_limit": kline_limit,
        "top_n": top_n,
        "total_candidates": len(candidates),
        "analyzed_count": len(snapshot_list),
        "uptrend_count": len(uptrend_list),
        "uptrend_symbols": [x["symbol"] for x in uptrend_list],
        "uptrend_list": uptrend_list,
        "snapshot_list": snapshot_list,
        "errors": errors[:30],
        "duration_sec": round(time.time() - t0, 1),
        "note": "上涨趋势扫描不调用 DeepSeek，仅本地指标计算。",
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
