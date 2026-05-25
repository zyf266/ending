"""自选关键词 + 金十快讯监控 API"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backpack_quant_trading.api.deps import require_user
from backpack_quant_trading.core.stock_news_feeds import (
    DEFAULT_JIN10_APP_ID,
    ALL_SOURCE_KEYS,
    SOURCE_LABELS,
    build_feeds_preview,
    fetch_jin10_flash_rows,
    normalize_enabled_sources,
    probe_sources_status,
)
from backpack_quant_trading.core.stock_news_alert import (
    StockNewsAlertService,
    format_dingtalk_test_body,
    get_poll_logs,
    get_stock_news_alert_instance,
    set_stock_news_alert_instance,
    load_config,
    resolve_dingtalk_webhook,
    save_config,
    try_restore_from_disk,
    set_stock_news_alert_user_stopped,
    get_stock_news_alert_user_stopped,
)

router = APIRouter()


class StockNewsAlertConfigBody(BaseModel):
    watch_names: List[str] = Field(default_factory=list, description="自选名称/代码，多条")
    dingtalk_webhook: Optional[str] = Field(
        None,
        description="可选；仅当传入非空时更新，避免页面保存时清空已有 Webhook",
    )
    poll_interval_sec: int = Field(30, ge=10, le=300)
    only_material: bool = Field(True, description="仅推送含「重要度」或命中影响面关键词的快讯")
    only_extra_impact_keywords: bool = Field(
        False,
        description="为 true 时影响面仅使用 extra_impact_keywords，不含内置加息/财报等",
    )
    extra_impact_keywords: List[str] = Field(default_factory=list)
    news_sources: List[str] = Field(
        default_factory=list,
        description="启用数据源：jin10/ths/eastmoney/sina/futu，空则全选",
    )


class StockNewsAlertStartBody(BaseModel):
    """启动时可选带上页面当前自选词，避免仅 UI 有值、磁盘配置为空。"""

    watch_names: Optional[List[str]] = None


@router.get("/config")
def get_config(user: dict = Depends(require_user)) -> Dict[str, Any]:
    cfg = load_config()
    out = dict(cfg)
    out.pop("dingtalk_webhook", None)
    wh = resolve_dingtalk_webhook(cfg)
    out["dingtalk_configured"] = bool(wh)
    if wh and len(wh) > 24:
        out["dingtalk_webhook_masked"] = wh[:20] + "…" + wh[-8:]
    return out


@router.post("/config")
def post_config(body: StockNewsAlertConfigBody, user: dict = Depends(require_user)) -> Dict[str, str]:
    cfg = load_config()
    prev_wh = resolve_dingtalk_webhook(cfg)
    prev_watch = cfg.get("watch_names") or []
    if isinstance(prev_watch, str):
        prev_watch = [prev_watch]
    names = [str(x).strip() for x in body.watch_names if str(x).strip()]
    cfg["watch_names"] = names if names else [str(x).strip() for x in prev_watch if str(x).strip()]
    cfg["poll_interval_sec"] = int(body.poll_interval_sec)
    cfg["only_material"] = bool(body.only_material)
    cfg["only_extra_impact_keywords"] = bool(body.only_extra_impact_keywords)
    cfg["extra_impact_keywords"] = [str(x).strip() for x in body.extra_impact_keywords if str(x).strip()]
    wh = (body.dingtalk_webhook or "").strip()
    if wh:
        cfg["dingtalk_webhook"] = wh
    elif prev_wh:
        cfg["dingtalk_webhook"] = prev_wh
    allowed = set(ALL_SOURCE_KEYS)
    src = [str(x).strip().lower() for x in (body.news_sources or []) if str(x).strip().lower() in allowed]
    cfg["news_sources"] = src if src else list(ALL_SOURCE_KEYS)
    save_config(cfg)
    return {"message": "已保存"}


@router.get("/status")
def get_status(user: dict = Depends(require_user)) -> Dict[str, Any]:
    cfg = load_config()
    if get_stock_news_alert_user_stopped():
        return {
            "running": False,
            "restored": False,
            "last_error": None,
            "last_poll_at": None,
            "last_push_count": 0,
            "last_poll_summary": None,
            "poll_logs": get_poll_logs(20),
            "log_file": "log/stock_news_alert.log",
            "watch_names": cfg.get("watch_names") or [],
            "news_sources": normalize_enabled_sources(cfg),
        }
    inst = get_stock_news_alert_instance()
    running = bool(inst and inst.is_running())
    if not running and cfg.get("running"):
        try_restore_from_disk()
        inst = get_stock_news_alert_instance()
        running = bool(inst and inst.is_running())
    return {
        "running": running,
        "restored": bool(cfg.get("running") and running),
        "last_error": getattr(inst, "last_error", None) if inst else None,
        "last_poll_at": getattr(inst, "last_poll_at", None) if inst else None,
        "last_push_count": getattr(inst, "last_push_count", 0) if inst else 0,
        "last_poll_summary": getattr(inst, "last_poll_summary", None) if inst else None,
        "poll_logs": get_poll_logs(20),
        "log_file": "log/stock_news_alert.log",
        "watch_names": cfg.get("watch_names") or [],
        "news_sources": normalize_enabled_sources(cfg),
    }


@router.post("/start")
def start_alert(
    body: Optional[StockNewsAlertStartBody] = None,
    user: dict = Depends(require_user),
) -> Dict[str, Any]:
    set_stock_news_alert_user_stopped(False)
    cfg = load_config()
    if body and body.watch_names:
        cfg["watch_names"] = [str(x).strip() for x in body.watch_names if str(x).strip()]
        save_config(cfg)
    names = cfg.get("watch_names") or []
    if isinstance(names, str):
        names = [names]
    names = [str(x).strip() for x in names if str(x).strip()]
    if not names:
        raise HTTPException(status_code=400, detail="请先在配置中填写自选名称")
    if not resolve_dingtalk_webhook(cfg):
        raise HTTPException(
            status_code=400,
            detail="未配置钉钉：请在 data/stock_news_alert_config.json 或环境变量 STOCK_NEWS_DINGTALK_WEBHOOK 中设置",
        )
    inst = get_stock_news_alert_instance()
    if inst and inst.is_running():
        inst.stop()
    svc = StockNewsAlertService()
    set_stock_news_alert_instance(svc)
    svc.start()
    cfg["running"] = True
    save_config(cfg)
    return {"message": "已启动", "running": True}


@router.post("/stop")
def stop_alert(user: dict = Depends(require_user)) -> Dict[str, Any]:
    set_stock_news_alert_user_stopped(True)
    inst = get_stock_news_alert_instance()
    if inst:
        inst.stop()
    set_stock_news_alert_instance(None)
    cfg = load_config()
    cfg["running"] = False
    save_config(cfg)
    return {"message": "已停止", "running": False}


@router.post("/test-dingtalk")
def test_dingtalk(user: dict = Depends(require_user)) -> Dict[str, Any]:
    from backpack_quant_trading.core.stock_news_alert import send_dingtalk_text

    cfg = load_config()
    url = resolve_dingtalk_webhook(cfg)
    if not url:
        raise HTTPException(
            status_code=400,
            detail="未配置钉钉：请在 data/stock_news_alert_config.json 或环境变量 STOCK_NEWS_DINGTALK_WEBHOOK 中设置",
        )
    ok, msg = send_dingtalk_text(url, format_dingtalk_test_body())
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True}


@router.get("/probe-jin10")
def probe_jin10(user: dict = Depends(require_user)) -> Dict[str, Any]:
    """健康检查：金十单源条数（兼容旧前端）。"""
    cfg = load_config()
    x_app = str(cfg.get("jin10_x_app_id") or DEFAULT_JIN10_APP_ID).strip()
    rows, err = fetch_jin10_flash_rows(x_app_id=x_app)
    if err:
        return {"ok": False, "error": err}
    return {"ok": True, "count": len(rows)}


@router.get("/probe-sources")
def probe_sources(user: dict = Depends(require_user)) -> Dict[str, Any]:
    """各数据源连通性与条数。"""
    return probe_sources_status(load_config())


@router.get("/feeds-preview")
def feeds_preview(
    user: dict = Depends(require_user),
    per_source: int = 12,
) -> Dict[str, Any]:
    """聚合预览：各源状态 + 每条若干行快讯（供页面展示）。"""
    per_source = max(3, min(int(per_source or 12), 30))
    return build_feeds_preview(load_config(), per_source=per_source)


@router.get("/poll-logs")
def poll_logs(
    user: dict = Depends(require_user),
    limit: int = 30,
) -> Dict[str, Any]:
    """最近轮询摘要（内存环形缓冲 + 文件 log/stock_news_alert.log）。"""
    n = max(1, min(int(limit or 30), 60))
    inst = get_stock_news_alert_instance()
    return {
        "logs": get_poll_logs(n),
        "last_poll_summary": getattr(inst, "last_poll_summary", None) if inst else None,
        "log_file": "log/stock_news_alert.log",
    }


@router.get("/source-catalog")
def source_catalog(user: dict = Depends(require_user)) -> Dict[str, Any]:
    """可选数据源清单（供前端勾选）。"""
    return {
        "keys": list(ALL_SOURCE_KEYS),
        "labels": {k: SOURCE_LABELS.get(k, k) for k in ALL_SOURCE_KEYS},
    }
