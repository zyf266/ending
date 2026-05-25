"""加密货币上涨趋势扫描 + Webhook 买入信号 DeepSeek 评分 API。"""
from __future__ import annotations

import threading
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backpack_quant_trading.api.deps import require_user
from backpack_quant_trading.core.crypto_signal_scorer import (
    load_config,
    list_score_history,
    run_signal_score_and_push,
    save_config,
)
from backpack_quant_trading.core.crypto_uptrend_scanner import (
    load_scan_cache,
    scan_top50_uptrend,
)
from backpack_quant_trading.core.stock_news_alert import send_dingtalk_text

router = APIRouter()

_scan_lock = threading.Lock()
_scan_running = False


class ConfigUpdate(BaseModel):
    webhook_scorer_enabled: Optional[bool] = None
    dingtalk_webhook: Optional[str] = None
    dingtalk_keyword: Optional[str] = None
    kline_interval: Optional[str] = None
    kline_limit: Optional[int] = None
    min_deepseek_score: Optional[int] = None
    scan_top_n: Optional[int] = None
    only_actions: Optional[list] = None
    deepseek_temperature: Optional[float] = None


class TestScoreRequest(BaseModel):
    symbol: str = "ETH"
    action: str = "buy"
    timeframe: Optional[str] = "4h"


class TestDingtalkRequest(BaseModel):
    text: Optional[str] = None


@router.get("/config")
def get_config(user: dict = Depends(require_user)) -> Dict[str, Any]:
    cfg = load_config()
    return {"config": cfg, "deepseek_configured": bool(__import__("os").getenv("DEEPSEEK_API_KEY"))}


@router.put("/config")
def put_config(body: ConfigUpdate, user: dict = Depends(require_user)) -> Dict[str, Any]:
    updates = body.model_dump(exclude_none=True)
    cfg = save_config(updates)
    return {"ok": True, "config": cfg}


@router.get("/scan")
def get_scan_cache(user: dict = Depends(require_user)) -> Dict[str, Any]:
    cached = load_scan_cache()
    return {"cached": cached is not None, "data": cached, "scan_running": _scan_running}


@router.post("/scan/run")
def run_scan(user: dict = Depends(require_user)) -> Dict[str, Any]:
    global _scan_running
    with _scan_lock:
        if _scan_running:
            return {"ok": False, "message": "扫描任务进行中，请稍后刷新", "scan_running": True}
        _scan_running = True

    cfg = load_config()

    def _job():
        global _scan_running
        try:
            scan_top50_uptrend(
                top_n=int(cfg.get("scan_top_n") or 50),
                interval=str(cfg.get("kline_interval") or "4h"),
                kline_limit=int(cfg.get("kline_limit") or 100),
            )
        finally:
            with _scan_lock:
                _scan_running = False

    threading.Thread(target=_job, daemon=True, name="crypto-uptrend-scan").start()
    return {"ok": True, "message": "已启动后台扫描（HL成交额Top50→Hyperliquid K线→上涨趋势）", "scan_running": True}


@router.post("/scan/run-sync")
def run_scan_sync(user: dict = Depends(require_user)) -> Dict[str, Any]:
    """同步扫描（耗时较长，适合调试）。"""
    cfg = load_config()
    data = scan_top50_uptrend(
        top_n=int(cfg.get("scan_top_n") or 50),
        interval=str(cfg.get("kline_interval") or "4h"),
        kline_limit=int(cfg.get("kline_limit") or 100),
    )
    return {"ok": True, "data": data}


@router.get("/score/history")
def score_history(limit: int = 30, user: dict = Depends(require_user)) -> Dict[str, Any]:
    items = list_score_history(limit)
    return {"items": items, "count": len(items)}


@router.post("/score/test")
def test_score(body: TestScoreRequest, user: dict = Depends(require_user)) -> Dict[str, Any]:
    if not __import__("os").getenv("DEEPSEEK_API_KEY"):
        raise HTTPException(status_code=400, detail="未配置 DEEPSEEK_API_KEY")
    result = run_signal_score_and_push(
        body.symbol,
        body.action,
        timeframe=body.timeframe or "",
        webhook_raw={"test": True},
        strategy_label="manual_test",
    )
    if not result.get("ok"):
        raise HTTPException(status_code=500, detail=result.get("error") or "评分失败")
    return result


@router.post("/test-dingtalk")
def test_dingtalk(body: TestDingtalkRequest, user: dict = Depends(require_user)) -> Dict[str, Any]:
    cfg = load_config()
    url = (cfg.get("dingtalk_webhook") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="未配置钉钉 Webhook")
    text = body.text or "【提醒】加密货币信号评分通道测试 — 配置正常"
    ok, msg = send_dingtalk_text(url, text)
    return {"ok": ok, "message": msg}
