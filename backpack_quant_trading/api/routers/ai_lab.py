"""AI 自适应实验室 API - 完整迁移"""
import json
import re
import time
import requests
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from typing import Optional, List, Any, Tuple

from backpack_quant_trading.api.deps import require_user
from backpack_quant_trading.core.ai_adaptive import AIAdaptive, get_kline_analysis_system_prompt

router = APIRouter()

# 中文别名 -> 合约符号（只覆盖少数大币，其余走自动匹配）
CN_SYMBOL_ALIASES = {
    "比特": "BTCUSDT",
    "比特币": "BTCUSDT",
    "以太": "ETHUSDT",
    "以太坊": "ETHUSDT",
    "币安": "BNBUSDT",
    "瑞波": "XRPUSDT",
    "狗狗": "DOGEUSDT",
    "艾达": "ADAUSDT",
    "波卡": "DOTUSDT",
    "莱特": "LTCUSDT",
    "柴犬": "SHIBUSDT",
    "波场": "TRXUSDT",
}

# 周期关键词 -> 币安 interval
INTERVAL_KEYWORDS = [
    ("1分钟", "1m", "1分钟k线", "1mk"), "1m",
    ("5分钟", "5m", "5分钟k线", "5mk"), "5m",
    ("15分钟", "15m", "15分钟k线", "15mk", "15mk线"), "15m",
    ("30分钟", "30m", "30分钟k线", "30mk"), "30m",
    ("1小时", "1h", "1小时k线", "1hk", "1小时线"), "1h",
    ("2小时", "2h", "2小时k线", "2hk", "2小时线"), "2h",
    ("4小时", "4h", "4小时k线", "4hk"), "4h",
    ("6小时", "6h"), "6h",
    ("12小时", "12h"), "12h",
    ("日线", "1d", "日k", "1天", "天"), "1d",
    ("周线", "1w", "周k"), "1w",
]


def _guess_symbol_from_text(msg: str) -> str:
    """
    从用户输入中猜测币种：优先用中文别名，其次用任意字母数字组合匹配币安所有 USDT 永续合约。
    例如：sol / SOL / solusdt / 1000shib / shib 均可命中，只要币安上存在对应 USDT 永续合约。
    """
    from backpack_quant_trading.core.binance_monitor import fetch_binance_symbols_usdt

    default_symbol = "ETHUSDT"
    if not msg or not msg.strip():
        return default_symbol
    m = (msg or "").strip().lower()
    m_zh = msg.strip()
    m_no_space = m.replace(" ", "")
    m_zh_no_space = m_zh.replace(" ", "")

    # 1) 中文别名优先（比特、以太、波卡等）
    for kw, sym in CN_SYMBOL_ALIASES.items():
        if kw in m_zh:
            return sym

    # 2) 动态从币安获取所有 USDT 永续合约
    symbols = fetch_binance_symbols_usdt()  # 已带内部缓存
    if not symbols:
        return default_symbol
    sym_set = set(symbols)

    # 构建 base -> symbol 映射，如 BTC -> BTCUSDT, 1000SHIB -> 1000SHIBUSDT, SHIB -> 1000SHIBUSDT
    base_map: dict[str, str] = {}
    for s in symbols:
        if not s.endswith("USDT"):
            continue
        base = s[:-4]  # e.g. BTC, ETH, 1000SHIB
        base_lower = base.lower()
        base_map[base_lower] = s
        # 常见 1000 合约：允许用 shib 直接匹配 1000SHIBUSDT
        if base_lower.startswith("1000"):
            short = base_lower[4:]
            if short and short not in base_map:
                base_map[short] = s

    # 3) 提取可能的代码片段，如 sol / btc / arb / op / 1000shib
    tokens = re.findall(r"[a-zA-Z0-9]{2,15}", m)
    for tok in tokens:
        t = tok.lower()
        # 3.1 直接 base 匹配
        if t in base_map:
            return base_map[t]
        # 3.2 组合成 XXXUSDT 再匹配
        cand = f"{t.upper()}USDT"
        if cand in sym_set:
            return cand

    return default_symbol


def _parse_symbol_and_intervals(msg: str) -> Tuple[str, List[str]]:
    """
    从用户输入解析币种与 K 线周期。
    返回 (symbol, intervals)，如 ("BTCUSDT", ["15m"]) 或 ("SOLUSDT", ["2h", "15m"])。
    """
    if not msg or not msg.strip():
        return "ETHUSDT", ["15m"]
    m = (msg or "").strip().lower()
    m_zh = msg.strip()
    m_no_space = m.replace(" ", "")
    m_zh_no_space = m_zh.replace(" ", "")
    symbol = _guess_symbol_from_text(msg)
    intervals: List[str] = []

    # 解析周期：支持多周期，如「2小时和15分钟」
    seen: set = set()
    for i in range(0, len(INTERVAL_KEYWORDS), 2):
        keywords = INTERVAL_KEYWORDS[i]
        interval = INTERVAL_KEYWORDS[i + 1]
        for kw in keywords:
            if not isinstance(kw, str):
                continue
            kw_ns = kw.replace(" ", "")
            if ((kw in m) or (kw in m_zh) or (kw_ns in m_no_space) or (kw_ns in m_zh_no_space)) and interval not in seen:
                seen.add(interval)
                intervals.append(interval)
                break
    if not intervals:
        intervals = ["15m"]

    return symbol, intervals


class AnalyzeRequest(BaseModel):
    image_base64: Optional[str] = None  # data:image/png;base64,xxx
    kline_json: Optional[Any] = None
    user_query: str = "请根据当前的 K 线图形和原始数据，识别趋势并标注买卖点。"
    symbol: Optional[str] = None
    interval: Optional[str] = None


class ChatRequest(BaseModel):
    message: str
    history: Optional[List[dict]] = None  # [{role, content}, ...]


def _is_kline_analysis_intent(msg: str) -> bool:
    """检测用户是否在询问 K 线 / 行情分析"""
    kw = ["分析", "k线", "趋势", "买卖", "行情", "走势", "支撑", "阻力", "15m", "15分钟", "eth", "btc", "技术分析", "k线趋"]
    m = (msg or "").lower().replace(" ", "")
    return any(k in m for k in kw)


def _ts_to_readable(ts_ms: int) -> str:
    """时间戳(ms)转可读格式 YYYY-MM-DD HH:mm 北京时间"""
    from datetime import datetime, timezone, timedelta
    try:
        s = ts_ms if ts_ms >= 10000000000 else ts_ms * 1000
        tz = timezone(timedelta(hours=8))
        return datetime.fromtimestamp(s / 1000, tz=tz).strftime("%Y-%m-%d %H:%M") + " 北京时间"
    except Exception:
        return str(ts_ms)


def _fetch_and_format_kline_for_chat(symbol: str = "ETHUSDT", interval: str = "15m", limit: int = 800) -> str:
    """抓取币安 K 线并格式化为紧凑文本供 AI 分析，时间戳转为可读格式"""
    from backpack_quant_trading.core.binance_monitor import fetch_binance_klines_batch

    try:
        data = fetch_binance_klines_batch(symbol=symbol, interval=interval, total_limit=limit, batch_size=1000)
        if not data:
            return ""
        lines = []
        for c in data:
            dt = _ts_to_readable(c["time"])
            lines.append(f"{dt} O:{c['open']} H:{c['high']} L:{c['low']} C:{c['close']} V:{c.get('volume',0)}")
        return "\n".join(lines)
    except Exception:
        return ""


@router.post("/chat")
def chat(req: ChatRequest, user: dict = Depends(require_user)):
    """智能助手对话 - 支持「分析ETH 15m K线趋势」等智能分析，自动抓取最新数据"""
    import os
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        return {"reply": "暂无 AI 对话能力，请配置 DEEPSEEK_API_KEY 环境变量后使用。"}

    try:
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        user_msg = (req.message or "").strip()

        # 若为 K 线/行情分析意图，从用户输入解析币种与周期，再抓取对应数据
        kline_context = ""
        parsed_symbol = "ETHUSDT"
        parsed_intervals: List[str] = ["15m"]
        if _is_kline_analysis_intent(user_msg):
            parsed_symbol, parsed_intervals = _parse_symbol_and_intervals(user_msg)
            parts_list: List[str] = []
            for iv in parsed_intervals:
                try:
                    text = _fetch_and_format_kline_for_chat(symbol=parsed_symbol, interval=iv, limit=800)
                    if text:
                        label = {"1m": "1分钟", "5m": "5分钟", "15m": "15分钟", "30m": "30分钟",
                                 "1h": "1小时", "2h": "2小时", "4h": "4小时", "6h": "6小时",
                                 "12h": "12小时", "1d": "日线", "1w": "周线"}.get(iv, iv)
                        parts_list.append(f"【币安 {parsed_symbol} {label} K 线最新数据（按时间升序，最后一行最新）】\n{text}")
                except Exception:
                    continue
            if parts_list:
                kline_context = "\n\n".join(parts_list)
            if _is_kline_analysis_intent(user_msg) and not kline_context:
                return {"reply": "币安 K 线数据获取失败，请稍后重试或检查网络。"}

        # K 线分析时使用 ai_adaptive 的驯化知识库和输出格式，并强调按用户请求的币种与周期作答
        if kline_context:
            system_content = get_kline_analysis_system_prompt()
            _iv_labels = {"1m": "1分钟", "5m": "5分钟", "15m": "15分钟", "30m": "30分钟",
                         "1h": "1小时", "2h": "2小时", "4h": "4小时", "1d": "日线", "1w": "周线"}
            interval_desc = "、".join(_iv_labels.get(iv, iv) for iv in parsed_intervals)
            user_content = (
                f"用户需求：{user_msg}\n\n"
                f"重要：当前分析的品种是 **{parsed_symbol}**（币安永续），周期为 **{interval_desc}**。"
                "请严格按用户请求的币种与周期作答，不要分析成其他币种（例如用户问 BTC 就不要分析 ETH）。\n\n"
                "如果包含多个周期（例如 2 小时 + 15 分钟），请分别对每个周期给出趋势判断，可使用小标题（如「2 小时周期」「15 分钟周期」）进行对比分析，最后再给出综合策略结论。\n\n"
                f"{kline_context}\n\n"
                "请从技术面、基本面、消息面三个维度进行分析，并严格按照系统提示中的输出格式输出（趋势判断、策略建议、详细逻辑、交易参数）。"
            )
        else:
            system_content = """你是沐龙量化终端的智能助手，专精于加密货币量化交易、技术分析、网格策略、风险管理等。回答要简洁专业，必要时给出具体建议。"""
            user_content = user_msg

        messages = [{"role": "system", "content": system_content}]
        if req.history:
            for h in req.history[-8:]:
                if h.get("role") and h.get("content"):
                    messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": user_content})

        r = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers=headers,
            json={"model": "deepseek-chat", "messages": messages, "temperature": 0.3},
            timeout=90,
        )
        data = r.json()
        if r.status_code == 200 and data.get("choices"):
            reply = data["choices"][0]["message"]["content"]
            return {"reply": reply}
        err_info = data.get("error", {})
        if isinstance(err_info, dict):
            err_info = err_info.get("message", str(data))
        return {"reply": f"DeepSeek 接口异常: {err_info}"}
    except requests.exceptions.Timeout:
        return {"reply": "请求超时，K 线分析耗时较长，请稍后重试。"}
    except requests.exceptions.RequestException as e:
        return {"reply": f"网络请求失败: {str(e)}"}
    except Exception as e:
        return {"reply": f"服务异常: {str(e)}"}


@router.post("/fetch-kline")
def fetch_kline(
    user: dict = Depends(require_user),
    symbol: str = Query("ETHUSDT", description="交易对"),
    interval: str = Query("15m", description="K线周期 1m/15m/1h/4h/1d"),
    limit: int = Query(1500, ge=500, le=2000, description="K线数量"),
):
    """从币安分批次抓取最新 K 线（1000-2000 根），供 AI 技术分析"""
    from backpack_quant_trading.core.binance_monitor import fetch_binance_klines_batch

    limit = min(2000, max(500, limit))
    try:
        data = fetch_binance_klines_batch(
            symbol=symbol.upper(),
            interval=interval,
            total_limit=limit,
            batch_size=1000,
        )
        if not data:
            return {"error": "币安 API 无数据返回", "data": None}
        return {"data": data, "error": None}
    except Exception as e:
        return {"error": str(e), "data": None}


@router.post("/analyze")
def run_analyze(req: AnalyzeRequest, user: dict = Depends(require_user)):
    """AI 综合分析"""
    import base64
    import re
    import os

    temp_path = None
    if req.image_base64:
        try:
            data = req.image_base64.split(",")[1] if "," in req.image_base64 else req.image_base64
            temp_path = "temp_kline_upload.png"
            with open(temp_path, "wb") as f:
                f.write(base64.b64decode(data))
        except Exception as e:
            return {"analysis": f"图片解析失败: {e}", "buy": [], "sell": []}

    kline_json = req.kline_json
    if isinstance(kline_json, str):
        try:
            kline_json = json.loads(kline_json)
        except Exception:
            pass

    raw_symbol = (req.symbol or "ETHUSDT").upper()
    display_symbol = raw_symbol.replace("USDT", "/USDT") if raw_symbol.endswith("USDT") else raw_symbol
    iv = req.interval or "15m"
    full_query = (
        f"注意：当前分析的品种是 {display_symbol}（币安永续，周期 {iv}）。"
        "以下为最新一批 K 线数据，请严格基于最后一根 K 线的收盘价和形态进行分析，并结合技术面、基本面、消息面给出综合判断。"
        f"{req.user_query}"
    )

    try:
        ai = AIAdaptive()
        result = ai.analyze_kline(image_path=temp_path, kline_data=kline_json, user_query=full_query)
        analysis_text = result.get("analysis", "")
    except Exception as e:
        analysis_text = f"分析失败: {e}"
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)

    suggested_buy = []
    suggested_sell = []
    marker_section = re.search(r"【回测标注数据】.*?(买入点位.*)", analysis_text, re.DOTALL)
    search_text = marker_section.group(1) if marker_section else analysis_text

    def clean_price(s):
        return re.sub(r"[,\$￥\*%\sA-Za-z]", "", str(s))

    buy_match = re.search(r"买入点位[:：]\s*\[(.*?)\]", search_text)
    if buy_match:
        for item in buy_match.group(1).split(","):
            try:
                p = float(clean_price(item))
                if p > 0:
                    suggested_buy.append(p)
            except Exception:
                continue

    sell_match = re.search(r"卖出点位[:：]\s*\[(.*?)\]", search_text)
    if sell_match:
        for item in sell_match.group(1).split(","):
            try:
                p = float(clean_price(item))
                if p > 0:
                    suggested_sell.append(p)
            except Exception:
                continue

    return {
        "analysis": analysis_text,
        "buy": suggested_buy,
        "sell": suggested_sell,
    }
