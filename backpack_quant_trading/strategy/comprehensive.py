"""
综合性策略 - 多指标评分系统（优化版）
优化目标：提高开仓频率，增加收益率，改进风险控制
"""

from decimal import Decimal
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np
from loguru import logger  # pyright: ignore[reportMissingImports]
from datetime import datetime, timedelta

from backpack_quant_trading.strategy.base import BaseStrategy, Signal, Position
from backpack_quant_trading.config.settings import TradingConfig


class ComprehensiveStrategyV2(BaseStrategy):
    """综合性策略 - 多指标评分开仓（优化版）"""
    
    def __init__(self, symbols: List[str], config: TradingConfig, params: Optional[Dict] = None):
        super().__init__(
            name="ComprehensiveStrategyV2",
            symbols=symbols,
            api_client=None,
            risk_manager=None
        )
        
        # 基础配置
        self.initial_capital = 500
        self.leverage = 100
        
        # 【优化】阶梯式保证金分配
        self.margin_levels = {
            2: 5.0,    # 2个指标：5U
            3: 8.0,    # 3个指标：8U
            4: 12.0,   # 4个指标：12U
            5: 15.0    # 5个以上指标：15U
        }
        
        # 【优化】动态止盈止损（基于ATR）
        self.atr_multiplier_tp = 3.0    # 止盈：3倍ATR
        self.atr_multiplier_sl = 1.5    # 止损：1.5倍ATR
        self.default_tp_pct = 0.5       # 止盈50%，更易达成提高胜率
        self.default_sl_pct = 0.4       # 止损40%，控制单笔亏损（盈亏比1.25:1）
        
        # 【优化】指标权重系统
        self.condition_weights = {
            'trend': 1.5,           # 趋势权重最高
            'price_position': 1.3,  # 价格位置
            'rsi_signal': 1.0,      # RSI信号
            'pattern': 0.8,         # K线形态
            'volume': 0.7,          # 成交量
            'kdj_signal': 0.6,      # KDJ
            'obv_signal': 0.5,      # OBV
            'ma_cross': 0.9,        # 均线交叉
            'macd_signal': 0.8      # MACD信号
        }
        
        # 技术指标阈值（适度放宽以获取更多有效信号）
        self.rsi_oversold = 35      # 做多：RSI<35 超卖
        self.rsi_overbought = 65    # 做空：RSI>65 超买
        self.rsi_take_profit_long = 68   # 平多：RSI>68 技术止盈（适度提前锁定利润）
        self.rsi_take_profit_short = 32  # 平空：RSI<32 技术止盈
        
        # 【优化】仓位管理参数
        self.max_position_ratio = 0.25    # 单品种最大仓位25%
        self.total_margin_ratio = 0.75    # 总保证金不超过75%
        self.min_score_to_open = 4.0      # 至少4个指标，减少假信号
        self.min_weighted_score = 5.0     # 加权评分>=5才开仓
        
        # 【优化】趋势过滤
        self.use_trend_filter = True      # 启用趋势过滤
        self.trend_period = 30           # 趋势判断周期
        self.only_trend_following = True  # 【优化】只做顺势交易，提高胜率
        
        # 【新增】波动率过滤：避免在横盘震荡中频繁开仓
        self.min_bb_width = 0.02         # 布林带宽度最小值（2%），低于此不开仓
        
        # 【新增】强趋势过滤：做多时价格需在MA50上方，做空时在MA50下方
        self.require_ma50_filter = True
        
        # 如果传入了params，覆盖默认值
        if params:
            for key, value in params.items():
                if hasattr(self, key):
                    setattr(self, key, value)
        
        logger.info(f"策略初始化完成 - 初始资金: ${self.initial_capital}, 杠杆: {self.leverage}x")
        logger.info(f"保证金级别: {self.margin_levels}")
        logger.info(f"开仓最低评分: {self.min_score_to_open}")
    
    def calculate_technical_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算技术指标（优化版）"""
        if len(df) < 60:
            return df
        
        # 1. 移动平均线（增加多周期）
        df['MA5'] = df['close'].rolling(window=5).mean()
        df['MA10'] = df['close'].rolling(window=10).mean()
        df['MA20'] = df['close'].rolling(window=20).mean()
        df['MA50'] = df['close'].rolling(window=50).mean()
        df['MA100'] = df['close'].rolling(window=100).mean()
        
        # 2. 布林带（增加宽度指标）
        df['BB_MIDDLE'] = df['close'].rolling(window=20).mean()
        bb_std = df['close'].rolling(window=20).std()
        df['BB_UPPER'] = df['BB_MIDDLE'] + 2 * bb_std
        df['BB_LOWER'] = df['BB_MIDDLE'] - 2 * bb_std
        df['BB_WIDTH'] = (df['BB_UPPER'] - df['BB_LOWER']) / df['BB_MIDDLE']  # 布林带宽度%
        
        # 3. RSI（多周期）
        for period in [7, 14, 21]:
            delta = df['close'].diff()
            gain = delta.where(delta > 0, 0.0)
            loss = (-delta).where(delta < 0, 0.0)
            avg_gain = gain.rolling(window=period).mean()
            avg_loss = loss.rolling(window=period).mean()
            rs = np.where(avg_loss > 0, avg_gain / avg_loss, 10.0)
            df[f'RSI_{period}'] = 100 - (100 / (1 + rs))
        
        # 主要使用RSI_14
        df['RSI'] = df['RSI_14']
        
        # 4. MACD（多参数）
        ema12 = df['close'].ewm(span=12, adjust=False).mean()
        ema26 = df['close'].ewm(span=26, adjust=False).mean()
        df['MACD'] = ema12 - ema26
        df['MACD_SIGNAL'] = df['MACD'].ewm(span=9, adjust=False).mean()
        df['MACD_HIST'] = df['MACD'] - df['MACD_SIGNAL']
        
        # 5. 成交量指标（多维度）
        df['VOLUME_MA5'] = df['volume'].rolling(window=5).mean()
        df['VOLUME_MA20'] = df['volume'].rolling(window=20).mean()
        df['VOLUME_RATIO'] = df['volume'] / df['VOLUME_MA20']  # 成交量比率
        
        # 6. KDJ（优化计算）
        low_9 = df['low'].rolling(9).min()
        high_9 = df['high'].rolling(9).max()
        rsv = np.where(high_9 > low_9, (df['close'] - low_9) / (high_9 - low_9) * 100, 50)
        df['KDJ_K'] = pd.Series(rsv, index=df.index).ewm(com=2, adjust=False).mean()
        df['KDJ_D'] = df['KDJ_K'].ewm(com=2, adjust=False).mean()
        df['KDJ_J'] = 3 * df['KDJ_K'] - 2 * df['KDJ_D']
        
        # 7. ATR（多周期）
        for period in [7, 14, 21]:
            tr1 = df['high'] - df['low']
            tr2 = abs(df['high'] - df['close'].shift(1))
            tr3 = abs(df['low'] - df['close'].shift(1))
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            df[f'ATR_{period}'] = tr.rolling(period).mean()
        
        df['ATR'] = df['ATR_14']  # 主要使用14周期ATR
        df['ATR_PCT'] = df['ATR'] / df['close']  # ATR百分比
        
        # 8. OBV（带均线）
        df['OBV'] = (np.sign(df['close'].diff()) * df['volume']).fillna(0).cumsum()
        df['OBV_MA5'] = df['OBV'].rolling(5).mean()
        df['OBV_MA20'] = df['OBV'].rolling(20).mean()
        
        # 9. 动量指标
        df['MOMENTUM_5'] = df['close'].pct_change(5)
        df['MOMENTUM_10'] = df['close'].pct_change(10)
        
        # 10. 支撑阻力标记
        df['RESISTANCE'] = df['high'].rolling(20).max()
        df['SUPPORT'] = df['low'].rolling(20).min()
        
        return df
    
    def check_trend_direction(self, df: pd.DataFrame) -> str:
        """判断当前趋势方向"""
        if len(df) < self.trend_period:
            return 'neutral'
        
        latest = df.iloc[-1]
        
        # 多重趋势判断
        trend_scores = []
        
        # 1. 均线排列（权重最高）
        if all(pd.notna(latest.get(ma)) for ma in ['MA5', 'MA20', 'MA50']):
            ma5, ma20, ma50 = latest['MA5'], latest['MA20'], latest['MA50']
            if ma5 > ma20 > ma50:
                trend_scores.append(('uptrend', 2.0))
            elif ma5 < ma20 < ma50:
                trend_scores.append(('downtrend', 2.0))
            elif ma5 > ma20 and ma20 > latest['close']:
                trend_scores.append(('downtrend', 1.0))
            elif ma5 < ma20 and ma20 < latest['close']:
                trend_scores.append(('uptrend', 1.0))
        
        # 2. 价格相对位置
        if pd.notna(latest.get('BB_MIDDLE')):
            price = latest['close']
            bb_middle = latest['BB_MIDDLE']
            if price > bb_middle * 1.03:
                trend_scores.append(('uptrend', 1.5))
            elif price < bb_middle * 0.97:
                trend_scores.append(('downtrend', 1.5))
            elif price > bb_middle:
                trend_scores.append(('uptrend', 0.5))
            else:
                trend_scores.append(('downtrend', 0.5))
        
        # 3. 动量方向
        if pd.notna(latest.get('MOMENTUM_10')):
            if latest['MOMENTUM_10'] > 0.02:
                trend_scores.append(('uptrend', 1.0))
            elif latest['MOMENTUM_10'] < -0.02:
                trend_scores.append(('downtrend', 1.0))
        
        # 汇总趋势得分
        if trend_scores:
            uptrend_score = sum(score for trend, score in trend_scores if trend == 'uptrend')
            downtrend_score = sum(score for trend, score in trend_scores if trend == 'downtrend')
            
            if uptrend_score > downtrend_score + 0.5:
                return 'uptrend'
            elif downtrend_score > uptrend_score + 0.5:
                return 'downtrend'
        
        return 'neutral'
    
    def calculate_long_entry_score(self, df: pd.DataFrame) -> Dict:
        """计算做多开仓综合评分"""
        if len(df) < 50:
            return {'score': 0, 'weighted_score': 0, 'details': {}}
        
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        score_details = {}
        weighted_score = 0
        
        # 【优化】趋势过滤检查
        if self.use_trend_filter:
            trend = self.check_trend_direction(df)
            if self.only_trend_following:
                if trend == 'downtrend':
                    logger.debug(f"⚠️ 趋势过滤：当前为下降趋势，不做多")
                    return {'score': 0, 'weighted_score': 0, 'details': {}}
                if trend == 'neutral':
                    return {'score': 0, 'weighted_score': 0, 'details': {}}  # 震荡市不做多
                # trend == 'uptrend' 顺势做多
                score_details['trend_aligned'] = 1
                weighted_score += 1.0 * self.condition_weights['trend']
            elif trend == 'uptrend':
                score_details['trend_aligned'] = 1
                weighted_score += 1.0 * self.condition_weights['trend']
        # 【强趋势】做多时价格需在MA50上方
        if getattr(self, 'require_ma50_filter', False) and pd.notna(latest.get('MA50')):
            if latest['close'] < latest['MA50'] * 0.998:
                return {'score': 0, 'weighted_score': 0, 'details': {}}
        
        # 1. 价格支撑位（优化判断条件）
        price_score = self.calculate_price_support_score(latest, 'long')
        if price_score > 0:
            score_details['price_support'] = price_score
            weighted_score += price_score * self.condition_weights['price_position']
        
        # 2. RSI超卖（多条件判断，含反转确认）
        rsi_score = self.calculate_rsi_score(latest, 'long', prev)
        if rsi_score > 0:
            score_details['rsi_oversold'] = rsi_score
            weighted_score += rsi_score * self.condition_weights['rsi_signal']
        
        # 3. K线反转形态（优化识别）
        pattern_score = self.calculate_kline_pattern_score(latest, prev, 'long')
        if pattern_score > 0:
            score_details['kline_pattern'] = pattern_score
            weighted_score += pattern_score * self.condition_weights['pattern']
        
        # 4. 成交量确认（多维度）
        volume_score = self.calculate_volume_score(latest, prev, 'long')
        if volume_score > 0:
            score_details['volume_confirmation'] = volume_score
            weighted_score += volume_score * self.condition_weights['volume']
        
        # 5. KDJ超卖
        kdj_score = self.calculate_kdj_score(latest, 'long')
        if kdj_score > 0:
            score_details['kdj_oversold'] = kdj_score
            weighted_score += kdj_score * self.condition_weights['kdj_signal']
        
        # 6. OBV支撑
        obv_score = self.calculate_obv_score(latest, prev, 'long')
        if obv_score > 0:
            score_details['obv_support'] = obv_score
            weighted_score += obv_score * self.condition_weights['obv_signal']
        
        # 7. 均线金叉
        ma_cross_score = self.calculate_ma_cross_score(df, 'long')
        if ma_cross_score > 0:
            score_details['ma_cross'] = ma_cross_score
            weighted_score += ma_cross_score * self.condition_weights['ma_cross']
        
        # 8. MACD背离/金叉
        macd_score = self.calculate_macd_score(df, 'long')
        if macd_score > 0:
            score_details['macd_signal'] = macd_score
            weighted_score += macd_score * self.condition_weights['macd_signal']
        
        # 9. 多指标共振（加分项）
        resonance_score = self.check_indicator_resonance(df, 'long')
        if resonance_score > 0:
            score_details['resonance'] = resonance_score
            weighted_score += resonance_score * 1.2  # 共振额外权重
        
        return {
            'score': len(score_details),
            'weighted_score': weighted_score,
            'details': score_details
        }
    
    def calculate_short_entry_score(self, df: pd.DataFrame) -> Dict:
        """计算做空开仓综合评分"""
        if len(df) < 50:
            return {'score': 0, 'weighted_score': 0, 'details': {}}
        
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        score_details = {}
        weighted_score = 0
        
        # 【优化】趋势过滤检查
        if self.use_trend_filter:
            trend = self.check_trend_direction(df)
            if self.only_trend_following:
                if trend == 'uptrend':
                    logger.debug(f"⚠️ 趋势过滤：当前为上升趋势，不做空")
                    return {'score': 0, 'weighted_score': 0, 'details': {}}
                if trend == 'neutral':
                    return {'score': 0, 'weighted_score': 0, 'details': {}}  # 震荡市不做空
                # trend == 'downtrend' 顺势做空
                score_details['trend_aligned'] = 1
                weighted_score += 1.0 * self.condition_weights['trend']
            elif trend == 'downtrend':
                score_details['trend_aligned'] = 1
                weighted_score += 1.0 * self.condition_weights['trend']
        
        # 【强趋势】做空时价格需在MA50下方
        if getattr(self, 'require_ma50_filter', False) and pd.notna(latest.get('MA50')):
            if latest['close'] > latest['MA50'] * 1.002:
                return {'score': 0, 'weighted_score': 0, 'details': {}}
        
        # 1. 价格阻力位
        price_score = self.calculate_price_resistance_score(latest, 'short')
        if price_score > 0:
            score_details['price_resistance'] = price_score
            weighted_score += price_score * self.condition_weights['price_position']
        
        # 2. RSI超买（含反转确认）
        rsi_score = self.calculate_rsi_score(latest, 'short', prev)
        if rsi_score > 0:
            score_details['rsi_overbought'] = rsi_score
            weighted_score += rsi_score * self.condition_weights['rsi_signal']
        
        # 3. K线反转形态
        pattern_score = self.calculate_kline_pattern_score(latest, prev, 'short')
        if pattern_score > 0:
            score_details['kline_pattern'] = pattern_score
            weighted_score += pattern_score * self.condition_weights['pattern']
        
        # 4. 成交量背离
        volume_score = self.calculate_volume_score(latest, prev, 'short')
        if volume_score > 0:
            score_details['volume_divergence'] = volume_score
            weighted_score += volume_score * self.condition_weights['volume']
        
        # 5. KDJ超买
        kdj_score = self.calculate_kdj_score(latest, 'short')
        if kdj_score > 0:
            score_details['kdj_overbought'] = kdj_score
            weighted_score += kdj_score * self.condition_weights['kdj_signal']
        
        # 6. OBV背离
        obv_score = self.calculate_obv_score(latest, prev, 'short')
        if obv_score > 0:
            score_details['obv_divergence'] = obv_score
            weighted_score += obv_score * self.condition_weights['obv_signal']
        
        # 7. 均线死叉
        ma_cross_score = self.calculate_ma_cross_score(df, 'short')
        if ma_cross_score > 0:
            score_details['ma_cross'] = ma_cross_score
            weighted_score += ma_cross_score * self.condition_weights['ma_cross']
        
        # 8. MACD死叉/背离
        macd_score = self.calculate_macd_score(df, 'short')
        if macd_score > 0:
            score_details['macd_signal'] = macd_score
            weighted_score += macd_score * self.condition_weights['macd_signal']
        
        # 9. 多指标共振
        resonance_score = self.check_indicator_resonance(df, 'short')
        if resonance_score > 0:
            score_details['resonance'] = resonance_score
            weighted_score += resonance_score * 1.2
        
        return {
            'score': len(score_details),
            'weighted_score': weighted_score,
            'details': score_details
        }
    
    def calculate_price_support_score(self, latest: pd.Series, side: str) -> float:
        """计算价格支撑位得分"""
        close = latest['close']
        
        # 多重支撑判断
        scores = []
        
        # 1. 布林带下轨支撑
        if pd.notna(latest.get('BB_LOWER')):
            bb_lower = latest['BB_LOWER']
            bb_width = latest.get('BB_WIDTH', 0.05)
            
            # 【优化】放宽支撑判断条件
            if close <= bb_lower * (1 + bb_width * 0.3):  # 下轨附近30%宽度区域
                distance_pct = (close - bb_lower) / bb_lower if bb_lower > 0 else 0
                score = max(0.3, 1.0 - abs(distance_pct) * 5)
                scores.append(score)
        
        # 2. 移动平均线支撑
        for ma_key in ['MA20', 'MA50', 'MA100']:
            if pd.notna(latest.get(ma_key)):
                ma_value = latest[ma_key]
                if abs(close - ma_value) / ma_value < 0.01:  # 价格在均线1%以内
                    scores.append(0.7)
                elif abs(close - ma_value) / ma_value < 0.02:  # 价格在均线2%以内
                    scores.append(0.5)
        
        # 3. 前低支撑
        if pd.notna(latest.get('SUPPORT')):
            support = latest['SUPPORT']
            if abs(close - support) / support < 0.015:  # 价格在前低1.5%以内
                scores.append(0.8)
        
        return max(scores) if scores else 0
    
    def calculate_price_resistance_score(self, latest: pd.Series, side: str) -> float:
        """计算价格阻力位得分"""
        close = latest['close']
        scores = []
        
        # 1. 布林带上轨阻力
        if pd.notna(latest.get('BB_UPPER')):
            bb_upper = latest['BB_UPPER']
            bb_width = latest.get('BB_WIDTH', 0.05)
            
            if close >= bb_upper * (1 - bb_width * 0.3):  # 上轨附近30%宽度区域
                distance_pct = (bb_upper - close) / bb_upper if bb_upper > 0 else 0
                score = max(0.3, 1.0 - abs(distance_pct) * 5)
                scores.append(score)
        
        # 2. 移动平均线阻力
        for ma_key in ['MA20', 'MA50', 'MA100']:
            if pd.notna(latest.get(ma_key)):
                ma_value = latest[ma_key]
                if abs(close - ma_value) / ma_value < 0.01:
                    scores.append(0.7)
                elif abs(close - ma_value) / ma_value < 0.02:
                    scores.append(0.5)
        
        # 3. 前高阻力
        if pd.notna(latest.get('RESISTANCE')):
            resistance = latest['RESISTANCE']
            if abs(close - resistance) / resistance < 0.015:
                scores.append(0.8)
        
        return max(scores) if scores else 0
    
    def calculate_rsi_score(self, latest: pd.Series, side: str, prev: Optional[pd.Series] = None) -> float:
        """计算RSI信号得分（含反转确认加分）"""
        if side == 'long':
            # 做多：检查多周期RSI超卖
            rsi_scores = []
            for period in [7, 14, 21]:
                rsi_key = f'RSI_{period}'
                if pd.notna(latest.get(rsi_key)):
                    rsi = latest[rsi_key]
                    if rsi < self.rsi_oversold:
                        score = min(1.0, (self.rsi_oversold - rsi) / 20)
                        rsi_scores.append(score)
            
            base = max(rsi_scores) * 1.2 if len(rsi_scores) >= 2 else (max(rsi_scores) if rsi_scores else 0)
            # 【优化】RSI开始回升时加分（反转确认）
            if base > 0 and prev is not None and pd.notna(latest.get('RSI')) and pd.notna(prev.get('RSI')):
                if latest['RSI'] > prev['RSI']:
                    base = min(1.0, base * 1.2)
            return base
        
        else:  # short
            rsi_scores = []
            for period in [7, 14, 21]:
                rsi_key = f'RSI_{period}'
                if pd.notna(latest.get(rsi_key)):
                    rsi = latest[rsi_key]
                    if rsi > self.rsi_overbought:
                        score = min(1.0, (rsi - self.rsi_overbought) / 20)
                        rsi_scores.append(score)
            
            base = max(rsi_scores) * 1.2 if len(rsi_scores) >= 2 else (max(rsi_scores) if rsi_scores else 0)
            if base > 0 and prev is not None and pd.notna(latest.get('RSI')) and pd.notna(prev.get('RSI')):
                if latest['RSI'] < prev['RSI']:  # RSI从超买回落
                    base = min(1.0, base * 1.2)
            return base
        
        return 0
    
    def calculate_kline_pattern_score(self, latest: pd.Series, prev: pd.Series, side: str) -> float:
        """计算K线形态得分"""
        open_price, close, high, low = latest['open'], latest['close'], latest['high'], latest['low']
        prev_open, prev_close = prev['open'], prev['close']
        
        body = abs(close - open_price)
        high_low_range = high - low
        
        if body == 0 or high_low_range == 0:
            return 0
        
        body_ratio = body / high_low_range
        upper_shadow = high - max(open_price, close)
        lower_shadow = min(open_price, close) - low
        
        if side == 'long':
            # 锤子线
            if (lower_shadow > body * 1.5 and upper_shadow < body * 0.5 and 
                close > open_price and body_ratio < 0.3):
                return 0.9
            
            # 看涨吞没
            if (prev_close < prev_open and close > open_price and
                close > prev_open and open_price < prev_close):
                return 0.8
            
            # 启明星（简化版）
            if body_ratio < 0.3 and close > open_price and lower_shadow > body:
                return 0.6
        
        else:  # short
            # 上吊线
            if (upper_shadow > body * 1.5 and lower_shadow < body * 0.5 and
                close < open_price and body_ratio < 0.3):
                return 0.9
            
            # 看跌吞没
            if (prev_close > prev_open and close < open_price and
                close < prev_open and open_price > prev_close):
                return 0.8
            
            # 黄昏星（简化版）
            if body_ratio < 0.3 and close < open_price and upper_shadow > body:
                return 0.6
        
        return 0
    
    def calculate_volume_score(self, latest: pd.Series, prev: pd.Series, side: str) -> float:
        """计算成交量信号得分"""
        volume = latest.get('volume', 0)
        volume_ma20 = latest.get('VOLUME_MA20', 1)
        volume_ratio = latest.get('VOLUME_RATIO', 1)
        
        if volume_ma20 == 0:
            return 0
        
        if side == 'long':
            # 做多：缩量回调或放量突破
            price_change = (latest['close'] - prev['close']) / prev['close']
            
            # 缩量回调到支撑位
            if price_change < -0.005 and volume_ratio < 0.8:
                return 0.7
            
            # 放量上涨
            if price_change > 0.01 and volume_ratio > 1.2:
                return 0.8
        
        else:  # short
            # 做空：放量滞涨或缩量反弹
            price_change = (latest['close'] - prev['close']) / prev['close']
            
            # 放量滞涨（价格上涨但涨幅小）
            if 0 < price_change < 0.005 and volume_ratio > 1.3:
                return 0.7
            
            # 缩量反弹
            if price_change > 0.005 and volume_ratio < 0.7:
                return 0.6
        
        return 0
    
    def calculate_kdj_score(self, latest: pd.Series, side: str) -> float:
        """计算KDJ信号得分"""
        k = latest.get('KDJ_K', 50)
        d = latest.get('KDJ_D', 50)
        j = latest.get('KDJ_J', 50)
        
        if side == 'long':
            # KDJ超卖
            if j < 20 or (k < 25 and d < 30):
                # 计算超卖程度
                if j < 10:
                    return 0.9
                elif j < 20:
                    return 0.7
                else:
                    return 0.5
            
            # KDJ金叉（K上穿D）
            if pd.notna(latest.get('KDJ_K')) and pd.notna(latest.get('KDJ_D')):
                # 需要历史数据判断金叉，这里简化处理
                if k > d and k < 40:
                    return 0.6
        
        else:  # short
            # KDJ超买
            if j > 80 or (k > 75 and d > 70):
                if j > 90:
                    return 0.9
                elif j > 80:
                    return 0.7
                else:
                    return 0.5
            
            # KDJ死叉（K下穿D）
            if k < d and k > 60:
                return 0.6
        
        return 0
    
    def calculate_obv_score(self, latest: pd.Series, prev: pd.Series, side: str) -> float:
        """计算OBV信号得分"""
        obv = latest.get('OBV', 0)
        obv_ma20 = latest.get('OBV_MA20', 0)
        obv_prev = prev.get('OBV', 0)
        
        if obv_ma20 == 0:
            return 0
        
        obv_ratio = obv / obv_ma20 if obv_ma20 != 0 else 1
        
        if side == 'long':
            # OBV在均线上方且上升
            if obv_ratio > 1.02 and obv > obv_prev:
                return 0.7
            
            # OBV底背离（价格新低但OBV未新低）
            if latest['close'] < prev['close'] and obv > obv_prev:
                return 0.6
        
        else:  # short
            # OBV在均线下方且下降
            if obv_ratio < 0.98 and obv < obv_prev:
                return 0.7
            
            # OBV顶背离（价格新高但OBV未新高）
            if latest['close'] > prev['close'] and obv < obv_prev:
                return 0.6
        
        return 0
    
    def calculate_ma_cross_score(self, df: pd.DataFrame, side: str) -> float:
        """计算均线交叉得分"""
        if len(df) < 10:
            return 0
        
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        # 检查短期均线交叉
        ma5_now = latest.get('MA5', 0)
        ma10_now = latest.get('MA10', 0)
        ma5_prev = prev.get('MA5', 0)
        ma10_prev = prev.get('MA10', 0)
        
        if ma5_now == 0 or ma10_now == 0 or ma5_prev == 0 or ma10_prev == 0:
            return 0
        
        if side == 'long':
            # 金叉：MA5上穿MA10
            if ma5_prev <= ma10_prev and ma5_now > ma10_now:
                return 0.8
            
            # 多头排列
            ma20 = latest.get('MA20', 0)
            if ma5_now > ma10_now > ma20:
                return 0.6
        
        else:  # short
            # 死叉：MA5下穿MA10
            if ma5_prev >= ma10_prev and ma5_now < ma10_now:
                return 0.8
            
            # 空头排列
            ma20 = latest.get('MA20', 0)
            if ma5_now < ma10_now < ma20:
                return 0.6
        
        return 0
    
    def calculate_macd_score(self, df: pd.DataFrame, side: str) -> float:
        """计算MACD信号得分"""
        if len(df) < 30:
            return 0
        
        latest = df.iloc[-1]
        macd_hist = latest.get('MACD_HIST', 0)
        
        # 需要更多历史数据判断趋势
        hist_values = df['MACD_HIST'].tail(5).values
        
        if side == 'long':
            # MACD柱状线由负转正
            if len(hist_values) >= 3:
                if hist_values[-3] < 0 and hist_values[-2] < 0 and macd_hist > 0:
                    return 0.8
            
            # MACD底背离检测（简化版）
            # 实际需要更复杂的逻辑
            
        else:  # short
            # MACD柱状线由正转负
            if len(hist_values) >= 3:
                if hist_values[-3] > 0 and hist_values[-2] > 0 and macd_hist < 0:
                    return 0.8
        
        return 0
    
    def check_indicator_resonance(self, df: pd.DataFrame, side: str) -> float:
        """检查多指标共振：至少2个核心指标同向确认才加分"""
        if len(df) < 50:
            return 0
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        resonance_count = 0
        
        if side == 'long':
            # 均线支撑
            if pd.notna(latest.get('MA5')) and latest['MA5'] > latest.get('MA20', 0):
                resonance_count += 1
            # RSI超卖且开始回升（反转确认）
            rsi = latest.get('RSI')
            rsi_prev = prev.get('RSI')
            if pd.notna(rsi) and pd.notna(rsi_prev) and rsi < 45 and rsi > rsi_prev:
                resonance_count += 1
            # MACD柱状线由负转正或增强
            if len(df) >= 3 and 'MACD_HIST' in df.columns:
                hist_now = latest.get('MACD_HIST', 0)
                hist_prev = df['MACD_HIST'].iloc[-3]
                if pd.notna(hist_now) and hist_now > hist_prev:
                    resonance_count += 1
            # KDJ超卖且J值回升
            j_now = latest.get('KDJ_J')
            j_prev = prev.get('KDJ_J')
            if pd.notna(j_now) and pd.notna(j_prev) and j_now < 40 and j_now > j_prev:
                resonance_count += 1
        else:  # short
            if pd.notna(latest.get('MA5')) and latest['MA5'] < latest.get('MA20', 0):
                resonance_count += 1
            rsi = latest.get('RSI')
            rsi_prev = prev.get('RSI')
            if pd.notna(rsi) and pd.notna(rsi_prev) and rsi > 55 and rsi < rsi_prev:
                resonance_count += 1
            if len(df) >= 3 and 'MACD_HIST' in df.columns:
                hist_now = latest.get('MACD_HIST', 0)
                hist_prev = df['MACD_HIST'].iloc[-3]
                if pd.notna(hist_now) and hist_now < hist_prev:
                    resonance_count += 1
            j_now = latest.get('KDJ_J')
            j_prev = prev.get('KDJ_J')
            if pd.notna(j_now) and pd.notna(j_prev) and j_now > 60 and j_now < j_prev:
                resonance_count += 1
        
        if resonance_count >= 3:
            return 0.5
        elif resonance_count >= 2:
            return 0.3
        return 0
    
    def calculate_dynamic_tp_sl(self, df: pd.DataFrame, entry_price: float, side: str) -> Tuple[float, float]:
        """基于ATR计算动态止盈止损"""
        if len(df) < 15:
            # 使用默认百分比
            if side == 'long':
                return entry_price * (1 + self.default_tp_pct / 100), \
                       entry_price * (1 - self.default_sl_pct / 100)
            else:
                return entry_price * (1 - self.default_tp_pct / 100), \
                       entry_price * (1 + self.default_sl_pct / 100)
        
        latest = df.iloc[-1]
        atr = latest.get('ATR', entry_price * 0.005)
        
        # 基于波动率调整倍数
        atr_pct = latest.get('ATR_PCT', 0.005)
        if atr_pct > 0.02:  # 高波动
            tp_multiplier = 2.5
            sl_multiplier = 1.2
        elif atr_pct < 0.01:  # 低波动
            tp_multiplier = 3.5
            sl_multiplier = 1.8
        else:  # 正常波动
            tp_multiplier = self.atr_multiplier_tp
            sl_multiplier = self.atr_multiplier_sl
        
        if side == 'long':
            take_profit = entry_price + atr * tp_multiplier
            stop_loss = entry_price - atr * sl_multiplier
        else:
            take_profit = entry_price - atr * tp_multiplier
            stop_loss = entry_price + atr * sl_multiplier
        
        # 确保最小盈利空间
        min_profit_ratio = 0.015  # 1.5%
        if side == 'long' and (take_profit - entry_price) / entry_price < min_profit_ratio:
            take_profit = entry_price * (1 + min_profit_ratio)
        elif side == 'short' and (entry_price - take_profit) / entry_price < min_profit_ratio:
            take_profit = entry_price * (1 - min_profit_ratio)
        
        return take_profit, stop_loss
    
    def calculate_position_size(self, df: pd.DataFrame, score_result: Dict, 
                              available_capital: float, side: str) -> float:
        """根据评分计算仓位大小"""
        weighted_score = score_result['weighted_score']
        condition_count = score_result['score']
        
        # 基础仓位比例（基于评分）
        base_ratio = min(0.25, weighted_score / 10)  # 最高25%仓位
        
        # 波动率调整（高波动降低仓位）
        atr_pct = df.iloc[-1].get('ATR_PCT', 0.005)
        volatility_factor = 1.0
        if atr_pct > 0.02:
            volatility_factor = 0.7
        elif atr_pct > 0.03:
            volatility_factor = 0.5
        
        # 计算保证金
        margin = available_capital * base_ratio * volatility_factor
        
        # 根据指标数量调整到阶梯保证金
        if condition_count in self.margin_levels:
            margin = min(margin, self.margin_levels[condition_count])
        else:
            margin = min(margin, max(self.margin_levels.values()))
        
        # 确保最小保证金
        min_margin = min(self.margin_levels.values())
        margin = max(margin, min_margin)
        
        # 确保不超过单品种最大仓位
        max_margin = self.initial_capital * self.max_position_ratio
        margin = min(margin, max_margin)
        
        return margin
    
    def get_stop_take_profit_prices(self, entry_price: float, side: str) -> Tuple[float, float]:
        """返回止盈止损价格（用于回测引擎K线内模拟）
        tp_pct/sl_pct 为保证金收益率，100x杠杆下 1%价格变动=100%保证金收益
        """
        price_move_sl = self.default_sl_pct / 100  # 0.5 -> 0.005 (0.5%价格变动=50%保证金亏损)
        price_move_tp = self.default_tp_pct / 100   # 0.6 -> 0.006
        if side == 'long':
            sl_price = entry_price * (1 - price_move_sl)
            tp_price = entry_price * (1 + price_move_tp)
        else:
            sl_price = entry_price * (1 + price_move_sl)
            tp_price = entry_price * (1 - price_move_tp)
        return tp_price, sl_price
    
    def check_long_exit_conditions(self, df: pd.DataFrame, position: Dict) -> Tuple[bool, str]:
        """检查平多条件"""
        if len(df) < 2:
            return False, ""
        
        latest = df.iloc[-1]
        current_price = float(latest['close'])
        entry_price = float(position['entry_price'])
        
        # 计算盈亏（考虑杠杆）
        pnl_pct = ((current_price - entry_price) / entry_price) * self.leverage
        
        # 1. 固定止盈止损
        if pnl_pct >= self.default_tp_pct:
            return True, f"固定止盈({pnl_pct*100:.1f}%)"
        
        if pnl_pct <= -self.default_sl_pct:
            return True, f"固定止损({pnl_pct*100:.1f}%)"
        
        # 2. 技术指标止盈（需有盈利才触发，避免浮亏时误平）
        rsi = latest.get('RSI', 50)
        if rsi > self.rsi_take_profit_long and pnl_pct > 0.1:
            return True, f"RSI止盈({rsi:.1f})"
        
        # 3. 价格触及阻力位（需有盈利）
        bb_upper = latest.get('BB_UPPER', current_price * 1.05)
        if current_price >= bb_upper * 0.998 and pnl_pct > 0.1:
            return True, "触及布林上轨"
        
        # 4. MACD转弱（需有盈利）
        macd_hist = latest.get('MACD_HIST', 0)
        if macd_hist < 0 and pnl_pct > 0.25:
            return True, "MACD转弱"
        
        # 5. 趋势反转（需有盈利）
        trend = self.check_trend_direction(df)
        if trend == 'downtrend' and pnl_pct > 0.15:
            return True, "趋势反转"
        
        return False, ""
    
    def check_short_exit_conditions(self, df: pd.DataFrame, position: Dict) -> Tuple[bool, str]:
        """检查平空条件"""
        if len(df) < 2:
            return False, ""
        
        latest = df.iloc[-1]
        current_price = float(latest['close'])
        entry_price = float(position['entry_price'])
        
        # 计算盈亏（做空）
        pnl_pct = ((entry_price - current_price) / entry_price) * self.leverage
        
        # 1. 固定止盈止损
        if pnl_pct >= self.default_tp_pct:
            return True, f"固定止盈({pnl_pct*100:.1f}%)"
        
        if pnl_pct <= -self.default_sl_pct:
            return True, f"固定止损({pnl_pct*100:.1f}%)"
        
        # 2. 技术指标止盈（需有盈利才触发）
        rsi = latest.get('RSI', 50)
        if rsi < self.rsi_take_profit_short and pnl_pct > 0.1:
            return True, f"RSI止盈({rsi:.1f})"
        
        # 3. 价格触及支撑位（需有盈利）
        bb_lower = latest.get('BB_LOWER', current_price * 0.95)
        if current_price <= bb_lower * 1.002 and pnl_pct > 0.1:
            return True, "触及布林下轨"
        
        # 4. MACD转强（需有盈利）
        macd_hist = latest.get('MACD_HIST', 0)
        if macd_hist > 0 and pnl_pct > 0.25:
            return True, "MACD转强"
        
        # 5. 趋势反转（需有盈利）
        trend = self.check_trend_direction(df)
        if trend == 'uptrend' and pnl_pct > 0.15:
            return True, "趋势反转"
        
        return False, ""
    
    async def calculate_signal(self, market_data: Dict[str, pd.DataFrame]) -> List[Signal]:
        """生成交易信号（主逻辑）
        注意：平仓由回测引擎根据 check_long_exit_conditions/check_short_exit_conditions 处理，
        本方法仅生成开仓信号。
        """
        signals = []
        available_margin = self.initial_capital * self.total_margin_ratio
        
        for symbol, df in market_data.items():
            if len(df) < 50:
                continue
            
            # 计算技术指标
            df = self.calculate_technical_indicators(df)
            
            if df.empty or pd.isna(df.iloc[-1].get('RSI', 50)):
                continue
            
            current_price = float(df.iloc[-1]['close'])
            
            # 检查是否有足够保证金开新仓
            if available_margin < min(self.margin_levels.values()):
                logger.debug(f"💰 可用保证金不足: ${available_margin:.2f}")
                continue
            
            # 【新增】波动率过滤：横盘震荡时不开仓
            bb_width = df.iloc[-1].get('BB_WIDTH', 0.05)
            if pd.notna(bb_width) and bb_width < getattr(self, 'min_bb_width', 0.02):
                logger.debug(f"⚠️ 波动率过滤：布林带宽度{bb_width:.4f}过低，跳过")
                continue
            
            # 计算开仓评分
            long_result = self.calculate_long_entry_score(df)
            short_result = self.calculate_short_entry_score(df)
            
            # 选择最佳开仓方向（同时满足指标数量和加权评分）
            min_ws = getattr(self, 'min_weighted_score', 3.5)
            action = None
            score_result = None
            side = None
            
            if (long_result['score'] >= self.min_score_to_open and 
                long_result['weighted_score'] >= min_ws and
                long_result['weighted_score'] > short_result['weighted_score']):
                action = 'buy'
                score_result = long_result
                side = 'long'
            elif (short_result['score'] >= self.min_score_to_open and 
                  short_result['weighted_score'] >= min_ws and
                  short_result['weighted_score'] > long_result['weighted_score']):
                action = 'sell'
                score_result = short_result
                side = 'short'
            
            if action and score_result:
                # 计算仓位大小
                margin = self.calculate_position_size(df, score_result, available_margin, side)
                
                if margin <= 0:
                    continue
                
                # 计算开仓数量
                quantity = (margin * self.leverage) / current_price
                
                # 生成开仓信号（止盈止损由 check_long/short_exit_conditions 处理）
                signals.append(Signal(
                    symbol=symbol,
                    action=action,
                    price=Decimal(str(current_price)),
                    quantity=Decimal(str(quantity)),
                    reason=f"开{side}仓: 评分{score_result['weighted_score']:.2f}, "
                           f"{score_result['score']}个指标, 保证金${margin:.2f}"
                ))
                
                logger.info(f"✅ 生成{side}信号: {symbol} @ {current_price:.4f}, "
                          f"数量: {quantity:.6f}, 保证金: ${margin:.2f}")
                
                # 更新可用保证金
                available_margin -= margin
        
        return signals
    
    def should_exit_position(self, position: Position, current_data: pd.Series) -> bool:
        """判断是否需要平仓（接口方法）"""
        # 构造一个简单的DataFrame
        df = pd.DataFrame([current_data])
        
        pos_dict = {
            'symbol': position.symbol,
            'side': position.side,
            'quantity': position.quantity,
            'entry_price': position.entry_price,
            'current_price': position.current_price
        }
        
        if position.side == 'long':
            should_exit, _ = self.check_long_exit_conditions(df, pos_dict)
            return should_exit
        else:
            should_exit, _ = self.check_short_exit_conditions(df, pos_dict)
            return should_exit


# 快速参数调整函数
def create_strategy_with_params(params: Dict) -> "ComprehensiveStrategyV2":
    """使用自定义参数创建策略实例"""
    default_config = TradingConfig()
    
    # 默认参数
    default_params = {
        'initial_capital': 500,
        'margin_levels': {2: 5.0, 3: 8.0, 4: 12.0, 5: 15.0},
        'min_score_to_open': 2.5,
        'use_trend_filter': True,
        'only_trend_following': False,
        'default_tp_pct': 1.0,
        'default_sl_pct': 0.5
    }
    
    # 合并参数
    merged_params = {**default_params, **params}
    
    strategy = ComprehensiveStrategyV2(
        symbols=['BTCUSDT', 'ETHUSDT'],  # 默认交易对
        config=default_config,
        params=merged_params
    )
    
    return strategy