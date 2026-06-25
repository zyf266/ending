#!/usr/bin/env python
"""生成 MU 美光科技 strategy_backtest_trade INSERT SQL（100万美金复利）。"""
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backpack_quant_trading.core.a_share_strategy_import import recompound_trades_from_csv

CSV = ROOT / "美光.csv"
OUT = ROOT / "MU_insert.sql"

SN, SYM, TF = "MU_KLINE", "MUUSDT", "2H"
CAP = 1_000_000

rows = recompound_trades_from_csv(
    CSV,
    initial_capital=CAP,
    trade_start=datetime(2026, 1, 1, 0, 0),
)
trade_nos = sorted({r["trade_no"] for r in rows})
final = rows[-1]["cum_pnl"] + CAP
lines = [
    f"-- 先删旧数据",
    f"DELETE FROM strategy_backtest_trade WHERE strategy_name='{SN}' AND symbol='{SYM}' AND timeframe='{TF}';",
    "",
]
for r in rows:
    tt = r["trade_time"].strftime("%Y-%m-%d %H:%M:%S")
    sig = (r.get("signal") or "").replace("'", "''")
    lines.append(
        "INSERT INTO strategy_backtest_trade "
        "(strategy_name,symbol,timeframe,trade_no,trade_type,`signal`,trade_time,price,"
        "position_qty,position_value,pnl,pnl_pct,runup,runup_pct,drawdown,drawdown_pct,cum_pnl,cum_pnl_pct) VALUES "
        f"('{SN}','{SYM}','{TF}',{r['trade_no']},'{r['trade_type']}','{sig}','{tt}',"
        f"{r['price']},{r['position_qty']},{r['position_value']},{r['pnl']},{r['pnl_pct']},"
        f"{r['runup']},{r['runup_pct']},{r['drawdown']},{r['drawdown_pct']},{r['cum_pnl']},{r['cum_pnl_pct']});"
    )
lines.append("")
lines.append(f"-- 共 {len(trade_nos)} 笔完整交易, {len(rows)} 条记录, 期末资金 {final:.2f}")
OUT.write_text("\n".join(lines), encoding="utf-8")
print(OUT)
print(f"trades={len(trade_nos)} rows={len(rows)} final={final:.2f}")
