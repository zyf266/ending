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
    title="Backpack 量化交易终端 API",
    description="FastAPI 后端服务",
    version="1.0.0",
)

# CORS - 允许 Vue 前端跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000", "http://localhost:8050", "http://127.0.0.1:8050", "http://0.0.0.0:8050"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
from backpack_quant_trading.api.routers import auth, trading, grid, currency_monitor, dashboard, ai_lab

app.include_router(auth.router, prefix="/api/auth", tags=["认证"])
app.include_router(trading.router, prefix="/api/trading", tags=["实盘交易"])
app.include_router(grid.router, prefix="/api/grid", tags=["网格交易"])
app.include_router(currency_monitor.router, prefix="/api/currency-monitor", tags=["币种监视"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["数据大屏"])
app.include_router(ai_lab.router, prefix="/api/ai-lab", tags=["AI实验室"])


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "backpack-quant-api"}


# 生产构建后挂载 Vue 静态文件（开发时前端单独运行在 5173，通过 Vite 代理 /api）
frontend_dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
