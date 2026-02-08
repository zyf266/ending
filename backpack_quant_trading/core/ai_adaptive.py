import os
import base64
import requests
import json
from backpack_quant_trading.utils.logger import get_logger

logger = get_logger("ai_adaptive")

# 驯化知识库 - 供 ai_lab 聊天分析复用
KNOWLEDGE_BASE = """
【核心策略知识库】:

1. 移动平均线 (MA):
   - 金叉: 短期MA上穿长期MA → 买入信号
   - 死叉: 短期MA下穿长期MA → 卖出信号
   - 多头排列: MA呈上升趋势排列 → 强势上涨
   - 空头排列: MA呈下降趋势排列 → 强势下跌
   - 常用周期: 5/10日(短线), 20/30/60日(中线), 120/250日(长线)

2. 布林带 (Bollinger Bands):
   - 中轨 = 20日SMA, 上轨 = 中轨 + 2σ, 下轨 = 中轨 - 2σ
   - 触及上轨: 超买 → 减仓/卖出
   - 触及下轨: 超卖 → 买入/补仓
   - 缩口后张口: 带宽从窄变宽 → 趋势启动
   - 喇叭口张开: 上下轨同时扩张 → 波动加大

3. RSI (相对强弱指数):
   - RSI > 80: 极度超买 → 强卖出信号
   - RSI > 70: 超买区域 → 减仓
   - RSI < 30: 超卖区域 → 建仓/加仓
   - RSI < 20: 极度超卖 → 强买入信号
   - 顶背离: 价格创新高，RSI未创新高 → 卖出
   - 底背离: 价格创新低，RSI未创新低 → 买入

4. KDJ (随机指标):
   - K>80, D>70: 超买 → 卖出
   - K<20, D<30: 超卖 → 买入
   - 金叉: K上穿D → 买入
   - 死叉: K下穿D → 卖出
   - J值极端: J>100或J<0 → 反转信号

5. MACD (异同移动平均线):
   - DIF = 12日EMA - 26日EMA, DEA = DIF的9日EMA
   - 零轴上方金叉: DIF上穿DEA>0 → 强烈买入
   - 零轴下方死叉: DIF下穿DEA<0 → 强烈卖出
   - 红柱放大/绿柱缩小: 动能增强 → 买入
   - 顶背离: 价↑柱↓ → 顶部信号
   - 底背离: 价↓柱↑ → 底部信号

6. 成交量与价格关系:
   - 价涨量增 → 健康上涨 → 买入
   - 价涨量缩 → 上涨乏力 → 卖出
   - 价跌量增 → 恐慌下跌 → 卖出
   - 价跌量缩 → 下跌尾声 → 买入
   - 天量见天价 → 顶部信号
   - 地量见地价 → 底部信号

7. ATR (平均真实波幅):
   - 止损设置: 止损位 = 买入价 - 2×ATR
   - ATR上升 = 波动加大 → 减仓

8. 斐波那契回调线:
   - 关键位: 23.6%, 38.2%, 50%, 61.8%, 78.6%
   - 支撑位: 下跌到61.8%/50%/38.2% → 买入
   - 阻力位: 上涨到38.2%/50%/61.8% → 卖出
   - 扩展位: 161.8%, 261.8% → 目标价位

9. Ichimoku云图:
   - 最强买入: 价栿>云层+三线多头排列
   - 买入: 价栿上穿云层
   - 卖出: 价栿下穿云层
   - 最强卖出: 价栿<云层+三线空头排列

10. K线形态 - 单根:
    - 大阳线: 实体长+上下影短 → 强势上涨 → 买入
    - 大阴线: 实体长+上下影短 → 强势下跌 → 卖出
    - 锤子线(下跌趋势): 下影长+上影短 → 底部反转 → 买入
    - 上吊线(上涨趋势): 下影长+上影短 → 顶部反转 → 卖出
    - 十字星: 实体极小 → 多空平衡 → 观望

11. K线形态 - 双根组合:
    - 看涨吞没: 阳线完全包住前阴线 → 强买入
    - 看跌吞没: 阴线完全包住前阳线 → 强卖出
    - 乌云盖顶: 阳线后高开低走阴线 → 卖出
    - 曙光初现: 阴线后低开高走阳线 → 买入

12. K线形态 - 三根及以上:
    - 早晨之星(底部): 阴-十字-阳 → 强烈买入
    - 黄昏之星(顶部): 阳-十字-阴 → 强烈卖出
    - 红三兵(上涨初期): 三连阳渐大 → 买入
    - 三只乌鸦(上涨末期): 三连阴渐大 → 卖出

13. 止损止盈原则:
    - 止损: 必须设在进场点下方最近的支撑位
    - 止盈: 必须设在进场点上方最近的压力位
    - 支撑压力识别: 重点关注144日和233日均线
"""


def get_kline_analysis_system_prompt() -> str:
    """返回 K 线技术分析的系统提示词（含知识库），供聊天分析复用"""
    return f"""你是一个顶级加密货币量化交易专家。
{KNOWLEDGE_BASE}

【任务目标】：
你现在收到的是 1000-2000 根 15 分钟 K 线数据（覆盖约 10-20 天），来自币安最新行情。
数据中的时间格式为 YYYY-MM-DD HH:mm 北京时间，按时间升序排列，最后一行是最新一根 K 线。
请基于这些真实最新数据进行全面的多周期技术分析，并对当前最新一根 K 线时刻给出精准的开平仓判断。
切勿使用虚构或过时的价格；务必引用数据中的实际收盘价和时间。

【分析要求】：
1. 综合运用知识库中的13大类技术指标（MA/布林带/RSI/KDJ/MACD/成交量/ATR/斐波那契/云图/K线形态等）
2. 识别多周期趋势（短期/中期趋势是否一致）
3. 寻找技术指标共振信号（多个指标同时发出买入/卖出信号）
4. 精确标注关键支撑位和压力位
5. 基于ATR和支撑压力位计算科学的止损止盈价格

【输出格式要求（必须严格遵守）】：
1. 【趋势判断】：分析整体趋势（上涨/下跌/震荡）及趋势强度。
2. 【策略建议】：明确给出当前最新时刻的操作建议（买入/卖出/观望）。
3. 【详细逻辑】：列出支持你判断的所有技术指标及其当前状态。

4. 【交易参数】（如果建议开仓）：
   严格按照以下格式在回复最末尾输出，不要带任何干扰字符：
   买入点位: [当前价格]
   卖出点位: []
   止损点位: [具体价格]
   止盈点位: [具体价格]
   
   注意：
   - 如果建议买入，买入点位填写当前价格，卖出点位留空
   - 如果建议卖出，卖出点位填写当前价格，买入点位留空
   - 止损必须基于ATR或最近支撑/压力位设置
   - 止盈建议设在下一个关键阻力/支撑位
"""


class AIAdaptive:
    def __init__(self):
        # API 配置
        self.vision_api_key = os.getenv("GEMINI_API_KEY") # 切换为 Gemini Key
        self.reasoning_api_key = os.getenv("DEEPSEEK_API_KEY") # DeepSeek V3 Key
        
        # Gemini 1.5 Flash 接口地址
        self.vision_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={self.vision_api_key}"
        self.reasoning_url = "https://api.deepseek.com/v1/chat/completions"

    def _encode_image(self, image_path):
        """图片转 Base64"""
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')

    def analyze_kline(self, image_path=None, kline_data=None, user_query="请分析当前买卖点"):
        """
        数据驱动模式：基于原始 OHLC 数据进行逻辑推演
        """
        # 1. 准备传给 DeepSeek 的上下文
        context = ""
        if kline_data:
            # 如果是列表 (来自 API 的数据)，转为易读的文本
            if isinstance(kline_data, list):
                context = "【K 线 OHLC 数据列表】:\n"
                # 为了支持全图回测标注，我们提供完整的 100 根 K 线数据
                for candle in kline_data:
                    context += f"时间: {candle.get('time')}, O: {candle.get('open')}, H: {candle.get('high')}, L: {candle.get('low')}, C: {candle.get('close')}\n"
            else:
                context = f"【K 线数据】: {str(kline_data)}\n"
        
        # 2. DeepSeek V3 逻辑推演
        logger.info("DeepSeek V3 正在进行纯数据驱动的策略分析...")
        analysis_result = self._get_deepseek_reasoning(context, user_query)
        
        return {
            "analysis": analysis_result
        }

    def _get_vision_description(self, image_base64):
        """视觉模型：使用 Gemini 1.5 Flash 提取图形特征"""
        if not self.vision_api_key:
            return "错误：未配置 Gemini API Key (GEMINI_API_KEY)"

        headers = {"Content-Type": "application/json"}
        
        # Gemini 的数据结构
        payload = {
            "contents": [{
                "parts": [
                    {"text": "你是一个K线识别专家。请描述这张图中：1. 当前形态（如双底、旗形等） 2. 主要指标（如RSI、MACD、布林带）所处的具体位置。3. 明显的支撑位和压力位。请只输出技术特征，不要给建议。"},
                    {
                        "inline_data": {
                            "mime_type": "image/png",
                            "data": image_base64
                        }
                    }
                ]
            }]
        }
        
        try:
            response = requests.post(self.vision_url, headers=headers, json=payload, timeout=30)
            res_json = response.json()
            # 解析 Gemini 返回的内容
            if 'candidates' in res_json:
                return res_json['candidates'][0]['content']['parts'][0]['text']
            else:
                return f"Gemini 接口响应异常: {res_json}"
        except Exception as e:
            return f"视觉识别错误 (Gemini): {str(e)}"

    def _get_deepseek_reasoning(self, features, query):
        """DeepSeek V3：深度逻辑分析 (包含驯化知识库)"""
        if not self.reasoning_api_key:
            return "错误：未配置 DeepSeek API Key"

        headers = {"Authorization": f"Bearer {self.reasoning_api_key}", "Content-Type": "application/json"}
        
        system_prompt = f"""你是一个顶级加密货币量化交易专家。
        {KNOWLEDGE_BASE}
        
        【任务目标】：
        你现在收到的是 1000-2000 根 15 分钟 K 线数据（覆盖约 10-20 天），来自币安最新行情。
        请基于这些真实最新数据进行全面的多周期技术分析，并对当前最新一根 K 线时刻给出精准的开平仓判断。
        注意：数据按时间升序，最后一根是最新；切勿使用过时或虚构的价格。
        
        【分析要求】：
        1. 综合运用知识库中的13大类技术指标（MA/布林带/RSI/KDJ/MACD/成交量/ATR/斐波那契/云图/K线形态等）
        2. 识别多周期趋势（短期/中期趋势是否一致）
        3. 寻找技术指标共振信号（多个指标同时发出买入/卖出信号）
        4. 精确标注关键支撑位和压力位
        5. 基于ATR和支撑压力位计算科学的止损止盈价格
        
        【输出格式要求（必须严格遵守）】：
        1. 【趋势判断】：分析整体趋势（上涨/下跌/震荡）及趋势强度。
        2. 【策略建议】：明确给出当前最新时刻的操作建议（买入/卖出/观望）。
        3. 【详细逻辑】：列出支持你判断的所有技术指标及其当前状态。
        
        4. 【交易参数】（如果建议开仓）：
           严格按照以下格式在回复最末尾输出，不要带任何干扰字符：
           买入点位: [当前价格]
           卖出点位: []
           止损点位: [具体价格]
           止盈点位: [具体价格]
           
           注意：
           - 如果建议买入，买入点位填写当前价格，卖出点位留空
           - 如果建议卖出，卖出点位填写当前价格，买入点位留空
           - 止损必须基于ATR或最近支撑/压力位设置
           - 止盈建议设在下一个关键阻力/支撑位
        """

        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"上下文背景：{features}\n用户需求：{query}"}
            ],
            "temperature": 0.3
        }
        try:
            response = requests.post(self.reasoning_url, headers=headers, json=payload, timeout=150)
            res_json = response.json()
            
            if response.status_code != 200:
                return f"DeepSeek API 错误 (状态码 {response.status_code}): {json.dumps(res_json, ensure_ascii=False)}"
                
            if 'choices' in res_json:
                return res_json['choices'][0]['message']['content']
            else:
                return f"API 响应结构异常: {json.dumps(res_json, ensure_ascii=False)}"
        except Exception as e:
            return f"网络或解析错误 (DeepSeek): {str(e)}"
