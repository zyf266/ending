"""统一加载 backpack_quant_trading/.env（CLI / 脚本未走 run_api 时也生效）。"""
from __future__ import annotations

from pathlib import Path

_LOADED = False
_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def load_project_env(*, override: bool = False) -> None:
    global _LOADED
    if _LOADED and not override:
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    if _ENV_PATH.is_file():
        load_dotenv(_ENV_PATH, override=override)
    _LOADED = True
