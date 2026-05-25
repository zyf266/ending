"""AI 选股卡片：NVDA 研究数据、钉钉推送历史、策略信号。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from backpack_quant_trading.api.deps import require_user
from backpack_quant_trading.core.research_report_hub import (
    get_quote_symbol,
    list_research_codes,
    load_research_card,
    load_research_report,
    resolve_pdf_path,
)
from backpack_quant_trading.core.manual_card_feeds import (
    save_news_paste,
    save_signal_paste,
)
from backpack_quant_trading.core.research_card_feeds import (
    get_latest_news_for_symbol,
    get_latest_signal_for_symbol,
    list_dingtalk_news,
    list_news_for_symbol,
    list_signals_for_symbol,
    text_matches_symbol,
)
from backpack_quant_trading.core.manual_card_feeds import (
    get_latest_signal,
    list_news_history,
    list_signal_history,
)

router = APIRouter()

_DATA = Path(__file__).resolve().parents[2] / "data"

def _summary_matches_symbol(summary: Optional[str], code: str) -> bool:
    return text_matches_symbol(summary or "", code)


def _build_card_hub(code: str, *, fetch_price: bool = True) -> Dict[str, Any]:
    from backpack_quant_trading.core.research_card_prices import (
        get_cached_hub_price,
        fetch_market_price,
    )

    sym = code.upper().strip()
    card = load_research_card(sym)
    cached = get_cached_hub_price(sym)
    price = cached.get("price") if cached else None
    price_updated_at = cached.get("price_updated_at") if cached else None
    currency = (cached.get("currency") if cached else None) or "USD"
    if price is None and fetch_price:
        qsym = get_quote_symbol(sym)
        live, _src = fetch_market_price(sym, qsym)
        if live is not None:
            price = live
            currency = "USD"
    news = get_latest_news_for_symbol(sym)
    signal = get_latest_signal_for_symbol(sym)
    news_summary = (news or {}).get("summary")
    signal_summary = (signal or {}).get("summary")
    return {
        "card": card,
        "price": price,
        "price_updated_at": price_updated_at,
        "currency": currency,
        "latest_news": news,
        "latest_signal": signal,
        "news_summary": news_summary if _summary_matches_symbol(news_summary, sym) else None,
        "signal_summary": signal_summary if _summary_matches_symbol(signal_summary, sym) else None,
    }


@router.get("/research-codes")
def research_codes(user: dict = Depends(require_user)) -> Dict[str, Any]:
    return {"codes": list_research_codes()}


@router.get("/cards")
def get_all_cards(user: dict = Depends(require_user)) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []
    for code in list_research_codes():
        try:
            items.append(_build_card_hub(code, fetch_price=True))
        except FileNotFoundError:
            continue
    return {"items": items, "count": len(items)}


@router.post("/refresh-prices")
def refresh_prices(user: dict = Depends(require_user)) -> Dict[str, Any]:
    from backpack_quant_trading.core.research_card_prices import refresh_research_prices_task

    return refresh_research_prices_task()


@router.get("/card/{symbol}")
def get_card(symbol: str, user: dict = Depends(require_user)) -> Dict[str, Any]:
    try:
        return _build_card_hub(symbol)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/report/{symbol}")
def get_report(symbol: str, user: dict = Depends(require_user)) -> Dict[str, Any]:
    try:
        return load_research_report(symbol)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/pdf/{symbol}")
def get_pdf(symbol: str, user: dict = Depends(require_user)):
    try:
        pdf = resolve_pdf_path(symbol)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return FileResponse(pdf, media_type="application/pdf", filename=pdf.name)


@router.get("/nvda-card")
def get_nvda_card(user: dict = Depends(require_user)) -> Dict[str, Any]:
    return _build_card_hub("NVDA")


@router.get("/quote/{symbol}")
def get_quote(symbol: str, user: dict = Depends(require_user)) -> Dict[str, Any]:
    from backpack_quant_trading.core.research_card_prices import fetch_market_price

    sym = symbol.upper()
    qsym = get_quote_symbol(sym) if sym in list_research_codes() else sym
    p, source = fetch_market_price(sym, qsym)
    return {"symbol": sym, "quote_symbol": qsym, "price": p, "currency": "USD", "source": source}


@router.get("/push-history")
def push_history(
    symbol: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    user: dict = Depends(require_user),
) -> Dict[str, Any]:
    sym = (symbol or "").upper().strip()
    if sym:
        rows = list_news_for_symbol(sym, limit)
    else:
        rows = list_dingtalk_news(limit)
    return {"items": rows, "count": len(rows), "symbol": sym or None}


@router.get("/signals/{symbol}")
def strategy_signals(
    symbol: str,
    limit: int = Query(30, ge=1, le=100),
    user: dict = Depends(require_user),
) -> Dict[str, Any]:
    sym = (symbol or "").upper().strip()
    rows = list_signals_for_symbol(sym, limit)
    return {"items": rows, "count": len(rows), "symbol": sym}


@router.get("/manual-news")
def manual_news(user: dict = Depends(require_user)) -> Dict[str, Any]:
    items = list_news_history(100)
    latest = items[0] if items else get_latest_news_for_symbol("")
    return {"latest": latest, "items": items, "count": len(items)}


@router.get("/manual-signal")
def manual_signal(user: dict = Depends(require_user)) -> Dict[str, Any]:
    items = list_signal_history(100)
    latest = get_latest_signal()
    return {"latest": latest, "items": items, "count": len(items)}


@router.post("/manual-news")
def post_manual_news(body: Dict[str, Any], user: dict = Depends(require_user)) -> Dict[str, Any]:
    raw = str(body.get("paste") or body.get("text") or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="请提供 paste 字段")
    try:
        item = save_news_paste(raw)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "item": item}


@router.post("/manual-signal")
def post_manual_signal(body: Dict[str, Any], user: dict = Depends(require_user)) -> Dict[str, Any]:
    raw = str(body.get("paste") or body.get("text") or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="请提供 paste 字段")
    try:
        item = save_signal_paste(raw)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "item": item}


@router.get("/nvda-report")
def nvda_report(user: dict = Depends(require_user)) -> Dict[str, Any]:
    try:
        return load_research_report("NVDA")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="NVDA 研报数据未找到")


@router.get("/nvda-pdf")
def nvda_pdf(user: dict = Depends(require_user)):
    try:
        pdf = resolve_pdf_path("NVDA")
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return FileResponse(pdf, media_type="application/pdf", filename=pdf.name)


