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
from loguru import logger  # pyright: ignore[reportMissingImports]
from datetime import datetime, timedelta

from backpack_quant_trading.strategy.base import BaseStrategy, Signal, Position


class DualFreqTrendResonanceStrategy(BaseStrategy):
    """双频趋势共振高频策略"""

    def __init__(
        self,
        symbols: List[str],
        api_client=None,
        risk_manager=None,
        *,
        margin: Optional[float] = None,
        leverage: Optional[int] = None,
        stop_loss_ratio: Optional[float] = None,
        take_profit_ratio: Optional[float] = None,
        params: Optional[Dict] = None,
    ):
        # 统一为 live 引擎可实例化的构造参数（与 MeanReversion/AIAdaptive 一致）
        super().__init__("DualFreqTrendResonance", symbols, api_client, risk_manager)
        self.initial_capital = 500
        # === Pine 对齐：杠杆 ===
        self.leverage = int(leverage) if leverage is not None else 100

        # 15分钟趋势参数
        self.ema9_period = 9
        self.ema21_period = 21

        # 1分钟入场参数
        self.ema5_period = 5
        self.ema13_period = 13
        self.rsi_period = 6
        self.bb_period = 20
        self.bb_std = 2

        # Pine: RSI 阈值
        self.rsi_long_min = 32
        self.rsi_long_max = 55
        self.rsi_short_min = 45
        self.rsi_short_max = 68

        # Pine: 1m 均线方向过滤
        self.trend_ema_filter = True

        # === Pine 对齐：止盈/止损用“保证金收益%”定义，再按杠杆换算为价格波动 ===
        # Pine: tp_price_move = (tp_pct/100)/leverage；sl_price_move = (sl_pct/100)/leverage
        self.tp_pct = 150.0  # 保证金收益%
        self.sl_pct = 50.0   # 保证金收益%
        # 允许通过启动参数覆盖（若传入的是比例 0.02/0.015，则认为是“价格比例”，直接换算回保证金收益%以对齐）
        if take_profit_ratio is not None:
            v = float(take_profit_ratio)
            # v<=1 视为价格比例（0.02=2%价格），换算为保证金收益%：v * leverage * 100
            self.tp_pct = v * self.leverage * 100 if v <= 1 else v
        if stop_loss_ratio is not None:
            v = float(stop_loss_ratio)
            self.sl_pct = v * self.leverage * 100 if v <= 1 else v

        # === Pine 对齐：时间止损/冷却/最小进场间隔（单位：1m K线）===
        self.time_stop_bars = 6
        self.cooldown_bars = 6
        self.min_entry_gap = 6

        # Pine: 单日最大回撤（按权益曲线）
        self.daily_loss_pct = 5.0
        self._day_start_equity: Optional[float] = None
        self._day_key: Optional[str] = None

        # Pine: 固定每单保证金（并可用评分分挡位替代）
        self.use_fixed_margin = True
        self.margin_per_trade = float(margin) if margin is not None else 10.0
        # Pine: 最大仓位% / 单笔风险%（在 use_fixed_margin=true 时基本不参与 qty 计算，这里保留以便未来切换）
        self.max_pos_pct = 30.0
        self.risk_per_trade_pct = 0.5

        # ======【Pine 对齐】加权评分 -> 分挡位保证金（影响 qty_fixed）======
        # 开关：启用后，quantity 不再固定 margin_per_trade，而是按 weighted_score 对应挡位保证金（再受 max_margin_per_trade 限制）
        self.use_weighted_positioning = True
        # 至少达到该加权分才允许开仓（避免弱信号）
        self.min_weighted_score = 3.0
        # 分挡位保证金（U），按 weighted_score 命中。越高分 -> 越大保证金
        # 例如：score>=3.0 用 5U，>=4.5 用 8U，>=6.0 用 12U，>=7.5 用 15U
        self.score_margin_levels: List[Tuple[float, float]] = [
            (3.0, 5.0),
            (4.5, 8.0),
            (6.0, 12.0),
            (7.5, 15.0),
        ]
        # 指标权重（可通过 params 覆盖）
        self.condition_weights = {
            'trend': 1.5,            # 趋势
            'price_position': 1.2,   # 价格位置（靠近EMA/布林中轨/上下轨）
            'rsi_signal': 1.0,       # RSI（超买超卖 + 反转）
            'ma_state': 0.9,         # EMA5/EMA13 方向/交叉
            'macd_signal': 0.8,      # MACD 柱方向
            'volume': 0.7,           # 成交量配合（回调缩量/突破放量）
            'volatility': 0.6,       # 波动率过滤（BB宽度/ATR%）
            'pattern': 0.8,          # 回调/突破形态本身
        }
        # 波动率过滤（只参与评分；你也可以加成硬过滤）
        self.min_bb_width = 0.004   # 0.4%
        self.min_atr_pct = 0.0010   # 0.10%
        self.max_atr_pct = 0.0060   # 0.60%
        self.near_dist_pct = 0.008  # 0.8%
        self.pos_long_max = 0.85
        self.pos_short_min = 0.15
        self.pullback_volume_filter = True
        self.use_macd_filter = True
        self.use_rsi_slope = True
        self.use_volume_confirm = False

        # 5m 极端波动过滤
        self.extreme_vol_pct = 1.0

        # 15m ADX/DMI 过滤
        self.use_adx_filter = True
        self.adx_len = 14
        self.adx_threshold = 20.0
        self.use_dmi_dir_filter = True

        # 趋势参数（Pine）
        self.trend_relaxed = True
        self.htf_filter = True
        self.htf2_minutes = 60

        # 出场优化（Pine 默认：分批/追踪关闭，保本开启）
        self.use_partial_tp = False
        self.partial_tp_trigger_pct = 80.0
        self.partial_tp_qty_pct = 50.0
        self.move_sl_to_be = True
        self.be_trigger_pct = 60.0
        self.use_trailing_close = False
        self.trail_trigger_pct = 120.0
        self.trail_retrace_pct = 45.0

        # 是否启用突破模式（突破假信号多，可关闭）
        self.use_breakout_mode = False

        if params:
            for key, value in params.items():
                if hasattr(self, key):
                    setattr(self, key, value)

        # 运行时状态（按 symbol 维护）
        self._last_entry_time: Dict[str, pd.Timestamp] = {}
        self._last_exit_time: Dict[str, pd.Timestamp] = {}
        self._entry_time: Dict[str, pd.Timestamp] = {}
        self._peak_profit_pct: Dict[str, float] = {}
        self._partial_tp_done: Dict[str, bool] = {}

        logger.info(
            f"DualFreqTrendResonance 初始化: leverage={self.leverage}x, tp%={self.tp_pct}, sl%={self.sl_pct}, "
            f"time_stop_bars={self.time_stop_bars}, cooldown_bars={self.cooldown_bars}, min_entry_gap={self.min_entry_gap}, "
            f"breakout={self.use_breakout_mode}"
        )

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
        # ADX/DMI（Wilder）
        try:
            pdi, mdi, adx = self._calc_dmi_adx(df['high'], df['low'], df['close'], self.adx_len)
            df['PDI'] = pdi
            df['MDI'] = mdi
            df['ADX'] = adx
        except Exception:
            pass
        return df

    @staticmethod
    def _calc_dmi_adx(high: pd.Series, low: pd.Series, close: pd.Series, length: int) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """近似 Pine ta.dmi(len,len)：返回 (+DI, -DI, ADX)"""
        length = int(length)
        up = high.diff()
        down = -low.diff()
        plus_dm = np.where((up > down) & (up > 0), up, 0.0)
        minus_dm = np.where((down > up) & (down > 0), down, 0.0)
        tr1 = (high - low).abs()
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        def rma(x: pd.Series, n: int) -> pd.Series:
            return x.ewm(alpha=1 / n, adjust=False).mean()

        atr = rma(tr, length)
        p_dm = rma(pd.Series(plus_dm, index=high.index), length)
        m_dm = rma(pd.Series(minus_dm, index=high.index), length)
        pdi = 100 * (p_dm / atr.replace(0, np.nan))
        mdi = 100 * (m_dm / atr.replace(0, np.nan))
        dx = 100 * ((pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan))
        adx = rma(dx.fillna(0), length)
        return pdi.fillna(0), mdi.fillna(0), adx.fillna(0)

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

        # ======【新增】MACD / ATR / BB宽度（用于加权评分）======
        ema12 = df['close'].ewm(span=12, adjust=False).mean()
        ema26 = df['close'].ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        macd_signal = macd.ewm(span=9, adjust=False).mean()
        df['MACD_HIST'] = macd - macd_signal

        # ATR(14) 与 ATR%
        high = df['high']
        low = df['low']
        close = df['close']
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df['ATR14'] = tr.rolling(14).mean()
        df['ATR_PCT'] = df['ATR14'] / df['close']

        # BB宽度%
        df['BB_WIDTH'] = (df['BB_UPPER'] - df['BB_LOWER']) / df['BB_MID']
        return df

    def _pick_margin_by_score(self, weighted_score: float) -> float:
        """按加权评分选择保证金挡位（U）。未达标返回 0。"""
        if weighted_score < float(getattr(self, 'min_weighted_score', 0) or 0):
            return 0.0
        levels = list(getattr(self, 'score_margin_levels', []) or [])
        # 按阈值升序取最后一个命中的保证金
        levels = sorted([(float(s), float(m)) for s, m in levels], key=lambda x: x[0])
        margin = 0.0
        for s_th, m in levels:
            if weighted_score >= s_th:
                margin = m
        # 受用户在前端填写的“每单保证金”上限约束
        cap = float(getattr(self, "margin_per_trade", 0) or 0)
        if cap > 0:
            margin = min(margin, cap)
        return margin

    def _calc_weighted_entry_score(
        self,
        *,
        side: str,
        trend: str,
        latest: pd.Series,
        prev: pd.Series,
        prev2: pd.Series,
        df_1m: pd.DataFrame,
        entry_mode: str,  # "pullback"|"breakout"
    ) -> Dict:
        """计算开仓加权评分（简化版：0/1命中 + 权重求和），并给出保证金挡位。

        目标：复用 dual 的形态逻辑，同时引入 comprehensive 的“加权评分→分挡位下单”。
        """
        w = getattr(self, 'condition_weights', {}) or {}
        weighted = 0.0
        hits: Dict[str, float] = {}

        def hit(name: str, score: float = 1.0):
            nonlocal weighted
            weight = float(w.get(name, 1.0))
            weighted += float(score) * weight
            hits[name] = float(score) * weight

        close = float(latest.get('close') or 0)
        if close <= 0:
            return {'weighted_score': 0.0, 'hits': {}, 'margin': 0.0}

        # 1) 趋势对齐（dual 的核心）
        if (side == 'long' and trend == 'uptrend') or (side == 'short' and trend == 'downtrend'):
            hit('trend', 1.0)
        else:
            return {'weighted_score': 0.0, 'hits': {}, 'margin': 0.0}

        # 2) 形态（回调/突破）
        if entry_mode in ('pullback', 'breakout'):
            hit('pattern', 1.0)

        # 3) 价格位置（靠近 EMA13 或 BB中轨；以及更靠近上下轨可加分）
        ema13 = float(latest.get('EMA13') or 0)
        bb_mid = float(latest.get('BB_MID') or 0)
        bb_upper = float(latest.get('BB_UPPER') or 0)
        bb_lower = float(latest.get('BB_LOWER') or 0)
        pos_score = 0.0
        if ema13 > 0 and abs(close - ema13) / ema13 < 0.008:
            pos_score = max(pos_score, 0.8)
        if bb_mid > 0 and abs(close - bb_mid) / bb_mid < 0.008:
            pos_score = max(pos_score, 0.7)
        # 贴近下轨（多）/上轨（空）更强
        if side == 'long' and bb_lower > 0 and close <= bb_lower * 1.01:
            pos_score = max(pos_score, 1.0)
        if side == 'short' and bb_upper > 0 and close >= bb_upper * 0.99:
            pos_score = max(pos_score, 1.0)
        if pos_score > 0:
            hit('price_position', pos_score)

        # 4) RSI 信号（区间 + 反转）
        rsi = float(latest.get('RSI', 50) or 50)
        rsi_prev = float(prev.get('RSI', 50) or 50)
        rsi_prev2 = float(prev2.get('RSI', 50) or 50)
        rsi_score = 0.0
        if side == 'long':
            # 越超卖越高分 + 回升加分
            if rsi_prev2 < 38 or rsi_prev < 35:
                rsi_score = max(rsi_score, 0.7)
            if rsi > rsi_prev and 32 <= rsi <= 55:
                rsi_score = max(rsi_score, 0.9)
        else:
            if rsi_prev2 > 62 or rsi_prev > 65:
                rsi_score = max(rsi_score, 0.7)
            if rsi < rsi_prev and 45 <= rsi <= 68:
                rsi_score = max(rsi_score, 0.9)
        if rsi_score > 0:
            hit('rsi_signal', rsi_score)

        # 5) EMA 状态（方向/交叉）
        ema5 = float(latest.get('EMA5') or 0)
        ema13 = float(latest.get('EMA13') or 0)
        ema5_prev = float(prev.get('EMA5') or 0)
        ema13_prev = float(prev.get('EMA13') or 0)
        ma_score = 0.0
        if ema5 > 0 and ema13 > 0 and ema5_prev > 0 and ema13_prev > 0:
            if side == 'long':
                if ema5 > ema13:
                    ma_score = max(ma_score, 0.6)
                if entry_mode == 'breakout' and ema5_prev <= ema13_prev and ema5 > ema13:
                    ma_score = max(ma_score, 1.0)
            else:
                if ema5 < ema13:
                    ma_score = max(ma_score, 0.6)
                if entry_mode == 'breakout' and ema5_prev >= ema13_prev and ema5 < ema13:
                    ma_score = max(ma_score, 1.0)
        if ma_score > 0:
            hit('ma_state', ma_score)

        # 6) MACD 柱方向
        macd_hist = float(latest.get('MACD_HIST') or 0)
        macd_hist_prev = float(prev.get('MACD_HIST') or 0)
        macd_score = 0.0
        if side == 'long':
            if macd_hist > 0:
                macd_score = max(macd_score, 0.7)
            if macd_hist > macd_hist_prev:
                macd_score = max(macd_score, 0.9)
        else:
            if macd_hist < 0:
                macd_score = max(macd_score, 0.7)
            if macd_hist < macd_hist_prev:
                macd_score = max(macd_score, 0.9)
        if macd_score > 0:
            hit('macd_signal', macd_score)

        # 7) 量能配合（回调缩量 / 突破放量）
        vol = float(latest.get('volume') or 0)
        vol_ma5 = float(latest.get('VOLUME_MA5') or 0)
        vol_score = 0.0
        if vol_ma5 > 0 and vol > 0:
            if entry_mode == 'pullback' and vol < vol_ma5:
                vol_score = 0.7
            if entry_mode == 'breakout' and vol > vol_ma5 * 1.2:
                vol_score = 0.9
        if vol_score > 0:
            hit('volume', vol_score)

        # 8) 波动率（BB宽度 / ATR%）只做加分，避免横盘假信号
        bb_width = float(latest.get('BB_WIDTH') or 0)
        atr_pct = float(latest.get('ATR_PCT') or 0)
        volty_score = 0.0
        if bb_width >= float(getattr(self, 'min_bb_width', 0) or 0):
            volty_score = max(volty_score, 0.6)
        if atr_pct >= float(getattr(self, 'min_atr_pct', 0) or 0):
            volty_score = max(volty_score, 0.6)
        if volty_score > 0:
            hit('volatility', volty_score)

        margin = self._pick_margin_by_score(weighted) if getattr(self, 'use_weighted_positioning', False) else float(getattr(self, 'margin_per_trade', 0) or 0)
        return {'weighted_score': float(weighted), 'hits': hits, 'margin': float(margin)}

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

        strict = 0
        if gap > 0.001 and close > ema21 * 1.001 and prev_gap > 0.0005:
            strict = 1
        elif gap < -0.001 and close < ema21 * 0.999 and prev_gap < -0.0005:
            strict = -1
        if getattr(self, "trend_relaxed", False):
            return 'uptrend' if ema9 >= ema21 else 'downtrend'
        return 'uptrend' if strict == 1 else 'downtrend' if strict == -1 else 'neutral'

    def _check_long_entry_pullback(self, latest: pd.Series, prev: pd.Series, prev2: pd.Series,
                                    df_1m: pd.DataFrame) -> bool:
        """Pine 对齐：回调做多"""
        close = float(latest.get('close') or 0)
        ema13 = float(latest.get('EMA13') or 0)
        bb_mid = float(latest.get('BB_MID') or 0)
        rsi = float(latest.get('RSI', 50) or 50)
        rsi_prev = float(prev.get('RSI', 50) or 50)
        if ema13 <= 0 or bb_mid <= 0 or close <= 0:
            return False

        near_ema = abs(close - ema13) / ema13 < float(getattr(self, "near_dist_pct", 0.008))
        near_bb = abs(close - bb_mid) / bb_mid < float(getattr(self, "near_dist_pct", 0.008))
        prev_closed_down = float(prev.get('close') or 0) < float(prev.get('open') or 0)

        # 20根区间位置（不追高）
        not_at_top = True
        if len(df_1m) >= 20:
            high20 = float(df_1m['high'].iloc[-20:].max())
            low20 = float(df_1m['low'].iloc[-20:].min())
            if high20 > low20:
                pos_in_range = (close - low20) / (high20 - low20)
                not_at_top = pos_in_range < float(getattr(self, "pos_long_max", 0.85))

        vol_pullback_ok = (not getattr(self, "pullback_volume_filter", True)) or (float(latest.get('volume') or 0) < float(latest.get('VOLUME_MA5') or 0))
        return (near_ema or near_bb) and prev_closed_down and (rsi > rsi_prev and self.rsi_long_min <= rsi <= self.rsi_long_max) and not_at_top and vol_pullback_ok

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
        """Pine 对齐：回调做空"""
        close = float(latest.get('close') or 0)
        ema13 = float(latest.get('EMA13') or 0)
        bb_mid = float(latest.get('BB_MID') or 0)
        rsi = float(latest.get('RSI', 50) or 50)
        rsi_prev = float(prev.get('RSI', 50) or 50)
        if ema13 <= 0 or bb_mid <= 0 or close <= 0:
            return False

        near_ema = abs(close - ema13) / ema13 < float(getattr(self, "near_dist_pct", 0.008))
        near_bb = abs(close - bb_mid) / bb_mid < float(getattr(self, "near_dist_pct", 0.008))
        prev_closed_up = float(prev.get('close') or 0) > float(prev.get('open') or 0)

        # 20根区间位置（不抄底）
        not_at_bottom = True
        if len(df_1m) >= 20:
            high20 = float(df_1m['high'].iloc[-20:].max())
            low20 = float(df_1m['low'].iloc[-20:].min())
            if high20 > low20:
                pos_in_range = (close - low20) / (high20 - low20)
                not_at_bottom = pos_in_range > float(getattr(self, "pos_short_min", 0.15))

        vol_pullback_ok = (not getattr(self, "pullback_volume_filter", True)) or (float(latest.get('volume') or 0) < float(latest.get('VOLUME_MA5') or 0))
        return (near_ema or near_bb) and prev_closed_up and (rsi < rsi_prev and self.rsi_short_min <= rsi <= self.rsi_short_max) and not_at_bottom and vol_pullback_ok

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
        """Pine 对齐：tp/sl 用保证金收益%定义，按杠杆换算为价格移动"""
        tp_move = (float(self.tp_pct) / 100.0) / float(self.leverage)
        sl_move = (float(self.sl_pct) / 100.0) / float(self.leverage)
        sl_move = max(sl_move, 0.0001)
        if side == 'long':
            sl_price = entry_price * (1 - sl_move)
            tp_price = entry_price * (1 + tp_move)
        else:
            sl_price = entry_price * (1 + sl_move)
            tp_price = entry_price * (1 - tp_move)
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
        """Pine 对齐：生成入场/出场信号（用同一套过滤与止盈止损规则）。"""
        signals: List[Signal] = []

        for symbol, raw_df in (market_data or {}).items():
            if raw_df is None or len(raw_df) < 120:
                continue

            df_1m = self._calc_1m_indicators(raw_df)
            if df_1m is None or df_1m.empty:
                continue

            now_ts = df_1m.index[-1] if isinstance(df_1m.index, pd.DatetimeIndex) else pd.Timestamp.utcnow()
            day_key = now_ts.strftime("%Y-%m-%d")

            # === 日内风控：单日最大回撤（用账户余额近似 equity）===
            trade_allowed = True
            try:
                if self._day_key != day_key:
                    self._day_key = day_key
                    self._day_start_equity = None
                if self._day_start_equity is None and self.api_client and hasattr(self.api_client, "get_balance"):
                    bal = await self.api_client.get_balance()
                    eq = 0.0
                    if isinstance(bal, dict):
                        for a, amt in bal.items():
                            if str(a).upper() in ("USDC", "USDT", "USD"):
                                eq += float(amt or 0)
                    self._day_start_equity = eq if eq > 0 else None
                if self._day_start_equity is not None and self.api_client and hasattr(self.api_client, "get_balance"):
                    bal = await self.api_client.get_balance()
                    eq = 0.0
                    if isinstance(bal, dict):
                        for a, amt in bal.items():
                            if str(a).upper() in ("USDC", "USDT", "USD"):
                                eq += float(amt or 0)
                    trade_allowed = eq >= float(self._day_start_equity) * (1 - float(self.daily_loss_pct) / 100.0)
            except Exception:
                trade_allowed = True

            # === 趋势：15m + 高周期过滤（60m）===
            df_15m = self._resample_to_15m(df_1m)
            df_15m = self._calc_15m_indicators(df_15m)
            trend = self._get_15m_trend(df_15m)
            if trend == "neutral":
                # Pine 在 trend_relaxed=false 时会 neutral，不入场；但持仓仍可能需要出场管理
                pass

            # HTF2 过滤（默认 60m）
            htf2_ok_long = True
            htf2_ok_short = True
            if getattr(self, "htf_filter", True):
                try:
                    df_h2 = df_1m.resample(f"{int(getattr(self, 'htf2_minutes', 60))}min").agg(
                        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
                    ).dropna()
                    if len(df_h2) >= 25:
                        ema9_h2 = df_h2["close"].ewm(span=self.ema9_period, adjust=False).mean().iloc[-1]
                        ema21_h2 = df_h2["close"].ewm(span=self.ema21_period, adjust=False).mean().iloc[-1]
                        htf2_ok_long = bool(ema9_h2 >= ema21_h2)
                        htf2_ok_short = bool(ema9_h2 < ema21_h2)
                except Exception:
                    pass

            latest = df_1m.iloc[-1]
            prev = df_1m.iloc[-2]
            prev2 = df_1m.iloc[-3]
            close = float(latest.get("close") or 0)
            if close <= 0:
                continue

            # === 当前保证金收益率%（用于保本/追踪/分批）===
            in_pos = symbol in self.positions
            cur_profit_pct = 0.0
            if in_pos:
                pos = self.positions[symbol]
                entry_price = float(pos.entry_price)
                if entry_price > 0:
                    if pos.side == "long":
                        cur_profit_pct = (close - entry_price) / entry_price * self.leverage * 100
                    else:
                        cur_profit_pct = (entry_price - close) / entry_price * self.leverage * 100

                # peak profit
                self._peak_profit_pct[symbol] = max(float(self._peak_profit_pct.get(symbol, 0.0)), float(cur_profit_pct))

                # 追踪回撤止盈
                if getattr(self, "use_trailing_close", False):
                    peak = float(self._peak_profit_pct.get(symbol, 0.0))
                    if peak >= float(self.trail_trigger_pct) and cur_profit_pct <= peak * (1 - float(self.trail_retrace_pct) / 100.0):
                        qty = float(pos.quantity)
                        if qty > 0:
                            signals.append(Signal(symbol=symbol, action=("sell" if pos.side == "long" else "buy"), quantity=qty, price=close, reason="追踪回撤止盈"))
                            self._last_exit_time[symbol] = now_ts
                            continue

                # 时间止损
                et = self._entry_time.get(symbol)
                if et is not None:
                    held_min = (now_ts - et).total_seconds() / 60.0
                    if held_min >= float(self.time_stop_bars):
                        qty = float(pos.quantity)
                        if qty > 0:
                            signals.append(Signal(symbol=symbol, action=("sell" if pos.side == "long" else "buy"), quantity=qty, price=close, reason="时间止损"))
                            self._last_exit_time[symbol] = now_ts
                            continue

                # 15m 趋势反转退出（仅亏损时）
                if pos.side == "long" and trend == "downtrend" and cur_profit_pct < 0:
                    qty = float(pos.quantity)
                    if qty > 0:
                        signals.append(Signal(symbol=symbol, action="sell", quantity=qty, price=close, reason="15m趋势反转(亏损)"))
                        self._last_exit_time[symbol] = now_ts
                        continue
                if pos.side == "short" and trend == "uptrend" and cur_profit_pct < 0:
                    qty = float(pos.quantity)
                    if qty > 0:
                        signals.append(Signal(symbol=symbol, action="buy", quantity=qty, price=close, reason="15m趋势反转(亏损)"))
                        self._last_exit_time[symbol] = now_ts
                        continue

                # 保本：达到阈值后把止损上移到开仓价
                if getattr(self, "move_sl_to_be", True) and cur_profit_pct >= float(self.be_trigger_pct):
                    try:
                        entry_price = float(pos.entry_price)
                        if pos.side == "long":
                            pos.stop_loss = max(float(pos.stop_loss or 0), entry_price) if pos.stop_loss else entry_price
                        else:
                            pos.stop_loss = min(float(pos.stop_loss or entry_price), entry_price) if pos.stop_loss else entry_price
                    except Exception:
                        pass

                # 分批止盈（在 bar close 触发，market 减仓）
                if getattr(self, "use_partial_tp", False) and not bool(self._partial_tp_done.get(symbol, False)):
                    if cur_profit_pct >= float(self.partial_tp_trigger_pct):
                        qty = float(pos.quantity) * float(self.partial_tp_qty_pct) / 100.0
                        qty = max(0.0, qty)
                        if qty > 0:
                            signals.append(Signal(symbol=symbol, action=("sell" if pos.side == "long" else "buy"), quantity=qty, price=close, reason="分批止盈"))
                            self._partial_tp_done[symbol] = True

                # 持仓情况下不再生成开仓信号
                continue

            # === 冷却/最小间隔 ===
            last_exit = self._last_exit_time.get(symbol)
            in_cooldown = False
            if last_exit is not None:
                in_cooldown = (now_ts - last_exit).total_seconds() / 60.0 < float(self.cooldown_bars)
            last_entry = self._last_entry_time.get(symbol)
            entry_spacing_ok = True
            if last_entry is not None:
                entry_spacing_ok = (now_ts - last_entry).total_seconds() / 60.0 >= float(self.min_entry_gap)

            if in_cooldown or (not entry_spacing_ok) or (not trade_allowed):
                continue

            # === 5m 极端波动过滤 ===
            extreme_vol_ok = True
            try:
                df_5m = df_1m.resample("5min").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
                if len(df_5m) >= 1:
                    b = df_5m.iloc[-1]
                    c5 = float(b.get("close") or 0)
                    if c5 > 0:
                        rng = (float(b.get("high") or 0) - float(b.get("low") or 0)) / c5
                        extreme_vol_ok = rng < float(self.extreme_vol_pct) / 100.0
            except Exception:
                pass
            if not extreme_vol_ok:
                continue

            # === ADX/DMI（15m）过滤 ===
            adx_ok = True
            dmi_long_ok = True
            dmi_short_ok = True
            try:
                if getattr(self, "use_adx_filter", True) and len(df_15m) >= 1 and "ADX" in df_15m.columns:
                    adx_ok = float(df_15m["ADX"].iloc[-1]) >= float(self.adx_threshold)
                if getattr(self, "use_dmi_dir_filter", True) and "PDI" in df_15m.columns and "MDI" in df_15m.columns:
                    pdi = float(df_15m["PDI"].iloc[-1])
                    mdi = float(df_15m["MDI"].iloc[-1])
                    dmi_long_ok = pdi > mdi
                    dmi_short_ok = mdi > pdi
            except Exception:
                pass

            # === 1m 指标 ===
            ema5 = float(latest.get("EMA5") or 0)
            ema13 = float(latest.get("EMA13") or 0)
            rsi = float(latest.get("RSI") or 50)
            macd_hist = float(latest.get("MACD_HIST") or 0)
            atr_pct = float(latest.get("ATR_PCT") or 0)
            bb_mid = float(latest.get("BB_MID") or 0)
            bb_upper = float(latest.get("BB_UPPER") or 0)
            bb_lower = float(latest.get("BB_LOWER") or 0)
            bb_width = float(latest.get("BB_WIDTH") or 0)
            vol_ma5 = float(latest.get("VOLUME_MA5") or 0)
            vol = float(latest.get("volume") or 0)

            ema_dir_long = (not getattr(self, "trend_ema_filter", True)) or (ema5 > ema13)
            ema_dir_short = (not getattr(self, "trend_ema_filter", True)) or (ema5 < ema13)
            bb_ok = bb_width >= float(self.min_bb_width)
            volatility_ok = (atr_pct >= float(self.min_atr_pct)) and (atr_pct <= float(self.max_atr_pct))

            vol_confirm = vol_ma5 > 0 and vol > vol_ma5
            rsi_slope_ok_long = rsi > float(prev.get("RSI", rsi) or rsi)
            rsi_slope_ok_short = rsi < float(prev.get("RSI", rsi) or rsi)
            macd_dir_long = macd_hist > 0
            macd_dir_short = macd_hist < 0

            extra_long_ok = (not getattr(self, "use_macd_filter", True) or macd_dir_long) and (not getattr(self, "use_rsi_slope", True) or rsi_slope_ok_long) and (not getattr(self, "use_volume_confirm", False) or vol_confirm)
            extra_short_ok = (not getattr(self, "use_macd_filter", True) or macd_dir_short) and (not getattr(self, "use_rsi_slope", True) or rsi_slope_ok_short) and (not getattr(self, "use_volume_confirm", False) or vol_confirm)

            # 20根区间位置
            not_at_top = True
            not_at_bottom = True
            if len(df_1m) >= 20:
                high20 = float(df_1m["high"].iloc[-20:].max())
                low20 = float(df_1m["low"].iloc[-20:].min())
                if high20 > low20:
                    pos_in_range = (close - low20) / (high20 - low20)
                    not_at_top = pos_in_range < float(self.pos_long_max)
                    not_at_bottom = pos_in_range > float(self.pos_short_min)

            # 回调
            near_ema = ema13 > 0 and abs(close - ema13) / ema13 < float(self.near_dist_pct)
            near_bb = bb_mid > 0 and abs(close - bb_mid) / bb_mid < float(self.near_dist_pct)
            prev_closed_down = float(prev.get("close") or 0) < float(prev.get("open") or 0)
            prev_closed_up = float(prev.get("close") or 0) > float(prev.get("open") or 0)
            vol_pullback_ok = (not getattr(self, "pullback_volume_filter", True)) or (vol_ma5 > 0 and vol < vol_ma5)

            long_pullback = (near_ema or near_bb) and prev_closed_down and (rsi > float(prev.get("RSI", rsi) or rsi) and self.rsi_long_min <= rsi <= self.rsi_long_max) and not_at_top and vol_pullback_ok
            short_pullback = (near_ema or near_bb) and prev_closed_up and (rsi < float(prev.get("RSI", rsi) or rsi) and self.rsi_short_min <= rsi <= self.rsi_short_max) and not_at_bottom and vol_pullback_ok

            # 突破
            golden_cross = float(prev.get("EMA5") or ema5) <= float(prev.get("EMA13") or ema13) and ema5 > ema13
            death_cross = float(prev.get("EMA5") or ema5) >= float(prev.get("EMA13") or ema13) and ema5 < ema13
            long_breakout = bb_upper > 0 and close >= bb_upper * 0.998 and golden_cross and rsi > 55 and (vol_ma5 > 0 and vol > vol_ma5 * 1.2)
            short_breakout = bb_lower > 0 and close <= bb_lower * 1.002 and death_cross and rsi < 45 and (vol_ma5 > 0 and vol > vol_ma5 * 1.2)

            # 入场条件（Pine）
            long_entry = adx_ok and dmi_long_ok and (trend == "uptrend") and ema_dir_long and bb_ok and volatility_ok and extra_long_ok and htf2_ok_long and (long_pullback or (getattr(self, "use_breakout_mode", False) and long_breakout))
            short_entry = adx_ok and dmi_short_ok and (trend == "downtrend") and ema_dir_short and bb_ok and volatility_ok and extra_short_ok and htf2_ok_short and (short_pullback or (getattr(self, "use_breakout_mode", False) and short_breakout))

            # 评分/分档保证金（Pine：只有满足入场形态才会加 pattern）
            # 为了 100% 对齐 TV，我们直接复用你 Pine 的 scoring 结构（趋势/形态/位置/RSI/MA/MACD/量能/波动）
            long_score = None
            short_score = None
            try:
                long_score = self._calc_weighted_entry_score(side="long", trend="uptrend", latest=latest, prev=prev, prev2=prev2, df_1m=df_1m, entry_mode=("breakout" if long_breakout else "pullback"))["weighted_score"]
                short_score = self._calc_weighted_entry_score(side="short", trend="downtrend", latest=latest, prev=prev, prev2=prev2, df_1m=df_1m, entry_mode=("breakout" if short_breakout else "pullback"))["weighted_score"]
            except Exception:
                long_score = 0.0
                short_score = 0.0

            if long_entry and (not self.use_weighted_positioning or float(long_score) >= float(self.min_weighted_score)):
                margin_use = self._pick_margin_by_score(float(long_score)) if self.use_weighted_positioning else float(self.margin_per_trade)
                if margin_use <= 0:
                    continue
                qty = (margin_use * float(self.leverage)) / close
                tp_px, sl_px = self.get_stop_take_profit_prices(close, "long")
                signals.append(Signal(symbol=symbol, action="buy", quantity=qty, price=close, stop_loss=sl_px, take_profit=tp_px, reason=f"多头入场 | score={float(long_score):.2f} margin={margin_use:.2f}"))
                self._last_entry_time[symbol] = now_ts
                self._entry_time[symbol] = now_ts
                self._peak_profit_pct[symbol] = 0.0
                self._partial_tp_done[symbol] = False
                continue

            if short_entry and (not self.use_weighted_positioning or float(short_score) >= float(self.min_weighted_score)):
                margin_use = self._pick_margin_by_score(float(short_score)) if self.use_weighted_positioning else float(self.margin_per_trade)
                if margin_use <= 0:
                    continue
                qty = (margin_use * float(self.leverage)) / close
                tp_px, sl_px = self.get_stop_take_profit_prices(close, "short")
                signals.append(Signal(symbol=symbol, action="sell", quantity=qty, price=close, stop_loss=sl_px, take_profit=tp_px, reason=f"空头入场 | score={float(short_score):.2f} margin={margin_use:.2f}"))
                self._last_entry_time[symbol] = now_ts
                self._entry_time[symbol] = now_ts
                self._peak_profit_pct[symbol] = 0.0
                self._partial_tp_done[symbol] = False
                continue

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
