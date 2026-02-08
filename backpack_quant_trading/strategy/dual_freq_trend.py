"""
双频趋势共振高频策略
- 15分钟：趋势判定（EMA9/21 + 成交量）
- 1分钟：精细入场（回调/突破 + RSI6 + 布林带 + EMA5/13）
- 持仓时间短，高胜率，风险回报比 1:1.5~1:2
"""

from decimal import Decimal
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np
from loguru import logger
from datetime import datetime, timedelta

from backpack_quant_trading.strategy.base import BaseStrategy, Signal, Position
from backpack_quant_trading.config.settings import TradingConfig


class DualFreqTrendResonanceStrategy(BaseStrategy):
    """双频趋势共振高频策略"""

    def __init__(self, symbols: List[str], config: TradingConfig, params: Optional[Dict] = None):
        super().__init__(
            name="DualFreqTrendResonance",
            symbols=symbols,
            api_client=None,
            risk_manager=None
        )
        self.initial_capital = 500
        self.leverage = 100

        # 15分钟趋势参数
        self.ema9_period = 9
        self.ema21_period = 21

        # 1分钟入场参数
        self.ema5_period = 5
        self.ema13_period = 13
        self.rsi_period = 6
        self.bb_period = 20
        self.bb_std = 2

        # 【优化】小止盈易达成，提高胜率；1:1 盈亏比
        self.sl_pct = 0.004   # 0.4% 止损
        self.tp_pct = 0.004   # 0.4% 止盈（与止损同，1:1）

        # 时间止损（分钟）
        self.time_stop_minutes = 6

        # 日内总止损（占总资金比例）
        self.daily_stop_pct = 0.02
        self._daily_pnl = 0.0
        self._last_reset_date = None

        # 保证金
        self.margin_per_trade = 10.0

        # 平仓后冷却期（50分钟）
        self.cooldown_bars = 50
        # 是否启用突破模式（突破假信号多，可关闭）
        self.use_breakout_mode = False

        if params:
            for key, value in params.items():
                if hasattr(self, key):
                    setattr(self, key, value)

        logger.info(f"双频趋势共振策略 - 时间止损:{self.time_stop_minutes}min, 止盈止损各0.4%, 突破模式:{self.use_breakout_mode}")

    def _resample_to_15m(self, df_1m: pd.DataFrame) -> pd.DataFrame:
        """将1分钟数据重采样为15分钟"""
        if df_1m.empty or len(df_1m) < 20:
            return pd.DataFrame()
        resampled = df_1m.resample('15min').agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }).dropna()
        return resampled

    def _calc_15m_indicators(self, df_15m: pd.DataFrame) -> pd.DataFrame:
        """计算15分钟图指标"""
        if len(df_15m) < 25:
            return df_15m
        df = df_15m.copy()
        df['EMA9'] = df['close'].ewm(span=self.ema9_period, adjust=False).mean()
        df['EMA21'] = df['close'].ewm(span=self.ema21_period, adjust=False).mean()
        df['VOL_MA5'] = df['volume'].rolling(5).mean()
        df['PRICE_CHG'] = df['close'].pct_change()
        df['VOL_CHG'] = df['volume'].pct_change()
        return df

    def _calc_1m_indicators(self, df_1m: pd.DataFrame) -> pd.DataFrame:
        """计算1分钟图指标"""
        if len(df_1m) < 25:
            return df_1m
        df = df_1m.copy()
        df['EMA5'] = df['close'].ewm(span=self.ema5_period, adjust=False).mean()
        df['EMA13'] = df['close'].ewm(span=self.ema13_period, adjust=False).mean()
        # RSI(6)
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        avg_gain = gain.rolling(self.rsi_period).mean()
        avg_loss = loss.rolling(self.rsi_period).mean()
        rs = np.where(avg_loss > 0, avg_gain / avg_loss, 10.0)
        df['RSI'] = 100 - (100 / (1 + rs))
        # 布林带
        df['BB_MID'] = df['close'].rolling(self.bb_period).mean()
        bb_std_val = df['close'].rolling(self.bb_period).std()
        df['BB_UPPER'] = df['BB_MID'] + self.bb_std * bb_std_val
        df['BB_LOWER'] = df['BB_MID'] - self.bb_std * bb_std_val
        df['VOLUME_MA5'] = df['volume'].rolling(5).mean()
        return df

    def _get_15m_trend(self, df_15m: pd.DataFrame) -> str:
        """判定15分钟趋势，需连续2根同向确认"""
        if len(df_15m) < 6 or 'EMA9' not in df_15m.columns:
            return 'neutral'
        latest = df_15m.iloc[-1]
        prev_bar = df_15m.iloc[-2]
        ema9 = latest.get('EMA9')
        ema21 = latest.get('EMA21')
        close = latest['close']
        if pd.isna(ema9) or pd.isna(ema21) or ema21 <= 0:
            return 'neutral'
        gap = (ema9 - ema21) / ema21
        prev_gap = (prev_bar.get('EMA9') - prev_bar.get('EMA21')) / prev_bar.get('EMA21') if prev_bar.get('EMA21', 0) > 0 else 0

        # 多头：当前+上一根15m均为多头
        if gap > 0.001 and close > ema21 * 1.001 and prev_gap > 0.0005:
            return 'uptrend'
        # 空头
        if gap < -0.001 and close < ema21 * 0.999 and prev_gap < -0.0005:
            return 'downtrend'
        return 'neutral'

    def _check_long_entry_pullback(self, latest: pd.Series, prev: pd.Series, prev2: pd.Series,
                                    df_1m: pd.DataFrame) -> bool:
        """回调买入：价格回踩+RSI超卖回升+非高位+前一根下跌"""
        close = latest['close']
        ema13 = latest.get('EMA13')
        bb_mid = latest.get('BB_MID')
        rsi = latest.get('RSI', 50)
        rsi_prev = prev.get('RSI', 50)
        rsi_prev2 = prev2.get('RSI', 50)
        if pd.isna(ema13) or pd.isna(bb_mid) or ema13 <= 0 or bb_mid <= 0:
            return False
        rsi_prev2 = rsi_prev2 if pd.notna(rsi_prev2) else 50
        near_ema = abs(close - ema13) / ema13 < 0.005
        near_bb = abs(close - bb_mid) / bb_mid < 0.005
        rsi_was_low = rsi_prev2 < 38 or rsi_prev < 35
        rsi_rising = rsi > rsi_prev and 35 <= rsi <= 48
        # 前一根K线收跌（真回调）
        prev_closed_down = prev['close'] < prev['open']
        # 价格不在20根高点附近（不追高）
        if len(df_1m) >= 20:
            high20 = df_1m['high'].iloc[-20:].max()
            low20 = df_1m['low'].iloc[-20:].min()
            if high20 > low20:
                pos_in_range = (close - low20) / (high20 - low20)
                not_at_top = pos_in_range < 0.85  # 不在顶部15%
            else:
                not_at_top = True
        else:
            not_at_top = True
        return (near_ema or near_bb) and rsi_was_low and rsi_rising and prev_closed_down and not_at_top

    def _check_long_entry_breakout(self, latest: pd.Series, prev: pd.Series) -> bool:
        """突破买入：【收紧】放量突破+金叉+RSI强"""
        close = latest['close']
        ema5 = latest.get('EMA5')
        ema13 = latest.get('EMA13')
        bb_upper = latest.get('BB_UPPER')
        rsi = latest.get('RSI', 50)
        vol = latest.get('volume', 0)
        vol_ma = latest.get('VOLUME_MA5', vol)
        ema5_prev = prev.get('EMA5')
        ema13_prev = prev.get('EMA13')
        if pd.isna(ema5) or pd.isna(ema13) or pd.isna(bb_upper) or vol_ma <= 0:
            return False
        broke_upper = close >= bb_upper * 0.998
        golden_cross = ema5_prev <= ema13_prev and ema5 > ema13
        # 【收紧】RSI>55 且 放量>1.2倍
        rsi_ok = rsi > 55
        volume_ok = vol > vol_ma * 1.2
        return broke_upper and golden_cross and rsi_ok and volume_ok

    def _check_short_entry_pullback(self, latest: pd.Series, prev: pd.Series, prev2: pd.Series,
                                     df_1m: pd.DataFrame) -> bool:
        """反弹做空：价格反弹至EMA13/布林中轨，RSI超买回落+非低位+前一根上涨"""
        close = latest['close']
        ema13 = latest.get('EMA13')
        bb_mid = latest.get('BB_MID')
        rsi = latest.get('RSI', 50)
        rsi_prev = prev.get('RSI', 50)
        rsi_prev2 = prev2.get('RSI', 50)
        if pd.isna(ema13) or pd.isna(bb_mid) or ema13 <= 0 or bb_mid <= 0:
            return False
        rsi_prev2 = rsi_prev2 if pd.notna(rsi_prev2) else 50
        near_ema = abs(close - ema13) / ema13 < 0.005
        near_bb = abs(close - bb_mid) / bb_mid < 0.005
        rsi_was_high = rsi_prev2 > 62 or rsi_prev > 65
        rsi_falling = rsi < rsi_prev and 52 <= rsi <= 65
        prev_closed_up = prev['close'] > prev['open']
        if len(df_1m) >= 20:
            high20 = df_1m['high'].iloc[-20:].max()
            low20 = df_1m['low'].iloc[-20:].min()
            if high20 > low20:
                pos_in_range = (close - low20) / (high20 - low20)
                not_at_bottom = pos_in_range > 0.15
            else:
                not_at_bottom = True
        else:
            not_at_bottom = True
        return (near_ema or near_bb) and rsi_was_high and rsi_falling and prev_closed_up and not_at_bottom

    def _check_short_entry_breakout(self, latest: pd.Series, prev: pd.Series) -> bool:
        """突破做空：【收紧】放量跌破+死叉+RSI弱"""
        close = latest['close']
        ema5 = latest.get('EMA5')
        ema13 = latest.get('EMA13')
        bb_lower = latest.get('BB_LOWER')
        rsi = latest.get('RSI', 50)
        vol = latest.get('volume', 0)
        vol_ma = latest.get('VOLUME_MA5', vol)
        ema5_prev = prev.get('EMA5')
        ema13_prev = prev.get('EMA13')
        if pd.isna(ema5) or pd.isna(ema13) or pd.isna(bb_lower) or vol_ma <= 0:
            return False
        broke_lower = close <= bb_lower * 1.002
        death_cross = ema5_prev >= ema13_prev and ema5 < ema13
        rsi_ok = rsi < 45
        volume_ok = vol > vol_ma * 1.2
        return broke_lower and death_cross and rsi_ok and volume_ok

    def calculate_technical_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算指标（1分钟数据，内部会重采样15分钟）"""
        return self._calc_1m_indicators(df)

    def get_stop_take_profit_prices(self, entry_price: float, side: str) -> Tuple[float, float]:
        """返回止盈止损价格（风险回报比 1:1.5）"""
        if side == 'long':
            sl_price = entry_price * (1 - self.sl_pct)
            tp_price = entry_price * (1 + self.tp_pct)
        else:
            sl_price = entry_price * (1 + self.sl_pct)
            tp_price = entry_price * (1 - self.tp_pct)
        return tp_price, sl_price

    def check_long_exit_conditions(self, df: pd.DataFrame, position: Dict) -> Tuple[bool, str]:
        """检查平多条件"""
        if len(df) < 2:
            return False, ""
        latest = df.iloc[-1]
        price = float(latest['close'])
        entry_price = float(position['entry_price'])
        entry_time = position.get('entry_time')
        current_time = position.get('current_time', df.index[-1])

        # 1. 固定止盈止损（由回测引擎K线内模拟处理，此处作收盘价二次检查）
        pnl_pct = ((price - entry_price) / entry_price) * self.leverage  # 小数形式 0.6=60%
        tp_threshold = self.tp_pct * self.leverage   # 0.006*100=0.6
        sl_threshold = self.sl_pct * self.leverage   # 0.004*100=0.4
        if pnl_pct >= tp_threshold:
            return True, f"止盈({pnl_pct*100:.1f}%)"
        if pnl_pct <= -sl_threshold:
            return True, f"止损({pnl_pct*100:.1f}%)"

        # 2. 时间止损
        if entry_time is not None and current_time is not None:
            try:
                entry_ts = pd.Timestamp(entry_time)
                curr_ts = pd.Timestamp(current_time)
                minutes_held = (curr_ts - entry_ts).total_seconds() / 60
                if minutes_held >= self.time_stop_minutes:
                    return True, f"时间止损({minutes_held:.0f}min)"
            except Exception:
                pass

        # 3. 15分钟趋势反转
        df_15m = self._resample_to_15m(df)
        df_15m = self._calc_15m_indicators(df_15m)
        trend = self._get_15m_trend(df_15m)
        if trend == 'downtrend':
            return True, "15m趋势反转"

        return False, ""

    def check_short_exit_conditions(self, df: pd.DataFrame, position: Dict) -> Tuple[bool, str]:
        """检查平空条件"""
        if len(df) < 2:
            return False, ""
        latest = df.iloc[-1]
        price = float(latest['close'])
        entry_price = float(position['entry_price'])
        entry_time = position.get('entry_time')
        current_time = position.get('current_time', df.index[-1])

        pnl_pct = ((entry_price - price) / entry_price) * self.leverage
        tp_threshold = self.tp_pct * self.leverage
        sl_threshold = self.sl_pct * self.leverage
        if pnl_pct >= tp_threshold:
            return True, f"止盈({pnl_pct*100:.1f}%)"
        if pnl_pct <= -sl_threshold:
            return True, f"止损({pnl_pct*100:.1f}%)"

        if entry_time is not None and current_time is not None:
            try:
                entry_ts = pd.Timestamp(entry_time)
                curr_ts = pd.Timestamp(current_time)
                minutes_held = (curr_ts - entry_ts).total_seconds() / 60
                if minutes_held >= self.time_stop_minutes:
                    return True, f"时间止损({minutes_held:.0f}min)"
            except Exception:
                pass

        df_15m = self._resample_to_15m(df)
        df_15m = self._calc_15m_indicators(df_15m)
        trend = self._get_15m_trend(df_15m)
        if trend == 'uptrend':
            return True, "15m趋势反转"

        return False, ""

    async def calculate_signal(self, market_data: Dict[str, pd.DataFrame]) -> List[Signal]:
        """生成交易信号"""
        signals = []
        for symbol, df in market_data.items():
            if len(df) < 110:
                continue
            df_1m = self._calc_1m_indicators(df)
            df_15m = self._resample_to_15m(df_1m)
            df_15m = self._calc_15m_indicators(df_15m)
            trend = self._get_15m_trend(df_15m)
            if trend == 'neutral':
                continue

            latest = df_1m.iloc[-1]
            prev = df_1m.iloc[-2]
            prev2 = df_1m.iloc[-3]
            current_price = float(latest['close'])
            quantity = (self.margin_per_trade * self.leverage) / current_price

            if trend == 'uptrend':
                pb = self._check_long_entry_pullback(latest, prev, prev2, df_1m)
                bo = self._check_long_entry_breakout(latest, prev) if getattr(self, 'use_breakout_mode', False) else False
                if pb or bo:
                    mode = "回调" if pb else "突破"
                    signals.append(Signal(
                        symbol=symbol,
                        action='buy',
                        price=Decimal(str(current_price)),
                        quantity=Decimal(str(quantity)),
                        reason=f"多头{mode} | 15m趋势向上"
                    ))
                    logger.info(f"双频多头信号: {symbol} @ {current_price:.2f} ({mode})")
            elif trend == 'downtrend':
                pb = self._check_short_entry_pullback(latest, prev, prev2, df_1m)
                bo = self._check_short_entry_breakout(latest, prev) if getattr(self, 'use_breakout_mode', False) else False
                if pb or bo:
                    mode = "反弹" if pb else "突破"
                    signals.append(Signal(
                        symbol=symbol,
                        action='sell',
                        price=Decimal(str(current_price)),
                        quantity=Decimal(str(quantity)),
                        reason=f"空头{mode} | 15m趋势向下"
                    ))
                    logger.info(f"双频空头信号: {symbol} @ {current_price:.2f} ({mode})")

        return signals

    def should_exit_position(self, position: Position, current_data: pd.Series) -> bool:
        """接口方法"""
        df = pd.DataFrame([current_data])
        pos_dict = {
            'symbol': position.symbol, 'side': position.side,
            'entry_price': position.entry_price, 'quantity': position.quantity,
            'current_price': position.current_price
        }
        if position.side == 'long':
            return self.check_long_exit_conditions(df, pos_dict)[0]
        return self.check_short_exit_conditions(df, pos_dict)[0]
