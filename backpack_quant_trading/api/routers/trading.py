"""实盘交易 API - 完整迁移"""
import os
import sys
import json
import socket
import subprocess
import logging
import requests
import psutil
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Tuple
import threading
import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
import re

from backpack_quant_trading.api.deps import require_user
from backpack_quant_trading.config.settings import config
from backpack_quant_trading.database.models import DatabaseManager
from backpack_quant_trading.main import STRATEGY_REGISTRY, STRATEGY_DISPLAY_NAMES
from backpack_quant_trading.strategy.hype_adaptive_short import HYPEAdaptiveShortStrategy
from backpack_quant_trading.strategy.eth_trend_short import ETHTrendShortStrategy
from backpack_quant_trading.strategy.adaptive_long_strategy import AdaptiveLongStrategy
from backpack_quant_trading.strategy.auto_close_strategy import AutoCloseStrategy
try:
    from backpack_quant_trading.strategy.adaptive_short_strategy import AdaptiveShortStrategy
except Exception as _e:
    AdaptiveShortStrategy = None  # type: ignore[assignment]
    logging.getLogger(__name__).error(f"[启动保护] 导入 AdaptiveShortStrategy 失败: {repr(_e)}")

logger = logging.getLogger(__name__)

router = APIRouter()
WEBHOOK_PORT = 8005
PROJECT_ROOT = Path(__file__).resolve().parents[3]

HYPE_STRATEGY_INSTANCES: Dict[str, HYPEAdaptiveShortStrategy] = {}
HYPE_STRATEGY_TASKS: Dict[str, asyncio.AbstractEventLoop] = {}
HYPE_STRATEGY_THREADS: Dict[str, threading.Thread] = {}

# ETH 趋势做空策略全局实例（复用同一字典模式）
ETH_TREND_INSTANCES: Dict[str, ETHTrendShortStrategy] = {}
ETH_TREND_TASKS: Dict[str, asyncio.AbstractEventLoop] = {}
ETH_TREND_THREADS: Dict[str, threading.Thread] = {}

# 自适应做多策略全局实例
ADAPTIVE_LONG_INSTANCES: Dict[str, AdaptiveLongStrategy] = {}
ADAPTIVE_LONG_TASKS: Dict[str, asyncio.AbstractEventLoop] = {}
ADAPTIVE_LONG_THREADS: Dict[str, threading.Thread] = {}

# 自适应做空策略全局实例
ADAPTIVE_SHORT_INSTANCES: Dict[str, AdaptiveShortStrategy] = {}
ADAPTIVE_SHORT_TASKS: Dict[str, asyncio.AbstractEventLoop] = {}
ADAPTIVE_SHORT_THREADS: Dict[str, threading.Thread] = {}

# 自动平仓策略全局实例
AUTO_CLOSE_INSTANCES: Dict[str, AutoCloseStrategy] = {}
AUTO_CLOSE_TASKS: Dict[str, asyncio.AbstractEventLoop] = {}
AUTO_CLOSE_THREADS: Dict[str, threading.Thread] = {}


def _adaptive_short_symbol_candidates(
    instances: Dict[str, AdaptiveShortStrategy],
    signal_symbol: str,
) -> List[Tuple[str, AdaptiveShortStrategy]]:
    """按币种筛选运行中的实例：优先 symbol_filter 精确匹配，否则退回无绑定币种实例。"""
    exact: List[Tuple[str, AdaptiveShortStrategy]] = []
    wild: List[Tuple[str, AdaptiveShortStrategy]] = []
    for iid, st in instances.items():
        if not st.is_enabled or st._stop:
            continue
        sf = getattr(st, "symbol_filter", None)
        if sf and sf.upper() == signal_symbol:
            exact.append((iid, st))
        elif not sf:
            wild.append((iid, st))
    return exact if exact else wild


def _pick_adaptive_short_instance_for_webhook(
    candidates: List[Tuple[str, AdaptiveShortStrategy]],
    signal_timeframe: str,
) -> Optional[str]:
    """与做多同逻辑：多实例同币种时按 K 线级别路由。"""
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0][0]

    stf = (signal_timeframe or "").strip().upper()
    if stf:
        for iid, st in candidates:
            inst_tf = getattr(st, "timeframe_filter", None)
            if inst_tf and str(inst_tf).strip().upper() == stf:
                return iid
        for iid, st in candidates:
            if not getattr(st, "timeframe_filter", None):
                return iid
        return None

    unrestricted = [(iid, st) for iid, st in candidates if not getattr(st, "timeframe_filter", None)]
    if len(unrestricted) == 1:
        return unrestricted[0][0]
    return None


def _adaptive_long_symbol_candidates(
    instances: Dict[str, AdaptiveLongStrategy],
    signal_symbol: str,
) -> List[Tuple[str, AdaptiveLongStrategy]]:
    """按币种筛选运行中的实例：优先 symbol_filter 精确匹配，否则退回无绑定币种实例。"""
    exact: List[Tuple[str, AdaptiveLongStrategy]] = []
    wild: List[Tuple[str, AdaptiveLongStrategy]] = []
    for iid, st in instances.items():
        if not st.is_enabled or st._stop:
            continue
        sf = getattr(st, "symbol_filter", None)
        if sf and sf.upper() == signal_symbol:
            exact.append((iid, st))
        elif not sf:
            wild.append((iid, st))
    return exact if exact else wild


def _pick_adaptive_long_instance_for_webhook(
    candidates: List[Tuple[str, AdaptiveLongStrategy]],
    signal_timeframe: str,
) -> Optional[str]:
    """
    多实例同币种时按 K 线级别路由：
    - 信号带 timeframe → 优先 timeframe_filter 相同的实例，其次「不限制」实例
    - 仅一个候选 → 直接命中
    - 多个候选且信号未带级别 → 无法唯一路由，返回 None
    """
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0][0]

    stf = (signal_timeframe or "").strip().upper()
    if stf:
        for iid, st in candidates:
            inst_tf = getattr(st, "timeframe_filter", None)
            if inst_tf and str(inst_tf).strip().upper() == stf:
                return iid
        for iid, st in candidates:
            if not getattr(st, "timeframe_filter", None):
                return iid
        return None

    unrestricted = [(iid, st) for iid, st in candidates if not getattr(st, "timeframe_filter", None)]
    if len(unrestricted) == 1:
        return unrestricted[0][0]
    return None


def _is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            return s.connect_ex((host, port)) == 0
    except Exception:
        return False


def _get_webhook_pid() -> int:
    try:
        for proc in psutil.process_iter(["pid", "cmdline"]):
            cmdline = proc.info.get("cmdline") or []
            if any("webhook_service" in str(arg) for arg in (cmdline if isinstance(cmdline, list) else [cmdline])):
                return proc.info.get("pid", 0)
    except Exception:
        pass
    return 0


def _resolve_symbol(user_input: str, platform: str) -> str:
    """将简写（如 ETH、BTC）解析为交易所完整交易对格式

    - Backpack: ETH -> ETH_USDC_PERP, BTC -> BTC_USDC_PERP
    - Deepcoin: ETH -> ETH-USDT-SWAP, BTC -> BTC-USDT-SWAP
    - Binance:  ETH -> ETHUSDT, BTC -> BTCUSDT（USD-M 合约）
    - 若已是完整格式（含 _PERP、-SWAP 等），则原样返回
    """
    s = (user_input or "").strip().upper()
    if not s:
        return user_input or ""

    # 已是完整格式：包含 _PERP、-SWAP、-PERP
    if "_PERP" in s or "-SWAP" in s or "-PERP" in s:
        # Binance 平台需要转换为 ETHUSDT 格式
        if platform == "binance":
            base = s.split("_")[0].split("-")[0]
            return f"{base}USDT"
        return s
    # 已是分隔格式：ETH_USDC、ETH-USDT、ETH/USDC 等
    if "_" in s:
        if platform == "binance":
            return f"{s.split('_')[0]}USDT"
        return s
    if "-" in s and len(s) > 6:
        if platform == "binance":
            return f"{s.split('-')[0]}USDT"
        return s
    if "/" in s:
        base = s.split("/")[0]
        if platform == "backpack":
            return f"{base}_USDC_PERP"
        if platform == "deepcoin":
            return f"{base}-USDT-SWAP"
        if platform == "binance":
            return f"{base}USDT"
        return s

    # 纯基础币种：ETH、BTC、SOL 等
    base = s
    if platform == "backpack":
        return f"{base}_USDC_PERP"
    if platform == "deepcoin":
        return f"{base}-USDT-SWAP"
    if platform == "binance":
        return f"{base}USDT"
    return s


# 自适应做多策略（统一单策略，coin 由前端传入）
ADAPTIVE_LONG_KEYS = {"adaptive_long"}
ADAPTIVE_SHORT_KEYS = {"adaptive_short"}


@router.get("/strategies")
def list_strategies():
    return {
        "strategies": [
            {"value": k, "label": STRATEGY_DISPLAY_NAMES.get(k, k)}
            for k in STRATEGY_REGISTRY.keys()
            if k != "hype_adaptive_short"
        ] + [
            {"value": "eth_trend_short", "label": "ETH趋势做空策略"},
            {"value": "adaptive_long",   "label": "🟢 自适应做多(Webhook版)"},
            {"value": "adaptive_short",  "label": "🔴 自适应做空(Webhook版)"},
            {"value": "auto_close",      "label": "🟡 自动平仓策略(Webhook版)"},
        ],
        "exchanges": [
            {"value": "backpack",    "label": "Backpack"},
            {"value": "deepcoin",    "label": "Deepcoin"},
            {"value": "ostium",      "label": "Ostium"},
            {"value": "hyperliquid", "label": "Hyperliquid"},
            {"value": "binance",     "label": "Binance"},
            {"value": "lighter",     "label": "Lighter"},
        ],
        "hype_strategies": [
            {"value": "hype_adaptive_short", "label": "自适应做空策略(Webhook版)"},
        ],
        # 独立的专用策略，不走通用 /launch 入口
        "special_strategies": [
            {"value": "eth_trend_short", "label": "ETH趋势做空策略"},
            {"value": "adaptive_long",   "label": "🟢 自适应做多(Webhook版)"},
            {"value": "adaptive_short",  "label": "🔴 自适应做空(Webhook版)"},
            {"value": "auto_close",      "label": "🟡 自动平仓策略(Webhook版)"},
        ],
    }


@router.get("/instances")
def list_instances(user: dict = Depends(require_user)):
    """当前用户的实盘实例（含 Webhook 恢复）"""
    try:
        db = DatabaseManager()
        my_ids = set(db.get_user_instance_ids(user["id"], "live"))
    except Exception as e:
        _log = __import__("logging").getLogger(__name__)
        _log.exception("list_instances: %s", e)
        my_ids = set()

    # 严格隔离：只展示属于当前用户的实例
    if not my_ids:
        return {"instances": []}

    try:
        # 尝试从 Webhook 获取运行中实例（仅返回属于当前用户的 instance_id）
        instances = []
        if _is_port_in_use(WEBHOOK_PORT):
            try:
                r = requests.get(f"http://127.0.0.1:{WEBHOOK_PORT}/instances", timeout=5)
                if r.status_code == 200:
                    data = r.json()
                    for inst in data.get("instances", []):
                        iid = inst.get("instance_id", inst)
                        if iid not in my_ids:
                            continue
                        balance_str = "同步中..."
                        try:
                            br = requests.get(f"http://127.0.0.1:{WEBHOOK_PORT}/balance/{iid}", timeout=3)
                            if br.status_code == 200:
                                bj = br.json()
                                bal = bj.get("balance")
                                if bal is not None:
                                    balance_str = f"{float(bal):,.2f}"
                        except Exception:
                            pass
                        instances.append({
                            "id": iid,
                            "pid": _get_webhook_pid(),
                            "platform": inst.get("exchange", "ostium"),
                            "strategy_name": inst.get("strategy", ""),
                            "symbol": inst.get("symbol", ""),
                            "start_time": "--:--",
                            "balance": balance_str,
                            "webhook_instance_id": iid,
                            "status": "running",
                        })
            except Exception:
                pass

        # 补充 DB 中有但 Webhook 未返回的（子进程实例 Backpack/Deepcoin）
        _pids_path = PROJECT_ROOT / "backpack_quant_trading" / "log" / "live_pids.json"
        _balances_path = PROJECT_ROOT / "backpack_quant_trading" / "log" / "live_balances.json"
        _pids = {}
        _balances = {}
        if _pids_path.exists():
            try:
                _pids = json.loads(_pids_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        if _balances_path.exists():
            try:
                _balances = json.loads(_balances_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        configs = {iid: cfg for iid, cfg in db.get_user_instance_configs(user["id"], "live")}
        # 补充 DB 中有但 Webhook 未返回的（子进程实例 / 未注册 webhook 等）
        for iid in list(my_ids):
            if any(inst["id"] == iid for inst in instances):
                continue
            cfg = configs.get(iid)
            try:
                obj = json.loads(cfg) if cfg else {}
            except Exception:
                obj = {}
            pid = _pids.get(iid, 0)
            
            # HYPE 内存实例：直接从内存读取余额和启动时间
            if iid in HYPE_STRATEGY_INSTANCES:
                hype = HYPE_STRATEGY_INSTANCES[iid]
                balance_str = f"{hype.balance_cache:,.2f}" if hype.balance_cache is not None else "--"
                start_time_str = hype.start_time.strftime("%m-%d %H:%M")
                instances.append({
                    "id": iid,
                    "pid": pid,
                    "platform": "hyperliquid",
                    "strategy_name": "HYPE做空策略(Webhook版)",
                    "symbol": hype.symbol,
                    "start_time": start_time_str,
                    "balance": balance_str,
                    "status": "running",
                })
                continue

            # ETH趋势做空实例：直接从内存读取
            if iid in ETH_TREND_INSTANCES:
                eth = ETH_TREND_INSTANCES[iid]
                balance_str = f"{eth.balance_cache:,.2f}" if eth.balance_cache is not None else "--"
                start_time_str = eth.start_time.strftime("%m-%d %H:%M") if hasattr(eth, "start_time") else "--:--"
                instances.append({
                    "id": iid,
                    "pid": pid,
                    "platform": "hyperliquid",
                    "strategy_name": "ETH趋势做空策略",
                    "symbol": getattr(eth, "symbol", "ETH"),
                    "start_time": start_time_str,
                    "balance": balance_str,
                    "status": "running",
                })
                continue

            # 自适应做多实例：直接从内存读取
            if iid in ADAPTIVE_LONG_INSTANCES:
                al = ADAPTIVE_LONG_INSTANCES[iid]
                bal_cache = getattr(al, "balance_cache", None)
                balance_str = f"{bal_cache:,.2f}" if isinstance(bal_cache, (int, float)) else "--"
                st = getattr(al, "start_time", None)
                start_time_str = st.strftime("%m-%d %H:%M") if hasattr(st, "strftime") else "--:--"
                sf = getattr(al, "symbol_filter", None) or getattr(al, "symbol", None) or "HYPE"
                sf = str(sf).upper().strip() if sf else "HYPE"
                _sname = f"{sf}做多策略(Webhook版)"
                try:
                    _cfg_obj = json.loads(configs.get(iid) or "{}")
                except Exception:
                    _cfg_obj = {}
                if not isinstance(_cfg_obj, dict):
                    _cfg_obj = {}
                _cfg_obj["min_ai_score_for_trade"] = getattr(
                    al, "min_ai_score_for_trade", _min_ai_score_from_config(_cfg_obj),
                )
                instances.append({
                    "id": iid,
                    "pid": pid,
                    "platform": getattr(al, "exchange", "hyperliquid"),
                    "strategy_name": _sname,
                    "symbol": sf,
                    "start_time": start_time_str,
                    "balance": balance_str,
                    "status": "running" if getattr(al, "is_enabled", True) else "stopped",
                    "config": _cfg_obj,
                })
                continue

            # 自适应做空实例：直接从内存读取
            if iid in ADAPTIVE_SHORT_INSTANCES:
                s = ADAPTIVE_SHORT_INSTANCES[iid]
                bal_cache = getattr(s, "balance_cache", None)
                balance_str = f"{bal_cache:,.2f}" if isinstance(bal_cache, (int, float)) else "--"
                st = getattr(s, "start_time", None)
                start_time_str = st.strftime("%m-%d %H:%M") if hasattr(st, "strftime") else "--:--"
                sf = getattr(s, "symbol_filter", None) or getattr(s, "symbol", None) or "HYPE"
                sf = str(sf).upper().strip() if sf else "HYPE"
                _sname = f"{sf}做空策略(Webhook版)"
                instances.append({
                    "id": iid,
                    "pid": pid,
                    "platform": getattr(s, "exchange", "hyperliquid"),
                    "strategy_name": _sname,
                    "symbol": sf,
                    "start_time": start_time_str,
                    "balance": balance_str,
                    "status": "running" if getattr(s, "is_enabled", True) else "stopped",
                })
                continue

            # 自动平仓实例：直接从内存读取
            if iid in AUTO_CLOSE_INSTANCES:
                ac = AUTO_CLOSE_INSTANCES[iid]
                bal_cache = getattr(ac, "balance_cache", None)
                balance_str = f"{bal_cache:,.2f}" if isinstance(bal_cache, (int, float)) else "--"
                st = getattr(ac, "start_time", None)
                start_time_str = st.strftime("%m-%d %H:%M") if hasattr(st, "strftime") else "--:--"
                sf = getattr(ac, "symbol_filter", None) or "ETH"
                sf = str(sf).upper().strip() if sf else "ETH"
                _sname = f"{sf}自动平仓(Webhook版)"
                instances.append({
                    "id": iid,
                    "pid": pid,
                    "platform": getattr(ac, "exchange", "hyperliquid"),
                    "strategy_name": _sname,
                    "symbol": sf,
                    "start_time": start_time_str,
                    "balance": balance_str,
                    "status": "running" if getattr(ac, "is_enabled", True) else "stopped",
                })
                continue

            balance_str = "--"
            if iid in _balances:
                bal = _balances[iid].get("balance")
                if bal is not None:
                    balance_str = f"{float(bal):,.2f}"
            raw_strategy = obj.get("strategy", "")
            strategy_name = STRATEGY_DISPLAY_NAMES.get(raw_strategy, raw_strategy)
            # DB 实例：若进程/线程不在跑，则标记 stopped（保留卡片）
            db_status = (obj.get("status") or "").strip().lower()
            is_proc_running = bool(pid) and psutil.pid_exists(int(pid)) if pid else False
            status = "running" if is_proc_running else ("stopped" if db_status in ("", "stopped") else db_status)
            instances.append({
                "id": iid,
                "pid": pid,
                "platform": obj.get("platform", "backpack"),
                "strategy_name": strategy_name,
                "symbol": obj.get("symbol", ""),
                "start_time": "--:--",
                "balance": balance_str,
                "status": status,
                "config": obj,
            })

        # 兜底：如果 DB 里漏记了实例，也要把当前进程内存里正在跑的实例展示出来
        # （尤其是 adaptive-short / adaptive-long 这类线程内存策略）
        known_ids = {inst["id"] for inst in instances if isinstance(inst, dict) and inst.get("id")}
        for iid, s in list(ADAPTIVE_SHORT_INSTANCES.items()):
            if iid in known_ids:
                continue
            sf = getattr(s, "symbol_filter", None) or getattr(s, "symbol", None) or "HYPE"
            sf = str(sf).upper().strip() if sf else "HYPE"
            instances.append({
                "id": iid,
                "pid": _pids.get(iid, 0),
                "platform": getattr(s, "exchange", "hyperliquid"),
                "strategy_name": f"{sf}做空策略(Webhook版)",
                "symbol": sf,
                "start_time": "--:--",
                "balance": "--",
                "status": "running",
            })
        for iid, al in list(ADAPTIVE_LONG_INSTANCES.items()):
            if iid in known_ids:
                continue
            sf = getattr(al, "symbol_filter", None) or getattr(al, "symbol", None) or "HYPE"
            sf = str(sf).upper().strip() if sf else "HYPE"
            instances.append({
                "id": iid,
                "pid": _pids.get(iid, 0),
                "platform": getattr(al, "exchange", "hyperliquid"),
                "strategy_name": f"{sf}做多策略(Webhook版)",
                "symbol": sf,
                "start_time": "--:--",
                "balance": "--",
                "status": "running",
            })

        for iid, ac in list(AUTO_CLOSE_INSTANCES.items()):
            if iid in known_ids:
                continue
            sf = getattr(ac, "symbol_filter", None) or "ETH"
            sf = str(sf).upper().strip() if sf else "ETH"
            instances.append({
                "id": iid,
                "pid": _pids.get(iid, 0),
                "platform": getattr(ac, "exchange", "hyperliquid"),
                "strategy_name": f"{sf}自动平仓(Webhook版)",
                "symbol": sf,
                "start_time": "--:--",
                "balance": "--",
                "status": "running",
            })

        # 为前端“修改参数/重启”提供配置快照（若 DB 有记录则附带）
        try:
            configs = {iid: cfg for iid, cfg in db.get_user_instance_configs(user["id"], "live")}
            for inst in instances:
                if not isinstance(inst, dict):
                    continue
                iid = inst.get("id")
                if not iid or inst.get("config"):
                    continue
                cfg = configs.get(iid)
                if not cfg:
                    continue
                try:
                    obj = json.loads(cfg) if cfg else None
                except Exception:
                    obj = None
                # 永远不回显敏感明文
                if isinstance(obj, dict):
                    obj.pop("private_key", None)
                    obj.pop("private_key_enc", None)
                    obj.pop("api_secret", None)
                    obj.pop("api_secret_enc", None)
                inst["config"] = obj
        except Exception:
            pass

        # 权限标记：当前接口已只返回本人实例，统一可操作
        for inst in instances:
            if isinstance(inst, dict):
                inst["can_operate"] = True

        return {"instances": instances}
    except Exception as e:
        _log = __import__("logging").getLogger(__name__)
        _log.exception("list_instances: %s", e)
        return {"instances": []}


class LaunchRequest(BaseModel):
    platform: str = "backpack"
    strategy: str = "mean_reversion"
    symbol: str = "ETH/USDC"
    size: float = 20
    leverage: int = 50
    take_profit: float = 2.0
    stop_loss: float = 1.5
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    passphrase: Optional[str] = None
    private_key: Optional[str] = None
    forbidden_ranges: Optional[List[List[int]]] = None  # [[3,8],[13,15]]


class HypeStartRequest(BaseModel):
    symbol: str = "ETH"
    private_key: Optional[str] = None
    stop_loss_pct: float = 0.03
    take_profit_pct: float = 0.06
    break_even_pct: float = 0.03
    margin_amount: float = 20.0
    leverage: int = 50



class HypeToggleRequest(BaseModel):
    instance_id: Optional[str] = None
    enabled: bool


def _run_hype_strategy_in_thread(instance_id: str, strategy: HYPEAdaptiveShortStrategy):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    HYPE_STRATEGY_TASKS[instance_id] = loop
    try:
        loop.run_until_complete(strategy.run())
    finally:
        try:
            loop.run_until_complete(strategy.close())
        except Exception:
            pass
        loop.close()
        HYPE_STRATEGY_TASKS.pop(instance_id, None)


@router.post("/hype/start")
def start_hype_strategy(req: HypeStartRequest, user: dict = Depends(require_user)):
    if not req.private_key and not config.hyperliquid.PRIVATE_KEY:
        raise HTTPException(status_code=400, detail="请提供 Hyperliquid 私钥")
    symbol = (req.symbol or "ETH").upper()
    instance_id = f"hype_{datetime.now().strftime('%H%M%S_%f')}"
    
    # 使用用户提供的私钥或配置中的私钥
    private_key = req.private_key or config.hyperliquid.PRIVATE_KEY
    
    try:
        strategy = HYPEAdaptiveShortStrategy(
            symbol=symbol,
            private_key=private_key,
            instance_id=instance_id,
            stop_loss_pct=req.stop_loss_pct,
            take_profit_pct=req.take_profit_pct,
            break_even_pct=req.break_even_pct,
            margin_amount=req.margin_amount,
            leverage=req.leverage,
        )
    except ValueError as e:
        # 私钥格式错误
        raise HTTPException(status_code=400, detail=f"私钥格式错误: {str(e)}")
    except Exception as e:
        # 其他初始化错误
        raise HTTPException(status_code=500, detail=f"策略初始化失败: {str(e)}")
    
    thread = threading.Thread(target=_run_hype_strategy_in_thread, args=(instance_id, strategy), daemon=True)
    HYPE_STRATEGY_INSTANCES[instance_id] = strategy
    HYPE_STRATEGY_THREADS[instance_id] = thread
    thread.start()

    db = DatabaseManager()
    cfg = json.dumps({"platform": "hyperliquid", "strategy": "hype_adaptive_short", "symbol": symbol}, ensure_ascii=False)
    db.save_user_instance(user["id"], "live", instance_id, cfg)
    return {"ok": True, "instance_id": instance_id, "message": "自适应做空策略已启动"}


@router.post("/hype/stop")
def stop_hype_strategy(user: dict = Depends(require_user)):
    db = DatabaseManager()
    my_ids = set(db.get_user_instance_ids(user["id"], "live"))
    target_ids = [iid for iid in list(HYPE_STRATEGY_INSTANCES.keys()) if iid in my_ids]
    if not target_ids:
        return {"ok": True, "message": "没有运行中的 HYPE 策略"}

    for instance_id in target_ids:
        strategy = HYPE_STRATEGY_INSTANCES.pop(instance_id, None)
        loop = HYPE_STRATEGY_TASKS.get(instance_id)
        HYPE_STRATEGY_THREADS.pop(instance_id, None)
        if strategy and loop:
            strategy._stop = True
            asyncio.run_coroutine_threadsafe(strategy.close(), loop)
        db.delete_user_instance(user["id"], "live", instance_id)
    return {"ok": True, "message": "HYPE做空策略已停止"}


@router.get("/hype/status")
def get_hype_status():
    """获取HYPE策略状态（免登录，供调试和TradingView调用）"""
    try:
        # 直接返回内存中的实例状态
        items = []
        logger.info(f"[DEBUG] HYPE_STRATEGY_INSTANCES 数量: {len(HYPE_STRATEGY_INSTANCES)}")
        logger.info(f"[DEBUG] HYPE_STRATEGY_INSTANCES keys: {list(HYPE_STRATEGY_INSTANCES.keys())}")
        
        for instance_id, strategy in HYPE_STRATEGY_INSTANCES.items():
            try:
                item = strategy.get_status()
                item["running"] = True
                items.append(item)
                logger.info(f"[DEBUG] 实例 {instance_id}: is_enabled={strategy.is_enabled}, position={strategy.position}")
            except Exception as e:
                logger.error(f"获取策略状态失败 {instance_id}: {e}")
                items.append({
                    "instance_id": instance_id,
                    "error": str(e),
                    "running": False
                })
        
        return {"running": len(items) > 0, "instances": items, "debug_count": len(HYPE_STRATEGY_INSTANCES)}
    except Exception as e:
        logger.error(f"获取HYPE状态失败: {e}")
        return {"running": False, "instances": [], "error": str(e)}


@router.post("/hype/toggle")
def toggle_hype_strategy(req: HypeToggleRequest, user: dict = Depends(require_user)):
    db = DatabaseManager()
    my_ids = set(db.get_user_instance_ids(user["id"], "live"))
    target_id = req.instance_id
    if not target_id:
        for iid in HYPE_STRATEGY_INSTANCES.keys():
            if iid in my_ids:
                target_id = iid
                break
    if not target_id or target_id not in HYPE_STRATEGY_INSTANCES or target_id not in my_ids:
        raise HTTPException(status_code=404, detail="未找到对应的 HYPE 策略实例")
    strategy = HYPE_STRATEGY_INSTANCES[target_id]
    strategy.set_enabled(req.enabled)
    return {"ok": True, "instance_id": target_id, "enabled": req.enabled, "message": f"策略已{'开启' if req.enabled else '关闭'}"}


class WebhookSignal(BaseModel):
    """
    TradingView Webhook 信号，兼容新旧两种格式：

    新格式（推荐）:
      { "ID": "趋势信号提醒", "策略": "2h级别趋势增强",
        "交易品种": "ETHUSD", "方向": "sell", "成交价格": "2091.5" }

    旧格式（兼容）:
      { "交易品种": "ETH", "操作": "sell", "价格": 2091.5, "先前仓位大小": "0" }
    """
    # 新格式字段
    ID: Optional[str] = None
    策略: Optional[str] = None
    方向: Optional[str] = None        # 新格式：'sell' / 'buy'
    成交价格: Optional[str] = None    # 新格式：字符串价格

    # 旧格式字段（兼容保留）
    交易品种: str = "ETH"
    价格: Optional[float] = None
    操作: Optional[str] = None        # 旧格式：'sell' / 'buy'
    仓位方向: Optional[str] = None
    先前仓位大小: Optional[str] = None  # 旧格式专用，新格式无此字段

    @property
    def resolved_action(self) -> str:
        """统一取操作方向：优先新格式 方向，回退旧格式 操作"""
        return (self.方向 or self.操作 or "").lower().strip()

    @property
    def resolved_price(self) -> Optional[float]:
        """统一取价格：优先新格式 成交价格，回退旧格式 价格"""
        if self.成交价格 is not None:
            try:
                return float(self.成交价格)
            except (ValueError, TypeError):
                return None
        return self.价格

    @property
    def resolved_symbol(self) -> str:
        """清理交易品种：'ETHUSD' / 'ETH/USD' → 'ETH'"""
        raw = self.交易品种 or "ETH"
        # 去掉后缀 USD/USDT/PERP 等
        for suffix in ["USDT", "USD", "PERP", "/USDT", "/USD"]:
            if raw.upper().endswith(suffix.upper()):
                raw = raw[: -len(suffix)]
                break
        return raw.upper().strip() or "ETH"


@router.post("/hype/webhook")
async def hype_webhook(request: Request):
    """接收 TradingView Webhook 信号并转发给策略（无需登录，供 TradingView 调用）"""
    # 直接读取原始 JSON，避免 Pydantic 对中文字段名解析失败
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="无效的 JSON 请求体")

    # 找到第一个运行中的 HYPE 策略实例
    target_id = None
    for iid, strategy in HYPE_STRATEGY_INSTANCES.items():
        if strategy.is_enabled:
            target_id = iid
            break

    if not target_id:
        raise HTTPException(status_code=404, detail="没有运行中的 HYPE 策略实例")

    strategy = HYPE_STRATEGY_INSTANCES[target_id]

    # 兼容新旧两种格式提取字段（直接从 dict 读取，避免中文字段名编码问题）
    action = (data.get("方向") or data.get("操作") or data.get("signal") or "").lower().strip()
    price_raw = data.get("成交价格") or data.get("价格") or data.get("price")
    try:
        price = float(price_raw) if price_raw is not None else None
    except (ValueError, TypeError):
        price = None

    # 清理交易品种后缀
    symbol_raw = str(data.get("交易品种") or data.get("symbol") or "ETH")
    for suffix in ["USDT", "USD", "PERP", "/USDT", "/USD"]:
        if symbol_raw.upper().endswith(suffix.upper()):
            symbol_raw = symbol_raw[: -len(suffix)]
            break
    symbol = symbol_raw.upper().strip() or "ETH"

    # 推断先前仓位大小
    prev_size = str(data.get("先前仓位大小") or "")
    if not prev_size:
        prev_size = "1" if strategy.position == "SHORT" else "0"

    logger.info(
        f"📡 Webhook 收到信号: action={action} symbol={symbol} price={price} prev_size={prev_size}"
    )

    # 转换为策略内部 TVSignal
    from backpack_quant_trading.strategy.hype_adaptive_short import TVSignal
    signal = TVSignal(
        交易品种=symbol,
        价格=price,
        操作=action,
        仓位方向=data.get("仓位方向"),
        先前仓位大小=prev_size,
    )

    # 通过策略所在事件循环异步执行
    import asyncio
    try:
        loop = HYPE_STRATEGY_TASKS.get(target_id)
        if loop:
            future = asyncio.run_coroutine_threadsafe(
                strategy.execute_signal(signal, data),
                loop
            )
            future.result(timeout=5)
            return {
                "ok": True,
                "instance_id": target_id,
                "position": strategy.position,
                "message": f"信号已处理: {action}"
            }
        else:
            raise HTTPException(status_code=500, detail="策略事件循环未找到")
    except Exception as e:
        logger.error(f"处理 Webhook 信号失败: {e}")
        raise HTTPException(status_code=500, detail=f"信号处理失败: {str(e)}")


@router.post("/launch")
def launch_strategy(req: LaunchRequest, user: dict = Depends(require_user)):
    """启动实盘策略"""
    user_id = user["id"]
    db = DatabaseManager()

    # 解析交易对：ETH/BTC 等简写 -> 交易所完整格式
    symbol = _resolve_symbol(req.symbol or "", req.platform)

    # 【HYPE自适应做空策略】使用独立的线程模式，不走 Webhook
    if req.strategy == "hype_adaptive_short":
        raise HTTPException(
            status_code=400, 
            detail="HYPE做空策略请使用专用端点 /trading/hype/start"
        )
    # 【自适应做多策略】使用独立线程模式（Hyperliquid XYZ DEX）
    if req.strategy == "adaptive_long":
        raise HTTPException(
            status_code=400,
            detail="自适应做多策略请使用专用启动面板（支持 Hyperliquid XYZ DEX）"
        )
    # 【ETH趋势做空策略】使用独立线程模式
    if req.strategy == "eth_trend_short":
        raise HTTPException(
            status_code=400,
            detail="ETH趋势做空策略请使用专用启动面板"
        )

    if req.platform in ["ostium", "hyperliquid"]:
        # Webhook 模式
        if not req.private_key:
            raise HTTPException(status_code=400, detail="Ostium/Hyperliquid 需要提供私钥")

        if not _is_port_in_use(WEBHOOK_PORT):
            # 启动 Webhook 服务
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONPATH"] = str(PROJECT_ROOT) + (os.pathsep + env.get("PYTHONPATH", ""))
            log_dir = PROJECT_ROOT / "backpack_quant_trading" / "log"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / "webhook_console.log"
            cmd = [sys.executable, "-u", "-m", "backpack_quant_trading.webhook_service"]
            try:
                with open(log_path, "a", encoding="utf-8") as f:
                    proc = subprocess.Popen(cmd, env=env, stdout=f, stderr=subprocess.STDOUT, cwd=str(PROJECT_ROOT))
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"启动 Webhook 服务失败: {e}")

        prefix = "hl" if req.platform == "hyperliquid" else "ostium"
        instance_id = f"{prefix}_{datetime.now().strftime('%H%M%S_%f')}"

        forbidden_hours_str = ""
        if req.platform == "ostium" and req.forbidden_ranges:
            hours_set = set()
            for start, end in req.forbidden_ranges:
                for h in range(start, end):
                    hours_set.add(h)
            forbidden_hours_str = ",".join(str(h) for h in sorted(hours_set))

        register_data = {
            "instance_id": instance_id,
            "exchange": req.platform,
            "private_key": str(req.private_key or ""),
            "strategy_name": STRATEGY_DISPLAY_NAMES.get(req.strategy, req.strategy),
            "symbol": symbol,
            "leverage": int(req.leverage) if req.leverage else 50,
            "margin_amount": str(req.size),
            "stop_loss_ratio": (req.stop_loss or 1.5) / 100,
            "take_profit_ratio": (req.take_profit or 2.0) / 100,
            "forbidden_hours": forbidden_hours_str,
        }

        import threading
        def _async_register():
            for attempt in range(5):
                try:
                    r = requests.post(f"http://127.0.0.1:{WEBHOOK_PORT}/register_instance", json=register_data, timeout=10)
                    if r.status_code == 200:
                        return
                except Exception:
                    pass
                import time
                time.sleep(1)

        t = threading.Thread(target=_async_register, daemon=True)
        t.start()

        cfg = json.dumps({"platform": req.platform, "strategy": STRATEGY_DISPLAY_NAMES.get(req.strategy, req.strategy), "symbol": symbol})
        db.save_user_instance(user_id, "live", instance_id, cfg)
        return {"ok": True, "instance_id": instance_id, "message": "实例已添加，后台注册中"}

    # Backpack / Deepcoin / Binance：子进程模式
    instance_id = f"{req.platform}_{req.strategy}_{datetime.now().strftime('%H%M%S')}"
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = str(PROJECT_ROOT) + (os.pathsep + env.get("PYTHONPATH", ""))
    env["LIVE_INSTANCE_ID"] = instance_id  # 供子进程写入余额到 live_balances.json
    if req.platform == "backpack":
        env["BACKPACK_API_KEY"] = str(req.api_key or "")
        env["BACKPACK_API_SECRET"] = str(req.api_secret or "")
    elif req.platform == "deepcoin":
        env["DEEPCOIN_API_KEY"] = str(req.api_key or "")
        env["DEEPCOIN_API_SECRET"] = str(req.api_secret or "")
        env["DEEPCOIN_PASSPHRASE"] = str(req.passphrase or "")
    elif req.platform == "binance":
        env["BINANCE_API_KEY"] = str(req.api_key or "")
        env["BINANCE_SECRET_KEY"] = str(req.api_secret or "")

    cmd = [
        sys.executable, "-u", "-m", "backpack_quant_trading.main",
        "--mode", "live",
        "--strategy", req.strategy,
        "--exchange", req.platform,
        "--symbols", symbol,
        "--position-size", str(req.size),
        "--leverage", str(req.leverage),
        # dual_freq_trend：止盈止损按 Pine 语义（保证金收益%），直接传原值；其他策略仍用“百分比/100”
        "--take-profit", str((req.take_profit or 2) if req.strategy == "dual_freq_trend" else ((req.take_profit or 2) / 100)),
        "--stop-loss", str((req.stop_loss or 1.5) if req.strategy == "dual_freq_trend" else ((req.stop_loss or 1.5) / 100)),
    ]

    log_dir = PROJECT_ROOT / "backpack_quant_trading" / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "live_console.log"
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            proc = subprocess.Popen(cmd, env=env, stdout=f, stderr=subprocess.STDOUT, cwd=str(PROJECT_ROOT))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"启动失败: {e}")

    cfg = json.dumps({"platform": req.platform, "strategy": req.strategy, "symbol": symbol})
    db.save_user_instance(user_id, "live", instance_id, cfg)
    # 保存 PID 便于停止时杀死进程
    _pids_path = PROJECT_ROOT / "backpack_quant_trading" / "log" / "live_pids.json"
    _pids_path.parent.mkdir(parents=True, exist_ok=True)
    _pids = {}
    if _pids_path.exists():
        try:
            _pids = json.loads(_pids_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    _pids[instance_id] = proc.pid
    _pids_path.write_text(json.dumps(_pids), encoding="utf-8")
    return {"ok": True, "instance_id": instance_id, "pid": proc.pid}


@router.delete("/instances/{instance_id}")
def stop_instance(instance_id: str, user: dict = Depends(require_user)):
    """删除实盘实例（停止 + 从列表移除）"""
    # 兼容旧前端：之前用 DELETE 作为“停止”。现在 DELETE 语义为“删除”，
    # 新增 POST /instances/{id}/stop 仅停止不删除卡片。
    db = DatabaseManager()
    my_ids = db.get_user_instance_ids(user["id"], "live")
    if instance_id not in my_ids:
        raise HTTPException(status_code=403, detail="非本人账户启动，已隔离（不可操作）")

    configs = {iid: cfg for iid, cfg in db.get_user_instance_configs(user["id"], "live")}
    cfg_str = configs.get(instance_id, "{}")
    try:
        obj = json.loads(cfg_str) if cfg_str else {}
    except Exception:
        obj = {}
    platform = obj.get("platform", "backpack")

    # 线程/内存策略：**优先按 instance_id 前缀停止**，不要用 platform 分支（adaptive-long/short 可能是 lighter/binance）
    if instance_id.startswith("hype_"):
        strategy = HYPE_STRATEGY_INSTANCES.pop(instance_id, None)
        loop = HYPE_STRATEGY_TASKS.get(instance_id)
        HYPE_STRATEGY_THREADS.pop(instance_id, None)
        if strategy and loop:
            strategy._stop = True
            asyncio.run_coroutine_threadsafe(strategy.close(), loop)
        HYPE_STRATEGY_TASKS.pop(instance_id, None)
    elif instance_id.startswith("eth_trend_"):
        strategy = ETH_TREND_INSTANCES.pop(instance_id, None)
        loop = ETH_TREND_TASKS.get(instance_id)
        ETH_TREND_THREADS.pop(instance_id, None)
        if strategy:
            strategy.stop()
        if loop and loop.is_running() and strategy:
            asyncio.run_coroutine_threadsafe(strategy.client.close(), loop)
        ETH_TREND_TASKS.pop(instance_id, None)
    elif instance_id.startswith("al_"):
        strategy = ADAPTIVE_LONG_INSTANCES.pop(instance_id, None)
        loop = ADAPTIVE_LONG_TASKS.get(instance_id)
        ADAPTIVE_LONG_THREADS.pop(instance_id, None)
        if strategy:
            strategy.stop()
        if loop and loop.is_running() and strategy:
            asyncio.run_coroutine_threadsafe(strategy.client.close(), loop)
        ADAPTIVE_LONG_TASKS.pop(instance_id, None)
    elif instance_id.startswith("as_"):
        strategy = ADAPTIVE_SHORT_INSTANCES.pop(instance_id, None)
        loop = ADAPTIVE_SHORT_TASKS.get(instance_id)
        ADAPTIVE_SHORT_THREADS.pop(instance_id, None)
        if strategy:
            strategy.stop()
        if loop and loop.is_running() and strategy:
            asyncio.run_coroutine_threadsafe(strategy.client.close(), loop)
        ADAPTIVE_SHORT_TASKS.pop(instance_id, None)
    elif instance_id.startswith("ac_"):
        strategy = AUTO_CLOSE_INSTANCES.pop(instance_id, None)
        loop = AUTO_CLOSE_TASKS.get(instance_id)
        AUTO_CLOSE_THREADS.pop(instance_id, None)
        if strategy:
            strategy.stop()
        if loop and loop.is_running() and strategy:
            asyncio.run_coroutine_threadsafe(strategy.client.close(), loop)
        AUTO_CLOSE_TASKS.pop(instance_id, None)
    elif platform in ["ostium", "hyperliquid", "lighter", "binance"]:
        # 其它 webhook 管理的实例
        try:
            r = requests.post(f"http://127.0.0.1:{WEBHOOK_PORT}/unregister_instance/{instance_id}", timeout=5)
            if r.status_code != 200:
                raise HTTPException(status_code=500, detail="注销 Webhook 实例失败")
        except requests.exceptions.ConnectionError:
            pass  # 服务已关闭
    else:
        # 子进程实例：从 live_pids.json 读取 PID 并杀死
        _pids_path = PROJECT_ROOT / "backpack_quant_trading" / "log" / "live_pids.json"
        if _pids_path.exists():
            try:
                _pids = json.loads(_pids_path.read_text(encoding="utf-8"))
                pid = _pids.pop(instance_id, None)
                _pids_path.write_text(json.dumps(_pids), encoding="utf-8")
                if pid and psutil.pid_exists(pid):
                    proc = psutil.Process(pid)
                    for c in proc.children(recursive=True):
                        c.kill()
                    proc.kill()
            except Exception:
                pass
        # 清理 live_balances.json 中对应实例的余额记录
        _balances_path = PROJECT_ROOT / "backpack_quant_trading" / "log" / "live_balances.json"
        if _balances_path.exists():
            try:
                _balances = json.loads(_balances_path.read_text(encoding="utf-8"))
                if instance_id in _balances:
                    del _balances[instance_id]
                    _balances_path.write_text(json.dumps(_balances, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass

    try:
        db.delete_user_instance(user["id"], "live", instance_id)
    except Exception:
        pass
    return {"message": "ok"}


# 不在 DB 中存储私钥/API Secret：
# - 编辑参数时留空=不修改密钥
# - 若需要重启并应用参数，优先复用当前运行实例内存中的密钥


def _stop_live_runtime(instance_id: str, platform: str):
    """仅停止运行态，不触碰 DB（用于 stop / update / delete）"""
    # 线程/内存策略：**优先按 instance_id 前缀停止**，不要用 platform 分支（adaptive-long/short 可能是 lighter/binance）
    if instance_id.startswith("hype_"):
        strategy = HYPE_STRATEGY_INSTANCES.pop(instance_id, None)
        loop = HYPE_STRATEGY_TASKS.get(instance_id)
        HYPE_STRATEGY_THREADS.pop(instance_id, None)
        if strategy and loop:
            strategy._stop = True
            asyncio.run_coroutine_threadsafe(strategy.close(), loop)
        HYPE_STRATEGY_TASKS.pop(instance_id, None)
        return
    if instance_id.startswith("eth_trend_"):
        strategy = ETH_TREND_INSTANCES.pop(instance_id, None)
        loop = ETH_TREND_TASKS.get(instance_id)
        ETH_TREND_THREADS.pop(instance_id, None)
        if strategy:
            strategy.stop()
        if loop and loop.is_running() and strategy:
            asyncio.run_coroutine_threadsafe(strategy.client.close(), loop)
        ETH_TREND_TASKS.pop(instance_id, None)
        return
    if instance_id.startswith("al_"):
        strategy = ADAPTIVE_LONG_INSTANCES.pop(instance_id, None)
        loop = ADAPTIVE_LONG_TASKS.get(instance_id)
        ADAPTIVE_LONG_THREADS.pop(instance_id, None)
        if strategy:
            strategy.stop()
        if loop and loop.is_running() and strategy:
            asyncio.run_coroutine_threadsafe(strategy.client.close(), loop)
        ADAPTIVE_LONG_TASKS.pop(instance_id, None)
        return
    if instance_id.startswith("as_"):
        strategy = ADAPTIVE_SHORT_INSTANCES.pop(instance_id, None)
        loop = ADAPTIVE_SHORT_TASKS.get(instance_id)
        ADAPTIVE_SHORT_THREADS.pop(instance_id, None)
        if strategy:
            strategy.stop()
        if loop and loop.is_running() and strategy:
            asyncio.run_coroutine_threadsafe(strategy.client.close(), loop)
        ADAPTIVE_SHORT_TASKS.pop(instance_id, None)
        return
    if instance_id.startswith("ac_"):
        strategy = AUTO_CLOSE_INSTANCES.pop(instance_id, None)
        loop = AUTO_CLOSE_TASKS.get(instance_id)
        AUTO_CLOSE_THREADS.pop(instance_id, None)
        if strategy:
            strategy.stop()
        if loop and loop.is_running() and strategy:
            asyncio.run_coroutine_threadsafe(strategy.client.close(), loop)
        AUTO_CLOSE_TASKS.pop(instance_id, None)
        return

    if platform in ["ostium", "hyperliquid", "lighter", "binance"]:
        # 其它 webhook 管理的实例
        try:
            r = requests.post(f"http://127.0.0.1:{WEBHOOK_PORT}/unregister_instance/{instance_id}", timeout=5)
            if r.status_code != 200:
                raise HTTPException(status_code=500, detail="注销 Webhook 实例失败")
        except requests.exceptions.ConnectionError:
            pass  # 服务已关闭
        return

    # 子进程实例：从 live_pids.json 读取 PID 并杀死
    _pids_path = PROJECT_ROOT / "backpack_quant_trading" / "log" / "live_pids.json"
    if _pids_path.exists():
        try:
            _pids = json.loads(_pids_path.read_text(encoding="utf-8"))
            pid = _pids.pop(instance_id, None)
            _pids_path.write_text(json.dumps(_pids), encoding="utf-8")
            if pid and psutil.pid_exists(pid):
                proc = psutil.Process(pid)
                for c in proc.children(recursive=True):
                    c.kill()
                proc.kill()
        except Exception:
            pass
    # 清理 live_balances.json 中对应实例的余额记录
    _balances_path = PROJECT_ROOT / "backpack_quant_trading" / "log" / "live_balances.json"
    if _balances_path.exists():
        try:
            _balances = json.loads(_balances_path.read_text(encoding="utf-8"))
            if instance_id in _balances:
                del _balances[instance_id]
                _balances_path.write_text(json.dumps(_balances, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass


@router.post("/instances/{instance_id}/stop", summary="停止实例（保留卡片）")
def stop_instance_keep_card(instance_id: str, user: dict = Depends(require_user)):
    db = DatabaseManager()
    my_ids = set(db.get_user_instance_ids(user["id"], "live"))
    if instance_id not in my_ids:
        raise HTTPException(status_code=403, detail="非本人账户启动，已隔离（不可操作）")

    configs = {iid: cfg for iid, cfg in db.get_user_instance_configs(user["id"], "live")}
    cfg_str = configs.get(instance_id, "{}")
    try:
        obj = json.loads(cfg_str) if cfg_str else {}
    except Exception:
        obj = {}
    # 自适应做多/做空：停止=软暂停（不销毁线程/不重建实例）
    if instance_id in ADAPTIVE_LONG_INSTANCES:
        st = ADAPTIVE_LONG_INSTANCES[instance_id]
        st.is_enabled = False
        obj["status"] = "stopped"
        try:
            if instance_id in my_ids:
                db.save_user_instance(user["id"], "live", instance_id, json.dumps(obj, ensure_ascii=False))
        except Exception:
            pass
        return {"ok": True, "message": "已停止（暂停接收信号）"}

    if instance_id in ADAPTIVE_SHORT_INSTANCES:
        st = ADAPTIVE_SHORT_INSTANCES[instance_id]
        st.is_enabled = False
        obj["status"] = "stopped"
        try:
            if instance_id in my_ids:
                db.save_user_instance(user["id"], "live", instance_id, json.dumps(obj, ensure_ascii=False))
        except Exception:
            pass
        return {"ok": True, "message": "已停止（暂停接收信号）"}

    if instance_id in AUTO_CLOSE_INSTANCES:
        st = AUTO_CLOSE_INSTANCES[instance_id]
        st.is_enabled = False
        obj["status"] = "stopped"
        try:
            if instance_id in my_ids:
                db.save_user_instance(user["id"], "live", instance_id, json.dumps(obj, ensure_ascii=False))
        except Exception:
            pass
        return {"ok": True, "message": "已停止（暂停接收信号）"}

    platform = obj.get("platform", "backpack")
    _stop_live_runtime(instance_id, platform)

    # 标记状态（仅用于列表展示）
    obj["status"] = "stopped"
    try:
        if instance_id in my_ids:
            db.save_user_instance(user["id"], "live", instance_id, json.dumps(obj, ensure_ascii=False))
    except Exception:
        pass
    return {"ok": True, "message": "已停止"}


def _coerce_float(v, default: float) -> float:
    try:
        x = float(v)
        return x if x == x else default  # NaN
    except Exception:
        return default


def _coerce_int(v, default: int) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _min_ai_score_from_config(obj: dict) -> int:
    """从实例配置读取 AI 开单门槛（缺省 0）。"""
    try:
        return max(0, int(obj.get("min_ai_score_for_trade") or 0))
    except (TypeError, ValueError):
        return 0


def _use_ai_sr_tpsl_from_config(obj: dict) -> bool:
    v = obj.get("use_ai_sr_tpsl")
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    s = str(v or "").strip().lower()
    return s in ("1", "true", "yes", "y", "是", "启用", "on")


def _allow_repeat_open_from_config(obj: dict) -> bool:
    """从实例配置读取是否允许同币种重复开单（不同 K 线级别加仓）。"""
    v = obj.get("allow_repeat_open")
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    s = str(v or "").strip().lower()
    return s in ("1", "true", "yes", "y", "是", "允许", "on")


@router.post("/instances/{instance_id}/start", summary="启动实例（使用保存的参数）")
def start_instance_from_saved_config(instance_id: str, user: dict = Depends(require_user)):
    db = DatabaseManager()
    configs = {iid: cfg for iid, cfg in db.get_user_instance_configs(user["id"], "live")}
    if instance_id not in configs:
        raise HTTPException(status_code=404, detail="未找到该实例的配置（请先启动一次或重新创建）")
    try:
        obj = json.loads(configs.get(instance_id) or "{}")
    except Exception:
        obj = {}

    # 自适应做多/做空：启动=恢复接收信号（不重建，但从 DB 刷新门槛等参数）
    if instance_id in ADAPTIVE_LONG_INSTANCES:
        st = ADAPTIVE_LONG_INSTANCES[instance_id]
        st.is_enabled = True
        st.min_ai_score_for_trade = _min_ai_score_from_config(obj)
        st.allow_repeat_open = _allow_repeat_open_from_config(obj)
        st.use_ai_sr_tpsl = _use_ai_sr_tpsl_from_config(obj)
        logger.info(
            "▶️ 恢复做多实例 %s | AI开单门槛=%s | 重复开单=%s | AI位阶止盈止损=%s（来自已保存配置）",
            instance_id, st.min_ai_score_for_trade, "是" if st.allow_repeat_open else "否",
            "是" if st.use_ai_sr_tpsl else "否",
        )
        obj["status"] = "running"
        obj["min_ai_score_for_trade"] = st.min_ai_score_for_trade
        obj["allow_repeat_open"] = st.allow_repeat_open
        obj["use_ai_sr_tpsl"] = st.use_ai_sr_tpsl
        db.save_user_instance(user["id"], "live", instance_id, json.dumps(obj, ensure_ascii=False))
        return {
            "ok": True,
            "instance_id": instance_id,
            "min_ai_score_for_trade": st.min_ai_score_for_trade,
            "message": f"已启动（恢复接收信号，AI开单门槛={st.min_ai_score_for_trade}）",
        }
    if instance_id in ADAPTIVE_SHORT_INSTANCES:
        st = ADAPTIVE_SHORT_INSTANCES[instance_id]
        st.is_enabled = True
        obj["status"] = "running"
        db.save_user_instance(user["id"], "live", instance_id, json.dumps(obj, ensure_ascii=False))
        return {"ok": True, "instance_id": instance_id, "message": "已启动（恢复接收信号）"}

    if instance_id in AUTO_CLOSE_INSTANCES:
        st = AUTO_CLOSE_INSTANCES[instance_id]
        st.is_enabled = True
        obj["status"] = "running"
        db.save_user_instance(user["id"], "live", instance_id, json.dumps(obj, ensure_ascii=False))
        return {"ok": True, "instance_id": instance_id, "message": "已启动（恢复接收信号）"}

    if instance_id in AUTO_CLOSE_INSTANCES:
        st = AUTO_CLOSE_INSTANCES[instance_id]
        st.is_enabled = True
        obj["status"] = "running"
        db.save_user_instance(user["id"], "live", instance_id, json.dumps(obj, ensure_ascii=False))
        return {"ok": True, "instance_id": instance_id, "message": "已启动（恢复接收信号）"}

    # 其它策略：已在跑则拒绝，避免重复线程/重复 webhook
    if instance_id in ETH_TREND_INSTANCES or instance_id in HYPE_STRATEGY_INSTANCES:
        raise HTTPException(status_code=400, detail="实例正在运行中，请先停止")

    strat = (obj.get("strategy") or "").strip()
    if strat not in ("adaptive_long", "adaptive_short"):
        raise HTTPException(status_code=400, detail="该实例暂不支持一键重启（仅支持 adaptive_long/adaptive_short）")

    exchange = (obj.get("exchange") or obj.get("platform") or "hyperliquid").lower()
    coin = (obj.get("coin") or obj.get("symbol") or "HYPE").upper().strip()
    tf = (obj.get("timeframe_filter") or "").strip() or None
    margin_amount = _coerce_float(obj.get("margin_amount", 20.0), 20.0)
    leverage = _coerce_int(obj.get("leverage", 50), 50)
    stop_loss_pct = _coerce_float(obj.get("stop_loss_pct", 0.03), 0.03)
    take_profit_pct = _coerce_float(obj.get("take_profit_pct", 0.06), 0.06)
    break_even_pct = _coerce_float(obj.get("break_even_pct", 0.03), 0.03)
    lock_profit_pct = _coerce_float(obj.get("lock_profit_pct", 0.0), 0.0)
    lock_profit_sl_pct = _coerce_float(obj.get("lock_profit_sl_pct", 0.0), 0.0)
    min_ai_score_for_trade = _min_ai_score_from_config(obj)
    allow_repeat_open = _allow_repeat_open_from_config(obj)
    use_ai_sr_tpsl = _use_ai_sr_tpsl_from_config(obj)

    # 密钥不存 DB：这里只能使用环境变量（Hyperliquid）或要求用户重新填写（其它平台）
    private_key = None
    api_key = obj.get("api_key") or None
    api_secret = None
    account_index = _coerce_int(obj.get("account_index", 0), 0)
    api_key_index = _coerce_int(obj.get("api_key_index", 2), 2)

    if exchange in ("hyperliquid", ""):
        private_key = config.hyperliquid.PRIVATE_KEY or None
    if exchange == "binance":
        # 不从 DB 取 secret；用户需重新填写或仅在“运行中修改参数”场景复用内存
        api_secret = None
    if exchange == "lighter":
        private_key = None

    if exchange in ("lighter", "binance") and not private_key and not api_secret and strat in ("adaptive_long", "adaptive_short"):
        raise HTTPException(status_code=400, detail="该实例未保存密钥：请在修改弹窗中重新填写密钥后保存并应用")

    if strat == "adaptive_long":
        strategy = AdaptiveLongStrategy(
            exchange=exchange,
            private_key=private_key,
            api_key=api_key,
            api_secret=api_secret,
            instance_id=instance_id,
            margin_amount=margin_amount,
            leverage=leverage,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            break_even_pct=break_even_pct,
            lock_profit_pct=lock_profit_pct,
            lock_profit_sl_pct=lock_profit_sl_pct,
            symbol_filter=coin,
            timeframe_filter=tf,
            account_index=account_index,
            api_key_index=api_key_index,
            min_ai_score_for_trade=min_ai_score_for_trade,
            allow_repeat_open=allow_repeat_open,
            use_ai_sr_tpsl=use_ai_sr_tpsl,
        )
        logger.info(
            "▶️ 重建做多实例 %s | AI开单门槛=%s | 重复开单=%s | AI位阶止盈止损=%s（来自已保存配置）",
            instance_id, min_ai_score_for_trade, "是" if allow_repeat_open else "否",
            "是" if use_ai_sr_tpsl else "否",
        )
        thread = threading.Thread(target=_run_adaptive_long_in_thread, args=(instance_id, strategy), daemon=True)
        ADAPTIVE_LONG_INSTANCES[instance_id] = strategy
        ADAPTIVE_LONG_THREADS[instance_id] = thread
        thread.start()
    else:
        strategy = AdaptiveShortStrategy(
            exchange=exchange,
            private_key=private_key,
            api_key=api_key,
            api_secret=api_secret,
            instance_id=instance_id,
            margin_amount=margin_amount,
            leverage=leverage,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            break_even_pct=break_even_pct,
            lock_profit_pct=lock_profit_pct,
            lock_profit_sl_pct=lock_profit_sl_pct,
            symbol_filter=coin,
            timeframe_filter=tf,
            account_index=account_index,
            api_key_index=api_key_index,
        )
        thread = threading.Thread(target=_run_adaptive_short_in_thread, args=(instance_id, strategy), daemon=True)
        ADAPTIVE_SHORT_INSTANCES[instance_id] = strategy
        ADAPTIVE_SHORT_THREADS[instance_id] = thread
        thread.start()

    obj["status"] = "running"
    if strat == "adaptive_long":
        obj["min_ai_score_for_trade"] = min_ai_score_for_trade
        obj["allow_repeat_open"] = allow_repeat_open
        obj["use_ai_sr_tpsl"] = use_ai_sr_tpsl
    db.save_user_instance(user["id"], "live", instance_id, json.dumps(obj, ensure_ascii=False))
    return {
        "ok": True,
        "instance_id": instance_id,
        "min_ai_score_for_trade": min_ai_score_for_trade if strat == "adaptive_long" else None,
        "message": (
            f"已启动（AI开单门槛={min_ai_score_for_trade}）"
            if strat == "adaptive_long"
            else "已启动"
        ),
    }


class InstanceUpdateRequest(BaseModel):
    # 只覆盖 adaptive_long / adaptive_short 所需字段
    wallet_memo: Optional[str] = None
    exchange: Optional[str] = None
    coin: Optional[str] = None
    timeframe_filter: Optional[str] = None
    margin_amount: Optional[float] = None
    leverage: Optional[int] = None
    stop_loss_pct: Optional[float] = None
    take_profit_pct: Optional[float] = None
    break_even_pct: Optional[float] = None
    lock_profit_pct: Optional[float] = None
    lock_profit_sl_pct: Optional[float] = None
    private_key: Optional[str] = None
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    account_index: Optional[int] = None
    api_key_index: Optional[int] = None
    min_ai_score_for_trade: Optional[int] = None
    allow_repeat_open: Optional[bool] = None
    use_ai_sr_tpsl: Optional[bool] = None


@router.put("/instances/{instance_id}", summary="修改实例参数（必要时自动重启）")
def update_instance_config(instance_id: str, req: InstanceUpdateRequest, user: dict = Depends(require_user)):
    db = DatabaseManager()
    configs = {iid: cfg for iid, cfg in db.get_user_instance_configs(user["id"], "live")}
    if instance_id not in configs:
        raise HTTPException(status_code=404, detail="未找到该实例")

    try:
        obj = json.loads(configs.get(instance_id) or "{}")
    except Exception:
        obj = {}

    payload = req.model_dump(exclude_unset=True)

    # 敏感字段：留空=不修改；不写入 DB
    new_private_key = (payload.pop("private_key", None) or "").strip() or None
    new_api_secret = (payload.pop("api_secret", None) or "").strip() or None

    # 合并非敏感字段
    for k, v in payload.items():
        obj[k] = v

    # 规范化
    if obj.get("coin"):
        obj["coin"] = str(obj["coin"]).upper().strip()
    if obj.get("exchange"):
        obj["exchange"] = str(obj["exchange"]).lower().strip()

    db.save_user_instance(user["id"], "live", instance_id, json.dumps(obj, ensure_ascii=False))

    # 若运行中：自动重启以应用参数
    is_running = (
        instance_id in ADAPTIVE_LONG_INSTANCES
        or instance_id in ADAPTIVE_SHORT_INSTANCES
        or instance_id in ETH_TREND_INSTANCES
        or instance_id in HYPE_STRATEGY_INSTANCES
    )
    if is_running:
        # 运行中修改：直接热更新参数（不停止、不重启、更符合“只改参数不动私钥”的预期）
        if instance_id in ADAPTIVE_LONG_INSTANCES:
            s = ADAPTIVE_LONG_INSTANCES[instance_id]
            s.margin_amount = _coerce_float(obj.get("margin_amount", getattr(s, "margin_amount", 20.0)), getattr(s, "margin_amount", 20.0))
            s.leverage = _coerce_int(obj.get("leverage", getattr(s, "leverage", 50)), getattr(s, "leverage", 50))
            s.stop_loss_pct = _coerce_float(obj.get("stop_loss_pct", getattr(s, "stop_loss_pct", 0.03)), getattr(s, "stop_loss_pct", 0.03))
            s.take_profit_pct = _coerce_float(obj.get("take_profit_pct", getattr(s, "take_profit_pct", 0.06)), getattr(s, "take_profit_pct", 0.06))
            s.break_even_pct = _coerce_float(obj.get("break_even_pct", getattr(s, "break_even_pct", 0.03)), getattr(s, "break_even_pct", 0.03))
            s.lock_profit_pct = _coerce_float(obj.get("lock_profit_pct", getattr(s, "lock_profit_pct", 0.0)), getattr(s, "lock_profit_pct", 0.0))
            s.lock_profit_sl_pct = _coerce_float(obj.get("lock_profit_sl_pct", getattr(s, "lock_profit_sl_pct", 0.0)), getattr(s, "lock_profit_sl_pct", 0.0))
            coin = (obj.get("coin") or obj.get("symbol") or getattr(s, "symbol_filter", None) or "").upper().strip()
            s.symbol_filter = coin or getattr(s, "symbol_filter", None)
            tf = (obj.get("timeframe_filter") or "").strip().upper()
            s.timeframe_filter = tf or None
            if "min_ai_score_for_trade" in payload:
                s.min_ai_score_for_trade = _min_ai_score_from_config(obj)
            elif "min_ai_score_for_trade" in obj:
                s.min_ai_score_for_trade = _min_ai_score_from_config(obj)
            obj["min_ai_score_for_trade"] = getattr(s, "min_ai_score_for_trade", 0)
            if "allow_repeat_open" in payload:
                s.allow_repeat_open = bool(payload.get("allow_repeat_open"))
                obj["allow_repeat_open"] = s.allow_repeat_open
            elif "allow_repeat_open" in obj:
                s.allow_repeat_open = _allow_repeat_open_from_config(obj)
                obj["allow_repeat_open"] = s.allow_repeat_open
            if "use_ai_sr_tpsl" in payload:
                s.use_ai_sr_tpsl = bool(payload.get("use_ai_sr_tpsl"))
                obj["use_ai_sr_tpsl"] = s.use_ai_sr_tpsl
            elif "use_ai_sr_tpsl" in obj:
                s.use_ai_sr_tpsl = _use_ai_sr_tpsl_from_config(obj)
                obj["use_ai_sr_tpsl"] = s.use_ai_sr_tpsl
            logger.info(
                "💾 热更新做多实例 %s | AI开单门槛=%s | 重复开单=%s | AI位阶止盈止损=%s",
                instance_id, s.min_ai_score_for_trade, "是" if s.allow_repeat_open else "否",
                "是" if s.use_ai_sr_tpsl else "否",
            )
            obj["status"] = "running"
            db.save_user_instance(user["id"], "live", instance_id, json.dumps(obj, ensure_ascii=False))
            return {
                "ok": True,
                "message": f"已保存并生效（AI开单门槛={s.min_ai_score_for_trade}）",
                "min_ai_score_for_trade": s.min_ai_score_for_trade,
            }

        if instance_id in ADAPTIVE_SHORT_INSTANCES:
            s = ADAPTIVE_SHORT_INSTANCES[instance_id]
            s.margin_amount = _coerce_float(obj.get("margin_amount", getattr(s, "margin_amount", 20.0)), getattr(s, "margin_amount", 20.0))
            s.leverage = _coerce_int(obj.get("leverage", getattr(s, "leverage", 50)), getattr(s, "leverage", 50))
            s.stop_loss_pct = _coerce_float(obj.get("stop_loss_pct", getattr(s, "stop_loss_pct", 0.03)), getattr(s, "stop_loss_pct", 0.03))
            s.take_profit_pct = _coerce_float(obj.get("take_profit_pct", getattr(s, "take_profit_pct", 0.06)), getattr(s, "take_profit_pct", 0.06))
            s.break_even_pct = _coerce_float(obj.get("break_even_pct", getattr(s, "break_even_pct", 0.03)), getattr(s, "break_even_pct", 0.03))
            s.lock_profit_pct = _coerce_float(obj.get("lock_profit_pct", getattr(s, "lock_profit_pct", 0.0)), getattr(s, "lock_profit_pct", 0.0))
            s.lock_profit_sl_pct = _coerce_float(obj.get("lock_profit_sl_pct", getattr(s, "lock_profit_sl_pct", 0.0)), getattr(s, "lock_profit_sl_pct", 0.0))
            coin = (obj.get("coin") or obj.get("symbol") or getattr(s, "symbol_filter", None) or "").upper().strip()
            s.symbol_filter = coin or getattr(s, "symbol_filter", None)
            tf = (obj.get("timeframe_filter") or "").strip().upper()
            s.timeframe_filter = tf or None
            obj["status"] = "running"
            db.save_user_instance(user["id"], "live", instance_id, json.dumps(obj, ensure_ascii=False))
            return {"ok": True, "message": "已保存并生效"}

        # 其它策略仍按旧逻辑：仅保存，不热更新
        return {"ok": True, "message": "已保存（该策略需手动停止后再启动以生效）"}

    return {"ok": True, "message": "已保存"}


@router.get("/logs")
def get_logs(user: dict = Depends(require_user)):
    """获取实盘交易相关实时日志（最近 150 行）

    只展示：启动/停止/买卖/下单/撤单/平仓/止盈止损/Webhook 等交易动作。
    """
    try:
        # 兼容不同启动目录：日志目录可能在 <repo>/log 或 <repo>/backpack_quant_trading/log
        cand_dirs = [
            PROJECT_ROOT / "log",
            PROJECT_ROOT / "backpack_quant_trading" / "log",
        ]
        log_dir = next((d for d in cand_dirs if d.exists()), cand_dirs[0])
        lines: list[str] = []

        # 只读取“交易相关”的独立日志文件（优先）。避免把 app_*.log 的杂讯塞进来。
        fixed = [
            "live_console.log",
            "webhook_server.log",
            "hype_strategy.log",
            "eth_trend_short.log",
            "adaptive_long.log",
            "adaptive_short.log",
            "auto_close.log",
        ]

        # 始终追加最新 app_*.log（但严格过滤，只保留策略/交易动作相关行）
        app_logs: list[str] = []
        try:
            app_logs = sorted(
                [p.name for p in log_dir.glob("app_*.log")],
                key=lambda n: (log_dir / n).stat().st_mtime,
                reverse=True,
            )[:1]
        except Exception:
            app_logs = []

        import re
        # 强过滤：只保留“策略生命周期 + 交易动作”相关行（不按交易所关键词保留，避免监控/网络噪音混入）
        keep_pat = re.compile(
            r"(启动|已启动|启动成功|停止|已停止|重启|退出|开始|结束|运行|"
            r"策略|strategy|instance_id|instance=|adaptive_long|adaptive_short|eth_trend|hype|auto_close|"
            r"下单|开仓|平仓|撤单|改单|挂单|成交|拒绝|失败|成功|"
            r"买入|卖出|BUY|SELL|reduce_only|"
            r"止损|止盈|tpsl|tp\\b|sl\\b|break[-_ ]?even|lock[-_ ]?profit|"
            r"Webhook|webhook|signal|TradingView|入场|离场|开多|开空|平多|平空|"
            r"AI|评分|门槛|开单门槛|开单筛选|未达门槛|拒绝交易|评分开单|跳过 AI|平仓|开多未成交|保证金不足|同步多仓|做多策略|重复开单|AI位阶|止盈止损|"
            r"✅|❌|🚀|🧹|✍️|🤖|⛔|📋)",
            re.IGNORECASE,
        )
        # 丢弃明显噪音：轮询/状态/instances debug 等
        drop_pat = re.compile(
            r"(HYPE_STRATEGY_INSTANCES|/api/(currency-monitor|trading/instances|trading/hype/status|trading/logs)|"
            r"Starting new HTTP connection|Starting new HTTPS connection|urllib3\\.connectionpool|"
            r"binance_monitor|yahoo|query\\d\\.finance\\.yahoo|轮询完成|currency-monitor|"
            r"GET\\s+http://127\\.0\\.0\\.1:8005/instances|/instances\\s+HTTP/1\\.1)",
            re.IGNORECASE,
        )

        # 默认 INFO；交易相关的 ERROR 也展示（如开多失败、平仓异常）
        info_pat = re.compile(r"(\|\s*INFO\s*\|)|(^INFO:\s)", re.IGNORECASE)
        err_pat = re.compile(r"\|\s*ERROR\s*\|", re.IGNORECASE)

        def _append_filtered(fname: str, content: str):
            for line in content.splitlines():
                s = (line or "").strip()
                if not s:
                    continue
                is_info = bool(info_pat.search(s))
                is_trade_err = bool(err_pat.search(s) and keep_pat.search(s))
                if not is_info and not is_trade_err:
                    continue
                if drop_pat.search(s):
                    continue
                if keep_pat.search(s):
                    lines.append(f"[{fname}] {s}")

        # 先读 fixed（交易专用日志）
        for fname in fixed:
            fp = log_dir / fname
            if not fp.exists():
                continue
            try:
                with open(fp, "rb") as f:
                    f.seek(0, 2)
                    size = f.tell()
                    if size <= 0:
                        continue
                    buf = min(350 * 180, size)
                    f.seek(-buf, 2)
                    chunk = f.read().decode("utf-8", errors="replace")
                _append_filtered(fname, chunk)
            except Exception:
                pass

        # 始终读取最新 app_*.log（严格过滤后追加），确保“启动成功/下单”等关键日志不会漏
        for fname in app_logs:
            fp = log_dir / fname
            if not fp.exists():
                continue
            try:
                with open(fp, "rb") as f:
                    f.seek(0, 2)
                    size = f.tell()
                    if size <= 0:
                        continue
                    buf = min(450 * 260, size)
                    f.seek(-buf, 2)
                    chunk = f.read().decode("utf-8", errors="replace")
                _append_filtered(fname, chunk)
            except Exception:
                pass

        pat = re.compile(r"(\d{4}-\d{2}-\d{2}[\sT]\d{2}:\d{2}:\d{2})")
        def _t(l):
            m = pat.search(l)
            return m.group(1) if m else "0000-00-00 00:00:00"
        lines.sort(key=_t, reverse=True)
        return {"logs": "\n".join(lines[:150]) if lines else "等待日志输出..."}
    except Exception as e:
        _log = __import__("logging").getLogger(__name__)
        _log.exception("get_logs: %s", e)
        return {"logs": "暂无日志"}


# ═══════════════════════════════════════════════════════
#  ETH 趋势做空策略  start / stop / status
# ═══════════════════════════════════════════════════════

class EthTrendStartRequest(BaseModel):
    symbol: str = "ETH"
    exchange: str = "hyperliquid"   # hyperliquid | binance | backpack | deepcoin
    private_key: Optional[str] = None
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    margin_amount: float = 20.0
    leverage: int = 50
    stop_loss_pct: float = 0.03
    take_profit_pct: float = 0.10
    lockin_trig_pct: float = 0.04
    lockin_prot_pct: float = 0.02
    breakeven_pct: float = 0.03
    price_filter_min: float = 2000.0


def _run_eth_trend_in_thread(instance_id: str, strategy: ETHTrendShortStrategy):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    ETH_TREND_TASKS[instance_id] = loop
    try:
        loop.run_until_complete(strategy.run())
    finally:
        try:
            loop.run_until_complete(strategy.client.close())
        except Exception:
            pass
        loop.close()
        ETH_TREND_TASKS.pop(instance_id, None)


@router.post("/eth-trend-short/start", summary="启动 ETH 趋势做空策略")
def start_eth_trend_short(req: EthTrendStartRequest, user: dict = Depends(require_user)):
    CEX_PLATFORMS = {"binance", "backpack", "deepcoin"}
    exchange = req.exchange.lower() if req.exchange else "hyperliquid"

    if exchange in CEX_PLATFORMS:
        if not req.api_key or not req.api_secret:
            raise HTTPException(status_code=400, detail=f"请提供 {exchange.capitalize()} API Key 和 Secret")
        private_key = None
        api_key = req.api_key
        api_secret = req.api_secret
    else:
        private_key = req.private_key or config.hyperliquid.PRIVATE_KEY
        if not private_key:
            raise HTTPException(status_code=400, detail="请提供 Hyperliquid 私鑰")
        api_key = None
        api_secret = None

    instance_id = f"eth_trend_{datetime.now().strftime('%H%M%S_%f')}"
    try:
        strategy = ETHTrendShortStrategy(
            symbol=req.symbol,
            exchange=exchange,
            private_key=private_key,
            api_key=api_key,
            api_secret=api_secret,
            instance_id=instance_id,
            margin_amount=req.margin_amount,
            leverage=req.leverage,
            stop_loss_pct=req.stop_loss_pct,
            take_profit_pct=req.take_profit_pct,
            lockin_trig_pct=req.lockin_trig_pct,
            lockin_prot_pct=req.lockin_prot_pct,
            breakeven_pct=req.breakeven_pct,
            price_filter_min=req.price_filter_min,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"私鑰格式错误: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"策略初始化失败: {str(e)}")

    thread = threading.Thread(
        target=_run_eth_trend_in_thread, args=(instance_id, strategy), daemon=True
    )
    ETH_TREND_INSTANCES[instance_id] = strategy
    ETH_TREND_THREADS[instance_id] = thread
    thread.start()

    db = DatabaseManager()
    cfg = json.dumps({"platform": exchange, "strategy": "eth_trend_short", "symbol": req.symbol}, ensure_ascii=False)
    db.save_user_instance(user["id"], "live", instance_id, cfg)
    logger.info(f"✅ ETH趋势做空策略已启动: {instance_id} exchange={exchange}")
    return {"ok": True, "instance_id": instance_id, "message": "ETH趋势做空策略已启动"}


@router.post("/eth-trend-short/stop", summary="停止 ETH 趋势做空策略")
def stop_eth_trend_short(user: dict = Depends(require_user)):
    db = DatabaseManager()
    my_ids = set(db.get_user_instance_ids(user["id"], "live"))
    target_ids = [iid for iid in list(ETH_TREND_INSTANCES.keys()) if iid in my_ids]
    if not target_ids:
        return {"ok": True, "message": "没有运行中的ETH趋势做空策略（或不属于当前账号）"}

    for iid in target_ids:
        strategy = ETH_TREND_INSTANCES.pop(iid, None)
        ETH_TREND_THREADS.pop(iid, None)
        loop = ETH_TREND_TASKS.get(iid)
        if strategy:
            strategy.stop()
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(strategy.client.close(), loop)
        ETH_TREND_TASKS.pop(iid, None)
        try:
            db.delete_user_instance(user["id"], "live", iid)
        except Exception:
            pass
    logger.info("🛑 ETH趋势做空策略已停止")
    return {"ok": True, "message": "ETH趋势做空策略已停止"}


@router.get("/eth-trend-short/status", summary="获取 ETH 趋势做空策略状态")
def get_eth_trend_short_status():
    items = []
    for iid, strategy in ETH_TREND_INSTANCES.items():
        try:
            status = strategy.get_status()
            status["running"] = not strategy._stop
            items.append(status)
        except Exception as e:
            items.append({"instance_id": iid, "error": str(e), "running": False})
    return {"running": len(items) > 0, "instances": items}


@router.post("/eth-trend-short/test-open", summary="测试开空仓 (ETH趋势做空)")
def test_eth_trend_open(user: dict = Depends(require_user)):
    """仅用于联调测试：直接触发开空，验证 API 连通性和下单能力。不影响自动信号逻辑。"""
    if not ETH_TREND_INSTANCES:
        raise HTTPException(status_code=404, detail="没有运行中的 ETH趋势做空策略实例")
    iid, strategy = next(iter(ETH_TREND_INSTANCES.items()))
    if strategy.position == "SHORT":
        return {"ok": False, "message": "已有空头仓位，无需开仓", "instance_id": iid}
    loop = ETH_TREND_TASKS.get(iid)
    if not loop:
        raise HTTPException(status_code=500, detail="策略事件循环未找到")
    try:
        future = asyncio.run_coroutine_threadsafe(strategy._open_short(), loop)
        future.result(timeout=15)
        return {
            "ok": True,
            "instance_id": iid,
            "position": strategy.position,
            "entry_price": strategy.entry_price,
            "message": "测试开空已执行",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"测试开空失败: {str(e)}")


@router.post("/eth-trend-short/test-close", summary="测试平仓位 (ETH趋势做空)")
def test_eth_trend_close(user: dict = Depends(require_user)):
    """仅用于联调测试：直接触发平仓。不影响自动信号逻辑。"""
    if not ETH_TREND_INSTANCES:
        raise HTTPException(status_code=404, detail="没有运行中的 ETH趋势做空策略实例")
    iid, strategy = next(iter(ETH_TREND_INSTANCES.items()))
    if strategy.position != "SHORT":
        return {"ok": False, "message": "当前无空头仓位，无需平仓", "instance_id": iid}
    loop = ETH_TREND_TASKS.get(iid)
    if not loop:
        raise HTTPException(status_code=500, detail="策略事件循环未找到")
    try:
        future = asyncio.run_coroutine_threadsafe(
            strategy._safe_close("测试平仓"),
            loop
        )
        future.result(timeout=15)
        return {
            "ok": True,
            "instance_id": iid,
            "position": strategy.position,
            "message": "测试平仓已执行",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"测试平仓失败: {str(e)}")


# ═══════════════════════════════════════════════════════
#  自适应做多策略  start / stop / status / webhook
# ═══════════════════════════════════════════════════════

class AdaptiveLongStartRequest(BaseModel):
    coin: str = "HYPE"                           # 交易对币种，如 BTC/ETH/HYPE
    exchange: str = "hyperliquid"               # hyperliquid | binance | lighter
    wallet_memo: Optional[str] = None           # 可选：钱包备注（仅用于界面显示/备忘，不参与交易）
    private_key: Optional[str] = None           # Hyperliquid / Lighter 专用
    api_key: Optional[str] = None               # Binance API Key
    api_secret: Optional[str] = None            # Binance API Secret
    account_index: int = 0                      # Lighter 账户索引
    api_key_index: int = 2                      # Lighter API 密鑰索引
    timeframe_filter: Optional[str] = None      # K线级别过滤，如 "1H" "2H"，为空则不过滤
    margin_amount: float = 20.0
    leverage: int = 50
    stop_loss_pct: float = 0.03
    take_profit_pct: float = 0.06
    break_even_pct: float = 0.03
    lock_profit_pct: float = 0.0    # 锁利触发盈利比例，0=不启用
    lock_profit_sl_pct: float = 0.0 # 锁利后 SL 锁定的盈利比例
    min_ai_score_for_trade: int = 0  # 0=不启用 AI 门槛；买入须评分>=该值才开单
    allow_repeat_open: bool = False  # K线不限制时：False=同币种已有仓不再开；True=不同周期可加仓
    use_ai_sr_tpsl: bool = False  # True=AI 支撑位止损 + 小级/同级压力分批止盈
    # 注: XYZ 不是子账户，是 HIP-3 DEX，无需地址参数，系统自动识别资产所属 DEX。


class AutoCloseStartRequest(BaseModel):
    coin: str = "ETH"
    exchange: str = "hyperliquid"               # hyperliquid | lighter | binance
    wallet_memo: Optional[str] = None
    private_key: Optional[str] = None           # Hyperliquid 专用
    api_key: Optional[str] = None               # Binance API Key
    api_secret: Optional[str] = None            # Binance API Secret
    account_index: int = 0                      # Lighter 账户索引（可不填，0=自动识别）
    api_key_index: int = 2                      # Lighter API Key index（默认 2）


def _run_auto_close_in_thread(instance_id: str, strategy: AutoCloseStrategy):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    AUTO_CLOSE_TASKS[instance_id] = loop
    try:
        loop.run_until_complete(strategy.run())
    except Exception as e:
        logger.error(f"❌ 自动平仓策略异常退出 [{instance_id}]: {e}")
    finally:
        try:
            loop.run_until_complete(strategy.client.close())
        except Exception:
            pass
        loop.close()
        if AUTO_CLOSE_TASKS.get(instance_id) is loop:
            AUTO_CLOSE_TASKS.pop(instance_id, None)
        if AUTO_CLOSE_INSTANCES.get(instance_id) is strategy:
            AUTO_CLOSE_INSTANCES.pop(instance_id, None)
        if AUTO_CLOSE_THREADS.get(instance_id) is threading.current_thread():
            AUTO_CLOSE_THREADS.pop(instance_id, None)
        logger.info(f"🧹 策略线程已退出并清理: {instance_id}")


@router.post("/auto-close/start", summary="启动自动平仓策略")
def start_auto_close(req: AutoCloseStartRequest, user: dict = Depends(require_user)):
    exchange = (req.exchange or "hyperliquid").lower()
    coin = (req.coin or "ETH").upper().strip()
    if not coin:
        raise HTTPException(status_code=400, detail="请提供币种（如 BTC、ETH、HYPE）")

    if exchange == "binance":
        if not req.api_key or not req.api_secret:
            raise HTTPException(status_code=400, detail="请提供 Binance API Key 和 Secret")
        strategy_kwargs = {"api_key": req.api_key, "api_secret": req.api_secret}
    elif exchange == "lighter":
        if not req.private_key:
            raise HTTPException(status_code=400, detail="请提供 Lighter 私鑰")
        strategy_kwargs = {
            "private_key": req.private_key,
            "account_index": int(getattr(req, "account_index", 0) or 0),
            "api_key_index": int(getattr(req, "api_key_index", 2) or 2),
        }
    else:
        if not req.private_key and not getattr(config.hyperliquid, "PRIVATE_KEY", None):
            raise HTTPException(status_code=400, detail="请提供 Hyperliquid 私鑰")
        strategy_kwargs = {"private_key": req.private_key or getattr(config.hyperliquid, "PRIVATE_KEY", None)}

    instance_id = f"ac_{datetime.now().strftime('%H%M%S_%f')}"
    strategy = AutoCloseStrategy(
        coin=coin,
        exchange=exchange,
        instance_id=instance_id,
        wallet_memo=req.wallet_memo or "",
        **strategy_kwargs,
    )
    thread = threading.Thread(target=_run_auto_close_in_thread, args=(instance_id, strategy), daemon=True)
    AUTO_CLOSE_INSTANCES[instance_id] = strategy
    AUTO_CLOSE_THREADS[instance_id] = thread
    thread.start()

    db = DatabaseManager()
    cfg = json.dumps(
        {
            "platform": exchange,
            "strategy": "auto_close",
            "symbol": coin,
            "coin": coin,
            "exchange": exchange,
            "wallet_memo": req.wallet_memo or "",
            "status": "running",
        },
        ensure_ascii=False,
    )
    db.save_user_instance(user["id"], "live", instance_id, cfg)
    return {"ok": True, "instance_id": instance_id, "message": f"{coin}自动平仓策略已启动"}


@router.post("/auto-close/stop", summary="停止自动平仓策略")
def stop_auto_close(user: dict = Depends(require_user)):
    db = DatabaseManager()
    my_ids = set(db.get_user_instance_ids(user["id"], "live"))
    target_ids = [iid for iid in list(AUTO_CLOSE_INSTANCES.keys()) if iid in my_ids] or list(AUTO_CLOSE_INSTANCES.keys())
    if not target_ids:
        return {"ok": True, "message": "没有运行中的自动平仓策略"}

    for iid in target_ids:
        st = AUTO_CLOSE_INSTANCES.pop(iid, None)
        AUTO_CLOSE_THREADS.pop(iid, None)
        loop = AUTO_CLOSE_TASKS.get(iid)
        if st:
            st.stop()
        if loop and loop.is_running():
            try:
                asyncio.run_coroutine_threadsafe(st.client.close(), loop)
            except Exception:
                pass
        AUTO_CLOSE_TASKS.pop(iid, None)
        try:
            db.delete_user_instance(user["id"], "live", iid)
        except Exception:
            pass
    return {"ok": True, "message": "自动平仓策略已停止"}


@router.get("/auto-close/status", summary="获取自动平仓策略状态")
def get_auto_close_status():
    items = []
    for iid, st in AUTO_CLOSE_INSTANCES.items():
        try:
            s = st.get_status()
            s["running"] = not st._stop
            items.append(s)
        except Exception as e:
            items.append({"instance_id": iid, "error": str(e), "running": False})
    return {"running": len(items) > 0, "instances": items}


@router.post("/auto-close/webhook", summary="接收 TradingView Webhook 信号（自动平仓）")
async def auto_close_webhook(request: Request):
    try:
        _body = await request.body()
        data = json.loads(_body)
    except Exception:
        raise HTTPException(status_code=400, detail="无效的 JSON 请求体")

    action = (data.get("方向") or data.get("操作") or data.get("action") or data.get("signal") or "").lower().strip()
    symbol_raw = str(data.get("交易品种") or data.get("symbol") or data.get("coin") or "")
    symbol_raw = symbol_raw.split(":")[0]
    if symbol_raw.upper().endswith(".P"):
        symbol_raw = symbol_raw[:-2]
    for suffix in ["USDT.P", "USDC.P", "USDT", "USDC", "USD", "PERP", "/USDT", "/USD"]:
        if symbol_raw.upper().endswith(suffix.upper()):
            symbol_raw = symbol_raw[: -len(suffix)]
            break
    signal_symbol = symbol_raw.upper().strip()
    if not signal_symbol:
        raise HTTPException(status_code=400, detail="信号缺少 symbol 字段")

    # 清理僵尸线程实例
    dead_ids = []
    for iid, th in list(AUTO_CLOSE_THREADS.items()):
        if th and not th.is_alive():
            dead_ids.append(iid)
    for iid in dead_ids:
        AUTO_CLOSE_INSTANCES.pop(iid, None)
        AUTO_CLOSE_TASKS.pop(iid, None)
        AUTO_CLOSE_THREADS.pop(iid, None)

    # 按币种路由（自动平仓策略要求绑定币种）
    candidates = [(iid, st) for iid, st in AUTO_CLOSE_INSTANCES.items() if getattr(st, "symbol_filter", "").upper() == signal_symbol]
    if not candidates:
        raise HTTPException(status_code=404, detail=f"没有处理 {signal_symbol} 的自动平仓实例，请先在前端启动该币种策略")
    target_id, strategy = candidates[0]
    if not getattr(strategy, "is_enabled", True):
        return {"ok": True, "instance_id": target_id, "symbol": signal_symbol, "action": action, "message": "策略已停止（暂停接收信号）"}
    loop = AUTO_CLOSE_TASKS.get(target_id)
    if not loop or not loop.is_running():
        AUTO_CLOSE_INSTANCES.pop(target_id, None)
        AUTO_CLOSE_TASKS.pop(target_id, None)
        AUTO_CLOSE_THREADS.pop(target_id, None)
        raise HTTPException(status_code=404, detail=f"策略线程已停止，请重新启动 {signal_symbol} 自动平仓策略")

    try:
        future = asyncio.run_coroutine_threadsafe(strategy.execute_signal(signal_symbol, action), loop)
        try:
            future.result(timeout=2)
        except Exception as e:
            import concurrent.futures
            if isinstance(e, concurrent.futures.TimeoutError):
                logger.warning(f"⏳ Webhook 等待策略处理超时(2s)，已转后台继续: {signal_symbol} {action}")
            else:
                raise
        return {"ok": True, "instance_id": target_id, "symbol": signal_symbol, "action": action, "message": "信号已接收"}
    except Exception as e:
        logger.error(f"处理 {signal_symbol} Webhook 信号失败: {repr(e)}")
        raise HTTPException(status_code=500, detail=f"信号处理失败: {repr(e)}")


def _run_adaptive_long_in_thread(instance_id: str, strategy: AdaptiveLongStrategy):
    logger.info(
        "▶️ 做多策略线程启动 %s | %s | AI开单门槛=%s | 重复开单=%s",
        instance_id,
        getattr(strategy, "symbol_filter", "—"),
        getattr(strategy, "min_ai_score_for_trade", 0),
        "是" if getattr(strategy, "allow_repeat_open", False) else "否",
        "是" if getattr(strategy, "use_ai_sr_tpsl", False) else "否",
    )
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    ADAPTIVE_LONG_TASKS[instance_id] = loop
    try:
        loop.run_until_complete(strategy.run())
    except Exception as e:
        logger.error(f"❌ 自适应做多策略异常退出 [{instance_id}]: {e}")
    finally:
        try:
            loop.run_until_complete(strategy.client.close())
        except Exception:
            pass
        loop.close()
        # 重要：若该 instance_id 已被“更新参数/重启”替换成新 loop，不能误删新 loop
        if ADAPTIVE_LONG_TASKS.get(instance_id) is loop:
            ADAPTIVE_LONG_TASKS.pop(instance_id, None)
        # 同步清理实例，避免 Webhook 找到实例却找不到事件循环的不一致状态
        # 重要：若该 instance_id 已被“更新参数/重启”替换成新对象，不能误删新实例
        if ADAPTIVE_LONG_INSTANCES.get(instance_id) is strategy:
            ADAPTIVE_LONG_INSTANCES.pop(instance_id, None)
        if ADAPTIVE_LONG_THREADS.get(instance_id) is threading.current_thread():
            ADAPTIVE_LONG_THREADS.pop(instance_id, None)
        logger.info(f"🧹 策略线程已退出并清理: {instance_id}")


@router.post("/adaptive-long/start", summary="启动自适应做多策略")
def start_adaptive_long(req: AdaptiveLongStartRequest, user: dict = Depends(require_user)):
    exchange = (req.exchange or "hyperliquid").lower()
    symbol_filter = req.coin.upper().strip() or "HYPE"
    strategy_name = f"{symbol_filter}做多策略(Webhook版)"
    
    # 兼容“全级别/不限制”的多种输入，统一为空（不过滤）
    tf_raw = (req.timeframe_filter or "").strip()
    if tf_raw in ("", "ALL", "all", "不限", "不限制", "全级别", "全周期", "任意"):
        tf_raw = ""
    timeframe_filter = tf_raw or None

    # 根据交易所选择认证方式
    if exchange == "binance":
        if not req.api_key or not req.api_secret:
            raise HTTPException(status_code=400, detail="请提供 Binance API Key 和 Secret")
        strategy_kwargs = {
            "exchange": "binance",
            "api_key": req.api_key,
            "api_secret": req.api_secret,
        }
    elif exchange == "lighter":
        private_key = req.private_key
        if not private_key:
            raise HTTPException(status_code=400, detail="请提供 Lighter 私鑰")
        pk = str(private_key).strip()
        if pk.lower() in ("none", "null", "nan"):
            raise HTTPException(status_code=400, detail="Lighter 私鑰无效：收到了 none/null/nan")
        raw = pk[2:] if pk.lower().startswith("0x") else pk
        if not re.fullmatch(r"[0-9a-fA-F]+", raw or ""):
            raise HTTPException(status_code=400, detail="Lighter 私鑰无效：包含非十六进制字符（仅允许 0-9 a-f A-F）")
        if len(raw) not in (64, 80):
            raise HTTPException(status_code=400, detail=f"Lighter 私鑰长度不正确：期望 64(ETH私钥) 或 80(L2 API Key) hex，实际 {len(raw)}")
        strategy_kwargs = {
            "exchange": "lighter",
            "private_key": private_key,
            "account_index": req.account_index,
            "api_key_index": req.api_key_index,
        }
    else:
        private_key = req.private_key or config.hyperliquid.PRIVATE_KEY
        if not private_key:
            raise HTTPException(status_code=400, detail="请提供 Hyperliquid 私鑰")
        strategy_kwargs = {
            "exchange": "hyperliquid",
            "private_key": private_key,
        }

    instance_id = f"al_{datetime.now().strftime('%H%M%S_%f')}"
    try:
        pk = (str(getattr(req, "private_key", "") or "")).strip()
        pk_raw = pk[2:] if pk.lower().startswith("0x") else pk
        pk_fingerprint = (pk_raw[:6] + "..." + pk_raw[-4:]) if pk_raw else ""
        min_ai = max(0, int(getattr(req, "min_ai_score_for_trade", 0) or 0))
        allow_rep = bool(getattr(req, "allow_repeat_open", False))
        use_ai_sr = bool(getattr(req, "use_ai_sr_tpsl", False))
        logger.info(
            f"🚀 请求启动自适应做多: exchange={exchange} coin={symbol_filter} "
            f"timeframe_filter={timeframe_filter or '不限制'} "
            f"margin_amount={req.margin_amount} leverage={req.leverage} "
            f"AI开单门槛={min_ai} 重复开单={'是' if allow_rep else '否'} "
            f"AI位阶止盈止损={'是' if use_ai_sr else '否'} "
            f"account_index={getattr(req, 'account_index', None)} api_key_index={getattr(req, 'api_key_index', None)} "
            f"pk_len={len(pk_raw) if pk_raw else 0} pk_fp={pk_fingerprint}"
        )
        strategy = AdaptiveLongStrategy(
            **strategy_kwargs,
            instance_id=instance_id,
            margin_amount=req.margin_amount,
            leverage=req.leverage,
            stop_loss_pct=req.stop_loss_pct,
            take_profit_pct=req.take_profit_pct,
            break_even_pct=req.break_even_pct,
            lock_profit_pct=req.lock_profit_pct,
            lock_profit_sl_pct=req.lock_profit_sl_pct,
            symbol_filter=symbol_filter,
            timeframe_filter=timeframe_filter,
            min_ai_score_for_trade=min_ai,
            allow_repeat_open=allow_rep,
            use_ai_sr_tpsl=use_ai_sr,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"认证参数错误: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"策略初始化失败: {str(e)}")

    logger.info(
        "✅ 做多策略对象已创建 %s | %s | AI开单门槛=%s | 重复开单=%s | AI位阶止盈止损=%s（内存）",
        instance_id, symbol_filter, strategy.min_ai_score_for_trade,
        "是" if strategy.allow_repeat_open else "否",
        "是" if strategy.use_ai_sr_tpsl else "否",
    )

    thread = threading.Thread(
        target=_run_adaptive_long_in_thread, args=(instance_id, strategy), daemon=True
    )
    ADAPTIVE_LONG_INSTANCES[instance_id] = strategy
    ADAPTIVE_LONG_THREADS[instance_id] = thread
    thread.start()

    db = DatabaseManager()
    cfg = json.dumps(
        {
            "platform": exchange,
            "exchange": exchange,
            "strategy": "adaptive_long",
            "symbol": symbol_filter,
            "coin": symbol_filter,
            "timeframe_filter": timeframe_filter,
            "margin_amount": req.margin_amount,
            "leverage": req.leverage,
            "stop_loss_pct": req.stop_loss_pct,
            "take_profit_pct": req.take_profit_pct,
            "break_even_pct": req.break_even_pct,
            "lock_profit_pct": req.lock_profit_pct,
            "lock_profit_sl_pct": req.lock_profit_sl_pct,
            # 不在 DB 保存密钥（编辑参数时留空=不修改；运行中应用参数会复用内存中的密钥）
            "api_key": req.api_key if exchange == "binance" else None,
            "account_index": getattr(req, "account_index", 0),
            "api_key_index": getattr(req, "api_key_index", 2),
            "wallet_memo": getattr(req, "wallet_memo", "") if hasattr(req, "wallet_memo") else "",
            "min_ai_score_for_trade": min_ai,
            "allow_repeat_open": allow_rep,
            "use_ai_sr_tpsl": use_ai_sr,
            "status": "running",
        },
        ensure_ascii=False
    )
    db.save_user_instance(user["id"], "live", instance_id, cfg)
    logger.info(
        "✅ %s已启动: %s (交易所=%s 币种=%s AI开单门槛=%s 重复开单=%s AI位阶止盈止损=%s 已写入DB)",
        strategy_name, instance_id, exchange, symbol_filter, min_ai,
        "是" if allow_rep else "否", "是" if use_ai_sr else "否",
    )
    return {
        "ok": True,
        "instance_id": instance_id,
        "min_ai_score_for_trade": min_ai,
        "allow_repeat_open": allow_rep,
        "use_ai_sr_tpsl": use_ai_sr,
        "message": (
            f"{strategy_name}已启动（AI开单门槛={min_ai}，重复开单={'是' if allow_rep else '否'}，"
            f"AI位阶止盈止损={'是' if use_ai_sr else '否'}）"
        ),
    }


@router.post("/adaptive-long/stop", summary="停止自适应做多策略")
def stop_adaptive_long(user: dict = Depends(require_user)):
    db = DatabaseManager()
    my_ids = set(db.get_user_instance_ids(user["id"], "live"))
    target_ids = [iid for iid in list(ADAPTIVE_LONG_INSTANCES.keys()) if iid in my_ids]
    if not target_ids:
        return {"ok": True, "message": "没有运行中的自适应做多策略（或不属于当前账号）"}

    for iid in target_ids:
        strategy = ADAPTIVE_LONG_INSTANCES.pop(iid, None)
        ADAPTIVE_LONG_THREADS.pop(iid, None)
        loop = ADAPTIVE_LONG_TASKS.get(iid)
        if strategy:
            strategy.stop()
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(strategy.client.close(), loop)
        ADAPTIVE_LONG_TASKS.pop(iid, None)
        try:
            db.delete_user_instance(user["id"], "live", iid)
        except Exception:
            pass
    logger.info("🛑 自适应做多策略已停止")
    return {"ok": True, "message": "自适应做多策略已停止"}


@router.get("/adaptive-long/status", summary="获取自适应做多策略状态")
def get_adaptive_long_status():
    items = []
    for iid, strategy in ADAPTIVE_LONG_INSTANCES.items():
        try:
            status = strategy.get_status()
            status["running"] = not strategy._stop
            items.append(status)
        except Exception as e:
            items.append({"instance_id": iid, "error": str(e), "running": False})
    return {"running": len(items) > 0, "instances": items}


@router.post("/adaptive-long/webhook", summary="接收 TradingView Webhook 信号（多币种做多）")
async def adaptive_long_webhook(request: Request):
    """
    一个 Webhook URL 支持多币种，根据 symbol 自动路由到对应实例。
    信号格式: {"symbol":"HYPE","action":"buy","price":10.5}
    """
    try:
        _body = await request.body()
        data = json.loads(_body)
    except Exception:
        raise HTTPException(status_code=400, detail="无效的 JSON 请求体")

    logger.info(f"📥 adaptive-long 收到信号: {str(data)[:200]}")

    # 解析信号字段（兼容中文字段名 + 英文字段名）
    action = (data.get("方向") or data.get("操作") or data.get("action") or data.get("signal") or "").lower().strip()
    symbol_raw = str(data.get("交易品种") or data.get("symbol") or data.get("coin") or "")
    strategy_name = str(
        data.get("策略名称")
        or data.get("strategy_name")
        or data.get("strategyName")
        or data.get("strategy")
        or data.get("strategy_label")
        or ""
    ).strip()
    # K线级别：兼容多种字段名
    signal_timeframe = str(
        data.get("K线级别") or data.get("timeframe") or data.get("interval") or data.get("tf") or ""
    ).upper().strip()
    # 将 TradingView 分钟数转换为标准格式：60→1H  240→4H
    _TF_MAP = {
        "1": "1M", "3": "3M", "5": "5M", "10": "10M",
        "15": "15M", "30": "30M", "45": "45M",
        "60": "1H", "120": "2H", "180": "3H", "240": "4H",
        "360": "6H", "480": "8H", "720": "12H",
        "1440": "1D", "D": "1D", "1W": "1W", "W": "1W",
    }
    signal_timeframe = _TF_MAP.get(signal_timeframe, signal_timeframe)
    # 先去掉 TradingView 常见后缀（如 .P / .p / :USDT 等）
    symbol_raw = symbol_raw.split(":")[0]          # 去 :USDT
    if symbol_raw.upper().endswith(".P"):
        symbol_raw = symbol_raw[:-2]               # 去 .P
    for suffix in ["USDT.P", "USDC.P", "USDT", "USDC", "USD", "PERP", "/USDT", "/USD"]:
        if symbol_raw.upper().endswith(suffix.upper()):
            symbol_raw = symbol_raw[: -len(suffix)]
            break
    signal_symbol = symbol_raw.upper().strip()

    if not signal_symbol:
        raise HTTPException(status_code=400, detail="信号缺少 symbol 字段")

    logger.info(f"📡 Webhook 信号解析: action={action}  symbol={signal_symbol}  timeframe={signal_timeframe or '未指定'}")

    from backpack_quant_trading.core.crypto_signal_scorer import (
        dingtalk_webhook_enabled,
        extract_ai_sr_tpsl_plan,
        is_buy_action,
        is_sell_action,
        push_score_to_dingtalk,
        run_signal_score,
    )

    if is_sell_action(action):
        logger.info(
            "📋 做多策略卖出=平仓 | %s %s | 跳过 AI 评分与开单门槛",
            signal_symbol, signal_timeframe or "默认周期",
        )

    # 按 symbol_filter 路由到匹配的实例
    # 同时清理线程已死亡的僵尸实例（防止旧版 finally 未清理留下的残留）
    dead_ids = []
    for iid, th in list(ADAPTIVE_LONG_THREADS.items()):
        if th and not th.is_alive():
            dead_ids.append(iid)
    for iid in dead_ids:
        logger.warning(f"🧹 Webhook 发现僵尸实例，自动清理: {iid}")
        ADAPTIVE_LONG_INSTANCES.pop(iid, None)
        ADAPTIVE_LONG_TASKS.pop(iid, None)
        ADAPTIVE_LONG_THREADS.pop(iid, None)

    candidates = _adaptive_long_symbol_candidates(ADAPTIVE_LONG_INSTANCES, signal_symbol)
    target_id = _pick_adaptive_long_instance_for_webhook(candidates, signal_timeframe)
    logger.info(
        f"📨 adaptive-long 路由: target={target_id} 候选数={len(candidates)} "
        f"signal_tf={signal_timeframe or '未指定'}"
    )

    if not target_id:
        if len(candidates) > 1 and not (signal_timeframe or "").strip():
            raise HTTPException(
                status_code=400,
                detail=(
                    f"同币种 {signal_symbol} 有多个运行中的做多实例，Webhook 必须在 JSON 中携带 K 线级别字段"
                    f"（如 timeframe / K线级别 / tf），以便路由到对应实例"
                ),
            )
        if len(candidates) > 1 and (signal_timeframe or "").strip():
            raise HTTPException(
                status_code=404,
                detail=(
                    f"没有 K 线级别与信号 {signal_timeframe} 匹配的 {signal_symbol} 做多实例"
                    f"（请确认已启动对应周期的策略，或信号级别与实例配置一致）"
                ),
            )
        raise HTTPException(
            status_code=404,
            detail=f"没有处理 {signal_symbol} 的运行中策略实例，请先在前端启动对应币种的做多策略",
        )

    strategy = ADAPTIVE_LONG_INSTANCES[target_id]
    if not getattr(strategy, "is_enabled", True):
        return {
            "ok": True,
            "instance_id": target_id,
            "symbol": signal_symbol,
            "action": action,
            "message": "策略已停止（暂停接收信号），本次信号已忽略",
        }

    allow_repeat = bool(getattr(strategy, "allow_repeat_open", False))
    use_ai_sr = bool(getattr(strategy, "use_ai_sr_tpsl", False))
    min_trade_score = max(0, int(getattr(strategy, "min_ai_score_for_trade", 0) or 0))
    ai_sr_plan = None
    score_res: dict = {}

    if is_buy_action(action):
        logger.info(
            "📋 实例 %s | %s %s | AI开单门槛=%s | 重复开单=%s | AI位阶止盈止损=%s | 持仓=%s | 开仓中=%s",
            target_id,
            signal_symbol,
            signal_timeframe or "默认周期",
            min_trade_score,
            "是" if allow_repeat else "否",
            "是" if use_ai_sr else "否",
            getattr(strategy, "position", None) or "无",
            "是" if getattr(strategy, "_opening", False) else "否",
        )
        if not allow_repeat and (
            getattr(strategy, "position", None) == "LONG"
            or getattr(strategy, "_opening", False)
        ):
            entry_tfs = sorted(getattr(strategy, "position_entry_tfs", set()) or [])
            logger.info(
                "⛔ Webhook拦截 | 重复开单=否 | 已有或正在建立 %s 多仓，忽略 %s %s 买入"
                "（已开仓级别=%s）",
                signal_symbol,
                signal_symbol,
                signal_timeframe or "—",
                entry_tfs or ["—"],
            )
            return {
                "ok": True,
                "skipped": True,
                "instance_id": target_id,
                "symbol": signal_symbol,
                "action": action,
                "allow_repeat_open": False,
                "message": (
                    f"重复开单=否，已有{signal_symbol}多仓或开仓进行中，"
                    f"忽略{signal_timeframe or '本次'}买入"
                ),
            }

    # 买入：先同步完成 AI 评分，再决定是否开单（避免后台钉钉评分未结束就已开仓）
    if is_buy_action(action):
        need_score = min_trade_score > 0 or use_ai_sr or dingtalk_webhook_enabled()
        logger.info(
            "🤖 AI评分（同步，开单前）| %s %s | 开单门槛=%s%s%s",
            signal_symbol,
            signal_timeframe or "默认周期",
            min_trade_score,
            "（未启用拦截）" if min_trade_score <= 0 else "（低于门槛将拒绝开仓）",
            " | 将提取支撑/压力挂止盈止损" if use_ai_sr else "",
        )
        if not need_score:
            score_res = {"ok": False, "error": "skip"}
        else:
            score_res = run_signal_score(
                signal_symbol,
                action,
                timeframe=signal_timeframe,
                webhook_raw=data,
                strategy_label="adaptive_long",
            )
        if need_score and not score_res.get("ok"):
            err_detail = score_res.get("error") or "未知错误"
            logger.info(
                "⛔ AI评分失败 | %s | 开单门槛=%s | 原因=%s",
                signal_symbol, min_trade_score, err_detail,
            )
            if min_trade_score > 0:
                return {
                    "ok": True,
                    "skipped": True,
                    "instance_id": target_id,
                    "symbol": signal_symbol,
                    "action": action,
                    "ai_score_filter": True,
                    "min_ai_score_required": min_trade_score,
                    "message": (
                        f"AI评分为—（评分失败），开单门槛为{min_trade_score}，未达门槛，拒绝交易：{err_detail}"
                    ),
                }
        elif need_score:
            got_score = int(score_res.get("score") or 0)
            grade = score_res.get("grade") or "—"
            rec = score_res.get("recommendation") or "—"
            if min_trade_score > 0 and got_score < min_trade_score:
                logger.info(
                    "⛔ 拒绝交易 | %s | AI评分=%s（等级%s 建议%s）| 开单门槛=%s | 未达门槛，拒绝开仓",
                    signal_symbol, got_score, grade, rec, min_trade_score,
                )
                return {
                    "ok": True,
                    "skipped": True,
                    "instance_id": target_id,
                    "symbol": signal_symbol,
                    "action": action,
                    "ai_score": got_score,
                    "min_ai_score_required": min_trade_score,
                    "grade": grade,
                    "recommendation": rec,
                    "message": (
                        f"AI评分为{got_score}，开单门槛为{min_trade_score}，未达门槛，拒绝交易"
                    ),
                }
            if min_trade_score > 0:
                logger.info(
                    "✅ 允许开单 | %s | AI评分=%s（等级%s 建议%s）| 开单门槛=%s | 已达门槛",
                    signal_symbol, got_score, grade, rec, min_trade_score,
                )
            else:
                logger.info(
                    "📋 允许开单 | %s | AI评分=%s（等级%s 建议%s）| 开单门槛=0（仅记录，不拦截）",
                    signal_symbol, got_score, grade, rec,
                )

            if use_ai_sr and score_res.get("ok"):
                metrics = (score_res.get("snapshot") or {}).get("metrics") or {}
                entry_est = float(metrics.get("close") or metrics.get("sr_close") or 0)
                ai_sr_plan = extract_ai_sr_tpsl_plan(metrics, entry_est)
                if ai_sr_plan:
                    logger.info(
                        "📐 AI位阶止盈止损方案 | 止损支撑=%.4f | 止盈1(50%%)小级=%s | 止盈2(50%%)同级=%s",
                        ai_sr_plan["support"],
                        f"{ai_sr_plan['tp_lower_tf']:.4f}" if ai_sr_plan.get("tp_lower_tf") else "—",
                        f"{ai_sr_plan['tp_same_tf']:.4f}" if ai_sr_plan.get("tp_same_tf") else "—",
                    )
                else:
                    logger.info("⚠️ AI位阶止盈止损: 支撑/压力数据不足，开仓后将使用百分比止盈止损")

            if dingtalk_webhook_enabled() and score_res.get("ok"):

                def _push_dingtalk_cached(res: dict = score_res):
                    try:
                        push_score_to_dingtalk(res)
                    except Exception as e:
                        logger.warning("钉钉 AI 评分推送失败(忽略): %s", e)

                threading.Thread(
                    target=_push_dingtalk_cached,
                    daemon=True,
                    name=f"dingtalk-push-{signal_symbol}",
                ).start()

    loop = ADAPTIVE_LONG_TASKS.get(target_id)
    if not loop or not loop.is_running():
        # 兜底：loop 不存在或已关闭，清理该实例
        ADAPTIVE_LONG_INSTANCES.pop(target_id, None)
        ADAPTIVE_LONG_TASKS.pop(target_id, None)
        ADAPTIVE_LONG_THREADS.pop(target_id, None)
        raise HTTPException(
            status_code=404,
            detail=f"策略线程已停止，请在前端重新启动 {signal_symbol} 做多策略"
        )

    try:
        future = asyncio.run_coroutine_threadsafe(
            strategy.execute_signal(
                signal_symbol,
                action,
                timeframe=signal_timeframe or None,
                ai_sr_levels=ai_sr_plan if is_buy_action(action) else None,
            ),
            loop
        )
        try:
            # Webhook 需要快速返回；下单/拉行情可能超过 10s（代理抖动、DEX 延迟）。
            # 这里尽量等待短时间确认任务已启动；超时则返回已接收，让策略后台继续跑。
            future.result(timeout=2)
        except Exception as e:
            # 仅处理超时：其它异常继续抛给上层
            import concurrent.futures
            if isinstance(e, concurrent.futures.TimeoutError):
                logger.warning(f"⏳ Webhook 等待策略处理超时(2s)，已转后台继续: {signal_symbol} {action}")
            else:
                raise
        return {
            "ok": True,
            "instance_id": target_id,
            "symbol": signal_symbol,
            "action": action,
            "position": strategy.position,
            "message": f"信号已处理: {action} {signal_symbol}",
        }
    except Exception as e:
        logger.error(f"处理 {signal_symbol} Webhook 信号失败: {repr(e)}")
        raise HTTPException(status_code=500, detail=f"信号处理失败: {repr(e)}")


# ═══════════════════════════════════════════════════════
#  自适应做空策略  start / stop / status / webhook
# ═══════════════════════════════════════════════════════


def _run_adaptive_short_in_thread(instance_id: str, strategy: AdaptiveShortStrategy):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    ADAPTIVE_SHORT_TASKS[instance_id] = loop
    try:
        loop.run_until_complete(strategy.run())
    except Exception as e:
        logger.error(f"❌ 自适应做空策略异常退出 [{instance_id}]: {e}")
    finally:
        try:
            loop.run_until_complete(strategy.client.close())
        except Exception:
            pass
        loop.close()
        # 重要：若该 instance_id 已被“更新参数/重启”替换成新 loop，不能误删新 loop
        if ADAPTIVE_SHORT_TASKS.get(instance_id) is loop:
            ADAPTIVE_SHORT_TASKS.pop(instance_id, None)
        # 重要：若该 instance_id 已被“更新参数/重启”替换成新对象，不能误删新实例
        if ADAPTIVE_SHORT_INSTANCES.get(instance_id) is strategy:
            ADAPTIVE_SHORT_INSTANCES.pop(instance_id, None)
        if ADAPTIVE_SHORT_THREADS.get(instance_id) is threading.current_thread():
            ADAPTIVE_SHORT_THREADS.pop(instance_id, None)
        logger.info(f"🧹 策略线程已退出并清理: {instance_id}")


@router.post("/adaptive-short/start", summary="启动自适应做空策略")
def start_adaptive_short(req: AdaptiveLongStartRequest, user: dict = Depends(require_user)):
    if AdaptiveShortStrategy is None:
        raise HTTPException(status_code=500, detail="AdaptiveShortStrategy 导入失败：请检查服务器上 strategy/adaptive_short_strategy.py 是否为最新版本")
    exchange = (req.exchange or "hyperliquid").lower()
    symbol_filter = req.coin.upper().strip() or "HYPE"
    strategy_name = f"{symbol_filter}做空策略(Webhook版)"

    tf_raw = (req.timeframe_filter or "").strip()
    if tf_raw in ("", "ALL", "all", "不限", "不限制", "全级别", "全周期", "任意"):
        tf_raw = ""
    timeframe_filter = tf_raw or None

    if exchange == "binance":
        if not req.api_key or not req.api_secret:
            raise HTTPException(status_code=400, detail="请提供 Binance API Key 和 Secret")
        strategy_kwargs = {"exchange": "binance", "api_key": req.api_key, "api_secret": req.api_secret}
    elif exchange == "lighter":
        private_key = req.private_key
        if not private_key:
            raise HTTPException(status_code=400, detail="请提供 Lighter 私鑰")
        pk = str(private_key).strip()
        if pk.lower() in ("none", "null", "nan"):
            raise HTTPException(status_code=400, detail="Lighter 私鑰无效：收到了 none/null/nan")
        raw = pk[2:] if pk.lower().startswith("0x") else pk
        if not re.fullmatch(r"[0-9a-fA-F]+", raw or ""):
            raise HTTPException(status_code=400, detail="Lighter 私鑰无效：包含非十六进制字符（仅允许 0-9 a-f A-F）")
        if len(raw) not in (64, 80):
            raise HTTPException(status_code=400, detail=f"Lighter 私鑰长度不正确：期望 64(ETH私钥) 或 80(L2 API Key) hex，实际 {len(raw)}")
        strategy_kwargs = {"exchange": "lighter", "private_key": private_key, "account_index": req.account_index, "api_key_index": req.api_key_index}
    else:
        private_key = req.private_key or config.hyperliquid.PRIVATE_KEY
        if not private_key:
            raise HTTPException(status_code=400, detail="请提供 Hyperliquid 私鑰")
        strategy_kwargs = {"exchange": "hyperliquid", "private_key": private_key}

    instance_id = f"as_{datetime.now().strftime('%H%M%S_%f')}"
    try:
        pk = (str(getattr(req, "private_key", "") or "")).strip()
        pk_raw = pk[2:] if pk.lower().startswith("0x") else pk
        pk_fingerprint = (pk_raw[:6] + "..." + pk_raw[-4:]) if pk_raw else ""
        logger.info(
            f"🚀 请求启动自适应做空: exchange={exchange} coin={symbol_filter} "
            f"timeframe_filter={timeframe_filter or '不限制'} "
            f"margin_amount={req.margin_amount} leverage={req.leverage} "
            f"account_index={getattr(req, 'account_index', None)} api_key_index={getattr(req, 'api_key_index', None)} "
            f"pk_len={len(pk_raw) if pk_raw else 0} pk_fp={pk_fingerprint}"
        )
        strategy = AdaptiveShortStrategy(
            **strategy_kwargs,
            instance_id=instance_id,
            margin_amount=req.margin_amount,
            leverage=req.leverage,
            stop_loss_pct=req.stop_loss_pct,
            take_profit_pct=req.take_profit_pct,
            break_even_pct=req.break_even_pct,
            lock_profit_pct=req.lock_profit_pct,
            lock_profit_sl_pct=req.lock_profit_sl_pct,
            symbol_filter=symbol_filter,
            timeframe_filter=timeframe_filter,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建策略失败: {repr(e)}")

    thread = threading.Thread(
        target=_run_adaptive_short_in_thread, args=(instance_id, strategy), daemon=True
    )
    ADAPTIVE_SHORT_INSTANCES[instance_id] = strategy
    ADAPTIVE_SHORT_THREADS[instance_id] = thread
    thread.start()

    # 与 adaptive-long 保持一致：用 save_user_instance 落库，instances 列表才能稳定显示
    try:
        db = DatabaseManager()
        cfg = json.dumps(
            {
                "platform": exchange,
                "exchange": exchange,
                "strategy": "adaptive_short",
                "symbol": symbol_filter,
                "coin": symbol_filter,
                "timeframe_filter": timeframe_filter,
                "margin_amount": req.margin_amount,
                "leverage": req.leverage,
                "stop_loss_pct": req.stop_loss_pct,
                "take_profit_pct": req.take_profit_pct,
                "break_even_pct": req.break_even_pct,
                "lock_profit_pct": req.lock_profit_pct,
                "lock_profit_sl_pct": req.lock_profit_sl_pct,
                # 不在 DB 保存密钥（编辑参数时留空=不修改；运行中应用参数会复用内存中的密钥）
                "api_key": req.api_key if exchange == "binance" else None,
                "account_index": getattr(req, "account_index", 0),
                "api_key_index": getattr(req, "api_key_index", 2),
                "wallet_memo": getattr(req, "wallet_memo", "") if hasattr(req, "wallet_memo") else "",
                "status": "running",
            },
            ensure_ascii=False,
        )
        db.save_user_instance(user["id"], "live", instance_id, cfg)
    except Exception:
        pass
    logger.info(f"✅ {strategy_name}已启动: {instance_id} (交易所={exchange} 币种={symbol_filter})")
    return {"ok": True, "instance_id": instance_id, "message": f"{strategy_name}已启动"}


@router.post("/adaptive-short/stop", summary="停止自适应做空策略")
def stop_adaptive_short(user: dict = Depends(require_user)):
    try:
        db = DatabaseManager()
        my_ids = set(db.get_user_instance_ids(user["id"], "live"))
    except Exception:
        my_ids = set()

    target_ids = [iid for iid in list(ADAPTIVE_SHORT_INSTANCES.keys()) if iid in my_ids]
    if not target_ids:
        return {"ok": True, "message": "没有运行中的自适应做空策略（或不属于当前账号）"}

    for iid in target_ids:
        try:
            strategy = ADAPTIVE_SHORT_INSTANCES.pop(iid, None)
            if strategy:
                strategy.stop()
        except Exception:
            pass
        ADAPTIVE_SHORT_TASKS.pop(iid, None)
        ADAPTIVE_SHORT_THREADS.pop(iid, None)
        try:
            db = DatabaseManager()
            db.delete_user_instance(user["id"], "live", iid)
        except Exception:
            pass
    logger.info("🛑 自适应做空策略已停止")
    return {"ok": True, "message": "自适应做空策略已停止"}


@router.get("/adaptive-short/status", summary="获取自适应做空策略状态")
def get_adaptive_short_status():
    items = []
    for iid, strategy in ADAPTIVE_SHORT_INSTANCES.items():
        try:
            status = strategy.get_status()
            status["running"] = not strategy._stop
            items.append(status)
        except Exception as e:
            items.append({"instance_id": iid, "error": str(e), "running": False})
    return {"running": len(items) > 0, "instances": items}


@router.post("/adaptive-short/webhook", summary="接收 TradingView Webhook 信号（多币种做空）")
async def adaptive_short_webhook(request: Request):
    try:
        _body = await request.body()
        data = json.loads(_body)
    except Exception:
        raise HTTPException(status_code=400, detail="无效的 JSON 请求体")

    logger.info(f"📥 adaptive-short 收到信号: {str(data)[:200]}")

    action = (data.get("方向") or data.get("操作") or data.get("action") or data.get("signal") or "").lower().strip()
    symbol_raw = str(data.get("交易品种") or data.get("symbol") or data.get("coin") or "")
    strategy_name = str(
        data.get("策略名称")
        or data.get("strategy_name")
        or data.get("strategyName")
        or data.get("strategy")
        or data.get("strategy_label")
        or ""
    ).strip()
    signal_timeframe = str(data.get("K线级别") or data.get("timeframe") or data.get("interval") or data.get("tf") or "").upper().strip()
    _TF_MAP = {
        "1": "1M", "3": "3M", "5": "5M", "10": "10M",
        "15": "15M", "30": "30M", "45": "45M",
        "60": "1H", "120": "2H", "180": "3H", "240": "4H",
        "360": "6H", "480": "8H", "720": "12H",
        "1440": "1D", "D": "1D", "1W": "1W", "W": "1W",
    }
    signal_timeframe = _TF_MAP.get(signal_timeframe, signal_timeframe)
    symbol_raw = symbol_raw.split(":")[0]
    if symbol_raw.upper().endswith(".P"):
        symbol_raw = symbol_raw[:-2]
    for suffix in ["USDT.P", "USDC.P", "USDT", "USDC", "USD", "PERP", "/USDT", "/USD"]:
        if symbol_raw.upper().endswith(suffix.upper()):
            symbol_raw = symbol_raw[: -len(suffix)]
            break
    signal_symbol = symbol_raw.upper().strip()
    if not signal_symbol:
        raise HTTPException(status_code=400, detail="信号缺少 symbol 字段")

    logger.info(f"📡 Webhook 信号解析: action={action}  symbol={signal_symbol}  timeframe={signal_timeframe or '未指定'}")

    from backpack_quant_trading.core.crypto_signal_scorer import (
        is_buy_action,
        is_sell_action,
        schedule_webhook_dingtalk_score,
    )

    # 路径2：钉钉 AI 评分（仅卖出开空；买入=平空，不评分）
    if is_sell_action(action):
        try:
            schedule_webhook_dingtalk_score(
                signal_symbol,
                action,
                timeframe=signal_timeframe,
                webhook_raw=data,
                strategy_label="adaptive_short",
                strategy_name=strategy_name or "自适应做空",
                strategy_side="short",
            )
        except Exception as _sc_err:
            logger.warning("钉钉 AI 评分调度失败(忽略): %s", _sc_err)
    elif is_buy_action(action):
        logger.info(
            "📋 做空策略买入=平仓 | %s %s | 跳过 AI 评分（钉钉）",
            signal_symbol, signal_timeframe or "默认周期",
        )

    dead_ids = []
    for iid, th in list(ADAPTIVE_SHORT_THREADS.items()):
        if th and not th.is_alive():
            dead_ids.append(iid)
    for iid in dead_ids:
        logger.warning(f"🧹 Webhook 发现僵尸实例，自动清理: {iid}")
        ADAPTIVE_SHORT_INSTANCES.pop(iid, None)
        ADAPTIVE_SHORT_TASKS.pop(iid, None)
        ADAPTIVE_SHORT_THREADS.pop(iid, None)

    candidates = _adaptive_short_symbol_candidates(ADAPTIVE_SHORT_INSTANCES, signal_symbol)
    target_id = _pick_adaptive_short_instance_for_webhook(candidates, signal_timeframe)
    logger.info(f"📨 adaptive-short 路由: target={target_id} 候选数={len(candidates)} signal_tf={signal_timeframe or '未指定'}")

    if not target_id:
        if len(candidates) > 1 and not (signal_timeframe or "").strip():
            raise HTTPException(status_code=400, detail=f"同币种 {signal_symbol} 有多个运行中的做空实例，Webhook 必须携带 K 线级别字段以便路由")
        if len(candidates) > 1 and (signal_timeframe or "").strip():
            raise HTTPException(status_code=404, detail=f"没有 K 线级别与信号 {signal_timeframe} 匹配的 {signal_symbol} 做空实例")
        raise HTTPException(status_code=404, detail=f"没有处理 {signal_symbol} 的运行中做空实例，请先在前端启动对应币种的做空策略")

    strategy = ADAPTIVE_SHORT_INSTANCES[target_id]
    if not getattr(strategy, "is_enabled", True):
        return {
            "ok": True,
            "instance_id": target_id,
            "symbol": signal_symbol,
            "action": action,
            "message": "策略已停止（暂停接收信号），本次信号已忽略",
        }
    loop = ADAPTIVE_SHORT_TASKS.get(target_id)
    if not loop or not loop.is_running():
        ADAPTIVE_SHORT_INSTANCES.pop(target_id, None)
        ADAPTIVE_SHORT_TASKS.pop(target_id, None)
        ADAPTIVE_SHORT_THREADS.pop(target_id, None)
        raise HTTPException(status_code=404, detail=f"策略线程已停止，请在前端重新启动 {signal_symbol} 做空策略")

    try:
        future = asyncio.run_coroutine_threadsafe(
            strategy.execute_signal(signal_symbol, action, timeframe=signal_timeframe or None),
            loop,
        )
        try:
            future.result(timeout=2)
        except Exception as e:
            import concurrent.futures
            if isinstance(e, concurrent.futures.TimeoutError):
                logger.warning(f"⏳ Webhook 等待策略处理超时(2s)，已转后台继续: {signal_symbol} {action}")
            else:
                raise
        return {"ok": True, "instance_id": target_id, "symbol": signal_symbol, "action": action, "position": strategy.position, "message": f"信号已处理: {action} {signal_symbol}"}
    except Exception as e:
        logger.error(f"处理 {signal_symbol} Webhook 信号失败: {repr(e)}")
        raise HTTPException(status_code=500, detail=f"信号处理失败: {repr(e)}")

