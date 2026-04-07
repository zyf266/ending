"""
2H 趋势策略 Python 回测
======================
完全对齐 TradingView Pine Script "2h趋势策略 (隐藏优化版)"

策略逻辑:
  入场: 2H MACD金叉[1] AND 2H RSI[1]>=50 AND close > 日线WMA15[1]  → 下一根2H开盘执行
  离场(信号): 4H MACD死叉[1] OR close < 日线WMA15[1]               → 下一根2H开盘执行
  止损(硬止损): 价格跌破 entry*(1-SL_PCT=6%)                        → 当根K线内触发
  保本止损: 盈利达到 BREAKEVEN_TRIGGER=3% 时, SL移至成本价           → 此后回到成本价即止损

防重绘对齐:
  - 所有多周期指标均 [1] 偏移
  - 4H 死叉在4H周期第2根2H bar触发 (shift(1) 对齐 TV 行为)

数据源: Hyperliquid candleSnapshot API（无需代理）
运行:
  python trend_2h_backtest.py
"""

import os
import sys
import time
import warnings
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timezone

warnings.filterwarnings("ignore", category=FutureWarning)

# ==================== 配置 ====================
COIN                 = "ETH"
# Hyperliquid 约保留 1 年历史数据，动态取 365 天前作为起始
_one_year_ago        = (datetime.now(timezone.utc) - __import__('datetime').timedelta(days=365))
START_DATE           = _one_year_ago.strftime("%Y-%m-%d")
END_DATE             = None            # None = 到最新
MACD_FAST            = 12
MACD_SLOW            = 26
MACD_SIG             = 9
RSI_LEN              = 14
WMA_LEN              = 15
INITIAL_CAP          = 10_000.0
STOP_LOSS_PCT        = 0.03           # 硬止损: -3%（超过此亏损立即平仓）
TAKE_PROFIT_PCT      = 0.06           # 硬止盈: +6%（超过此盈利立即平仓）
BREAKEVEN_TRIGGER    = 0.03           # 保本触发: 盈利达到 3% 时将SL移至成本价
FEE_RATE             = 0.001          # 手续费 0.1% 双向 (Taker 0.05%×2)
OUTPUT_CSV           = "trend_2h_backtest_trades.csv"
HL_URL               = "https://api.hyperliquid.xyz/info"

INTERVAL_MS = {"2h": 7_200_000, "4h": 14_400_000, "1d": 86_400_000}


# ==================== Hyperliquid 数据获取 ====================

def _hl_chunk(coin: str, interval: str, start_ms: int, end_ms: int) -> list:
    payload = {"type": "candleSnapshot",
               "req": {"coin": coin, "interval": interval,
                       "startTime": start_ms, "endTime": end_ms}}
    r = requests.post(HL_URL, json=payload, timeout=20)
    r.raise_for_status()
    return r.json() or []


def fetch_hyperliquid(coin: str, interval: str, start: str, end: str = None) -> pd.DataFrame:
    """分批拉取 Hyperliquid K 线（每批 500 根，确保分页准确）"""
    itvl_ms  = INTERVAL_MS.get(interval, 7_200_000)
    batch_ms = itvl_ms * 500          # 每批约 500 根
    start_ms = int(datetime.strptime(start, "%Y-%m-%d")
                   .replace(tzinfo=timezone.utc).timestamp() * 1000)
    end_ms   = (int(datetime.strptime(end, "%Y-%m-%d")
                    .replace(tzinfo=timezone.utc).timestamp() * 1000)
                if end else int(time.time() * 1000))

    all_rows   = []
    cur_start  = start_ms
    empty_cnt  = 0

    while cur_start < end_ms:
        cur_end = min(cur_start + batch_ms, end_ms)
        chunk   = _hl_chunk(coin, interval, cur_start, cur_end)
        if chunk:
            all_rows.extend(chunk)
            cur_start = chunk[-1]["t"] + itvl_ms
            empty_cnt = 0
        else:
            cur_start = cur_end + itvl_ms
            empty_cnt += 1
            if empty_cnt >= 5:
                break
        time.sleep(0.05)

    if not all_rows:
        raise RuntimeError("Hyperliquid 未返回任何 K 线数据")

    df = pd.DataFrame(all_rows)[["t", "o", "h", "l", "c", "v"]].copy()
    df.columns = ["ts", "open", "high", "low", "close", "volume"]
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = df[c].astype(float)
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df.set_index("ts", inplace=True)
    df.sort_index(inplace=True)
    df = df[~df.index.duplicated(keep="last")]
    return df


# ==================== 技术指标 ====================

def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()

def calc_macd(close: pd.Series, fast=12, slow=26, sig=9):
    """返回 (macd线, 信号线)，与 TV ta.macd 完全一致"""
    m = ema(close, fast) - ema(close, slow)
    s = ema(m, sig)
    return m, s

def calc_rsi(close: pd.Series, period=14) -> pd.Series:
    """Wilder RSI，与 TV ta.rsi 完全一致"""
    d    = close.diff()
    up   = d.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    dn   = (-d.clip(upper=0)).ewm(alpha=1/period, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)

def calc_wma(close: pd.Series, period=15) -> pd.Series:
    """加权移动平均，与 TV ta.wma 完全一致"""
    w = np.arange(1, period + 1, dtype=float)
    return close.rolling(period).apply(lambda x: np.dot(x, w) / w.sum(), raw=True)

def crossover(a: pd.Series, b: pd.Series) -> pd.Series:
    """a 从下方穿越 b（金叉）"""
    return (a > b) & (a.shift(1) <= b.shift(1))

def crossunder(a: pd.Series, b: pd.Series) -> pd.Series:
    """a 从上方穿越 b（死叉）"""
    return (a < b) & (a.shift(1) >= b.shift(1))


# ==================== 信号构建 ====================

def build_signals(df2h: pd.DataFrame) -> pd.DataFrame:
    df = df2h.copy()

    # ── 2H MACD + RSI（[1] 偏移，等效 TV request.security("120", x[1])）──
    m_raw, s_raw = calc_macd(df["close"], MACD_FAST, MACD_SLOW, MACD_SIG)
    rsi_raw      = calc_rsi(df["close"], RSI_LEN)

    m2h   = m_raw.shift(1)    # [1] 偏移
    s2h   = s_raw.shift(1)
    rsi2h = rsi_raw.shift(1)
    gc2h  = crossover(m2h, s2h)   # 2H 金叉

    # ── 4H MACD 死叉（[1] 偏移 + 4H周期第2根2H bar 触发）──
    #
    # TV 行为: request.security("240", macd[1]) 在 2H 图上，
    # 新 4H 周期开始后，第 1 根 2H bar 读取到的值仍是旧值，
    # 第 2 根 2H bar 才读取到上一个完整4H bar 的值，因此死叉在第 2 根触发。
    df4h           = df["close"].resample("4h", closed="left", label="left").last()
    m4h_raw, s4h_raw = calc_macd(df4h, MACD_FAST, MACD_SLOW, MACD_SIG)
    m4h_sh         = m4h_raw.shift(1)   # [1] 偏移
    s4h_sh         = s4h_raw.shift(1)

    # 对齐到 2H 时间轴（前向填充）
    m4h_2h = m4h_sh.reindex(df.index, method="ffill")
    s4h_2h = s4h_sh.reindex(df.index, method="ffill")

    # 标记 4H 周期第 1/2 根 2H bar
    df["_4h_grp"]      = df.index.floor("4h")
    df["_is_4h_first"] = df["_4h_grp"] != df["_4h_grp"].shift(1)
    df["_is_4h_second"] = (
        df["_is_4h_first"].shift(1).fillna(False).astype(bool)
        & (df["_4h_grp"] == df["_4h_grp"].shift(1))
    )

    # 死叉在第 1 根 2H bar 能被 crossunder 检测到 → shift(1) → 第 2 根触发
    dc4h_at_first = crossunder(m4h_2h, s4h_2h)
    dc4h = dc4h_at_first.shift(1).fillna(False).astype(bool)

    # ── 日线 WMA15（[1] 偏移）──
    df_daily  = df["close"].resample("1D", closed="left", label="left").last().dropna()
    wma_d     = calc_wma(df_daily, WMA_LEN).shift(1)   # [1] 偏移（前一日）
    daily_wma = wma_d.reindex(df.index, method="ffill")  # 前向填充到 2H

    # ── 组合条件 ──
    above_daily = df["close"] > daily_wma
    below_daily = df["close"] < daily_wma

    df["entry_cond"]  = gc2h & (rsi2h >= 50) & above_daily
    df["exit_cond"]   = dc4h | below_daily
    df["_below_daily"] = below_daily  # 用于记录出场原因

    # 清理临时列
    df.drop(columns=["_4h_grp", "_is_4h_first", "_is_4h_second"], inplace=True)
    return df


# ==================== 逐 Bar 模拟 ====================

def run_backtest(df_signals: pd.DataFrame) -> pd.DataFrame:
    """
    逐 Bar 模拟，完整风控逻辑（以 bar 内最高/最低价判断触发）:
      1. 跳空检测    : open <= sl_price → 以 open 出场 (gap-down)
                       open >= tp_price → 以 open 出场 (gap-up)
      2. 止盈检测    : bar.high >= entry*(1+TAKE_PROFIT_PCT=6%) → 以 tp_price 出场
      3. 保本激活    : bar.high >= entry*(1+BREAKEVEN_TRIGGER=3%) → sl 移至 entry
      4. 止损检测    : bar.low  <= sl_price → 以 sl_price 出场
      5. 信号离场    : 4H死叉 / 跌破日线WMA → 下一根 2H 开盘执行
    同一根 K 线若同时触发止盈和止损，优先触发止盈（假设先涨后跌）
    """
    capital          = INITIAL_CAP
    position         = 0.0
    entry_price      = 0.0
    entry_time       = None
    sl_price         = 0.0
    tp_price         = 0.0
    breakeven_active = False
    trades           = []

    bars = df_signals.reset_index()
    n    = len(bars)

    for i in range(n):
        bar      = bars.iloc[i]
        bar_open = float(bar["open"])
        bar_high = float(bar["high"])
        bar_low  = float(bar["low"])

        # ────── 无持仓: 检测入场信号 ──────
        if position == 0:
            if bar["entry_cond"] and i < n - 1:
                nxt         = bars.iloc[i + 1]
                entry_price = float(nxt["open"])
                entry_time  = nxt["ts"]
                position    = capital / entry_price
                sl_price    = entry_price * (1 - STOP_LOSS_PCT)      # 初始止损 -3%
                tp_price    = entry_price * (1 + TAKE_PROFIT_PCT)    # 止盈 +6%
                breakeven_active = False
            continue

        # ────── 有持仓: 依次检测风控 ──────

        # Step 1: 跳空低开 → gap-down 出场
        if bar_open <= sl_price:
            exit_price = bar_open
            reason     = "跳空止损(保本)" if breakeven_active else "跳空止损"
            pnl        = (exit_price - entry_price) * position
            trade      = _make_trade(entry_time, entry_price, bar["ts"],
                                     exit_price, pnl, capital, reason)
            capital = trade["capital"]
            trades.append(trade)
            position = 0.0
            continue

        # Step 1b: 跳空高开 → gap-up 触达止盈
        if bar_open >= tp_price:
            exit_price = bar_open
            reason     = "止盈(+6%)"
            pnl        = (exit_price - entry_price) * position
            trade      = _make_trade(entry_time, entry_price, bar["ts"],
                                     exit_price, pnl, capital, reason)
            capital = trade["capital"]
            trades.append(trade)
            position = 0.0
            continue

        # Step 2: 止盈触发（K线内最高价 >= tp_price）
        if bar_high >= tp_price:
            exit_price = tp_price
            reason     = "止盈(+6%)"
            pnl        = (exit_price - entry_price) * position
            trade      = _make_trade(entry_time, entry_price, bar["ts"],
                                     exit_price, pnl, capital, reason)
            capital = trade["capital"]
            trades.append(trade)
            position = 0.0
            continue

        # Step 3: 保本激活（high 触碰 3% 盈利线 → SL 移至成本）
        if not breakeven_active and bar_high >= entry_price * (1 + BREAKEVEN_TRIGGER):
            sl_price         = entry_price
            breakeven_active = True

        # Step 4: 止损触发（K线内最低价 <= sl_price）
        if bar_low <= sl_price:
            exit_price = sl_price
            reason     = "保本止损" if breakeven_active else "硬止损(-3%)"
            pnl        = (exit_price - entry_price) * position
            trade      = _make_trade(entry_time, entry_price, bar["ts"],
                                     exit_price, pnl, capital, reason)
            capital = trade["capital"]
            trades.append(trade)
            position = 0.0
            continue

        # Step 5: 信号离场（4H死叉 or 跌破日线WMA）→ 下一根开盘执行
        if bar["exit_cond"] and i < n - 1:
            nxt        = bars.iloc[i + 1]
            exit_price = float(nxt["open"])
            reason     = "趋止损" if bar["_below_daily"] else "趋出"
            pnl        = (exit_price - entry_price) * position
            trade      = _make_trade(entry_time, entry_price, nxt["ts"],
                                     exit_price, pnl, capital, reason)
            capital = trade["capital"]
            trades.append(trade)
            position = 0.0

    return pd.DataFrame(trades)


def _make_trade(entry_time, entry_price, exit_time, exit_price, pnl_gross, capital_before, reason):
    # 手续费 = 名义价值 * FEE_RATE (开仓+平仓)
    qty = capital_before / entry_price
    fee = entry_price * qty * FEE_RATE      # 开仓手续费
    fee += exit_price * qty * FEE_RATE      # 平仓手续费(近似用原始qty)
    pnl_net = pnl_gross - fee
    capital  = capital_before + pnl_net
    return {
        "entry_time":  entry_time,
        "entry_price": round(entry_price, 4),
        "exit_time":   exit_time,
        "exit_price":  round(exit_price, 4),
        "pnl_gross":   round(pnl_gross, 4),
        "fee":         round(fee, 4),
        "pnl_usdt":    round(pnl_net, 4),
        "pnl_pct":     round((exit_price / entry_price - 1) * 100, 2),
        "capital":     round(capital, 4),
        "reason":      reason,
        "breakeven":   "✓" if "保本" in reason else "",
    }


# ==================== 统计输出 ====================

def print_stats(df_trades: pd.DataFrame, start: str):
    if df_trades.empty:
        print("⚠️ 回测期间无交易信号")
        return

    n      = len(df_trades)
    wins   = (df_trades["pnl_usdt"] > 0).sum()
    wr     = wins / n * 100
    final  = df_trades["capital"].iloc[-1]
    ret    = (final / INITIAL_CAP - 1) * 100
    tot    = df_trades["pnl_usdt"].sum()

    cap_s  = pd.concat([pd.Series([INITIAL_CAP]), df_trades["capital"].reset_index(drop=True)])
    peak   = cap_s.cummax()
    max_dd = ((cap_s - peak) / peak * 100).min()

    avg_win  = df_trades.loc[df_trades["pnl_usdt"] > 0, "pnl_pct"].mean() if wins else 0.0
    avg_loss = df_trades.loc[df_trades["pnl_usdt"] <= 0, "pnl_pct"].mean() if (n - wins) else 0.0
    max_win  = df_trades["pnl_pct"].max()
    max_loss = df_trades["pnl_pct"].min()

    print("\n" + "═" * 56)
    print("   2H 趋势策略  回测结果")
    print("═" * 56)
    print(f"   数据起止    : {start} ~ 最新")
    print(f"   风控参数    : 止损={STOP_LOSS_PCT*100:.0f}%  止盈={TAKE_PROFIT_PCT*100:.0f}%  保本触发={BREAKEVEN_TRIGGER*100:.0f}%")
    print(f"   初始资金    : {INITIAL_CAP:>14,.2f} USDT")
    print(f"   最终资金    : {final:>14,.2f} USDT")
    print(f"   总收益      : {tot:>+13,.2f} USDT  ({ret:+.2f}%)")
    print(f"   总交易数    : {n:>14d}")
    print(f"   胜率        : {wr:>13.1f}%")
    print(f"   平均盈利    : {avg_win:>+12.2f}%   最大单笔盈利: {max_win:>+.2f}%")
    print(f"   平均亏损    : {avg_loss:>+12.2f}%   最大单笔亏损: {max_loss:>+.2f}%")
    print(f"   最大回撤    : {max_dd:>+12.2f}%")
    print("═" * 56)

    reason_grp = df_trades.groupby("reason")["pnl_usdt"].agg(count="count", total="sum")
    print("\n   出场原因统计:")
    for r, row in reason_grp.iterrows():
        print(f"     {r:<14} : {int(row['count']):3d} 笔   PnL = {row['total']:>+10.2f} USDT")
    print()


# ==================== 主入口 ====================

def main():
    print("╔" + "═" * 52 + "╗")
    print(f"║   2H 趋势策略 Python 回测   ({COIN}/USD)       ║")
    print("╚" + "═" * 52 + "╝")
    print(f"\n📅 回测区间: {START_DATE} ~ {END_DATE or '最新'}")
    print(f"📡 数据源  : Hyperliquid candleSnapshot API")

    # 缓存文件（避免重复请求）
    cache = f".cache_HL_{COIN}_2h_{START_DATE}.pkl"
    if os.path.exists(cache):
        print(f"📂 使用本地缓存: {cache}")
        df2h = pd.read_pickle(cache)
    else:
        print("📥 从 Hyperliquid 获取 2H K 线数据...")
        try:
            df2h = fetch_hyperliquid(COIN, "2h", START_DATE, END_DATE)
            df2h.to_pickle(cache)
            print(f"💾 数据已缓存: {cache}")
        except Exception as e:
            print(f"\n❌ 数据获取失败: {e}")
            sys.exit(1)

    print(f"   2H K线: {len(df2h)} 根  "
          f"({df2h.index[0].strftime('%Y-%m-%d')} ~ {df2h.index[-1].strftime('%Y-%m-%d')})")

    # 构建信号
    print("\n📊 计算多周期指标与信号...")
    df_sig = build_signals(df2h)

    total_bars    = len(df_sig)
    entry_signals = df_sig["entry_cond"].sum()
    # 出场条件只在持仓期间有意义；这里只统计"入场后第一根满足出场的bar"(近似)
    # 准确出场数量在回测完成后从 trades 中读取
    print(f"   总K线数  : {total_bars} 根")
    print(f"   2H金叉信号(含指标预热): {entry_signals} 次  → 实际交易次数见下方结果")

    # 回测
    print("\n🔄 逐 Bar 模拟（信号触发后下一根开盘执行）...")
    df_trades = run_backtest(df_sig)

    # 输出统计
    print_stats(df_trades, START_DATE)

    # 保存 CSV
    if not df_trades.empty:
        df_trades.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
        print(f"📄 交易记录: {OUTPUT_CSV}  ({len(df_trades)} 笔)")
        print("\n最近 10 笔交易:")
        cols = ["entry_time", "entry_price", "exit_time", "exit_price",
                "pnl_usdt", "pnl_pct", "capital", "reason"]
        print(df_trades[cols].tail(10).to_string(index=False))


if __name__ == "__main__":
    main()
