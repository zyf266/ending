#!/usr/bin/env python
"""启动 FastAPI 后端（开发模式）"""
import os
import signal
import sys
import uvicorn
from pathlib import Path

if __name__ == "__main__":
    # 开启 OKX 操作台交易能力（下单/撤单等）；不设则仅允许查询
    os.environ.setdefault("ENABLE_OKX_TRADE", "true")
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root))

    def _on_sigint(*_):
        print("\n服务已停止")
        sys.exit(0)
    signal.signal(signal.SIGINT, _on_sigint)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _on_sigint)

    try:
        uvicorn.run(
            "backpack_quant_trading.api.main:app",
            host="0.0.0.0",
            port=8100,
            reload=True,
        )
    except KeyboardInterrupt:
        print("\n服务已停止")
        sys.exit(0)
