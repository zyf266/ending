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
from typing import Optional, List, Dict
import threading
import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backpack_quant_trading.api.deps import require_user
from backpack_quant_trading.config.settings import config
from backpack_quant_trading.database.models import DatabaseManager
from backpack_quant_trading.main import STRATEGY_REGISTRY, STRATEGY_DISPLAY_NAMES
from backpack_quant_trading.strategy.hype_adaptive_short import HYPEAdaptiveShortStrategy
from backpack_quant_trading.strategy.eth_trend_short import ETHTrendShortStrategy
from backpack_quant_trading.strategy.adaptive_long_strategy import AdaptiveLongStrategy

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
    - 若已是完整格式（含 _PERP、-SWAP 等），则原样返回
    """
    s = (user_input or "").strip().upper()
    if not s:
        return user_input or ""

    # 已是完整格式：包含 _PERP、-SWAP、-PERP
    if "_PERP" in s or "-SWAP" in s or "-PERP" in s:
        return s
    # 已是分隔格式：ETH_USDC、ETH-USDT、ETH/USDC 等
    if "_" in s:
        return s
    if "-" in s and len(s) > 6:
        return s
    if "/" in s:
        base = s.split("/")[0]
        if platform == "backpack":
            return f"{base}_USDC_PERP"
        if platform == "deepcoin":
            return f"{base}-USDT-SWAP"
        return s

    # 纯基础币种：ETH、BTC、SOL 等
    base = s
    if platform == "backpack":
        return f"{base}_USDC_PERP"
    if platform == "deepcoin":
        return f"{base}-USDT-SWAP"
    return s


@router.get("/strategies")
def list_strategies():
    return {
        "strategies": [{"value": k, "label": STRATEGY_DISPLAY_NAMES.get(k, k)} for k in STRATEGY_REGISTRY.keys()] + [
            {"value": "hype_adaptive_short", "label": "自适应做空策略(Webhook版)"},
            {"value": "eth_trend_short",     "label": "ETH趋势做空策略"},
            {"value": "adaptive_long",       "label": "自适应做多策略(Webhook版)"},
        ],
        "exchanges": [
            {"value": "backpack", "label": "Backpack"},
            {"value": "deepcoin", "label": "Deepcoin"},
            {"value": "ostium", "label": "Ostium"},
            {"value": "hyperliquid", "label": "Hyperliquid"},
        ],
        "hype_strategies": [
            {"value": "hype_adaptive_short", "label": "自适应做空策略(Webhook版)"},
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
        return {"instances": []}
    if not my_ids:
        return {"instances": []}

    try:
        # 尝试从 Webhook 获取运行中实例
        instances = []
        if _is_port_in_use(WEBHOOK_PORT):
            try:
                r = requests.get(f"http://127.0.0.1:{WEBHOOK_PORT}/instances", timeout=5)
                if r.status_code == 200:
                    data = r.json()
                    for inst in data.get("instances", []):
                        iid = inst.get("instance_id", inst)
                        if iid in my_ids:
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
        for iid in my_ids:
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
                balance_str = f"{al.balance_cache:,.2f}" if al.balance_cache is not None else "--"
                start_time_str = al.start_time.strftime("%m-%d %H:%M") if hasattr(al, "start_time") else "--:--"
                instances.append({
                    "id": iid,
                    "pid": pid,
                    "platform": "hyperliquid",
                    "strategy_name": "自适应做多策略(Webhook版)",
                    "symbol": al.symbol or "动态(Webhook)",
                    "start_time": start_time_str,
                    "balance": balance_str,
                    "status": "running",
                })
                continue

            balance_str = "--"
            if iid in _balances:
                bal = _balances[iid].get("balance")
                if bal is not None:
                    balance_str = f"{float(bal):,.2f}"
            raw_strategy = obj.get("strategy", "")
            strategy_name = STRATEGY_DISPLAY_NAMES.get(raw_strategy, raw_strategy)
            instances.append({
                "id": iid,
                "pid": pid,
                "platform": obj.get("platform", "backpack"),
                "strategy_name": strategy_name,
                "symbol": obj.get("symbol", ""),
                "start_time": "--:--",
                "balance": balance_str,
                "status": "running",
            })

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

    # Backpack / Deepcoin：子进程模式
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
    """停止实盘实例"""
    db = DatabaseManager()
    my_ids = db.get_user_instance_ids(user["id"], "live")
    if instance_id not in my_ids:
        raise HTTPException(status_code=403, detail="无权操作该实例")

    configs = {iid: cfg for iid, cfg in db.get_user_instance_configs(user["id"], "live")}
    cfg_str = configs.get(instance_id, "{}")
    try:
        obj = json.loads(cfg_str) if cfg_str else {}
    except Exception:
        obj = {}
    platform = obj.get("platform", "backpack")

    if platform in ["ostium", "hyperliquid"]:
        # HYPE 自适应做空策略是本地线程模式，不走 webhook 注销
        if instance_id.startswith("hype_"):
            strategy = HYPE_STRATEGY_INSTANCES.pop(instance_id, None)
            loop = HYPE_STRATEGY_TASKS.get(instance_id)
            HYPE_STRATEGY_THREADS.pop(instance_id, None)
            if strategy and loop:
                strategy._stop = True
                asyncio.run_coroutine_threadsafe(strategy.close(), loop)
        # ETH 趋势做空
        elif instance_id.startswith("eth_trend_"):
            strategy = ETH_TREND_INSTANCES.pop(instance_id, None)
            loop = ETH_TREND_TASKS.get(instance_id)
            ETH_TREND_THREADS.pop(instance_id, None)
            if strategy:
                strategy.stop()
            if loop and loop.is_running():
                asyncio.run_coroutine_threadsafe(strategy.client.close(), loop)
            ETH_TREND_TASKS.pop(instance_id, None)
        # 自适应做多策略
        elif instance_id.startswith("al_"):
            strategy = ADAPTIVE_LONG_INSTANCES.pop(instance_id, None)
            loop = ADAPTIVE_LONG_TASKS.get(instance_id)
            ADAPTIVE_LONG_THREADS.pop(instance_id, None)
            if strategy:
                strategy.stop()
            if loop and loop.is_running():
                asyncio.run_coroutine_threadsafe(strategy.client.close(), loop)
            ADAPTIVE_LONG_TASKS.pop(instance_id, None)
        else:
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

    db.delete_user_instance(user["id"], "live", instance_id)
    return {"message": "ok"}


@router.get("/logs")
def get_logs(user: dict = Depends(require_user)):
    """获取实时日志（最近 150 行）"""
    try:
        log_dir = PROJECT_ROOT / "backpack_quant_trading" / "log"
        lines = []
        # 添加各策略日志文件到读取列表
        for fname in ["webhook_server.log", "live_console.log", "hype_strategy.log", "eth_trend_short.log", "adaptive_long.log"]:
            fp = log_dir / fname
            if fp.exists():
                try:
                    with open(fp, "rb") as f:
                        f.seek(0, 2)
                        size = f.tell()
                        buf = min(300 * 150, size)
                        f.seek(-buf, 2)
                        chunk = f.read().decode("utf-8", errors="replace")
                        for line in chunk.splitlines():
                            if line.strip():
                                lines.append(f"[{fname}] {line}")
                except Exception:
                    pass

        import re
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
    private_key: Optional[str] = None
    margin_amount: float = 20.0
    leverage: int = 50
    stop_loss_pct: float = 0.03
    take_profit_pct: float = 0.10
    lockin_trig_pct: float = 0.04
    lockin_prot_pct: float = 0.02
    breakeven_pct: float = 0.05
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
    if ETH_TREND_INSTANCES:
        running = [iid for iid, s in ETH_TREND_INSTANCES.items() if not s._stop]
        if running:
            return {"ok": False, "message": "ETH趋势做空策略已在运行中，请先停止再启动"}

    private_key = req.private_key or config.hyperliquid.PRIVATE_KEY
    if not private_key:
        raise HTTPException(status_code=400, detail="请提供 Hyperliquid 私钥")

    instance_id = f"eth_trend_{datetime.now().strftime('%H%M%S_%f')}"
    try:
        strategy = ETHTrendShortStrategy(
            symbol=req.symbol,
            private_key=private_key,
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
        raise HTTPException(status_code=400, detail=f"私钥格式错误: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"策略初始化失败: {str(e)}")

    thread = threading.Thread(
        target=_run_eth_trend_in_thread, args=(instance_id, strategy), daemon=True
    )
    ETH_TREND_INSTANCES[instance_id] = strategy
    ETH_TREND_THREADS[instance_id] = thread
    thread.start()

    db = DatabaseManager()
    cfg = json.dumps({"platform": "hyperliquid", "strategy": "eth_trend_short", "symbol": req.symbol}, ensure_ascii=False)
    db.save_user_instance(user["id"], "live", instance_id, cfg)
    logger.info(f"✅ ETH趋势做空策略已启动: {instance_id}")
    return {"ok": True, "instance_id": instance_id, "message": "ETH趋势做空策略已启动"}


@router.post("/eth-trend-short/stop", summary="停止 ETH 趋势做空策略")
def stop_eth_trend_short(user: dict = Depends(require_user)):
    db = DatabaseManager()
    my_ids = set(db.get_user_instance_ids(user["id"], "live"))
    target_ids = [iid for iid in list(ETH_TREND_INSTANCES.keys()) if iid in my_ids]
    if not target_ids:
        # 如果数据库没记录但内存有实例，也一并清除
        target_ids = list(ETH_TREND_INSTANCES.keys())
    if not target_ids:
        return {"ok": True, "message": "没有运行中的ETH趋势做空策略"}

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


# ═══════════════════════════════════════════════════════
#  自适应做多策略  start / stop / status / webhook
# ═══════════════════════════════════════════════════════

class AdaptiveLongStartRequest(BaseModel):
    private_key: Optional[str] = None
    margin_amount: float = 20.0
    leverage: int = 50
    stop_loss_pct: float = 0.03
    take_profit_pct: float = 0.06
    break_even_pct: float = 0.03


def _run_adaptive_long_in_thread(instance_id: str, strategy: AdaptiveLongStrategy):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    ADAPTIVE_LONG_TASKS[instance_id] = loop
    try:
        loop.run_until_complete(strategy.run())
    finally:
        try:
            loop.run_until_complete(strategy.client.close())
        except Exception:
            pass
        loop.close()
        ADAPTIVE_LONG_TASKS.pop(instance_id, None)


@router.post("/adaptive-long/start", summary="启动自适应做多策略")
def start_adaptive_long(req: AdaptiveLongStartRequest, user: dict = Depends(require_user)):
    if ADAPTIVE_LONG_INSTANCES:
        running = [iid for iid, s in ADAPTIVE_LONG_INSTANCES.items() if not s._stop]
        if running:
            return {"ok": False, "message": "自适应做多策略已在运行中，请先停止再启动"}

    private_key = req.private_key or config.hyperliquid.PRIVATE_KEY
    if not private_key:
        raise HTTPException(status_code=400, detail="请提供 Hyperliquid 私钥")

    instance_id = f"al_{datetime.now().strftime('%H%M%S_%f')}"
    try:
        strategy = AdaptiveLongStrategy(
            private_key=private_key,
            instance_id=instance_id,
            margin_amount=req.margin_amount,
            leverage=req.leverage,
            stop_loss_pct=req.stop_loss_pct,
            take_profit_pct=req.take_profit_pct,
            break_even_pct=req.break_even_pct,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"私钥格式错误: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"策略初始化失败: {str(e)}")

    thread = threading.Thread(
        target=_run_adaptive_long_in_thread, args=(instance_id, strategy), daemon=True
    )
    ADAPTIVE_LONG_INSTANCES[instance_id] = strategy
    ADAPTIVE_LONG_THREADS[instance_id] = thread
    thread.start()

    db = DatabaseManager()
    cfg = json.dumps(
        {"platform": "hyperliquid", "strategy": "adaptive_long", "symbol": "动态(Webhook)"},
        ensure_ascii=False
    )
    db.save_user_instance(user["id"], "live", instance_id, cfg)
    logger.info(f"✅ 自适应做多策略已启动: {instance_id}")
    return {"ok": True, "instance_id": instance_id, "message": "自适应做多策略已启动"}


@router.post("/adaptive-long/stop", summary="停止自适应做多策略")
def stop_adaptive_long(user: dict = Depends(require_user)):
    db = DatabaseManager()
    my_ids = set(db.get_user_instance_ids(user["id"], "live"))
    target_ids = [iid for iid in list(ADAPTIVE_LONG_INSTANCES.keys()) if iid in my_ids]
    if not target_ids:
        target_ids = list(ADAPTIVE_LONG_INSTANCES.keys())
    if not target_ids:
        return {"ok": True, "message": "没有运行中的自适应做多策略"}

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


@router.post("/adaptive-long/webhook", summary="接收 TradingView Webhook 信号（自适应做多）")
async def adaptive_long_webhook(request: Request):
    """
    接收 TradingView Webhook 信号，格式:
      {"交易品种":"ETH","操作":"buy","先前仓位大小":"0"}   → 开多
      {"交易品种":"ETH","操作":"sell","先前仓位大小":"0.1"} → 平多
    币种不匹配时 sell 信号自动忽略。
    """
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="无效的 JSON 请求体")

    # 找第一个运行中且已启用的实例
    target_id = None
    for iid, strategy in ADAPTIVE_LONG_INSTANCES.items():
        if strategy.is_enabled and not strategy._stop:
            target_id = iid
            break

    if not target_id:
        raise HTTPException(status_code=404, detail="没有运行中的自适应做多策略实例")

    strategy = ADAPTIVE_LONG_INSTANCES[target_id]

    # 解析信号字段（兼容中文字段名）
    action = (data.get("方向") or data.get("操作") or "").lower().strip()
    symbol_raw = str(data.get("交易品种") or data.get("symbol") or "ETH")
    for suffix in ["USDT", "USD", "PERP", "/USDT", "/USD"]:
        if symbol_raw.upper().endswith(suffix.upper()):
            symbol_raw = symbol_raw[: -len(suffix)]
            break
    signal_symbol = symbol_raw.upper().strip() or "ETH"

    logger.info(f"📡 自适应做多 Webhook: action={action}  symbol={signal_symbol}")

    loop = ADAPTIVE_LONG_TASKS.get(target_id)
    if not loop:
        raise HTTPException(status_code=500, detail="策略事件循环未找到")

    try:
        future = asyncio.run_coroutine_threadsafe(
            strategy.execute_signal(signal_symbol, action),
            loop
        )
        future.result(timeout=10)
        return {
            "ok": True,
            "instance_id": target_id,
            "position": strategy.position,
            "symbol": strategy.symbol,
            "message": f"信号已处理: {action} {signal_symbol}",
        }
    except Exception as e:
        logger.error(f"处理自适应做多 Webhook 信号失败: {e}")
        raise HTTPException(status_code=500, detail=f"信号处理失败: {str(e)}")

