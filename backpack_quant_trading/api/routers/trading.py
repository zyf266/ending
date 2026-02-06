"""实盘交易 API - 完整迁移"""
import os
import sys
import json
import socket
import subprocess
import requests
import psutil
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backpack_quant_trading.api.deps import require_user
from backpack_quant_trading.database.models import DatabaseManager
from backpack_quant_trading.main import STRATEGY_REGISTRY, STRATEGY_DISPLAY_NAMES

router = APIRouter()
WEBHOOK_PORT = 8005
# api/routers/trading.py -> api -> backpack_quant_trading -> project root
PROJECT_ROOT = Path(__file__).resolve().parents[3]


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
        "strategies": [{"value": k, "label": STRATEGY_DISPLAY_NAMES.get(k, k)} for k in STRATEGY_REGISTRY.keys()],
        "exchanges": [
            {"value": "backpack", "label": "Backpack"},
            {"value": "deepcoin", "label": "Deepcoin"},
            {"value": "ostium", "label": "Ostium"},
            {"value": "hyperliquid", "label": "Hyperliquid"},
        ],
    }


@router.get("/instances")
def list_instances(user: dict = Depends(require_user)):
    """当前用户的实盘实例（含 Webhook 恢复）"""
    db = DatabaseManager()
    my_ids = set(db.get_user_instance_ids(user["id"], "live"))
    if not my_ids:
        return {"instances": []}

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


@router.post("/launch")
def launch_strategy(req: LaunchRequest, user: dict = Depends(require_user)):
    """启动实盘策略"""
    user_id = user["id"]
    db = DatabaseManager()

    # 解析交易对：ETH/BTC 等简写 -> 交易所完整格式
    symbol = _resolve_symbol(req.symbol or "", req.platform)

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
        "--take-profit", str((req.take_profit or 2) / 100),
        "--stop-loss", str((req.stop_loss or 1.5) / 100),
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
    log_dir = PROJECT_ROOT / "backpack_quant_trading" / "log"
    lines = []
    for fname in ["webhook_server.log", "live_console.log"]:
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
