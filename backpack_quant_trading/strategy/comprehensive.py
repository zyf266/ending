"""
综合性策略 - 多指标评分系统
基于AI Prompt中的开平仓条件，直接用代码实现

策略核心：
1. 符合1个指标 → 下单5U
2. 符合2个指标 → 下单10U
3. 符合3个以上指标 → 下单20U

本金：500U
杠杆：100x
"""

from decimal import Decimal
from typing import Dict, List, Optional
import pandas as pd
import numpy as np
from loguru import logger

from backpack_quant_trading.strategy.base import BaseStrategy, Signal, Position
from backpack_quant_trading.config.settings import TradingConfig


class ComprehensiveStrategy(BaseStrategy):
    """综合性策略 - 多指标评分开仓"""
    
    def __init__(self, symbols: List[str], config: TradingConfig, params: Optional[Dict] = None):
        # 【关键修复】调用父类构造函数，传入需要的参数
        # BaseStrategy需要: name, symbols, api_client, risk_manager
        # 因为回测不需要真实API客户端，设置为None
        super().__init__(
            name="ComprehensiveStrategy",
            symbols=symbols,
            api_client=None,  # 回测不需要API客户端
            risk_manager=None  # 回测不需要风控管理器
        )
        
        # 策略参数
        self.initial_capital = 500  # 初始资金500U
        self.leverage = 100  # 100倍杠杆
        
        # 保证金配置（根据信号强度）
        self.margin_level_1 = 5.0   # 1个指标：5U
        self.margin_level_2 = 10.0  # 2个指标：10U
        self.margin_level_3 = 20.0  # 3个以上指标：20U
        
        # 止盈止损配置
        self.take_profit_pct = 0.30  # 【优化】止盈：30%（100倍杠杆下相当于价格波动0.3%）
        self.stop_loss_pct = 0.15    # 【优化】止损：15%（100倍杠杆下相当于价格波动0.15%）
        
        # 指标阈值
        self.rsi_oversold = 40      # RSI超卖
        self.rsi_overbought = 60    # RSI超买
        self.rsi_take_profit_long = 70   # 平多RSI阈值
        self.rsi_take_profit_short = 30  # 平空RSI阈值
        
        # 【新增】冷静期：平仓后多少根K线不开新仓（避免频繁交易）
        self.cooldown_period = 10  # 【优化】10根K线冷静期（原5根太短）
        self.last_exit_time = {}  # 记录每个交易对的最后平仓时间
        
        # 如果传入了params，覆盖默认值
        if params:
            self.initial_capital = params.get('initial_capital', self.initial_capital)
            self.margin_level_1 = params.get('margin_level_1', self.margin_level_1)
            self.margin_level_2 = params.get('margin_level_2', self.margin_level_2)
            self.margin_level_3 = params.get('margin_level_3', self.margin_level_3)
            self.take_profit_pct = params.get('take_profit_pct', self.take_profit_pct)
            self.stop_loss_pct = params.get('stop_loss_pct', self.stop_loss_pct)
        
    def calculate_technical_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算技术指标"""
        if len(df) < 50:
            return df
        
        # 1. 移动平均线
        df['MA20'] = df['close'].rolling(window=20).mean()
        df['MA50'] = df['close'].rolling(window=50).mean()
        
        # 2. 布林带
        df['BB_MIDDLE'] = df['close'].rolling(window=20).mean()
        bb_std = df['close'].rolling(window=20).std()
        df['BB_UPPER'] = df['BB_MIDDLE'] + 2 * bb_std
        df['BB_LOWER'] = df['BB_MIDDLE'] - 2 * bb_std
        
        # 3. RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        
        # 4. MACD
        ema12 = df['close'].ewm(span=12, adjust=False).mean()
        ema26 = df['close'].ewm(span=26, adjust=False).mean()
        df['MACD'] = ema12 - ema26
        df['MACD_SIGNAL'] = df['MACD'].ewm(span=9, adjust=False).mean()
        df['MACD_HIST'] = df['MACD'] - df['MACD_SIGNAL']
        
        # 5. 成交量指标
        df['VOLUME_MA20'] = df['volume'].rolling(window=20).mean()
        
        return df
    
    def check_long_entry_conditions(self, df: pd.DataFrame) -> int:
        """检查做多开仓条件，返回满足的条件数量
        
        做多信号条件（来自AI Prompt）：
        1. 价格处于支撑位附近（均线支撑/前低点/布林下轨）
        2. RSI < 40（超卖区域） 或 MACD红柱放大
        3. K线出现反转信号（锤子线/看涨吞没）
        4. 量价配合：缩量回调到支撑位
        """
        if len(df) < 50:
            return 0
        
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        count = 0
        
        # 条件1: 价格接近支撑位（布林下轨或MA20）
        close = latest['close']
        bb_lower = latest['BB_LOWER']
        ma20 = latest['MA20']
        
        # 价格在布林下轨附近（±1%）或低于MA20
        if close <= bb_lower * 1.01 or close < ma20:
            count += 1
            logger.debug(f"✅ 做多条件1: 价格在支撑位附近 (close={close:.2f}, BB下轨={bb_lower:.2f}, MA20={ma20:.2f})")
        
        # 条件2: RSI超卖 或 MACD红柱放大
        rsi = latest['RSI']
        macd_hist = latest['MACD_HIST']
        prev_macd_hist = prev['MACD_HIST']
        
        if rsi < self.rsi_oversold or (macd_hist > 0 and macd_hist > prev_macd_hist):
            count += 1
            logger.debug(f"✅ 做多条件2: RSI超卖或MACD红柱放大 (RSI={rsi:.2f}, MACD_HIST={macd_hist:.4f})")
        
        # 条件3: K线反转信号 - 锤子线（下影线长，实体小）
        body = abs(latest['close'] - latest['open'])
        lower_shadow = min(latest['open'], latest['close']) - latest['low']
        upper_shadow = latest['high'] - max(latest['open'], latest['close'])
        
        # 锤子线：下影线 > 实体*2，上影线很小，且收盘价上涨
        is_hammer = (lower_shadow > body * 2 and upper_shadow < body and latest['close'] > latest['open'])
        
        # 看涨吞没：当前K线阳线吞没前一根阴线
        is_bullish_engulfing = (prev['close'] < prev['open'] and 
                                latest['close'] > latest['open'] and
                                latest['close'] > prev['open'] and
                                latest['open'] < prev['close'])
        
        if is_hammer or is_bullish_engulfing:
            count += 1
            pattern = "锤子线" if is_hammer else "看涨吞没"
            logger.debug(f"✅ 做多条件3: K线反转信号 ({pattern})")
        
        # 条件4: 量价配合 - 缩量回调（成交量低于均值）
        volume = latest['volume']
        volume_ma = latest['VOLUME_MA20']
        
        if volume < volume_ma * 0.8 and close < prev['close']:
            count += 1
            logger.debug(f"✅ 做多条件4: 缩量回调 (volume={volume:.0f}, MA={volume_ma:.0f})")
        
        return count
    
    def check_short_entry_conditions(self, df: pd.DataFrame) -> int:
        """检查做空开仓条件，返回满足的条件数量
        
        做空信号条件（来自AI Prompt）：
        1. 价格处于阻力位附近（均线压力/前高点/布林上轨）
        2. RSI > 60（超买区域） 或 MACD绿柱放大
        3. K线出现反转信号（上吊线/看跌吞没）
        4. 量价背离：价格新高量未放大
        """
        if len(df) < 50:
            return 0
        
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        count = 0
        
        # 条件1: 价格接近阻力位（布林上轨或MA20）
        close = latest['close']
        bb_upper = latest['BB_UPPER']
        ma20 = latest['MA20']
        
        # 价格在布林上轨附近（±1%）或高于MA20
        if close >= bb_upper * 0.99 or close > ma20:
            count += 1
            logger.debug(f"✅ 做空条件1: 价格在阻力位附近 (close={close:.2f}, BB上轨={bb_upper:.2f}, MA20={ma20:.2f})")
        
        # 条件2: RSI超买 或 MACD绿柱放大
        rsi = latest['RSI']
        macd_hist = latest['MACD_HIST']
        prev_macd_hist = prev['MACD_HIST']
        
        if rsi > self.rsi_overbought or (macd_hist < 0 and macd_hist < prev_macd_hist):
            count += 1
            logger.debug(f"✅ 做空条件2: RSI超买或MACD绿柱放大 (RSI={rsi:.2f}, MACD_HIST={macd_hist:.4f})")
        
        # 条件3: K线反转信号 - 上吊线（上影线长，实体小）
        body = abs(latest['close'] - latest['open'])
        lower_shadow = min(latest['open'], latest['close']) - latest['low']
        upper_shadow = latest['high'] - max(latest['open'], latest['close'])
        
        # 上吊线：上影线 > 实体*2，下影线很小，且收盘价下跌
        is_hanging_man = (upper_shadow > body * 2 and lower_shadow < body and latest['close'] < latest['open'])
        
        # 看跌吞没：当前K线阴线吞没前一根阳线
        is_bearish_engulfing = (prev['close'] > prev['open'] and 
                                latest['close'] < latest['open'] and
                                latest['close'] < prev['open'] and
                                latest['open'] > prev['close'])
        
        if is_hanging_man or is_bearish_engulfing:
            count += 1
            pattern = "上吊线" if is_hanging_man else "看跌吞没"
            logger.debug(f"✅ 做空条件3: K线反转信号 ({pattern})")
        
        # 条件4: 量价背离 - 价格新高但成交量未放大
        volume = latest['volume']
        volume_ma = latest['VOLUME_MA20']
        
        if close > prev['close'] and volume < volume_ma:
            count += 1
            logger.debug(f"✅ 做空条件4: 量价背离 (价格新高但量未放大)")
        
        return count
    
    def check_long_exit_conditions(self, df: pd.DataFrame, position: Dict) -> tuple[bool, str]:
        """检查平多条件
        
        平多条件（止盈）：
        - 价格上涨至阻力位（均线压力/前高点/布林上轨）
        - RSI > 70（超买区域）
        - MACD绿柱出现或红柱缩小
        - 浮盈达到100%以上
        
        平多条件（止损）：
        - 价格跌破支撑位
        - 浮亏达到50%
        - 出现明显空头K线形态
        """
        if len(df) < 2:
            return False, ""
        
        latest = df.iloc[-1]
        current_price = float(latest['close'])
        entry_price = float(position['entry_price'])
        quantity = float(position['quantity'])
        
        # 计算盈亏（100倍杠杆）
        pnl_pct = ((current_price - entry_price) / entry_price) * self.leverage
        
        # 止盈条件：浮盈 >= 100%
        if pnl_pct >= self.take_profit_pct:
            logger.info(f"🎯 平多信号（止盈）: 浮盈{pnl_pct*100:.2f}% >= 100%")
            return True, f"止盈(浮盈{pnl_pct*100:.1f}%)"
        
        # 止损条件：浮亏 <= -50%
        if pnl_pct <= -self.stop_loss_pct:
            logger.warning(f"🛑 平多信号（止损）: 浮亏{pnl_pct*100:.2f}% <= -50%")
            return True, f"止损(浮亏{pnl_pct*100:.1f}%)"
        
        # 【修复】技术指标止盈：需要有一定盈利才触发技术止盈
        rsi = latest['RSI']
        bb_upper = latest['BB_UPPER']
        
        # RSI超买 + 至少有10%盈利才平仓
        if rsi > self.rsi_take_profit_long and pnl_pct > 0.1:
            logger.info(f"🎯 平多信号（技术止盈）: RSI={rsi:.2f} > 70 且盈利{pnl_pct*100:.1f}%")
            return True, f"技术止盈(RSI={rsi:.1f})"
        
        # 价格突破布林上轨 + 至少有20%盈利才平仓
        if current_price >= bb_upper * 1.002 and pnl_pct > 0.2:
            logger.info(f"🎯 平多信号（技术止盈）: 价格突破布林上轨且盈利{pnl_pct*100:.1f}%")
            return True, "技术止盈(布林上轨)"
        
        # 【修复】MACD转绿 + 至少有15%盈利才平仓（避免频繁平仓）
        if latest['MACD_HIST'] < 0 and pnl_pct > 0.15:
            logger.info(f"🎯 平多信号（趋势反转）: MACD转绿且盈利{pnl_pct*100:.1f}%")
            return True, "趋势反转(MACD)"
        
        return False, ""
    
    def check_short_exit_conditions(self, df: pd.DataFrame, position: Dict) -> tuple[bool, str]:
        """检查平空条件
        
        平空条件（止盈）：
        - 价格下跌至支撑位（均线支撑/前低点/布林下轨）
        - RSI < 30（超卖区域）
        - MACD红柱出现或绿柱缩小
        - 浮盈达到100%以上
        
        平空条件（止损）：
        - 价格突破阻力位
        - 浮亏达到50%
        - 出现明显多头K线形态
        """
        if len(df) < 2:
            return False, ""
        
        latest = df.iloc[-1]
        current_price = float(latest['close'])
        entry_price = float(position['entry_price'])
        
        # 计算盈亏（做空，价格下跌盈利）
        pnl_pct = ((entry_price - current_price) / entry_price) * self.leverage
        
        # 止盈条件：浮盈 >= 100%
        if pnl_pct >= self.take_profit_pct:
            logger.info(f"🎯 平空信号（止盈）: 浮盈{pnl_pct*100:.2f}% >= 100%")
            return True, f"止盈(浮盈{pnl_pct*100:.1f}%)"
        
        # 止损条件：浮亏 <= -50%
        if pnl_pct <= -self.stop_loss_pct:
            logger.warning(f"🛑 平空信号（止损）: 浮亏{pnl_pct*100:.2f}% <= -50%")
            return True, f"止损(浮亏{pnl_pct*100:.1f}%)"
        
        # 【修复】技术指标止盈：需要有一定盈利才触发技术止盈
        rsi = latest['RSI']
        bb_lower = latest['BB_LOWER']
        
        # RSI超卖 + 至少有10%盈利才平仓
        if rsi < self.rsi_take_profit_short and pnl_pct > 0.1:
            logger.info(f"🎯 平空信号（技术止盈）: RSI={rsi:.2f} < 30 且盈利{pnl_pct*100:.1f}%")
            return True, f"技术止盈(RSI={rsi:.1f})"
        
        # 价格跌破布林下轨 + 至少有20%盈利才平仓
        if current_price <= bb_lower * 0.998 and pnl_pct > 0.2:
            logger.info(f"🎯 平空信号（技术止盈）: 价格跌破布林下轨且盈利{pnl_pct*100:.1f}%")
            return True, "技术止盈(布林下轨)"
        
        # 【修复】MACD转红 + 至少有15%盈利才平仓（避免频繁平仓）
        if latest['MACD_HIST'] > 0 and pnl_pct > 0.15:
            logger.info(f"🎯 平空信号（趋势反转）: MACD转红且盈利{pnl_pct*100:.1f}%")
            return True, "趋势反转(MACD)"
        
        return False, ""
    
    async def calculate_signal(self, market_data: Dict[str, pd.DataFrame]) -> List[Signal]:
        """生成交易信号"""
        signals = []
        
        for symbol, df in market_data.items():
            if len(df) < 50:
                logger.warning(f"⚠️ {symbol} K线数据不足（{len(df)}根），需要至少50根")
                continue
            
            # 计算技术指标
            df = self.calculate_technical_indicators(df)
            
            if df.empty or pd.isna(df.iloc[-1]['RSI']):
                logger.warning(f"⚠️ {symbol} 技术指标计算失败")
                continue
            
            latest = df.iloc[-1]
            current_price = float(latest['close'])
            
            # 【修复】回测引擎会自动处理持仓，策略只需生成信号
            # 所以移除持仓检查逻辑，直接生成开仓信号
            long_score = self.check_long_entry_conditions(df)
            short_score = self.check_short_entry_conditions(df)
            
            # 根据评分决定开仓方向和保证金
            margin = 0
            action = None
            
            if long_score >= 1 and long_score > short_score:
                action = 'buy'
                if long_score == 1:
                    margin = self.margin_level_1
                elif long_score == 2:
                    margin = self.margin_level_2
                else:  # >= 3
                    margin = self.margin_level_3
                
                logger.info(f"📊 {symbol} 做多信号强度: {long_score}个指标满足 → 保证金${margin:.0f}")
            
            elif short_score >= 1 and short_score > long_score:
                action = 'sell'
                if short_score == 1:
                    margin = self.margin_level_1
                elif short_score == 2:
                    margin = self.margin_level_2
                else:  # >= 3
                    margin = self.margin_level_3
                
                logger.info(f"📊 {symbol} 做空信号强度: {short_score}个指标满足 → 保证金${margin:.0f}")
            
            if action and margin > 0:
                # 计算开仓数量
                quantity = (margin * self.leverage) / current_price
                
                signals.append(Signal(
                    symbol=symbol,
                    action=action,
                    price=Decimal(str(current_price)),
                    quantity=Decimal(str(quantity)),
                    reason=f"综合信号(强度:{long_score if action == 'buy' else short_score}个指标,保证金${margin:.0f})"
                ))
                
                direction = "做多" if action == 'buy' else "做空"
                logger.info(f"✅ 生成{direction}信号: {symbol} @ {current_price:.2f}, "
                          f"数量: {quantity:.4f}, 保证金: ${margin:.0f}")
        
        return signals
    
    def should_exit_position(self, position: Position, current_data: pd.Series) -> bool:
        """判断是否需要平仓（继承自BaseStrategy的抽象方法）
        
        注意：这个方法是为了满足BaseStrategy的接口要求
        实际平仓逻辑已经在calculate_signal中实现
        """
        # 转换Position对象为dict格式（兼容处理）
        if isinstance(position, Position):
            pos_dict = {
                'symbol': position.symbol,
                'side': position.side,
                'quantity': position.quantity,
                'entry_price': position.entry_price,
                'current_price': position.current_price
            }
        else:
            pos_dict = position
        
        # 构造一个简单的DataFrame进行检查
        df = pd.DataFrame([current_data])
        
        if pos_dict['side'] == 'long':
            should_exit, _ = self.check_long_exit_conditions(df, pos_dict)
            return should_exit
        elif pos_dict['side'] == 'short':
            should_exit, _ = self.check_short_exit_conditions(df, pos_dict)
            return should_exit
        
        return False
