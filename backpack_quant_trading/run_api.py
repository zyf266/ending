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
    os.environ.setdefault("DEEPSEEK_SCORE_MODEL", "deepseek-v4-flash")
    os.environ.setdefault("DEEPSEEK_SCORE_THINKING", "0")
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root))
    from backpack_quant_trading.core.env_loader import load_project_env

    load_project_env()
    # 本机开发默认关闭加密评分，避免与服务器共用 Key；服务器 export TRADING_SERVER=1
    if os.getenv("TRADING_SERVER", "").strip().lower() not in ("1", "true", "yes"):
        os.environ.setdefault("CRYPTO_SCORE_ENABLED", "0")

    import logging
    from backpack_quant_trading.config.settings import config
    from backpack_quant_trading.utils.logger import setup_logger

    setup_logger(log_dir=config.log_dir, level=logging.INFO)
    from backpack_quant_trading.core.crypto_signal_scorer import log_score_runtime_config

    log_score_runtime_config()

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
            reload=False,
            access_log=False,
        )
    except KeyboardInterrupt:
        print("\n服务已停止")
        sys.exit(0)
