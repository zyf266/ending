"""
FastAPI 量化交易后端
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

app = FastAPI(
    title="沐龙量化交易平台 API",
    description="实盘交易、策略回测、AI 实验室、OKX Agent 集成、网格与监控",
    version="1.0.0",
)

# CORS - 允许 Vue 前端跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:3000", "http://localhost:8050", "http://localhost:8051",
        "http://127.0.0.1:8050", "http://127.0.0.1:8051",
        "http://0.0.0.0:8050", "http://0.0.0.0:8051",
        "http://47.110.57.118:8050", "http://47.110.57.118:8051",
        "http://172.26.30.20:8050", "http://172.26.30.20:8051",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
from backpack_quant_trading.api.routers import auth, trading, grid, currency_monitor, dashboard, ai_lab, stock_ai, strategy, okx_agent, okx_console

app.include_router(auth.router, prefix="/api/auth", tags=["认证"])
app.include_router(trading.router, prefix="/api/trading", tags=["实盘交易"])
app.include_router(grid.router, prefix="/api/grid", tags=["网格交易"])
app.include_router(currency_monitor.router, prefix="/api/currency-monitor", tags=["币种监视"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["数据大屏"])
app.include_router(ai_lab.router, prefix="/api/ai-lab", tags=["AI实验室"])
app.include_router(stock_ai.router, prefix="/api/stock-ai", tags=["A股AI选股"])
app.include_router(strategy.router, prefix="/api/strategy", tags=["量化策略"])
app.include_router(okx_agent.router, prefix="/api/okx-agent", tags=["OKX AI 交易"])
app.include_router(okx_console.router, prefix="/api/okx-console", tags=["OKX 控制台"])


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "backpack-quant-api"}


# ──────────────────────────────────────────────────────────
# 每日凌晨2点 自动同步 HYPE 4H / ETH 2H K 线
# ──────────────────────────────────────────────────────────
import asyncio as _asyncio
import logging as _sched_logging
from datetime import datetime as _dt, timedelta as _td

_sched_logger = _sched_logging.getLogger("kline_scheduler")


@app.on_event("startup")
async def start_kline_scheduler():
    _asyncio.create_task(_daily_kline_sync_loop())


async def _daily_kline_sync_loop():
    """每天凌晨2:00 自动从 Hyperliquid 同步 HYPE 4H 和 ETH 2H K 线。"""
    from backpack_quant_trading.api.routers.strategy import sync_hype_klines_hl, sync_eth_klines_hl
    while True:
        now = _dt.now()
        target = now.replace(hour=2, minute=0, second=0, microsecond=0)
        if target <= now:
            target += _td(days=1)
        wait_secs = (target - now).total_seconds()
        _sched_logger.info(f"[K线定时] 下次同步于 {target.strftime('%Y-%m-%d %H:%M:%S')}，等待 {wait_secs/3600:.1f}h")
        await _asyncio.sleep(wait_secs)
        # 同步 HYPE
        try:
            r1 = await _asyncio.to_thread(sync_hype_klines_hl)
            _sched_logger.info(f"[K线定时] HYPE 4H 同步完成: {r1}")
        except Exception as exc:
            _sched_logger.error(f"[K线定时] HYPE 4H 同步失败: {exc}")
        # 同步 ETH
        try:
            r2 = await _asyncio.to_thread(sync_eth_klines_hl)
            _sched_logger.info(f"[K线定时] ETH 2H 同步完成: {r2}")
        except Exception as exc:
            _sched_logger.error(f"[K线定时] ETH 2H 同步失败: {exc}")


# ── HYPE 策略 Webhook 快捷入口（无需 /api/trading 前缀，供 TradingView 直接调用）──
from fastapi import Request as _Request
from fastapi.responses import JSONResponse as _JSONResponse
from backpack_quant_trading.api.routers.trading import HYPE_STRATEGY_INSTANCES, WebhookSignal


@app.post("/hype/webhook", tags=["HYPE Webhook"])
async def hype_webhook_shortcut(request: _Request):
    """TradingView Webhook 快捷入口，策略启动后立即可用。

    开空: POST /hype/webhook  {"交易品种":"ETH","操作":"sell","先前仓位大小":"0"}
    平空: POST /hype/webhook  {"交易品种":"ETH","操作":"buy","先前仓位大小":"0.5"}
    """
    try:
        data = await request.json()

        # 找到第一个运行中的 HYPE 实例
        target_id = None
        for iid, strategy in HYPE_STRATEGY_INSTANCES.items():
            if strategy.is_enabled:
                target_id = iid
                break

        if not target_id:
            return _JSONResponse(
                {"status": "error", "message": "没有运行中的 HYPE 策略，请先从前端启动"},
                status_code=404,
            )

        strategy = HYPE_STRATEGY_INSTANCES[target_id]

        # 直接从 dict 读取，避免中文字段名 Pydantic 解析失败
        action = (data.get("方向") or data.get("操作") or data.get("signal") or "").lower().strip()
        price_raw = data.get("成交价格") or data.get("价格") or data.get("price")
        try:
            price = float(price_raw) if price_raw is not None else None
        except (ValueError, TypeError):
            price = None
        symbol_raw = str(data.get("交易品种") or data.get("symbol") or "ETH")
        for suffix in ["USDT", "USD", "PERP", "/USDT", "/USD"]:
            if symbol_raw.upper().endswith(suffix.upper()):
                symbol_raw = symbol_raw[: -len(suffix)]
                break
        symbol = symbol_raw.upper().strip() or "ETH"
        prev_size = str(data.get("先前仓位大小") or "")
        if not prev_size:
            prev_size = "1" if strategy.position == "SHORT" else "0"

        import asyncio as _asyncio
        from backpack_quant_trading.strategy.hype_adaptive_short import TVSignal
        signal = TVSignal(
            交易品种=symbol,
            价格=price,
            操作=action,
            仓位方向=data.get("仓位方向"),
            先前仓位大小=prev_size,
        )

        from backpack_quant_trading.api.routers.trading import HYPE_STRATEGY_TASKS
        loop = HYPE_STRATEGY_TASKS.get(target_id)
        if loop:
            future = _asyncio.run_coroutine_threadsafe(
                strategy.execute_signal(signal, data), loop
            )
            future.result(timeout=5)
        else:
            _asyncio.ensure_future(strategy.execute_signal(signal, data))

        return {"status": "ok", "signal": action, "instance_id": target_id}

    except Exception as e:
        return _JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@app.get("/hype/position", tags=["HYPE Webhook"])
def hype_position_shortcut():
    """查询 HYPE 策略当前持仓"""
    result = {}
    for iid, strategy in HYPE_STRATEGY_INSTANCES.items():
        result[iid] = strategy.get_status()
    return result if result else {"position": None, "message": "无运行中实例"}


# 生产构建后挂载 Vue 静态文件
# 尝试多个可能路径（兼容不同启动方式）
_pkg_dir = Path(__file__).resolve().parents[1]
_cwd_dir = Path.cwd()
for base in (_pkg_dir, _cwd_dir, _cwd_dir / "backpack_quant_trading"):
    frontend_dist = base / "frontend" / "dist"
    if frontend_dist.exists() and (frontend_dist / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=str(frontend_dist / "assets")), name="frontend-assets")
        # SPA 根及子路由：返回 index.html
        from fastapi.responses import FileResponse
        _dist = str(frontend_dist)
        @app.get("/")
        def _index():
            return FileResponse(frontend_dist / "index.html")
        @app.get("/login")
        def _login():
            return FileResponse(frontend_dist / "index.html")
        @app.get("/trading")
        def _trading():
            return FileResponse(frontend_dist / "index.html")
        @app.get("/dashboard")
        def _dashboard():
            return FileResponse(frontend_dist / "index.html")
        @app.get("/ai-lab")
        def _ai_lab():
            return FileResponse(frontend_dist / "index.html")
        @app.get("/grid-trading")
        def _grid():
            return FileResponse(frontend_dist / "index.html")
        @app.get("/currency-monitor")
        def _monitor():
            return FileResponse(frontend_dist / "index.html")
        @app.get("/stock-ai")
        def _stock_ai():
            return FileResponse(frontend_dist / "index.html")
        @app.get("/okx-agent")
        def _okx_agent():
            return FileResponse(frontend_dist / "index.html")
        @app.get("/okx-console")
        def _okx_console():
            return FileResponse(frontend_dist / "index.html")
        break
