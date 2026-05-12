"""
美股周报（免费数据源快照）

数据来源（均为免费、无需密钥；请遵守各站服务条款与访问频率）：
- Yahoo Finance v8 chart API（非官方）：指数/ETF/个股日线收盘价
- FRED 公开 CSV 导出：美债收益率 DGS10/DGS2、部分信用利差系列（若可用）

口径说明：
- 「近一周涨跌」：取最近一段日 K 中，**最后一根完整日 K 收盘价**相对 **往前第 5 个交易日** 收盘价的百分比变化（约等于一周交易日，非自然周）。
- 若历史不足 6 根有效收盘，则退化为首根至末根，并在字段中标注。
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from backpack_quant_trading.api.deps import require_user
from backpack_quant_trading.config.settings import config as _app_config

logger = logging.getLogger(__name__)

router = APIRouter()

YAHOO_CHART_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"
FRED_GRAPH_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"

UA = "Mozilla/5.0 (compatible; ApexAI-UsWeeklyReport/1.0; +https://example.local)"

# 简单的进程内 TTL 缓存：避免每次刷新都把 25+ 外部请求重新打一遍
_CACHE_LOCK = threading.Lock()
_CACHE: Dict[str, Any] = {"data": None, "ts": 0.0}
_CACHE_TTL_SEC = 300  # 5 分钟

# 历史分析结果持久化（JSON 文件，避免新建数据库表）
_HISTORY_LOCK = threading.Lock()
_HISTORY_PATH = Path(_app_config.data_dir) / "us_bubble_history.json"

# 泡沫阶段标签（与提示词一致）
BUBBLE_STAGES = [
    "1996-1998 早期扩散",
    "1999 叙事和估值同步加速",
    "2000Q1 顶部附近",
    "2000H2 订单和资本开支恶化",
    "2001-2002 信用风险暴露",
    "2003 后幸存者阶段",
]


def _resolve_proxies() -> Optional[Dict[str, str]]:
    """
    代理解析顺序（优先级从高到低）：
    1) 环境变量 US_REPORT_PROXY（仅此模块生效，如 http://127.0.0.1:7890）
    2) 系统 HTTPS_PROXY / HTTP_PROXY（requests 默认行为）
    3) 显式禁用代理：US_REPORT_NO_PROXY=1
    """
    if os.getenv("US_REPORT_NO_PROXY") in ("1", "true", "True"):
        return {"http": None, "https": None}
    explicit = os.getenv("US_REPORT_PROXY")
    if explicit:
        return {"http": explicit, "https": explicit}
    # 返回 None 表示「让 requests 自行用系统代理」
    return None


def _http_get(url: str, params: Optional[dict] = None, retries: int = 1) -> requests.Response:
    """
    对外部行情站请求：
    - 默认尊重系统代理（Clash 等），可通过 US_REPORT_PROXY 单独指定，或 US_REPORT_NO_PROXY=1 强制直连。
    - timeout 拉宽到 (8, 25)，失败重试 retries 次。
    """
    proxies = _resolve_proxies()
    last_exc: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            return requests.get(
                url,
                params=params or {},
                timeout=(8, 25),
                headers={"User-Agent": UA, "Accept": "application/json,text/csv,*/*"},
                proxies=proxies,
            )
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(0.6 * (attempt + 1))
                continue
            raise
    # 理论不会到这里
    if last_exc:
        raise last_exc
    raise RuntimeError("_http_get unknown error")


def _yahoo_series(symbol: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """
    返回 [{date, close, ts}, ...] 按时间升序；错误时第二项为错误说明。
    """
    enc = urllib.parse.quote(symbol, safe="")
    url = f"{YAHOO_CHART_BASE}/{enc}"
    try:
        r = _http_get(url, params={"range": "2mo", "interval": "1d"})
        r.raise_for_status()
        js = r.json()
    except Exception as e:
        return [], f"Yahoo 请求失败 {symbol}: {e}"

    try:
        res = js["chart"]["result"][0]
        ts_list = res.get("timestamp") or []
        _ind = res.get("indicators") or {}
        _qkey = "quote"
        _qrows = _ind.get(_qkey) or [{}]
        closes = (_qrows[0] or {}).get("close") or []
    except (KeyError, IndexError, TypeError) as e:
        return [], f"Yahoo 解析失败 {symbol}: {e}"

    out: List[Dict[str, Any]] = []
    for ts, c in zip(ts_list, closes):
        if c is None or ts is None:
            continue
        dt_utc = datetime.fromtimestamp(int(ts), tz=timezone.utc)
        out.append({
            "ts": int(ts),
            "date": dt_utc.strftime("%Y-%m-%d"),
            "close": float(c),
        })
    if not out:
        return [], f"Yahoo 无有效收盘 {symbol}"
    return out, None


def _week_like_return(closes_asc: List[Dict[str, Any]]) -> Dict[str, Any]:
    """最后一根相对往前第 5 根交易日的涨跌幅。"""
    n = len(closes_asc)
    if n < 2:
        return {"pct": None, "note": "数据不足", "from_date": None, "to_date": None, "from_close": None, "to_close": None}
    end = closes_asc[-1]
    start_idx = max(0, n - 6)
    start = closes_asc[start_idx]
    pct = (end["close"] - start["close"]) / start["close"] * 100.0 if start["close"] else None
    note = "近约5个交易日收盘到收盘" if n >= 6 else f"仅{n}根K线，为首末根涨跌"
    return {
        "pct": round(pct, 4) if pct is not None else None,
        "note": note,
        "from_date": start["date"],
        "to_date": end["date"],
        "from_close": start["close"],
        "to_close": end["close"],
    }


def _fred_latest_two(series_id: str) -> Dict[str, Any]:
    """拉取 FRED graph CSV 最近两行（用于展示最新值与上一日）。"""
    url = f"{FRED_GRAPH_CSV}?id={series_id}"
    try:
        r = _http_get(url)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
    except Exception as e:
        return {"series": series_id, "error": str(e), "source": url}

    # 列名可能是 observation_date 或 DATE，值列多为 series_id
    cols = list(df.columns)
    if len(cols) < 2:
        return {"series": series_id, "error": "CSV列异常", "source": url, "columns": cols}

    date_col = "observation_date" if "observation_date" in cols else cols[0]
    val_col = series_id if series_id in cols else cols[-1]
    df = df[[date_col, val_col]].dropna()
    df = df[df[val_col] != "."]
    if df.empty:
        return {"series": series_id, "error": "无有效观测", "source": url}

    df[val_col] = pd.to_numeric(df[val_col], errors="coerce")
    df = df.dropna(subset=[val_col])
    if len(df) < 1:
        return {"series": series_id, "error": "无数值", "source": url}

    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else None
    out: Dict[str, Any] = {
        "series": series_id,
        "source": url,
        "data_vendor": "FRED (St. Louis Fed) graph CSV export",
        "as_of_date": str(last[date_col]),
        "value_pct": float(last[val_col]),
        "field": "percent per annum" if series_id.startswith("DGS") else "index level / spread (see FRED definition)",
    }
    if prev is not None:
        out["prev_date"] = str(prev[date_col])
        out["prev_value_pct"] = float(prev[val_col])
        out["dod_bp"] = round((float(last[val_col]) - float(prev[val_col])) * 100.0, 2)  # 百分点→bp 显示用（对收益率序列）
    return out


def _build_index_row(label: str, yahoo_symbol: str) -> Dict[str, Any]:
    series, err = _yahoo_series(yahoo_symbol)
    if err:
        return {
            "label": label,
            "yahoo_symbol": yahoo_symbol,
            "error": err,
            "source": f"{YAHOO_CHART_BASE}/{urllib.parse.quote(yahoo_symbol, safe='')}?range=2mo&interval=1d",
            "data_vendor": "Yahoo Finance chart API (unofficial)",
        }
    ch = _week_like_return(series)
    last = series[-1]
    return {
        "label": label,
        "yahoo_symbol": yahoo_symbol,
        "last_date": last["date"],
        "last_close": last["close"],
        "week_change_pct": ch["pct"],
        "week_note": ch["note"],
        "week_from_date": ch["from_date"],
        "week_to_date": ch["to_date"],
        "source": f"{YAHOO_CHART_BASE}/{urllib.parse.quote(yahoo_symbol, safe='')}?range=2mo&interval=1d",
        "data_vendor": "Yahoo Finance chart API (unofficial)",
    }


def _build_snapshot_payload() -> Dict[str, Any]:
    generated_at_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    index_specs: List[Tuple[str, str]] = [
        ("标普500", "^GSPC"),
        ("纳斯达克综合", "^IXIC"),
        ("纳斯达克100", "^NDX"),
        ("QQQ", "QQQ"),
        ("罗素2000 ETF", "IWM"),
        ("费城半导体指数", "^SOX"),
        ("半导体 ETF SMH", "SMH"),
    ]
    vol_specs: List[Tuple[str, str]] = [
        ("VIX", "^VIX"),
        ("VVIX", "^VVIX"),
    ]
    watch_symbols = [
        "NVDA", "AMD", "AVGO", "TSM", "ASML", "ANET", "DELL", "SMCI",
        "ORCL", "MSFT", "GOOGL", "AMZN", "META", "PLTR", "TSLA",
    ]
    dxy_spec = ("美元指数期货连续", "DX-Y.NYB")
    fred_rates = [("DGS10", "rates"), ("DGS2", "rates")]
    fred_credit = [
        ("BAMLH0A0HYM2", "ICE BofA US High Yield OAS"),
        ("BAMLC0A4CBBB", "ICE BofA BBB US Corporate OAS（近似投资级端，非全 IG 指数）"),
    ]

    # 全部抓取任务并发执行（IO 密集，线程池足够）
    yahoo_jobs: List[Tuple[str, Tuple[str, str]]] = []
    for label, sym in index_specs:
        yahoo_jobs.append((f"idx::{sym}", (label, sym)))
    for label, sym in vol_specs:
        yahoo_jobs.append((f"vol::{sym}", (label, sym)))
    for sym in watch_symbols:
        yahoo_jobs.append((f"wl::{sym}", (sym, sym)))
    yahoo_jobs.append((f"dxy::{dxy_spec[1]}", dxy_spec))

    fred_jobs: List[str] = [sid for sid, _ in fred_rates] + [sid for sid, _ in fred_credit]

    results: Dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=12) as ex:
        fut_map: Dict[Any, str] = {}
        for key, (label, sym) in yahoo_jobs:
            fut = ex.submit(_build_index_row, label, sym)
            fut_map[fut] = key
        for sid in fred_jobs:
            fut = ex.submit(_fred_latest_two, sid)
            fut_map[fut] = f"fred::{sid}"
        for fut, key in fut_map.items():
            try:
                results[key] = fut.result(timeout=25)
            except Exception as e:
                results[key] = {"error": f"任务异常: {e!r}", "key": key}

    indices = [results[f"idx::{sym}"] for _, sym in index_specs]
    vol_block = {
        "vix": results[f"vol::^VIX"],
        "vvix": results[f"vol::^VVIX"],
        "note": "VIX/VVIX 为 Yahoo 日线收盘推导的「近约5交易日」变化，非 CBOE 官方实时推送。",
    }
    rates = {
        "dgs10": results.get("fred::DGS10", {"error": "未取到"}),
        "dgs2": results.get("fred::DGS2", {"error": "未取到"}),
        "note": "DGS10/DGS2 为 FRED 日频「市场预期」口径美债收益率（%），非拍卖中标利率。",
    }
    credit: Dict[str, Any] = {}
    for sid, name in fred_credit:
        row = results.get(f"fred::{sid}", {"series": sid, "error": "未取到"})
        if isinstance(row, dict):
            row["label"] = name
        credit[sid] = row
    tickers = [results[f"wl::{s}"] for s in watch_symbols]
    dxy = results[f"dxy::{dxy_spec[1]}"]

    disclaimer = (
        "本页为免费数据源自动聚合，仅供内部研究备忘，不构成投资建议。"
        "未覆盖部分（期权结构、宽度、私募融资、GPU 租价等）标注为未提供。"
        "若某字段抓取失败，以 error 为准，请勿用记忆补数。"
    )

    return {
        "generated_at_utc": generated_at_utc,
        "disclaimer": disclaimer,
        "sections_included": [
            "主要指数与半导体相关（Yahoo）",
            "波动率 VIX / VVIX（Yahoo）",
            "美债 10Y/2Y（FRED CSV）",
            "部分信用利差 HY/IG OAS（FRED CSV，若系列可用）",
            "观察清单大票日线快照（Yahoo）",
            "美元指数相关（Yahoo DX-Y.NYB）",
        ],
        "sections_excluded": [
            "休市日历（需交易所官方日历逐周核对，此处不自动推断）",
            "Put/Call、期权成交、CDX、市场宽度、Mag7 贡献分解",
            "Hyperscaler capex 细项、GPU 租赁价、AI 私募估值",
        ],
        "indices": indices,
        "volatility": vol_block,
        "rates": rates,
        "credit": credit,
        "dxy": dxy,
        "watchlist_equities": tickers,
    }


@router.get("/snapshot")
def us_weekly_snapshot(
    user: dict = Depends(require_user),
    force_refresh: bool = Query(False, description="忽略缓存，强制重新抓取"),
) -> Dict[str, Any]:
    """
    免费数据源「半套」周报快照：指数/波动率/部分利率与信用 + 若干 AI 链标的。
    不含：期权 put/call、市场宽度、Mag7 贡献分解、GPU 租赁价等（需付费或无法免费稳定验证）。

    内存级 TTL 缓存（默认 5 分钟）：避免每次刷新都重新打 20+ 外部请求。
    """
    now = time.time()
    if not force_refresh:
        with _CACHE_LOCK:
            if _CACHE["data"] is not None and (now - _CACHE["ts"]) < _CACHE_TTL_SEC:
                cached = dict(_CACHE["data"])
                cached["_cache_age_sec"] = round(now - _CACHE["ts"], 1)
                cached["_cache_ttl_sec"] = _CACHE_TTL_SEC
                return cached

    try:
        payload = _build_snapshot_payload()
        with _CACHE_LOCK:
            _CACHE["data"] = payload
            _CACHE["ts"] = time.time()
        payload["_cache_age_sec"] = 0.0
        payload["_cache_ttl_sec"] = _CACHE_TTL_SEC
        return payload
    except Exception as e:
        logger.exception("us_weekly_snapshot 聚合失败: %s", e)
        return {
            "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "fatal_error": repr(e),
            "disclaimer": "聚合过程发生异常，以下为占位；请查看 fatal_error 并重试或检查网络/代理。",
            "sections_included": [],
            "sections_excluded": [],
            "indices": [],
            "volatility": {"vix": {}, "vvix": {}, "note": ""},
            "rates": {},
            "credit": {},
            "dxy": {},
            "watchlist_equities": [],
        }


# ─────────────────────────────────────────────────────────
# 历史分析存储（JSON 文件）
# ─────────────────────────────────────────────────────────
def _history_load() -> List[Dict[str, Any]]:
    try:
        if not _HISTORY_PATH.exists():
            return []
        with open(_HISTORY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.warning("读取历史分析失败: %s", e)
        return []


def _history_save(items: List[Dict[str, Any]]) -> None:
    try:
        _HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_HISTORY_PATH, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("写入历史分析失败: %s", e)


def _history_append(item: Dict[str, Any]) -> None:
    with _HISTORY_LOCK:
        items = _history_load()
        items.append(item)
        # 保留最近 200 条即可
        if len(items) > 200:
            items = items[-200:]
        _history_save(items)


# ─────────────────────────────────────────────────────────
# DeepSeek 分析（按用户给定的“买方周度复盘”提示词）
# ─────────────────────────────────────────────────────────
_SYSTEM_PROMPT = """你是一名严谨的宏观科技周期研究员、买方策略分析师和交易风险顾问。
任务时间：中国时间每周六上午 10:00。
本任务用于复盘完整一周美股表现，并判断 AI 泡沫周期阶段和下一周交易计划。

我的目标（用户视角）：
1. 过去一周发生了什么；
2. 哪些事件是真正的转折点；
3. 当前 AI 泡沫接近互联网泡沫哪一阶段；
4. 市场是继续上涨、顶部震荡、下跌初期，还是泡沫破裂；
5. 下周应该持有、减仓、止盈、止损、对冲、买 put、做空还是等待；
6. 输出要短、清楚、可执行。

每周必须覆盖以下检查项（哪怕只能给出范围或「无法验证」也要逐项点名）：
1. 指数：SPX、NDX、QQQ、Nasdaq Composite、SOX、SMH、IWM。
2. 波动率：VIX、VVIX、期权 put/call、AI 龙头期权成交。
3. 利率和信用：10Y、2Y、实际利率、美元指数、HY OAS、IG OAS、CDX HY（如可得）。
4. 市场宽度：上涨家数、下跌家数、52 周新高新低、Mag 7 贡献、AI 股贡献。
5. AI 资本开支：MSFT、GOOGL、AMZN、META、ORCL、TSLA、xAI、OpenAI、Anthropic、CoreWeave、Nebius。
6. AI 供应链：NVDA、AMD、AVGO、TSM、ASML、SK Hynix、Micron、ANET、DELL、SMCI。
7. AI 需求：云 AI 收入、企业 AI 付费、AI 软件 ARR、模型 API 收入、ChatGPT/Claude/Gemini 使用与收入。
8. AI 单位经济：推理成本、GPU 租赁价格、毛利率、折旧、云毛利、AI 服务毛利。
9. 融资和 IPO：SpaceX、OpenAI、Anthropic 是否有 IPO 文件/融资/估值变化/二级交易/锁定期/私募估值下调。
10. 监管和地缘：芯片出口管制、反垄断、数据监管、电力审批、地缘冲突。

硬性规则：
1. 优先使用用户提供的数据快照；当某项缺失或 error，结合公开常识、长期估值锚、以及已知的近期宏观/AI 行业背景做**概率性**推断，**不要因为一两项数据缺失就整体拒绝判断**。
2. 关键数字尽量标注来源、发布日期、口径。
3. 不能凭空捏造数字；无法核实写「无法验证」，但其它判断仍要正常输出。
4. 每个判断区分：**事实 / 推论 / 概率情景 / 交易行动建议**。
5. 所有交易建议必须包含触发条件、失效条件、时间周期。
6. 不要长篇大论，不要空泛表达。
7. 没有明确交易机会，直接写「没有明确交易机会」。
8. 本周美股若休市，必须说明日期与原因，不要编造数据。
9. 不能输出整页空白或整页「无法判断」。即便没数据，也要给出 AI 周期阶段的**先验概率分布**和**三种情景计划**。

【关键】请在 Markdown 报告**末尾**额外输出一个 JSON 代码块（语言标记 json），用于程序化提取：
```json
{
  "stage": "1996-1998 早期扩散|1999 叙事和估值同步加速|2000Q1 顶部附近|2000H2 订单和资本开支恶化|2001-2002 信用风险暴露|2003 后幸存者阶段",
  "stage_probabilities": {
    "1996-1998 早期扩散": 0.0,
    "1999 叙事和估值同步加速": 0.0,
    "2000Q1 顶部附近": 0.0,
    "2000H2 订单和资本开支恶化": 0.0,
    "2001-2002 信用风险暴露": 0.0,
    "2003 后幸存者阶段": 0.0
  },
  "short_term_score": 0,
  "short_term_max": 20,
  "mid_term_score": 0,
  "mid_term_max": 25,
  "long_term_score": 0,
  "long_term_max": 25,
  "bubble_total_score": 0,
  "bubble_total_max": 70,
  "market_state": "上涨|强趋势|顶部震荡|下跌初期|泡沫破裂初期|信用压力阶段",
  "next_week_bias": "进攻|防守|震荡交易|等待",
  "short_term_bias": "进攻|防守|震荡交易",
  "mid_term_bias": "持有核心|逐步止盈|对冲|降低敞口",
  "analog_year": "1998|1999|2000Q1|2000H2|2001-2002|2003+"
}
```
其中 bubble_total_score = short_term_score + mid_term_score + long_term_score（取值 0–70）。
"""

_OUTPUT_FORMAT = """请使用以下中文 Markdown 输出格式（**逐项严格执行，不可遗漏**）：

【1. 本周总判断】
- 市场状态：上涨 / 强趋势 / 顶部震荡 / 下跌初期 / 泡沫破裂初期 / 信用压力阶段
- AI 泡沫阶段：1996-1998 早期扩散 / 1999 叙事和估值同步加速 / 2000Q1 顶部附近 /
  2000H2 订单和资本开支恶化 / 2001-2002 信用风险暴露 / 2003 后幸存者阶段
- 当前概率分布（表格）：| 阶段 | 概率 |
- 一句话结论：下周应该偏进攻 / 防守 / 震荡交易 / 等待

【2. 本周真正重要的 5 件事】
每条包括：事件 / 事实 / 来源和日期 / 为什么重要 / 影响方向 / 是否改变交易计划。

【3. 泡沫评分模型】
分三个时间维度打分，每项 0–5 分（0 = 健康，5 = 极端泡沫），必须给出关键判断依据。

评分锚定规则（强制）：
- 中期总分应围绕 12–13/25（当前周期已进入泡沫加速，不应超过 15）
- 长期总分应控制在 10/25 以下（结构性泡沫尚需验证，早期信号权重不宜过高）
- 短期总分反映即时交易压力，不受此锚定约束

3.1 短期泡沫压力（1–4 周交易窗口）
- 估值极端度（PE、PS、市值/收入、远期 PEG）
- 市场宽度与动量拥挤（Mag7 贡献、涨跌比、新高新低、SOX 超买幅度）
- 信用与流动性预警（HY OAS 周度变化、VIX/VVIX、put/call 比、私募信贷赎回）
- 事件催化剂风险（CPI、SpaceX IPO 招股书、NVDA 财报前仓位）
短期总分：__/20
短期结论：继续冲顶 / 震荡消化 / 已现下跌引信

3.2 中期泡沫积累（3–6 个月趋势）
评分基准：当前处于泡沫加速期，中期得分应在 12–15/25 区间，接近 15 即为高温预警。
- 资本开支过热（九大云厂 Capex 增速、折旧压力、GPU 订货倍数的二阶导数）
- 融资脆弱性（AI 私募估值上跳速度、IPO 抽水规模、非上市股权抵押贷款拒绝增加）
- 真实需求兑现的边际变化（云 AI 收入加速/首次减速、软件 ARR 续约率下降、API 收入增速收窄）
- 供给瓶颈缓解信号（HBM 交期开始缩短、租赁价格出现月度环比下降、电力审批通过加速）
- 龙头盈利质量拐点（毛利率见顶、FCF/净债务恶化、应收账款周转天数上升）
- 资本回报率边际递减（每 1 美元 Capex 带来的增量收入是否下降）
中期总分：__/25（锚定 12–15）
中期结论：泡沫加速 / 顶部构筑 / 需求首次出现边际放缓信号

3.3 长期结构性泡沫（1–3 年周期）
评分基准：长期得分应控制在 10/25 以下。仅当下列多项同时触发时才可给出 4–5 分：
- 监管/地缘出现不可逆分水岭（出口管制升级至全面封锁、主要国家禁建 AI 数据中心）
- Mega IPO 与私募抽水已实际发生并造成二级市场持续失血（非预期阶段）
- 二三线公司出现批量破产或债务违约（而非个别解散）
- 技术路线被确凿证伪（主流架构被替代方案全面超越，非实验室阶段）
- 信用市场系统性压力（IG/HY OAS 走扩 >150bp、AI 数据中心 CMBS 降级、银行收 AI 贷款敞口）
长期总分：__/25（锚定 ≤10）
长期结论：当前类似互联网泡沫哪一阶段（1998-1999 扩散 / 1999-2000 加速顶部 / 2000H2 破裂前 /
  2001-2002 信用出清 / 2003+ 幸存）

【三层次综合判断】
- 短期建议：进攻 / 防守 / 震荡交易
- 中期建议：持有核心 / 逐步止盈 / 对冲 / 降低敞口
- 长期类比年份：1998 / 1999 / 2000Q1 / 2000H2 / 2001-2002 / 2003+
- 最关键反证条件：（出现什么现象，上述判断立即失效）
- 总分（0–70）：__（短期 __/20 + 中期 __/25 + 长期 __/25；上期 __，变化 __）

【4. 我的持仓周度处理】（表格）
| 代码 | 当前状态 | 本周风险变化 | 建议动作（持有/加仓/减仓/止盈/止损/对冲/买 put/做空/不动）| 触发条件 | 失效条件 | 下周重点观察 |

【5. 下周三种情景计划】
情景一 继续上涨：触发条件 / 应该做什么 / 不能做什么
情景二 顶部震荡：触发条件 / 应该做什么 / 不能做什么
情景三 下跌或泡沫破裂：触发条件 / 应该做什么 / 不能做什么

【6. 下周交易行动清单】（最多 8 条）
每条：动作 / 标的 / 原因 / 触发条件 / 止损或失效条件 / 时间周期

【7. 下周必须盯的转折点】（最多 10 条）
重点：hyperscaler 资本开支、NVIDIA 毛利率/库存/应收、GPU 租赁价格、AI 云收入、
AI 软件付费、SpaceX IPO、OpenAI IPO、Anthropic 融资或 IPO、AI 数据中心融资、
高收益债利差、Nasdaq 和 SOX 趋势位。
"""


def _build_user_prompt(snapshot: Dict[str, Any], holdings: Optional[List[Dict[str, Any]]] = None, extra: str = "") -> str:
    holdings = holdings or []
    holdings_lines: List[str] = []
    if holdings:
        for h in holdings:
            holdings_lines.append(
                f"- {h.get('symbol','?')} | 方向={h.get('side','?')} | 仓位比例={h.get('weight','?')} | "
                f"成本={h.get('cost','?')} | 止损={h.get('stop','?')} | 目标={h.get('target','?')}"
            )
    else:
        holdings_lines.append("- 持仓未填写（仅给出宏观判断与三种情景计划）")

    watchlist = (
        "QQQ、SPY、IWM、SOXX、SMH、NVDA、AMD、AVGO、TSM、ASML、ANET、DELL、SMCI、"
        "ORCL、MSFT、GOOGL、AMZN、META、PLTR、SNOW、DDOG、MDB、NOW、CRM、TSLA"
    )

    snapshot_text = json.dumps(snapshot, ensure_ascii=False)
    # 数据量大，截断保留前 ~28KB
    if len(snapshot_text) > 28000:
        snapshot_text = snapshot_text[:28000] + "...(已截断)"

    return (
        f"## 用户持仓\n" + "\n".join(holdings_lines) + "\n\n"
        f"## 观察清单\n{watchlist}\n\n"
        f"## 额外说明\n{extra or '无'}\n\n"
        f"## 本周市场数据快照（JSON，免费数据源聚合）\n"
        f"```json\n{snapshot_text}\n```\n\n"
        f"{_OUTPUT_FORMAT}"
    )


def _extract_json_block(markdown: str) -> Dict[str, Any]:
    if not markdown:
        return {}
    # 优先匹配 ```json ... ```
    m = re.search(r"```json\s*(\{[\s\S]*?\})\s*```", markdown)
    if not m:
        # 退化：最后一个 {...} 块
        m = re.search(r"(\{[\s\S]*\})\s*$", markdown.strip())
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except Exception:
        return {}


def _call_deepseek(snapshot: Dict[str, Any], holdings: Optional[List[Dict[str, Any]]] = None, extra: str = "") -> Dict[str, Any]:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        return {"ok": False, "error": "未配置 DEEPSEEK_API_KEY"}

    user_prompt = _build_user_prompt(snapshot, holdings, extra)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
    }
    # DeepSeek 国内通常直连可用；如本机配了代理也允许走（由 _resolve_proxies 控制）
    try:
        r = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=120,
            proxies=_resolve_proxies(),
        )
    except Exception as e:
        return {"ok": False, "error": f"DeepSeek 网络错误: {e!r}"}

    try:
        data = r.json()
    except Exception:
        return {"ok": False, "error": f"DeepSeek 返回非 JSON, status={r.status_code}"}

    if r.status_code != 200 or not data.get("choices"):
        err = data.get("error", {})
        if isinstance(err, dict):
            err = err.get("message", str(data))
        return {"ok": False, "error": f"DeepSeek 调用失败: {err}"}

    markdown = data["choices"][0]["message"]["content"] or ""
    structured = _extract_json_block(markdown)
    return {
        "ok": True,
        "markdown": markdown,
        "structured": structured,
    }


# ─────────────────────────────────────────────────────────
# 分析接口 + 历史接口
# ─────────────────────────────────────────────────────────
class HoldingItem(BaseModel):
    symbol: str
    side: Optional[str] = "long"
    weight: Optional[float] = None
    cost: Optional[float] = None
    stop: Optional[float] = None
    target: Optional[float] = None


class AnalyzeRequest(BaseModel):
    holdings: Optional[List[HoldingItem]] = None
    extra: Optional[str] = ""
    force_refresh: Optional[bool] = False  # 强制重新抓取快照
    save: Optional[bool] = True  # 是否写入历史


def _do_analyze(holdings: Optional[List[Dict[str, Any]]], extra: str, force_refresh: bool, save: bool) -> Dict[str, Any]:
    # 1) 获取快照（默认走缓存以节省时间）
    if force_refresh:
        snapshot = _build_snapshot_payload()
        with _CACHE_LOCK:
            _CACHE["data"] = snapshot
            _CACHE["ts"] = time.time()
    else:
        with _CACHE_LOCK:
            cached = _CACHE.get("data")
            cached_age = time.time() - (_CACHE.get("ts") or 0)
        if cached and cached_age < _CACHE_TTL_SEC:
            snapshot = cached
        else:
            snapshot = _build_snapshot_payload()
            with _CACHE_LOCK:
                _CACHE["data"] = snapshot
                _CACHE["ts"] = time.time()

    # 2) 调用 DeepSeek
    ds = _call_deepseek(snapshot, holdings, extra)
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    record: Dict[str, Any] = {
        "generated_at_utc": now_utc,
        "ok": ds.get("ok", False),
    }

    if not ds.get("ok"):
        record["error"] = ds.get("error")
        return record

    structured = ds.get("structured") or {}

    def _num(x: Any) -> Optional[float]:
        try:
            return float(x) if x is not None else None
        except Exception:
            return None

    score_f = _num(structured.get("bubble_total_score"))
    short_f = _num(structured.get("short_term_score"))
    mid_f = _num(structured.get("mid_term_score"))
    long_f = _num(structured.get("long_term_score"))
    # 若模型没给 total，但三项分齐全，则自行加总
    if score_f is None and (short_f is not None or mid_f is not None or long_f is not None):
        score_f = sum(v for v in [short_f, mid_f, long_f] if v is not None)

    record.update({
        "markdown": ds.get("markdown", ""),
        "structured": structured,
        "bubble_total_score": score_f,
        "bubble_total_max": structured.get("bubble_total_max", 70),
        "short_term_score": short_f,
        "short_term_max": structured.get("short_term_max", 20),
        "mid_term_score": mid_f,
        "mid_term_max": structured.get("mid_term_max", 25),
        "long_term_score": long_f,
        "long_term_max": structured.get("long_term_max", 25),
        "stage": structured.get("stage"),
        "stage_probabilities": structured.get("stage_probabilities") or {},
        "market_state": structured.get("market_state"),
        "next_week_bias": structured.get("next_week_bias"),
        "short_term_bias": structured.get("short_term_bias"),
        "mid_term_bias": structured.get("mid_term_bias"),
        "analog_year": structured.get("analog_year"),
    })

    if save:
        _history_append({
            "generated_at_utc": now_utc,
            "bubble_total_score": score_f,
            "bubble_total_max": record["bubble_total_max"],
            "short_term_score": short_f,
            "short_term_max": record["short_term_max"],
            "mid_term_score": mid_f,
            "mid_term_max": record["mid_term_max"],
            "long_term_score": long_f,
            "long_term_max": record["long_term_max"],
            "stage": record["stage"],
            "market_state": record["market_state"],
            "next_week_bias": record["next_week_bias"],
            "short_term_bias": record["short_term_bias"],
            "mid_term_bias": record["mid_term_bias"],
            "analog_year": record["analog_year"],
            "stage_probabilities": record["stage_probabilities"],
            "markdown": record["markdown"],
        })
    return record


@router.post("/analyze")
def analyze_now(req: AnalyzeRequest, user: dict = Depends(require_user)) -> Dict[str, Any]:
    """手动触发一次分析（调用 DeepSeek）。"""
    holdings = [h.model_dump() if hasattr(h, "model_dump") else h.dict() for h in (req.holdings or [])]
    return _do_analyze(holdings, req.extra or "", bool(req.force_refresh), bool(req.save))


@router.get("/history")
def list_history(user: dict = Depends(require_user), limit: int = Query(80, ge=1, le=200)) -> Dict[str, Any]:
    items = _history_load()
    items = items[-limit:]
    series = [
        {
            "generated_at_utc": x.get("generated_at_utc"),
            "report_date": x.get("report_date"),
            "report_label": x.get("report_label"),
            "bubble_total_score": x.get("bubble_total_score"),
            "bubble_total_max": x.get("bubble_total_max", 70),
            "short_term_score": x.get("short_term_score"),
            "short_term_max": x.get("short_term_max", 20),
            "mid_term_score": x.get("mid_term_score"),
            "mid_term_max": x.get("mid_term_max", 25),
            "long_term_score": x.get("long_term_score"),
            "long_term_max": x.get("long_term_max", 25),
            "stage": x.get("stage"),
            "market_state": x.get("market_state"),
            "next_week_bias": x.get("next_week_bias"),
            "short_term_bias": x.get("short_term_bias"),
            "mid_term_bias": x.get("mid_term_bias"),
            "analog_year": x.get("analog_year"),
            "one_liner": x.get("one_liner"),
            "is_seed": x.get("is_seed", False),
            "has_report": bool(x.get("report")),
        }
        for x in items
    ]
    return {
        "stages": BUBBLE_STAGES,
        "count": len(series),
        "items": series,
    }


@router.get("/latest")
def latest_analysis(user: dict = Depends(require_user)) -> Dict[str, Any]:
    items = _history_load()
    if not items:
        return {"empty": True}
    return items[-1]


@router.get("/report")
def get_report_by_id(
    user: dict = Depends(require_user),
    id: str = Query(..., description="generated_at_utc 作为报告 ID"),
) -> Dict[str, Any]:
    """按 ID 取某一份完整周报。"""
    items = _history_load()
    for x in items:
        if (x.get("generated_at_utc") or "") == id:
            return x
    return {"empty": True, "error": "report not found"}


# 给定时任务用（无登录依赖）
def run_weekly_analyze_task() -> Dict[str, Any]:
    """由调度器调用：无 require_user 依赖，直接生成并落盘。"""
    try:
        return _do_analyze(holdings=None, extra="自动调度（每周六 10:00 CST）", force_refresh=True, save=True)
    except Exception as e:
        logger.exception("run_weekly_analyze_task 失败: %s", e)
        return {"ok": False, "error": repr(e)}
