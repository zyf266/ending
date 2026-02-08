#!/usr/bin/env python
"""启动 FastAPI 后端（开发模式）"""
import sys
import uvicorn
from pathlib import Path

if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root))
    uvicorn.run(
        "backpack_quant_trading.api.main:app",
        host="0.0.0.0",
        port=8100,
        reload=True,
    )
