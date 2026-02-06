"""数据大屏 API - 完整迁移"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import List, Optional
import pandas as pd
import math

from backpack_quant_trading.api.deps import require_user


def _safe_float(val, default=0.0):
    """安全转换为 float，处理 None、nan、Decimal 等"""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default
from backpack_quant_trading.config.settings import config
from sqlalchemy import create_engine

router = APIRouter()
engine = create_engine(config.database_url)


@router.get("/summary")
def get_dashboard(exchange: str = "backpack", user: dict = Depends(require_user)):
    """exchange 可为 backpack/deepcoin/ostium 等，默认 backpack"""
    """组合概览、净值曲线、持仓、订单、成交、风险事件"""
    try:
        portfolio_df = pd.read_sql_query(
            f"SELECT * FROM portfolio_history WHERE source = '{exchange}' ORDER BY timestamp DESC LIMIT 100",
            engine
        )
    except Exception:
        portfolio_df = pd.DataFrame()

    try:
        positions_df = pd.read_sql_query(
            f"SELECT * FROM positions WHERE source = '{exchange}' AND closed_at IS NULL",
            engine
        )
    except Exception:
        positions_df = pd.DataFrame()

    try:
        orders_df = pd.read_sql_query(
            f"SELECT * FROM orders WHERE source = '{exchange}' ORDER BY created_at DESC LIMIT 20",
            engine
        )
    except Exception:
        orders_df = pd.DataFrame()

    try:
        trades_df = pd.read_sql_query(
            f"SELECT * FROM trades WHERE source = '{exchange}' ORDER BY created_at DESC LIMIT 20",
            engine
        )
    except Exception:
        trades_df = pd.DataFrame()

    try:
        risk_df = pd.read_sql_query(
            f"SELECT * FROM risk_events WHERE source = '{exchange}' ORDER BY created_at DESC LIMIT 10",
            engine
        )
    except Exception:
        risk_df = pd.DataFrame()

    # 概览
    summary = {}
    if not portfolio_df.empty:
        latest = portfolio_df.iloc[0]
        summary = {
            "portfolio_value": _safe_float(latest.get("portfolio_value")),
            "cash_balance": _safe_float(latest.get("cash_balance")),
            "daily_pnl": _safe_float(latest.get("daily_pnl")),
            "daily_return": _safe_float(latest.get("daily_return")),
        }

    # 净值曲线
    chart_data = []
    if not portfolio_df.empty:
        df_sorted = portfolio_df.sort_values("timestamp")
        for _, row in df_sorted.iterrows():
            chart_data.append({
                "timestamp": str(row["timestamp"]),
                "value": _safe_float(row.get("portfolio_value")),
            })

    # 持仓
    positions = positions_df.to_dict("records") if not positions_df.empty else []
    for p in positions:
        for k, v in p.items():
            if hasattr(v, "item"):
                p[k] = v.item() if hasattr(v, "item") else float(v)

    # 订单
    orders = orders_df.head(8).to_dict("records") if not orders_df.empty else []
    for o in orders:
        for k, v in o.items():
            if hasattr(v, "item"):
                o[k] = v.item() if hasattr(v, "item") else float(v)
            elif hasattr(v, "isoformat"):
                o[k] = str(v)

    # 成交
    trades = trades_df.head(8).to_dict("records") if not trades_df.empty else []
    for t in trades:
        for k, v in t.items():
            if hasattr(v, "item"):
                t[k] = v.item() if hasattr(v, "item") else float(v)
            elif hasattr(v, "isoformat"):
                t[k] = str(v)

    # 风险
    risks = risk_df.head(5).to_dict("records") if not risk_df.empty else []
    for r in risks:
        for k, v in r.items():
            if hasattr(v, "isoformat"):
                r[k] = str(v)

    return {
        "summary": summary,
        "chart": chart_data,
        "positions": positions,
        "orders": orders,
        "trades": trades,
        "risks": risks,
    }
