"""
A股AI选股服务：板块/行业筛选 + 多指标打分（MACD/RSI/成交量/KDJ/OBV/均线/主力等）
数据来源：akshare（东方财富等），未安装 akshare 时接口返回空数据。
"""
from __future__ import annotations

import logging
import random
import time
from concurrent.futures import TimeoutError as FuturesTimeoutError
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

try:
    import akshare as ak  # type: ignore
    HAS_AKSHARE = True
except ImportError:
    HAS_AKSHARE = False
    ak = None

# 板块：前端选项 -> 股票代码前缀/市场筛选
BOARD_OPTIONS = [
    {"value": "主板", "label": "主板（沪市+深市）"},
    {"value": "创业板", "label": "创业板"},
    {"value": "科创板", "label": "科创板"},
    {"value": "北交所", "label": "北交所"},
]

# 沪市: 60, 68 | 深市主板: 00 | 创业板: 30 | 科创板: 68(沪) | 北交所: 8, 4
BOARD_CODE_MAP = {
    "主板": {"prefix": ["60", "00"], "market": ["sh", "sz"]},
    "创业板": {"prefix": ["30"], "market": ["sz"]},
    "科创板": {"prefix": ["68"], "market": ["sh"]},
    "北交所": {"prefix": ["8", "4"], "market": ["bj"]},
}


def _code_to_market(code: str) -> str:
    if not code:
        return "sh"
    code = str(code).strip()
    if code.startswith("6") or code.startswith("68"):
        return "sh"
    if code.startswith("0") or code.startswith("3"):
        return "sz"
    if code.startswith("8") or code.startswith("4"):
        return "bj"
    return "sh"


def _belongs_to_board(code: str, board: str) -> bool:
    if not board or board == "全部":
        return True
    cfg = BOARD_CODE_MAP.get(board)
    if not cfg:
        return True
    code = str(code).strip()
    for p in cfg["prefix"]:
        if code.startswith(p):
            return True
    return False


@dataclass
class StockAiConfig:
    """选股请求参数"""
    boards: list[str] = field(default_factory=lambda: [])   # 空=全部
    industries: list[str] = field(default_factory=lambda: [])  # 空=全部
    top_n: int = 30
    min_score: float = 0.0
    lookback_days: int = 120  # 指标计算回溯天数


def get_board_options() -> list[dict]:
    """返回板块选项（前端下拉）"""
    return list(BOARD_OPTIONS)


_DEFAULT_INDUSTRY_OPTIONS = [
    {"value": "化学原料", "label": "化学原料"},
    {"value": "贵金属", "label": "贵金属"},
    {"value": "电力", "label": "电力"},
    {"value": "银行", "label": "银行"},
    {"value": "半导体", "label": "半导体"},
]


def get_industry_options() -> list[dict]:
    """返回行业选项（东方财富行业板块）。失败或为空时返回默认行业列表，保证前端始终有数据。"""
    if not HAS_AKSHARE:
        return list(_DEFAULT_INDUSTRY_OPTIONS)
    try:
        df = ak.stock_board_industry_name_em()
        if df is None or df.empty:
            return list(_DEFAULT_INDUSTRY_OPTIONS)
        name_col = "板块名称" if "板块名称" in df.columns else (df.columns[0] if len(df.columns) else None)
        if name_col is None:
            return list(_DEFAULT_INDUSTRY_OPTIONS)
        names = df[name_col].dropna().unique().tolist()
        if not names:
            return list(_DEFAULT_INDUSTRY_OPTIONS)
        return [{"value": str(n), "label": str(n)} for n in names[:80]]
    except Exception as e:
        logger.warning("获取行业列表失败: %s", e)
        return list(_DEFAULT_INDUSTRY_OPTIONS)


def _normalize_stock_list_df(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """统一列为 code / name"""
    if df is None or df.empty:
        return None
    cols = [str(c).strip() for c in list(df.columns)]
    code_col = "code" if "code" in cols else ("代码" if "代码" in df.columns else (cols[0] if cols else None))
    name_col = "name" if "name" in cols else ("名称" if "名称" in df.columns else ("证券简称" if "证券简称" in df.columns else (cols[1] if len(cols) > 1 else None)))
    if not code_col or not name_col:
        return None
    out = df[[code_col, name_col]].copy()
    out = out.rename(columns={code_col: "code", name_col: "name"})
    out["code"] = out["code"].astype(str).str.strip()
    out = out.dropna(subset=["code"])
    return out


def _fetch_a_stock_list() -> Optional[pd.DataFrame]:
    """获取 A 股代码+名称列表。优先用统一接口，失败时改用沪市+深市分开拉取（避免 bse 等源断连）。"""
    if not HAS_AKSHARE:
        return None
    # 1) 优先使用统一 A 股列表（可能因 bse.cn 等源断连失败）
    try:
        df = ak.stock_info_a_code_name()
        out = _normalize_stock_list_df(df)
        if out is not None and len(out) > 100:
            return out
    except Exception as e:
        logger.warning("获取A股列表(统一接口)失败，改用沪市+深市: %s", e)
    # 2) 备用：沪市 + 深市分别获取后合并（避免 bse.cn 等源断连）
    parts = []
    try:
        sh = ak.stock_info_sh_name_code()
        out_sh = _normalize_stock_list_df(sh)
        if out_sh is not None and len(out_sh) > 0:
            parts.append(out_sh)
    except Exception as e:
        logger.warning("获取沪市列表失败: %s", e)
    try:
        try:
            sz = ak.stock_info_sz_name_code(symbol="A股列表")
        except TypeError:
            sz = ak.stock_info_sz_name_code()
        out_sz = _normalize_stock_list_df(sz)
        if out_sz is not None and len(out_sz) > 0:
            parts.append(out_sz)
    except Exception as e:
        logger.warning("获取深市列表失败: %s", e)
    if parts:
        merged = pd.concat(parts, ignore_index=True).drop_duplicates(subset=["code"], keep="first")
        logger.info("A股列表已从沪市+深市合并获取，共 %s 只", len(merged))
        return merged
    return None


def _filter_by_board_and_industry(
    df: pd.DataFrame,
    boards: list[str],
    industries: list[str],
) -> pd.DataFrame:
    """按板块、行业筛选。行业需后续用板块成分接口过滤，这里先按板块过滤。"""
    if df is None or df.empty:
        return pd.DataFrame()
    # 板块筛选
    if boards:
        mask = df["code"].apply(lambda c: any(_belongs_to_board(c, b) for b in boards))
        df = df[mask].copy()
    # 行业：akshare 用 stock_board_industry_cons_em(symbol=行业名) 取成分股，后面在选股时再筛
    return df


def _get_industry_constituents(industry_name: str) -> set[str]:
    """获取某行业成分股代码集合"""
    if not HAS_AKSHARE or not industry_name:
        return set()
    try:
        df = ak.stock_board_industry_cons_em(symbol=industry_name)
        if df is None or df.empty:
            return set()
        code_col = "代码" if "代码" in df.columns else (df.columns[0] if df.columns.any() else None)
        if code_col:
            return set(df[code_col].astype(str).str.strip().tolist())
        return set()
    except Exception as e:
        logger.debug("获取行业成分股失败 %s: %s", industry_name, e)
        return set()


def _normalize_daily_df(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """统一日线 DataFrame 列名与类型（兼容东财/新浪/腾讯等返回格式）"""
    if df is None or len(df) < 30:
        return None
    rename_map = {
        "日期": "date", "开盘": "open", "收盘": "close", "最高": "high", "最低": "low",
        "成交量": "volume", "成交额": "amount", "涨跌幅": "pct_chg", "换手率": "turnover",
        "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume",
        "change_pct": "pct_chg", "pct_change": "pct_chg", "幅度": "pct_chg",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
    date_col = "date" if "date" in df.columns else "日期"
    if date_col not in df.columns:
        return None
    df["date"] = pd.to_datetime(df[date_col])
    if "close" not in df.columns and "收盘" in df.columns:
        df["close"] = df["收盘"].astype(float)
    if "high" not in df.columns and "最高" in df.columns:
        df["high"] = df["最高"].astype(float)
    if "low" not in df.columns and "最低" in df.columns:
        df["low"] = df["最低"].astype(float)
    if "volume" not in df.columns and "成交量" in df.columns:
        df["volume"] = df["成交量"].astype(float)
    if "pct_chg" not in df.columns and "涨跌幅" in df.columns:
        df["pct_chg"] = df["涨跌幅"].astype(float)
    # 若仍无涨跌幅（部分数据源无此列），用收盘价推算
    if "pct_chg" not in df.columns and "close" in df.columns and len(df) >= 2:
        close = df["close"].astype(float)
        df["pct_chg"] = close.pct_change().mul(100)
    df = df.sort_values("date").reset_index(drop=True)
    return df


def _date_range_str(days: int = 400) -> tuple[str, str]:
    end_d = datetime.now()
    start_d = end_d - timedelta(days=days)
    return start_d.strftime("%Y%m%d"), end_d.strftime("%Y%m%d")


def _fetch_daily_tx(symbol_with_prefix: str, adjust: str = "qfq") -> Optional[pd.DataFrame]:
    """腾讯数据源日线，symbol 需带前缀如 sh600000、sz000001，相对稳定"""
    if not HAS_AKSHARE:
        return None
    func = getattr(ak, "stock_zh_a_hist_tx", None)
    if func is None:
        return None
    try:
        start_date, end_date = _date_range_str(400)
        df = func(symbol=symbol_with_prefix, start_date=start_date, end_date=end_date, adjust=adjust)
        return _normalize_daily_df(df)
    except Exception as e:
        logger.debug("腾讯日线 %s 失败: %s", symbol_with_prefix, e)
        return None


def _fetch_daily_sina(symbol_with_prefix: str, adjust: str = "qfq") -> Optional[pd.DataFrame]:
    """新浪数据源日线，symbol 需带前缀如 sh600000、sz000001"""
    if not HAS_AKSHARE:
        return None
    func = getattr(ak, "stock_zh_a_daily", None)
    if func is None:
        return None
    try:
        start_date, end_date = _date_range_str(400)
        df = func(symbol=symbol_with_prefix, start_date=start_date, end_date=end_date, adjust=adjust)
        return _normalize_daily_df(df)
    except Exception as e:
        logger.debug("新浪日线 %s 失败: %s", symbol_with_prefix, e)
        return None


def _fetch_daily_em(symbol: str, adjust: str = "qfq") -> Optional[pd.DataFrame]:
    """东方财富数据源日线（易被反爬断开），仅作兜底"""
    if not HAS_AKSHARE:
        return None
    try:
        df = ak.stock_zh_a_hist(symbol=symbol, period="daily", start_date="", end_date="", adjust=adjust)
        return _normalize_daily_df(df)
    except Exception as e:
        logger.debug("东财日线 %s 失败: %s", symbol, e)
        return None


def _get_daily_for_screen(symbol: str, lookback_days: int = 120) -> Optional[pd.DataFrame]:
    """选股用日线：优先从本地 K 线缓存读取（Tushare 增量写入），无缓存或不足时再走实时接口。"""
    try:
        from backpack_quant_trading.core.stock_kline_cache import get_daily_klines_from_cache
        daily = get_daily_klines_from_cache(symbol, lookback_days=lookback_days)
        if daily is not None and len(daily) >= 30:
            return daily
    except Exception:
        pass
    daily = _fetch_daily(symbol, adjust="qfq", max_retries=2)
    if daily is not None and len(daily) > lookback_days:
        daily = daily.tail(lookback_days)
    return daily


def _fetch_daily(symbol: str, adjust: str = "qfq", max_retries: int = 2) -> Optional[pd.DataFrame]:
    """
    获取个股日线（前复权）。优先使用腾讯/新浪接口（更稳定），东方财富仅作兜底，
    避免因东财反爬导致大量 RemoteDisconnected。
    """
    if not HAS_AKSHARE:
        return None
    market = _code_to_market(symbol)
    prefix_symbol = f"{market}{symbol}"

    # 沪/深：优先腾讯，其次新浪，最后东财（东财易断开）
    if market in ("sh", "sz"):
        out = _fetch_daily_tx(prefix_symbol, adjust)
        if out is not None:
            return out
        out = _fetch_daily_sina(prefix_symbol, adjust)
        if out is not None:
            return out
        for _ in range(max_retries):
            out = _fetch_daily_em(symbol, adjust)
            if out is not None:
                return out
            time.sleep(1.0 + random.uniform(0.5, 1.0))
        return None

    # 北交所等：仅东财
    for _ in range(max_retries):
        out = _fetch_daily_em(symbol, adjust)
        if out is not None:
            return out
        time.sleep(1.0 + random.uniform(0.5, 1.0))
    return None


def _macd_signal(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[float, float, float]:
    """MACD 柱、DIF、DEA。返回最近一根的 (hist, dif, dea)。"""
    if close is None or len(close) < slow + signal:
        return 0.0, 0.0, 0.0
    ema_f = close.ewm(span=fast, adjust=False).mean()
    ema_s = close.ewm(span=slow, adjust=False).mean()
    dif = ema_f - ema_s
    dea = dif.ewm(span=signal, adjust=False).mean()
    hist = (dif - dea).iloc[-1] if len(dif) else 0.0
    return float(hist), float(dif.iloc[-1]), float(dea.iloc[-1])


def _rsi(close: pd.Series, period: int = 14) -> float:
    if close is None or len(close) < period + 1:
        return 50.0
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.rolling(period).mean().iloc[-1] if len(gain) >= period else 0.0
    avg_loss = loss.rolling(period).mean().iloc[-1] if len(loss) >= period else 0.0
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100 - (100 / (1 + rs)))


def _kdj(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 9, m1: int = 3, m2: int = 3) -> tuple[float, float, float]:
    """K, D, J 最后一根"""
    if high is None or low is None or close is None or len(close) < n + m2:
        return 50.0, 50.0, 50.0
    low_min = low.rolling(n).min()
    high_max = high.rolling(n).max()
    rsv = (close - low_min) / (high_max - low_min + 1e-10) * 100
    rsv = rsv.fillna(50)
    k = rsv.ewm(com=m1 - 1, adjust=False).mean()
    d = k.ewm(com=m2 - 1, adjust=False).mean()
    j = 3 * k - 2 * d
    return float(k.iloc[-1]), float(d.iloc[-1]), float(j.iloc[-1])


def _obv_score(close: pd.Series, volume: pd.Series, window: int = 20) -> float:
    """量价配合：近期 OBV 趋势与价格同向加分。返回 0~1 归一化得分。"""
    if close is None or volume is None or len(close) < window:
        return 0.5
    obv = (np.sign(close.diff().fillna(0)) * volume).cumsum()
    obv_ma = obv.rolling(window).mean()
    price_ma = close.rolling(window).mean()
    obv_trend = 1 if obv.iloc[-1] > obv_ma.iloc[-2] else -1
    price_trend = 1 if close.iloc[-1] > price_ma.iloc[-2] else -1
    return 1.0 if obv_trend == price_trend else 0.0


def _volume_ratio(volume: pd.Series, window: int = 5) -> float:
    """量比：当日量 / 过去 window 日均量（与常见行情软件一致，便于区分个股）。"""
    if volume is None or len(volume) < window + 1:
        return 1.0
    today = float(volume.iloc[-1])
    past_avg = volume.iloc[-window - 1 : -1].mean()
    if past_avg == 0 or pd.isna(past_avg):
        return 1.0
    return float(today / past_avg)


def _ma_cross_score(close: pd.Series, short: int = 5, long: int = 20) -> float:
    """均线金叉/多头排列加分。0~1。"""
    if close is None or len(close) < long:
        return 0.0
    ma_s = close.rolling(short).mean().iloc[-1]
    ma_l = close.rolling(long).mean().iloc[-1]
    if ma_s > ma_l:
        return 1.0
    return 0.0


def _fund_flow_score(stock_code: str, market: str) -> float:
    """主力净流入得分：最近一日净流入占比，归一化到 0~1。"""
    if not HAS_AKSHARE or not stock_code:
        return 0.5
    try:
        df = ak.stock_individual_fund_flow(stock=stock_code, market=market)
        if df is None or len(df) < 1:
            return 0.5
        # 主力净流入-净占比 或类似列
        col = None
        for c in ["主力净流入-净占比", "主力净流入净占比", "净占比"]:
            if c in df.columns:
                col = c
                break
        if col is None:
            col = df.columns[-1] if len(df.columns) else None
        if col:
            v = df[col].iloc[0]
            if pd.isna(v):
                return 0.5
            # 占比 -10~10 映射到 0~1
            return float(np.clip((float(v) + 10) / 20, 0, 1))
        return 0.5
    except Exception as e:
        logger.debug("主力资金流 %s: %s", stock_code, e)
        return 0.5


def compute_composite_score(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    volume: pd.Series,
    stock_code: str = "",
    market: str = "sh",
    skip_fund_flow: bool = False,
) -> dict[str, Any]:
    """
    计算多指标并汇总为综合得分 0~100。
    指标：MACD、RSI、KDJ、量比、OBV、均线、主力净流入。skip_fund_flow=True 时跳过主力接口以加快选股。
    """
    if close is None or len(close) < 30:
        return {"score": 0.0, "details": {}}
    details = {}
    scores = []

    # MACD：红柱且 DIF>DEA 加分
    hist, dif, dea = _macd_signal(close)
    details["macd_hist"] = round(hist, 4)
    details["macd_dif"] = round(dif, 4)
    details["macd_dea"] = round(dea, 4)
    if hist > 0 and dif > dea:
        scores.append(15.0)
    elif hist > 0:
        scores.append(10.0)
    else:
        scores.append(0.0)

    # RSI：30~70 加分，50 附近最优
    r = _rsi(close)
    details["rsi"] = round(r, 2)
    if 40 <= r <= 60:
        scores.append(15.0)
    elif 30 <= r <= 70:
        scores.append(10.0)
    else:
        scores.append(5.0)

    # KDJ：J 从下方上穿 K、D 或 K>D 低位
    k, d, j = _kdj(high, low, close)
    details["kdj_k"] = round(k, 2)
    details["kdj_d"] = round(d, 2)
    details["kdj_j"] = round(j, 2)
    if k > d and j < 80:
        scores.append(15.0)
    elif k > d:
        scores.append(10.0)
    else:
        scores.append(5.0)

    # 量比：温和放量 1~2 倍加分
    vr = _volume_ratio(volume)
    details["volume_ratio"] = round(vr, 2)
    if 1.0 <= vr <= 2.5:
        scores.append(12.0)
    elif vr >= 1.0:
        scores.append(8.0)
    else:
        scores.append(4.0)

    # OBV 量价配合
    obv_s = _obv_score(close, volume)
    details["obv_sync"] = round(obv_s, 2)
    scores.append(obv_s * 10.0)

    # 均线金叉/多头
    ma_s = _ma_cross_score(close)
    details["ma_cross"] = round(ma_s, 2)
    scores.append(ma_s * 10.0)

    # 主力净流入（选股阶段跳过以节省时间；不拉取则不写入 details，前端不展示该列）
    if skip_fund_flow:
        ff = 0.5
    else:
        ff = _fund_flow_score(stock_code, market)
        details["fund_flow"] = round(ff, 2)
    scores.append(ff * 18.0)

    total = sum(scores)
    # 归一化到 0~100（理论最大约 15+15+15+12+10+10+18=95）
    total = min(100.0, total * (100.0 / 95.0))
    details["score"] = round(total, 2)
    return {"score": round(total, 2), "details": details}


def _safe_daily_series(df: pd.DataFrame, col: str, fallback_col: str = None):
    """从日线 DataFrame 安全取列，兼容中英文列名"""
    if df is None or df.empty:
        return None
    for c in (col, fallback_col):
        if c and c in df.columns:
            s = df[c]
            if s is not None and len(s) > 0:
                return s.astype(float) if s.dtype != float else s
    return None


def _format_detail_description(details: dict, skip_fund_flow: bool = True) -> str:
    """根据 details 生成每行说明，避免笼统重复。"""
    if not details:
        return "量价/均线等已计入综合得分"
    parts = []
    h = details.get("macd_hist")
    if h is not None:
        parts.append("红柱" if h > 0 else "绿柱")
    r = details.get("rsi")
    if r is not None:
        if r < 30:
            parts.append("RSI超卖")
        elif r > 70:
            parts.append("RSI超买")
        else:
            parts.append(f"RSI{r:.0f}")
    vr = details.get("volume_ratio")
    if vr is not None:
        if vr >= 2:
            parts.append("放量")
        elif vr >= 1:
            parts.append(f"量比{vr:.2f}")
        else:
            parts.append("缩量")
    k, d = details.get("kdj_k"), details.get("kdj_d")
    if k is not None and d is not None and k > d:
        parts.append("KDJ金叉")
    if not skip_fund_flow and details.get("fund_flow") is not None:
        parts.append("主力" + str(details.get("fund_flow")))
    return "；".join(parts) if parts else "量价/均线等已计入综合得分"


def _score_daily_df(
    code: str,
    name: str,
    daily: pd.DataFrame,
    config: StockAiConfig,
) -> Optional[dict]:
    """对单只股票的日线 DataFrame 打分，返回与 _score_one 相同结构。"""
    try:
        market = _code_to_market(code)
        if daily is None or len(daily) < 30:
            return None
        close = _safe_daily_series(daily, "close", "收盘")
        if close is None or len(close) < 20:
            return None
        high = _safe_daily_series(daily, "high", "最高")
        if high is None or (hasattr(high, "empty") and high.empty) or len(high) < 20:
            high = close
        low = _safe_daily_series(daily, "low", "最低")
        if low is None or (hasattr(low, "empty") and low.empty) or len(low) < 20:
            low = close
        volume = _safe_daily_series(daily, "volume", "成交量")
        if volume is None or (hasattr(volume, "empty") and volume.empty) or (hasattr(volume, "isna") and bool(volume.isna().all())):
            volume = pd.Series(1.0, index=close.index)
        res = compute_composite_score(
            close, high, low, volume, stock_code=code, market=market, skip_fund_flow=True
        )
        score = res["score"]
        if score < config.min_score:
            return None
        pct_chg = None
        pcol = _safe_daily_series(daily, "pct_chg", "涨跌幅")
        if pcol is not None and len(pcol) > 0:
            try:
                v = float(pcol.iloc[-1])
                if not pd.isna(v):
                    pct_chg = v
            except (TypeError, ValueError):
                pass
        if pct_chg is None and close is not None and len(close) >= 2:
            try:
                pct_chg = float((close.iloc[-1] - close.iloc[-2]) / close.iloc[-2] * 100)
            except (TypeError, ValueError, ZeroDivisionError):
                pass
        details = res.get("details", {})
        return {
            "code": code,
            "name": name,
            "market": market,
            "score": score,
            "details": details,
            "description": _format_detail_description(details, skip_fund_flow=True),
            "close": float(close.iloc[-1]) if len(close) else None,
            "pct_chg": pct_chg,
        }
    except Exception as e:
        logger.debug("选股单只跳过 %s: %s", code, e)
        return None


def run_ai_stock_screen(config: StockAiConfig) -> tuple[list[dict], dict[str, Any]]:
    """
    执行 AI 选股：按板块/行业筛股票，拉日线算指标，综合打分排序，返回 top_n。
    缓存充足时对「筛选池内全量」打分取真正 top N；否则对前 30 只抽样打分。
    返回 (结果列表, meta)，meta 含 candidates_count、from_full_market。
    """
    meta: dict[str, Any] = {"candidates_count": 0, "from_full_market": False}
    if not HAS_AKSHARE:
        logger.warning("未安装 akshare，无法执行 A 股选股")
        return [], meta
    try:
        df_all = _fetch_a_stock_list()
    except Exception as e:
        logger.exception("获取A股列表异常: %s", e)
        raise RuntimeError(f"获取A股列表失败: {e}") from e
    if df_all is None or df_all.empty:
        return [], meta
    df_all = _filter_by_board_and_industry(
        df_all,
        config.boards if config.boards else [],
        config.industries if config.industries else [],
    )
    industry_codes: set[str] = set()
    if config.industries:
        for ind in config.industries:
            industry_codes |= _get_industry_constituents(ind)
        if industry_codes:
            df_all = df_all[df_all["code"].astype(str).str.strip().isin(industry_codes)].copy()
    if df_all.empty:
        return [], meta

    # 缓存充足时：全量从缓存打分，得到「筛选池内所有股票」的真正 top N
    try:
        from backpack_quant_trading.core.stock_kline_cache import (
            cache_has_sufficient_data,
            get_daily_klines_batch,
        )
        if cache_has_sufficient_data(min_codes=800, min_days=60):
            batch = get_daily_klines_batch(lookback_days=config.lookback_days)
            if batch:
                all_codes_in_filter = df_all["code"].astype(str).str.strip().tolist()
                code_to_name = {}
                for _, r in df_all.iterrows():
                    code_to_name[str(r["code"]).strip()] = str(r.get("name", r.get("名称", "")) or "")
                candidate_codes = [c for c in all_codes_in_filter if c in batch]
                meta["candidates_count"] = len(candidate_codes)
                meta["from_full_market"] = True
                results = []
                for code in candidate_codes:
                    name = code_to_name.get(code, code)
                    r = _score_daily_df(code, str(name), batch[code], config)
                    if r is not None:
                        results.append(r)
                results.sort(key=lambda x: -(x["score"] or 0))
                return results[: config.top_n], meta
    except Exception as e:
        logger.debug("全量缓存选股跳过，回退抽样: %s", e)

    # 抽样模式：仅对前 30 只拉日线并打分（接口易慢）
    max_candidates = 30
    df_all = df_all.sort_values("code").reset_index(drop=True)
    if len(df_all) > max_candidates:
        df_all = df_all.iloc[:max_candidates].reset_index(drop=True)
    meta["candidates_count"] = len(df_all)
    meta["from_full_market"] = False
    rows = [row for _, row in df_all.iterrows()]

    def _score_one(row: pd.Series) -> Optional[dict]:
        try:
            code = str(row["code"]).strip()
            name = str(row.get("name", row.get("名称", "")))
            daily = _get_daily_for_screen(code, config.lookback_days)
            return _score_daily_df(code, name, daily, config) if daily is not None else None
        except Exception as e:
            logger.debug("选股单只跳过 %s: %s", row.get("code", ""), e)
            return None

    results = []
    max_workers = min(6, len(rows))
    _single_timeout = 8
    _total_timeout = 60
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_score_one, row): row for row in rows}
        try:
            for future in as_completed(futures, timeout=_total_timeout):
                try:
                    r = future.result(timeout=_single_timeout)
                    if r is not None:
                        results.append(r)
                except Exception:
                    pass
        except (FuturesTimeoutError, TimeoutError):
            logger.warning("选股部分请求超时，已返回当前已完成的 %s 只", len(results))
    results.sort(key=lambda x: -(x["score"] or 0))
    return results[: config.top_n], meta


def deepseek_analyze_stocks(items: list[dict], max_items: int = 15) -> str:
    """
    调用 DeepSeek 接口对选股结果做简要解读：综合得分、技术面、买卖参考。
    需配置环境变量 DEEPSEEK_API_KEY。items 为 run_ai_stock_screen 返回的列表项。
    """
    import os
    import requests
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        return "请配置 DEEPSEEK_API_KEY 环境变量后使用 AI 解读。"
    if not items:
        return "暂无选股结果，请先执行选股。"
    # 只取前 max_items 条，拼成文本
    rows = []
    for i, x in enumerate(items[:max_items], 1):
        code = x.get("code", "")
        name = x.get("name", "")
        score = x.get("score")
        close = x.get("close")
        pct = x.get("pct_chg")
        d = x.get("details") or {}
        rsi = d.get("rsi")
        macd = d.get("macd_hist")
        kdj_j = d.get("kdj_j")
        vol_ratio = d.get("volume_ratio")
        fund = d.get("fund_flow")
        fund_str = f" 主力{fund}" if fund is not None else ""
        rows.append(
            f"{i}. {code} {name} 得分{score} 最新价{close} 涨跌幅{pct}% "
            f"RSI{rsi} MACD柱{macd} KDJ(J){kdj_j} 量比{vol_ratio}{fund_str}"
        )
    text = "\n".join(rows)
    system = (
        "你是 A 股技术分析助手。根据下面多指标选股结果（得分、RSI、MACD、KDJ、量比、主力等），"
        "用 2～4 句话概括当前技术面共性、得分高的原因，并给出 1～2 条操作建议（如分批建仓、设好止损）。"
    )
    user = f"选股结果（按综合得分排序）：\n{text}\n\n请给出简要解读与操作建议。"
    try:
        r = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": "deepseek-chat", "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}], "temperature": 0.3},
            timeout=60,
        )
        data = r.json()
        if r.status_code == 200 and data.get("choices"):
            return (data["choices"][0].get("message") or {}).get("content", "").strip() or "DeepSeek 未返回内容"
        err = data.get("error") or {}
        msg = err.get("message", str(data)) if isinstance(err, dict) else str(data)
        return f"DeepSeek 接口异常: {msg}"
    except requests.exceptions.Timeout:
        return "请求超时，请稍后重试。"
    except Exception as e:
        logger.exception("DeepSeek 选股解读: %s", e)
        return f"调用失败: {e}"


def deepseek_analyze_stocks_with_daily(items: list[dict], max_items: int = 10, daily_bars: int = 55) -> str:
    """
    拉取选股结果的日线数据，结合知识库与「资深 A 股交易员」角色调用 DeepSeek 做日线技术分析。
    使用 ai_adaptive 的 KNOWLEDGE_BASE 与 get_a_share_kline_system_prompt。
    需配置 DEEPSEEK_API_KEY。
    """
    import os
    import requests
    from backpack_quant_trading.core.ai_adaptive import get_a_share_kline_system_prompt

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        return "请配置 DEEPSEEK_API_KEY 环境变量后使用 AI 解读。"
    if not items:
        return "暂无选股结果，请先执行选股。"

    parts = []
    for i, x in enumerate(items[:max_items], 1):
        code = str(x.get("code", "")).strip()
        name = x.get("name", "")
        score = x.get("score")
        close = x.get("close")
        pct = x.get("pct_chg")
        d = x.get("details") or {}
        rsi = d.get("rsi")
        macd = d.get("macd_hist")
        kdj_j = d.get("kdj_j")
        vol_ratio = d.get("volume_ratio")
        fund = d.get("fund_flow")
        fund_str = f" 主力{fund}" if fund is not None else ""
        summary = (
            f"得分{score} 最新价{close} 涨跌幅{pct}% "
            f"RSI{rsi} MACD柱{macd} KDJ(J){kdj_j} 量比{vol_ratio}{fund_str}"
        )
        df = _fetch_daily(code, adjust="qfq")
        if df is None or len(df) < 30:
            parts.append(f"=== {code} {name} ===\n选股摘要: {summary}\n日线数据: 拉取失败或不足，请略过该只。\n")
            continue
        df = df.sort_values("date").reset_index(drop=True).tail(daily_bars)
        df["_dt"] = pd.to_datetime(df["date"])
        rows = []
        for _, r in df.iterrows():
            dt = r["_dt"].strftime("%Y-%m-%d") if hasattr(r["_dt"], "strftime") else str(r["date"])[:10]
            o, h, lo, c, v = r.get("open", ""), r.get("high", ""), r.get("low", ""), r.get("close", ""), r.get("volume", "")
            rows.append(f"{dt} {o} {h} {lo} {c} {v}")
        table = "日期 开盘 最高 最低 收盘 成交量\n" + "\n".join(rows)
        parts.append(f"=== {code} {name} ===\n选股摘要: {summary}\n日线数据(最近{len(df)}日):\n{table}\n")

    if not parts:
        return "未能拉取到任何一只的日线数据，请检查网络或稍后重试。"
    user = (
        "以下标的来自「未来3～5日看涨」预测排序或选股结果，请结合技术面给出：是否仍可持有或逢低加仓、还是短期观望/逢高减仓。"
        "不要仅因超买就一律建议卖出；若趋势未坏可给出「持有或回调加仓」等结论。\n\n"
        "选股结果及对应日线数据：\n\n" + "\n".join(parts)
    )
    system = get_a_share_kline_system_prompt()
    try:
        r = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": "deepseek-chat", "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}], "temperature": 0.3},
            timeout=120,
        )
        data = r.json()
        if r.status_code == 200 and data.get("choices"):
            return (data["choices"][0].get("message") or {}).get("content", "").strip() or "DeepSeek 未返回内容"
        err = data.get("error") or {}
        msg = err.get("message", str(data)) if isinstance(err, dict) else str(data)
        return f"DeepSeek 接口异常: {msg}"
    except requests.exceptions.Timeout:
        return "请求超时，请稍后重试。"
    except Exception as e:
        logger.exception("DeepSeek 日线解读: %s", e)
        return f"调用失败: {e}"


def _get_stock_name_by_code(code: str) -> str:
    """根据股票代码获取名称，失败则返回空字符串（前端可只显示代码）。"""
    if not HAS_AKSHARE or not code:
        return ""
    code = str(code).strip()
    try:
        df = ak.stock_individual_info_em(symbol=code)
        if df is None or df.empty or len(df.columns) < 2:
            return ""
        # 列名可能是 item/value 或 项目/值
        key_col = "item" if "item" in df.columns else (df.columns[0] if len(df.columns) else None)
        val_col = "value" if "value" in df.columns else (df.columns[1] if len(df.columns) > 1 else None)
        if not key_col or not val_col:
            return ""
        name_row = df[df[key_col].astype(str).str.strip().str.contains("股票简称|简称", na=False)]
        if not name_row.empty:
            return str(name_row[val_col].iloc[0]).strip()
    except Exception as e:
        logger.debug("获取股票名称 %s: %s", code, e)
    return ""


def _format_capital_number(v: Any) -> str:
    """将市值/股本等数值转为『xx 亿』『xx 万』等更易读格式。"""
    try:
        x = float(v)
    except Exception:
        return str(v)
    if x >= 1e8:
        return f"{x / 1e8:.1f}亿"
    if x >= 1e4:
        return f"{x / 1e4:.1f}万"
    return f"{x:.2f}"


def _get_basic_info_summary(code: str) -> str:
    """从东财接口获取个股部分基本面信息，整理成简要文本。失败返回空串。"""
    if not HAS_AKSHARE or not code:
        return ""
    code = str(code).strip()
    try:
        df = ak.stock_individual_info_em(symbol=code)
        if df is None or df.empty or len(df.columns) < 2:
            return ""
        key_col = "item" if "item" in df.columns else (df.columns[0] if len(df.columns) else None)
        val_col = "value" if "value" in df.columns else (df.columns[1] if len(df.columns) > 1 else None)
        if not key_col or not val_col:
            return ""
        items = df[key_col].astype(str).str.strip().tolist()
        values = df[val_col].tolist()
        kv = {str(k): v for k, v in zip(items, values)}

        def _find_first(keys) -> Optional[Any]:
            for k in keys:
                if k in kv:
                    return kv[k]
            # 支持模糊匹配（如包含“市盈率”）
            for name, val in kv.items():
                if any(sub in name for sub in keys):
                    return val
            return None

        industry = _find_first(["行业", "所属行业"])
        mktcap = _find_first(["总市值"])
        pe = _find_first(["市盈率", "市盈率(TTM)", "市盈率-动态"])
        pb = _find_first(["市净率"])
        roe = _find_first(["ROE", "净资产收益率"])
        growth = _find_first(["净利润同比", "净利润增长率"])
        total_share = _find_first(["总股本", "股本"])
        float_share = _find_first(["流通股", "流通股本"])
        list_date = _find_first(["上市时间", "上市日期"])

        parts: list[str] = []
        if industry:
            parts.append(f"行业: {industry}")
        if mktcap is not None:
            parts.append(f"总市值: {_format_capital_number(mktcap)}")
        if pe is not None:
            parts.append(f"市盈率: {pe}")
        if pb is not None:
            parts.append(f"市净率: {pb}")
        if roe is not None:
            parts.append(f"ROE: {roe}")
        if growth is not None:
            parts.append(f"净利增速: {growth}")
        if total_share is not None:
            parts.append(f"总股本: {_format_capital_number(total_share)}")
        if float_share is not None:
            parts.append(f"流通股: {_format_capital_number(float_share)}")
        if list_date is not None:
            parts.append(f"上市: {list_date}")
        # 尝试新浪财报最近一期关键指标（财：利润/收入；事：可结合公告）
        extra = _get_sina_financial_snippet(code)
        if extra:
            parts.append(extra)
        return "；".join(parts)
    except Exception as e:
        logger.debug("获取基本面信息 %s: %s", code, e)
        return ""


def _get_sina_financial_snippet(code: str) -> str:
    """尝试从新浪财报取最近一期净利润/营业收入等，用于基本面摘要。失败返回空串。"""
    if not HAS_AKSHARE or not code:
        return ""
    code = str(code).strip()
    try:
        func = getattr(ak, "stock_financial_report_sina", None)
        if func is None:
            return ""
        df = func(stock=code, symbol="利润表")
        if df is None or df.empty:
            return ""
        cols = [str(c).strip() for c in df.columns]
        date_col = next((c for c in cols if "报告期" in c or "报表日期" in c or "日期" in c), None)
        net_col = next((c for c in cols if "净利润" in c and "同比" not in c), None)
        rev_col = next((c for c in cols if "营业收入" in c or "营业总收入" in c), None)
        row = df.iloc[0]
        parts: list[str] = []
        if date_col:
            report_date = str(row.get(date_col, ""))[:10]
            if report_date and report_date != "nan":
                parts.append(f"最近报告期: {report_date}")
        if net_col:
            try:
                v = row.get(net_col)
                if v is not None and pd.notna(v):
                    parts.append(f"净利润: {_format_capital_number(float(v))}")
            except Exception:
                pass
        if rev_col:
            try:
                v = row.get(rev_col)
                if v is not None and pd.notna(v):
                    parts.append(f"营收: {_format_capital_number(float(v))}")
            except Exception:
                pass
        return "；".join(parts) if parts else ""
    except Exception as e:
        logger.debug("新浪财报摘要 %s: %s", code, e)
        return ""


def _get_news_summary(code: str, max_items: int = 8) -> str:
    """
    获取个股最近新闻标题摘要（来自东方财富），返回多行字符串。
    消息面建议用户结合财联社/金十/新浪财经等做盘中快讯补充。
    """
    if not HAS_AKSHARE or not code:
        return ""
    code = str(code).strip()
    try:
        func = getattr(ak, "stock_news_em", None)
        if func is None:
            return ""
        df = func(symbol=code)
        if df is None or df.empty:
            return ""
        cols = list(df.columns)
        # 标题/内容/时间/来源等列名在不同版本可能略有差异，这里做兼容处理
        title_col = "title" if "title" in cols else next((c for c in cols if "标题" in str(c)), None)
        time_col = "public_time" if "public_time" in cols else next((c for c in cols if "时间" in str(c)), None)
        source_col = next((c for c in cols if "来源" in str(c) or "媒体" in str(c)), None)
        if not title_col:
            return ""
        lines: list[str] = []
        for _, r in df.head(max_items).iterrows():
            t = str(r.get(time_col, "")) if time_col else ""
            title = str(r.get(title_col, "")).strip()
            if not title:
                continue
            src = str(r.get(source_col, "")).strip() if source_col else ""
            line = f"{t} {title}".strip()
            if src:
                line += f"（{src}）"
            lines.append(line)
        return "\n".join(lines)
    except Exception as e:
        logger.debug("获取新闻信息 %s: %s", code, e)
        return ""


def deepseek_analyze_single_stock(stock_code: str, daily_bars: int = 55) -> str:
    """
    根据用户输入的股票代码，从数据源拉取日 K 线，交给 DeepSeek 做单只股票分析。
    日线优先从本地 K 线缓存读取，不足时再走实时接口（腾讯/新浪/东财）。
    需配置 DEEPSEEK_API_KEY。
    """
    import os
    import requests
    from backpack_quant_trading.core.ai_adaptive import get_a_share_kline_system_prompt

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        return "请配置 DEEPSEEK_API_KEY 环境变量后使用股票分析。"
    code = str(stock_code).strip()
    if not code or len(code) < 5:
        return "请输入有效的 6 位 A 股代码（如 000001、600519）。"

    name = _get_stock_name_by_code(code) or code
    # 日线：点「分析」时优先拉取实时数据，保证最新交易日是最新的；失败再用缓存
    lookback = max(daily_bars, 120)
    daily = _fetch_daily(code, adjust="qfq", max_retries=2)
    if daily is not None and len(daily) > lookback:
        daily = daily.tail(lookback).reset_index(drop=True)
    if daily is None or len(daily) < 30:
        try:
            from backpack_quant_trading.core.stock_kline_cache import get_daily_klines_from_cache
            daily = get_daily_klines_from_cache(code, lookback_days=lookback)
        except Exception:
            pass
    if daily is None or len(daily) < 30:
        daily = _get_daily_for_screen(code, lookback_days=lookback)
    if daily is None or len(daily) < 30:
        return f"无法拉取 {code} {name} 的日 K 线数据（需至少 30 个交易日），请检查代码是否正确或稍后重试。"

    daily = daily.sort_values("date").reset_index(drop=True).tail(daily_bars)
    close = _safe_daily_series(daily, "close", "收盘")
    high = _safe_daily_series(daily, "high", "最高")
    low = _safe_daily_series(daily, "low", "最低")
    volume = _safe_daily_series(daily, "volume", "成交量")
    if volume is None or (hasattr(volume, "empty") and volume.empty):
        volume = pd.Series(1.0, index=close.index) if close is not None else None
    res = compute_composite_score(
        close, high, low, volume, stock_code=code, market=_code_to_market(code), skip_fund_flow=True
    )
    details = res.get("details", {})
    summary = (
        f"得分{res.get('score')} 最新价{float(close.iloc[-1]) if close is not None and len(close) else '-'} "
        f"RSI{details.get('rsi')} MACD柱{details.get('macd_hist')} KDJ(J){details.get('kdj_j')} 量比{details.get('volume_ratio')}"
    )
    basic_text = _get_basic_info_summary(code)
    news_text = _get_news_summary(code, max_items=8)
    daily["_dt"] = pd.to_datetime(daily["date"])
    rows = []
    for _, r in daily.iterrows():
        dt = r["_dt"].strftime("%Y-%m-%d") if hasattr(r["_dt"], "strftime") else str(r["date"])[:10]
        o, h, lo, c, v = r.get("open", ""), r.get("high", ""), r.get("low", ""), r.get("close", ""), r.get("volume", "")
        rows.append(f"{dt} {o} {h} {lo} {c} {v}")
    table = "日期 开盘 最高 最低 收盘 成交量\n" + "\n".join(rows)
    user_parts: list[str] = []
    user_parts.append(f"请对以下单只 A 股做综合分析：{code} {name}。")
    user_parts.append(f"【技术面摘要】{summary}")
    if basic_text:
        user_parts.append(f"【基本面简要】数据来源：东方财富/新浪。{basic_text}\n（深度研究建议查阅巨潮资讯网、交易所官网、Choice/同花顺/Wind。）")
    else:
        user_parts.append("【基本面简要】当前未拉取到东财/新浪财务摘要，分析时可默认视为中性；深度研究请查阅巨潮、交易所、Choice。")
    if news_text:
        user_parts.append("【消息面摘要】以下为东财个股最近新闻，请直接据此判断当前消息面对股价的正负影响和重要性：")
        user_parts.append(news_text)
    else:
        user_parts.append("【消息面摘要】暂未抓取到东财个股近期新闻，可视为消息面中性或影响较弱。")
    user_parts.append(f"【日线数据】以下为本次实时拉取的最新 {len(daily)} 日 OHLCV（最后一行为最新交易日）：\n{table}")
    user_parts.append(
        "请从技术面 + 基本面 + 消息面 三个维度给出综合分析。"
        "基本面请按「人（管理层）、财（资产负债/利润）、事（重大诉讼担保）、况（行业地位）」抓重点；"
        "消息面若当前仅有东财个股新闻，请在结论中注明并建议用户结合财联社/金十/新浪等做盘中快讯补充。"
        "最后在【策略建议】中给出是否适合当前介入/持有/观望，并明确止损与止盈参考。"
    )
    user = "\n\n".join(user_parts)
    system = get_a_share_kline_system_prompt()
    try:
        r = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": "deepseek-chat", "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}], "temperature": 0.3},
            timeout=120,
        )
        data = r.json()
        if r.status_code == 200 and data.get("choices"):
            return (data["choices"][0].get("message") or {}).get("content", "").strip() or "DeepSeek 未返回内容"
        err = data.get("error") or {}
        msg = err.get("message", str(data)) if isinstance(err, dict) else str(data)
        return f"DeepSeek 接口异常: {msg}"
    except requests.exceptions.Timeout:
        return "请求超时，请稍后重试。"
    except Exception as e:
        logger.exception("DeepSeek 单只股票分析: %s", e)
        return f"调用失败: {e}"
