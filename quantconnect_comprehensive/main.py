# region imports
from AlgorithmImports import *
import pandas as pd
import numpy as np
# endregion

"""
Comprehensive 综合性策略 - QuantConnect 版本
多指标评分开仓：布林带、RSI、K线形态、KDJ、OBV、均线、MACD
趋势过滤 + 止盈止损
"""


class ComprehensiveStrategyAlgorithm(QCAlgorithm):
    """Comprehensive 策略 QuantConnect 实现"""

    def Initialize(self):
        self.SetStartDate(2024, 1, 1)
        self.SetEndDate(2025, 1, 1)
        self.SetCash(10000)
        
        # 交易标的（QuantConnect 加密货币格式）
        self.symbol = self.AddCrypto("ETHUSD", Resolution.Daily).Symbol
        self.SetBrokerageModel(BrokerageName.Default, AccountType.Cash)
        
        # 策略参数（与 comprehensive.py 一致）
        self.margin_levels = {2: 5.0, 3: 8.0, 4: 12.0, 5: 15.0}
        self.take_profit_pct = 0.5   # 止盈 50%
        self.stop_loss_pct = 0.4     # 止损 40%
        self.rsi_oversold = 40   # 放宽以便日线有更多信号
        self.rsi_overbought = 60
        self.rsi_take_profit_long = 68
        self.rsi_take_profit_short = 32
        self.min_score_to_open = 3   # 至少3个条件（原4太严，日线少有触发）
        self.min_weighted_score = 4.0
        self.condition_weights = {
            'trend': 1.5, 'price_position': 1.3, 'rsi_signal': 1.0,
            'pattern': 0.8, 'volume': 0.7, 'kdj_signal': 0.6,
            'obv_signal': 0.5, 'ma_cross': 0.9, 'macd_signal': 0.8
        }
        self.require_ma50_filter = True
        self.min_bb_width = 0.01  # 布林带过窄不开仓（0.02 太严，日线常不触发）
        self.cooldown_days = 5
        self.last_exit_day = -999
        self.allow_short = False  # 现金账户不支持做空，设为 True 需使用 Margin 账户
        
        self.entry_price = 0
        self.entry_day = 0

    def OnData(self, data: Slice):
        if not data.Bars.ContainsKey(self.symbol):
            return
            
        if not self.Portfolio[self.symbol].Invested:
            self._check_entry(data)
        else:
            self._check_exit(data)

    def _get_history_df(self, period: int = 120) -> pd.DataFrame:
        """获取历史数据 DataFrame（兼容 QuantConnect 列名 open/Open）"""
        hist = self.History(self.symbol, period, Resolution.Daily)
        if hist.empty:
            return pd.DataFrame()
        if isinstance(hist.index, pd.MultiIndex):
            hist = hist.reset_index(level=0, drop=True)
        # QuantConnect 通常用小写列名，兼容 PascalCase
        def _col(k):
            for key in [k, k.title(), k.upper()]:
                if key in hist.columns:
                    return hist[key]
            return None
        o, h, l, c, v = _col('open'), _col('high'), _col('low'), _col('close'), _col('volume')
        if o is None or c is None:
            return pd.DataFrame()
        df = pd.DataFrame({'open': o, 'high': h, 'low': l, 'close': c, 'volume': v if v is not None else 0})
        return df

    def _calc_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算技术指标"""
        if len(df) < 60:
            return df
        df = df.copy()
        df['MA5'] = df['close'].rolling(5).mean()
        df['MA10'] = df['close'].rolling(10).mean()
        df['MA20'] = df['close'].rolling(20).mean()
        df['MA50'] = df['close'].rolling(50).mean()
        df['BB_MIDDLE'] = df['close'].rolling(20).mean()
        bb_std = df['close'].rolling(20).std()
        df['BB_UPPER'] = df['BB_MIDDLE'] + 2 * bb_std
        df['BB_LOWER'] = df['BB_MIDDLE'] - 2 * bb_std
        df['BB_WIDTH'] = (df['BB_UPPER'] - df['BB_LOWER']) / df['BB_MIDDLE'].replace(0, np.nan)
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        avg_gain = gain.rolling(14).mean()
        avg_loss = loss.rolling(14).mean()
        rs = np.where(avg_loss > 0, avg_gain / avg_loss, 10.0)
        df['RSI'] = 100 - (100 / (1 + rs))
        ema12 = df['close'].ewm(span=12, adjust=False).mean()
        ema26 = df['close'].ewm(span=26, adjust=False).mean()
        df['MACD'] = ema12 - ema26
        df['MACD_SIGNAL'] = df['MACD'].ewm(span=9, adjust=False).mean()
        df['MACD_HIST'] = df['MACD'] - df['MACD_SIGNAL']
        df['VOLUME_MA20'] = df['volume'].rolling(20).mean()
        df['VOLUME_RATIO'] = df['volume'] / df['VOLUME_MA20'].replace(0, np.nan)
        low_9 = df['low'].rolling(9).min()
        high_9 = df['high'].rolling(9).max()
        rsv = np.where(high_9 > low_9, (df['close'] - low_9) / (high_9 - low_9) * 100, 50)
        df['KDJ_K'] = pd.Series(rsv, index=df.index).ewm(com=2, adjust=False).mean()
        df['KDJ_D'] = df['KDJ_K'].ewm(com=2, adjust=False).mean()
        df['KDJ_J'] = 3 * df['KDJ_K'] - 2 * df['KDJ_D']
        df['OBV'] = (np.sign(df['close'].diff()) * df['volume']).fillna(0).cumsum()
        df['OBV_MA20'] = df['OBV'].rolling(20).mean()
        df['MOMENTUM_10'] = df['close'].pct_change(10)
        df['RESISTANCE'] = df['high'].rolling(20).max()
        df['SUPPORT'] = df['low'].rolling(20).min()
        return df

    def _get_trend(self, df: pd.DataFrame) -> str:
        """判定趋势"""
        if len(df) < 30:
            return 'neutral'
        latest = df.iloc[-1]
        ma5, ma20, ma50 = latest.get('MA5'), latest.get('MA20'), latest.get('MA50')
        if pd.isna(ma5) or pd.isna(ma20) or pd.isna(ma50):
            return 'neutral'
        close = latest['close']
        mom = latest.get('MOMENTUM_10', 0)
        if ma5 > ma20 > ma50:
            return 'uptrend'
        if ma5 < ma20 < ma50:
            return 'downtrend'
        if ma5 > ma20 and ma20 > close:
            return 'downtrend'
        if ma5 < ma20 and ma20 < close:
            return 'uptrend'
        if pd.notna(latest.get('BB_MIDDLE')):
            if close > latest['BB_MIDDLE'] * 1.02:
                return 'uptrend'
            if close < latest['BB_MIDDLE'] * 0.98:
                return 'downtrend'
        if pd.notna(mom):
            if mom > 0.02:
                return 'uptrend'
            if mom < -0.02:
                return 'downtrend'
        return 'neutral'

    def _calc_long_score(self, df: pd.DataFrame) -> dict:
        """计算做多评分，score = 满足的条件数量"""
        if len(df) < 50:
            return {'score': 0, 'weighted_score': 0}
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        trend = self._get_trend(df)
        if trend in ('downtrend', 'neutral'):
            return {'score': 0, 'weighted_score': 0}
        condition_count = 1  # 趋势已满足
        weighted_score = 1.0 * self.condition_weights['trend']
        if self.require_ma50_filter and pd.notna(latest.get('MA50')):
            if latest['close'] < latest['MA50'] * 0.998:
                return {'score': 0, 'weighted_score': 0}
        # 价格支撑（接近或触及下轨加分）
        if pd.notna(latest.get('BB_LOWER')):
            if latest['close'] <= latest['BB_LOWER'] * 1.05:
                condition_count += 1
                weighted_score += 0.8 * self.condition_weights['price_position']
        # RSI
        rsi = latest.get('RSI', 50)
        if pd.notna(rsi) and rsi < self.rsi_oversold:
            condition_count += 1
            weighted_score += min(1.0, (self.rsi_oversold - rsi) / 20) * self.condition_weights['rsi_signal']
        # K线形态
        body = abs(latest['close'] - latest['open'])
        lower_shadow = min(latest['open'], latest['close']) - latest['low']
        pattern_ok = False
        if body > 0 and lower_shadow > body * 1.5 and latest['close'] > latest['open']:
            pattern_ok = True
            weighted_score += 0.8 * self.condition_weights['pattern']
        if prev['close'] < prev['open'] and latest['close'] > latest['open'] and latest['close'] > prev['open']:
            pattern_ok = True
            weighted_score += 0.8 * self.condition_weights['pattern']
        if pattern_ok:
            condition_count += 1
        # 成交量
        vr = latest.get('VOLUME_RATIO', 1)
        if pd.notna(vr) and prev['close'] > 0 and (latest['close'] - prev['close']) / prev['close'] < -0.005 and vr < 0.8:
            condition_count += 1
            weighted_score += 0.7 * self.condition_weights['volume']
        # KDJ
        j = latest.get('KDJ_J', 50)
        if pd.notna(j) and j < 25:
            condition_count += 1
            weighted_score += 0.7 * self.condition_weights['kdj_signal']
        # OBV
        obv, obv_ma = latest.get('OBV'), latest.get('OBV_MA20')
        if pd.notna(obv) and pd.notna(obv_ma) and obv_ma > 0 and obv > obv_ma * 0.98:
            condition_count += 1
            weighted_score += 0.6 * self.condition_weights['obv_signal']
        # 均线金叉
        ma5, ma10 = latest.get('MA5'), latest.get('MA10')
        ma5_prev, ma10_prev = prev.get('MA5'), prev.get('MA10')
        if all(pd.notna(x) for x in [ma5, ma10, ma5_prev, ma10_prev]):
            if ma5_prev <= ma10_prev and ma5 > ma10:
                condition_count += 1
                weighted_score += 0.8 * self.condition_weights['ma_cross']
        # MACD
        hist_vals = df['MACD_HIST'].tail(5).values if 'MACD_HIST' in df.columns else []
        if len(hist_vals) >= 3 and hist_vals[-3] < 0 and hist_vals[-2] < 0 and hist_vals[-1] > 0:
            condition_count += 1
            weighted_score += 0.8 * self.condition_weights['macd_signal']
        return {'score': condition_count, 'weighted_score': weighted_score}

    def _calc_short_score(self, df: pd.DataFrame) -> dict:
        """计算做空评分，score = 满足的条件数量"""
        if len(df) < 50:
            return {'score': 0, 'weighted_score': 0}
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        trend = self._get_trend(df)
        if trend in ('uptrend', 'neutral'):
            return {'score': 0, 'weighted_score': 0}
        condition_count = 1
        weighted_score = 1.0 * self.condition_weights['trend']
        if self.require_ma50_filter and pd.notna(latest.get('MA50')):
            if latest['close'] > latest['MA50'] * 1.002:
                return {'score': 0, 'weighted_score': 0}
        if pd.notna(latest.get('BB_UPPER')) and latest['close'] >= latest['BB_UPPER'] * 0.95:
            condition_count += 1
            weighted_score += 0.8 * self.condition_weights['price_position']
        rsi = latest.get('RSI', 50)
        if pd.notna(rsi) and rsi > self.rsi_overbought:
            condition_count += 1
            weighted_score += min(1.0, (rsi - self.rsi_overbought) / 20) * self.condition_weights['rsi_signal']
        upper_shadow = latest['high'] - max(latest['open'], latest['close'])
        body = abs(latest['close'] - latest['open'])
        if body > 0 and upper_shadow > body * 1.5 and latest['close'] < latest['open']:
            condition_count += 1
            weighted_score += 0.8 * self.condition_weights['pattern']
        j = latest.get('KDJ_J', 50)
        if pd.notna(j) and j > 75:
            condition_count += 1
            weighted_score += 0.7 * self.condition_weights['kdj_signal']
        ma5, ma10 = latest.get('MA5'), latest.get('MA10')
        ma5_prev, ma10_prev = prev.get('MA5'), prev.get('MA10')
        if all(pd.notna(x) for x in [ma5, ma10, ma5_prev, ma10_prev]):
            if ma5_prev >= ma10_prev and ma5 < ma10:
                condition_count += 1
                weighted_score += 0.8 * self.condition_weights['ma_cross']
        hist_vals = df['MACD_HIST'].tail(5).values if 'MACD_HIST' in df.columns else []
        if len(hist_vals) >= 3 and hist_vals[-3] > 0 and hist_vals[-2] > 0 and hist_vals[-1] < 0:
            condition_count += 1
            weighted_score += 0.8 * self.condition_weights['macd_signal']
        return {'score': condition_count, 'weighted_score': weighted_score}

    def _check_entry(self, data: Slice):
        df = self._get_history_df(120)
        if len(df) < 60:
            return
        df = self._calc_indicators(df)
        if df.empty or pd.isna(df.iloc[-1].get('RSI', np.nan)):
            return
        bb_width = df.iloc[-1].get('BB_WIDTH', 0.05)
        if pd.notna(bb_width) and bb_width < self.min_bb_width:
            return
        current_bar = data.Bars[self.symbol]
        bars_count = len(df)
        if bars_count - self.last_exit_day < self.cooldown_days:
            return
        long_result = self._calc_long_score(df)
        short_result = self._calc_short_score(df)
        price = float(current_bar.Close)
        if (long_result['score'] >= self.min_score_to_open and 
            long_result['weighted_score'] >= self.min_weighted_score and
            long_result['weighted_score'] > short_result['weighted_score']):
            margin = self.margin_levels.get(min(5, long_result['score'] + 1), 15)
            pct = min(0.25, margin / 100)
            qty = (self.Portfolio.TotalPortfolioValue * pct) / price
            self.MarketOrder(self.symbol, qty)
            self.entry_price = price
            self.entry_day = bars_count
            self.Debug(f"开多 {price:.2f} 评分={long_result['weighted_score']:.2f}")
        elif (self.allow_short and
              short_result['weighted_score'] >= self.min_weighted_score and
              short_result['weighted_score'] > long_result['weighted_score']):
            margin = self.margin_levels.get(4, 15)
            pct = min(0.25, margin / 100)
            qty = -(self.Portfolio.TotalPortfolioValue * pct) / price
            self.MarketOrder(self.symbol, qty)
            self.entry_price = price
            self.entry_day = bars_count
            self.Debug(f"开空 {price:.2f} 评分={short_result['weighted_score']:.2f}")

    def _check_exit(self, data: Slice):
        if not self.Portfolio[self.symbol].Invested:
            return
        current_bar = data.Bars[self.symbol]
        price = float(current_bar.Close)
        pos = self.Portfolio[self.symbol]
        qty = pos.Quantity
        entry = self.entry_price if self.entry_price > 0 else pos.AveragePrice
        if qty > 0:  # 多头
            pnl_pct = (price - entry) / entry
            if pnl_pct >= self.take_profit_pct / 100:
                self.Liquidate(self.symbol)
                self.last_exit_day = len(self._get_history_df(120))
                self.Debug(f"止盈平多 {pnl_pct*100:.2f}%")
            elif pnl_pct <= -self.stop_loss_pct / 100:
                self.Liquidate(self.symbol)
                self.last_exit_day = len(self._get_history_df(120))
                self.Debug(f"止损平多 {pnl_pct*100:.2f}%")
            else:
                df = self._calc_indicators(self._get_history_df(120))
                if len(df) >= 2:
                    rsi = df.iloc[-1].get('RSI', 50)
                    if pd.notna(rsi) and rsi > self.rsi_take_profit_long and pnl_pct > 0.01:
                        self.Liquidate(self.symbol)
                        self.last_exit_day = len(self._get_history_df(120))
                        return
                if len(df) >= 30:
                    trend = self._get_trend(df)
                    if trend == 'downtrend' and pnl_pct > 0.015:
                        self.Liquidate(self.symbol)
                        self.last_exit_day = len(self._get_history_df(120))
        else:  # 空头
            pnl_pct = (entry - price) / entry
            if pnl_pct >= self.take_profit_pct / 100:
                self.Liquidate(self.symbol)
                self.last_exit_day = len(self._get_history_df(120))
                self.Debug(f"止盈平空 {pnl_pct*100:.2f}%")
            elif pnl_pct <= -self.stop_loss_pct / 100:
                self.Liquidate(self.symbol)
                self.last_exit_day = len(self._get_history_df(120))
                self.Debug(f"止损平空 {pnl_pct*100:.2f}%")
            else:
                df = self._calc_indicators(self._get_history_df(120))
                if len(df) >= 2:
                    rsi = df.iloc[-1].get('RSI', 50)
                    if pd.notna(rsi) and rsi < self.rsi_take_profit_short and pnl_pct > 0.01:
                        self.Liquidate(self.symbol)
                        self.last_exit_day = len(self._get_history_df(120))
                        return
                if len(df) >= 30:
                    trend = self._get_trend(df)
                    if trend == 'uptrend' and pnl_pct > 0.015:
                        self.Liquidate(self.symbol)
                        self.last_exit_day = len(self._get_history_df(120))
