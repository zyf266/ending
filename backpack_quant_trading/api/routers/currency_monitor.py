"""币种监视 API - 全局共享，不按用户隔离，刷新不丢失"""
import json
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List

from backpack_quant_trading.api.deps import require_user, get_current_user
from backpack_quant_trading.database.models import DatabaseManager
from backpack_quant_trading.core.binance_monitor import (
    fetch_binance_symbols_usdt,
    fetch_binance_spot_symbols_usdt,
    BinanceMonitorService,
    get_monitor_instance,
    set_monitor_instance,
    set_currency_monitor_user_stopped,
    get_currency_monitor_user_stopped,
    BinanceMinuteAlertService,
    get_minute_alert_instance,
    set_minute_alert_instance,
    get_spot_minute_alert_instance,
    set_spot_minute_alert_instance,
    probe_spot_minute_alert,
    send_spot_minute_test_dingtalk,
)
from backpack_quant_trading.core.chain_activity_monitor import (
    ChainActivityMonitorService,
    get_chain_activity_instance,
    set_chain_activity_instance,
    list_supported_chains,
    probe_chain_activity_batch,
    send_chain_activity_test_dingtalk,
    get_chain_rpc_info,
)

router = APIRouter()


def _build_minute_alert_service(d: dict, *, market: str = "futures") -> BinanceMinuteAlertService:
    return BinanceMinuteAlertService(
        symbols=d.get("symbols", []),
        interval=str(d.get("interval", "1m")),
        vol_pct_threshold=float(d.get("vol_pct_threshold", 5.0)),
        volume_mult_threshold=float(d.get("volume_mult_threshold", 20.0)),
        ob_notional_threshold=float(d.get("ob_notional_threshold", 200000.0)),
        ob_distance_pct=float(d.get("ob_distance_pct", 0.003)),
        depth_levels=int(d.get("depth_levels", 50)),
        cooldown_sec=int(d.get("cooldown_sec", 300)),
        market=market,
    )


def _minute_alert_status_payload(
    inst,
    cfg_getter,
    setter,
    *,
    market: str = "futures",
):
    if not inst or not getattr(inst, "_running", False):
        cfg = cfg_getter()
        if cfg:
            _, data = cfg
            try:
                d = json.loads(data) if isinstance(data, str) else data
                symbols = d.get("symbols", [])
                if symbols:
                    if inst:
                        inst.stop()
                    service = _build_minute_alert_service(d, market=market)
                    setter(service)
                    service.start()
                    return {"running": True, "symbols": symbols, "market": market, **d, "restored": True}
            except Exception:
                pass
        return {"running": False, "symbols": [], "interval": "1m", "market": market}
    return {
        "running": True,
        "market": market,
        "symbols": getattr(inst, "symbols", []),
        "interval": getattr(inst, "interval", "1m"),
        "vol_pct_threshold": getattr(inst, "vol_pct_threshold", 5.0),
        "volume_mult_threshold": getattr(inst, "volume_mult_threshold", 20.0),
        "ob_notional_threshold": getattr(inst, "ob_notional_threshold", 200000.0),
        "ob_distance_pct": getattr(inst, "ob_distance_pct", 0.003),
        "depth_levels": getattr(inst, "depth_levels", 50),
        "cooldown_sec": getattr(inst, "cooldown_sec", 300),
    }


@router.get("/symbols")
def list_symbols():
    """币安 USDT 永续合约交易对"""
    try:
        symbols = fetch_binance_symbols_usdt()
        return {"symbols": symbols, "market": "futures"}
    except Exception as e:
        return {"symbols": [], "market": "futures", "error": str(e)}


@router.get("/spot-symbols")
def list_spot_symbols():
    """币安现货 USDT 交易对"""
    try:
        symbols = fetch_binance_spot_symbols_usdt()
        return {"symbols": symbols, "market": "spot"}
    except Exception as e:
        return {"symbols": [], "market": "spot", "error": str(e)}


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


class ChainActivityStartRequest(BaseModel):
    chains: List[str] = ["eth", "arb", "bsc"]
    activity_mult_threshold: float = 10.0
    check_interval_sec: int = 900
    cooldown_sec: int = 900


@router.get("/status")
def get_status(user: dict = Depends(require_user)):
    """监视器状态（全局共享）。用户主动停止后不再从 DB 恢复，避免缓存导致继续监控。"""
    if get_currency_monitor_user_stopped():
        return {"running": False, "pairs": [], "alerted": []}
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
    set_currency_monitor_user_stopped(False)
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
    """停止全部监视（关闭所有正在监控的币种，并清除 DB 与恢复标记，停止后不再从缓存恢复）"""
    set_currency_monitor_user_stopped(True)
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


# ===== 合约分钟预警（波动/量能/订单簿墙）=====
@router.get("/minute-alert/status")
def minute_alert_status(user: dict = Depends(require_user)):
    db = DatabaseManager()
    return _minute_alert_status_payload(
        get_minute_alert_instance(),
        db.get_minute_alert_config,
        set_minute_alert_instance,
        market="futures",
    )


@router.post("/minute-alert/start")
def minute_alert_start(req: MinuteAlertStartRequest, user: dict = Depends(require_user)):
    if not req.symbols:
        raise HTTPException(status_code=400, detail="请选择监控币种")
    inst = get_minute_alert_instance()
    if inst and getattr(inst, "_running", False):
        inst.stop()
    service = _build_minute_alert_service({
        "symbols": [str(s).upper() for s in req.symbols],
        "interval": req.interval,
        "vol_pct_threshold": req.vol_pct_threshold,
        "volume_mult_threshold": req.volume_mult_threshold,
        "ob_notional_threshold": req.ob_notional_threshold,
        "ob_distance_pct": req.ob_distance_pct,
        "depth_levels": req.depth_levels,
        "cooldown_sec": req.cooldown_sec,
    }, market="futures")
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


# ===== 现货分钟预警 =====
@router.get("/spot-minute-alert/status")
def spot_minute_alert_status(user: dict = Depends(require_user)):
    db = DatabaseManager()
    return _minute_alert_status_payload(
        get_spot_minute_alert_instance(),
        db.get_spot_minute_alert_config,
        set_spot_minute_alert_instance,
        market="spot",
    )


@router.post("/spot-minute-alert/start")
def spot_minute_alert_start(req: MinuteAlertStartRequest, user: dict = Depends(require_user)):
    if not req.symbols:
        raise HTTPException(status_code=400, detail="请选择监控币种")
    inst = get_spot_minute_alert_instance()
    if inst and getattr(inst, "_running", False):
        inst.stop()
    service = _build_minute_alert_service({
        "symbols": [str(s).upper() for s in req.symbols],
        "interval": req.interval,
        "vol_pct_threshold": req.vol_pct_threshold,
        "volume_mult_threshold": req.volume_mult_threshold,
        "ob_notional_threshold": req.ob_notional_threshold,
        "ob_distance_pct": req.ob_distance_pct,
        "depth_levels": req.depth_levels,
        "cooldown_sec": req.cooldown_sec,
    }, market="spot")
    set_spot_minute_alert_instance(service)
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
    DatabaseManager().save_spot_minute_alert_config(cfg)
    return {"message": "已启动", "running": True}


@router.post("/spot-minute-alert/stop")
def spot_minute_alert_stop(user: dict = Depends(require_user)):
    inst = get_spot_minute_alert_instance()
    if inst and getattr(inst, "_running", False):
        inst.stop()
    set_spot_minute_alert_instance(None)
    DatabaseManager().delete_spot_minute_alert_config()
    return {"message": "ok", "running": False}


@router.get("/spot-minute-alert/probe")
def spot_minute_alert_probe(
    symbol: str = Query("BTCUSDT"),
    interval: str = Query("1m"),
    user: dict = Depends(require_user),
):
    """现货分钟预警连通性自检（拉 K 线 + 深度，不启动后台任务）。"""
    return probe_spot_minute_alert(symbol, interval=interval)


@router.post("/spot-minute-alert/test-dingtalk")
def spot_minute_test_dingtalk(
    symbol: str = Query("BTCUSDT"),
    user: dict = Depends(require_user),
):
    ok, msg = send_spot_minute_test_dingtalk(symbol)
    if not ok:
        raise HTTPException(status_code=502, detail=msg)
    return {"ok": True, "message": msg}


# ===== 链上活跃度监控 =====
@router.get("/chain-activity/chains")
def chain_activity_chains(user: dict = Depends(require_user)):
    return {"chains": list_supported_chains()}


@router.get("/chain-activity/status")
def chain_activity_status(user: dict = Depends(require_user)):
    inst = get_chain_activity_instance()
    if not inst or not getattr(inst, "_running", False):
        cfg = DatabaseManager().get_chain_activity_config()
        if cfg:
            _, data = cfg
            try:
                d = json.loads(data) if isinstance(data, str) else data
                chains = d.get("chains", [])
                if chains:
                    if inst:
                        inst.stop()
                    service = ChainActivityMonitorService(
                        chains=chains,
                        activity_mult_threshold=float(d.get("activity_mult_threshold", 10.0)),
                        check_interval_sec=int(d.get("check_interval_sec", 900)),
                        cooldown_sec=int(d.get("cooldown_sec", 900)),
                    )
                    set_chain_activity_instance(service)
                    service.start()
                    return {"running": True, **d, **service.get_status_summary(), "restored": True}
            except Exception:
                pass
        return {"running": False, "chains": []}
    summary = inst.get_status_summary()
    return {"running": True, **summary}


@router.post("/chain-activity/start")
def chain_activity_start(req: ChainActivityStartRequest, user: dict = Depends(require_user)):
    if not req.chains:
        raise HTTPException(status_code=400, detail="请选择监控链")
    inst = get_chain_activity_instance()
    if inst and getattr(inst, "_running", False):
        inst.stop()
    service = ChainActivityMonitorService(
        chains=[str(c).lower() for c in req.chains],
        activity_mult_threshold=req.activity_mult_threshold,
        check_interval_sec=req.check_interval_sec,
        cooldown_sec=req.cooldown_sec,
    )
    set_chain_activity_instance(service)
    service.start()
    cfg = json.dumps({
        "chains": [str(c).lower() for c in req.chains],
        "activity_mult_threshold": req.activity_mult_threshold,
        "check_interval_sec": req.check_interval_sec,
        "cooldown_sec": req.cooldown_sec,
    })
    DatabaseManager().save_chain_activity_config(cfg)
    return {"message": "已启动", "running": True}


@router.post("/chain-activity/stop")
def chain_activity_stop(user: dict = Depends(require_user)):
    inst = get_chain_activity_instance()
    if inst and getattr(inst, "_running", False):
        inst.stop()
    set_chain_activity_instance(None)
    DatabaseManager().delete_chain_activity_config()
    return {"message": "ok", "running": False}


@router.get("/chain-activity/rpc-info")
def chain_activity_rpc_info(user: dict = Depends(require_user)):
    """当前各链 RPC 配置（内置默认 + 环境变量自定义）。"""
    return get_chain_rpc_info()


@router.get("/chain-activity/probe")
def chain_activity_probe(
    chains: str = Query("eth,arb,bsc", description="逗号分隔，如 eth,arb,bsc"),
    deep: bool = Query(False, description="true=完整15分钟统计(慢)，false=快速连通性(默认)"),
    user: dict = Depends(require_user),
):
    """链上 RPC 连通性自检（不依赖监控是否启动）。"""
    ids = [c.strip().lower() for c in chains.split(",") if c.strip()]
    return probe_chain_activity_batch(ids, deep=deep)


@router.post("/chain-activity/check-now")
def chain_activity_check_now(user: dict = Depends(require_user)):
    """若监控已启动则立即跑一轮；否则仅做探测。"""
    inst = get_chain_activity_instance()
    if inst and getattr(inst, "_running", False):
        results = inst.check_now()
        return {
            "ok": True,
            "mode": "running_service",
            "results": results,
            "summary": inst.get_status_summary(),
        }
    return {"ok": False, "mode": "not_running", **probe_chain_activity_batch()}


@router.post("/chain-activity/test-dingtalk")
def chain_activity_test_dingtalk(user: dict = Depends(require_user)):
    ok, msg = send_chain_activity_test_dingtalk()
    if not ok:
        raise HTTPException(status_code=502, detail=msg)
    return {"ok": True, "message": msg}
