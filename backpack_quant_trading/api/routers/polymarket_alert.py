"""Polymarket 概率监控 API"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backpack_quant_trading.api.deps import require_user
from backpack_quant_trading.core.polymarket_alert import (
    PolymarketAlertService,
    format_dingtalk_test_body,
    get_poll_logs,
    get_polymarket_alert_instance,
    set_polymarket_alert_instance,
    load_config,
    normalize_rules,
    quote_rule,
    resolve_dingtalk_webhook,
    save_config,
    try_restore_from_disk,
    set_polymarket_alert_user_stopped,
    get_polymarket_alert_user_stopped,
    send_dingtalk_text,
)

router = APIRouter()


class PolymarketRuleBody(BaseModel):
    id: Optional[str] = None
    symbol: str = Field(..., description="股票代码，如 MSFT")
    target_price: float = Field(..., gt=0, description="目标价位（美元）")
    threshold_pct: float = Field(..., ge=0, le=100, description="Yes 概率阈值（%），低于则提醒")
    label: Optional[str] = None
    event_id: Optional[str] = None


class PolymarketAlertConfigBody(BaseModel):
    rules: List[PolymarketRuleBody] = Field(default_factory=list)
    poll_interval_sec: int = Field(60, ge=30, le=600)
    alert_cooldown_minutes: int = Field(30, ge=5, le=1440)
    dingtalk_webhook: Optional[str] = None


@router.get("/config")
def get_config(user: dict = Depends(require_user)) -> Dict[str, Any]:
    cfg = load_config()
    out = dict(cfg)
    out.pop("dingtalk_webhook", None)
    wh = resolve_dingtalk_webhook(cfg)
    out["dingtalk_configured"] = bool(wh)
    if wh and len(wh) > 24:
        out["dingtalk_webhook_masked"] = wh[:20] + "…" + wh[-8:]
    out["rules"] = normalize_rules(cfg.get("rules"))
    return out


@router.post("/config")
def post_config(body: PolymarketAlertConfigBody, user: dict = Depends(require_user)) -> Dict[str, str]:
    cfg = load_config()
    prev_wh = resolve_dingtalk_webhook(cfg)
    cfg["poll_interval_sec"] = int(body.poll_interval_sec)
    cfg["alert_cooldown_minutes"] = int(body.alert_cooldown_minutes)
    cfg["rules"] = [r.model_dump() for r in body.rules]
    wh = (body.dingtalk_webhook or "").strip()
    if wh:
        cfg["dingtalk_webhook"] = wh
    elif prev_wh and not str(cfg.get("dingtalk_webhook") or "").strip():
        cfg["dingtalk_webhook"] = prev_wh
    save_config(cfg)
    return {"message": "已保存"}


@router.get("/status")
def get_status(user: dict = Depends(require_user)) -> Dict[str, Any]:
    cfg = load_config()
    if get_polymarket_alert_user_stopped():
        return _status_payload(cfg, running=False)
    inst = get_polymarket_alert_instance()
    running = bool(inst and inst.is_running())
    if not running and cfg.get("running"):
        try_restore_from_disk()
        inst = get_polymarket_alert_instance()
        running = bool(inst and inst.is_running())
    return _status_payload(cfg, running=running, inst=inst)


def _status_payload(cfg: Dict[str, Any], running: bool, inst: Optional[PolymarketAlertService] = None) -> Dict[str, Any]:
    return {
        "running": running,
        "restored": bool(cfg.get("running") and running),
        "last_error": getattr(inst, "last_error", None) if inst else None,
        "last_poll_at": getattr(inst, "last_poll_at", None) if inst else None,
        "last_push_count": getattr(inst, "last_push_count", 0) if inst else 0,
        "last_poll_summary": getattr(inst, "last_poll_summary", None) if inst else None,
        "last_quotes": getattr(inst, "last_quotes", None) if inst else [],
        "poll_logs": get_poll_logs(20),
        "rules": normalize_rules(cfg.get("rules")),
        "dingtalk_configured": bool(resolve_dingtalk_webhook(cfg)),
    }


@router.post("/start")
def start_alert(user: dict = Depends(require_user)) -> Dict[str, Any]:
    set_polymarket_alert_user_stopped(False)
    cfg = load_config()
    rules = normalize_rules(cfg.get("rules"))
    if not rules:
        raise HTTPException(status_code=400, detail="请先添加至少一条监控规则并保存")
    if not resolve_dingtalk_webhook(cfg):
        raise HTTPException(
            status_code=400,
            detail="未配置钉钉：请在 polymarket_alert_config.json 或自选快讯配置中设置 Webhook",
        )
    inst = get_polymarket_alert_instance()
    if inst and inst.is_running():
        inst.stop()
    svc = PolymarketAlertService()
    set_polymarket_alert_instance(svc)
    svc.start()
    cfg["running"] = True
    save_config(cfg)
    return {"message": "已启动", "running": True}


@router.post("/stop")
def stop_alert(user: dict = Depends(require_user)) -> Dict[str, Any]:
    set_polymarket_alert_user_stopped(True)
    inst = get_polymarket_alert_instance()
    if inst:
        inst.stop()
    set_polymarket_alert_instance(None)
    cfg = load_config()
    cfg["running"] = False
    save_config(cfg)
    return {"message": "已停止", "running": False}


@router.post("/test-dingtalk")
def test_dingtalk(user: dict = Depends(require_user)) -> Dict[str, Any]:
    cfg = load_config()
    url = resolve_dingtalk_webhook(cfg)
    if not url:
        raise HTTPException(status_code=400, detail="未配置钉钉 Webhook")
    ok, msg = send_dingtalk_text(url, format_dingtalk_test_body())
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True}


@router.get("/quote")
def quote_one(
    symbol: str,
    target_price: float,
    threshold_pct: float = 30,
    user: dict = Depends(require_user),
) -> Dict[str, Any]:
    rule = {
        "id": "preview",
        "symbol": symbol.strip().upper(),
        "target_price": target_price,
        "threshold_pct": threshold_pct,
    }
    return quote_rule(rule)


@router.get("/quotes")
def quote_all(user: dict = Depends(require_user)) -> Dict[str, Any]:
    cfg = load_config()
    rules = normalize_rules(cfg.get("rules"))
    return {"quotes": [quote_rule(r) for r in rules]}


@router.get("/poll-logs")
def poll_logs(limit: int = 30, user: dict = Depends(require_user)) -> Dict[str, Any]:
    n = max(1, min(int(limit or 30), 60))
    inst = get_polymarket_alert_instance()
    return {
        "logs": get_poll_logs(n),
        "last_poll_summary": getattr(inst, "last_poll_summary", None) if inst else None,
    }
