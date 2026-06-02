import os
import asyncio
import logging
import uvicorn
from fastapi import FastAPI, Request, HTTPException, Header
from typing import Optional, Dict, Any, List
import hmac
import hashlib
from datetime import datetime

from backpack_quant_trading.config.settings import config
from backpack_quant_trading.engine.webhook_trading import WebhookTradingEngine, TradingViewSignal

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler(config.log_dir / "webhook_server.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("WebhookService")

app = FastAPI(title="Ostium TradingView Webhook Service")

# ====== TradingView → AI评分 → 钉钉（实盘筛选） ======
_RECENT_WEBHOOK_EVENTS: List[Dict[str, Any]] = []
_RECENT_LIMIT = 50


def _append_recent_event(evt: Dict[str, Any]) -> None:
    try:
        _RECENT_WEBHOOK_EVENTS.insert(0, evt)
        del _RECENT_WEBHOOK_EVENTS[_RECENT_LIMIT:]
    except Exception:
        pass


def _get_filter_id(payload: dict) -> str:
    return str(
        payload.get("筛选ID")
        or payload.get("filter_id")
        or payload.get("filterId")
        or payload.get("filterID")
        or payload.get("id")
        or payload.get("ID")
        or ""
    ).strip()


def _is_live_trade_payload(payload: dict) -> bool:
    """仅对筛选ID=实盘交易的信号做评分推送。"""
    fid = _get_filter_id(payload)
    return fid == "实盘交易" or fid.lower() == "live_trade"


def _extract_tv_fields(payload: dict) -> tuple[str, str, str, str]:
    """返回 (symbol, action, timeframe, strategy_name)"""
    action = str(
        payload.get("方向")
        or payload.get("操作")
        or payload.get("action")
        or payload.get("signal")
        or ""
    ).lower().strip()
    symbol = str(payload.get("交易品种") or payload.get("symbol") or payload.get("coin") or "").strip()
    tf = str(
        payload.get("周期")
        or payload.get("K线级别")
        or payload.get("timeframe")
        or payload.get("interval")
        or payload.get("tf")
        or ""
    ).strip()
    strategy_name = str(
        payload.get("策略名称")
        or payload.get("strategy_name")
        or payload.get("strategyName")
        or payload.get("strategy")
        or payload.get("strategy_label")
        or ""
    ).strip()
    return symbol, action, tf, strategy_name


def _maybe_schedule_live_trade_score(payload: dict) -> None:
    """后台调度评分与钉钉推送（不影响交易路由）。"""
    if not _is_live_trade_payload(payload):
        return
    try:
        from backpack_quant_trading.core.crypto_signal_scorer import schedule_webhook_dingtalk_score

        symbol, action, tf, strategy_name = _extract_tv_fields(payload)
        if not symbol or not action:
            return
        schedule_webhook_dingtalk_score(
            symbol,
            action,
            timeframe=tf,
            webhook_raw=payload,
            strategy_label=strategy_name or "live_trade",
            strategy_name=strategy_name,
        )
    except Exception as e:
        logger.warning("实盘筛选评分调度失败(忽略): %s", e)


@app.get("/debug/recent-webhooks")
async def debug_recent_webhooks():
    """调试：查看最近收到的 Webhook 与是否命中评分分支。"""
    return {"count": len(_RECENT_WEBHOOK_EVENTS), "items": _RECENT_WEBHOOK_EVENTS[:20]}


# 多引擎实例管理器
# 键: 实例 ID (由 Dashboard 分配)
# 值: WebhookTradingEngine 实例
engine_instances: Dict[str, WebhookTradingEngine] = {}
engine_locks: Dict[str, asyncio.Lock] = {}  # 每个引擎的锁

def verify_signature(payload: bytes, signature: str) -> bool:
    """验证 Webhook 签名"""
    secret = config.webhook.SECRET
    if not secret or secret == "your-secret-key-here":
        return True # 如果没配置密钥，跳过验证 (不推荐)
    
    expected = hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(signature, expected)

@app.on_event("startup")
async def startup_event():
    """启动后台监控任务"""
    logger.info("🚀 Webhook 服务已启动 (v1.1 - 修正 Hyperliquid 响应解析)")
    logger.info("✅ 等待注册引擎实例...")

@app.on_event("shutdown")
async def shutdown_event():
    """关闭所有引擎实例，释放资源"""
    logger.info("🛑 Webhook 服务正在关闭，清理引擎实例...")
    for instance_id, engine in list(engine_instances.items()):
        try:
            if hasattr(engine, 'close'):
                await engine.close()
                logger.info(f"✅ 引擎 {instance_id} 已关闭")
            elif hasattr(engine, 'is_stopped'):
                engine.is_stopped = True
        except Exception as e:
            logger.warning(f"关闭引擎 {instance_id} 时出错: {e}")
    engine_instances.clear()
    engine_locks.clear()
    logger.info("✅ 所有引擎实例已清理")

@app.get("/")
async def root():
    return {
        "service": "Ostium Webhook Service (Multi-Instance)",
        "total_instances": len(engine_instances),
        "instances": {k: {"symbol": v.symbol, "stopped": v.is_stopped} for k, v in engine_instances.items()},
        "timestamp": datetime.now().isoformat()
    }

@app.get("/health")
async def health():
    return {"status": "healthy", "instances": len(engine_instances)}

@app.post("/register_instance")
async def register_instance(request: Request):
    """注册新的引擎实例
    
    请求参数:
    - instance_id: 实例唯一标识符
    - private_key: Ostium 私钥
    - symbol: 交易对
    - leverage: 杠杆倍数
    - margin_amount: 保证金金额或范围
    - stop_loss_ratio: 止损比例 (小数)
    - take_profit_ratio: 止盈比例 (小数)
    - forbidden_hours: 休市时间段 (逗号分隔的小时列表，如 "3,4,5,6,7")
    """
    try:
        data = await request.json()
        instance_id = data.get("instance_id")
        private_key = data.get("private_key")
        strategy_name = data.get("strategy_name", "")  # 新增:策略名
        symbol = data.get("symbol", config.ostium.SYMBOL)
        leverage = data.get("leverage", config.ostium.LEVERAGE)
        margin_amount = data.get("margin_amount")
        stop_loss_ratio = data.get("stop_loss_ratio")
        take_profit_ratio = data.get("take_profit_ratio")
        forbidden_hours_str = data.get("forbidden_hours", "")  # 新增
        
        if not instance_id or not private_key:
            raise HTTPException(status_code=400, detail="instance_id 和 private_key 为必填项")
        
        # --- HYPERLIQUID 扩展分支 (新增) ---
        exchange = data.get("exchange", "ostium").lower()
        if exchange == "hyperliquid":
            if instance_id in engine_instances:
                logger.info(f"🔄 更新 Hyperliquid 实例 {instance_id} 配置")
                engine = engine_instances[instance_id]
                if symbol: engine.symbol = symbol
                if leverage: engine.leverage = int(leverage)
                if stop_loss_ratio is not None: engine.stop_loss_percent = float(stop_loss_ratio)
                if take_profit_ratio is not None: engine.take_profit_percent = float(take_profit_ratio)
                if margin_amount:
                    os.environ[f"WEBHOOK_MARGIN_AMOUNT_{instance_id}"] = str(margin_amount)
                return {"status": "updated", "instance_id": instance_id, "exchange": "hyperliquid"}
            
            logger.info(f"🔧 创建 Hyperliquid 引擎实例: {instance_id}")
            from backpack_quant_trading.engine.hyperliquid_trading import HyperliquidTradingEngine
            from eth_account import Account
            
            engine = HyperliquidTradingEngine(
                private_key=private_key,
                stop_loss_ratio=float(stop_loss_ratio) if stop_loss_ratio is not None else None,
                take_profit_ratio=float(take_profit_ratio) if take_profit_ratio is not None else None
            )
            engine.client.private_key = private_key
            engine.client.account = Account.from_key(private_key)
            engine.client.address = engine.client.account.address
            engine.symbol = symbol
            engine.leverage = int(leverage) if leverage else 50
            engine.instance_id = instance_id
            engine.strategy_name = strategy_name
            engine.source = f"hyperliquid_{instance_id}"
            
            if margin_amount:
                os.environ[f"WEBHOOK_MARGIN_AMOUNT_{instance_id}"] = str(margin_amount)
            
            await engine.initialize()
            if hasattr(engine, 'run_risk_monitor'):
                asyncio.create_task(engine.run_risk_monitor())
            
            engine_instances[instance_id] = engine
            engine_locks[instance_id] = asyncio.Lock()
            logger.info(f"✅ Hyperliquid 引擎实例 {instance_id} 注册成功")
            return {"status": "success", "instance_id": instance_id, "exchange": "hyperliquid"}
        # --- HYPERLIQUID 分支结束 ---

        # 检查实例是否已存在 (以下全部为原有的 Ostium 逻辑)
        if instance_id in engine_instances:
            logger.warning(f"实例 {instance_id} 已存在，将更新配置")
            # 更新现有实例的配置
            engine = engine_instances[instance_id]
            if symbol: engine.symbol = symbol
            if leverage: engine.leverage = leverage
            if stop_loss_ratio is not None: engine.stop_loss_percent = float(stop_loss_ratio)
            if take_profit_ratio is not None: engine.take_profit_percent = float(take_profit_ratio)
            
            # 更新休市时间段
            if forbidden_hours_str:
                try:
                    engine.forbidden_hours = [int(h.strip()) for h in forbidden_hours_str.split(',') if h.strip()]
                    logger.info(f"✅ 更新休市时间段: {engine.forbidden_hours}")
                except Exception as e:
                    logger.error(f"解析休市时间段失败: {e}")
            
            # 更新环境变量 (用于 margin_amount)
            if margin_amount:
                os.environ[f"WEBHOOK_MARGIN_AMOUNT_{instance_id}"] = str(margin_amount)
            
            logger.info(f"✅ 实例 {instance_id} 配置已更新")
            return {
                "status": "updated",
                "instance_id": instance_id,
                "config": {
                    "symbol": engine.symbol,
                    "leverage": engine.leverage,
                    "stop_loss_percent": engine.stop_loss_percent,
                    "take_profit_percent": engine.take_profit_percent,
                    "margin_amount": margin_amount,
                    "forbidden_hours": engine.forbidden_hours
                }
            }
        
        # 创建新引擎实例
        logger.info(f"🔧 创建新引擎实例: {instance_id}")
        
        # 临时设置环境变量
        os.environ["OSTIUM_PRIVATE_KEY"] = private_key
        if margin_amount:
            os.environ[f"WEBHOOK_MARGIN_AMOUNT_{instance_id}"] = str(margin_amount)
        
        # 设置休市时间段环境变量
        if forbidden_hours_str:
            os.environ["OSTIUM_FORBIDDEN_HOURS"] = forbidden_hours_str
        
        # 创建引擎
        engine = WebhookTradingEngine(
            stop_loss_ratio=float(stop_loss_ratio) if stop_loss_ratio is not None else None,
            take_profit_ratio=float(take_profit_ratio) if take_profit_ratio is not None else None
        )
        engine.symbol = symbol
        engine.leverage = leverage
        engine.instance_id = instance_id  # 添加实例 ID 属性
        engine.strategy_name = strategy_name  # 添加策略名属性
        
        # 修改 source 以区分不同实例
        engine.source = f"ostium_{instance_id}"
        
        # 初始化引擎
        await engine.initialize()
        
        # 启动监控任务
        asyncio.create_task(engine.run_risk_monitor())
        asyncio.create_task(engine.run_market_monitor())
        
        # 保存实例
        engine_instances[instance_id] = engine
        engine_locks[instance_id] = asyncio.Lock()
        
        logger.info(f"✅ 引擎实例 {instance_id} 注册成功")
        return {
            "status": "success",
            "instance_id": instance_id,
            "config": {
                "symbol": engine.symbol,
                "leverage": engine.leverage,
                "stop_loss_percent": engine.stop_loss_percent,
                "take_profit_percent": engine.take_profit_percent,
                "margin_amount": margin_amount,
                "forbidden_hours": engine.forbidden_hours
            }
        }
    except Exception as e:
        logger.error(f"注册引擎实例失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/unregister_instance/{instance_id}")
async def unregister_instance(instance_id: str):
    """注销引擎实例"""
    if instance_id not in engine_instances:
        raise HTTPException(status_code=404, detail=f"实例 {instance_id} 不存在")
    
    # 关闭引擎资源
    engine = engine_instances[instance_id]
    try:
        if hasattr(engine, 'close'):
            await engine.close()
        elif hasattr(engine, 'is_stopped'):
            engine.is_stopped = True
    except Exception as e:
        logger.warning(f"关闭引擎 {instance_id} 时出错: {e}")
    
    # 删除实例
    del engine_instances[instance_id]
    if instance_id in engine_locks:
        del engine_locks[instance_id]
    
    # 清理环境变量
    env_key = f"WEBHOOK_MARGIN_AMOUNT_{instance_id}"
    if env_key in os.environ:
        del os.environ[env_key]
    
    logger.info(f"✅ 引擎实例 {instance_id} 已注销")
    return {"status": "success", "message": f"实例 {instance_id} 已注销"}

@app.get("/instances")
async def get_instances():
    """查询已注册的实例列表"""
    return {
        "status": "success",
        "count": len(engine_instances),
        "instances": [
            {
                "instance_id": k,
                "symbol": v.symbol,
                "exchange": "hyperliquid" if "hyperliquid" in v.source else "ostium",
                "strategy": v.strategy_name or "TradingView Signal"
            }
            for k, v in engine_instances.items()
        ]
    }

@app.get("/balance/{instance_id}")
async def get_balance(instance_id: str):
    """查询实例余额"""
    if instance_id not in engine_instances:
        raise HTTPException(status_code=404, detail=f"实例 {instance_id} 不存在")
    
    engine = engine_instances[instance_id]
    
    try:
        balance_raw = await engine.client.get_balance()
        # Ostium 可能返回 tuple/dict（已在 ostium_client 统一为 dict），Hyperliquid 返回 float
        if isinstance(balance_raw, dict):
            balance = float(balance_raw.get("USDC", balance_raw.get("usdc", 0.0)))
        elif isinstance(balance_raw, (tuple, list)) and len(balance_raw) >= 2:
            balance = float(balance_raw[1])  # (collateral, usdc)
        else:
            balance = float(balance_raw)
        return {
            "status": "success",
            "instance_id": instance_id,
            "balance": balance,
            "symbol": engine.symbol
        }
    except Exception as e:
        logger.error(f"查询余额失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/webhook")
async def webhook_unified(request: Request, x_signature: Optional[str] = Header(None)):
    """统一 Webhook 接口 - 支持单实例和广播模式
    
    TradingView 配置 URL: http://127.0.0.1:8005/webhook
    
    两种模式:
    1. 单实例模式: 请求体包含 'instance_id' -> 只路由到指定实例
    2. 广播模式: 请求体不包含 'instance_id' 或为空 -> 广播到所有实例
    """
    body = await request.body()
    
    try:
        data = await request.json()
        # 对「筛选ID=实盘交易」的信号做评分推送（不阻塞）
        live_trade_scoring = False
        scoring_scheduled = False
        if isinstance(data, dict):
            live_trade_scoring = _is_live_trade_payload(data)
            if live_trade_scoring:
                scoring_scheduled = True
            _maybe_schedule_live_trade_score(data)

            sym, act, tf, st_name = _extract_tv_fields(data)
            _append_recent_event(
                {
                    "at": datetime.now().isoformat(timespec="seconds"),
                    "filter_id": _get_filter_id(data),
                    "live_trade_scoring": live_trade_scoring,
                    "scoring_scheduled": scoring_scheduled,
                    "symbol": sym,
                    "action": act,
                    "timeframe": tf,
                    "strategy_name": st_name,
                }
            )
        
        # 从请求体中获取 instance_id
        instance_id = data.get("instance_id")
        
        # 模式 1: 单实例模式
        if instance_id:
            # 检查实例是否存在
            if instance_id not in engine_instances:
                logger.error(f"实例 {instance_id} 不存在")
                raise HTTPException(status_code=404, detail=f"实例 {instance_id} 未注册")
            
            engine = engine_instances[instance_id]
            
            # 验证签名
            if x_signature:
                if not verify_signature(body, x_signature):
                    logger.warning(f"实例 {instance_id} 签名验证失败")
                    raise HTTPException(status_code=401, detail="Invalid signature")
            
            logger.info(f"[实例 {instance_id}] 收到 Webhook 原始数据: {data}")
            signal = TradingViewSignal(**data)
            
            # 异步执行交易（传入原始 payload，供 Hyperliquid 等引擎解析 先前仓位/先前仓位大小）
            asyncio.create_task(engine.execute_signal(signal, data))
            
            return {
                "status": "success",
                "message": "Signal received",
                "instance_id": instance_id,
                "mode": "single",
                "live_trade_scoring": live_trade_scoring,
                "scoring_scheduled": scoring_scheduled,
            }
        
        # 模式 2: 广播模式 (按策略名筛选)
        else:
            if not engine_instances:
                logger.error("没有可用的引擎实例")
                raise HTTPException(status_code=404, detail="没有可用的引擎实例，请先注册实例")
            
            # 验证签名（对所有实例使用相同签名）
            if x_signature:
                if not verify_signature(body, x_signature):
                    logger.warning("广播模式签名验证失败")
                    raise HTTPException(status_code=401, detail="Invalid signature")
            
            # 获取目标策略名
            target_strategy = data.get("strategy_name", "")
            target_symbol = data.get("symbol", "")
            
            logger.info(f"📡 [广播模式] 收到 Webhook 信号: {data}")
            if target_strategy:
                logger.info(f"🎯 [策略筛选] 目标策略: {target_strategy}")
            if target_symbol:
                logger.info(f"🎯 [交易对筛选] 目标交易对: {target_symbol}")
            
            signal = TradingViewSignal(**data)
            
            # 筛选目标实例
            target_instances = {}
            for inst_id, engine in engine_instances.items():
                match = True
                
                # 1. 策略名筛选
                if target_strategy:
                    if not (hasattr(engine, 'strategy_name') and engine.strategy_name == target_strategy):
                        match = False
                
                # 2. 交易对筛选 (可选增强：只有在广播时明确指定了 symbol 才过滤，否则由引擎内部逻辑处理)
                if match and target_symbol:
                    engine_symbol = getattr(engine, 'symbol', '').upper()
                    # 模糊匹配 ETH vs ETH/USD
                    clean_target = target_symbol.split('/')[0].split('-')[0].upper()
                    clean_engine = engine_symbol.split('/')[0].split('-')[0].upper()
                    if clean_target != clean_engine:
                        match = False
                
                if match:
                    target_instances[inst_id] = engine
            
            if not target_instances:
                logger.warning(f"⚠️ 没有找到匹配的实例（策略: {target_strategy}, 交易对: {target_symbol}）")
                return {
                    "status": "success",
                    "message": f"No instances found for strategy '{target_strategy}' and symbol '{target_symbol}'",
                    "mode": "broadcast",
                    "instances": [],
                    "broadcast_count": 0,
                    "live_trade_scoring": live_trade_scoring,
                    "scoring_scheduled": scoring_scheduled,
                }
            
            logger.info(f"📡 [广播模式] 将广播到 {len(target_instances)} 个实例: {list(target_instances.keys())}")
            
            # 广播到筛选后的实例
            broadcast_count = 0
            for inst_id, engine in target_instances.items():
                try:
                    logger.info(f"  → [实例 {inst_id}] 执行信号: {signal.signal}")
                    asyncio.create_task(engine.execute_signal(signal, data))
                    broadcast_count += 1
                except Exception as e:
                    logger.error(f"  ✗ [实例 {inst_id}] 广播失败: {e}")
            
            logger.info(f"✅ [广播模式] 成功广播到 {broadcast_count}/{len(target_instances)} 个实例")
            
            return {
                "status": "success",
                "message": f"Signal broadcasted to {broadcast_count} instances",
                "mode": "broadcast",
                "strategy_filter": target_strategy or "all",
                "instances": list(target_instances.keys()),
                "broadcast_count": broadcast_count
            }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"解析 Webhook 失败: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/webhook/{instance_id}")
async def webhook(instance_id: str, request: Request, x_signature: Optional[str] = Header(None)):
    """接收信号接口 - 支持多实例路由
    
    TradingView 需要配置 URL: http://127.0.0.1:8005/webhook/{instance_id}
    例如: http://127.0.0.1:8005/webhook/ostium_account1
    """
    # 检查实例是否存在
    if instance_id not in engine_instances:
        logger.error(f"实例 {instance_id} 不存在")
        raise HTTPException(status_code=404, detail=f"实例 {instance_id} 未注册")
    
    engine = engine_instances[instance_id]
    
    body = await request.body()
    
    # 验证签名
    if x_signature:
        if not verify_signature(body, x_signature):
            logger.warning(f"实例 {instance_id} 签名验证失败")
            raise HTTPException(status_code=401, detail="Invalid signature")
    
    try:
        data = await request.json()
        logger.info(f"[实例 {instance_id}] 收到 Webhook 原始数据: {data}")
        signal = TradingViewSignal(**data)
        
        # 异步执行交易（传入原始 payload，供 Hyperliquid 等引擎解析 先前仓位/先前仓位大小）
        asyncio.create_task(engine.execute_signal(signal, data))
        
        return {"status": "success", "message": "Signal received", "instance_id": instance_id}
    except Exception as e:
        logger.error(f"[实例 {instance_id}] 解析 Webhook 失败: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/reset/{instance_id}")
async def reset_service(instance_id: str, x_signature: Optional[str] = Header(None), request: Request = None):
    """解除熔断锁定 - 指定实例"""
    if instance_id not in engine_instances:
        raise HTTPException(status_code=404, detail=f"实例 {instance_id} 不存在")
    
    engine = engine_instances[instance_id]
    
    if x_signature:
        body = await request.body()
        if not verify_signature(body, x_signature):
            raise HTTPException(status_code=401, detail="Invalid signature")
            
    if engine.is_stopped:
        engine.is_stopped = False
        engine.last_reset_time = datetime.now().isoformat()
        logger.info(f"♻️ [实例 {instance_id}] 收到重置指令，已解除熔断锁定")
        await engine.send_dingtalk_notification(f"♻️ [实例 {instance_id}] 系统已手动重置，恢复交易。")
        return {"status": "success", "message": "Service reset successful", "instance_id": instance_id}
    return {"status": "info", "message": "Service was not stopped", "instance_id": instance_id}

@app.post("/test/{instance_id}")
async def test_signal(instance_id: str, signal: TradingViewSignal):
    """手动测试信号接口 - 指定实例"""
    if instance_id not in engine_instances:
        raise HTTPException(status_code=404, detail=f"实例 {instance_id} 不存在")
    
    engine = engine_instances[instance_id]
    logger.info(f"[实例 {instance_id}] 收到测试信号: {signal}")
    asyncio.create_task(engine.execute_signal(signal))
    return {"status": "test signal accepted", "instance_id": instance_id}

@app.post("/update_config/{instance_id}")
async def update_config(
    instance_id: str,
    request: Request,
    x_signature: Optional[str] = Header(None)
):
    """动态更新 Webhook 引擎配置（保证金、止盈、止损等）- 指定实例"""
    if instance_id not in engine_instances:
        raise HTTPException(status_code=404, detail=f"实例 {instance_id} 不存在")
    
    engine = engine_instances[instance_id]
    
    # 验证签名（可选）
    if x_signature:
        body = await request.body()
        if not verify_signature(body, x_signature):
            raise HTTPException(status_code=401, detail="Invalid signature")
    
    try:
        data = await request.json()
        updated_fields = []
        
        # 更新保证金范围
        if "margin_amount" in data:
            margin_value = str(data["margin_amount"])
            os.environ[f"WEBHOOK_MARGIN_AMOUNT_{instance_id}"] = margin_value
            updated_fields.append(f"保证金={margin_value}")
            logger.info(f"[实例 {instance_id}] ✅ 更新保证金配置: {margin_value}")
        
        # 更新止损比例
        if "stop_loss_ratio" in data:
            sl_ratio = float(data["stop_loss_ratio"])
            engine.stop_loss_percent = sl_ratio
            updated_fields.append(f"止损={sl_ratio*100}%")
            logger.info(f"[实例 {instance_id}] ✅ 更新止损比例: {sl_ratio*100}%")
        
        # 更新止盈比例
        if "take_profit_ratio" in data:
            tp_ratio = float(data["take_profit_ratio"])
            engine.take_profit_percent = tp_ratio
            updated_fields.append(f"止盈={tp_ratio*100}%")
            logger.info(f"[实例 {instance_id}] ✅ 更新止盈比例: {tp_ratio*100}%")
        
        # 更新杠杆
        if "leverage" in data:
            leverage = int(data["leverage"])
            engine.leverage = leverage
            updated_fields.append(f"杠杆={leverage}x")
            logger.info(f"[实例 {instance_id}] ✅ 更新杠杆: {leverage}x")
        
        # 更新交易对
        if "symbol" in data:
            symbol = str(data["symbol"])
            engine.symbol = symbol
            updated_fields.append(f"交易对={symbol}")
            logger.info(f"[实例 {instance_id}] ✅ 更新交易对: {symbol}")
        
        if not updated_fields:
            return {"status": "warning", "message": "未提供任何配置参数", "instance_id": instance_id}
        
        logger.info(f"[实例 {instance_id}] 🔄 配置更新成功: {', '.join(updated_fields)}")
        return {
            "status": "success",
            "message": "配置更新成功",
            "instance_id": instance_id,
            "updated": updated_fields,
            "current_config": {
                "margin_amount": os.getenv(f"WEBHOOK_MARGIN_AMOUNT_{instance_id}"),
                "stop_loss_percent": engine.stop_loss_percent,
                "take_profit_percent": engine.take_profit_percent,
                "leverage": engine.leverage,
                "symbol": engine.symbol
            }
        }
    except Exception as e:
        logger.error(f"[实例 {instance_id}] 更新配置失败: {e}")
        raise HTTPException(status_code=400, detail=str(e))

# ==================== HYPE 做空策略 Webhook 路由 ====================

from backpack_quant_trading.strategy.hype_adaptive_short import HYPEAdaptiveShortStrategy, TVSignal

# HYPE 策略实例管理（键: instance_id）
hype_instances: Dict[str, HYPEAdaptiveShortStrategy] = {}
hype_threads: Dict[str, "threading.Thread"] = {}

import threading
import asyncio as _asyncio


def _run_hype_in_thread(iid: str, strategy: HYPEAdaptiveShortStrategy):
    loop = _asyncio.new_event_loop()
    _asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(strategy.run())
    finally:
        try:
            loop.run_until_complete(strategy.close())
        except Exception:
            pass
        loop.close()
        hype_instances.pop(iid, None)
        hype_threads.pop(iid, None)


@app.post("/hype/start")
async def hype_start(request: Request):
    """启动 HYPE 做空策略实例

    Body 示例:
    {
      "private_key": "0x...",
      "symbol": "ETH",
      "stop_loss_pct": 0.03,
      "take_profit_pct": 0.06,
      "break_even_pct": 0.03,
      "margin_amount": 20.0,
      "leverage": 50
    }
    """
    try:
        data = await request.json()
        private_key = data.get("private_key") or config.hyperliquid.PRIVATE_KEY
        if not private_key:
            raise HTTPException(status_code=400, detail="请提供 private_key")

        symbol = str(data.get("symbol", "ETH")).upper()
        iid = f"hype_{datetime.now().strftime('%H%M%S_%f')}"

        strategy = HYPEAdaptiveShortStrategy(
            symbol=symbol,
            private_key=private_key,
            instance_id=iid,
            stop_loss_pct=float(data.get("stop_loss_pct", 0.03)),
            take_profit_pct=float(data.get("take_profit_pct", 0.06)),
            break_even_pct=float(data.get("break_even_pct", 0.03)),
            margin_amount=float(data.get("margin_amount", 20.0)),
            leverage=int(data.get("leverage", 50)),
        )

        hype_instances[iid] = strategy
        t = threading.Thread(target=_run_hype_in_thread, args=(iid, strategy), daemon=True)
        hype_threads[iid] = t
        t.start()

        logger.info(f"✅ HYPE 策略实例已启动: {iid} 品种={symbol}")
        return {"status": "ok", "instance_id": iid, "symbol": symbol}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"启动 HYPE 策略失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/hype/webhook")
async def hype_webhook(request: Request):
    """接收 TradingView Webhook 信号。

    路由优先级：
    1. 若本地 hype_instances 有运行中实例（通过 /hype/start 启动），直接处理
    2. 否则代理转发到主 API (http://localhost:8100/api/trading/hype/webhook)

    Body 示例（开空）: {"交易品种":"ETH","操作":"sell","先前仓位大小":"0"}
    Body 示例（平空）: {"交易品种":"ETH","操作":"buy","先前仓位大小":"0.5"}
    """
    try:
        data = await request.json()

        # --- 优先路由到本地 hype_instances ---
        target: Optional[HYPEAdaptiveShortStrategy] = None
        for inst in hype_instances.values():
            if inst.is_enabled:
                target = inst
                break

        if target:
            signal = TVSignal(
                交易品种=data.get("交易品种", data.get("symbol", "ETH")),
                价格=data.get("价格", data.get("price")),
                操作=data.get("操作", data.get("signal", "")),
                仓位方向=data.get("仓位方向"),
                先前仓位大小=str(data.get("先前仓位大小", "0")),
            )
            logger.info(f"📡 [HYPE Webhook 本地] 操作={signal.signal} 品种={signal.symbol}")
            _asyncio.create_task(target.execute_signal(signal, data))
            return {"status": "ok", "signal": signal.signal, "position": target.position, "source": "local"}

        # --- 代理转发到主 API ---
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    "http://localhost:8100/api/trading/hype/webhook",
                    json=data,
                    headers={"Content-Type": "application/json"},
                )
            logger.info(f"📡 [HYPE Webhook 代理→8100] 状态={resp.status_code}")
            return resp.json()
        except Exception as proxy_err:
            logger.error(f"❌ 代理转发失败: {proxy_err}")
            raise HTTPException(
                status_code=503,
                detail=f"本地无运行实例，且代理到主API失败: {proxy_err}。"
                       f"请先通过前端启动策略，或调用 POST /hype/start"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ HYPE Webhook 错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/hype/position")
async def hype_position():
    """查询 HYPE 策略当前持仓"""
    if not hype_instances:
        return {"position": None, "message": "无运行中实例"}
    result = {}
    for iid, inst in hype_instances.items():
        result[iid] = inst.get_status()
    return result


@app.post("/hype/close")
async def hype_close(request: Request):
    """手动平掉所有 HYPE 仓位"""
    data = {}
    try:
        data = await request.json()
    except Exception:
        pass
    iid = data.get("instance_id")

    closed = []
    for inst_id, inst in list(hype_instances.items()):
        if iid and inst_id != iid:
            continue
        if inst.position:
            loop = _asyncio.get_event_loop()
            _asyncio.ensure_future(inst.close_position("手动平仓(webhook_service)"))
            closed.append(inst_id)
    return {"status": "ok", "closed": closed}


@app.post("/hype/stop")
async def hype_stop(request: Request):
    """停止 HYPE 策略实例"""
    data = {}
    try:
        data = await request.json()
    except Exception:
        pass
    iid = data.get("instance_id")

    stopped = []
    for inst_id, inst in list(hype_instances.items()):
        if iid and inst_id != iid:
            continue
        inst._stop = True
        stopped.append(inst_id)
    return {"status": "ok", "stopped": stopped}


# ==================== HYPE做多策略 Webhook 透传 ====================

import aiohttp as _aiohttp


@app.post("/adaptive-long/webhook")
async def adaptive_long_webhook_proxy(request: Request):
    """透传到主 API 8100 的 adaptive-long webhook"""
    body = await request.body()
    try:
        data = await request.json()
        logger.info(f"📥 adaptive-long 收到 Webhook: {data}")
    except Exception as e:
        logger.error(f"📥 adaptive-long JSON 解析失败: {e}, 原始: {body[:200]}")
        raise HTTPException(status_code=400, detail=str(e))
    try:
        async with _aiohttp.ClientSession() as client:
            async with client.post(
                "http://127.0.0.1:8100/api/trading/adaptive-long/webhook",
                json=data,
                headers={"Content-Type": "application/json"},
                timeout=_aiohttp.ClientTimeout(total=10),
            ) as resp:
                result = await resp.json(content_type=None)
                if resp.status >= 400:
                    logger.error(f"❌ adaptive-long webhook 返回错误 {resp.status}: {result}")
                    raise HTTPException(status_code=resp.status, detail=result.get("detail", str(result)))
                return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ adaptive-long webhook 透传失败: {e}")
        raise HTTPException(status_code=503, detail=f"透传失败: {e}")


# ==================== ETH趋势做空策略 Webhook 透传 ====================


@app.post("/eth-trend-short/webhook")
async def eth_trend_short_webhook_proxy(request: Request):
    """透传到主 API 8100 的 eth-trend-short webhook"""
    body = await request.body()
    try:
        data = await request.json()
        logger.info(f"📥 eth-trend-short 收到 Webhook: {data}")
    except Exception as e:
        logger.error(f"📥 eth-trend-short JSON 解析失败: {e}, 原始: {body[:200]}")
        raise HTTPException(status_code=400, detail=str(e))
    try:
        async with _aiohttp.ClientSession() as client:
            async with client.post(
                "http://127.0.0.1:8100/api/trading/eth-trend-short/webhook",
                json=data,
                headers={"Content-Type": "application/json"},
                timeout=_aiohttp.ClientTimeout(total=10),
            ) as resp:
                result = await resp.json(content_type=None)
                if resp.status >= 400:
                    logger.error(f"❌ eth-trend-short webhook 返回错误 {resp.status}: {result}")
                    raise HTTPException(status_code=resp.status, detail=result.get("detail", str(result)))
                return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ eth-trend-short webhook 透传失败: {e}")
        raise HTTPException(status_code=503, detail=f"透传失败: {e}")


# ==================== 主入口 ====================

def main():
    host = config.webhook.HOST
    port = config.webhook.PORT
    logger.info(f"正在启动 Webhook 服务于 {host}:{port}")
    uvicorn.run(app, host=host, port=port)

if __name__ == "__main__":
    main()
