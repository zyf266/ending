import pandas as pd
import numpy as np
import re
from typing import Dict, List, Optional
from .base import BaseStrategy, Signal, Position
from ..core.ai_adaptive import AIAdaptive
from ..utils.logger import get_logger
from ..config.settings import config

logger = get_logger(__name__)

class AIAdaptiveStrategy(BaseStrategy):
    """AI 自适应策略
    基于 DeepSeek V3 的数据分析能力进行买卖点判断
    采用渐进式分析: 快速判断(50根) + 深度确认(1000根)
    """
    def __init__(self, symbols: List[str], api_client=None, risk_manager=None, 
                 margin=None, leverage=None, stop_loss_ratio=None, take_profit_ratio=None):
        super().__init__("AI_Adaptive", symbols, api_client, risk_manager)
        self.ai = AIAdaptive()
        self.last_analysis_time = {} # 记录每个交易对最后一次分析的 1m 时间戳
        self.last_deep_analysis_time = {} # 记录最后一次深度分析时间
        
        # 【日内交易】持仓状态跟踪（关键：确保开平仓一一对应）
        self.current_positions = {}  # {symbol: {'side': 'long'/'short', 'entry_price': float, 'entry_time': datetime}}
        
        # 【成本优化】本地指标预筛选计数器
        self.ai_call_count = 0  # 统计AI调用次数
        self.local_filter_skip_count = 0  # 统计本地预筛选跳过次数
        
        # 【关键修复】K线数据总是从Backpack获取（不管下单用哪个交易所）
        from ..core.api_client import BackpackAPIClient
        self.kline_client = BackpackAPIClient()
        logger.info(f"📊 [AI策略] K线数据源: Backpack API")
        logger.info(f"📝 [AI策略] 下单接口: {api_client.__class__.__name__ if api_client else 'None'}")
        
        # 从页面参数或配置读取
        self.margin = margin if margin is not None else 100  # 默认100 USDC
        self.leverage = leverage if leverage is not None else getattr(config.trading, 'LEVERAGE', 50)
        self.stop_loss_ratio = stop_loss_ratio if stop_loss_ratio is not None else 0.015  # 默认1.5%
        self.take_profit_ratio = take_profit_ratio if take_profit_ratio is not None else 0.02  # 默认2%
        
        self.deep_analysis_interval = 2 * 60 * 60  # 深度分析间隔: 2小时(秒) - 日内交易缩短周期

        
        logger.info(f"="*80)
        logger.info(f"🤖 [AI策略] 初始化完成! (日内交易模式 + 本地指标预筛选)")
        logger.info(f"📊 [AI策略] 监控交易对: {', '.join(symbols)}")
        logger.info(f"💰 [AI策略] 保证金=${self.margin}, 杠杆={self.leverage}x, 止损={self.stop_loss_ratio*100}%, 止盈={self.take_profit_ratio*100}%")
        logger.info(f"⏰ [AI策略] 触发条件: 每1分钟收线时 (本地指标预筛选)")
        logger.info(f"🔄 [AI策略] 深度分析间隔: {self.deep_analysis_interval//3600}小时")
        logger.info(f"📌 [AI策略] 开平仓配对模式: 严格一一对应")
        logger.info(f"💡 [成本优化] 启用本地RSI/MACD/布林带预筛选，预计降低85%AI调用")
        logger.info(f"👁️ [AI策略] 等待下一个1分钟收线时刻...")
        logger.info(f"="*80)
        
    def _convert_to_backpack_format(self, symbol: str) -> str:
        """将交易对转换为Backpack格式
        
        Examples:
            ETH-USDT-SWAP (Deepcoin) -> ETH_USDC_PERP (Backpack)
            ETH_USDC_PERP (Backpack) -> ETH_USDC_PERP (不变)
        """
        # 如果已经是Backpack格式，直接返回
        if "_PERP" in symbol or "_USDC" in symbol:
            return symbol
        
        # 解析Deepcoin格式: ETH-USDT-SWAP
        if "-SWAP" in symbol or "-PERP" in symbol:
            clean = symbol.replace("-SWAP", "").replace("-PERP", "")
            parts = clean.split("-")
            if len(parts) >= 2:
                base = parts[0]  # ETH
                # Backpack使用USDC作为计价币
                return f"{base}_USDC_PERP"
        
        # 其他情况，直接返回
        return symbol
    
    def _calculate_technical_indicators(self, df: pd.DataFrame) -> Dict:
        """【成本优化】计算本地技术指标用于预筛选
        
        Args:
            df: K线数据DataFrame，包含open/high/low/close/volume
            
        Returns:
            dict: {
                'rsi': float,  # RSI(14)
                'macd_hist': float,  # MACD柱状图
                'bb_upper': float,  # 布林带上轨
                'bb_lower': float,  # 布林带下轨
                'price': float,  # 当前价格
                'atr': float  # ATR波动性指标
            }
        """
        try:
            # 确保数据足够
            if len(df) < 50:
                logger.warning(f"⚠️ [本地指标] K线数据不足: 当前{len(df)}根, 需要至少50根")
                return None
            
            logger.debug(f"📊 [本地指标] 开始计算, K线数据量: {len(df)}根")
            
            close = df['close'].values
            high = df['high'].values
            low = df['low'].values
            
            # 1. RSI(14)
            period = 14
            delta = np.diff(close)
            gains = np.where(delta > 0, delta, 0)
            losses = np.where(delta < 0, -delta, 0)
            
            avg_gain = np.mean(gains[-period:]) if len(gains) >= period else 0
            avg_loss = np.mean(losses[-period:]) if len(losses) >= period else 0
            
            if avg_loss == 0:
                rsi = 100
            else:
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
            
            # 2. MACD
            ema12 = pd.Series(close).ewm(span=12, adjust=False).mean().iloc[-1]
            ema26 = pd.Series(close).ewm(span=26, adjust=False).mean().iloc[-1]
            dif = ema12 - ema26
            
            # 计算DEA (DIF的9日EMA)
            dif_series = pd.Series(close).ewm(span=12, adjust=False).mean() - pd.Series(close).ewm(span=26, adjust=False).mean()
            dea = dif_series.ewm(span=9, adjust=False).mean().iloc[-1]
            macd_hist = dif - dea  # MACD柱状图
            
            # 3. 布林带 (20日, 2倍标准差)
            ma20 = np.mean(close[-20:])
            std20 = np.std(close[-20:])
            bb_upper = ma20 + 2 * std20
            bb_lower = ma20 - 2 * std20
            
            # 4. ATR(14)
            tr_list = []
            for i in range(1, min(15, len(high))):
                tr = max(
                    high[-i] - low[-i],
                    abs(high[-i] - close[-i-1]),
                    abs(low[-i] - close[-i-1])
                )
                tr_list.append(tr)
            atr = np.mean(tr_list) if tr_list else 0
            
            current_price = close[-1]
            
            return {
                'rsi': rsi,
                'macd_hist': macd_hist,
                'bb_upper': bb_upper,
                'bb_lower': bb_lower,
                'bb_middle': ma20,
                'price': current_price,
                'atr': atr
            }
        except Exception as e:
            logger.error(f"❌ [本地指标] 计算失败: {e}")
            logger.exception("详细错误信息:")
            return None
    
    def _should_call_ai_for_entry(self, indicators: Dict) -> bool:
        """【成本优化】判断是否需要调用AI进行开仓分析
        
        触发条件（满足任意2个）：
        1. RSI进入超买/超卖区域 (<40 或 >60)
        2. 价格触及布林带上下轨 (离轨道<5%)
        3. MACD柱状图绝对值较大 (>均值的2倍)
        """
        if not indicators:
            return False
        
        rsi = indicators['rsi']
        price = indicators['price']
        bb_upper = indicators['bb_upper']
        bb_lower = indicators['bb_lower']
        macd_hist = indicators['macd_hist']
        
        conditions_met = 0
        reasons = []
        
        # 条件1: RSI极端区域（放宽至45增加机会）
        if rsi < 45:
            conditions_met += 1
            reasons.append(f"RSI超卖({rsi:.1f})")
        elif rsi > 55:
            conditions_met += 1
            reasons.append(f"RSI超买({rsi:.1f})")
        
        # 条件2: 价格接近布林带边界
        dist_to_upper = abs(price - bb_upper) / price
        dist_to_lower = abs(price - bb_lower) / price
        
        if dist_to_upper < 0.01:  # 离上轨<1%
            conditions_met += 1
            reasons.append("触及布林上轨")
        elif dist_to_lower < 0.01:  # 离下轨<1%
            conditions_met += 1
            reasons.append("触及布林下轨")
        
        # 条件3: MACD柱状图明显
        if abs(macd_hist) > 0.5:  # 绝对值较大
            conditions_met += 1
            reasons.append(f"MACD强信号({macd_hist:.2f})")
        
        should_call = conditions_met >= 1  # 降低门槛：只需满足1个条件，增加交易机会
        
        if should_call:
            logger.info(f"✅ [本地预筛选] 满足{conditions_met}个条件，触发AI分析: {', '.join(reasons)}")
        else:
            logger.debug(f"⏭️ [本地预筛选] 条件不足({conditions_met}/1)，跳过AI调用")
            self.local_filter_skip_count += 1
        
        return should_call
    
    def _should_call_ai_for_exit(self, indicators: Dict, position: Dict) -> bool:
        """【成本优化】判断是否需要调用AI进行平仓分析
        
        触发条件（满足任意1个）：
        1. 浮盈 > 50% 或 浮亏 > 25%（100倍杠杆）
        2. RSI进入极端区域 (<30 或 >70)
        3. MACD柱状图反转
        """
        if not indicators or not position:
            return False
        
        side = position['side']
        entry_price = position['entry_price']
        current_price = indicators['price']
        rsi = indicators['rsi']
        
        # 计算浮动盈亏
        if side == 'long':
            pnl_pct = (current_price / entry_price - 1) * 100
        else:  # short
            pnl_pct = (1 - current_price / entry_price) * 100
        
        reasons = []
        
        # 条件1: 盈亏达到阈值（100倍杠杆）
        if pnl_pct > 50:
            reasons.append(f"浮盈{pnl_pct:.2f}%达到止盈线")
        elif pnl_pct < -25:
            reasons.append(f"浮亏{pnl_pct:.2f}%达到止损线")
        
        # 条件2: RSI极端
        if side == 'long' and rsi > 70:
            reasons.append(f"RSI超买({rsi:.1f})多单退出信号")
        elif side == 'short' and rsi < 30:
            reasons.append(f"RSI超卖({rsi:.1f})空单退出信号")
        
        should_call = len(reasons) > 0
        
        if should_call:
            logger.info(f"✅ [本地预筛选] 持仓监控触发AI分析: {', '.join(reasons)}")
        else:
            logger.debug(f"⏭️ [本地预筛选] 持仓状态正常，继续持有")
            self.local_filter_skip_count += 1
        
        return should_call
        
    async def calculate_signal(self, data: Dict[str, pd.DataFrame]) -> List[Signal]:
        """计算交易信号
        触发频率：每 1 分钟收线时触发一次
        数据来源：WebSocket实时推送的1分钟K线数据（已由live_trading维护）
        """
        signals = []
            
        logger.info(f"🔍 [AI策略] 开始检查信号, 共 {len(data)} 个交易对")
            
        for symbol, df in data.items():
            if df.empty:
                logger.warning(f"⚠️ [AI策略] {symbol} 数据为空,跳过")
                continue
                
            # 获取当前时间和价格（来自WebSocket实时数据）
            current_time = df.index[-1]
            current_price = df['close'].iloc[-1]
            logger.info(f"📅 [AI策略] {symbol} - 当前时间: {current_time}, 价格: ${current_price:.2f}, 分钟: {current_time.minute}")
            
            # 获取实际的系统时间（用于对比）
            from datetime import datetime
            system_time = datetime.now()
            time_diff = (system_time - current_time).total_seconds() / 60
            logger.info(f"⏰ [时间对比] 系统时间: {system_time.strftime('%Y-%m-%d %H:%M:%S')}, K线时间: {current_time}, 延迟: {time_diff:.1f}分钟")
                    
            # 1. 【日内交易】每1分钟收线都触发分析
            # 1分钟收线的逻辑：每分钟都触发，去重靠时间戳
            if True:  # 每分钟都触发
                # 【调试日志】检查去重逻辑
                last_time = self.last_analysis_time.get(symbol)
                logger.info(f"🔍 [去重检查] {symbol} 上次分析时间: {last_time}, 当前时间: {current_time}, 是否相同: {last_time == current_time}")
                
                if symbol not in self.last_analysis_time or self.last_analysis_time[symbol] != current_time:
                    logger.info(f"⚡ [AI策略] {symbol} 达到收线时刻,开始分析! @ {current_time}")
                    
                    # 【调试日志】检查DataFrame状态
                    logger.info(f"📊 [DataFrame检查] {symbol} K线数据量: {len(df)}根, 类型: {type(df)}, 列: {list(df.columns)}")
                    if len(df) > 0:
                        logger.debug(f"📊 [最新K线] 时间={df.index[-1]}, 价格={df['close'].iloc[-1]:.2f}")
                        if len(df) >= 5:
                            logger.debug(f"📊 [最近5根] {df.tail(5)[['close']].to_dict()}")
                    
                    # 【成本优化】先计算本地技术指标
                    indicators = self._calculate_technical_indicators(df)
                    if not indicators:
                        logger.warning(f"⚠️ [AI策略] {symbol} 指标计算失败，跳过本次分析")
                        continue
                    
                    logger.info(f"📊 [本地指标] RSI={indicators['rsi']:.1f}, MACD={indicators['macd_hist']:.2f}, 价格={indicators['price']:.2f}, BB=[{indicators['bb_lower']:.2f}, {indicators['bb_upper']:.2f}]")
                    
                    # 【成本优化】检查持仓状态，决定是否调用AI
                    current_position = self.current_positions.get(symbol)
                    
                    should_call_ai = False
                    if current_position is None:
                        # 空仓状态：判断是否需要调用AI寻找开仓机会
                        should_call_ai = self._should_call_ai_for_entry(indicators)
                    else:
                        # 持仓状态：判断是否需要调用AI监控平仓
                        should_call_ai = self._should_call_ai_for_exit(indicators, current_position)
                    
                    # 如果本地预筛选不通过，直接跳过AI调用
                    if not should_call_ai:
                        logger.info(f"💰 [成本优化] {symbol} 本地预筛选未通过，节省AI调用 (已节省{self.local_filter_skip_count}次)")
                        # 更新记录时间，避免在同一分钟内重复触发
                        self.last_analysis_time[symbol] = current_time
                        continue
                    
                    # 2. 判断是否需要深度分析（首次或距上次深度分析超过4小时）
                    try:
                        end_time_ts = int(datetime.now().timestamp())
                                            
                        # 判断是否需要深度分析
                        need_deep_analysis = False
                        if symbol not in self.last_deep_analysis_time:
                            need_deep_analysis = True
                            logger.info(f"🔍 [AI策略] {symbol} 首次分析,启用深度模式(1000根K线)")
                        else:
                            time_since_last_deep = end_time_ts - self.last_deep_analysis_time[symbol]
                            if time_since_last_deep >= self.deep_analysis_interval:
                                need_deep_analysis = True
                                logger.info(f"🔍 [AI策略] {symbol} 距上次深度分析已 {time_since_last_deep//3600} 小时,启用深度模式")
                            else:
                                logger.info(f"⏱️ [AI策略] {symbol} 使用WebSocket实时K线, 距下次深度分析还有 {(self.deep_analysis_interval - time_since_last_deep)//60} 分钟")
                        
                        # 3. 获取K线数据
                        if need_deep_analysis:
                            # 如果传入的 df 已经包含足够的数据（说明引擎已预加载），则直接使用
                            if len(df) >= 1000:
                                logger.info(f"📈 [AI策略] {symbol} 发现缓存中已有 {len(df)} 根K线，跳过重复REST下载")
                                kline_list = []
                                for idx, row in df.tail(1000).iterrows():
                                    kline_list.append({
                                        "time": idx.strftime('%Y-%m-%d %H:%M:%S'),
                                        "open": float(row['open']),
                                        "high": float(row['high']),
                                        "low": float(row['low']),
                                        "close": float(row['close']),
                                        "volume": float(row.get('volume', 0))
                                    })
                                analysis_mode = "深度分析(1000根-缓存)"
                            else:
                                # 深度分析: 通过REST API获取1000根历史K线 (日内交易使用1分钟K线)
                                start_time = end_time_ts - (1 * 24 * 60 * 60)  # 1天前 (1440个1分钟K线)
                                limit = 1000
                                analysis_mode = "深度分析(1000根-REST-1m)"
                                
                                logger.info(f"📡 [AI策略] {symbol} 深度分析：通过REST API获取1000根历史1分钟K线...")
                                
                                # 【关键修复】将交易对转换为Backpack格式
                                backpack_symbol = self._convert_to_backpack_format(symbol)
                                if backpack_symbol != symbol:
                                    logger.info(f"🔄 [AI策略] 交易对格式转换: {symbol} -> {backpack_symbol}")
                                
                                # 【修复】使用Backpack API获取K线（改为1m周期）
                                klines = await self.kline_client.get_klines(
                                    symbol=backpack_symbol,
                                    interval="1m",  # 日内交易使用1分钟周期
                                    start_time=start_time,
                                    end_time=end_time_ts,
                                    limit=limit
                                )
                                
                                # 取最近需要的数量
                                if len(klines) > limit:
                                    klines = klines[-limit:]
                                                
                                logger.info(f"✅ [AI策略] {symbol} REST API获取成功: {len(klines)} 根K线")
                                
                                # 格式化数据供AI分析
                                kline_list = []
                                for k in klines:
                                    if isinstance(k, dict):
                                        kline_list.append({
                                            "time": k.get('start') or k.get('timestamp') or k.get('t'),
                                            "open": float(k.get('open', 0)),
                                            "high": float(k.get('high', 0)),
                                            "low": float(k.get('low', 0)),
                                            "close": float(k.get('close', 0)),
                                            "volume": float(k.get('volume', 0))
                                        })
                                    elif isinstance(k, list) and len(k) >= 6:
                                        kline_list.append({
                                            "time": str(k[0]),
                                            "open": float(k[1]),
                                            "high": float(k[2]),
                                            "low": float(k[3]),
                                            "close": float(k[4]),
                                            "volume": float(k[5]) if len(k) > 5 else 0
                                        })
                        else:
                            # 快速判断: 直接使用WebSocket推送的实时K线（无需额外API调用）
                            analysis_mode = "快速判断(WebSocket实时)"
                            
                            # 检查DataFrame数据量
                            available_klines = len(df)
                            logger.info(f"📊 [AI策略] {symbol} 使用WebSocket K线缓存: {available_klines}根")
                            
                            if available_klines < 200:
                                logger.warning(f"⚠️ [AI策略] {symbol} K线数据不足({available_klines}根)，跳过本次分析")
                                logger.info(f"💡 建议：等待更多K线数据积累 (需200根以稳定计算MACD等指标)，或触发深度分析")
                                continue
                            
                            # 取最近300根（如果有的话）用于分析
                            use_count = min(300, available_klines)
                            df_recent = df.tail(use_count)
                            
                            logger.info(f"✅ [AI策略] {symbol} 使用最近 {use_count} 根实时K线进行分析")
                            
                            # 转换DataFrame为AI需要的格式
                            kline_list = []
                            for idx, row in df_recent.iterrows():
                                kline_list.append({
                                    "time": idx.strftime('%Y-%m-%d %H:%M:%S'),
                                    "open": float(row['open']),
                                    "high": float(row['high']),
                                    "low": float(row['low']),
                                    "close": float(row['close']),
                                    "volume": float(row.get('volume', 0))
                                })
                        
                        if not kline_list:
                            logger.warning(f"⚠️ [AI策略] {symbol} 没有可用的K线数据")
                            continue
                        
                        # 4. 调用 AI 分析
                        logger.info(f"🤖 [AI策略] {symbol} 开始AI分析: 模式={analysis_mode}, K线数量={len(kline_list)}根")
                        
                        # 【关键】检查当前持仓状态，决定AI提示词
                        current_position = self.current_positions.get(symbol)
                        
                        if need_deep_analysis:
                            # 深度分析模式：日内交易逻辑
                            if current_position is None:
                                # 空仓状态：寻找开仓机会
                                user_query = f"""【深度分析模式 - 日内交易 - 空仓寻找开仓机会】
你现在看到的是{len(kline_list)}根**1分钟**K线数据（约{len(kline_list)//60}小时）。

【当前持仓状态】
- **空仓**，需要寻找开仓机会（做多或做空）

【日内交易核心原则】
1. **严格开平仓配对**：每个开仓信号必须有对应的平仓目标
2. **止盈止损明确**：开仓时必须计算清楚平仓价格（止盈/止损）
3. **快进快出**：日内交易不过夜，每笔交易持仓时间不超过1小时
4. **高胜率点位**：RR比≥ 2:1，在支撑/阻力关键位入场

【开仓信号判断标准】
**做多信号条件：**
- 价格处于支撑位附近（均线支撑/前低点/布林下轨）
- RSI < 40（超卖区域） 或 MACD红柱放大
- K线出现反转信号（锤子线/看涨吞没/启明星）
- 量价配合：缩量回调到支撑位

**做空信号条件：**
- 价格处于阻力位附近（均线压力/前高点/布林上轨）
- RSI > 60（超买区域） 或 MACD绿柱放大
- K线出现反转信号（上吊线/看跌吞没/黄昏星）
- 量价背离：价格新高量未放大

【平仓目标计算】
开仓时**必须同时计算**平仓价格：
- **止盈位**：下一个阻力/支撑位，或按固定比例（如开仓价±2%）
- **止损位**：开仓价下方/上方的支撑/阻力，或按固定比例（如开仓价±1%）

【必须输出格式】
如果有开仓机会，必须输出：

做多信号: [价格]  # 当前价格，开多单
平多信号: [止盈价, 止损价]  # 先填止盈，后填止损，用逗号分隔

或

做空信号: [价格]  # 当前价格，开空单
平空信号: [止盈价, 止损价]  # 先填止盈，后填止损，用逗号分隔

【严格要求】
- 必须同时输出开仓和平仓信号（一一对应）
- 如果当时无法准确计算平仓价，可以先留空，等待下一根K线再判断
- 如果信号不明确，输出: []
"""
                            else:
                                # 持仓状态：监控平仓机会
                                side = current_position['side']
                                entry_price = current_position['entry_price']
                                user_query = f"""【深度分析模式 - 日内交易 - 持仓监控平仓】
你现在看到的是{len(kline_list)}根**1分钟**K线数据（约{len(kline_list)//60}小时）。

【当前持仓状态】
- 持有: **{side.upper()}**
- 开仓价: **{entry_price:.4f}**
- 当前价: **{kline_list[-1]['close']:.4f}**
- 浮动盈亏: **{((kline_list[-1]['close'] / entry_price - 1) * (1 if side == 'long' else -1) * 100):.2f}%**

【任务目标】
监控当前持仓，判断是否达到**止盈**或**止损**条件，决定是否平仓。

【平仓信号判断标准】
""" + (
    f"""
**平多条件（止盈）：**
- 价格上涨至阻力位（均线压力/前高点/布林上轨）
- RSI > 70（超买区域）
- MACD绿柱出现或红柱缩小
- 浮盈达到2%以上

**平多条件（止损）：**
- 价格跌破支撑位
- 浮亏达到1%
- 出现明显空头K线形态
""" if side == 'long' else f"""
**平空条件（止盈）：**
- 价格下跌至支撑位（均线支撑/前低点/布林下轨）
- RSI < 30（超卖区域）
- MACD红柱出现或绿柱缩小
- 浮盈达到2%以上

**平空条件（止损）：**
- 价格突破阻力位
- 浮亏达到1%
- 出现明显多头K线形态
"""
) + f"""

【必须输出格式】
如果达到平仓条件：

{'平多信号' if side == 'long' else '平空信号'}: [价格]  # 当前价格，平仓

如果未达到平仓条件，继续持有，输出: []
"""
                        else:
                            # 快速判断模式：日内交易逻辑
                            if current_position is None:
                                user_query = f"""【快速判断模式 - 日内交易 - 空仓寻找开仓机会】
你现在看到的是{len(kline_list)}根**1分钟**K线数据（约{len(kline_list)//60}小时）。

【当前持仓状态】空仓

【任务】寻找开仓机会（做多或做空），并计算平仓目标价

【必须输出格式】
做多信号: [价格]  # 开多价格
平多信号: [止盈价, 止损价]  # 用逗号分隔
或
做空信号: [价格]  # 开空价格
平空信号: [止盈价, 止损价]  # 用逗号分隔

如果无机会，输出: []
"""
                            else:
                                side = current_position['side']
                                entry_price = current_position['entry_price']
                                user_query = f"""【快速判断模式 - 日内交易 - 持仓监控】
你现在看到的是{len(kline_list)}根**1分钟**K线数据。

【当前持仓】持有{side.upper()}，开仓价{entry_price:.4f}，当前价{kline_list[-1]['close']:.4f}

【任务】判断是否达到止盈或止损条件

【必须输出格式】
{'平多信号' if side == 'long' else '平空信号'}: [价格]  # 平仓价格
或
[]  # 继续持有
"""

                        result = self.ai.analyze_kline(kline_data=kline_list, user_query=user_query)
                        analysis_text = result.get('analysis', '')
                        
                        # 【成本优化】统计AI调用次数
                        self.ai_call_count += 1
                        
                        logger.info(f"✅ [AI策略] {symbol} AI分析完成!")
                        logger.info(f"💰 [成本统计] AI调用={self.ai_call_count}次, 节省={self.local_filter_skip_count}次, 节省率={(self.local_filter_skip_count/(self.ai_call_count+self.local_filter_skip_count)*100) if (self.ai_call_count+self.local_filter_skip_count)>0 else 0:.1f}%")
                        logger.info(f"{'='*80}")
                        logger.info(f"📝 [AI分析结果] {symbol} - {analysis_mode}")
                        logger.info(f"{'='*80}")
                        logger.info(f"{analysis_text}")
                        logger.info(f"{'='*80}")
                        logger.info(f"分析字数: {len(analysis_text)}字")
                        logger.info(f"{'='*80}")
                        
                        # 5. 解析信号并判断是否需要升级为深度分析
                        current_price = kline_list[-1]['close'] if kline_list else df['close'].iloc[-1]
                                                
                        # 检查AI是否建议深度分析
                        if not need_deep_analysis and "需要深度分析" in analysis_text:
                            logger.info(f"⚡ [AI策略] {symbol} AI建议进行深度分析,下次将使用1000根K线")
                            # 强制下次进行深度分析
                            self.last_deep_analysis_time[symbol] = 0
                            # 跳过本次信号生成,等待下次15分钟的深度分析
                        else:
                            logger.info(f"🔍 [AI策略] {symbol} 开始解析AI信号...")
                            signal = await self._parse_ai_signal(symbol, analysis_text, current_price)
                            if signal:
                                logger.info(f"{'='*80}")
                                logger.info(f"✅ [交易信号生成] {symbol}")
                                logger.info(f"{'='*80}")
                                logger.info(f"  动作: {signal.action.upper()}")
                                logger.info(f"  交易对: {signal.symbol}")
                                logger.info(f"  目标价格: ${signal.price:.2f}")
                                logger.info(f"  数量: {signal.quantity}")
                                if signal.stop_loss:
                                    logger.info(f"  止损价: ${signal.stop_loss:.2f}")
                                if signal.take_profit:
                                    logger.info(f"  止盈价: ${signal.take_profit:.2f}")
                                logger.info(f"  原因: {signal.reason}")
                                logger.info(f"{'='*80}")
                                signals.append(signal)
                                # 生成信号后,更新深度分析时间
                                if need_deep_analysis:
                                    self.last_deep_analysis_time[symbol] = end_time_ts
                            else:
                                logger.info(f"⏸️ [AI策略] {symbol} 当前无交易信号")
                                logger.info(f"  AI建议: 观望或信号不明确")
                                                
                        # 6. 更新记录时间,避免在同一分钟内重复触发
                        self.last_analysis_time[symbol] = current_time
                                                
                        # 如果是深度分析,更新深度分析时间
                        if need_deep_analysis:
                            self.last_deep_analysis_time[symbol] = end_time_ts
                            next_deep_time = datetime.fromtimestamp(end_time_ts + self.deep_analysis_interval).strftime('%Y-%m-%d %H:%M')
                            logger.info(f"✅ [AI策略] {symbol} 深度分析完成,下次深度分析时间: {next_deep_time}")
                        
                    except Exception as e:
                        logger.error(f"❌ [AI策略] {symbol} 分析失败: {e}")
                        import traceback
                        traceback.print_exc()
                else:
                    logger.info(f"⏭️ [AI策略] {symbol} 跳过重复分析 (本时刻已处理过)")
            else:
                logger.debug(f"⏱️ [AI策略] {symbol} 未到收线时刻 (当前分钟: {current_time.minute}, 需要: 0/15/30/45)")
                    
        logger.info(f"{'='*80}")
        logger.info(f"🏁 [AI策略检查完成]")
        logger.info(f"  检查的交易对: {len(data)} 个")
        logger.info(f"  生成的信号: {len(signals)} 个")
        if signals:
            for sig in signals:
                logger.info(f"    - {sig.symbol}: {sig.action.upper()} @ ${sig.price:.2f}")
        else:
            logger.info(f"    当前市场条件下暂无交易机会")
        logger.info(f"{'='*80}")
        return signals

    async def _parse_ai_signal(self, symbol: str, text: str, current_price: float) -> Optional[Signal]:
        """从 AI 文本中解析买卖信号
        
        支持两种格式:
        1. 新格式(多空双向): 做多信号/平多信号/做空信号/平空信号
        2. 旧格式(兼容): 买入点位/卖出点位
        """
        # 首先尝试解析新格式（多空双向）
        long_entry_match = re.search(r'做多信号[：:]\s*\[(.*?)\]', text)
        long_exit_match = re.search(r'平多信号[：:]\s*\[(.*?)\]', text)
        short_entry_match = re.search(r'做空信号[：:]\s*\[(.*?)\]', text)
        short_exit_match = re.search(r'平空信号[：:]\s*\[(.*?)\]', text)
        
        # 如果找到新格式信号
        if long_entry_match or long_exit_match or short_entry_match or short_exit_match:
            logger.info(f"🔍 [AI解析] 使用新格式（多空双向）")
            
            # 检查当前持仓状态
            current_position = None
            if self.risk_manager and hasattr(self.risk_manager, 'positions'):
                for pos_symbol, pos in self.risk_manager.positions.items():
                    if pos_symbol == symbol:
                        current_position = pos
                        break
            
            # 状态机逻辑：根据持仓状态决定信号
            if current_position is None:
                # 空仓状态：只接受开仓信号（做多或做空）
                if long_entry_match:
                    try:
                        prices = [float(x.strip()) for x in long_entry_match.group(1).split(',') if x.strip()]
                        if prices:
                            target_price = prices[0]
                            logger.info(f"✅ [AI信号] 做多信号: ${target_price:.2f}")
                            return await self._create_signal(symbol, 'buy', target_price, current_price, "AI做多信号")
                    except Exception as e:
                        logger.warning(f"⚠️ 解析做多信号失败: {e}")
                
                if short_entry_match:
                    try:
                        prices = [float(x.strip()) for x in short_entry_match.group(1).split(',') if x.strip()]
                        if prices:
                            target_price = prices[0]
                            logger.info(f"✅ [AI信号] 做空信号: ${target_price:.2f}")
                            return await self._create_signal(symbol, 'sell', target_price, current_price, "AI做空信号")
                    except Exception as e:
                        logger.warning(f"⚠️ 解析做空信号失败: {e}")
            
            else:
                # 持仓状态：只接受对应的平仓信号
                if current_position.side == 'long' and long_exit_match:
                    try:
                        prices = [float(x.strip()) for x in long_exit_match.group(1).split(',') if x.strip()]
                        if prices:
                            target_price = prices[0]
                            logger.info(f"✅ [AI信号] 平多信号: ${target_price:.2f}")
                            return await self._create_signal(symbol, 'sell', target_price, current_price, "AI平多信号")
                    except Exception as e:
                        logger.warning(f"⚠️ 解析平多信号失败: {e}")
                
                elif current_position.side == 'short' and short_exit_match:
                    try:
                        prices = [float(x.strip()) for x in short_exit_match.group(1).split(',') if x.strip()]
                        if prices:
                            target_price = prices[0]
                            logger.info(f"✅ [AI信号] 平空信号: ${target_price:.2f}")
                            return await self._create_signal(symbol, 'buy', target_price, current_price, "AI平空信号")
                    except Exception as e:
                        logger.warning(f"⚠️ 解析平空信号失败: {e}")
                else:
                    logger.info(f"⏸️ [AI信号] 当前持{current_position.side}仓，但AI未给出对应的平仓信号")
            
            return None
        
        # 兼容旧格式
        logger.info(f"🔍 [AI解析] 尝试兼容旧格式（买入/卖出）")
        action = 'hold'
        if "买入" in text and "【策略建议】" in text:
            action = 'buy'
        elif "卖出" in text and "【策略建议】" in text:
            action = 'sell'
            
        if action == 'hold':
            return None
            
        # 尝试匹配点位
        buy_match = re.search(r"买入点位: \[(.*?)\]", text)
        sell_match = re.search(r"卖出点位: \[(.*?)\]", text)
        
        target_price = current_price
        
        if action == 'buy' and buy_match:
            try:
                prices = [float(x.strip()) for x in buy_match.group(1).split(',') if x.strip()]
                if prices: target_price = prices[0]
            except: pass
        elif action == 'sell' and sell_match:
            try:
                prices = [float(x.strip()) for x in sell_match.group(1).split(',') if x.strip()]
                if prices: target_price = prices[0]
            except: pass
        
        return await self._create_signal(symbol, action, target_price, current_price, f"AI{action}信号")
    
    async def _create_signal(self, symbol: str, action: str, target_price: float, current_price: float, reason: str) -> Optional[Signal]:
        """创建交易信号（统一处理止损止盈）"""
        # 解析止损止盈（如果AI提供）
        stop_loss = None
        take_profit = None
        
        # 如果AI没有给出止损止盈,使用页面配置的比例计算
        if stop_loss is None and self.stop_loss_ratio > 0:
            if action == 'buy':
                stop_loss = current_price * (1 - self.stop_loss_ratio)
            elif action == 'sell':
                stop_loss = current_price * (1 + self.stop_loss_ratio)
            logger.info(f"   使用页面止损比例: {self.stop_loss_ratio*100}%")
        
        if take_profit is None and self.take_profit_ratio > 0:
            if action == 'buy':
                take_profit = current_price * (1 + self.take_profit_ratio)
            elif action == 'sell':
                take_profit = current_price * (1 - self.take_profit_ratio)
            logger.info(f"   使用页面止盈比例: {self.take_profit_ratio*100}%")
        
        # 计算仓位大小
        quantity = await self._calculate_position_size(symbol, current_price)
        if quantity <= 0:
            logger.warning(f"AI 策略生成了 {action} 信号，但计算仓位为 0，跳过下单")
            return None
        
        # 日志输出交易信号详情
        logger.info(f"📢 AI生成交易信号: {action.upper()}")
        logger.info(f"   交易对: {symbol}")
        logger.info(f"   目标价格: ${target_price:.2f}")
        logger.info(f"   仓位大小: {quantity}")
        if stop_loss:
            logger.info(f"   止损价: ${stop_loss:.2f}")
        if take_profit:
            logger.info(f"   止盈价: ${take_profit:.2f}")
        
        return Signal(
            symbol=symbol,
            action=action,
            quantity=quantity,
            price=target_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            reason=reason
        )

    async def _calculate_position_size(self, symbol: str, price: float) -> float:
        """计算仓位大小(使用页面配置的保证金和杠杆)"""
        try:
            if self.api_client is None:
                return 0.01 # 模拟测试值
            
            # 获取余额
            balances = await self.api_client.get_balances()
            logger.info(f"💰 API返回的余额数据: {balances}")
            
            # 查找可用稳定币 (USDC/USDT)
            balance = 0.0
            balance_asset = None
            for asset in ['USDC', 'USDT']:
                if asset in balances:
                    asset_data = balances[asset]
                    logger.info(f"🔍 检查 {asset}: {asset_data}")
                    balance = float(asset_data.get('available', asset_data.get('availableBalance', asset_data.get('free', 0))))
                    if balance > 0:
                        balance_asset = asset
                        break
            
            if balance_asset:
                logger.info(f"✅ 找到可用余额: {balance_asset} = ${balance:.4f}")
            else:
                logger.warning(f"⚠️ 未找到USDC/USDT余额! 所有资产: {list(balances.keys())}")
            
            if balance <= 0:
                logger.warning(f"账户余额不足，无法计算仓位")
                return 0
            
            # 使用页面配置的保证金和杠杆
            margin = min(self.margin, balance)  # 保证金不超过余额
            position_value = margin * self.leverage
            
            quantity = position_value / price
            # 考虑最小单位
            logger.info(f"📈 仓位计算: 保证金=${margin:.2f}, 杠杆={self.leverage}x, 价格=${price:.2f} → 数量={quantity:.4f}")
            return round(quantity, 4)
            
        except Exception as e:
            logger.error(f"计算 AI 策略仓位失败: {e}")
            return 0

    def should_exit_position(self, position: Position, current_data: pd.Series) -> bool:
        """AI 策略的平仓逻辑
        目前主要依赖下单时 AI 给出的止损价，或在下一次 15m 收线时由 AI 判断
        """
        # 1. 基础止损检查
        if position.stop_loss:
            curr_price = current_data['price']
            if position.side == 'long' and curr_price <= position.stop_loss:
                return True
            if position.side == 'short' and curr_price >= position.stop_loss:
                return True
                
        # 2. AI 逻辑平仓将在 calculate_signal 中通过生成反向信号或平仓信号处理
        return False
