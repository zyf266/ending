"""
A 股日 K 线本地缓存 + 增量拉取。
优先使用 pytdx（免费、通达信协议，全市场日线）；未安装或连接失败时再尝试 Tushare Pro。
使用方式：
  1. 安装 pytdx：pip install pytdx。盘后或次日运行 ensure_incremental()，按股票增量拉取并入库。
  2. 若配置了 TUSHARE_TOKEN 且希望改用 Tushare，可设置环境变量 PREFER_TUSHARE=1。
  3. 选股/今日预测时从缓存读取日线，在内存中打分后取 top N。
"""
from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# 缓存文件默认路径
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "kline_cache"
CACHE_DB = CACHE_DIR / "daily_klines.db"

# 表结构：与 Tushare daily 对齐，便于增量写入
TABLE_NAME = "daily_klines"
CREATE_SQL = """
CREATE TABLE IF NOT EXISTS daily_klines (
    ts_code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    vol REAL,
    amount REAL,
    pct_chg REAL,
    PRIMARY KEY (ts_code, trade_date)
);
CREATE INDEX IF NOT EXISTS idx_daily_klines_ts_code ON daily_klines(ts_code);
CREATE INDEX IF NOT EXISTS idx_daily_klines_trade_date ON daily_klines(trade_date);
"""


def _code_to_ts_code(code: str) -> str:
    """6 位代码转 Tushare 格式：000001 -> 000001.SZ, 600000 -> 600000.SH"""
    code = str(code).strip()
    if not code or len(code) < 5:
        return f"{code}.SH"
    if code.startswith("6") or code.startswith("68"):
        return f"{code}.SH"
    return f"{code}.SZ"


def _ts_code_to_code(ts_code: str) -> str:
    """000001.SZ -> 000001"""
    return str(ts_code).split(".")[0].strip()


def _get_conn() -> sqlite3.Connection:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(CACHE_DB))
    conn.executescript(CREATE_SQL)
    return conn


def get_max_cached_date() -> Optional[str]:
    """返回缓存中最新交易日期 YYYYMMDD，无数据返回 None"""
    try:
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT MAX(trade_date) FROM daily_klines"
            ).fetchone()
            if row and row[0]:
                return row[0]
    except Exception as e:
        logger.debug("get_max_cached_date: %s", e)
    return None


def ensure_incremental() -> dict[str, Any]:
    """
    增量更新缓存：只拉取「比缓存更新」的交易日数据。
    优先使用 pytdx（免费）；若设置 PREFER_TUSHARE=1 且已配置 TUSHARE_TOKEN 则用 Tushare。
    返回 {"ok": bool, "message": str, "rows_added": int, "max_date": str, "source": "pytdx"|"tushare"}
    """
    result: dict[str, Any] = {"ok": False, "message": "", "rows_added": 0, "max_date": None, "source": None}
    prefer_tushare = os.getenv("PREFER_TUSHARE", "").strip() in ("1", "true", "yes")
    token = os.getenv("TUSHARE_TOKEN", "").strip()
    if prefer_tushare and token:
        out = _incremental_tushare(token, result)
        out["source"] = "tushare"
        return out
    # 优先 pytdx（免费、通达信协议）
    out = _incremental_pytdx(result)
    if out["ok"]:
        out["source"] = "pytdx"
        return out
    if token:
        out = _incremental_tushare(token, result)
        out["source"] = "tushare"
        return out
    result["message"] = result["message"] or "pytdx 连接失败且未配置 TUSHARE_TOKEN。请安装 pytdx（pip install pytdx）或配置 TUSHARE_TOKEN。"
    return result


def _incremental_pytdx(result: dict[str, Any]) -> dict[str, Any]:
    """
    使用 pytdx（通达信协议）按股票拉取日 K，只写入比缓存更新的交易日。
    全市场需逐只请求，单只最多 800 条；增量时只保留 trade_date > max_cached 的行。
    """
    try:
        from pytdx.hq import TdxHq_API
    except ImportError:
        result["message"] = "请安装 pytdx: pip install pytdx"
        return result

    # 行情服务器：优先用 pytdx 自带列表，再试常用备用（多券商 7709 端口）
    try:
        from pytdx.config.hosts import hq_hosts
        _hosts = [(h["ip"], h["port"]) for h in (hq_hosts or []) if h.get("ip") and h.get("port")]
    except Exception:
        _hosts = []
    if not _hosts:
        _hosts = [
            ("119.147.212.81", 7709),
            ("114.80.63.12", 7709),
            ("218.108.98.244", 7709),
            ("221.231.141.60", 7709),
            ("101.227.73.20", 7709),
            ("101.227.77.254", 7709),
            ("14.215.128.18", 7709),
            ("59.173.18.140", 7709),
            ("60.28.23.80", 7709),
            ("218.60.29.136", 7709),
            ("122.192.35.44", 7709),
            ("115.238.56.198", 7709),
            ("124.74.236.94", 7709),
        ]

    api = TdxHq_API()
    connected = False
    for host, port in _hosts:
        try:
            if api.connect(host, port, time_out=8):
                connected = True
                break
        except TypeError:
            try:
                if api.connect(host, port):
                    connected = True
                    break
            except Exception as e:
                logger.debug("pytdx connect %s:%s %s", host, port, e)
        except Exception as e:
            logger.debug("pytdx connect %s:%s %s", host, port, e)
    if not connected:
        result["message"] = (
            "pytdx 无法连接行情服务器（可能网络限制或服务器繁忙）。"
            "选股仍可直接用「开始选股」（实时拉取，稍慢）；若需全市场缓存可配置 TUSHARE_TOKEN 或稍后重试。"
        )
        return result

    max_cached = get_max_cached_date()
    # 收集 (market, code)：深市 0，沪市 1
    stocks: list[tuple[int, str]] = []
    try:
        for market in (0, 1):
            pos = 0
            while True:
                part = api.get_security_list(market, pos)
                if not part:
                    break
                for item in part:
                    code = getattr(item, "code", None) or (item.get("code") if isinstance(item, dict) else None)
                    if code is None and hasattr(item, "__getitem__"):
                        try:
                            code = item[0]
                        except (IndexError, KeyError, TypeError):
                            pass
                    if not code or not isinstance(code, str):
                        continue
                    code = code.strip()
                    if len(code) != 6 or not code.isdigit():
                        continue
                    # 仅 A 股：沪市 6/68 开头，深市 0/3/2/30 开头
                    if market == 1 and code[0] not in ("6", "9"):
                        continue
                    if market == 0 and code[0] not in ("0", "2", "3"):
                        continue
                    stocks.append((market, code))
                if len(part) < 1000:
                    break
                pos += len(part)
    except Exception as e:
        result["message"] = f"pytdx 获取股票列表失败: {e}"
        try:
            api.disconnect()
        except Exception:
            pass
        return result

    conn = _get_conn()
    total_added = 0
    latest_date: Optional[str] = None
    ins_sql = """INSERT OR REPLACE INTO daily_klines (ts_code, trade_date, open, high, low, close, vol, amount, pct_chg)
                 VALUES (?,?,?,?,?,?,?,?,?)"""
    import time

    try:
        for i, (market, code) in enumerate(stocks):
            try:
                raw = api.get_security_bars(9, market, code, 0, 800)
                if not raw:
                    continue
                df = api.to_df(raw)
                if df is None or df.empty:
                    continue
                if "datetime" not in df.columns and "year" in df.columns and "month" in df.columns and "day" in df.columns:
                    df["datetime"] = pd.to_datetime(df[["year", "month", "day"]].astype(int), errors="coerce")
                # 部分标的（如指数）返回 "0-00-00 15:00"，用 errors=coerce 转为 NaT 再丢弃
                dt_ser = pd.to_datetime(df["datetime"], errors="coerce")
                df = df.loc[dt_ser.notna()].copy()
                if df.empty:
                    continue
                df["trade_date"] = dt_ser.loc[df.index].dt.strftime("%Y%m%d")
                if max_cached:
                    df = df[df["trade_date"].astype(str) > max_cached].copy()
                if df.empty:
                    continue
                ts_code = f"{code}.SH" if market == 1 else f"{code}.SZ"
                if "vol" not in df.columns and "volume" in df.columns:
                    df["vol"] = df["volume"]
                if "pct_chg" not in df.columns and "close" in df.columns:
                    df["pct_chg"] = df["close"].astype(float).pct_change().mul(100)
                for _, row in df.iterrows():
                    try:
                        td = str(row["trade_date"])
                        if latest_date is None or td > latest_date:
                            latest_date = td
                        v = row.get("vol", row.get("volume", 0))
                        amt = row.get("amount", 0)
                        pc = row.get("pct_chg")
                        conn.execute(
                            ins_sql,
                            (
                                ts_code,
                                td,
                                float(row["open"]) if pd.notna(row.get("open")) else None,
                                float(row["high"]) if pd.notna(row.get("high")) else None,
                                float(row["low"]) if pd.notna(row.get("low")) else None,
                                float(row["close"]) if pd.notna(row.get("close")) else None,
                                float(v) if pd.notna(v) else None,
                                float(amt) if pd.notna(amt) else None,
                                float(pc) if pc is not None and pd.notna(pc) else None,
                            ),
                        )
                        total_added += 1
                    except Exception:
                        continue
                if (i + 1) % 100 == 0:
                    conn.commit()
                if (i + 1) % 50 == 0:
                    time.sleep(0.05)
            except Exception as e:
                logger.debug("pytdx %s %s: %s", market, code, e)
                continue
        conn.commit()
        result["ok"] = True
        result["message"] = f"pytdx 增量完成，新增 {total_added} 条，最新日期 {latest_date or max_cached}"
        result["rows_added"] = total_added
        result["max_date"] = latest_date or max_cached
    except Exception as e:
        result["message"] = f"pytdx 写入缓存失败: {e}"
        logger.exception("pytdx incremental: %s", e)
    finally:
        conn.close()
        try:
            api.disconnect()
        except Exception:
            pass
    return result


def _incremental_tushare(token: str, result: dict[str, Any]) -> dict[str, Any]:
    try:
        import tushare as ts
        pro = ts.pro_api(token)
    except ImportError:
        result["message"] = "请安装 tushare: pip install tushare"
        return result
    except Exception as e:
        result["message"] = f"Tushare 初始化失败: {e}"
        return result

    max_cached = get_max_cached_date()
    # 需要拉取的日期：从 max_cached 的下一日到「最近交易日」
    if max_cached:
        start_d = datetime.strptime(max_cached, "%Y%m%d") + timedelta(days=1)
    else:
        start_d = datetime.now() - timedelta(days=30)
    end_d = datetime.now()
    # 交易日历：只取 start_d ~ end_d 之间的交易日
    try:
        cal = pro.trade_cal(exchange="SSE", start_date=start_d.strftime("%Y%m%d"), end_date=end_d.strftime("%Y%m%d"), is_open=1)
        if cal is None or cal.empty:
            result["ok"] = True
            result["message"] = "无需更新"
            result["max_date"] = max_cached
            return result
        dates = cal["cal_date"].astype(str).tolist()
    except Exception as e:
        result["message"] = f"获取交易日历失败: {e}"
        return result

    total_added = 0
    conn = _get_conn()
    try:
        for trade_date in dates:
            try:
                df = pro.daily(trade_date=trade_date)
                if df is None or df.empty:
                    continue
                if "vol" not in df.columns and "volume" in df.columns:
                    df["vol"] = df["volume"]
                cols = ["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount", "pct_chg"]
                use = [c for c in cols if c in df.columns]
                df = df[use].copy()
                df["trade_date"] = df["trade_date"].astype(str)
                n = 0
                for _, row in df.iterrows():
                    try:
                        conn.execute(
                            """INSERT OR REPLACE INTO daily_klines (ts_code, trade_date, open, high, low, close, vol, amount, pct_chg)
                               VALUES (?,?,?,?,?,?,?,?,?)""",
                            (
                                str(row["ts_code"]),
                                str(row["trade_date"]),
                                float(row.get("open", 0)) if pd.notna(row.get("open")) else None,
                                float(row.get("high", 0)) if pd.notna(row.get("high")) else None,
                                float(row.get("low", 0)) if pd.notna(row.get("low")) else None,
                                float(row.get("close", 0)) if pd.notna(row.get("close")) else None,
                                float(row.get("vol", 0)) if pd.notna(row.get("vol")) else None,
                                float(row.get("amount", 0)) if pd.notna(row.get("amount")) else None,
                                float(row.get("pct_chg", 0)) if pd.notna(row.get("pct_chg")) else None,
                            ),
                        )
                        n += 1
                    except Exception:
                        continue
                conn.commit()
                total_added += n
                result["max_date"] = trade_date
            except Exception as e:
                logger.warning("Tushare daily %s: %s", trade_date, e)
                continue
        result["ok"] = True
        result["message"] = f"增量完成，新增 {total_added} 条，最新日期 {result.get('max_date') or max_cached}"
        result["rows_added"] = total_added
    finally:
        conn.close()
    return result


def get_daily_klines_from_cache(
    code: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    lookback_days: int = 400,
) -> Optional[pd.DataFrame]:
    """
    从缓存读取单只股票日线。日期格式 YYYYMMDD 或 YYYY-MM-DD。
    返回列：date, open, high, low, close, volume, pct_chg（与现有 _normalize_daily_df 对齐）。
    """
    ts_code = _code_to_ts_code(code)
    try:
        with _get_conn() as conn:
            sql = "SELECT ts_code, trade_date, open, high, low, close, vol, amount, pct_chg FROM daily_klines WHERE ts_code = ?"
            params: list = [ts_code]
            if start_date:
                s = str(start_date).replace("-", "")[:8]
                sql += " AND trade_date >= ?"
                params.append(s)
            if end_date:
                e = str(end_date).replace("-", "")[:8]
                sql += " AND trade_date <= ?"
                params.append(e)
            sql += " ORDER BY trade_date ASC"
            df = pd.read_sql_query(sql, conn, params=params)
    except Exception as e:
        logger.debug("get_daily_klines_from_cache %s: %s", code, e)
        return None
    if df is None or df.empty or len(df) < 30:
        return None
    df = df.rename(columns={"vol": "volume", "trade_date": "date"})
    df["date"] = pd.to_datetime(df["date"].astype(str))
    if "pct_chg" not in df.columns:
        df["pct_chg"] = df["close"].pct_change().mul(100)
    # 只保留最近 lookback_days 条
    if len(df) > lookback_days:
        df = df.tail(lookback_days).reset_index(drop=True)
    return df


def get_all_codes_from_cache() -> list[str]:
    """从缓存中取所有出现过的 ts_code，转为 6 位 code 列表（去重）。"""
    try:
        with _get_conn() as conn:
            rows = conn.execute("SELECT DISTINCT ts_code FROM daily_klines").fetchall()
        codes = sorted(set(_ts_code_to_code(r[0]) for r in rows if r[0]))
        return codes
    except Exception as e:
        logger.debug("get_all_codes_from_cache: %s", e)
        return []


def cache_has_sufficient_data(min_codes: int = 1000, min_days: int = 60) -> bool:
    """判断缓存是否具备「全市场 + 足够天数」用于全量打分。"""
    try:
        with _get_conn() as conn:
            n_codes = conn.execute("SELECT COUNT(DISTINCT ts_code) FROM daily_klines").fetchone()[0]
            n_days = conn.execute("SELECT COUNT(DISTINCT trade_date) FROM daily_klines").fetchone()[0]
        return n_codes >= min_codes and n_days >= min_days
    except Exception:
        return False


def get_daily_klines_batch(lookback_days: int = 120) -> dict[str, pd.DataFrame]:
    """
    一次性从缓存读取全市场最近 lookback_days 的日线，按 code 分表返回。
    用于「全量打分」：避免逐只查库。返回 6 位 code -> DataFrame(date, open, high, low, close, volume, pct_chg)。
    """
    out: dict[str, pd.DataFrame] = {}
    try:
        max_date = get_max_cached_date()
        if not max_date:
            return out
        with _get_conn() as conn:
            df = pd.read_sql_query(
                """SELECT ts_code, trade_date, open, high, low, close, vol, pct_chg
                   FROM daily_klines ORDER BY trade_date ASC""",
                conn,
            )
        if df is None or df.empty:
            return out
        df["trade_date"] = pd.to_datetime(df["trade_date"].astype(str))
        df["code"] = df["ts_code"].map(_ts_code_to_code)
        df = df.rename(columns={"vol": "volume"})
        if len(df) > 0:
            # 只保留最近 lookback_days 个交易日
            uniq_dates = sorted(df["trade_date"].dropna().unique())
            if len(uniq_dates) > lookback_days:
                cut = uniq_dates[-lookback_days]
                df = df[df["trade_date"] >= cut].copy()
        for code, g in df.groupby("code"):
            if len(g) < 30:
                continue
            g = g.rename(columns={"trade_date": "date"}).sort_values("date").reset_index(drop=True)
            out[code] = g
    except Exception as e:
        logger.debug("get_daily_klines_batch: %s", e)
    return out
