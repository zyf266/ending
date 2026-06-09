"""TradingView / Webhook 信号：区分加密 vs 美股，并路由到对应评分器。"""
from __future__ import annotations

import re
from typing import Any, Dict, Literal, Optional

from backpack_quant_trading.core.massive_klines import normalize_us_ticker

AssetKind = Literal["crypto", "us_stock"]

_CRYPTO_SUFFIXES = ("USDT.P", "USDC.P", "USDT", "USDC", "USD", "PERP", ".P")
_CRYPTO_BASES = frozenset({
    "BTC", "ETH", "SOL", "HYPE", "DOGE", "XRP", "BNB", "ADA", "AVAX", "LINK",
    "DOT", "MATIC", "POL", "UNI", "ATOM", "LTC", "BCH", "FIL", "APT", "ARB",
    "OP", "SUI", "SEI", "TIA", "INJ", "NEAR", "FTM", "AAVE", "MKR", "CRV",
    "WIF", "PEPE", "SHIB", "TRX", "TON", "FET", "RENDER", "WLD", "ONDO",
})

_US_STOCK_WEBHOOK_KEYS = ("asset_type", "资产类型", "market", "市场", "asset_class")
_US_STOCK_VALUES = frozenset({
    "us_stock", "us", "stock", "equity", "美股", "股票", "us_equity", "nasdaq", "nyse",
})
_CRYPTO_VALUES = frozenset({
    "crypto", "cryptocurrency", "perp", "futures", "加密", "合约", "永续",
})


def _webhook_asset_hint(webhook_raw: Optional[Dict[str, Any]]) -> Optional[AssetKind]:
    if not webhook_raw:
        return None
    for key in _US_STOCK_WEBHOOK_KEYS:
        v = str(webhook_raw.get(key) or "").strip().lower()
        if not v:
            continue
        if v in _US_STOCK_VALUES or "stock" in v or "美股" in v:
            return "us_stock"
        if v in _CRYPTO_VALUES or "crypto" in v or "加密" in v:
            return "crypto"
    return None


def classify_signal_asset(
    symbol: str,
    webhook_raw: Optional[Dict[str, Any]] = None,
) -> AssetKind:
    """
    判定信号资产类型（优先级）：
    1. Webhook 显式字段：资产类型 / market / asset_type
    2. 品种后缀：USDT / USDC / PERP / .P → 加密
    3. 已知加密 base（BTC、ETH…）→ 加密
    4. 1–5 位纯字母 ticker → 美股
    5. 默认 → 加密（TV 加密 alert 通常带 USDT）
    """
    hinted = _webhook_asset_hint(webhook_raw)
    if hinted:
        return hinted

    raw = (symbol or "").upper().strip()
    if not raw:
        return "crypto"

    if "/" in raw or raw.endswith(".P"):
        return "crypto"

    for suffix in _CRYPTO_SUFFIXES:
        if raw.endswith(suffix):
            return "crypto"

    base = normalize_us_ticker(raw)
    if base in _CRYPTO_BASES:
        return "crypto"

    if re.fullmatch(r"[A-Z]{1,5}", base):
        return "us_stock"

    return "crypto"


def is_us_stock_signal(symbol: str, webhook_raw: Optional[Dict[str, Any]] = None) -> bool:
    return classify_signal_asset(symbol, webhook_raw) == "us_stock"


def run_signal_score_routed(
    symbol: str,
    action: str,
    *,
    timeframe: str = "",
    webhook_raw: Optional[Dict[str, Any]] = None,
    strategy_label: str = "adaptive_long",
) -> Dict[str, Any]:
    """按品种自动选择 Hyperliquid（加密）或 Massive（美股）评分。"""
    kind = classify_signal_asset(symbol, webhook_raw)
    if kind == "us_stock":
        from backpack_quant_trading.core.us_stock_signal_scorer import run_us_stock_signal_score

        return run_us_stock_signal_score(
            symbol,
            action,
            timeframe=timeframe,
            webhook_raw=webhook_raw,
            strategy_label=strategy_label or "us_stock",
        )

    from backpack_quant_trading.core.crypto_signal_scorer import run_signal_score

    return run_signal_score(
        symbol,
        action,
        timeframe=timeframe,
        webhook_raw=webhook_raw,
        strategy_label=strategy_label,
    )


def run_signal_score_and_push_routed(
    symbol: str,
    action: str,
    *,
    timeframe: str = "",
    webhook_raw: Optional[Dict[str, Any]] = None,
    strategy_label: str = "adaptive_long",
) -> Dict[str, Any]:
    from backpack_quant_trading.core.crypto_signal_scorer import push_score_to_dingtalk

    result = run_signal_score_routed(
        symbol,
        action,
        timeframe=timeframe,
        webhook_raw=webhook_raw,
        strategy_label=strategy_label,
    )
    if result.get("ok"):
        ok, msg = push_score_to_dingtalk(result)
        result["dingtalk_ok"] = ok
        result["dingtalk_msg"] = msg
        result["asset_kind"] = classify_signal_asset(symbol, webhook_raw)
    return result
