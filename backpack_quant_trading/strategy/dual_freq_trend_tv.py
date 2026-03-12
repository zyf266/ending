"""
双频趋势共振策略 - TradingView 版（与 test Pine 脚本对齐）
- 仅做多，无做空
- 15m 趋势（EMA9/21 + 60m 过滤）+ 1m 入场（回调 / 大单被吃）
- 止盈止损按保证金% × 杠杆换算价格，时间止损、15m 趋势反转平仓
"""

from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np
from datetime import datetime
from decimal import Decimal

from .base import BaseStrategy, Signal, Position


class DualFreqTrendTVStrategy(BaseStrategy):
    """双频趋势共振 - TV 版（long only，与 test 对齐）"""

    def __init__(
        self,
        symbols: List[str],
        api_client=None,
        risk_manager=None,
        *,
        leverage: int = 100,
        margin_per_trade: float = 10.0,
        tp_pct: float = 150.0,
        sl_pct: float = 50.0,
        time_stop_bars: int = 6,
        cooldown_bars: int = 6,
        min_entry_gap: int = 6,
        use_big_order_eaten: bool = True,
        big_order_vol_mul: float = 2.0,
        big_order_close_ratio: float = 0.6,
        daily_loss_pct: float = 5.0,
        params: Optional[Dict] = None,
    ):
        super().__init__("DualFreqTrendTV", symbols, api_client, risk_manager)

        self.leverage = leverage
        self.margin_per_trade = margin_per_trade
        self.tp_pct = tp_pct
        self.sl_pct = sl_pct
        self.time_stop_bars = time_stop_bars  # 1m 根数 = 分钟数
        self.cooldown_bars = cooldown_bars
        self.min_entry_gap = min_entry_gap
        self.use_big_order_eaten = use_big_order_eaten
        self.big_order_vol_mul = big_order_vol_mul
        self.big_order_close_ratio = big_order_close_ratio
        self.daily_loss_pct = daily_loss_pct

        self.ema9_period = 9
        self.ema21_period = 21
        self.ema5_period = 5
        self.ema13_period = 13
        self.rsi_period = 6
        self.bb_period = 20
        self.bb_std = 2.0
        self.rsi_long_min = 32
        self.rsi_long_max = 55
        self.trend_ema_filter = True
        self.trend_relaxed = True
        self.htf_filter = True
        self.htf2_minutes = 60
        self.min_bb_width = 0.004
        self.min_atr_pct = 0.001
        self.extreme_vol_pct = 1.0
        self.pullback_volume_filter = True
        self.use_macd_filter = True
        self.use_rsi_slope = True
        self.use_volume_confirm = False
        self.use_htf_rsi = False
        self.htf_rsi_min = 45
        self.near_dist_pct = 0.015  # Pine near_ema / near_bb
        self.use_breakout_mode = False

        self._day_start_equity: Optional[float] = None
        self._day_key: Optional[str] = None
        self._last_exit_bar: Dict[str, int] = {}
        self._last_entry_bar: Dict[str, int] = {}
        self._entry_bar: Dict[str, Optional[int]] = {}

        if params:
            for k, v in params.items():
                if hasattr(self, k):
                    setattr(self, k, v)

    def _resample_15m(self, df_1m: pd.DataFrame) -> pd.DataFrame:
        if df_1m.empty or len(df_1m) < 20:
            return pd.DataFrame()
        return df_1m.resample("15min").agg({
            "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
        }).dropna()

    def _resample_60m(self, df_1m: pd.DataFrame) -> pd.DataFrame:
        if df_1m.empty or len(df_1m) < 25:
            return pd.DataFrame()
        return df_1m.resample("60min").agg({
            "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
        }).dropna()

    def calculate_technical_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """1m 指标：EMA5/13, RSI6, 布林, MACD, ATR%, BB_WIDTH, VOLUME_MA5"""
        if len(df) < 25:
            return df
        d = df.copy()
        d["EMA5"] = d["close"].ewm(span=self.ema5_period, adjust=False).mean()
        d["EMA13"] = d["close"].ewm(span=self.ema13_period, adjust=False).mean()
        delta = d["close"].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        avg_gain = gain.rolling(self.rsi_period).mean()
        avg_loss = loss.rolling(self.rsi_period).mean()
        rs = np.where(avg_loss > 0, avg_gain / avg_loss, 10.0)
        d["RSI"] = 100 - (100 / (1 + rs))
        d["BB_MID"] = d["close"].rolling(self.bb_period).mean()
        bb_std_val = d["close"].rolling(self.bb_period).std()
        d["BB_UPPER"] = d["BB_MID"] + self.bb_std * bb_std_val
        d["BB_LOWER"] = d["BB_MID"] - self.bb_std * bb_std_val
        d["BB_WIDTH"] = (d["BB_UPPER"] - d["BB_LOWER"]) / d["BB_MID"].replace(0, np.nan)
        d["VOLUME_MA5"] = d["volume"].rolling(5).mean()
        ema12 = d["close"].ewm(span=12, adjust=False).mean()
        ema26 = d["close"].ewm(span=26, adjust=False).mean()
        d["MACD_HIST"] = ema12 - ema26 - (ema12 - ema26).ewm(span=9, adjust=False).mean()
        tr = pd.concat([
            d["high"] - d["low"],
            (d["high"] - d["close"].shift(1)).abs(),
            (d["low"] - d["close"].shift(1)).abs(),
        ], axis=1).max(axis=1)
        d["ATR_PCT"] = tr.rolling(14).mean() / d["close"]
        return d

    def _get_15m_trend(self, df_15m: pd.DataFrame) -> int:
        """1=uptrend, -1=downtrend"""
        if len(df_15m) < 3:
            return 0
        df_15m = df_15m.copy()
        df_15m["EMA9"] = df_15m["close"].ewm(span=self.ema9_period, adjust=False).mean()
        df_15m["EMA21"] = df_15m["close"].ewm(span=self.ema21_period, adjust=False).mean()
        last = df_15m.iloc[-1]
        prev = df_15m.iloc[-2]
        ema9, ema21 = last["EMA9"], last["EMA21"]
        close = last["close"]
        if pd.isna(ema9) or pd.isna(ema21) or ema21 <= 0:
            return 0
        gap = (ema9 - ema21) / ema21
        prev_gap = (prev["EMA9"] - prev["EMA21"]) / prev["EMA21"] if prev["EMA21"] > 0 else 0
        if not self.trend_relaxed:
            if gap > 0.001 and close > ema21 * 1.001 and prev_gap > 0.0005:
                return 1
            if gap < -0.001 and close < ema21 * 0.999 and prev_gap < -0.0005:
                return -1
            return 0
        return 1 if ema9 >= ema21 else -1

    def _htf2_up(self, df_1m: pd.DataFrame) -> bool:
        if not self.htf_filter or len(df_1m) < 60:
            return True
        df_h = self._resample_60m(df_1m)
        if len(df_h) < 25:
            return True
        ema9 = df_h["close"].ewm(span=self.ema9_period, adjust=False).mean().iloc[-1]
        ema21 = df_h["close"].ewm(span=self.ema21_period, adjust=False).mean().iloc[-1]
        return bool(ema9 >= ema21)

    def get_stop_take_profit_prices(self, entry_price: float, side: str) -> Tuple[float, float]:
        tp_move = (self.tp_pct / 100.0) / self.leverage
        sl_move = max((self.sl_pct / 100.0) / self.leverage, 0.0001)
        if side == "long":
            return entry_price * (1 + tp_move), entry_price * (1 - sl_move)
        return entry_price * (1 - tp_move), entry_price * (1 + sl_move)

    def check_long_exit_conditions(self, df: pd.DataFrame, position: Dict) -> Tuple[bool, str]:
        if len(df) < 2:
            return False, ""
        latest = df.iloc[-1]
        price = float(latest["close"])
        entry_price = float(position["entry_price"])
        entry_time = position.get("entry_time")
        current_time = position.get("current_time", df.index[-1])

        pnl_pct = (price - entry_price) / entry_price * self.leverage * 100
        if pnl_pct >= self.tp_pct:
            return True, f"止盈({pnl_pct:.1f}%)"
        if pnl_pct <= -self.sl_pct:
            return True, f"止损({pnl_pct:.1f}%)"

        if entry_time is not None and current_time is not None:
            try:
                entry_ts = pd.Timestamp(entry_time)
                curr_ts = pd.Timestamp(current_time)
                minutes = (curr_ts - entry_ts).total_seconds() / 60.0
                if minutes >= self.time_stop_bars:
                    return True, f"时间止损({minutes:.0f}min)"
            except Exception:
                pass

        df_15m = self._resample_15m(df)
        if len(df_15m) >= 3:
            trend = self._get_15m_trend(df_15m)
            if trend == -1:
                return True, "15m趋势反转"
        return False, ""

    async def calculate_signal(self, market_data: Dict[str, pd.DataFrame]) -> List[Signal]:
        signals: List[Signal] = []
        for symbol, raw in (market_data or {}).items():
            if raw is None or len(raw) < 120:
                continue
            df = self.calculate_technical_indicators(raw)
            if df.empty or "RSI" not in df.columns:
                continue

            now = df.index[-1] if isinstance(df.index, pd.DatetimeIndex) else pd.Timestamp.utcnow()
            day_key = now.strftime("%Y-%m-%d")
            bar_idx = len(df) - 1

            trade_allowed = True
            if self._day_key != day_key:
                self._day_key = day_key
                self._day_start_equity = None
            if self.api_client and hasattr(self.api_client, "get_balance"):
                try:
                    bal = await self.api_client.get_balance()
                    eq = 0.0
                    if isinstance(bal, dict):
                        for a, amt in bal.items():
                            if str(a).upper() in ("USDC", "USDT", "USD"):
                                eq += float(amt or 0)
                    if self._day_start_equity is None and eq > 0:
                        self._day_start_equity = eq
                    if self._day_start_equity is not None:
                        trade_allowed = eq >= self._day_start_equity * (1 - self.daily_loss_pct / 100.0)
                except Exception:
                    pass

            df_15m = self._resample_15m(df)
            trend = self._get_15m_trend(df_15m)
            htf2_ok = self._htf2_up(df)

            last_exit = self._last_exit_bar.get(symbol, -999)
            last_entry = self._last_entry_bar.get(symbol, -999)
            in_cooldown = (bar_idx - last_exit) < self.cooldown_bars
            entry_spacing_ok = (bar_idx - last_entry) >= self.min_entry_gap
            if in_cooldown or not entry_spacing_ok or not trade_allowed:
                continue

            try:
                df_5m = df.resample("5min").agg({"high": "max", "low": "min", "close": "last"}).dropna()
                if len(df_5m) >= 1:
                    r = df_5m.iloc[-1]
                    c = float(r["close"]) or 1
                    rng = (float(r["high"]) - float(r["low"])) / c
                    if rng >= self.extreme_vol_pct / 100.0:
                        continue
            except Exception:
                pass

            latest = df.iloc[-1]
            prev = df.iloc[-2]
            close = float(latest["close"])
            if close <= 0:
                continue

            ema5 = float(latest.get("EMA5") or 0)
            ema13 = float(latest.get("EMA13") or 0)
            rsi = float(latest.get("RSI") or 50)
            rsi_prev = float(prev.get("RSI") or 50)
            bb_width = float(latest.get("BB_WIDTH") or 0)
            atr_pct = float(latest.get("ATR_PCT") or 0)
            vol_ma5 = float(latest.get("VOLUME_MA5") or 0)
            vol = float(latest.get("volume") or 0)
            macd_hist = float(latest.get("MACD_HIST") or 0)
            bb_mid = float(latest.get("BB_MID") or 0)
            bb_upper = float(latest.get("BB_UPPER") or 0)

            near_ema = ema13 > 0 and abs(close - ema13) / ema13 < self.near_dist_pct
            near_bb = bb_mid > 0 and abs(close - bb_mid) / bb_mid < self.near_dist_pct
            vol_pullback_ok = (not self.pullback_volume_filter) or (vol_ma5 > 0 and vol < vol_ma5)
            not_at_top = True
            if len(df) >= 20:
                high20 = df["high"].iloc[-20:].max()
                low20 = df["low"].iloc[-20:].min()
                if high20 > low20:
                    pos_in_range = (close - low20) / (high20 - low20)
                    not_at_top = pos_in_range < 0.995

            long_pullback = (
                (near_ema or near_bb)
                and (rsi > rsi_prev and self.rsi_long_min <= rsi <= self.rsi_long_max)
                and not_at_top
                and vol_pullback_ok
            )
            golden_cross = (float(prev.get("EMA5") or 0) <= float(prev.get("EMA13") or 0)) and (ema5 > ema13)
            long_breakout = (
                bb_upper > 0
                and close >= bb_upper * 0.998
                and golden_cross
                and rsi > 55
                and vol_ma5 > 0
                and vol > vol_ma5 * 1.2
            )
            high_, low_ = float(latest["high"]), float(latest["low"])
            range_up = (close - low_) / (high_ - low_) if (high_ > low_) else 0.5
            big_vol = vol_ma5 > 0 and vol > vol_ma5 * self.big_order_vol_mul
            big_buy_eaten = big_vol and close > float(latest["open"]) and range_up >= self.big_order_close_ratio

            ema_dir_long = (not self.trend_ema_filter) or (ema5 > ema13)
            bb_ok = bb_width >= self.min_bb_width
            volatility_ok = atr_pct >= self.min_atr_pct
            vol_confirm = vol_ma5 > 0 and vol > vol_ma5
            rsi_slope_ok = rsi > rsi_prev
            macd_ok = (not self.use_macd_filter) or (macd_hist > 0)
            htf_rsi_ok = (not self.use_htf_rsi) or True
            extra_long_ok = macd_ok and (not self.use_rsi_slope or rsi_slope_ok) and (not self.use_volume_confirm or vol_confirm) and htf_rsi_ok

            long_entry = (
                trend == 1
                and ema_dir_long
                and bb_ok
                and volatility_ok
                and extra_long_ok
                and (not self.htf_filter or htf2_ok)
                and (
                    long_pullback
                    or (self.use_breakout_mode and long_breakout)
                    or (self.use_big_order_eaten and big_buy_eaten and self.rsi_long_min <= rsi <= self.rsi_long_max)
                )
            )
            if not long_entry:
                continue

            qty = (self.margin_per_trade * self.leverage) / close
            tp_px, sl_px = self.get_stop_take_profit_prices(close, "long")
            sig = Signal(
                symbol=symbol,
                action="buy",
                quantity=qty,
                price=close,
                stop_loss=sl_px,
                take_profit=tp_px,
                reason="多头入场",
            )
            signals.append(sig)
            self._last_entry_bar[symbol] = bar_idx
            self._entry_bar[symbol] = bar_idx
        return signals

    def should_exit_position(self, position: Position, current_data: pd.Series) -> bool:
        df = pd.DataFrame([current_data])
        pos_dict = {
            "symbol": position.symbol,
            "side": position.side,
            "entry_price": position.entry_price,
            "quantity": position.quantity,
            "current_price": position.current_price,
        }
        return self.check_long_exit_conditions(df, pos_dict)[0]
