import pandas as pd
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
        self.last_analysis_time = {} # 记录每个交易对最后一次分析的 15m 时间戳
        self.last_deep_analysis_time = {} # 记录最后一次深度分析时间
        
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
        
        self.deep_analysis_interval = 4 * 60 * 60  # 深度分析间隔: 4小时(秒)

        
        logger.info(f"="*80)
        logger.info(f"🤖 [AI策略] 初始化完成!")
        logger.info(f"📊 [AI策略] 监控交易对: {', '.join(symbols)}")
        logger.info(f"💰 [AI策略] 保证金=${self.margin}, 杠杆={self.leverage}x, 止损={self.stop_loss_ratio*100}%, 止盈={self.take_profit_ratio*100}%")
        logger.info(f"⏰ [AI策略] 触发条件: 每15分钟收线时 (0分/15分/30分/45分)")
        logger.info(f"🔄 [AI策略] 深度分析间隔: {self.deep_analysis_interval//3600}小时")
        logger.info(f"👁️ [AI策略] 等待下一个15分钟收线时刻...")
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
        
    async def calculate_signal(self, data: Dict[str, pd.DataFrame]) -> List[Signal]:
        """计算交易信号
        触发频率：每 15 分钟收线时触发一次
        数据来源：WebSocket实时推送的K线数据（已由live_trading维护）
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
                    
            # 1. 检查是否到达 15 分钟收线时间
            # 15分钟收线的逻辑：当前分钟是 0, 15, 30, 45 
            # 且我们还没有处理过这个时间戳
            if current_time.minute % 15 == 0:
                # 【调试日志】检查去重逻辑
                last_time = self.last_analysis_time.get(symbol)
                logger.info(f"🔍 [去重检查] {symbol} 上次分析时间: {last_time}, 当前时间: {current_time}, 是否相同: {last_time == current_time}")
                
                if symbol not in self.last_analysis_time or self.last_analysis_time[symbol] != current_time:
                    logger.info(f"⚡ [AI策略] {symbol} 达到收线时刻,开始分析! @ {current_time}")
                    
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
                                # 深度分析: 通过REST API获取1000根历史K线
                                start_time = end_time_ts - (11 * 24 * 60 * 60)  # 11天前
                                limit = 1000
                                analysis_mode = "深度分析(1000根-REST)"
                                
                                logger.info(f"📡 [AI策略] {symbol} 深度分析：通过REST API获取1000根历史K线...")
                                
                                # 【关键修复】将交易对转换为Backpack格式
                                backpack_symbol = self._convert_to_backpack_format(symbol)
                                if backpack_symbol != symbol:
                                    logger.info(f"🔄 [AI策略] 交易对格式转换: {symbol} -> {backpack_symbol}")
                                
                                # 【修复】使用Backpack API获取K线
                                klines = await self.kline_client.get_klines(
                                    symbol=backpack_symbol,
                                    interval="15m",
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
                        if need_deep_analysis:
                            user_query = f"""【深度分析模式 - 实盘交易】
你现在看到的是{len(kline_list)}根15分钟K线数据(约{len(kline_list)*15//60//24}天)。

【专业技术分析框架】

1. 市场结构分析（趋势判断基石）
   - 上升趋势：更高高点(HH) + 更高低点(HL) → 回调买入
   - 下降趋势：更低低点(LL) + 更低高点(LH) → 反弹卖出
   - 结构转换：上升结构出现LH/下降结构出现HL → 趋势反转信号
   - 趋势线/通道线：连接2+个HH/HL或LL/LH，通道边界为关键位

2. 多周期共振（信号强化）
   - 长期趋势(5天+)：MA144/MA233方向
   - 中期趋势(2-3天)：MA55/MA89方向
   - 短期信号(当日)：MA21/MA34交叉
   - 共振原则：小周期信号需与大周期趋势一致
   - 顺大逆小：大周期上升时小周期回调买入，大周期下降时小周期反弹卖出

3. 支撑阻力位进阶
   - 水平位：历史高低点、整数关口、密集成交区
   - 均线位：144/233日均线为强支撑/阻力
   - 斐波那契位：0.618回撤买入，1.618扩展止盈
   - 支撑阻力转换：突破后的阻力变支撑，跌破后的支撑变阻力

4. 量价配合（验证趋势真伪）
   - 量价齐升：健康上涨，可加仓
   - 量价背离：价格新高量未放大 → 趋势衰竭
   - 缩量回调：上升中缩量至支撑位 → 买入
   - 放量突破：成交量>前5日均量2倍 → 强信号
   - 天量天价/地量地价：极端信号

5. 技术指标共振
   - MA金叉/死叉：斜率越大越可靠
   - MACD：红柱放大(做多)/绿柱放大(做空)
   - RSI：<30超卖(买入)/>70超买(卖出)，背离更强
   - 布林带：触及下轨买入/上轨卖出，缩口后突破为趋势启动
   - 多指标共振：≥3个指标同时确认 → 高胜率

6. K线形态识别
   - 反转形态：头肩顶底、双顶底、锤子线、吞没形态
   - 持续形态：旗形、三角形、矩形突破
   - 缺口：突破缺口跟随，衰竭缺口反做
   - 组合确认：需结合成交量和大周期

7. 风险收益比(RR)
   - 最低要求：RR ≥ 1.5:1（止盈1.5%/止损1%）
   - 理想目标：RR ≥ 3:1
   - 不符合RR的信号放弃

8. 市场环境适配
   - 趋势市：回调买入持有至反转
   - 震荡市：高抛低吸，布林带上下轨交易
   - 极端行情：避免追单，等待企稳

【交易决策流程】
Step 1: 识别长期趋势(5天+) → 确定大方向
Step 2: 确认中期趋势(2-3天) → 判断回调/反弹
Step 3: 寻找短期信号(当日) → 精准进场点
Step 4: 验证多指标共振 → 确认信号强度
Step 5: 检查量价配合 → 验证真伪
Step 6: 计算RR比 → 评估风险收益
Step 7: 识别关键支撑阻力 → 设置止损止盈

【必须输出格式】如果有交易机会，必须输出：

做多信号: [价格]  # 开多的点位（价格低位，预期上涨）
平多信号: [价格]  # 平多的点位（持多仓时，价格上涨后平仓）
做空信号: [价格]  # 开空的点位（价格高位，预期下跌）
平空信号: [价格]  # 平空的点位（持空仓时，价格下跌后平仓）

【严格要求】
- 必须基于完整框架分析，不能仅看单一指标
- 必须满足多周期共振，否则不输出信号
- 必须计算RR比≥1.5:1，否则不输出信号
- 必须验证量价配合，背离时谨慎
- 如果信号不明确，输出: []
                            """
                        else:
                            user_query = f"""【快速判断模式 - 实盘交易】
你现在看到的是{len(kline_list)}根15分钟K线数据(约{len(kline_list)*15//60}小时)。

【快速筛选检查清单】

1. 短期趋势判断
   - 最近3-5根K线方向（连续阳线/阴线）
   - MA21/MA34金叉/死叉（快速均线）
   - 价格位置：支撑位附近/阻力位附近/中间区域

2. 关键信号识别
   - K线形态：锤子线、吞没、启明星/黄昏星
   - MACD快线：红柱放大(多)/绿柱放大(空)
   - RSI：<30超卖(买)/>70超买(卖)
   - 布林带：触及下轨(买)/上轨(卖)

3. 量价验证
   - 上涨配合放量 → 健康
   - 上涨缩量/下跌放量 → 警惕

4. 风险位确认
   - 止损位：最近支撑/阻力
   - RR比：必须≥1.5:1

【决策标准】
✅ 输出信号条件：
- ≥2个指标共振确认
- RR比≥1.5:1
- 量价配合无明显背离
- 处于关键位（支撑/阻力附近）

⏸️ 需要深度分析条件：
- 信号冲突（指标背离）
- 趋势不明确（震荡市）
- 关键位突破待确认

❌ 无信号条件：
- 指标无共振
- RR比<1.5:1
- 量价严重背离
- 远离关键位

【必须输出格式】

做多信号: [价格]  # 开多点位
平多信号: [价格]  # 平多点位
做空信号: [价格]  # 开空点位
平空信号: [价格]  # 平空点位

【注意】
- 这是快速筛选，只在信号明确时输出
- 如果需要更多数据确认，在【策略建议】中说明"需要深度分析"
- 如果无机会，输出: []
                            """

                        result = self.ai.analyze_kline(kline_data=kline_list, user_query=user_query)
                        analysis_text = result.get('analysis', '')
                        
                        logger.info(f"✅ [AI策略] {symbol} AI分析完成!")
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
