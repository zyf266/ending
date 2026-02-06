"""AI 自适应实验室 API - 完整迁移"""
import json
import time
import requests
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from typing import Optional, List, Any

from backpack_quant_trading.api.deps import require_user
from backpack_quant_trading.core.ai_adaptive import AIAdaptive, get_kline_analysis_system_prompt

router = APIRouter()


class AnalyzeRequest(BaseModel):
    image_base64: Optional[str] = None  # data:image/png;base64,xxx
    kline_json: Optional[Any] = None
    user_query: str = "请根据当前的 K 线图形和原始数据，识别趋势并标注买卖点。"


class ChatRequest(BaseModel):
    message: str
    history: Optional[List[dict]] = None  # [{role, content}, ...]


def _is_kline_analysis_intent(msg: str) -> bool:
    """检测用户是否在询问 K 线 / 行情分析"""
    kw = ["分析", "k线", "趋势", "买卖", "行情", "走势", "支撑", "阻力", "15m", "15分钟", "eth", "btc", "技术分析"]
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

        # 若为 K 线/行情分析意图，自动抓取币安最新数据并注入上下文
        kline_context = ""
        if _is_kline_analysis_intent(user_msg):
            try:
                kline_context = _fetch_and_format_kline_for_chat(symbol="ETHUSDT", interval="15m", limit=800)
            except Exception as ek:
                kline_context = ""
            if kline_context:
                kline_context = (
                    f"\n\n【币安 ETH/USDT 15 分钟 K 线最新数据（按时间升序，最后一行最新）】\n{kline_context}\n"
                )
            elif _is_kline_analysis_intent(user_msg):
                return {"reply": "币安 K 线数据获取失败，请稍后重试或检查网络。"}

        # K 线分析时使用 ai_adaptive 的驯化知识库和输出格式
        if kline_context:
            system_content = get_kline_analysis_system_prompt()
            user_content = f"用户需求：{user_msg}\n\n{kline_context}\n\n请严格按照系统提示中的13大技术指标和输出格式进行分析。"
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

    target_symbol = "ETH/USDT"
    full_query = f"注意：当前分析的品种是 {target_symbol}（币安永续）。数据为最新 K 线，请严格基于最后一根 K 线的收盘价和形态进行分析。{req.user_query}"

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
