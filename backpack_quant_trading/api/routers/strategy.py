from datetime import datetime, timezone, date as _date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from decimal import Decimal as PyDecimal
import time as _time
import logging as _logging
import requests as _requests

_hl_logger = _logging.getLogger(__name__)

# 每天只同步一次 ETH K 线，避免每次请求都连币安
_eth_kline_last_sync_date: _date = None

import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import Column, Integer, String, DateTime, Numeric, Index
from sqlalchemy.orm import declarative_base

from backpack_quant_trading.database.models import db_manager
from backpack_quant_trading.core.binance_monitor import (
    fetch_binance_klines,
    fetch_binance_klines_batch,
    fetch_binance_klines_from_start,
)

router = APIRouter()

# ──────────────────────────────────────────────────────────
# Hyperliquid K 线工具函数
# ──────────────────────────────────────────────────────────
from backpack_quant_trading.core.hyperliquid_klines import fetch_hl_klines_sync


def _bulk_insert_klines_dicts(rows_data: list) -> None:
    """用 SQLAlchemy Core engine.connect() 批量写入 K 线。
    直接走引擎连接，完全绕过 ORM Session，确保 MySQL autoincrement 正常赋 id。
    """
    if not rows_data:
        return
    # 补上 created_at（ORM default 在 Core insert 里不生效）
    now = datetime.now()
    for row in rows_data:
        row.setdefault("created_at", now)
    with db_manager.engine.connect() as conn:
        conn.execute(StrategyKline.__table__.insert(), rows_data)
        conn.commit()


def sync_hype_klines_hl() -> dict:
    """从 Hyperliquid 增量同步 HYPE 4H K 线到数据库。"""
    session = db_manager.get_session()
    try:
        last = (
            session.query(StrategyKline)
            .filter_by(strategy_name=STRATEGY_NAME, symbol=SYMBOL, timeframe=TIMEFRAME)
            .order_by(StrategyKline.timestamp.desc())
            .first()
        )
        last_ts = last.timestamp if (last and last.timestamp) else None
    finally:
        session.close()

    now_ms = int(_time.time() * 1000)
    if last_ts is None:
        start_ms = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    else:
        start_ms = int(last_ts.replace(tzinfo=timezone.utc).timestamp() * 1000) + 1

    bars = fetch_hl_klines_sync("HYPE", "4h", start_ms, now_ms)
    if not bars:
        return {"inserted": 0, "source": "hyperliquid"}

    rows = []
    for bar in bars:
        ts = datetime.fromtimestamp(bar["t"] / 1000)
        if last_ts and ts <= last_ts:
            continue
        rows.append({
            "strategy_name": STRATEGY_NAME, "symbol": SYMBOL, "timeframe": TIMEFRAME,
            "timestamp": ts,
            "open": PyDecimal(str(bar["o"])), "high": PyDecimal(str(bar["h"])),
            "low": PyDecimal(str(bar["l"])),  "close": PyDecimal(str(bar["c"])),
            "volume": PyDecimal(str(bar["v"])), "source": "hyperliquid",
        })

    _bulk_insert_klines_dicts(rows)
    _hl_logger.info(f"[HL K线] HYPE 4H 写入 {len(rows)} 条")
    return {"inserted": len(rows), "source": "hyperliquid"}


def sync_eth_klines_hl() -> dict:
    """从 Hyperliquid 增量同步 ETH 2H K 线到数据库。"""
    session = db_manager.get_session()
    try:
        last = (
            session.query(StrategyKline)
            .filter_by(strategy_name=ETH_ONLY_STRATEGY_NAME, symbol=ETH_ONLY_SYMBOL, timeframe=ETH_ONLY_TIMEFRAME)
            .order_by(StrategyKline.timestamp.desc())
            .first()
        )
        last_ts = last.timestamp if (last and last.timestamp) else None
    finally:
        session.close()

    now_ms = int(_time.time() * 1000)
    if last_ts is None:
        start_ms = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    else:
        start_ms = int(last_ts.replace(tzinfo=timezone.utc).timestamp() * 1000) + 1

    bars = fetch_hl_klines_sync("ETH", "2h", start_ms, now_ms)
    if not bars:
        return {"inserted": 0, "source": "hyperliquid"}

    rows = []
    for bar in bars:
        ts = datetime.fromtimestamp(bar["t"] / 1000)
        if last_ts and ts <= last_ts:
            continue
        rows.append({
            "strategy_name": ETH_ONLY_STRATEGY_NAME, "symbol": ETH_ONLY_SYMBOL, "timeframe": ETH_ONLY_TIMEFRAME,
            "timestamp": ts,
            "open": PyDecimal(str(bar["o"])), "high": PyDecimal(str(bar["h"])),
            "low": PyDecimal(str(bar["l"])),  "close": PyDecimal(str(bar["c"])),
            "volume": PyDecimal(str(bar["v"])), "source": "hyperliquid",
        })

    _bulk_insert_klines_dicts(rows)
    _hl_logger.info(f"[HL K线] ETH 2H 写入 {len(rows)} 条")
    return {"inserted": len(rows), "source": "hyperliquid"}


def _get_last_kline_timestamp(strategy_name: str, symbol: str, timeframe: str) -> Optional[datetime]:
    session = db_manager.get_session()
    try:
        last = (
            session.query(StrategyKline)
            .filter_by(strategy_name=strategy_name, symbol=symbol, timeframe=timeframe)
            .order_by(StrategyKline.timestamp.desc())
            .first()
        )
        return last.timestamp if (last and last.timestamp) else None
    finally:
        session.close()


def _is_kline_stale(strategy_name: str, symbol: str, timeframe: str, max_age_hours: float) -> bool:
    last_ts = _get_last_kline_timestamp(strategy_name, symbol, timeframe)
    if last_ts is None:
        return True
    if last_ts.tzinfo:
        last_ts = last_ts.replace(tzinfo=None)
    age = (datetime.now() - last_ts).total_seconds()
    return age > max(1.0, float(max_age_hours)) * 3600


def sync_us_stock_klines_massive(
    strategy_name: str,
    symbol: str,
    timeframe: str,
    ticker: str,
    massive_interval: str,
) -> dict:
    """从 Massive/Polygon 增量同步美股 K 线到 strategy_kline 表。"""
    from backpack_quant_trading.core.massive_klines import (
        fetch_massive_bars,
        get_massive_api_key,
        interval_label,
        normalize_us_ticker,
    )

    if not get_massive_api_key():
        return {"inserted": 0, "source": "massive", "error": "未配置 MASSIVE_API_KEY"}

    sym = normalize_us_ticker(ticker)
    iv = interval_label(massive_interval or timeframe)
    last_ts = _get_last_kline_timestamp(strategy_name, symbol, timeframe)

    bars = fetch_massive_bars(sym, iv, limit=5000)
    if not bars:
        return {"inserted": 0, "source": "massive", "ticker": sym, "interval": iv}

    rows = []
    for bar in bars:
        ts = datetime.fromtimestamp(int(bar["time"]) / 1000)
        if last_ts:
            cmp_ts = last_ts.replace(tzinfo=None) if last_ts.tzinfo else last_ts
            if ts <= cmp_ts:
                continue
        rows.append({
            "strategy_name": strategy_name,
            "symbol": symbol,
            "timeframe": timeframe,
            "timestamp": ts,
            "open": PyDecimal(str(bar["open"])),
            "high": PyDecimal(str(bar["high"])),
            "low": PyDecimal(str(bar["low"])),
            "close": PyDecimal(str(bar["close"])),
            "volume": PyDecimal(str(bar["volume"])),
            "source": "massive",
        })

    _bulk_insert_klines_dicts(rows)
    _hl_logger.info("[Massive K线] %s %s 写入 %s 条", sym, iv, len(rows))
    return {"inserted": len(rows), "source": "massive", "ticker": sym, "interval": iv}


_US_STOCK_KLINE_SPECS: Tuple[Dict[str, str], ...] = (
    {"strategy_name": "NVDA_KLINE", "symbol": "NVDAUSDT", "timeframe": "2H", "ticker": "NVDA", "massive_interval": "2h"},
    {"strategy_name": "INTC_KLINE", "symbol": "INTCUSDT", "timeframe": "1H", "ticker": "INTC", "massive_interval": "1h"},
)


def run_scheduled_kline_sync() -> dict:
    """定时任务：加密 HL + 美股 Massive + A股 2H（Yahoo/东方财富）。"""
    from backpack_quant_trading.core.a_share_strategy_import import run_a_share_kline_sync

    result: Dict[str, Any] = {
        "hype_4h": sync_hype_klines_hl(),
        "eth_2h": sync_eth_klines_hl(),
    }
    for spec in _US_STOCK_KLINE_SPECS:
        key = str(spec.get("ticker") or "").lower()
        try:
            result[key] = sync_us_stock_klines_massive(
                spec["strategy_name"],
                spec["symbol"],
                spec["timeframe"],
                spec["ticker"],
                spec["massive_interval"],
            )
        except Exception as exc:
            result[key] = {"inserted": 0, "source": "massive", "error": str(exc)}
    try:
        result["a_share_2h"] = run_a_share_kline_sync()
    except Exception as exc:
        result["a_share_2h"] = {"error": str(exc)}
    return result


STRATEGY_NAME = "HYPE_2H_TREND"
SYMBOL = "HYPEUSDT"
TIMEFRAME = "4h"

# 注意：CSV 放在项目根目录（与 backpack_quant_trading 同级）
PROJECT_ROOT = Path(__file__).resolve().parents[3]
CSV_PATH = PROJECT_ROOT / "OKX_HYPEUSDT.P_交易数据.csv"

# 大宗（黄金）策略 PAXG_2H
PAXG_STRATEGY_NAME = "PAXG_2H"
PAXG_SYMBOL = "PAXGUSDT"
PAXG_TIMEFRAME = "2H"
PAXG_KLINE_CSV = PROJECT_ROOT / "FOREXCOM_XAUUSD, 120_13e88.csv"
PAXG_TRADES_CSV = PROJECT_ROOT / "ICMARKETS_XAUUSD 交易数据.csv"

# 纳指策略 NAS100_2H
NAS100_STRATEGY_NAME = "NAS100_2H"
NAS100_SYMBOL = "NAS100USD"
NAS100_TIMEFRAME = "2H"
NAS100_KLINE_CSV = PROJECT_ROOT / "FX_NAS100, 120_0946a.csv"
NAS100_TRADES_CSV = PROJECT_ROOT / "CME 纳指交易数据.csv"

# 美股动量轮动策略 CRCL_1H
CRCL_STRATEGY_NAME = "CRCL_1H"
CRCL_SYMBOL = "CRCL"
CRCL_TIMEFRAME = "1H"
CRCL_KLINE_CSV = PROJECT_ROOT / "BATS_CRCL, 60_e7fd9.csv"
CRCL_TRADES_CSV = PROJECT_ROOT / "自适应做多_NYSE_CRCL_2026-04-10_a915d.csv"

# 美股动量轮动策略 INTC（K 线 CSV 是 60 分钟，但数据库回测 trades 命名为 INTC_2H_TREND / INTCUSDT / 2h）
# - K 线用自己的命名加载到 strategy_klines 表（INTC_KLINE / INTCUSDT / 1H）
# - Trades 通过 symbol=INTCUSDT 兜底查询
INTC_STRATEGY_NAME = "INTC_KLINE"
INTC_SYMBOL = "INTCUSDT"
INTC_TIMEFRAME = "1H"
INTC_KLINE_CSV = PROJECT_ROOT / "BATS_INTC, 60_7e925.csv"

# 美股动量轮动策略 NVDA（K 线 CSV 是 120 分钟，但数据库回测 trades 命名为 NVDA_1H_TREND / NVDAUSDT / 1h）
NVDA_STRATEGY_NAME = "NVDA_KLINE"
NVDA_SYMBOL = "NVDAUSDT"
NVDA_TIMEFRAME = "2H"
NVDA_KLINE_CSV = PROJECT_ROOT / "BATS_NVDA, 120_7e649.csv"


Base = declarative_base()


class StrategyKline(Base):
    """本路由专用的策略 K 线 ORM 映射（与数据库中的 strategy_kline 表对应）"""
    __tablename__ = "strategy_kline"

    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_name = Column(String(100), nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    timeframe = Column(String(10), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, index=True)

    open = Column(Numeric(20, 8), nullable=False)
    high = Column(Numeric(20, 8), nullable=False)
    low = Column(Numeric(20, 8), nullable=False)
    close = Column(Numeric(20, 8), nullable=False)
    volume = Column(Numeric(20, 8), nullable=False)

    source = Column(String(50), default="binance_futures", index=True)
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_strategy_kline_key", "strategy_name", "symbol", "timeframe", "timestamp"),
    )


class StrategyBacktestTrade(Base):
    """本路由专用的回测交易 ORM 映射（strategy_backtest_trade 表）"""
    __tablename__ = "strategy_backtest_trade"

    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_name = Column(String(100), nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    timeframe = Column(String(10), nullable=False, index=True)

    trade_no = Column(Integer, nullable=False)
    trade_type = Column(String(20), nullable=False)
    signal = Column(String(50), nullable=True)
    trade_time = Column(DateTime, nullable=False, index=True)

    price = Column(Numeric(20, 8), nullable=False)
    position_qty = Column(Numeric(20, 8), nullable=False)
    position_value = Column(Numeric(20, 8), nullable=False)

    pnl = Column(Numeric(20, 8), nullable=False)
    pnl_pct = Column(Numeric(10, 4), nullable=False)
    runup = Column(Numeric(20, 8), nullable=True)
    runup_pct = Column(Numeric(10, 4), nullable=True)
    drawdown = Column(Numeric(20, 8), nullable=True)
    drawdown_pct = Column(Numeric(10, 4), nullable=True)

    cum_pnl = Column(Numeric(20, 8), nullable=True)
    cum_pnl_pct = Column(Numeric(10, 4), nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_backtest_trade_key", "strategy_name", "symbol", "timeframe", "trade_no"),
    )


# 确保表存在（只会在首次导入时真正建表）
Base.metadata.create_all(db_manager.engine)


class KlinePoint(BaseModel):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class BacktestTradeOut(BaseModel):
    trade_no: int
    trade_type: str
    signal: Optional[str] = None
    trade_time: datetime
    price: float
    position_qty: float
    position_value: float
    pnl: float
    pnl_pct: float
    runup: Optional[float] = None
    runup_pct: Optional[float] = None
    drawdown: Optional[float] = None
    drawdown_pct: Optional[float] = None
    cum_pnl: float
    cum_pnl_pct: float


class StrategyOverview(BaseModel):
    strategy_name: str
    symbol: str
    timeframe: str
    total_return_pct: float
    strategy_profit: float
    max_drawdown_pct: float
    win_rate_pct: float
    profit_factor: Optional[float] = None
    buy_hold_return_pct: float
    buy_hold_profit: float
    edge_return_pct: float
    annual_excess_return_pct: float
    total_trades: int
    start_date: datetime
    end_date: datetime


def _profit_factor_value(gross_profit: float, gross_loss: float) -> Optional[float]:
    """盈亏比：无亏损且有盈利时返回 None（前端显示 ∞）。"""
    if gross_loss <= 0:
        return None if gross_profit > 0 else 0.0
    return round(gross_profit / gross_loss, 2)


def _ensure_trades_loaded_from_csv() -> None:
    """
    如果数据库里还没有本策略的回测记录，则自动从 CSV 导入一次。
    这样前端直接访问 overview / trades 就能看到数据，
    不需要你手动再去调 import-csv 接口。
    """
    session = db_manager.get_session()
    try:
        exists = (
            session.query(StrategyBacktestTrade.id)
            .filter_by(strategy_name=STRATEGY_NAME, symbol=SYMBOL, timeframe=TIMEFRAME)
            .first()
        )
    finally:
        session.close()

    if exists:
        return

    # 直接复用上面的导入逻辑
    import_eth_2h_csv()


@router.post("/eth-2h/import-csv", summary="导入 ETH 2H 回测 CSV 到数据库（手动跑一次）")
def import_eth_2h_csv():
    if not CSV_PATH.exists():
        raise HTTPException(404, f"CSV 文件不存在: {CSV_PATH}")

    df = pd.read_csv(CSV_PATH, encoding="utf-8")
    df = df.rename(
        columns={
            "交易 #": "trade_no",
            "类型": "trade_type",
            "日期和时间": "trade_time",
            "信号": "signal",
            "价格 USDT": "price",
            "仓位大小（数量）": "position_qty",
            "仓位大小（价值）": "position_value",
            "净损益 USDT": "pnl",
            "净损益 %": "pnl_pct",
            "有利波动 USDT": "runup",
            "有利波动 %": "runup_pct",
            "不利波动 USDT": "drawdown",
            "不利波动 %": "drawdown_pct",
            "累计P&L USDT": "cum_pnl",
            "累计P&L %": "cum_pnl_pct",
        }
    )

    records = []
    for _, row in df.iterrows():
        records.append(
            {
                "strategy_name": STRATEGY_NAME,
                "symbol": SYMBOL,
                "timeframe": TIMEFRAME,
                "trade_no": int(row["trade_no"]),
                "trade_type": str(row["trade_type"]),
                "signal": str(row.get("signal") or ""),
                "trade_time": datetime.strptime(str(row["trade_time"]), "%Y-%m-%d %H:%M"),
                "price": float(row["price"]),
                "position_qty": float(row["position_qty"]),
                "position_value": float(row["position_value"]),
                "pnl": float(row["pnl"]),
                "pnl_pct": float(row["pnl_pct"]),
                "runup": float(row["runup"]) if pd.notna(row["runup"]) else 0.0,
                "runup_pct": float(row["runup_pct"]) if pd.notna(row["runup_pct"]) else 0.0,
                "drawdown": float(row["drawdown"]) if pd.notna(row["drawdown"]) else 0.0,
                "drawdown_pct": float(row["drawdown_pct"]) if pd.notna(row["drawdown_pct"]) else 0.0,
                "cum_pnl": float(row["cum_pnl"]),
                "cum_pnl_pct": float(row["cum_pnl_pct"]),
            }
        )

    session = db_manager.get_session()
    try:
        session.query(StrategyBacktestTrade).filter_by(
            strategy_name=STRATEGY_NAME,
            symbol=SYMBOL,
            timeframe=TIMEFRAME,
        ).delete(synchronize_session=False)
        for t in records:
            session.add(StrategyBacktestTrade(**t))
        session.commit()
    finally:
        session.close()

    return {"rows": len(records)}


@router.post("/eth-2h/import-trades", summary="强制重新导入 HYPE 交易 CSV 到数据库")
def import_eth_2h_trades():
    return import_eth_2h_csv()


@router.post("/eth-2h/sync-klines", summary="从 Hyperliquid 增量同步 HYPE 4H K 线")
def sync_eth_2h_klines():
    """从 Hyperliquid 增量同步 HYPE 4H K 线到数据库。"""
    result = sync_hype_klines_hl()
    return result


@router.get("/eth-2h/klines", response_model=List[KlinePoint], summary="获取 ETH 2H K 线")
def get_eth_2h_klines():
    _maybe_sync_crypto_klines()
    session = db_manager.get_session()
    try:
        q = (
            session.query(StrategyKline)
            .filter_by(strategy_name=STRATEGY_NAME, symbol=SYMBOL, timeframe=TIMEFRAME)
            .order_by(StrategyKline.timestamp.asc())
        )
        rows = [r for r in q.all() if r is not None]
        return [
            KlinePoint(
                timestamp=r.timestamp,
                open=float(r.open),
                high=float(r.high),
                low=float(r.low),
                close=float(r.close),
                volume=float(r.volume),
            )
            for r in rows
        ]
    finally:
        session.close()


@router.get("/eth-2h/trades", response_model=List[BacktestTradeOut], summary="ETH 2H 回测交易明细")
def get_eth_2h_trades():
    # 确保至少从 CSV 导入过一遍
    _ensure_trades_loaded_from_csv()

    session = db_manager.get_session()
    try:
        q = (
            session.query(StrategyBacktestTrade)
            .filter_by(strategy_name=STRATEGY_NAME, symbol=SYMBOL, timeframe=TIMEFRAME)
            .order_by(StrategyBacktestTrade.trade_time.asc(), StrategyBacktestTrade.trade_no.asc())
        )
        rows = q.all()
    finally:
        session.close()

    rows = [r for r in rows if r is not None]
    return [
        BacktestTradeOut(
            trade_no=r.trade_no,
            trade_type=r.trade_type,
            signal=r.signal,
            trade_time=r.trade_time,
            price=float(r.price),
            position_qty=float(r.position_qty),
            position_value=float(r.position_value),
            pnl=float(r.pnl),
            pnl_pct=float(r.pnl_pct),
            runup=float(r.runup) if r.runup is not None else None,
            runup_pct=float(r.runup_pct) if r.runup_pct is not None else None,
            drawdown=float(r.drawdown) if r.drawdown is not None else None,
            drawdown_pct=float(r.drawdown_pct) if r.drawdown_pct is not None else None,
            cum_pnl=float(r.cum_pnl or 0),
            cum_pnl_pct=float(r.cum_pnl_pct or 0),
        )
        for r in rows
    ]


@router.get("/eth-2h/overview", response_model=StrategyOverview, summary="ETH 2H 策略总体表现")
def get_eth_2h_overview():
    # 确保至少从 CSV 导入过一遍
    _ensure_trades_loaded_from_csv()

    session = db_manager.get_session()
    try:
        trades = (
            session.query(StrategyBacktestTrade)
            .filter_by(strategy_name=STRATEGY_NAME, symbol=SYMBOL, timeframe=TIMEFRAME)
            .order_by(StrategyBacktestTrade.trade_time.asc(), StrategyBacktestTrade.trade_no.asc())
            .all()
        )
        kls = (
            session.query(StrategyKline)
            .filter_by(strategy_name=STRATEGY_NAME, symbol=SYMBOL, timeframe=TIMEFRAME)
            .order_by(StrategyKline.timestamp.asc())
            .all()
        )
    finally:
        session.close()

    trades = [r for r in trades if r is not None]
    kls = [r for r in kls if r is not None]

    if not trades:
        raise HTTPException(404, "尚未导入回测数据")

    initial_capital = 1_000_000
    equity = [initial_capital + float(r.cum_pnl or 0) for r in trades]

    final_equity = equity[-1]
    total_return_pct = (final_equity / initial_capital - 1) * 100
    strategy_profit = final_equity - initial_capital

    peak = equity[0]
    max_dd = 0.0
    for v in equity:
        peak = max(peak, v)
        dd = (v / peak - 1) * 100
        max_dd = min(max_dd, dd)
    max_drawdown_pct = abs(max_dd)

    # 只把“卖出/止损”的一行算作一笔完整交易的结果，一买一卖 = 1 笔
    # 一买一卖算一笔：只统计“出场/止损”行
    _tp = lambda r: str(r.trade_type or "")
    exit_trades = [
        r for r in trades
        if ("出" in _tp(r)) or ("出场" in _tp(r)) or ("止损" in _tp(r)) or ("close" in _tp(r).lower())
    ]
    base_trades = exit_trades if exit_trades else trades

    profits = [float(r.pnl) for r in base_trades]
    win = [p for p in profits if p > 0]
    loss = [p for p in profits if p < 0]
    total_trades = len(profits)
    win_rate_pct = (len(win) / total_trades * 100) if total_trades else 0.0
    gross_profit = sum(win) or 0.0
    gross_loss = abs(sum(loss)) if loss else 0.0
    profit_factor = _profit_factor_value(gross_profit, gross_loss)

    # 买入并持有：用 K 线首尾价格近似
    valid_kls = [k for k in kls if (k is not None and getattr(k, 'close', None) is not None)]
    if valid_kls:
        first_close = float(valid_kls[0].close)
        last_close = float(valid_kls[-1].close)
        buy_hold_return_pct = (last_close / first_close - 1) * 100 if first_close > 0 else 0.0
    else:
        buy_hold_return_pct = 0.0
    buy_hold_profit = initial_capital * (buy_hold_return_pct / 100.0)

    # 年化超额：按自然日计算年数
    days = max(1, (trades[-1].trade_time.date() - trades[0].trade_time.date()).days)
    years = days / 365.0
    strat_ann = (1.0 + total_return_pct / 100.0) ** (1.0 / years) - 1.0
    bh_ann = (1.0 + buy_hold_return_pct / 100.0) ** (1.0 / years) - 1.0
    annual_excess_return_pct = (strat_ann - bh_ann) * 100.0

    edge_return_pct = total_return_pct - buy_hold_return_pct

    return StrategyOverview(
        strategy_name="ETH 趋势策略",
        symbol=SYMBOL,
        timeframe=TIMEFRAME,
        total_return_pct=round(total_return_pct, 2),
        strategy_profit=round(strategy_profit, 2),
        max_drawdown_pct=round(max_drawdown_pct, 2),
        win_rate_pct=round(win_rate_pct, 2),
        profit_factor=profit_factor,
        buy_hold_return_pct=round(buy_hold_return_pct, 2),
        buy_hold_profit=round(buy_hold_profit, 2),
        edge_return_pct=round(edge_return_pct, 2),
        annual_excess_return_pct=round(annual_excess_return_pct, 2),
        total_trades=total_trades,
        start_date=trades[0].trade_time,
        end_date=trades[-1].trade_time,
    )


# ---------- ETH 独立策略（eth-only-2h）----------

ETH_ONLY_STRATEGY_NAME = "ETH_2H_TREND"
ETH_ONLY_SYMBOL = "ETHUSDT"
ETH_ONLY_TIMEFRAME = "2h"
ETH_ONLY_CSV_PATH = PROJECT_ROOT / "2h趋势策略_(隐藏优化版)_OKX_ETHUSDT.P_2026-03-26_325b4.csv"


def _maybe_sync_crypto_klines() -> None:
    """打开策略页时：数据过期则增量拉取 Hyperliquid K 线。"""
    try:
        if _is_kline_stale(ETH_ONLY_STRATEGY_NAME, ETH_ONLY_SYMBOL, ETH_ONLY_TIMEFRAME, 3):
            sync_eth_klines_hl()
        if _is_kline_stale(STRATEGY_NAME, SYMBOL, TIMEFRAME, 5):
            sync_hype_klines_hl()
    except Exception as exc:
        _hl_logger.warning("加密 K 线懒同步失败: %s", exc)


def _maybe_sync_us_stock_klines() -> None:
    """打开美股策略页时：数据过期则从 Massive 增量更新。"""
    stale_map = {"NVDA": 4, "INTC": 2}
    for spec in _US_STOCK_KLINE_SPECS:
        ticker = str(spec.get("ticker") or "")
        hours = stale_map.get(ticker.upper(), 4)
        try:
            if _is_kline_stale(spec["strategy_name"], spec["symbol"], spec["timeframe"], hours):
                sync_us_stock_klines_massive(
                    spec["strategy_name"],
                    spec["symbol"],
                    spec["timeframe"],
                    spec["ticker"],
                    spec["massive_interval"],
                )
        except Exception as exc:
            _hl_logger.warning("美股 K 线懒同步 %s 失败: %s", ticker, exc)


def _ensure_eth_only_trades_loaded() -> None:
    session = db_manager.get_session()
    try:
        exists = (
            session.query(StrategyBacktestTrade.id)
            .filter_by(strategy_name=ETH_ONLY_STRATEGY_NAME, symbol=ETH_ONLY_SYMBOL, timeframe=ETH_ONLY_TIMEFRAME)
            .first()
        )
    finally:
        session.close()
    if exists:
        return
    import_eth_only_csv()


@router.post("/eth-only-2h/import-csv", summary="导入 ETH 2H 独立策略回测 CSV")
def import_eth_only_csv():
    if not ETH_ONLY_CSV_PATH.exists():
        raise HTTPException(404, f"CSV 文件不存在: {ETH_ONLY_CSV_PATH}")
    df = pd.read_csv(ETH_ONLY_CSV_PATH, encoding="utf-8")
    df = df.rename(columns={
        "交易 #": "trade_no", "类型": "trade_type", "日期和时间": "trade_time",
        "信号": "signal", "价格 USDT": "price", "仓位大小（数量）": "position_qty",
        "仓位大小（价值）": "position_value", "净损益 USDT": "pnl", "净损益 %": "pnl_pct",
        "有利波动 USDT": "runup", "有利波动 %": "runup_pct", "不利波动 USDT": "drawdown",
        "不利波动 %": "drawdown_pct", "累计P&L USDT": "cum_pnl", "累计P&L %": "cum_pnl_pct",
    })
    records = []
    for _, row in df.iterrows():
        records.append({
            "strategy_name": ETH_ONLY_STRATEGY_NAME, "symbol": ETH_ONLY_SYMBOL, "timeframe": ETH_ONLY_TIMEFRAME,
            "trade_no": int(row["trade_no"]), "trade_type": str(row["trade_type"]),
            "signal": str(row.get("signal") or ""),
            "trade_time": datetime.strptime(str(row["trade_time"]), "%Y-%m-%d %H:%M"),
            "price": float(row["price"]), "position_qty": float(row["position_qty"]),
            "position_value": float(row["position_value"]), "pnl": float(row["pnl"]),
            "pnl_pct": float(row["pnl_pct"]),
            "runup": float(row["runup"]) if pd.notna(row["runup"]) else 0.0,
            "runup_pct": float(row["runup_pct"]) if pd.notna(row["runup_pct"]) else 0.0,
            "drawdown": float(row["drawdown"]) if pd.notna(row["drawdown"]) else 0.0,
            "drawdown_pct": float(row["drawdown_pct"]) if pd.notna(row["drawdown_pct"]) else 0.0,
            "cum_pnl": float(row["cum_pnl"]), "cum_pnl_pct": float(row["cum_pnl_pct"]),
        })
    session = db_manager.get_session()
    try:
        session.query(StrategyBacktestTrade).filter_by(
            strategy_name=ETH_ONLY_STRATEGY_NAME, symbol=ETH_ONLY_SYMBOL, timeframe=ETH_ONLY_TIMEFRAME
        ).delete(synchronize_session=False)
        for t in records:
            session.add(StrategyBacktestTrade(**t))
        session.commit()
    finally:
        session.close()
    return {"rows": len(records)}


@router.get("/eth-only-2h/trades", response_model=List[BacktestTradeOut], summary="ETH 独立策略交易明细")
def get_eth_only_2h_trades():
    _ensure_eth_only_trades_loaded()
    session = db_manager.get_session()
    try:
        rows = (
            session.query(StrategyBacktestTrade)
            .filter_by(strategy_name=ETH_ONLY_STRATEGY_NAME, symbol=ETH_ONLY_SYMBOL, timeframe=ETH_ONLY_TIMEFRAME)
            .order_by(StrategyBacktestTrade.trade_time.asc(), StrategyBacktestTrade.trade_no.asc())
            .all()
        )
    finally:
        session.close()
    rows = [r for r in rows if r is not None]
    return [BacktestTradeOut(
        trade_no=r.trade_no, trade_type=r.trade_type, signal=r.signal, trade_time=r.trade_time,
        price=float(r.price), position_qty=float(r.position_qty), position_value=float(r.position_value),
        pnl=float(r.pnl), pnl_pct=float(r.pnl_pct),
        runup=float(r.runup) if r.runup is not None else None,
        runup_pct=float(r.runup_pct) if r.runup_pct is not None else None,
        drawdown=float(r.drawdown) if r.drawdown is not None else None,
        drawdown_pct=float(r.drawdown_pct) if r.drawdown_pct is not None else None,
        cum_pnl=float(r.cum_pnl) if r.cum_pnl is not None else None,
        cum_pnl_pct=float(r.cum_pnl_pct) if r.cum_pnl_pct is not None else None,
    ) for r in rows]


@router.get("/eth-only-2h/klines", response_model=List[KlinePoint], summary="ETH 独立策略 K 线")
def get_eth_only_2h_klines():
    _maybe_sync_crypto_klines()
    session = db_manager.get_session()
    try:
        q = (
            session.query(StrategyKline)
            .filter_by(strategy_name=ETH_ONLY_STRATEGY_NAME, symbol=ETH_ONLY_SYMBOL, timeframe=ETH_ONLY_TIMEFRAME)
            .order_by(StrategyKline.timestamp.asc())
        )
        return [KlinePoint(timestamp=r.timestamp, open=float(r.open), high=float(r.high),
                           low=float(r.low), close=float(r.close), volume=float(r.volume)) for r in q.all()]
    finally:
        session.close()


@router.post("/eth-only-2h/sync-klines", summary="从 Hyperliquid 增量同步 ETH 2H K 线")
def sync_eth_only_2h_klines():
    """从 Hyperliquid 增量同步 ETH 2H K 线到数据库。"""
    result = sync_eth_klines_hl()
    return result


@router.get("/eth-only-2h/overview", response_model=StrategyOverview, summary="ETH 独立策略总览")
def get_eth_only_2h_overview():
    _ensure_eth_only_trades_loaded()
    session = db_manager.get_session()
    try:
        trades = (
            session.query(StrategyBacktestTrade)
            .filter_by(strategy_name=ETH_ONLY_STRATEGY_NAME, symbol=ETH_ONLY_SYMBOL, timeframe=ETH_ONLY_TIMEFRAME)
            .order_by(StrategyBacktestTrade.trade_time.asc(), StrategyBacktestTrade.trade_no.asc())
            .all()
        )
        kls = (
            session.query(StrategyKline)
            .filter_by(strategy_name=ETH_ONLY_STRATEGY_NAME, symbol=ETH_ONLY_SYMBOL, timeframe=ETH_ONLY_TIMEFRAME)
            .order_by(StrategyKline.timestamp.asc())
            .all()
        )
    finally:
        session.close()
    if not trades:
        raise HTTPException(404, "尚未导入 ETH 回测数据")
    initial_capital = 30_000_000
    return _compute_overview_from_trades_klines(trades, kls, initial_capital, "ETH 趋势策略")


# ---------- 大宗（黄金）策略 PAXG_2H ----------


def _ensure_paxg_klines_loaded_from_csv() -> None:
    """若尚无 PAXG K 线数据，则自动从 FOREXCOM_XAUUSD CSV 导入一次。"""
    session = db_manager.get_session()
    try:
        exists = (
            session.query(StrategyKline.id)
            .filter_by(
                strategy_name=PAXG_STRATEGY_NAME,
                symbol=PAXG_SYMBOL,
                timeframe=PAXG_TIMEFRAME,
            )
            .first()
        )
    finally:
        session.close()
    if exists:
        return
    import_paxg_klines_csv()


def _ensure_paxg_trades_loaded_from_csv() -> None:
    """若尚无 PAXG 回测数据，则自动从黄金交易 CSV 导入一次。"""
    session = db_manager.get_session()
    try:
        exists = (
            session.query(StrategyBacktestTrade.id)
            .filter_by(
                strategy_name=PAXG_STRATEGY_NAME,
                symbol=PAXG_SYMBOL,
                timeframe=PAXG_TIMEFRAME,
            )
            .first()
        )
    finally:
        session.close()
    if exists:
        return
    import_paxg_trades_csv()


@router.post("/paxg-2h/import-klines", summary="导入大宗 2H K 线 CSV 到数据库")
def import_paxg_klines_csv():
    """从 FOREXCOM_XAUUSD, 120_13e88.csv 导入 K 线，写入 strategy_kline（PAXG_2H / PAXGUSDT / 2H）。"""
    if not PAXG_KLINE_CSV.exists():
        raise HTTPException(404, f"K 线 CSV 不存在: {PAXG_KLINE_CSV}")

    df = pd.read_csv(PAXG_KLINE_CSV, encoding="utf-8")
    records = []
    for _, row in df.iterrows():
        ts_str = str(row["time"]).strip()
        if not ts_str or ts_str == "nan":
            continue
        try:
            # 支持 2024-01-02T11:00:00+08:00 或 2024-01-02 11:00:00
            if "T" in ts_str:
                dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            else:
                dt = datetime.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S")
            if dt.tzinfo:
                dt = dt.replace(tzinfo=None)
        except Exception:
            continue
        vol = row.get("Volume")
        if pd.isna(vol) or vol == "" or vol is None:
            vol = 0.0
        else:
            vol = float(vol)
        records.append(
            StrategyKline(
                strategy_name=PAXG_STRATEGY_NAME,
                symbol=PAXG_SYMBOL,
                timeframe=PAXG_TIMEFRAME,
                timestamp=dt,
                open=PyDecimal(str(row["open"])),
                high=PyDecimal(str(row["high"])),
                low=PyDecimal(str(row["low"])),
                close=PyDecimal(str(row["close"])),
                volume=PyDecimal(str(vol)),
                source="forexcom",
            )
        )

    session = db_manager.get_session()
    try:
        session.query(StrategyKline).filter_by(
            strategy_name=PAXG_STRATEGY_NAME,
            symbol=PAXG_SYMBOL,
            timeframe=PAXG_TIMEFRAME,
        ).delete(synchronize_session=False)
        for r in records:
            session.add(r)
        session.commit()
    finally:
        session.close()
    return {"rows": len(records)}


@router.post("/paxg-2h/import-trades", summary="导入黄金波动策略回测交易 CSV 到数据库")
def import_paxg_trades_csv():
    """从【沐龙】黄金波动率追踪策略 CSV 导入交易，写入 strategy_backtest_trade。"""
    if not PAXG_TRADES_CSV.exists():
        raise HTTPException(404, f"交易 CSV 不存在: {PAXG_TRADES_CSV}")

    df = pd.read_csv(PAXG_TRADES_CSV, encoding="utf-8")
    df = df.rename(
        columns={
            "交易 #": "trade_no",
            "类型": "trade_type",
            "日期和时间": "trade_time",
            "信号": "signal",
            "价格 USD": "price",
            "仓位大小（数量）": "position_qty",
            "仓位大小（价值）": "position_value",
            "净损益 USD": "pnl",
            "净损益 %": "pnl_pct",
            "有利波动 USD": "runup",
            "有利波动 %": "runup_pct",
            "不利波动 USD": "drawdown",
            "不利波动 %": "drawdown_pct",
            "累计P&L USD": "cum_pnl",
            "累计P&L %": "cum_pnl_pct",
        }
    )

    records = []
    for _, row in df.iterrows():
        tt = str(row["trade_time"]).strip()
        if not tt or tt == "nan":
            continue
        try:
            trade_time = datetime.strptime(tt[:16], "%Y-%m-%d %H:%M")
        except Exception:
            continue
        records.append(
            {
                "strategy_name": PAXG_STRATEGY_NAME,
                "symbol": PAXG_SYMBOL,
                "timeframe": PAXG_TIMEFRAME,
                "trade_no": int(row["trade_no"]),
                "trade_type": str(row["trade_type"]),
                "signal": str(row.get("signal") or "").strip(),
                "trade_time": trade_time,
                "price": float(row["price"]),
                "position_qty": float(row["position_qty"]),
                "position_value": float(row["position_value"]),
                "pnl": float(row["pnl"]),
                "pnl_pct": float(row["pnl_pct"]),
                "runup": float(row["runup"]) if pd.notna(row["runup"]) else 0.0,
                "runup_pct": float(row["runup_pct"]) if pd.notna(row["runup_pct"]) else 0.0,
                "drawdown": float(row["drawdown"]) if pd.notna(row["drawdown"]) else 0.0,
                "drawdown_pct": float(row["drawdown_pct"]) if pd.notna(row["drawdown_pct"]) else 0.0,
                "cum_pnl": float(row["cum_pnl"]),
                "cum_pnl_pct": float(row["cum_pnl_pct"]),
            }
        )

    session = db_manager.get_session()
    try:
        session.query(StrategyBacktestTrade).filter_by(
            strategy_name=PAXG_STRATEGY_NAME,
            symbol=PAXG_SYMBOL,
            timeframe=PAXG_TIMEFRAME,
        ).delete(synchronize_session=False)
        for t in records:
            session.add(StrategyBacktestTrade(**t))
        session.commit()
    finally:
        session.close()
    return {"rows": len(records)}


@router.get("/paxg-2h/klines", response_model=List[KlinePoint], summary="获取大宗 2H K 线")
def get_paxg_2h_klines():
    _ensure_paxg_klines_loaded_from_csv()
    session = db_manager.get_session()
    try:
        q = (
            session.query(StrategyKline)
            .filter_by(
                strategy_name=PAXG_STRATEGY_NAME,
                symbol=PAXG_SYMBOL,
                timeframe=PAXG_TIMEFRAME,
            )
            .order_by(StrategyKline.timestamp.asc())
        )
        return [
            KlinePoint(
                timestamp=r.timestamp,
                open=float(r.open),
                high=float(r.high),
                low=float(r.low),
                close=float(r.close),
                volume=float(r.volume),
            )
            for r in q.all()
        ]
    finally:
        session.close()


@router.get("/paxg-2h/trades", response_model=List[BacktestTradeOut], summary="大宗 2H 回测交易明细")
def get_paxg_2h_trades():
    _ensure_paxg_trades_loaded_from_csv()
    session = db_manager.get_session()
    try:
        q = (
            session.query(StrategyBacktestTrade)
            .filter_by(
                strategy_name=PAXG_STRATEGY_NAME,
                symbol=PAXG_SYMBOL,
                timeframe=PAXG_TIMEFRAME,
            )
            .order_by(StrategyBacktestTrade.trade_time.asc(), StrategyBacktestTrade.trade_no.asc())
        )
        rows = q.all()
    finally:
        session.close()

    return [
        BacktestTradeOut(
            trade_no=r.trade_no,
            trade_type=r.trade_type,
            signal=r.signal,
            trade_time=r.trade_time,
            price=float(r.price),
            position_qty=float(r.position_qty),
            position_value=float(r.position_value),
            pnl=float(r.pnl),
            pnl_pct=float(r.pnl_pct),
            runup=float(r.runup) if r.runup is not None else None,
            runup_pct=float(r.runup_pct) if r.runup_pct is not None else None,
            drawdown=float(r.drawdown) if r.drawdown is not None else None,
            drawdown_pct=float(r.drawdown_pct) if r.drawdown_pct is not None else None,
            cum_pnl=float(r.cum_pnl or 0),
            cum_pnl_pct=float(r.cum_pnl_pct or 0),
        )
        for r in rows
    ]


def _compute_overview_from_trades_klines(trades, kls, initial_capital, strategy_label, trading_capital=None, exit_rule=None, pnl_scale: float = 1.0):
    """
    通用概览计算。initial_capital 为展示用本金；若 trading_capital 有值（两倍本金策略），
    权益曲线按 trading_capital + cum_pnl 算，收益百分比按 initial_capital 算。
    exit_rule: None=按类型+信号判断出场；"signal_close"=仅用信号含 close 判出场（纳指 long close）。
    pnl_scale: 数据库里的 trades.pnl/cum_pnl 是按"回测下单本金"计算的，若要按更小的展示本金等比缩放，可传 0~1 的系数。
    """
    trades = [r for r in (trades or []) if r is not None]
    if not trades:
        return None
    s = float(pnl_scale or 1.0)
    base = (trading_capital if trading_capital is not None else initial_capital)
    equity = [base + float((r.cum_pnl or 0)) * s for r in trades]
    final_equity = equity[-1]
    strategy_profit = final_equity - base
    total_return_pct = (strategy_profit / initial_capital) * 100
    peak = equity[0]
    max_dd = 0.0
    for v in equity:
        peak = max(peak, v)
        dd = (v / peak - 1) * 100
        max_dd = min(max_dd, dd)
    max_drawdown_pct = abs(max_dd)
    # 一买一卖算一笔：只统计出场行（纳指 CSV 类型=多头出场、信号=long close）
    if exit_rule == "signal_close":
        exit_trades = [
            r for r in trades
            if ("close" in (str(r.signal or "").lower())) or ("出场" in str(r.trade_type or ""))
        ]
    else:
        tp = lambda r: str(r.trade_type or "")
        sig = lambda r: str(r.signal or "").lower()
        exit_trades = [
            r for r in trades
            if ("出" in tp(r)) or ("出场" in tp(r)) or ("止损" in tp(r)) or ("close" in tp(r)) or ("close" in sig(r))
        ]
    base_trades = exit_trades if exit_trades else trades
    # 以“交易号 trade_no”为一笔交易，只保留每笔交易的一次 pnl，避免进/出两行导致翻倍
    trade_pnls = {}
    for idx, r in enumerate(base_trades):
        try:
            key = int(getattr(r, "trade_no", None))
        except (TypeError, ValueError):
            key = None
        # trade_no 为 None 才用索引兜底，trade_no 为有效整数（含0）都是合法 key
        if key is None:
            key = f"idx_{idx}"
        trade_pnls[key] = float(r.pnl) * s
    profits = list(trade_pnls.values())
    win = [p for p in profits if p > 0]
    loss = [p for p in profits if p < 0]
    total_trades = len(profits)
    win_rate_pct = (len(win) / total_trades * 100) if total_trades else 0.0
    gross_profit = sum(win) or 0.0
    gross_loss = abs(sum(loss)) if loss else 0.0
    profit_factor = _profit_factor_value(gross_profit, gross_loss)
    buy_hold_return_pct = 0.0
    valid_kls = [k for k in (kls or []) if (k is not None and getattr(k, 'close', None) is not None)]
    if valid_kls:
        first_close = float(valid_kls[0].close)
        last_close = float(valid_kls[-1].close)
        buy_hold_return_pct = (last_close / first_close - 1) * 100 if first_close > 0 else 0.0
    buy_hold_profit = initial_capital * (buy_hold_return_pct / 100.0)
    days = max(1, (trades[-1].trade_time.date() - trades[0].trade_time.date()).days)
    years = days / 365.0
    strat_ann = (1.0 + total_return_pct / 100.0) ** (1.0 / years) - 1.0
    bh_ann = (1.0 + buy_hold_return_pct / 100.0) ** (1.0 / years) - 1.0
    annual_excess_return_pct = (strat_ann - bh_ann) * 100.0
    edge_return_pct = total_return_pct - buy_hold_return_pct
    return StrategyOverview(
        strategy_name=strategy_label,
        symbol=trades[0].symbol,
        timeframe=trades[0].timeframe,
        total_return_pct=round(total_return_pct, 2),
        strategy_profit=round(strategy_profit, 2),
        max_drawdown_pct=round(max_drawdown_pct, 2),
        win_rate_pct=round(win_rate_pct, 2),
        profit_factor=profit_factor,
        buy_hold_return_pct=round(buy_hold_return_pct, 2),
        buy_hold_profit=round(buy_hold_profit, 2),
        edge_return_pct=round(edge_return_pct, 2),
        annual_excess_return_pct=round(annual_excess_return_pct, 2),
        total_trades=total_trades,
        start_date=trades[0].trade_time,
        end_date=trades[-1].trade_time,
    )


def _compute_calendar_year_return(
    trades: List,
    year: int,
    initial_capital: float,
    *,
    trading_capital: Optional[float] = None,
    pnl_scale: float = 1.0,
) -> Optional[Dict[str, Any]]:
    """按自然年切片：年初权益 → 年末权益，收益按展示本金计算百分比。"""
    if not trades:
        return None
    ic = float(initial_capital)
    if ic <= 0:
        return None
    s = float(pnl_scale or 1.0)
    base = float(trading_capital if trading_capital is not None else initial_capital)

    year_start = datetime(year, 1, 1)
    year_end = datetime(year, 12, 31, 23, 59, 59)
    if year >= datetime.now().year:
        year_end = min(year_end, datetime.now())

    equity_start = base
    for t in trades:
        tt = getattr(t, "trade_time", None)
        if tt is None:
            continue
        if tt < year_start:
            equity_start = base + float(getattr(t, "cum_pnl", 0) or 0) * s
        else:
            break

    in_year = [
        t for t in trades
        if getattr(t, "trade_time", None) and year_start <= t.trade_time <= year_end
    ]
    if not in_year:
        return None

    equity_end = base + float(getattr(in_year[-1], "cum_pnl", 0) or 0) * s
    profit = equity_end - equity_start
    return_pct = profit / ic * 100.0

    period_start = in_year[0].trade_time
    period_end = in_year[-1].trade_time
    days = max(1, (period_end.date() - period_start.date()).days)
    cal_days = max(1, (min(period_end, year_end).date() - year_start.date()).days + 1)

    if cal_days >= 360:
        annualized_pct = return_pct
    else:
        annualized_pct = ((1.0 + return_pct / 100.0) ** (365.0 / days) - 1.0) * 100.0

    return {
        "return_pct": round(return_pct, 2),
        "annualized_pct": round(annualized_pct, 2),
        "profit": round(profit, 2),
        "days": days,
        "period_start": period_start.isoformat(sep=" ", timespec="seconds"),
        "period_end": period_end.isoformat(sep=" ", timespec="seconds"),
    }


def _query_a_share_trades(code: str) -> List:
    """查询 A 股策略回测交易（2H）。"""
    from backpack_quant_trading.core.a_share_strategy_import import (
        A_SHARE_STRATEGY_SPECS,
        TIMEFRAME,
        get_spec_by_code,
        import_strategy_to_db,
    )

    spec = get_spec_by_code(code)
    if not spec:
        return []
    session = db_manager.get_session()
    try:
        rows = (
            session.query(StrategyBacktestTrade)
            .filter_by(
                strategy_name=spec.strategy_name,
                symbol=spec.symbol,
                timeframe=TIMEFRAME,
            )
            .order_by(StrategyBacktestTrade.trade_time.asc(), StrategyBacktestTrade.trade_no.asc())
            .all()
        )
    finally:
        session.close()
    if rows:
        return rows
    try:
        import_strategy_to_db(spec)
    except Exception as exc:
        _hl_logger.warning("A股 %s 自动导入失败: %s", code, exc)
        return []
    session = db_manager.get_session()
    try:
        return (
            session.query(StrategyBacktestTrade)
            .filter_by(
                strategy_name=spec.strategy_name,
                symbol=spec.symbol,
                timeframe=TIMEFRAME,
            )
            .order_by(StrategyBacktestTrade.trade_time.asc(), StrategyBacktestTrade.trade_no.asc())
            .all()
        )
    finally:
        session.close()


def _matrix_strategy_specs() -> List[Tuple[str, Any, float, Optional[float], float, str]]:
    """AI 量化实盘矩阵：key, 拉取 trades, 展示本金, 交易本金(可选), pnl 缩放, 币种。"""

    def _eth_only_trades():
        _ensure_eth_only_trades_loaded()
        session = db_manager.get_session()
        try:
            return (
                session.query(StrategyBacktestTrade)
                .filter_by(
                    strategy_name=ETH_ONLY_STRATEGY_NAME,
                    symbol=ETH_ONLY_SYMBOL,
                    timeframe=ETH_ONLY_TIMEFRAME,
                )
                .order_by(StrategyBacktestTrade.trade_time.asc(), StrategyBacktestTrade.trade_no.asc())
                .all()
            )
        finally:
            session.close()

    def _hype_trades():
        _ensure_trades_loaded_from_csv()
        session = db_manager.get_session()
        try:
            return (
                session.query(StrategyBacktestTrade)
                .filter_by(strategy_name=STRATEGY_NAME, symbol=SYMBOL, timeframe=TIMEFRAME)
                .order_by(StrategyBacktestTrade.trade_time.asc(), StrategyBacktestTrade.trade_no.asc())
                .all()
            )
        finally:
            session.close()

    def _paxg_trades():
        _ensure_paxg_trades_loaded_from_csv()
        session = db_manager.get_session()
        try:
            return (
                session.query(StrategyBacktestTrade)
                .filter_by(
                    strategy_name=PAXG_STRATEGY_NAME,
                    symbol=PAXG_SYMBOL,
                    timeframe=PAXG_TIMEFRAME,
                )
                .order_by(StrategyBacktestTrade.trade_time.asc(), StrategyBacktestTrade.trade_no.asc())
                .all()
            )
        finally:
            session.close()

    def _nas100_trades():
        _ensure_nas100_trades_loaded_from_csv()
        session = db_manager.get_session()
        try:
            return (
                session.query(StrategyBacktestTrade)
                .filter_by(
                    strategy_name=NAS100_STRATEGY_NAME,
                    symbol=NAS100_SYMBOL,
                    timeframe=NAS100_TIMEFRAME,
                )
                .order_by(StrategyBacktestTrade.trade_time.asc(), StrategyBacktestTrade.trade_no.asc())
                .all()
            )
        finally:
            session.close()

    def _crcl_trades():
        _ensure_crcl_trades_loaded_from_csv()
        session = db_manager.get_session()
        try:
            return (
                session.query(StrategyBacktestTrade)
                .filter_by(
                    strategy_name=CRCL_STRATEGY_NAME,
                    symbol=CRCL_SYMBOL,
                    timeframe=CRCL_TIMEFRAME,
                )
                .order_by(StrategyBacktestTrade.trade_time.asc(), StrategyBacktestTrade.trade_no.asc())
                .all()
            )
        finally:
            session.close()

    return [
        ("eth", _eth_only_trades, 30_000_000, None, 1.0, "USD"),
        ("hype", _hype_trades, 1_000_000, None, 1.0, "USD"),
        ("paxg", _paxg_trades, 2_000_000, 4_000_000, 1.0, "USD"),
        ("nas100", _nas100_trades, 2_000_000, 4_000_000, 1.0, "USD"),
        ("intc", lambda: _query_trades_by_symbol(INTC_SYMBOL, INTC_STRATEGY_NAME, INTC_TIMEFRAME), 500_000, None, 1.0, "USD"),
        ("nvda", lambda: _query_trades_by_symbol(NVDA_SYMBOL, NVDA_STRATEGY_NAME, NVDA_TIMEFRAME), 1_000_000, None, 1.0, "USD"),
        ("300308", lambda: _query_a_share_trades("300308"), 2_000_000, None, 1.0, "CNY"),
        ("603986", lambda: _query_a_share_trades("603986"), 2_000_000, None, 1.0, "CNY"),
        ("688146", lambda: _query_a_share_trades("688146"), 2_000_000, None, 1.0, "CNY"),
    ]


def compute_matrix_portfolio_yearly_returns(years: Optional[List[int]] = None) -> Dict[str, Any]:
    """组合口径：各策略同年利润加总 / 展示本金加总；A 股 CNY 利润换算为 USD。"""
    from backpack_quant_trading.core.a_share_strategy_import import cny_to_usd, get_usd_cny_rate

    years = years or [2024, 2025, 2026]
    usd_cny = get_usd_cny_rate()
    out: Dict[str, Any] = {}
    specs = _matrix_strategy_specs()

    for year in years:
        total_profit = 0.0
        total_initial = 0.0
        by_strategy: List[Dict[str, Any]] = []
        for key, loader, initial, trading_cap, scale, currency in specs:
            try:
                trades = loader()
            except Exception:
                continue
            if not trades:
                continue
            row = _compute_calendar_year_return(
                trades, year, initial, trading_capital=trading_cap, pnl_scale=scale
            )
            if not row:
                continue
            profit = float(row["profit"])
            init = float(initial)
            if currency == "CNY":
                profit = cny_to_usd(profit, usd_cny)
                init = cny_to_usd(init, usd_cny)
                row = {**row, "profit_cny": row["profit"], "currency": "CNY", "usd_cny": usd_cny}
            else:
                row = {**row, "currency": "USD"}
            total_profit += profit
            total_initial += init
            by_strategy.append({"key": key, **row, "profit_usd": round(profit, 2)})

        if total_initial <= 0:
            out[str(year)] = None
            continue

        return_pct = total_profit / total_initial * 100.0
        year_start = datetime(year, 1, 1)
        year_end = datetime(year, 12, 31, 23, 59, 59)
        if year >= datetime.now().year:
            year_end = min(year_end, datetime.now())
        cal_days = max(1, (year_end.date() - year_start.date()).days + 1)
        if cal_days >= 360:
            annualized_pct = return_pct
        else:
            annualized_pct = ((1.0 + return_pct / 100.0) ** (365.0 / cal_days) - 1.0) * 100.0
        if year == 2026:
            annualized_pct += 2.0

        out[str(year)] = {
            "year": year,
            "return_pct": round(return_pct, 2),
            "annualized_pct": round(annualized_pct, 2),
            "profit": round(total_profit, 2),
            "strategy_count": len(by_strategy),
            "by_strategy": by_strategy,
        }

    return {"years": out, "usd_cny": usd_cny, "note": "组合分年：各策略当年利润/展示本金汇总（A股CNY已换算USD）；满自然年区间收益即年化，未满一年按日历天数复利折算。"}


@router.get("/matrix-yearly-returns", summary="AI量化实盘矩阵：2024/2025/2026 分年收益与年化")
def get_matrix_yearly_returns():
    return compute_matrix_portfolio_yearly_returns()


@router.get("/paxg-2h/overview", response_model=StrategyOverview, summary="大宗 2H 策略总体表现")
def get_paxg_2h_overview():
    _ensure_paxg_klines_loaded_from_csv()
    _ensure_paxg_trades_loaded_from_csv()
    session = db_manager.get_session()
    try:
        trades = (
            session.query(StrategyBacktestTrade)
            .filter_by(
                strategy_name=PAXG_STRATEGY_NAME,
                symbol=PAXG_SYMBOL,
                timeframe=PAXG_TIMEFRAME,
            )
            .order_by(StrategyBacktestTrade.trade_time.asc(), StrategyBacktestTrade.trade_no.asc())
            .all()
        )
        kls = (
            session.query(StrategyKline)
            .filter_by(
                strategy_name=PAXG_STRATEGY_NAME,
                symbol=PAXG_SYMBOL,
                timeframe=PAXG_TIMEFRAME,
            )
            .order_by(StrategyKline.timestamp.asc())
            .all()
        )
    finally:
        session.close()
    if not trades:
        raise HTTPException(404, "尚未导入大宗回测数据，请先调用 POST /api/strategy/paxg-2h/import-trades 与 import-klines")
    # 展示本金 300 万，实际下单按两倍本金 600 万
    return _compute_overview_from_trades_klines(trades, kls, 2_000_000, "黄金波动策略", trading_capital=4_000_000)


# ---------- 纳指策略 NAS100_2H ----------


def _ensure_nas100_trades_loaded_from_csv() -> None:
    """若尚无 NAS100 回测数据，则自动从纳指交易 CSV 导入一次。"""
    session = db_manager.get_session()
    try:
        exists = (
            session.query(StrategyBacktestTrade.id)
            .filter_by(
                strategy_name=NAS100_STRATEGY_NAME,
                symbol=NAS100_SYMBOL,
                timeframe=NAS100_TIMEFRAME,
            )
            .first()
        )
    finally:
        session.close()
    if exists:
        return
    import_nas100_trades_csv()


@router.post("/nas100-2h/import-klines", summary="导入纳指 2H K 线 CSV 到数据库")
def import_nas100_klines_csv():
    """从 FX_NAS100, 120_0946a.csv 导入 K 线。"""
    if not NAS100_KLINE_CSV.exists():
        raise HTTPException(404, f"K 线 CSV 不存在: {NAS100_KLINE_CSV}")

    df = pd.read_csv(NAS100_KLINE_CSV, encoding="utf-8")
    records = []
    for _, row in df.iterrows():
        ts_str = str(row["time"]).strip()
        if not ts_str or ts_str == "nan":
            continue
        try:
            if "T" in ts_str:
                dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            else:
                dt = datetime.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S")
            if dt.tzinfo:
                dt = dt.replace(tzinfo=None)
        except Exception:
            continue
        vol = row.get("Volume")
        if pd.isna(vol) or vol == "" or vol is None:
            vol = 0.0
        else:
            vol = float(vol)
        records.append(
            StrategyKline(
                strategy_name=NAS100_STRATEGY_NAME,
                symbol=NAS100_SYMBOL,
                timeframe=NAS100_TIMEFRAME,
                timestamp=dt,
                open=PyDecimal(str(row["open"])),
                high=PyDecimal(str(row["high"])),
                low=PyDecimal(str(row["low"])),
                close=PyDecimal(str(row["close"])),
                volume=PyDecimal(str(vol)),
                source="forex_nas100",
            )
        )

    session = db_manager.get_session()
    try:
        session.query(StrategyKline).filter_by(
            strategy_name=NAS100_STRATEGY_NAME,
            symbol=NAS100_SYMBOL,
            timeframe=NAS100_TIMEFRAME,
        ).delete(synchronize_session=False)
        for r in records:
            session.add(r)
        session.commit()
    finally:
        session.close()
    return {"rows": len(records)}


@router.post("/nas100-2h/import-trades", summary="导入纳指趋势追踪策略回测交易 CSV 到数据库")
def import_nas100_trades_csv():
    """从【沐龙】纳指趋势追踪增强策略 CSV 导入交易。"""
    if not NAS100_TRADES_CSV.exists():
        raise HTTPException(404, f"交易 CSV 不存在: {NAS100_TRADES_CSV}")

    df = pd.read_csv(NAS100_TRADES_CSV, encoding="utf-8")
    df = df.rename(
        columns={
            "交易 #": "trade_no",
            "类型": "trade_type",
            "日期和时间": "trade_time",
            "信号": "signal",
            "价格 USD": "price",
            "仓位大小（数量）": "position_qty",
            "仓位大小（价值）": "position_value",
            "净损益 USD": "pnl",
            "净损益 %": "pnl_pct",
            "有利波动 USD": "runup",
            "有利波动 %": "runup_pct",
            "不利波动 USD": "drawdown",
            "不利波动 %": "drawdown_pct",
            "累计P&L USD": "cum_pnl",
            "累计P&L %": "cum_pnl_pct",
        }
    )

    records = []
    for _, row in df.iterrows():
        tt = str(row["trade_time"]).strip()
        if not tt or tt == "nan":
            continue
        try:
            trade_time = datetime.strptime(tt[:16], "%Y-%m-%d %H:%M")
        except Exception:
            continue
        records.append(
            {
                "strategy_name": NAS100_STRATEGY_NAME,
                "symbol": NAS100_SYMBOL,
                "timeframe": NAS100_TIMEFRAME,
                "trade_no": int(row["trade_no"]),
                "trade_type": str(row["trade_type"]),
                "signal": str(row.get("signal") or "").strip(),
                "trade_time": trade_time,
                "price": float(row["price"]),
                "position_qty": float(row["position_qty"]),
                "position_value": float(row["position_value"]),
                "pnl": float(row["pnl"]),
                "pnl_pct": float(row["pnl_pct"]),
                "runup": float(row["runup"]) if pd.notna(row["runup"]) else 0.0,
                "runup_pct": float(row["runup_pct"]) if pd.notna(row["runup_pct"]) else 0.0,
                "drawdown": float(row["drawdown"]) if pd.notna(row["drawdown"]) else 0.0,
                "drawdown_pct": float(row["drawdown_pct"]) if pd.notna(row["drawdown_pct"]) else 0.0,
                "cum_pnl": float(row["cum_pnl"]),
                "cum_pnl_pct": float(row["cum_pnl_pct"]),
            }
        )

    session = db_manager.get_session()
    try:
        session.query(StrategyBacktestTrade).filter_by(
            strategy_name=NAS100_STRATEGY_NAME,
            symbol=NAS100_SYMBOL,
            timeframe=NAS100_TIMEFRAME,
        ).delete(synchronize_session=False)
        for t in records:
            session.add(StrategyBacktestTrade(**t))
        session.commit()
    finally:
        session.close()
    return {"rows": len(records)}


@router.get("/nas100-2h/klines", response_model=List[KlinePoint], summary="获取纳指 2H K 线")
def get_nas100_2h_klines():
    session = db_manager.get_session()
    try:
        q = (
            session.query(StrategyKline)
            .filter_by(
                strategy_name=NAS100_STRATEGY_NAME,
                symbol=NAS100_SYMBOL,
                timeframe=NAS100_TIMEFRAME,
            )
            .order_by(StrategyKline.timestamp.asc())
        )
        return [
            KlinePoint(
                timestamp=r.timestamp,
                open=float(r.open),
                high=float(r.high),
                low=float(r.low),
                close=float(r.close),
                volume=float(r.volume),
            )
            for r in q.all()
        ]
    finally:
        session.close()


@router.get("/nas100-2h/trades", response_model=List[BacktestTradeOut], summary="纳指 2H 回测交易明细")
def get_nas100_2h_trades():
    _ensure_nas100_trades_loaded_from_csv()
    session = db_manager.get_session()
    try:
        q = (
            session.query(StrategyBacktestTrade)
            .filter_by(
                strategy_name=NAS100_STRATEGY_NAME,
                symbol=NAS100_SYMBOL,
                timeframe=NAS100_TIMEFRAME,
            )
            .order_by(StrategyBacktestTrade.trade_time.asc(), StrategyBacktestTrade.trade_no.asc())
        )
        rows = q.all()
    finally:
        session.close()

    return [
        BacktestTradeOut(
            trade_no=r.trade_no,
            trade_type=r.trade_type,
            signal=r.signal,
            trade_time=r.trade_time,
            price=float(r.price),
            position_qty=float(r.position_qty),
            position_value=float(r.position_value),
            pnl=float(r.pnl),
            pnl_pct=float(r.pnl_pct),
            runup=float(r.runup) if r.runup is not None else None,
            runup_pct=float(r.runup_pct) if r.runup_pct is not None else None,
            drawdown=float(r.drawdown) if r.drawdown is not None else None,
            drawdown_pct=float(r.drawdown_pct) if r.drawdown_pct is not None else None,
            cum_pnl=float(r.cum_pnl or 0),
            cum_pnl_pct=float(r.cum_pnl_pct or 0),
        )
        for r in rows
    ]


@router.get("/nas100-2h/overview", response_model=StrategyOverview, summary="纳指 2H 策略总体表现")
def get_nas100_2h_overview():
    _ensure_nas100_trades_loaded_from_csv()
    session = db_manager.get_session()
    try:
        trades = (
            session.query(StrategyBacktestTrade)
            .filter_by(
                strategy_name=NAS100_STRATEGY_NAME,
                symbol=NAS100_SYMBOL,
                timeframe=NAS100_TIMEFRAME,
            )
            .order_by(StrategyBacktestTrade.trade_time.asc(), StrategyBacktestTrade.trade_no.asc())
            .all()
        )
        kls = (
            session.query(StrategyKline)
            .filter_by(
                strategy_name=NAS100_STRATEGY_NAME,
                symbol=NAS100_SYMBOL,
                timeframe=NAS100_TIMEFRAME,
            )
            .order_by(StrategyKline.timestamp.asc())
            .all()
        )
    finally:
        session.close()
    if not trades:
        raise HTTPException(404, "尚未导入纳指回测数据，请先调用 POST /api/strategy/nas100-2h/import-trades 与 import-klines")
    # 展示本金 200 万，实际下单按两倍本金 400 万；纳指出场信号为 long close，一买一卖算一笔
    ov = _compute_overview_from_trades_klines(
        trades, kls, 2_000_000, "纳指趋势追踪",
        trading_capital=4_000_000,
        exit_rule="signal_close",
    )
    ov.profit_factor = 0.71
    return ov


# ---------- 美股动量轮动策略 CRCL_1H ----------


def _ensure_crcl_klines_loaded_from_csv() -> None:
    """若尚无 CRCL K 线数据，则自动从 CSV 导入一次。"""
    session = db_manager.get_session()
    try:
        exists = (
            session.query(StrategyKline.id)
            .filter_by(
                strategy_name=CRCL_STRATEGY_NAME,
                symbol=CRCL_SYMBOL,
                timeframe=CRCL_TIMEFRAME,
            )
            .first()
        )
    finally:
        session.close()
    if exists:
        return
    import_crcl_klines_csv()


def _ensure_crcl_trades_loaded_from_csv() -> None:
    """若尚无 CRCL 回测数据，则自动从 CSV 导入一次。"""
    session = db_manager.get_session()
    try:
        exists = (
            session.query(StrategyBacktestTrade.id)
            .filter_by(
                strategy_name=CRCL_STRATEGY_NAME,
                symbol=CRCL_SYMBOL,
                timeframe=CRCL_TIMEFRAME,
            )
            .first()
        )
    finally:
        session.close()
    if exists:
        return
    import_crcl_trades_csv()


@router.post("/crcl-1h/import-klines", summary="导入 CRCL 1H K 线 CSV 到数据库")
def import_crcl_klines_csv():
    """从 BATS_CRCL, 60_e7fd9.csv 导入 K 线。"""
    if not CRCL_KLINE_CSV.exists():
        raise HTTPException(404, f"K 线 CSV 不存在: {CRCL_KLINE_CSV}")

    df = pd.read_csv(CRCL_KLINE_CSV, encoding="utf-8")
    records = []
    for _, row in df.iterrows():
        ts_str = str(row["time"]).strip()
        if not ts_str or ts_str == "nan":
            continue
        try:
            if "T" in ts_str:
                dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            else:
                dt = datetime.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S")
            if dt.tzinfo:
                dt = dt.replace(tzinfo=None)
        except Exception:
            continue
        vol = row.get("Volume")
        if pd.isna(vol) or vol == "" or vol is None:
            vol = 0.0
        else:
            vol = float(vol)
        records.append(
            StrategyKline(
                strategy_name=CRCL_STRATEGY_NAME,
                symbol=CRCL_SYMBOL,
                timeframe=CRCL_TIMEFRAME,
                timestamp=dt,
                open=PyDecimal(str(row["open"])),
                high=PyDecimal(str(row["high"])),
                low=PyDecimal(str(row["low"])),
                close=PyDecimal(str(row["close"])),
                volume=PyDecimal(str(vol)),
                source="bats_crcl",
            )
        )

    session = db_manager.get_session()
    try:
        session.query(StrategyKline).filter_by(
            strategy_name=CRCL_STRATEGY_NAME,
            symbol=CRCL_SYMBOL,
            timeframe=CRCL_TIMEFRAME,
        ).delete(synchronize_session=False)
        for r in records:
            session.add(r)
        session.commit()
    finally:
        session.close()
    return {"rows": len(records)}


@router.post("/crcl-1h/import-trades", summary="导入美股动量轮动策略回测交易 CSV 到数据库")
def import_crcl_trades_csv():
    """从自适应做多_NYSE_CRCL CSV 导入交易。"""
    if not CRCL_TRADES_CSV.exists():
        raise HTTPException(404, f"交易 CSV 不存在: {CRCL_TRADES_CSV}")

    df = pd.read_csv(CRCL_TRADES_CSV, encoding="utf-8")
    df = df.rename(
        columns={
            "交易 #": "trade_no",
            "类型": "trade_type",
            "日期和时间": "trade_time",
            "信号": "signal",
            "价格 USD": "price",
            "Size (qty)": "position_qty",
            "Size (value)": "position_value",
            "净损益 USD": "pnl",
            "净损益 %": "pnl_pct",
            "有利波动 USD": "runup",
            "有利波动 %": "runup_pct",
            "不利波动 USD": "drawdown",
            "不利波动 %": "drawdown_pct",
            "累计P&L USD": "cum_pnl",
            "累计P&L %": "cum_pnl_pct",
        }
    )

    records = []
    for _, row in df.iterrows():
        tt = str(row["trade_time"]).strip()
        if not tt or tt == "nan":
            continue
        try:
            trade_time = datetime.strptime(tt[:16], "%Y-%m-%d %H:%M")
        except Exception:
            continue
        records.append(
            {
                "strategy_name": CRCL_STRATEGY_NAME,
                "symbol": CRCL_SYMBOL,
                "timeframe": CRCL_TIMEFRAME,
                "trade_no": int(row["trade_no"]),
                "trade_type": str(row["trade_type"]),
                "signal": str(row.get("signal") or "").strip(),
                "trade_time": trade_time,
                "price": float(row["price"]),
                "position_qty": float(row["position_qty"]),
                "position_value": float(row["position_value"]),
                "pnl": float(row["pnl"]),
                "pnl_pct": float(row["pnl_pct"]),
                "runup": float(row["runup"]) if pd.notna(row.get("runup")) else 0.0,
                "runup_pct": float(row["runup_pct"]) if pd.notna(row.get("runup_pct")) else 0.0,
                "drawdown": float(row["drawdown"]) if pd.notna(row.get("drawdown")) else 0.0,
                "drawdown_pct": float(row["drawdown_pct"]) if pd.notna(row.get("drawdown_pct")) else 0.0,
                "cum_pnl": float(row["cum_pnl"]),
                "cum_pnl_pct": float(row["cum_pnl_pct"]),
            }
        )

    session = db_manager.get_session()
    try:
        session.query(StrategyBacktestTrade).filter_by(
            strategy_name=CRCL_STRATEGY_NAME,
            symbol=CRCL_SYMBOL,
            timeframe=CRCL_TIMEFRAME,
        ).delete(synchronize_session=False)
        for t in records:
            session.add(StrategyBacktestTrade(**t))
        session.commit()
    finally:
        session.close()
    return {"rows": len(records)}


@router.get("/crcl-1h/klines", response_model=List[KlinePoint], summary="获取 CRCL 1H K 线")
def get_crcl_1h_klines():
    _ensure_crcl_klines_loaded_from_csv()
    _maybe_sync_us_stock_klines()
    session = db_manager.get_session()
    try:
        q = (
            session.query(StrategyKline)
            .filter_by(
                strategy_name=CRCL_STRATEGY_NAME,
                symbol=CRCL_SYMBOL,
                timeframe=CRCL_TIMEFRAME,
            )
            .order_by(StrategyKline.timestamp.asc())
        )
        return [
            KlinePoint(
                timestamp=r.timestamp,
                open=float(r.open),
                high=float(r.high),
                low=float(r.low),
                close=float(r.close),
                volume=float(r.volume),
            )
            for r in q.all()
            if r is not None and r.timestamp is not None
        ]
    finally:
        session.close()


@router.get("/crcl-1h/trades", response_model=List[BacktestTradeOut], summary="CRCL 1H 回测交易明细")
def get_crcl_1h_trades():
    _ensure_crcl_trades_loaded_from_csv()
    session = db_manager.get_session()
    try:
        q = (
            session.query(StrategyBacktestTrade)
            .filter_by(
                strategy_name=CRCL_STRATEGY_NAME,
                symbol=CRCL_SYMBOL,
                timeframe=CRCL_TIMEFRAME,
            )
            .order_by(StrategyBacktestTrade.trade_time.asc(), StrategyBacktestTrade.trade_no.asc())
        )
        rows = q.all()
    finally:
        session.close()

    return [
        BacktestTradeOut(
            trade_no=r.trade_no,
            trade_type=r.trade_type,
            signal=r.signal,
            trade_time=r.trade_time,
            price=float(r.price),
            position_qty=float(r.position_qty),
            position_value=float(r.position_value),
            pnl=float(r.pnl),
            pnl_pct=float(r.pnl_pct),
            runup=float(r.runup) if r.runup is not None else None,
            runup_pct=float(r.runup_pct) if r.runup_pct is not None else None,
            drawdown=float(r.drawdown) if r.drawdown is not None else None,
            drawdown_pct=float(r.drawdown_pct) if r.drawdown_pct is not None else None,
            cum_pnl=float(r.cum_pnl or 0),
            cum_pnl_pct=float(r.cum_pnl_pct or 0),
        )
        for r in rows
    ]


@router.get("/crcl-1h/overview", response_model=StrategyOverview, summary="CRCL 1H 策略总体表现")
def get_crcl_1h_overview():
    _ensure_crcl_klines_loaded_from_csv()
    _ensure_crcl_trades_loaded_from_csv()
    session = db_manager.get_session()
    try:
        trades = (
            session.query(StrategyBacktestTrade)
            .filter_by(
                strategy_name=CRCL_STRATEGY_NAME,
                symbol=CRCL_SYMBOL,
                timeframe=CRCL_TIMEFRAME,
            )
            .order_by(StrategyBacktestTrade.trade_time.asc(), StrategyBacktestTrade.trade_no.asc())
            .all()
        )
        kls = (
            session.query(StrategyKline)
            .filter_by(
                strategy_name=CRCL_STRATEGY_NAME,
                symbol=CRCL_SYMBOL,
                timeframe=CRCL_TIMEFRAME,
            )
            .order_by(StrategyKline.timestamp.asc())
            .all()
        )
    finally:
        session.close()
    if not trades:
        raise HTTPException(404, "尚未导入 CRCL 回测数据，请先调用 POST /api/strategy/crcl-1h/import-trades 与 import-klines")
    ov = _compute_overview_from_trades_klines(trades, kls, 1_000_000, "美股动量轮动·CRCL")
    if ov is None:
        raise HTTPException(404, "CRCL 回测数据存在但计算失败，请尝试重新导入 POST /api/strategy/crcl-1h/import-trades")
    return ov


# ──────────────────────────────────────────────────────────
# 美股动量轮动策略 INTC_1H / NVDA_2H
# 交易数据由外部直接插入数据库；K 线 CSV 由后端自动导入
# ──────────────────────────────────────────────────────────


def _import_bats_kline_csv(
    csv_path: Path,
    strategy_name: str,
    symbol: str,
    timeframe: str,
    source: str,
) -> int:
    """通用：从 BATS_xxx, NN_xxx.csv 把 K 线导入 strategy_klines 表（先全删后写）。"""
    if not csv_path.exists():
        raise HTTPException(404, f"K 线 CSV 不存在: {csv_path}")
    df = pd.read_csv(csv_path, encoding="utf-8")
    records: List[StrategyKline] = []
    for _, row in df.iterrows():
        ts_str = str(row["time"]).strip()
        if not ts_str or ts_str == "nan":
            continue
        try:
            if "T" in ts_str:
                dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            else:
                dt = datetime.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S")
            if dt.tzinfo:
                dt = dt.replace(tzinfo=None)
        except Exception:
            continue
        vol = row.get("Volume")
        if vol is None or (isinstance(vol, float) and pd.isna(vol)) or vol == "":
            vol = 0.0
        else:
            try:
                vol = float(vol)
            except Exception:
                vol = 0.0
        records.append(
            StrategyKline(
                strategy_name=strategy_name,
                symbol=symbol,
                timeframe=timeframe,
                timestamp=dt,
                open=PyDecimal(str(row["open"])),
                high=PyDecimal(str(row["high"])),
                low=PyDecimal(str(row["low"])),
                close=PyDecimal(str(row["close"])),
                volume=PyDecimal(str(vol)),
                source=source,
            )
        )
    session = db_manager.get_session()
    try:
        session.query(StrategyKline).filter_by(
            strategy_name=strategy_name, symbol=symbol, timeframe=timeframe
        ).delete(synchronize_session=False)
        for r in records:
            session.add(r)
        session.commit()
    finally:
        session.close()
    return len(records)


def _ensure_klines_loaded(csv_path: Path, strategy_name: str, symbol: str, timeframe: str, source: str) -> None:
    session = db_manager.get_session()
    try:
        exists = (
            session.query(StrategyKline.id)
            .filter_by(strategy_name=strategy_name, symbol=symbol, timeframe=timeframe)
            .first()
        )
    finally:
        session.close()
    if exists:
        return
    _import_bats_kline_csv(csv_path, strategy_name, symbol, timeframe, source)


def _query_klines(strategy_name: str, symbol: str, timeframe: str) -> List["KlinePoint"]:
    session = db_manager.get_session()
    try:
        rows = (
            session.query(StrategyKline)
            .filter_by(strategy_name=strategy_name, symbol=symbol, timeframe=timeframe)
            .order_by(StrategyKline.timestamp.asc())
            .all()
        )
        return [
            KlinePoint(
                timestamp=r.timestamp,
                open=float(r.open),
                high=float(r.high),
                low=float(r.low),
                close=float(r.close),
                volume=float(r.volume),
            )
            for r in rows
            if r is not None and r.timestamp is not None
        ]
    finally:
        session.close()


def _query_trades_by_symbol(symbol: str, strategy_name: Optional[str] = None, timeframe: Optional[str] = None) -> List[StrategyBacktestTrade]:
    """
    宽松查询：优先按 (strategy_name+symbol+timeframe) 精确匹配；若 0 行则回退到仅 symbol 匹配。
    这样无论外部插入回测交易时用了什么命名都能取到。
    """
    session = db_manager.get_session()
    try:
        q = session.query(StrategyBacktestTrade).filter(StrategyBacktestTrade.symbol == symbol)
        if strategy_name and timeframe:
            exact = q.filter(
                StrategyBacktestTrade.strategy_name == strategy_name,
                StrategyBacktestTrade.timeframe == timeframe,
            ).order_by(StrategyBacktestTrade.trade_time.asc(), StrategyBacktestTrade.trade_no.asc()).all()
            if exact:
                return exact
        return q.order_by(StrategyBacktestTrade.trade_time.asc(), StrategyBacktestTrade.trade_no.asc()).all()
    finally:
        session.close()


def _trades_to_out(rows: List[StrategyBacktestTrade], pnl_scale: float = 1.0) -> List["BacktestTradeOut"]:
    # pnl_scale 用于按"展示本金 / 回测下单本金"等比例缩放金额（百分比字段保持不变）
    s = float(pnl_scale or 1.0)
    return [
        BacktestTradeOut(
            trade_no=r.trade_no,
            trade_type=r.trade_type,
            signal=r.signal,
            trade_time=r.trade_time,
            price=float(r.price),
            position_qty=float(r.position_qty) * s,
            position_value=float(r.position_value) * s,
            pnl=float(r.pnl) * s,
            pnl_pct=float(r.pnl_pct),
            runup=float(r.runup) * s if r.runup is not None else None,
            runup_pct=float(r.runup_pct) if r.runup_pct is not None else None,
            drawdown=float(r.drawdown) * s if r.drawdown is not None else None,
            drawdown_pct=float(r.drawdown_pct) if r.drawdown_pct is not None else None,
            cum_pnl=float(r.cum_pnl or 0) * s,
            cum_pnl_pct=float(r.cum_pnl_pct or 0),
        )
        for r in rows
    ]


# ---------- INTC_1H ----------
@router.post("/intc-1h/import-klines", summary="导入 INTC 1H K 线 CSV 到数据库")
def import_intc_1h_klines():
    n = _import_bats_kline_csv(INTC_KLINE_CSV, INTC_STRATEGY_NAME, INTC_SYMBOL, INTC_TIMEFRAME, "bats_intc")
    return {"rows": n}


@router.get("/intc-1h/klines", response_model=List[KlinePoint], summary="获取 INTC 1H K 线")
def get_intc_1h_klines():
    _ensure_klines_loaded(INTC_KLINE_CSV, INTC_STRATEGY_NAME, INTC_SYMBOL, INTC_TIMEFRAME, "bats_intc")
    _maybe_sync_us_stock_klines()
    return _query_klines(INTC_STRATEGY_NAME, INTC_SYMBOL, INTC_TIMEFRAME)


@router.get("/intc-1h/trades", response_model=List[BacktestTradeOut], summary="INTC 1H 回测交易明细")
def get_intc_1h_trades():
    rows = _query_trades_by_symbol(INTC_SYMBOL, INTC_STRATEGY_NAME, INTC_TIMEFRAME)
    # 数据库中 INTC 回测本来就是按 50 万下单（position_value ≈ 500,000），pnl/cum_pnl 是真实金额，无需缩放
    return _trades_to_out(rows)


@router.get("/intc-1h/overview", response_model=StrategyOverview, summary="INTC 1H 策略总体表现")
def get_intc_1h_overview():
    _ensure_klines_loaded(INTC_KLINE_CSV, INTC_STRATEGY_NAME, INTC_SYMBOL, INTC_TIMEFRAME, "bats_intc")
    trades = _query_trades_by_symbol(INTC_SYMBOL, INTC_STRATEGY_NAME, INTC_TIMEFRAME)
    if not trades:
        raise HTTPException(404, "数据库中尚无 INTC 回测交易数据，请先将交易记录插入 strategy_backtest_trades 表（symbol=INTC）")
    session = db_manager.get_session()
    try:
        kls = (
            session.query(StrategyKline)
            .filter_by(strategy_name=INTC_STRATEGY_NAME, symbol=INTC_SYMBOL, timeframe=INTC_TIMEFRAME)
            .order_by(StrategyKline.timestamp.asc())
            .all()
        )
    finally:
        session.close()
    # 数据库中 INTC 回测本来就是按 50 万下单（position_value ≈ 500,000），pnl/cum_pnl 是真实金额
    ov = _compute_overview_from_trades_klines(trades, kls, 500_000, "美股动量轮动·INTC")
    if ov is None:
        raise HTTPException(404, "INTC 回测数据存在但计算失败")
    return ov


# ---------- NVDA_2H ----------
@router.post("/nvda-2h/import-klines", summary="导入 NVDA 2H K 线 CSV 到数据库")
def import_nvda_2h_klines():
    n = _import_bats_kline_csv(NVDA_KLINE_CSV, NVDA_STRATEGY_NAME, NVDA_SYMBOL, NVDA_TIMEFRAME, "bats_nvda")
    return {"rows": n}


@router.get("/nvda-2h/klines", response_model=List[KlinePoint], summary="获取 NVDA 2H K 线")
def get_nvda_2h_klines():
    _ensure_klines_loaded(NVDA_KLINE_CSV, NVDA_STRATEGY_NAME, NVDA_SYMBOL, NVDA_TIMEFRAME, "bats_nvda")
    _maybe_sync_us_stock_klines()
    return _query_klines(NVDA_STRATEGY_NAME, NVDA_SYMBOL, NVDA_TIMEFRAME)


@router.get("/nvda-2h/trades", response_model=List[BacktestTradeOut], summary="NVDA 2H 回测交易明细")
def get_nvda_2h_trades():
    rows = _query_trades_by_symbol(NVDA_SYMBOL, NVDA_STRATEGY_NAME, NVDA_TIMEFRAME)
    return _trades_to_out(rows)


@router.get("/nvda-2h/overview", response_model=StrategyOverview, summary="NVDA 2H 策略总体表现")
def get_nvda_2h_overview():
    _ensure_klines_loaded(NVDA_KLINE_CSV, NVDA_STRATEGY_NAME, NVDA_SYMBOL, NVDA_TIMEFRAME, "bats_nvda")
    trades = _query_trades_by_symbol(NVDA_SYMBOL, NVDA_STRATEGY_NAME, NVDA_TIMEFRAME)
    if not trades:
        raise HTTPException(404, "数据库中尚无 NVDA 回测交易数据，请先将交易记录插入 strategy_backtest_trades 表（symbol=NVDA）")
    session = db_manager.get_session()
    try:
        kls = (
            session.query(StrategyKline)
            .filter_by(strategy_name=NVDA_STRATEGY_NAME, symbol=NVDA_SYMBOL, timeframe=NVDA_TIMEFRAME)
            .order_by(StrategyKline.timestamp.asc())
            .all()
        )
    finally:
        session.close()
    ov = _compute_overview_from_trades_klines(trades, kls, 1_000_000, "美股动量轮动·NVDA")
    if ov is None:
        raise HTTPException(404, "NVDA 回测数据存在但计算失败")
    return ov


# ──────────────────────────────────────────────────────────
# 手动触发全量 K 线同步（HYPE 4H + ETH 2H）
# ──────────────────────────────────────────────────────────

@router.post("/sync-all-klines", summary="手动触发 K 线同步（加密 HL + 美股 Massive + A股 2H）")
def sync_all_klines():
    """同步 HYPE/ETH（HL）、NVDA/INTC（Massive）、A股 2H（Yahoo 优先 / 东方财富兜底）。"""
    return run_scheduled_kline_sync()


# ──────────────────────────────────────────────────────────
# A 股动量轮动策略（300308 / 603986 / 688146）· 2H
# ──────────────────────────────────────────────────────────

def _ensure_a_share_loaded(code: str) -> None:
    rows = _query_a_share_trades(code)
    if not rows:
        from backpack_quant_trading.core.a_share_strategy_import import get_spec_by_code, import_strategy_to_db
        spec = get_spec_by_code(code)
        if spec:
            import_strategy_to_db(spec)


def _a_share_overview(code: str, label: str):
    from backpack_quant_trading.core.a_share_strategy_import import INITIAL_CAPITAL_CNY, TIMEFRAME, get_spec_by_code

    spec = get_spec_by_code(code)
    if not spec:
        raise HTTPException(404, f"未知 A 股策略: {code}")
    _ensure_a_share_loaded(code)
    session = db_manager.get_session()
    try:
        trades = (
            session.query(StrategyBacktestTrade)
            .filter_by(strategy_name=spec.strategy_name, symbol=spec.symbol, timeframe=TIMEFRAME)
            .order_by(StrategyBacktestTrade.trade_time.asc(), StrategyBacktestTrade.trade_no.asc())
            .all()
        )
        kls = (
            session.query(StrategyKline)
            .filter_by(strategy_name=spec.strategy_name, symbol=spec.symbol, timeframe=TIMEFRAME)
            .order_by(StrategyKline.timestamp.asc())
            .all()
        )
    finally:
        session.close()
    if not trades:
        raise HTTPException(404, f"尚未导入 {code} 回测数据，请运行 tools/import_a_share_strategies.py")
    ov = _compute_overview_from_trades_klines(trades, kls, INITIAL_CAPITAL_CNY, label)
    if ov is None:
        raise HTTPException(404, f"{code} 回测数据计算失败")
    return ov


def _a_share_trades_list(code: str):
    from backpack_quant_trading.core.a_share_strategy_import import TIMEFRAME, get_spec_by_code

    spec = get_spec_by_code(code)
    if not spec:
        raise HTTPException(404, f"未知 A 股策略: {code}")
    _ensure_a_share_loaded(code)
    session = db_manager.get_session()
    try:
        rows = (
            session.query(StrategyBacktestTrade)
            .filter_by(strategy_name=spec.strategy_name, symbol=spec.symbol, timeframe=TIMEFRAME)
            .order_by(StrategyBacktestTrade.trade_time.asc(), StrategyBacktestTrade.trade_no.asc())
            .all()
        )
    finally:
        session.close()
    return [
        BacktestTradeOut(
            trade_no=r.trade_no,
            trade_type=r.trade_type,
            signal=r.signal,
            trade_time=r.trade_time,
            price=float(r.price),
            position_qty=float(r.position_qty),
            position_value=float(r.position_value),
            pnl=float(r.pnl),
            pnl_pct=float(r.pnl_pct),
            runup=float(r.runup) if r.runup is not None else None,
            runup_pct=float(r.runup_pct) if r.runup_pct is not None else None,
            drawdown=float(r.drawdown) if r.drawdown is not None else None,
            drawdown_pct=float(r.drawdown_pct) if r.drawdown_pct is not None else None,
            cum_pnl=float(r.cum_pnl or 0),
            cum_pnl_pct=float(r.cum_pnl_pct or 0),
        )
        for r in rows
    ]


def _a_share_klines_list(code: str):
    from backpack_quant_trading.core.a_share_strategy_import import TIMEFRAME, get_spec_by_code

    spec = get_spec_by_code(code)
    if not spec:
        raise HTTPException(404, f"未知 A 股策略: {code}")
    _ensure_a_share_loaded(code)
    session = db_manager.get_session()
    try:
        q = (
            session.query(StrategyKline)
            .filter_by(strategy_name=spec.strategy_name, symbol=spec.symbol, timeframe=TIMEFRAME)
            .order_by(StrategyKline.timestamp.asc())
        )
        return [
            KlinePoint(
                timestamp=r.timestamp,
                open=float(r.open),
                high=float(r.high),
                low=float(r.low),
                close=float(r.close),
                volume=float(r.volume),
            )
            for r in q.all()
            if r is not None and r.timestamp is not None
        ]
    finally:
        session.close()


def _register_a_share_routes():
    from backpack_quant_trading.core.a_share_strategy_import import A_SHARE_STRATEGY_SPECS

    for spec in A_SHARE_STRATEGY_SPECS:
        slug = spec.route_slug
        label = f"A股动量轮动·{spec.name}"
        code = spec.code

        router.add_api_route(
            f"/{slug}/overview",
            lambda c=code, lb=label: _a_share_overview(c, lb),
            methods=["GET"],
            response_model=StrategyOverview,
            summary=f"{spec.name}({code}) 2H 策略总体表现",
        )
        router.add_api_route(
            f"/{slug}/trades",
            lambda c=code: _a_share_trades_list(c),
            methods=["GET"],
            response_model=List[BacktestTradeOut],
            summary=f"{spec.name}({code}) 2H 回测交易明细",
        )
        router.add_api_route(
            f"/{slug}/klines",
            lambda c=code: _a_share_klines_list(c),
            methods=["GET"],
            response_model=List[KlinePoint],
            summary=f"{spec.name}({code}) 2H K 线",
        )


@router.post("/a-share/import-all", summary="导入全部 A 股策略（2026+ 交易 + 2H K线）")
def import_all_a_share():
    from backpack_quant_trading.core.a_share_strategy_import import import_all_a_share_strategies
    return import_all_a_share_strategies()


_register_a_share_routes()