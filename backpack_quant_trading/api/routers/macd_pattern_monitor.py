"""MACD 金叉形态监控 API"""
import json
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backpack_quant_trading.api.deps import require_user
from backpack_quant_trading.core.binance_monitor import fetch_binance_symbols_usdt
from backpack_quant_trading.core.macd_pattern_monitor import (
    MACD_TF_OPTIONS,
    PATTERN_OPTIONS,
    MacdPatternMonitorService,
    get_macd_pattern_instance,
    get_macd_pattern_user_stopped,
    set_macd_pattern_instance,
    set_macd_pattern_user_stopped,
)
from backpack_quant_trading.database.models import DatabaseManager

router = APIRouter()


@router.get("/symbols")
def list_symbols():
    try:
        return {"symbols": fetch_binance_symbols_usdt()}
    except Exception as e:
        return {"symbols": [], "error": str(e)}


@router.get("/options")
def list_options():
    return {
        "timeframes": [{"value": k, "label": v["label"]} for k, v in MACD_TF_OPTIONS.items()],
        "patterns": [{"value": k, "label": v} for k, v in PATTERN_OPTIONS.items()],
    }


class MacdPatternStartRequest(BaseModel):
    symbols: List[str] = []
    timeframes: List[str] = []
    patterns: List[str] = []


class RemoveTaskRequest(BaseModel):
    symbol: str
    timeframe: str
    pattern: str


def _parse_tasks_from_cfg(data: dict) -> List[tuple]:
    tasks = []
    for t in data.get("tasks", []):
        if len(t) >= 3:
            tasks.append((str(t[0]).upper(), str(t[1]), str(t[2])))
    return tasks


@router.get("/status")
def get_status(user: dict = Depends(require_user)):
    if get_macd_pattern_user_stopped():
        return {"running": False, "tasks": [], "alerted": []}
    inst = get_macd_pattern_instance()
    if not inst or not getattr(inst, "_running", False):
        cfg = DatabaseManager().get_macd_pattern_monitor_config()
        if cfg:
            _, data = cfg
            try:
                d = json.loads(data) if isinstance(data, str) else data
                tasks = _parse_tasks_from_cfg(d)
                if tasks:
                    if inst:
                        inst.stop()
                    service = MacdPatternMonitorService(tasks=tasks)
                    set_macd_pattern_instance(service)
                    service.start()
                    alerted = [f"{s}|{tf}|{p}" for (s, tf, p) in service.get_alerted_tasks()]
                    return {
                        "running": True,
                        "tasks": [[s, tf, p] for s, tf, p in tasks],
                        "alerted": alerted,
                    }
                return {"running": False, "tasks": [[s, tf, p] for s, tf, p in tasks], "restored": True}
            except Exception:
                pass
        return {"running": False, "tasks": []}
    tasks = [[s, tf, p] for s, tf, p in getattr(inst, "_tasks", [])]
    alerted = [f"{s}|{tf}|{p}" for (s, tf, p) in inst.get_alerted_tasks()]
    return {"running": True, "tasks": tasks, "alerted": alerted}


@router.post("/start")
def start_monitor(req: MacdPatternStartRequest, user: dict = Depends(require_user)):
    set_macd_pattern_user_stopped(False)
    if not req.symbols or not req.timeframes or not req.patterns:
        raise HTTPException(status_code=400, detail="请选择币种、K线级别和形态类型")
    for tf in req.timeframes:
        if tf not in MACD_TF_OPTIONS:
            raise HTTPException(status_code=400, detail=f"不支持的K线级别: {tf}")
    for p in req.patterns:
        if p not in PATTERN_OPTIONS:
            raise HTTPException(status_code=400, detail=f"不支持的形态: {p}")

    inst = get_macd_pattern_instance()
    base_tasks = []
    if inst and getattr(inst, "_tasks", []):
        base_tasks = list(inst._tasks)
    if not base_tasks:
        cfg = DatabaseManager().get_macd_pattern_monitor_config()
        if cfg:
            _, data = cfg
            try:
                d = json.loads(data) if isinstance(data, str) else data
                base_tasks = _parse_tasks_from_cfg(d)
            except Exception:
                pass

    new_tasks = [
        (str(s).upper(), str(tf), str(p))
        for s in req.symbols
        for tf in req.timeframes
        for p in req.patterns
    ]
    seen = set()
    merged = []
    for t in base_tasks + new_tasks:
        if t not in seen:
            seen.add(t)
            merged.append(t)
    if not merged:
        raise HTTPException(status_code=400, detail="请选择币种、K线级别和形态类型")

    if inst and getattr(inst, "_running", False):
        inst.stop()
    service = MacdPatternMonitorService(tasks=merged)
    set_macd_pattern_instance(service)
    service.start()
    DatabaseManager().save_macd_pattern_monitor_config(json.dumps({"tasks": merged}))
    return {"message": "已启动", "running": True, "task_count": len(merged)}


@router.post("/stop")
def stop_monitor(user: dict = Depends(require_user)):
    set_macd_pattern_user_stopped(True)
    inst = get_macd_pattern_instance()
    if inst and getattr(inst, "_running", False):
        inst.stop()
    set_macd_pattern_instance(None)
    DatabaseManager().delete_macd_pattern_monitor_config()
    return {"message": "ok", "running": False}


@router.post("/remove-task")
def remove_task(req: RemoveTaskRequest, user: dict = Depends(require_user)):
    inst = get_macd_pattern_instance()
    if not inst or not getattr(inst, "_running", False):
        raise HTTPException(status_code=400, detail="监控未运行")
    if inst.remove_task(req.symbol, req.timeframe, req.pattern):
        remaining = list(getattr(inst, "_tasks", []))
        DatabaseManager().save_macd_pattern_monitor_config(json.dumps({"tasks": remaining}))
        if not remaining:
            inst.stop()
            set_macd_pattern_instance(None)
            DatabaseManager().delete_macd_pattern_monitor_config()
    return {"message": "ok"}
