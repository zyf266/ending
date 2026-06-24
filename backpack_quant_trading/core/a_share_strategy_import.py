"""
A 股量化实盘：从 TradingView 回测 CSV 提取交易，按研报次日开盘价起算、200 万 CNY 全仓滚仓复利重算，
并从 Yahoo 拉取 K 线（60m 聚合为 2H）写入 strategy_kline / strategy_backtest_trade。
"""
from __future__ import annotations

import calendar
import logging
import os
import time
import urllib.parse
from dataclasses import dataclass
from datetime import date, datetime
from datetime import time as dt_time
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests

from backpack_quant_trading.database.models import db_manager

logger = logging.getLogger(__name__)

INITIAL_CAPITAL_CNY = 2_000_000.0
TRADE_CUTOFF = datetime(2026, 1, 1)
TIMEFRAME = "2H"
YAHOO_CHART_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"
YAHOO_WARMUP_URL = "https://finance.yahoo.com/"
DEFAULT_USD_CNY = 7.25


def _proxy_env_value() -> str:
    for key in (
        "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY",
        "https_proxy", "http_proxy", "all_proxy",
    ):
        val = os.environ.get(key, "").strip()
        if val:
            return val
    return ""


def _yahoo_trust_env() -> bool:
    if os.environ.get("STOCK_NEWS_DISABLE_PROXY", "").lower() in ("1", "true", "yes"):
        return False
    if os.environ.get("STOCK_NEWS_FORCE_SYSTEM_PROXY", "").lower() in ("1", "true", "yes"):
        return True
    return bool(_proxy_env_value())


def _yahoo_headers() -> Dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://finance.yahoo.com/",
        "Origin": "https://finance.yahoo.com",
    }


def _yahoo_session() -> requests.Session:
    """云服务器配置 HTTP_PROXY/HTTPS_PROXY 后自动走代理访问 Yahoo。"""
    sess = requests.Session()
    sess.trust_env = _yahoo_trust_env()
    return sess


def _direct_get(url: str, **kwargs) -> requests.Response:
    """国内源（东方财富）直连，不走代理。"""
    sess = requests.Session()
    sess.trust_env = False
    kwargs.setdefault("timeout", 20)
    return sess.get(url, **kwargs)


def _yahoo_get(url: str, **kwargs) -> requests.Response:
    sess = _yahoo_session()
    try:
        sess.get(YAHOO_WARMUP_URL, headers=_yahoo_headers(), timeout=10)
    except Exception:
        pass
    kwargs.setdefault("timeout", 25)
    headers = {**_yahoo_headers(), **kwargs.pop("headers", {})}
    return sess.get(url, headers=headers, **kwargs)


_CSV_COL_MAP = {
    "交易编号": "trade_no",
    "类型": "trade_type",
    "日期和时间": "trade_time",
    "信号": "signal",
    "价格 CNY": "price",
    "大小（数量）": "position_qty",
    "大小（价值）": "position_value",
    "净损益 CNY": "pnl",
    "净损益 %": "pnl_pct",
    "有利波动 CNY": "runup",
    "有利波动 %": "runup_pct",
    "不利波动 CNY": "drawdown",
    "不利波动 %": "drawdown_pct",
    "累计损益 CNY": "cum_pnl",
    "累计损益 %": "cum_pnl_pct",
}


@dataclass(frozen=True)
class AShareStrategySpec:
    code: str
    name: str
    strategy_name: str
    symbol: str
    yahoo_ticker: str
    csv_filename: str
    route_slug: str  # e.g. 300308-2h
    report_date: date  # 研报发布日
    trade_start_date: date  # 交易起始日（以当日开盘价入场）
    initial_capital_cny: float = INITIAL_CAPITAL_CNY


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


A_SHARE_STRATEGY_SPECS: Tuple[AShareStrategySpec, ...] = (
    AShareStrategySpec(
        code="300308",
        name="中际旭创",
        strategy_name="300308_2H",
        symbol="300308",
        yahoo_ticker="300308.SZ",
        csv_filename="300308.csv",
        route_slug="300308-2h",
        report_date=date(2026, 1, 29),
        trade_start_date=date(2026, 1, 30),
        initial_capital_cny=2_000_000.0,
    ),
    AShareStrategySpec(
        code="603986",
        name="兆易创新",
        strategy_name="603986_2H",
        symbol="603986",
        yahoo_ticker="603986.SS",
        csv_filename="603986.csv",
        route_slug="603986-2h",
        report_date=date(2026, 1, 29),
        trade_start_date=date(2026, 1, 30),
        initial_capital_cny=2_000_000.0,
    ),
    AShareStrategySpec(
        code="688146",
        name="中船特气",
        strategy_name="688146_2H",
        symbol="688146",
        yahoo_ticker="688146.SS",
        csv_filename="688146.csv",
        route_slug="688146-2h",
        report_date=date(2026, 5, 11),
        trade_start_date=date(2026, 5, 12),
        initial_capital_cny=500_000.0,
    ),
    AShareStrategySpec(
        code="002837",
        name="英维克",
        strategy_name="002837_2H",
        symbol="002837",
        yahoo_ticker="002837.SZ",
        csv_filename="002837.csv",
        route_slug="002837-2h",
        report_date=date(2026, 1, 29),
        trade_start_date=date(2026, 1, 30),
        initial_capital_cny=500_000.0,
    ),
)


def get_spec_by_code(code: str) -> Optional[AShareStrategySpec]:
    c = str(code or "").strip()
    for s in A_SHARE_STRATEGY_SPECS:
        if s.code == c or s.route_slug == c:
            return s
    return None


def get_usd_cny_rate() -> float:
    """Yahoo USDCNY=X 最新价；失败则用默认 7.25。"""
    try:
        enc = urllib.parse.quote("USDCNY=X", safe="")
        url = f"{YAHOO_CHART_BASE}/{enc}"
        r = _yahoo_get(
            url,
            params={"range": "5d", "interval": "1d"},
        )
        r.raise_for_status()
        res = r.json()["chart"]["result"][0]
        closes = (res.get("indicators") or {}).get("quote", [{}])[0].get("close") or []
        for c in reversed(closes):
            if c is not None and float(c) > 0:
                return float(c)
    except Exception as exc:
        logger.warning("USDCNY 汇率获取失败，使用默认 %.2f: %s", DEFAULT_USD_CNY, exc)
    return DEFAULT_USD_CNY


def cny_to_usd(amount: float, rate: Optional[float] = None) -> float:
    r = float(rate or get_usd_cny_rate())
    if r <= 0:
        r = DEFAULT_USD_CNY
    return float(amount) / r


def _read_trades_csv(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    df = df.rename(columns={k: v for k, v in _CSV_COL_MAP.items() if k in df.columns})
    missing = [c for c in _CSV_COL_MAP.values() if c not in df.columns]
    if missing:
        raise ValueError(f"CSV 列不完整 {csv_path.name}: 缺少 {missing}")
    df["trade_time"] = pd.to_datetime(df["trade_time"], errors="coerce")
    df = df.dropna(subset=["trade_time", "trade_no"])
    return df


def _is_entry(tt: str) -> bool:
    return "进场" in str(tt or "")


def _is_exit(tt: str) -> bool:
    return "出场" in str(tt or "")


def trade_start_datetime(spec: AShareStrategySpec) -> datetime:
    """研报次日 09:30 作为交易起点。"""
    return datetime.combine(spec.trade_start_date, dt_time(9, 30))


def kline_chart_warmup_start(trade_start: datetime) -> datetime:
    """K 线展示起点：交易起始日前推 1 个自然月（如 4/7 → 3/7），保留前置走势上下文。"""
    d = trade_start.date()
    year, month = d.year, d.month - 1
    if month < 1:
        month = 12
        year -= 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return datetime.combine(date(year, month, day), trade_start.time())


def _sina_symbol(code: str) -> str:
    c = str(code or "").strip()
    if c.startswith("6"):
        return f"sh{c}"
    return f"sz{c}"


@dataclass(frozen=True)
class DailyOpenQuote:
    price: float
    trade_date: date  # 实际成交交易日（休市则顺延）


def fetch_daily_open_price(code: str, on_date: date) -> DailyOpenQuote:
    """
    取指定交易日开盘价；若当日休市则顺延至下一交易日。
    优先新浪日线（国内直连），失败再试东方财富。
    """
    px, used = _fetch_sina_daily_open(code, on_date)
    if px is not None and used is not None:
        if used != on_date:
            logger.info("%s %s 休市，使用下一交易日 %s 开盘价 %.4f", code, on_date, used, px)
        return DailyOpenQuote(price=px, trade_date=used)
    px, used = _fetch_eastmoney_daily_open(code, on_date)
    if px is not None and used is not None:
        if used != on_date:
            logger.info("%s %s 休市，使用下一交易日 %s 开盘价 %.4f", code, on_date, used, px)
        return DailyOpenQuote(price=px, trade_date=used)
    raise ValueError(f"无法获取 {code} {on_date} 及后续交易日开盘价")


def _fetch_sina_daily_open(code: str, on_date: date) -> Tuple[Optional[float], Optional[date]]:
    sym = _sina_symbol(code)
    try:
        r = _direct_get(
            "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData",
            params={"symbol": sym, "scale": 240, "ma": "no", "datalen": 400},
            headers={"User-Agent": "Mozilla/5.0"},
        )
        r.raise_for_status()
        rows = r.json()
    except Exception as exc:
        logger.warning("新浪日线失败 %s: %s", code, exc)
        return None, None

    by_day: Dict[str, float] = {}
    for row in rows or []:
        day = str(row.get("day") or "")[:10]
        if not day:
            continue
        try:
            by_day[day] = float(row["open"])
        except (TypeError, ValueError, KeyError):
            continue

    for i in range(0, 15):
        d = on_date.toordinal() + i
        ds = date.fromordinal(d).isoformat()
        if ds in by_day:
            return by_day[ds], date.fromordinal(d)
    return None, None


def _fetch_eastmoney_daily_open(code: str, on_date: date) -> Tuple[Optional[float], Optional[date]]:
    secid = _eastmoney_secid(code)
    if not secid:
        return None, None

    beg = on_date.strftime("%Y%m%d")
    end = date.fromordinal(on_date.toordinal() + 14).strftime("%Y%m%d")
    try:
        r = _direct_get(
            "https://push2his.eastmoney.com/api/qt/stock/kline/get",
            params={
                "secid": secid,
                "klt": "101",
                "fqt": "1",
                "beg": beg,
                "end": end,
                "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                "ut": "fa5fd1943c7b386f172d6893dbfba10b",
            },
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"},
        )
        r.raise_for_status()
        klines = ((r.json() or {}).get("data") or {}).get("klines") or []
    except Exception as exc:
        logger.warning("东方财富日线失败 %s: %s", code, exc)
        return None, None

    by_day: Dict[str, float] = {}
    for line in klines:
        parts = str(line).split(",")
        if len(parts) < 6:
            continue
        try:
            by_day[parts[0][:10]] = float(parts[1])
        except (ValueError, TypeError):
            continue

    for i in range(0, 15):
        d = on_date.toordinal() + i
        ds = date.fromordinal(d).isoformat()
        if ds in by_day:
            return by_day[ds], date.fromordinal(d)
    return None, None


def recompound_trades_from_csv(
    csv_path: Path,
    *,
    initial_capital: float = INITIAL_CAPITAL_CNY,
    trade_start: Optional[datetime] = None,
    open_price_on_start: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """
    提取出场时间 >= trade_start 的完整交易，按时间顺序用全仓复利重算。
    首笔若 CSV 进场早于 trade_start，则改为 trade_start 当日开盘价入场。
    """
    if trade_start is None:
        trade_start = TRADE_CUTOFF
    ts = trade_start.replace(tzinfo=None)

    df = _read_trades_csv(csv_path)
    pairs: List[Tuple[pd.Series, pd.Series]] = []

    for trade_no, grp in df.groupby("trade_no"):
        legs = grp.sort_values("trade_time")
        entries = legs[legs["trade_type"].map(_is_entry)]
        exits = legs[legs["trade_type"].map(_is_exit)]
        if entries.empty or exits.empty:
            continue
        entry = entries.iloc[0]
        exit_row = exits.iloc[-1]
        if exit_row["trade_time"].to_pydatetime().replace(tzinfo=None) < ts:
            continue
        pairs.append((entry, exit_row))

    pairs.sort(key=lambda x: x[1]["trade_time"])

    capital = float(initial_capital)
    records: List[Dict[str, Any]] = []
    first_trade = True

    for entry, exit_row in pairs:
        entry_time = entry["trade_time"].to_pydatetime().replace(tzinfo=None)
        entry_price = float(entry["price"])
        entry_type = str(entry["trade_type"])
        entry_signal = str(entry.get("signal") or "").strip()

        if first_trade and entry_time < ts:
            if open_price_on_start is None or open_price_on_start <= 0:
                raise ValueError(f"首笔交易需 {ts.date()} 开盘价，但未提供有效 open_price_on_start")
            entry_price = float(open_price_on_start)
            entry_time = ts
            entry_signal = "研报次日开盘"
        first_trade = False

        exit_price = float(exit_row["price"])
        if entry_price <= 0:
            continue

        position_value = capital
        position_qty = position_value / entry_price
        pnl = position_qty * (exit_price - entry_price)
        pnl_pct = (exit_price / entry_price - 1.0) * 100.0

        orig_pv = float(entry["position_value"]) or position_value
        scale = position_value / orig_pv if orig_pv > 0 else 1.0

        def _scale(v: Any) -> float:
            try:
                return float(v or 0) * scale
            except (TypeError, ValueError):
                return 0.0

        runup = _scale(exit_row.get("runup"))
        drawdown = _scale(exit_row.get("drawdown"))
        runup_pct = float(exit_row.get("runup_pct") or 0)
        drawdown_pct = float(exit_row.get("drawdown_pct") or 0)

        capital += pnl
        cum_pnl = capital - initial_capital
        cum_pnl_pct = cum_pnl / initial_capital * 100.0

        base = {
            "trade_no": int(entry["trade_no"]),
            "position_qty": round(position_qty, 4),
            "position_value": round(position_value, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 4),
            "runup": round(runup, 2),
            "runup_pct": round(runup_pct, 4),
            "drawdown": round(drawdown, 2),
            "drawdown_pct": round(drawdown_pct, 4),
            "cum_pnl": round(cum_pnl, 2),
            "cum_pnl_pct": round(cum_pnl_pct, 4),
        }

        entry_leg = {
            **base,
            "trade_type": entry_type,
            "signal": entry_signal,
            "trade_time": entry_time,
            "price": entry_price,
        }
        exit_leg = {
            **base,
            "trade_type": str(exit_row["trade_type"]),
            "signal": str(exit_row.get("signal") or "").strip(),
            "trade_time": exit_row["trade_time"].to_pydatetime().replace(tzinfo=None),
            "price": exit_price,
        }
        records.extend([entry_leg, exit_leg])

    return records


def _resample_to_2h(bars: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not bars:
        return []
    df = pd.DataFrame(bars)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.set_index("timestamp").sort_index()
    agg = df.resample("2h", label="left", closed="left").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna(subset=["open", "close"])
    out = []
    for ts, row in agg.iterrows():
        out.append({
            "timestamp": ts.to_pydatetime().replace(tzinfo=None),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"] or 0),
        })
    return out


def _eastmoney_secid(code: str) -> Optional[str]:
    c = str(code or "").strip()
    if not c.isdigit() or len(c) != 6:
        return None
    market = "1" if c.startswith("6") else "0"
    return f"{market}.{c}"


def fetch_eastmoney_klines_2h(
    code: str,
    start: datetime = TRADE_CUTOFF,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """东方财富 120 分钟 K 线（即 2H），A 股国内源优先。"""
    secid = _eastmoney_secid(code)
    if not secid:
        return [], f"无效 A 股代码: {code}"

    beg = start.strftime("%Y%m%d")
    end = datetime.now().strftime("%Y%m%d")
    try:
        r = _direct_get(
            "https://push2his.eastmoney.com/api/qt/stock/kline/get",
            params={
                "secid": secid,
                "klt": "120",
                "fqt": "1",
                "beg": beg,
                "end": end,
                "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                "ut": "fa5fd1943c7b386f172d6893dbfba10b",
            },
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"},
        )
        r.raise_for_status()
        klines = ((r.json() or {}).get("data") or {}).get("klines") or []
    except Exception as exc:
        return [], f"东方财富 K线失败 {code}: {exc}"

    out: List[Dict[str, Any]] = []
    for line in klines:
        parts = str(line).split(",")
        if len(parts) < 6:
            continue
        try:
            ts = datetime.strptime(parts[0], "%Y-%m-%d %H:%M")
            if ts < start:
                continue
            out.append({
                "timestamp": ts,
                "open": float(parts[1]),
                "close": float(parts[2]),
                "high": float(parts[3]),
                "low": float(parts[4]),
                "volume": float(parts[5] or 0),
            })
        except (ValueError, TypeError):
            continue
    if not out:
        return [], f"东方财富无有效 2H K线: {code}"
    return out, None


def fetch_a_share_klines_2h(
    code: str,
    yahoo_ticker: str = "",
    start: datetime = TRADE_CUTOFF,
) -> Tuple[List[Dict[str, Any]], Optional[str], str]:
    """
    拉取 2H K 线：Yahoo 60m 聚合（主，走代理）→ 东方财富 120（国内兜底）。
    返回 (bars, error, source)。
    """
    yerr: Optional[str] = None
    if yahoo_ticker:
        bars, yerr = fetch_yahoo_klines_2h(yahoo_ticker, start)
        if bars:
            return bars, yerr, "yahoo_2h"

    bars, em_err = fetch_eastmoney_klines_2h(code, start)
    if bars:
        return bars, None, "eastmoney_2h"

    return [], yerr if yahoo_ticker else em_err or "无可用 K 线源", "none"


def fetch_yahoo_klines_2h(
    yahoo_ticker: str,
    start: datetime = TRADE_CUTOFF,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Yahoo 60m K 线聚合为 2H；云服务器需配置 HTTP_PROXY/HTTPS_PROXY。"""
    enc = urllib.parse.quote(yahoo_ticker, safe="")
    url = f"{YAHOO_CHART_BASE}/{enc}"
    period1 = int(start.timestamp())
    period2 = int(time.time()) + 86400
    last_err: Optional[str] = None

    for interval in ("60m", "1h", "1d"):
        try:
            r = _yahoo_get(
                url,
                params={"period1": period1, "period2": period2, "interval": interval},
            )
            r.raise_for_status()
            res = r.json()["chart"]["result"][0]
            ts_list = res.get("timestamp") or []
            q = (res.get("indicators") or {}).get("quote", [{}])[0]
            opens = q.get("open") or []
            highs = q.get("high") or []
            lows = q.get("low") or []
            closes = q.get("close") or []
            vols = q.get("volume") or []
        except Exception as exc:
            last_err = str(exc)
            logger.warning("Yahoo K线 %s interval=%s 失败: %s", yahoo_ticker, interval, exc)
            continue

        raw: List[Dict[str, Any]] = []
        for i, ts in enumerate(ts_list):
            if ts is None or closes[i] is None:
                continue
            dt = datetime.fromtimestamp(int(ts))
            if dt < start:
                continue
            raw.append({
                "timestamp": dt,
                "open": float(opens[i] or closes[i]),
                "high": float(highs[i] or closes[i]),
                "low": float(lows[i] or closes[i]),
                "close": float(closes[i]),
                "volume": float(vols[i] or 0),
            })

        if not raw:
            continue

        if interval == "1d":
            # 日线无法聚合 2H，仅作兜底（buy-hold 用）
            return raw, None
        bars = _resample_to_2h(raw)
        if bars:
            return bars, None

    proxy_hint = _proxy_env_value() or "未配置"
    return [], f"Yahoo 无有效 K 线: {yahoo_ticker}（代理: {proxy_hint}；最近错误: {last_err}）"


def _get_orm_classes():
    from backpack_quant_trading.api.routers.strategy import StrategyBacktestTrade, StrategyKline
    return StrategyBacktestTrade, StrategyKline


def import_strategy_to_db(spec: AShareStrategySpec, *, csv_path: Optional[Path] = None) -> Dict[str, Any]:
    """导入单只 A 股策略：交易 + 2H K 线。"""
    StrategyBacktestTrade, StrategyKline = _get_orm_classes()
    root = _project_root()
    path = csv_path or (root / spec.csv_filename)
    if not path.exists():
        raise FileNotFoundError(f"CSV 不存在: {path}")

    open_q = fetch_daily_open_price(spec.code, spec.trade_start_date)
    trade_start = datetime.combine(open_q.trade_date, dt_time(9, 30))
    trade_rows = recompound_trades_from_csv(
        path,
        initial_capital=spec.initial_capital_cny,
        trade_start=trade_start,
        open_price_on_start=open_q.price,
    )
    if not trade_rows:
        raise ValueError(
            f"{spec.code} 自 {spec.trade_start_date} 起无有效交易（研报 {spec.report_date}）"
        )

    kline_start = kline_chart_warmup_start(trade_start)
    klines, k_err, kline_source = fetch_a_share_klines_2h(spec.code, spec.yahoo_ticker, start=kline_start)
    if not klines:
        logger.warning("%s K线拉取失败: %s", spec.code, k_err)

    session = db_manager.get_session()
    try:
        session.query(StrategyBacktestTrade).filter_by(
            strategy_name=spec.strategy_name,
            symbol=spec.symbol,
            timeframe=TIMEFRAME,
        ).delete(synchronize_session=False)

        session.query(StrategyKline).filter_by(
            strategy_name=spec.strategy_name,
            symbol=spec.symbol,
            timeframe=TIMEFRAME,
        ).delete(synchronize_session=False)

        for row in trade_rows:
            session.add(StrategyBacktestTrade(
                strategy_name=spec.strategy_name,
                symbol=spec.symbol,
                timeframe=TIMEFRAME,
                trade_no=row["trade_no"],
                trade_type=row["trade_type"],
                signal=row["signal"],
                trade_time=row["trade_time"],
                price=Decimal(str(row["price"])),
                position_qty=Decimal(str(row["position_qty"])),
                position_value=Decimal(str(row["position_value"])),
                pnl=Decimal(str(row["pnl"])),
                pnl_pct=Decimal(str(row["pnl_pct"])),
                runup=Decimal(str(row["runup"])),
                runup_pct=Decimal(str(row["runup_pct"])),
                drawdown=Decimal(str(row["drawdown"])),
                drawdown_pct=Decimal(str(row["drawdown_pct"])),
                cum_pnl=Decimal(str(row["cum_pnl"])),
                cum_pnl_pct=Decimal(str(row["cum_pnl_pct"])),
            ))

        for kl in klines:
            session.add(StrategyKline(
                strategy_name=spec.strategy_name,
                symbol=spec.symbol,
                timeframe=TIMEFRAME,
                timestamp=kl["timestamp"],
                open=Decimal(str(kl["open"])),
                high=Decimal(str(kl["high"])),
                low=Decimal(str(kl["low"])),
                close=Decimal(str(kl["close"])),
                volume=Decimal(str(kl["volume"])),
                source=kline_source,
            ))

        session.commit()
    finally:
        session.close()

    exit_count = len({r["trade_no"] for r in trade_rows if _is_exit(r["trade_type"])})
    return {
        "code": spec.code,
        "name": spec.name,
        "report_date": spec.report_date.isoformat(),
        "trade_start_date": spec.trade_start_date.isoformat(),
        "kline_chart_start": kline_start.isoformat(sep=" "),
        "actual_trade_date": open_q.trade_date.isoformat(),
        "open_price_on_start": open_q.price,
        "trade_rows": len(trade_rows),
        "trade_count": exit_count,
        "klines": len(klines),
        "kline_source": kline_source,
        "kline_error": k_err,
        "kline_first": klines[0]["timestamp"].isoformat(sep=" ") if klines else None,
        "kline_last": klines[-1]["timestamp"].isoformat(sep=" ") if klines else None,
        "final_capital_cny": trade_rows[-1]["cum_pnl"] + spec.initial_capital_cny,
        "initial_capital_cny": spec.initial_capital_cny,
    }


def sync_a_share_klines_to_db(spec: AShareStrategySpec) -> Dict[str, Any]:
    """全量刷新单只 A 股 2H K 线（Yahoo 优先，自交易起始日前 1 个月起）。"""
    _, StrategyKline = _get_orm_classes()
    kline_start = kline_chart_warmup_start(trade_start_datetime(spec))
    klines, k_err, source = fetch_a_share_klines_2h(
        spec.code, spec.yahoo_ticker, start=kline_start,
    )
    if not klines:
        return {"code": spec.code, "inserted": 0, "total": 0, "source": source, "error": k_err}

    session = db_manager.get_session()
    try:
        session.query(StrategyKline).filter_by(
            strategy_name=spec.strategy_name,
            symbol=spec.symbol,
            timeframe=TIMEFRAME,
        ).delete(synchronize_session=False)
        for kl in klines:
            session.add(StrategyKline(
                strategy_name=spec.strategy_name,
                symbol=spec.symbol,
                timeframe=TIMEFRAME,
                timestamp=kl["timestamp"],
                open=Decimal(str(kl["open"])),
                high=Decimal(str(kl["high"])),
                low=Decimal(str(kl["low"])),
                close=Decimal(str(kl["close"])),
                volume=Decimal(str(kl["volume"])),
                source=source,
            ))
        session.commit()
    finally:
        session.close()

    return {
        "code": spec.code,
        "inserted": len(klines),
        "total": len(klines),
        "source": source,
        "kline_chart_start": kline_start.isoformat(sep=" "),
        "first": klines[0]["timestamp"].isoformat(sep=" "),
        "last": klines[-1]["timestamp"].isoformat(sep=" "),
        "error": k_err,
    }


def run_a_share_kline_sync() -> Dict[str, Any]:
    """定时任务：刷新全部 A 股 2H K 线。"""
    results = {}
    for spec in A_SHARE_STRATEGY_SPECS:
        try:
            results[spec.code] = sync_a_share_klines_to_db(spec)
        except Exception as exc:
            logger.exception("A股 K线同步失败 %s", spec.code)
            results[spec.code] = {"inserted": 0, "error": str(exc)}
    return results


def import_all_a_share_strategies() -> Dict[str, Any]:
    results = []
    errors = []
    for spec in A_SHARE_STRATEGY_SPECS:
        try:
            results.append(import_strategy_to_db(spec))
        except Exception as exc:
            logger.exception("导入 %s 失败", spec.code)
            errors.append({"code": spec.code, "error": str(exc)})
    return {
        "ok": len(errors) == 0,
        "imported": results,
        "errors": errors,
        "usd_cny": get_usd_cny_rate(),
        "initial_capital_cny": INITIAL_CAPITAL_CNY,
        "timeframe": TIMEFRAME,
    }