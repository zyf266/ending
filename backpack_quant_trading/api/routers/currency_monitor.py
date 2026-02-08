"""币种监视 API - 全局共享，不按用户隔离，刷新不丢失"""
import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List

from backpack_quant_trading.api.deps import require_user, get_current_user
from backpack_quant_trading.database.models import DatabaseManager
from backpack_quant_trading.core.binance_monitor import (
    fetch_binance_symbols_usdt,
    BinanceMonitorService,
    get_monitor_instance,
    set_monitor_instance,
    BinanceMinuteAlertService,
    get_minute_alert_instance,
    set_minute_alert_instance,
)

router = APIRouter()


@router.get("/symbols")
def list_symbols():
    """币安 USDT 交易对"""
    try:
        symbols = fetch_binance_symbols_usdt()
        return {"symbols": symbols}
    except Exception as e:
        return {"symbols": [], "error": str(e)}


class MonitorStartRequest(BaseModel):
    symbols: List[str] = []
    timeframes: List[str] = ["1小时"]
    dingtalk_webhook: Optional[str] = None


class RemovePairRequest(BaseModel):
    symbol: str
    timeframe: str


class MinuteAlertStartRequest(BaseModel):
    symbols: List[str] = []
    interval: str = "1m"
    vol_pct_threshold: float = 5.0
    volume_mult_threshold: float = 20.0
    ob_notional_threshold: float = 200000.0
    ob_distance_pct: float = 0.003
    depth_levels: int = 50
    cooldown_sec: int = 300


@router.get("/status")
def get_status(user: dict = Depends(get_current_user)):
    """监视器状态（全局共享）"""
    if not user:
        return {"running": False, "pairs": []}
    inst = get_monitor_instance()
    if not inst or not getattr(inst, "_running", False):
        cfg = DatabaseManager().get_currency_monitor_config()
        if cfg:
            _, data = cfg
            try:
                d = json.loads(data) if isinstance(data, str) else data
                pairs = d.get("pairs", [])
                if pairs:
                    # 刷新后恢复：从 DB 配置自动启动监视器
                    if inst:
                        inst.stop()
                    service = BinanceMonitorService(pairs=pairs, user_id=None)
                    set_monitor_instance(service)
                    service.start()
                    alerted = [f"{s}|{t}" for (s, t) in service.get_alerted_pairs()]
                    return {"running": True, "pairs": pairs, "alerted": alerted}
                return {"running": False, "pairs": pairs, "restored": True}
            except Exception:
                pass
        return {"running": False, "pairs": []}
    pairs = list(getattr(inst, "_pairs", []))
    alerted = [f"{s}|{t}" for (s, t) in inst.get_alerted_pairs()]
    return {"running": True, "pairs": pairs, "alerted": alerted}


@router.post("/start")
def start_monitor(req: MonitorStartRequest, user: dict = Depends(require_user)):
    """启动币种监视（合并已有配对，支持多选，全局共享）"""
    if not req.symbols or not req.timeframes:
        raise HTTPException(status_code=400, detail="请选择币种和 K 线级别")
    inst = get_monitor_instance()
    base_pairs = []
    if inst and getattr(inst, "_pairs", []):
        base_pairs = list(inst._pairs)
    if not base_pairs:
        cfg = DatabaseManager().get_currency_monitor_config()
        if cfg:
            _, data = cfg
            try:
                d = json.loads(data) if isinstance(data, str) else data
                base_pairs = [(str(p[0]).upper(), str(p[1])) for p in d.get("pairs", [])]
            except Exception:
                pass
    new_pairs = [(str(s).upper(), str(t)) for s in req.symbols for t in req.timeframes]
    seen = set()
    merged = []
    for p in base_pairs + new_pairs:
        k = (p[0], p[1])
        if k not in seen:
            seen.add(k)
            merged.append(k)
    if not merged:
        raise HTTPException(status_code=400, detail="请选择币种和 K 线级别")
    if inst and getattr(inst, "_running", False):
        inst.stop()
    service = BinanceMonitorService(pairs=merged, user_id=None)
    set_monitor_instance(service)
    service.start()
    cfg = json.dumps({"pairs": merged})
    DatabaseManager().save_currency_monitor_config(cfg)
    return {"message": "已启动", "running": True}


@router.post("/stop")
def stop_monitor(user: dict = Depends(require_user)):
    """停止全部监视（关闭所有正在监控的币种）"""
    inst = get_monitor_instance()
    if inst and getattr(inst, "_running", False):
        inst.stop()
    set_monitor_instance(None)
    DatabaseManager().delete_currency_monitor_config()
    return {"message": "ok", "running": False}


@router.post("/remove-pair")
def remove_pair(req: RemovePairRequest, user: dict = Depends(require_user)):
    """移除单个监视对"""
    inst = get_monitor_instance()
    if not inst or not getattr(inst, "_running", False):
        raise HTTPException(status_code=400, detail="监视器未运行")
    if inst.remove_pair(req.symbol, req.timeframe):
        remaining = list(getattr(inst, "_pairs", []))
        cfg = json.dumps({"pairs": remaining})
        DatabaseManager().save_currency_monitor_config(cfg)
        if not remaining:
            inst.stop()
            set_monitor_instance(None)
            DatabaseManager().delete_currency_monitor_config()
    return {"message": "ok"}


# ===== 1分钟预警（波动/量能/订单簿墙）=====
@router.get("/minute-alert/status")
def minute_alert_status(user: dict = Depends(get_current_user)):
    if not user:
        return {"running": False, "symbols": []}
    inst = get_minute_alert_instance()
    if not inst or not getattr(inst, "_running", False):
        cfg = DatabaseManager().get_minute_alert_config()
        if cfg:
            _, data = cfg
            try:
                d = json.loads(data) if isinstance(data, str) else data
                symbols = d.get("symbols", [])
                if symbols:
                    if inst:
                        inst.stop()
                    service = BinanceMinuteAlertService(
                        symbols=symbols,
                        interval=str(d.get("interval", "1m")),
                        vol_pct_threshold=float(d.get("vol_pct_threshold", 5.0)),
                        volume_mult_threshold=float(d.get("volume_mult_threshold", 20.0)),
                        ob_notional_threshold=float(d.get("ob_notional_threshold", 200000.0)),
                        ob_distance_pct=float(d.get("ob_distance_pct", 0.003)),
                        depth_levels=int(d.get("depth_levels", 50)),
                        cooldown_sec=int(d.get("cooldown_sec", 300)),
                    )
                    set_minute_alert_instance(service)
                    service.start()
                    return {"running": True, "symbols": symbols, **d, "restored": True}
            except Exception:
                pass
        return {"running": False, "symbols": [], "interval": "1m"}
    return {
        "running": True,
        "symbols": getattr(inst, "symbols", []),
        "interval": getattr(inst, "interval", "1m"),
        "vol_pct_threshold": getattr(inst, "vol_pct_threshold", 5.0),
        "volume_mult_threshold": getattr(inst, "volume_mult_threshold", 20.0),
        "ob_notional_threshold": getattr(inst, "ob_notional_threshold", 200000.0),
        "ob_distance_pct": getattr(inst, "ob_distance_pct", 0.003),
        "depth_levels": getattr(inst, "depth_levels", 50),
        "cooldown_sec": getattr(inst, "cooldown_sec", 300),
    }


@router.post("/minute-alert/start")
def minute_alert_start(req: MinuteAlertStartRequest, user: dict = Depends(require_user)):
    if not req.symbols:
        raise HTTPException(status_code=400, detail="请选择监控币种")
    inst = get_minute_alert_instance()
    if inst and getattr(inst, "_running", False):
        inst.stop()
    service = BinanceMinuteAlertService(
        symbols=[str(s).upper() for s in req.symbols],
        interval=req.interval,
        vol_pct_threshold=req.vol_pct_threshold,
        volume_mult_threshold=req.volume_mult_threshold,
        ob_notional_threshold=req.ob_notional_threshold,
        ob_distance_pct=req.ob_distance_pct,
        depth_levels=req.depth_levels,
        cooldown_sec=req.cooldown_sec,
    )
    set_minute_alert_instance(service)
    service.start()
    cfg = json.dumps({
        "symbols": [str(s).upper() for s in req.symbols],
        "interval": req.interval,
        "vol_pct_threshold": req.vol_pct_threshold,
        "volume_mult_threshold": req.volume_mult_threshold,
        "ob_notional_threshold": req.ob_notional_threshold,
        "ob_distance_pct": req.ob_distance_pct,
        "depth_levels": req.depth_levels,
        "cooldown_sec": req.cooldown_sec,
    })
    DatabaseManager().save_minute_alert_config(cfg)
    return {"message": "已启动", "running": True}


@router.post("/minute-alert/stop")
def minute_alert_stop(user: dict = Depends(require_user)):
    inst = get_minute_alert_instance()
    if inst and getattr(inst, "_running", False):
        inst.stop()
    set_minute_alert_instance(None)
    DatabaseManager().delete_minute_alert_config()
    return {"message": "ok", "running": False}
