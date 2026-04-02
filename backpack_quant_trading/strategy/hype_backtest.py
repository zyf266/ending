"""
HYPE 自适应做空策略回测脚本 (与 TradingView Pine Script 完全一致)

回测逻辑：
- 入场：4H MACD 死叉 AND 价格跌破日线 WMA15 → 下一根 K 线开盘价入场
- 出场：MACD 金叉 / 止损 3% / 止盈 6%
- 保本：盈利≥3%时，止损移动到成本价

关键修正：
1. 信号在 K 线收盘时判断，入场在下一根 K 线开盘价
2. 止盈止损用 K 线内的最高/最低价判断
"""

import sys
import time
import requests
from datetime import datetime, timedelta, timezone

# UTC+8 时区（与 TradingView 显示一致）
TZ_CST = timezone(timedelta(hours=8))

def _ts_to_cst(ts_ms: int) -> datetime:
    """毫秒时间戳转换为 UTC+8 时间"""
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).astimezone(TZ_CST)
from typing import List, Optional, Tuple
import pandas as pd
import numpy as np

sys.path.insert(0, r'c:\Users\A1\PycharmProjects\PythonProject - 副本')

# 币安合约API
BINANCE_API_BASE = "https://fapi.binance.com"

INTERVAL_MS = {
    "1h": 3600 * 1000,
    "2h": 2 * 3600 * 1000,
    "4h": 4 * 3600 * 1000,
    "1d": 24 * 3600 * 1000,
}

def fetch_binance_klines(
    symbol: str,
    interval: str,
    start_time_ms: int,
    end_time_ms: Optional[int] = None,
    batch_size: int = 1000,
) -> List[dict]:
    """币安K线获取"""
    result = []
    url = f"{BINANCE_API_BASE}/fapi/v1/klines"
    symbol = symbol.upper()
    interval_ms = INTERVAL_MS.get(interval.lower(), 2 * 3600 * 1000)
    current_start = start_time_ms
    end_ts = end_time_ms or (int(time.time()) * 1000)

    while current_start < end_ts:
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": batch_size,
            "startTime": current_start,
        }
        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if not data:
                break
            for bar in data:
                t = int(bar[0])
                if t >= end_ts:
                    break
                result.append({
                    "time": t,
                    "open": float(bar[1]),
                    "high": float(bar[2]),
                    "low": float(bar[3]),
                    "close": float(bar[4]),
                    "volume": float(bar[5]),
                })
            if len(data) < batch_size:
                break
            current_start = int(data[-1][0]) + interval_ms
            time.sleep(0.3)
        except Exception as e:
            print(f"  ❌ 币安API错误: {e}")
            break
    return result

class HYPEBacktest:
    """HYPE 自适应做空策略回测"""
    
    def __init__(
        self,
        symbol: str = "ETH",
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
        wma_len: int = 15,
        stop_loss_pct: float = 0.03,
        take_profit_pct: float = 0.06,
        break_even_pct: float = 0.03,
        exit_tf: str = "2h",  # 离场参考周期 (TradingView: exitTF)
    ):
        self.symbol = symbol
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.wma_len = wma_len
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.break_even_pct = break_even_pct
        self.exit_tf = exit_tf
        
        self.klines_2h: List = []  # 进场信号周期K线
        self.klines_daily: List = []
        self.klines_exit: List = []  # 离场周期K线 (1h)
        self.trades = []
        
    def fetch_data(self, count_2h: int = 3000, count_daily: int = 500):
        """获取历史K线数据（固定从2025-01-01开始，与TradingView回测时间范围一致）
        使用币安合约API作为数据源
        进场：2H K线
        离场：1H K线
        """
        print(f"📥 正在获取 {self.symbol}USDT 历史K线数据 (币安合约)...")
        
        # 固定起始时间：2025-01-01 00:00 UTC（与TradingView一致）
        START_TS = int(datetime(2025, 1, 1, 0, 0, 0).timestamp() * 1000)
        # 日线需要多取一段历史（WMA15需要至少15根日线，往前多取60天）
        DAILY_START_TS = int(datetime(2024, 11, 1, 0, 0, 0).timestamp() * 1000)
        
        # 币安交易对格式：ETHUSDT
        binance_symbol = f"{self.symbol}USDT"
        
        # 获取 2H K线（进场信号周期）
        print(f"  ⏳ 获取 2H K线（进场周期）...")
        try:
            data_2h = fetch_binance_klines(
                symbol=binance_symbol,
                interval="2h",
                start_time_ms=START_TS,
            )
            if data_2h:
                for k in data_2h:
                    self.klines_2h.append([
                        int(k['time']),
                        float(k['open']),
                        float(k['high']),
                        float(k['low']),
                        float(k['close']),
                        float(k['volume'])
                    ])
                print(f"  ✅ 2H K线: {len(self.klines_2h)} 根")
        except Exception as e:
            print(f"  ❌ 获取 2H K线失败: {e}")
        
        # 获取日线 K线
        print(f"  ⏳ 获取日线 K线...")
        try:
            data_daily = fetch_binance_klines(
                symbol=binance_symbol,
                interval="1d",
                start_time_ms=DAILY_START_TS,
            )
            if data_daily:
                for k in data_daily:
                    self.klines_daily.append([
                        int(k['time']),
                        float(k['open']),
                        float(k['high']),
                        float(k['low']),
                        float(k['close']),
                        float(k['volume'])
                    ])
                print(f"  ✅ 日线 K线: {len(self.klines_daily)} 根")
        except Exception as e:
            print(f"  ❌ 获取日线 K线失败: {e}")
        
        # 获取离场周期 K线 (默认 2h)
        print(f"  ⏳ 获取 {self.exit_tf} K线 (离场周期)...")
        try:
            data_exit = fetch_binance_klines(
                symbol=binance_symbol,
                interval=self.exit_tf,
                start_time_ms=START_TS,
            )
            if data_exit:
                for k in data_exit:
                    self.klines_exit.append([
                        int(k['time']),
                        float(k['open']),
                        float(k['high']),
                        float(k['low']),
                        float(k['close']),
                        float(k['volume'])
                    ])
                print(f"  ✅ {self.exit_tf} K线: {len(self.klines_exit)} 根")
        except Exception as e:
            print(f"  ❌ 获取 {self.exit_tf} K线失败: {e}")
        
        # 按时间排序（从旧到新）
        self.klines_2h.sort(key=lambda x: x[0])
        self.klines_daily.sort(key=lambda x: x[0])
        self.klines_exit.sort(key=lambda x: x[0])
        
        if len(self.klines_2h) > count_2h:
            self.klines_2h = self.klines_2h[-count_2h:]
        if len(self.klines_daily) > count_daily:
            self.klines_daily = self.klines_daily[-count_daily:]
        
        if self.klines_2h:
            start_time = _ts_to_cst(self.klines_2h[0][0])
            end_time = _ts_to_cst(self.klines_2h[-1][0])
            print(f"  📅 时间范围: {start_time.strftime('%Y-%m-%d')} ~ {end_time.strftime('%Y-%m-%d')}")
    
    def _ema(self, data: List[float], period: int) -> List[float]:
        """计算 EMA (与 Pine Script ta.ema 一致)"""
        if len(data) < period:
            return []
        
        result = []
        alpha = 2 / (period + 1)
        
        # 初始值使用 SMA
        sma = sum(data[:period]) / period
        result.append(sma)
        
        for i in range(period, len(data)):
            ema = alpha * data[i] + (1 - alpha) * result[-1]
            result.append(ema)
        
        return result
    
    def _calculate_macd(self, closes: List[float]) -> Tuple[List[float], List[float], List[float]]:
        """计算 MACD"""
        if len(closes) < self.macd_slow + self.macd_signal:
            return [], [], []
        
        ema_fast = self._ema(closes, self.macd_fast)
        ema_slow = self._ema(closes, self.macd_slow)
        
        if not ema_fast or not ema_slow:
            return [], [], []
        
        # 对齐长度
        offset = len(ema_fast) - len(ema_slow)
        ema_fast = ema_fast[offset:]
        
        # MACD 线
        macd_line = [ema_fast[i] - ema_slow[i] for i in range(len(ema_slow))]
        
        # 信号线
        signal_line = self._ema(macd_line, self.macd_signal)
        
        if not signal_line:
            return macd_line, [], []
        
        offset2 = len(macd_line) - len(signal_line)
        macd_line = macd_line[offset2:]
        
        return macd_line, signal_line, []
    
    def _wma(self, data: List[float], period: int) -> Optional[float]:
        """计算 WMA (与 Pine Script ta.wma 一致)"""
        if len(data) < period:
            return None
        
        weights = list(range(1, period + 1))
        total_weight = sum(weights)
        weighted_sum = sum(data[-period:][i] * weights[i] for i in range(period))
        return weighted_sum / total_weight
    
    def _get_daily_wma(self, timestamp: int) -> Optional[float]:
        """获取对应时间点的日线 WMA（使用已完成的日线）
        
        TradingView: ta.wma(close, wmaLen)[1] - 使用上一根已完成日线计算 WMA
        
        关键：时间戳是K线开始时间，当天日线开始时间 < 当前时间戳，会被包含进来
        所以需要 [:-1] 排除当天正在进行的日线（未完成）
        """
        ts_ms = timestamp
        daily_closes = []
        
        for k in self.klines_daily:
            # 日线开始时间 < 当前时间戳
            # 这会包含：之前所有已完成的日线 + 当天正在进行中的日线（如果有的话）
            if k[0] < ts_ms:
                daily_closes.append(k[4])
        
        if len(daily_closes) < self.wma_len + 1:
            # 至少需要 wma_len + 1 根（因为要排除最后一根）
            return None
        
        # 排除最后一根（可能是当天未完成的日线），使用最近 wma_len 根已完成日线
        return self._wma(daily_closes[-(self.wma_len + 1):-1], self.wma_len)
    
    def run_backtest(self, initial_capital: float = 10000.0):
        """运行回测"""
        print(f"\n{'='*60}")
        print(f"🔄 开始回测...")
        print(f"{'='*60}")
        print(f"📊 参数设置:")
        print(f"   交易对: {self.symbol}")
        print(f"   MACD: 快线={self.macd_fast}, 慢线={self.macd_slow}, 信号={self.macd_signal}")
        print(f"   日线WMA: {self.wma_len}")
        print(f"   离场周期: {self.exit_tf}")
        print(f"   止损: {self.stop_loss_pct*100:.1f}%")
        print(f"   止盈: {self.take_profit_pct*100:.1f}%")
        print(f"   保本触发: {self.break_even_pct*100:.1f}%")
        print(f"   初始资金: ${initial_capital:.2f}")
        print(f"{'='*60}\n")
        
        if len(self.klines_2h) < 50:
            print("❌ 4H K线数据不足")
            return
        
        if len(self.klines_exit) < 50:
            print(f"❌ {self.exit_tf} K线数据不足")
            return
        
        # 计算 4H MACD (入场信号用)
        closes = [k[4] for k in self.klines_2h]
        macd_line, signal_line, _ = self._calculate_macd(closes)
        
        if len(macd_line) < 10:
            print("❌ 4H MACD 计算失败")
            return
        
        # 计算离场周期 MACD (离场信号用)
        exit_closes = [k[4] for k in self.klines_exit]
        exit_macd_line, exit_signal_line, _ = self._calculate_macd(exit_closes)
        
        if len(exit_macd_line) < 10:
            print(f"❌ {self.exit_tf} MACD 计算失败")
            return
        
        # 建立离场周期 MACD 映射表：K线时间戳 -> (macd, signal)
        exit_macd_map = {}
        exit_offset = len(self.klines_exit) - len(exit_macd_line)
        for _idx in range(exit_offset, len(self.klines_exit)):
            _ts = self.klines_exit[_idx][0]
            _macd_idx = _idx - exit_offset
            exit_macd_map[_ts] = (exit_macd_line[_macd_idx], exit_signal_line[_macd_idx])
        exit_ts_list = sorted(exit_macd_map.keys())
        
        # 状态变量
        capital = initial_capital
        position = None
        entry_price = 0.0
        entry_idx = 0
        stop_loss = 0.0
        take_profit = 0.0
        break_even_activated = False
        pending_entry = False  # 挂单入场标记
        
        # 信号统计
        short_signals = 0  # MACD 死叉次数
        price_signals = 0  # 跌破 WMA 次数
        valid_short_signals = 0  # 满足任一条件的次数
        
        # 对齐 MACD 和 K 线的起始位置
        macd_offset = len(self.klines_2h) - len(macd_line)
        
        for i in range(macd_offset + 2, len(self.klines_2h)):
            kline = self.klines_2h[i]
            timestamp, open_p, high, low, close, volume = kline
            
            macd_idx = i - macd_offset
            if macd_idx < 2:
                continue
            
            # TV: get_macd_data() 返回 [m[1], s[1]]，即上一根K线的MACD
            # 所以 ta.crossunder(m4h, s4h) 检测的是 K线(i-2) 和 K线(i-1) 之间的穿越
            m_now = macd_line[macd_idx - 1]   # 对应TV的当前m4h = 上一根K线的MACD
            s_now = signal_line[macd_idx - 1] # 对应TV的当前s4h = 上一根K线的Signal
            m_prev = macd_line[macd_idx - 2]  # 对应TV的上一根m4h = 上上根K线的MACD
            s_prev = signal_line[macd_idx - 2] # 对应TV的上一根s4h = 上上根K线的Signal
            
            daily_wma = self._get_daily_wma(timestamp)
            
            # ========== 处理挂单入场（下一根开盘价入场）==========
            if pending_entry and position is None:
                position = 'SHORT'
                entry_price = open_p  # 开盘价入场
                entry_idx = i
                stop_loss = entry_price * (1 + self.stop_loss_pct)
                take_profit = entry_price * (1 - self.take_profit_pct)
                break_even_activated = False
                pending_entry = False
                
                dt = _ts_to_cst(timestamp)
                print(f"🐻 开空 @ {dt.strftime('%Y-%m-%d %H:%M')} | 开盘价: {entry_price:.2f}")
                continue  # 入场当根不检查止损止盈
            
            # ========== 检查做空信号 ==========
            # TradingView: shortCondition = (ta.crossunder(m4h, s4h) or ta.crossunder(close, dailyWMA))
            # TV: get_macd_data() 返回 [m[1], s[1]]，即上一根K线的MACD
            # 所以 ta.crossunder(m4h, s4h) 检测的是 K线(N-2) 和 K线(N-1) 之间的穿越
            
            # 1. MACD 死叉
            macd_crossunder = m_prev >= s_prev and m_now < s_now
            
            # 2. 价格跌破 WMA (穿越)
            # TV: ta.crossunder(close, dailyWMA) - 当前K线收盘价穿越WMA
            # dailyWMA = request.security(..., ta.wma(close, wmaLen)[1], lookahead=barmerge.lookahead_off)
            # 注意：dailyWMA 也用了 [1]，即上一根日线的WMA值
            # 所以穿越检测是：上一根4H收盘价 vs 上一根日线WMA，当前4H收盘价 vs 当前日线WMA
            prev_close = self.klines_2h[i-1][4]  # 上一根4H K线收盘价
            # 获取上一根4H K线对应的日线WMA（用上一根日线的收盘价计算）
            prev_daily_wma = self._get_daily_wma(self.klines_2h[i-1][0])
            
            # 穿越: 上一根收盘价 >= WMA 且 当前收盘价 < WMA
            price_crossunder_wma = (
                daily_wma is not None and prev_daily_wma is not None and
                prev_close >= prev_daily_wma and close < daily_wma
            )
            
            # 信号统计
            if macd_crossunder:
                short_signals += 1
            if price_crossunder_wma:
                price_signals += 1
            
            # ========== 空仓状态：信号触发，下一根开盘价入场 ==========
            if position is None:
                if macd_crossunder or price_crossunder_wma:
                    valid_short_signals += 1
                    # TV: strategy.entry 默认在下一根K线开盘价入场
                    pending_entry = True  # 标记下一根入场
            
            # ========== 持仓状态 ==========
            elif position == 'SHORT':
                exit_reason = None
                exit_price = close
                
                # 用 K 线内极值判断止盈止损
                
                # 1. 保本触发（最低价达到 3% 盈利）
                if not break_even_activated:
                    if low <= entry_price * (1 - self.break_even_pct):
                        break_even_activated = True
                        stop_loss = entry_price
                        print(f"   💰 保本激活 @ 最低价 {low:.2f}")
                
                # 2. 止盈（最低价触及止盈价）
                if low <= take_profit:
                    exit_reason = "止盈"
                    exit_price = take_profit
                
                # 3. 止损（最高价触及止损价）
                elif high >= stop_loss:
                    exit_reason = "保本" if break_even_activated else "止损"
                    exit_price = stop_loss
                
                # 4. 离场周期 MACD 金叉（用 exit_tf 周期 MACD，不是 4H）
                # TV: get_exit_signal() => ta.crossover(m[1], s[1])
                # 所以金叉判断也是在 K线(N-2) 和 K线(N-1) 之间
                else:
                    # 找到 <= 当前时间戳的最近三根离场周期 K线
                    _ts_list = []
                    for _ets in exit_ts_list:
                        if _ets <= timestamp:
                            _ts_list.append(_ets)
                        else:
                            break
                    # 需要至少3根K线才能判断 K线(N-2) 和 K线(N-1) 之间的穿越
                    if len(_ts_list) >= 3:
                        _ts_n1 = _ts_list[-1]   # 最近一根 K线(N-1)
                        _ts_n2 = _ts_list[-2]   # K线(N-2)
                        _ts_n3 = _ts_list[-3]   # K线(N-3)
                        _em_n1, _es_n1 = exit_macd_map[_ts_n1]
                        _em_n2, _es_n2 = exit_macd_map[_ts_n2]
                        # 金叉: K线(N-2)的MACD <= Signal 且 K线(N-1)的MACD > Signal
                        if _em_n2 <= _es_n2 and _em_n1 > _es_n1:
                            exit_reason = "MACD金叉"
                            exit_price = close
                
                # 执行平仓
                if exit_reason:
                    pnl_pct = (entry_price - exit_price) / entry_price
                    pnl = capital * pnl_pct
                    capital += pnl
                    capital = max(capital, 0)
                    
                    dt = _ts_to_cst(timestamp)
                    hold_bars = i - entry_idx
                    hold_hours = hold_bars * 4  # 4H K线, 每根=4小时
                    entry_ts = self.klines_2h[entry_idx][0]
                    hold_hours = round((timestamp - entry_ts) / 3600000)  # 精确小时数
                    
                    print(f"   ✅ 平仓 @ {dt.strftime('%Y-%m-%d %H:%M')} | {exit_price:.2f} | "
                          f"{exit_reason} | {pnl_pct*100:+.2f}% ({pnl:+.2f}) | {hold_hours}h")
                    
                    self.trades.append({
                        'entry_time': _ts_to_cst(self.klines_2h[entry_idx][0]),
                        'exit_time': dt,
                        'entry_price': entry_price,
                        'exit_price': exit_price,
                        'pnl_pct': pnl_pct,
                        'pnl': pnl,
                        'exit_reason': exit_reason,
                        'hold_bars': hold_bars,
                        'break_even': break_even_activated
                    })
                    
                    position = None
                    stop_loss = 0.0
                    take_profit = 0.0
                    break_even_activated = False
        
        self._print_stats(initial_capital, capital, short_signals, price_signals, valid_short_signals)
    
    def _print_stats(self, initial_capital: float, final_capital: float, 
                     short_signals: int, price_signals: int, valid_short_signals: int):
        """打印回测统计"""
        print(f"\n{'='*60}")
        print(f"📊 回测结果")
        print(f"{'='*60}")
        
        total_return = (final_capital - initial_capital) / initial_capital * 100
        
        print(f"\n📈 总体表现:")
        print(f"   初始资金: ${initial_capital:.2f}")
        print(f"   最终资金: ${final_capital:.2f}")
        print(f"   总收益率: {total_return:+.2f}%")
        
        if self.trades:
            wins = [t for t in self.trades if t['pnl'] > 0]
            losses = [t for t in self.trades if t['pnl'] <= 0]
            
            win_rate = len(wins) / len(self.trades) * 100 if self.trades else 0
            avg_win = np.mean([t['pnl_pct'] for t in wins]) * 100 if wins else 0
            avg_loss = np.mean([t['pnl_pct'] for t in losses]) * 100 if losses else 0
            profit_factor = sum([t['pnl'] for t in wins]) / abs(sum([t['pnl'] for t in losses])) if losses and sum([t['pnl'] for t in losses]) != 0 else float('inf')
            
            # 最大回撤
            equity = [initial_capital]
            for t in self.trades:
                equity.append(equity[-1] + t['pnl'])
            
            peak = equity[0]
            max_drawdown = 0
            for e in equity:
                if e > peak:
                    peak = e
                drawdown = (peak - e) / peak
                if drawdown > max_drawdown:
                    max_drawdown = drawdown
            
            avg_hold = np.mean([t['hold_bars'] for t in self.trades]) * 4 if self.trades else 0
            
            print(f"\n📊 交易统计:")
            print(f"   总交易次数: {len(self.trades)}")
            print(f"   盈利次数: {len(wins)}")
            print(f"   亏损次数: {len(losses)}")
            print(f"   胜率: {win_rate:.1f}%")
            print(f"   平均盈利: {avg_win:+.2f}%")
            print(f"   平均亏损: {avg_loss:+.2f}%")
            print(f"   盈亏比: {abs(avg_win/avg_loss):.2f}" if avg_loss != 0 else "   盈亏比: N/A")
            print(f"   盈利因子: {profit_factor:.2f}")
            print(f"   最大回撤: {max_drawdown*100:.2f}%")
            print(f"   平均持仓: {avg_hold:.1f} 小时")
            
            print(f"\n📋 离场原因分析:")
            reasons = {}
            for t in self.trades:
                r = t['exit_reason']
                if r not in reasons:
                    reasons[r] = {'count': 0, 'pnl': 0}
                reasons[r]['count'] += 1
                reasons[r]['pnl'] += t['pnl_pct']
            
            for r, data in reasons.items():
                avg = data['pnl'] / data['count'] * 100
                print(f"   {r}: {data['count']}次, 平均 {avg:+.2f}%")
            
            be_trades = [t for t in self.trades if t['break_even']]
            print(f"\n🛡️ 保本统计:")
            print(f"   触发保本次数: {len(be_trades)}")
            if be_trades:
                be_wins = [t for t in be_trades if t['pnl'] > 0]
                print(f"   保本后盈利次数: {len(be_wins)}")
        
        print(f"\n📊 信号统计:")
        print(f"   MACD死叉信号: {short_signals}")
        print(f"   价格穿越WMA信号: {price_signals}")
        print(f"   有效做空信号(满足任一): {valid_short_signals}")
        
        print(f"\n{'='*60}")
    
    def export_trades(self, filename: str = "backtest_trades.csv"):
        """导出交易记录"""
        if not self.trades:
            return
        df = pd.DataFrame(self.trades)
        filepath = f"c:\\Users\\A1\\PycharmProjects\\PythonProject - 副本\\backpack_quant_trading\\strategy\\{filename}"
        df.to_csv(filepath, index=False, encoding='utf-8-sig')
        print(f"✅ 交易记录已导出: {filepath}")


def main():
    backtest = HYPEBacktest(
        symbol="ETH",
        macd_fast=12,
        macd_slow=26,
        macd_signal=9,
        wma_len=15,
        stop_loss_pct=0.03,
        take_profit_pct=0.06,
        break_even_pct=0.03,
        exit_tf="1h",  # 离场周期: 1小时
    )
    
    backtest.fetch_data(count_2h=6000, count_daily=500)
    backtest.run_backtest(initial_capital=10000.0)
    backtest.export_trades()


if __name__ == "__main__":
    main()
