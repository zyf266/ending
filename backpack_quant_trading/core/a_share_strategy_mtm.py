"""
A 股动量策略（300308 / 603986 / 688146）最后一笔未平仓持仓：
按最近交易日收盘价盯市，供 overview / trades 展示与矩阵收益刷新。
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, time as dt_time, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

MTM_CODES = frozenset({"300308", "603986", "688146"})
MTM_EXIT_SIGNAL_KEYS = ("开盘价", "收盘价", "收盘")
CACHE_PATH = Path(__file__).resolve().parents[1] / "data" / "a_share_strategy_close_cache.json"


def _is_entry(trade_type: Any) -> bool:
    return "进场" in str(trade_type or "")


def _is_exit(trade_type: Any) -> bool:
    tp = str(trade_type or "")
    return ("出" in tp) or ("止损" in tp)


def _is_mtm_exit_signal(signal: Any) -> bool:
    sig = str(signal or "")
    return any(k in sig for k in MTM_EXIT_SIGNAL_KEYS)


def _trade_to_ns(row: Any) -> SimpleNamespace:
    return SimpleNamespace(
        trade_no=getattr(row, "trade_no", None),
        trade_type=getattr(row, "trade_type", None),
        signal=getattr(row, "signal", None),
        trade_time=getattr(row, "trade_time", None),
        price=float(getattr(row, "price", 0) or 0),
        position_qty=float(getattr(row, "position_qty", 0) or 0),
        position_value=float(getattr(row, "position_value", 0) or 0),
        pnl=float(getattr(row, "pnl", 0) or 0),
        pnl_pct=float(getattr(row, "pnl_pct", 0) or 0),
        runup=float(getattr(row, "runup", 0) or 0) if getattr(row, "runup", None) is not None else None,
        runup_pct=float(getattr(row, "runup_pct", 0) or 0) if getattr(row, "runup_pct", None) is not None else None,
        drawdown=float(getattr(row, "drawdown", 0) or 0) if getattr(row, "drawdown", None) is not None else None,
        drawdown_pct=float(getattr(row, "drawdown_pct", 0) or 0) if getattr(row, "drawdown_pct", None) is not None else None,
        cum_pnl=float(getattr(row, "cum_pnl", 0) or 0),
        cum_pnl_pct=float(getattr(row, "cum_pnl_pct", 0) or 0),
        symbol=getattr(row, "symbol", None),
        timeframe=getattr(row, "timeframe", None),
    )


def load_close_cache() -> Dict[str, Any]:
    if not CACHE_PATH.exists():
        return {"quotes": {}, "updated_at": None}
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("读取 A股收盘价缓存失败: %s", exc)
        return {"quotes": {}, "updated_at": None}


def save_close_cache(data: Dict[str, Any]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _fetch_sina_daily_close(code: str) -> Tuple[Optional[float], Optional[date]]:
    from backpack_quant_trading.core.a_share_strategy_import import _direct_get, _sina_symbol

    sym = _sina_symbol(code)
    try:
        r = _direct_get(
            "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData",
            params={"symbol": sym, "scale": 240, "ma": "no", "datalen": 30},
            headers={"User-Agent": "Mozilla/5.0"},
        )
        r.raise_for_status()
        rows = r.json() or []
    except Exception as exc:
        logger.debug("新浪日收盘 %s 失败: %s", code, exc)
        return None, None
    if not rows:
        return None, None
    last = rows[-1]
    try:
        day = datetime.strptime(str(last.get("day") or "")[:10], "%Y-%m-%d").date()
        close = float(last["close"])
        return (close, day) if close > 0 else (None, None)
    except (TypeError, ValueError, KeyError):
        return None, None


def fetch_latest_daily_close(code: str) -> Tuple[Optional[float], Optional[date], str]:
    """最新交易日收盘价：新浪日线 → 东财日线 → 实时价兜底。"""
    c = str(code or "").strip()
    px, d = _fetch_sina_daily_close(c)
    if px is not None and d is not None:
        return px, d, "sina_daily"

    from backpack_quant_trading.core.a_share_strategy_import import fetch_eastmoney_klines_daily

    start = datetime.now() - timedelta(days=40)
    bars, _ = fetch_eastmoney_klines_daily(c, start)
    if bars:
        last = bars[-1]
        close = float(last["close"])
        td = last["timestamp"].date() if hasattr(last["timestamp"], "date") else None
        if close > 0 and td is not None:
            return close, td, "eastmoney_daily"

    from backpack_quant_trading.core.research_card_prices import fetch_a_share_price

    live, src = fetch_a_share_price(c)
    if live is not None and live > 0:
        return float(live), datetime.now().date(), f"{src}_live"
    return None, None, "none"


def refresh_mtm_close_prices(codes: Optional[List[str]] = None) -> Dict[str, Any]:
    """拉取并缓存三只 A 股策略标的最近收盘价。"""
    targets = [c for c in (codes or sorted(MTM_CODES)) if c in MTM_CODES]
    quotes: Dict[str, Any] = {}
    for code in targets:
        close, trade_date, source = fetch_latest_daily_close(code)
        if close is None or trade_date is None:
            logger.warning("A股 %s 收盘价获取失败", code)
            continue
        quotes[code] = {
            "close": round(close, 4),
            "trade_date": trade_date.isoformat(),
            "source": source,
        }
        logger.info("A股盯市 %s 收盘 %s @ %s (%s)", code, close, trade_date, source)

    payload = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "quotes": quotes,
    }
    if quotes:
        save_close_cache(payload)
    return payload


def get_cached_close(code: str, *, allow_stale_fetch: bool = True) -> Tuple[Optional[float], Optional[date], str]:
    cache = load_close_cache()
    hit = (cache.get("quotes") or {}).get(str(code))
    if hit and hit.get("close"):
        try:
            return (
                float(hit["close"]),
                date.fromisoformat(str(hit["trade_date"])),
                str(hit.get("source") or "cache"),
            )
        except (TypeError, ValueError):
            pass
    if allow_stale_fetch:
        close, trade_date, source = fetch_latest_daily_close(code)
        if close is not None:
            return close, trade_date, source
    return None, None, "none"


def _prior_closed_cum(trades: List[SimpleNamespace], open_trade_no: int) -> float:
    best = 0.0
    for t in trades:
        if int(t.trade_no or 0) >= int(open_trade_no):
            continue
        if _is_exit(t.trade_type):
            best = float(t.cum_pnl or 0)
    return best


def _intratrade_excursion(
    entry: SimpleNamespace,
    mark_price: float,
    klines: Optional[List[Any]],
) -> Tuple[float, float, float, float]:
    entry_price = float(entry.price or 0)
    qty = float(entry.position_qty or 0)
    if entry_price <= 0 or qty <= 0:
        return 0.0, 0.0, 0.0, 0.0

    high = mark_price
    low = mark_price
    entry_time = entry.trade_time
    if klines and entry_time is not None:
        for k in klines:
            ts = getattr(k, "timestamp", None)
            if ts is None or ts < entry_time:
                continue
            high = max(high, float(getattr(k, "high", mark_price) or mark_price))
            low = min(low, float(getattr(k, "low", mark_price) or mark_price))

    runup = qty * (high - entry_price)
    drawdown = qty * (low - entry_price)
    runup_pct = (high / entry_price - 1.0) * 100.0
    drawdown_pct = (low / entry_price - 1.0) * 100.0
    return runup, runup_pct, drawdown, drawdown_pct


def _apply_mtm_leg(
    entry: SimpleNamespace,
    exit_leg: SimpleNamespace,
    *,
    mark_price: float,
    mark_date: date,
    initial_capital: float,
    prior_cum: float,
    klines: Optional[List[Any]],
) -> None:
    entry_price = float(entry.price or 0)
    qty = float(entry.position_qty or 0)
    pos_val = float(entry.position_value or 0)
    if entry_price <= 0 or qty <= 0:
        return

    pnl = qty * (mark_price - entry_price)
    pnl_pct = (mark_price / entry_price - 1.0) * 100.0
    cum_pnl = prior_cum + pnl
    cum_pnl_pct = cum_pnl / float(initial_capital) * 100.0 if initial_capital > 0 else 0.0
    runup, runup_pct, drawdown, drawdown_pct = _intratrade_excursion(entry, mark_price, klines)
    mark_dt = datetime.combine(mark_date, dt_time(15, 0))

    for leg in (entry, exit_leg):
        leg.position_qty = qty
        leg.position_value = pos_val
        leg.pnl = round(pnl, 2)
        leg.pnl_pct = round(pnl_pct, 4)
        leg.runup = round(runup, 2)
        leg.runup_pct = round(runup_pct, 4)
        leg.drawdown = round(drawdown, 2)
        leg.drawdown_pct = round(drawdown_pct, 4)
        leg.cum_pnl = round(cum_pnl, 2)
        leg.cum_pnl_pct = round(cum_pnl_pct, 4)

    exit_leg.trade_type = "多头出场"
    exit_leg.signal = "收盘价"
    exit_leg.price = round(mark_price, 4)
    exit_leg.trade_time = mark_dt


def apply_mtm_to_trades(
    trades: List[Any],
    *,
    code: str,
    initial_capital: float,
    klines: Optional[List[Any]] = None,
) -> List[SimpleNamespace]:
    """若最后一笔仍为持仓中（无出场或出场为开盘价占位），按收盘价重算盈亏。"""
    if code not in MTM_CODES or not trades:
        return [_trade_to_ns(r) for r in trades]

    rows = [_trade_to_ns(r) for r in trades]
    by_no: Dict[int, Dict[str, SimpleNamespace]] = {}
    for r in rows:
        try:
            no = int(r.trade_no)
        except (TypeError, ValueError):
            continue
        bucket = by_no.setdefault(no, {})
        if _is_entry(r.trade_type):
            bucket["entry"] = r
        elif _is_exit(r.trade_type):
            bucket["exit"] = r

    if not by_no:
        return rows

    open_no = max(by_no)
    legs = by_no[open_no]
    entry = legs.get("entry")
    if entry is None:
        return rows

    exit_leg = legs.get("exit")
    needs_mtm = exit_leg is None or _is_mtm_exit_signal(exit_leg.signal)
    if not needs_mtm:
        return rows

    close, close_date, _ = get_cached_close(code)
    if close is None or close_date is None:
        return rows

    if exit_leg is None:
        exit_leg = _trade_to_ns(entry)
        exit_leg.trade_no = open_no
        rows.append(exit_leg)

    prior_cum = _prior_closed_cum(rows, open_no)
    _apply_mtm_leg(
        entry,
        exit_leg,
        mark_price=close,
        mark_date=close_date,
        initial_capital=initial_capital,
        prior_cum=prior_cum,
        klines=klines,
    )
    return rows
