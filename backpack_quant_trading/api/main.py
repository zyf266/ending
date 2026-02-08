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
        break
