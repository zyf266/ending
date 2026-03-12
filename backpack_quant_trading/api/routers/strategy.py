from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from decimal import Decimal as PyDecimal

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

STRATEGY_NAME = "ETH_2H_TREND"
SYMBOL = "ETHUSDT"
TIMEFRAME = "2h"

# 注意：CSV 放在项目根目录（与 backpack_quant_trading 同级）
PROJECT_ROOT = Path(__file__).resolve().parents[3]
CSV_PATH = PROJECT_ROOT / "2h趋势策略_(隐藏优化版)_BINANCE_ETHUSDT_2026-03-05_86efa.csv"

# 大宗（黄金）策略 PAXG_2H
PAXG_STRATEGY_NAME = "PAXG_2H"
PAXG_SYMBOL = "PAXGUSDT"
PAXG_TIMEFRAME = "2H"
PAXG_KLINE_CSV = PROJECT_ROOT / "FOREXCOM_XAUUSD, 120_13e88.csv"
PAXG_TRADES_CSV = PROJECT_ROOT / "【沐龙】黄金波动率追踪策略_2H_FOREXCOM_XAUUSD_2026-03-06_c5de1.csv"

# 纳指策略 NAS100_2H
NAS100_STRATEGY_NAME = "NAS100_2H"
NAS100_SYMBOL = "NAS100USD"
NAS100_TIMEFRAME = "2H"
NAS100_KLINE_CSV = PROJECT_ROOT / "FX_NAS100, 120_0946a.csv"
NAS100_TRADES_CSV = PROJECT_ROOT / "【沐龙】纳指趋势追踪增强策略_FX_NAS100_2026-03-06_87155.csv"


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
    profit_factor: float
    buy_hold_return_pct: float
    buy_hold_profit: float
    edge_return_pct: float
    annual_excess_return_pct: float
    total_trades: int
    start_date: datetime
    end_date: datetime


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
        for t in records:
            session.add(StrategyBacktestTrade(**t))
        session.commit()
    finally:
        session.close()

    return {"rows": len(records)}


@router.post("/eth-2h/sync-klines", summary="同步 ETH 2H K 线到 MySQL")
def sync_eth_2h_klines():
    session = db_manager.get_session()
    try:
        last = (
            session.query(StrategyKline)
            .filter_by(strategy_name=STRATEGY_NAME, symbol=SYMBOL, timeframe=TIMEFRAME)
            .order_by(StrategyKline.timestamp.desc())
            .first()
        )
        last_ts = last.timestamp if last else None
    finally:
        session.close()

    rows = []

    if last_ts is None:
        # 从 2022-01-01 00:00:00 UTC 起分批次拉取，直到当前
        start_ms = int(datetime(2022, 1, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
        data = fetch_binance_klines_from_start(SYMBOL, TIMEFRAME, start_ms, batch_size=1000)
        if not data:
            raise HTTPException(500, "从币安获取历史 K 线失败（从 2022-01-01 起）")
        for bar in data:
            rows.append(
                StrategyKline(
                    strategy_name=STRATEGY_NAME,
                    symbol=SYMBOL,
                    timeframe=TIMEFRAME,
                    timestamp=datetime.fromtimestamp(bar["time"] / 1000),
                    open=PyDecimal(str(bar["open"])),
                    high=PyDecimal(str(bar["high"])),
                    low=PyDecimal(str(bar["low"])),
                    close=PyDecimal(str(bar["close"])),
                    volume=PyDecimal(str(bar["volume"])),
                    source="binance_futures",
                )
            )
    else:
        data = fetch_binance_klines(SYMBOL, TIMEFRAME, limit=200)
        if not data:
            raise HTTPException(500, "从币安获取最新 K 线失败")
        for bar in data:
            ts = datetime.fromtimestamp(bar["open_time"] / 1000)
            if ts <= last_ts:
                continue
            rows.append(
                StrategyKline(
                    strategy_name=STRATEGY_NAME,
                    symbol=SYMBOL,
                    timeframe=TIMEFRAME,
                    timestamp=ts,
                    open=PyDecimal(str(bar["open"])),
                    high=PyDecimal(str(bar["high"])),
                    low=PyDecimal(str(bar["low"])),
                    close=PyDecimal(str(bar["close"])),
                    volume=PyDecimal(str(bar["volume"])),
                    source="binance_futures",
                )
            )

    if not rows:
        return {"inserted": 0}

    session = db_manager.get_session()
    try:
        for r in rows:
            session.add(r)
        session.commit()
    finally:
        session.close()

    return {"inserted": len(rows)}


@router.get("/eth-2h/klines", response_model=List[KlinePoint], summary="获取 ETH 2H K 线")
def get_eth_2h_klines():
    session = db_manager.get_session()
    try:
        q = (
            session.query(StrategyKline)
            .filter_by(strategy_name=STRATEGY_NAME, symbol=SYMBOL, timeframe=TIMEFRAME)
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

    if not trades:
        raise HTTPException(404, "尚未导入回测数据")

    initial_capital = 30_000_000
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
    gross_loss = abs(sum(loss)) or 1e-9
    profit_factor = gross_profit / gross_loss

    # 买入并持有：用 K 线首尾价格近似
    if kls:
        first_close = float(kls[0].close)
        last_close = float(kls[-1].close)
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
        profit_factor=round(profit_factor, 2),
        buy_hold_return_pct=round(buy_hold_return_pct, 2),
        buy_hold_profit=round(buy_hold_profit, 2),
        edge_return_pct=round(edge_return_pct, 2),
        annual_excess_return_pct=round(annual_excess_return_pct, 2),
        total_trades=total_trades,
        start_date=trades[0].trade_time,
        end_date=trades[-1].trade_time,
    )


# ---------- 大宗（黄金）策略 PAXG_2H ----------


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
        for t in records:
            session.add(StrategyBacktestTrade(**t))
        session.commit()
    finally:
        session.close()
    return {"rows": len(records)}


@router.get("/paxg-2h/klines", response_model=List[KlinePoint], summary="获取大宗 2H K 线")
def get_paxg_2h_klines():
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


def _compute_overview_from_trades_klines(trades, kls, initial_capital, strategy_label, trading_capital=None, exit_rule=None):
    """
    通用概览计算。initial_capital 为展示用本金；若 trading_capital 有值（两倍本金策略），
    权益曲线按 trading_capital + cum_pnl 算，收益百分比按 initial_capital 算。
    exit_rule: None=按类型+信号判断出场；"signal_close"=仅用信号含 close 判出场（纳指 long close）。
    """
    if not trades:
        return None
    base = (trading_capital if trading_capital is not None else initial_capital)
    equity = [base + float(r.cum_pnl or 0) for r in trades]
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
    for r in base_trades:
        try:
            key = int(getattr(r, "trade_no", 0))
        except Exception:
            key = getattr(r, "trade_no", None)
        trade_pnls[key] = float(r.pnl)
    profits = list(trade_pnls.values())
    win = [p for p in profits if p > 0]
    loss = [p for p in profits if p < 0]
    total_trades = len(profits)
    win_rate_pct = (len(win) / total_trades * 100) if total_trades else 0.0
    gross_profit = sum(win) or 0.0
    gross_loss = abs(sum(loss)) or 1e-9
    profit_factor = gross_profit / gross_loss
    buy_hold_return_pct = 0.0
    if kls:
        first_close = float(kls[0].close)
        last_close = float(kls[-1].close)
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
        profit_factor=round(profit_factor, 2),
        buy_hold_return_pct=round(buy_hold_return_pct, 2),
        buy_hold_profit=round(buy_hold_profit, 2),
        edge_return_pct=round(edge_return_pct, 2),
        annual_excess_return_pct=round(annual_excess_return_pct, 2),
        total_trades=total_trades,
        start_date=trades[0].trade_time,
        end_date=trades[-1].trade_time,
    )


@router.get("/paxg-2h/overview", response_model=StrategyOverview, summary="大宗 2H 策略总体表现")
def get_paxg_2h_overview():
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
    # 展示本金 200 万，实际下单按两倍本金 400 万
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
    return _compute_overview_from_trades_klines(
        trades, kls, 2_000_000, "纳指趋势追踪",
        trading_capital=4_000_000,
        exit_rule="signal_close",
    )