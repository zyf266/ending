# -*- coding: utf-8 -*-
"""
聚宽回测 - Comprehensive 综合性策略（单文件，无外部依赖）

策略逻辑与 backpack_quant_trading.strategy.comprehensive 完全一致：
- 2个指标=5U, 3个=10U, 4个以上=20U（至少3个指标才开仓）
- 止盈100%，止损50%
- 多指标评分开仓（布林带、RSI、K线形态、KDJ、OBV、均线金叉/死叉等）

使用说明：
1. 将本文件【全部内容】复制到聚宽策略编辑器中（单文件，研究根目录）
2. 修改 g.security 为你要交易的标的（如 '000001.XSHE' 或 '600519.XSHG'）
3. 日线回测：已用 run_daily，每日 14:50 执行
4. 分钟线回测：将 run_daily 注释掉，在 initialize 末添加：
   run_weekly(run_strategy, 1, '14:50')  # 或改用 handle_data 中每根K线调用
5. 聚宽A股无杠杆，用 order_target_value 按资金比例下单（模拟保证金*5~10倍）
6. 【重要】A股最少100股且为100的整数倍；建议初始资金>=3000元（000001约10元/股需1000元起）
"""

import pandas as pd
import numpy as np


# ========== 聚宽必须的函数 ==========
def initialize(context):
    """策略初始化"""
    # 交易标的（可改为股票/期货代码，如 '000001.XSHE' 或 'RB9999.XSGE'）
    g.security = '000001.XSHE'
    
    # 策略参数（与 comprehensive.py 一致）
    g.leverage = 100
    g.margin_level_2 = 5.0
    g.margin_level_3 = 10.0
    g.margin_level_4 = 20.0
    g.take_profit_pct = 1.0   # 止盈100%
    g.stop_loss_pct = 0.5     # 止损50%
    g.rsi_oversold = 40
    g.rsi_overbought = 60
    g.rsi_take_profit_long = 70
    g.rsi_take_profit_short = 30
    g.cooldown_period = 10
    
    # 持仓与状态（聚宽用 context.portfolio.positions 管理持仓，此处仅记录冷静期）
    g.last_exit_bar = -999
    
    # 设置基准、使用真实价格
    set_benchmark(g.security)
    set_option('use_real_price', True)
    
    # 每日运行（日线回测）；若用分钟线，改为在 handle_data 中调用 run_strategy
    run_daily(run_strategy, time='14:50')


def run_strategy(context):
    """每日/每周期执行策略逻辑"""
    # 获取历史K线（至少100根用于指标计算）
    df = get_klines(context, g.security, 120)
    if df is None or len(df) < 60:
        return
    
    # 计算技术指标
    df = calc_indicators(df)
    if df.empty or pd.isna(df.iloc[-1].get('RSI')):
        return
    
    current_price = float(df.iloc[-1]['close'])
    
    # 获取当前持仓（聚宽 API）
    pos = context.portfolio.positions.get(g.security)
    has_position = pos and pos.total_amount > 0
    entry_price = pos.avg_cost if pos else 0
    position = {'qty': pos.total_amount if pos else 0, 'entry_price': entry_price}
    
    # 1. 先检查平仓（有多仓时）
    if has_position and position['qty'] > 0:
        should_exit, reason = check_long_exit(df, position)
        if should_exit:
            order_target_value(g.security, 0)
            g.last_exit_bar = len(df)
            return
    
    # 聚宽 A 股不支持做空，若有期货/期权可在此扩展
    
    # 2. 检查开仓（冷静期）
    bars_since_exit = len(df) - g.last_exit_bar if g.last_exit_bar >= 0 else 999
    if bars_since_exit < g.cooldown_period:
        return
    
    # 3. 无持仓时检查开多
    if not has_position or position['qty'] <= 0:
        long_score = check_long_entry(df)
        short_score = check_short_entry(df)
        
        margin = 0
        action = None
        if long_score >= 3 and long_score > short_score:
            action = 'buy'
            margin = g.margin_level_3 if long_score == 3 else g.margin_level_4
        elif short_score >= 3 and short_score > long_score:
            # A 股不做空；期货可在此开空
            action = 'sell'
            margin = g.margin_level_3 if short_score == 3 else g.margin_level_4
        
        if action == 'buy' and margin > 0:
            # A股规则：最少100股，且必须为100的整数倍
            # 最低下单金额 = 股价 * 100
            min_order_value = current_price * 100
            order_value = margin * min(g.leverage, 10)
            order_value = max(order_value, min_order_value)  # 至少满足100股
            order_value = min(order_value, context.portfolio.available_cash * 0.95)
            # 向上取整到100股的整数倍
            lot_value = current_price * 100
            order_value = int(np.ceil(order_value / lot_value)) * lot_value
            if order_value >= min_order_value and order_value <= context.portfolio.available_cash:
                order_target_value(g.security, order_value)


# ========== 数据获取 ==========
def get_klines(context, security, count):
    """获取K线 DataFrame，列名: open, high, low, close, volume"""
    try:
        # 优先用 attribute_history（聚宽常用）
        df = attribute_history(security, count, '1d', ['open', 'high', 'low', 'close', 'volume'])
        if df is None or df.empty:
            return None
        return df.copy()
    except Exception:
        try:
            df = get_price(security, count=count, unit='1d',
                           fields=['open', 'high', 'low', 'close', 'volume'],
                           skip_paused=True, fq='pre')
            if df is None or df.empty:
                return None
            if isinstance(df.columns, pd.MultiIndex):
                df = df[security] if security in df.columns.get_level_values(0) else df.iloc[:, :5]
                df.columns = ['open', 'high', 'low', 'close', 'volume']
            return df.copy()
        except Exception:
            return None


# ========== 技术指标（与 comprehensive.py 完全一致）==========
def calc_indicators(df):
    if len(df) < 60:
        return df
    df = df.copy()
    df['MA20'] = df['close'].rolling(window=20).mean()
    df['MA50'] = df['close'].rolling(window=50).mean()
    df['BB_MIDDLE'] = df['close'].rolling(window=20).mean()
    bb_std = df['close'].rolling(window=20).std()
    df['BB_UPPER'] = df['BB_MIDDLE'] + 2 * bb_std
    df['BB_LOWER'] = df['BB_MIDDLE'] - 2 * bb_std
    
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()
    rs = np.where(avg_loss > 0, avg_gain / avg_loss, 10.0)
    df['RSI'] = 100 - (100 / (1 + rs))
    
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = ema12 - ema26
    df['MACD_SIGNAL'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['MACD_HIST'] = df['MACD'] - df['MACD_SIGNAL']
    
    df['VOLUME_MA20'] = df['volume'].rolling(window=20).mean()
    
    low_9 = df['low'].rolling(9).min()
    high_9 = df['high'].rolling(9).max()
    rsv = np.where(high_9 > low_9, (df['close'] - low_9) / (high_9 - low_9) * 100, 50)
    df['KDJ_K'] = pd.Series(rsv, index=df.index).ewm(com=2, adjust=False).mean()
    df['KDJ_D'] = df['KDJ_K'].ewm(com=2, adjust=False).mean()
    df['KDJ_J'] = 3 * df['KDJ_K'] - 2 * df['KDJ_D']
    
    tr1 = df['high'] - df['low']
    tr2 = abs(df['high'] - df['close'].shift(1))
    tr3 = abs(df['low'] - df['close'].shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df['ATR14'] = tr.rolling(14).mean()
    
    df['OBV'] = (np.sign(df['close'].diff()) * df['volume']).fillna(0).cumsum()
    df['OBV_MA20'] = df['OBV'].rolling(20).mean()
    
    df['MA5'] = df['close'].rolling(5).mean()
    df['MA10'] = df['close'].rolling(10).mean()
    
    return df


# ========== 做多开仓条件（与 comprehensive.py 完全一致）==========
def check_long_entry(df):
    if len(df) < 50:
        return 0
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    count = 0
    
    close = latest['close']
    bb_lower = latest.get('BB_LOWER')
    ma20 = latest.get('MA20')
    if pd.isna(bb_lower) or pd.isna(ma20):
        return count
    
    if close <= bb_lower * 1.005:
        count += 1
    
    rsi = latest.get('RSI')
    if pd.isna(rsi):
        rsi = 50
    if rsi < g.rsi_oversold:
        count += 1
    
    body = abs(latest['close'] - latest['open'])
    lower_shadow = min(latest['open'], latest['close']) - latest['low']
    upper_shadow = latest['high'] - max(latest['open'], latest['close'])
    is_hammer = (lower_shadow > body * 2 and upper_shadow < body and latest['close'] > latest['open'])
    is_bullish_engulfing = (prev['close'] < prev['open'] and latest['close'] > latest['open'] and
                            latest['close'] > prev['open'] and latest['open'] < prev['close'])
    if is_hammer or is_bullish_engulfing:
        count += 1
    
    volume = latest.get('volume', 0) or 0
    volume_ma = latest.get('VOLUME_MA20')
    if pd.notna(volume_ma) and volume_ma > 0 and volume < volume_ma * 0.8 and close < prev['close']:
        count += 1
    
    kdj_k, kdj_j = latest.get('KDJ_K'), latest.get('KDJ_J')
    if pd.notna(kdj_k) and pd.notna(kdj_j) and (kdj_j < 20 or kdj_k < 30):
        count += 1
    
    obv, obv_ma = latest.get('OBV'), latest.get('OBV_MA20')
    if pd.notna(obv) and pd.notna(obv_ma) and obv > obv_ma * 0.98:
        count += 1
    
    ma5, ma10 = latest.get('MA5'), latest.get('MA10')
    ma5_prev, ma10_prev = prev.get('MA5'), prev.get('MA10')
    if pd.notna(ma5) and pd.notna(ma10) and pd.notna(ma5_prev) and pd.notna(ma10_prev):
        if ma5_prev <= ma10_prev and ma5 > ma10:
            count += 1
    
    return count


# ========== 做空开仓条件（与 comprehensive.py 完全一致）==========
def check_short_entry(df):
    if len(df) < 50:
        return 0
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    count = 0
    
    close = latest['close']
    bb_upper = latest.get('BB_UPPER')
    ma20 = latest.get('MA20')
    if pd.isna(bb_upper) or pd.isna(ma20):
        return count
    
    if close >= bb_upper * 0.995:
        count += 1
    
    rsi = latest.get('RSI')
    if pd.isna(rsi):
        rsi = 50
    if rsi > g.rsi_overbought:
        count += 1
    
    body = abs(latest['close'] - latest['open'])
    lower_shadow = min(latest['open'], latest['close']) - latest['low']
    upper_shadow = latest['high'] - max(latest['open'], latest['close'])
    is_hanging_man = (upper_shadow > body * 2 and lower_shadow < body and latest['close'] < latest['open'])
    is_bearish_engulfing = (prev['close'] > prev['open'] and latest['close'] < latest['open'] and
                            latest['close'] < prev['open'] and latest['open'] > prev['close'])
    if is_hanging_man or is_bearish_engulfing:
        count += 1
    
    volume = latest.get('volume', 0) or 0
    volume_ma = latest.get('VOLUME_MA20')
    if pd.notna(volume_ma) and volume_ma > 0 and close > prev['close'] and volume < volume_ma:
        count += 1
    
    kdj_k, kdj_j = latest.get('KDJ_K'), latest.get('KDJ_J')
    if pd.notna(kdj_k) and pd.notna(kdj_j) and (kdj_j > 80 or kdj_k > 70):
        count += 1
    
    obv, obv_prev = latest.get('OBV'), prev.get('OBV')
    if pd.notna(obv) and pd.notna(obv_prev) and close > prev['close'] and obv < obv_prev:
        count += 1
    
    ma5, ma10 = latest.get('MA5'), latest.get('MA10')
    ma5_prev, ma10_prev = prev.get('MA5'), prev.get('MA10')
    if pd.notna(ma5) and pd.notna(ma10) and pd.notna(ma5_prev) and pd.notna(ma10_prev):
        if ma5_prev >= ma10_prev and ma5 < ma10:
            count += 1
    
    return count


# ========== 平多条件（与 comprehensive.py 完全一致）==========
def check_long_exit(df, position):
    if len(df) < 2:
        return False, ""
    latest = df.iloc[-1]
    current_price = float(latest['close'])
    entry_price = float(position['entry_price'])
    
    pnl_pct = ((current_price - entry_price) / entry_price) * g.leverage
    
    if pnl_pct >= g.take_profit_pct:
        return True, f"止盈(浮盈{pnl_pct*100:.1f}%)"
    if pnl_pct <= -g.stop_loss_pct:
        return True, f"止损(浮亏{pnl_pct*100:.1f}%)"
    
    rsi = latest.get('RSI')
    bb_upper = latest.get('BB_UPPER')
    if pd.isna(rsi) or pd.isna(bb_upper):
        return False, ""
    
    if rsi > g.rsi_take_profit_long and pnl_pct > 0.1:
        return True, f"技术止盈(RSI={rsi:.1f})"
    if current_price >= bb_upper * 1.002 and pnl_pct > 0.2:
        return True, "技术止盈(布林上轨)"
    
    macd_hist = latest.get('MACD_HIST', 0)
    if pd.notna(macd_hist) and macd_hist < 0 and pnl_pct > 0.15:
        return True, "趋势反转(MACD)"
    
    return False, ""


# ========== 平空条件（与 comprehensive.py 完全一致）==========
def check_short_exit(df, position):
    if len(df) < 2:
        return False, ""
    latest = df.iloc[-1]
    current_price = float(latest['close'])
    entry_price = float(position['entry_price'])
    
    pnl_pct = ((entry_price - current_price) / entry_price) * g.leverage
    
    if pnl_pct >= g.take_profit_pct:
        return True, f"止盈(浮盈{pnl_pct*100:.1f}%)"
    if pnl_pct <= -g.stop_loss_pct:
        return True, f"止损(浮亏{pnl_pct*100:.1f}%)"
    
    rsi = latest.get('RSI')
    bb_lower = latest.get('BB_LOWER')
    if pd.isna(rsi) or pd.isna(bb_lower):
        return False, ""
    
    if rsi < g.rsi_take_profit_short and pnl_pct > 0.1:
        return True, f"技术止盈(RSI={rsi:.1f})"
    if current_price <= bb_lower * 0.998 and pnl_pct > 0.2:
        return True, "技术止盈(布林下轨)"
    
    macd_hist = latest.get('MACD_HIST', 0)
    if pd.notna(macd_hist) and macd_hist > 0 and pnl_pct > 0.15:
        return True, "趋势反转(MACD)"
    
    return False, ""
