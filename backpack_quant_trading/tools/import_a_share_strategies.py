#!/usr/bin/env python3
"""导入 A 股量化实盘策略（2026+ 交易 + 2H K 线）到数据库。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backpack_quant_trading.core.a_share_strategy_import import import_all_a_share_strategies


def main() -> None:
    result = import_all_a_share_strategies()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("ok"):
        sys.exit(1)


if __name__ == "__main__":
    main()
