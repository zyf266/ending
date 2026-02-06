"""网格交易 API"""
import json
import time
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from backpack_quant_trading.api.deps import require_user


def _resolve_symbol(user_input: str, exchange: str) -> str:
    """将简写（如 ETH、BTC）解析为交易所完整交易对格式"""
    s = (user_input or "").strip().upper()
    if not s:
        return user_input or ""
    if "_PERP" in s or "-SWAP" in s or "-PERP" in s:
        return s
    if "_" in s:
        return s
    if "-" in s and len(s) > 6:
        return s
    if "/" in s:
        base = s.split("/")[0]
    else:
        base = s
    if exchange == "backpack":
        return f"{base}_USDC_PERP"
    if exchange == "deepcoin":
        return f"{base}-USDT-SWAP"
    if exchange == "ostium":
        return f"{base}-USD"
    if exchange in ("hyper", "hip3", "hip3_testnet"):
        return base
    return s
from backpack_quant_trading.database.models import DatabaseManager
from backpack_quant_trading.strategy.grid_strategy import grid_manager
from backpack_quant_trading.config.settings import config

router = APIRouter()


def _create_api_client(exchange: str, api_key: str = "", secret_key: str = "", passphrase: str = "", private_key: str = ""):
    """创建交易所客户端"""
    _ak = (api_key or "").strip()
    _sk = (secret_key or "").strip()
    if exchange == "backpack":
        from backpack_quant_trading.core.api_client import BackpackAPIClient
        return BackpackAPIClient(
            access_key=_ak or config.backpack.ACCESS_KEY,
            refresh_key=_sk or config.backpack.REFRESH_KEY,
            use_cookie_only=False,
            ed25519_public_key=_ak or None,
            ed25519_private_key=_sk or None,
        )
    elif exchange == "deepcoin":
        from backpack_quant_trading.core.deepcoin_client import DeepcoinAPIClient
        return DeepcoinAPIClient(
            api_key=_ak or config.deepcoin.API_KEY,
            secret_key=_sk or config.deepcoin.SECRET_KEY,
            passphrase=(passphrase or "").strip() or config.deepcoin.PASSPHRASE,
        )
    elif exchange in ("ostium", "hyper", "hip3", "hip3_testnet"):
        from backpack_quant_trading.core.hyperliquid_client import HyperliquidAPIClient
        base = "https://api.hyperliquid-testnet.xyz" if exchange == "hip3_testnet" else "https://api.hyperliquid.xyz"
        cfg_pk = getattr(config.hyperliquid, "PRIVATE_KEY", "") if hasattr(config, "hyperliquid") else ""
        return HyperliquidAPIClient(private_key=(private_key or "").strip() or cfg_pk or None, base_url=base)
    raise ValueError(f"不支持的交易所: {exchange}")


class GridStartRequest(BaseModel):
    exchange: str = "backpack"
    symbol: str = "ETH_USDC_PERP"
    price_lower: float = 2000
    price_upper: float = 2500
    grid_count: int = 5
    investment_per_grid: float = 10
    leverage: int = 10
    grid_mode: str = "short_only"
    api_key: Optional[str] = None
    secret_key: Optional[str] = None
    passphrase: Optional[str] = None
    private_key: Optional[str] = None


@router.get("/symbols")
def get_symbols():
    """获取交易对列表（可扩展）"""
    return {"symbols": ["ETH_USDC_PERP", "BTC_USDC_PERP", "PAXG_USDC_PERP", "SOL_USDC_PERP"]}


@router.get("/status")
def get_status(user: dict = Depends(require_user)):
    """运行中的网格实例（仅当前用户）"""
    all_grids = grid_manager.get_all()
    db = DatabaseManager()
    my_ids = set(db.get_user_instance_ids(user["id"], "grid"))
    filtered = {k: v for k, v in all_grids.items() if k in my_ids}
    return {"grids": [{"id": k, **v} for k, v in filtered.items()]}


@router.post("/start")
def start_grid(req: GridStartRequest, user: dict = Depends(require_user)):
    """启动网格"""
    try:
        symbol = _resolve_symbol(req.symbol or "", req.exchange or "backpack")
        api_client = _create_api_client(
            req.exchange,
            req.api_key or "",
            req.secret_key or "",
            req.passphrase or "",
            req.private_key or "",
        )
        data_client = None
        if req.exchange not in ("hyper", "hip3", "hip3_testnet"):
            from backpack_quant_trading.core.api_client import BackpackAPIClient
            data_client = BackpackAPIClient(public_only=True)
        instance_id = f"inst_{int(time.time())}"
        ok, msg = grid_manager.add_and_start(
            symbol=symbol,
            price_lower=req.price_lower,
            price_upper=req.price_upper,
            grid_count=req.grid_count,
            investment_per_grid=req.investment_per_grid,
            leverage=req.leverage,
            api_client=api_client,
            data_client=data_client,
            grid_mode=req.grid_mode or "short_only",
            exchange=req.exchange,
            instance_id=instance_id,
        )
        if ok:
            cfg = json.dumps({"symbol": symbol, "grid_mode": req.grid_mode, "exchange": req.exchange})
            db = DatabaseManager()
            db.save_user_instance(user["id"], "grid", instance_id, cfg)
            return {"ok": True, "instance_id": instance_id}
        return {"ok": False, "message": str(msg)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stop/{grid_id}")
def stop_grid(grid_id: str, user: dict = Depends(require_user)):
    """停止单个网格"""
    db = DatabaseManager()
    my_ids = db.get_user_instance_ids(user["id"], "grid")
    if grid_id not in my_ids:
        raise HTTPException(status_code=403, detail="无权操作该实例")
    grid_manager.stop(grid_id)
    db.delete_user_instance(user["id"], "grid", grid_id)
    return {"message": "ok"}


@router.post("/stop-all")
def stop_all(user: dict = Depends(require_user)):
    """停止当前用户全部网格"""
    db = DatabaseManager()
    my_ids = db.get_user_instance_ids(user["id"], "grid")
    for gid in my_ids:
        grid_manager.stop(gid)
        db.delete_user_instance(user["id"], "grid", gid)
    return {"message": "ok"}
