"""
ETH 2H 趋势反转做空回测
反转自 Pine Script "2h趋势策略 (隐藏优化版)"

原做多逻辑 → 反转做空:
  空单进场 = 原做多离场: 4H MACD死叉[1]  OR  2H收盘 < 日线WMA[1]（持续状态）
  空单离场 = 原做多进场: 2H MACD金叉[1]  AND  RSI2H[1]>=50  AND  2H收盘 > 日线WMA[1]

  实时风控: 止损+3%  止盈-6%  保本触发-3%（盈利≥3%时SL移至成本）

数据源: Hyperliquid API (ETH)  |  周期: 2H  |  方向: SHORT
仓位  : 100%权益复利（strategy.percent_of_equity=100，与Pine Script一致）
手续费: 0.05%单边 / 双边0.1%（设 FEE_RATE=0 可与TV零手续费模式对齐）

Pine Script 关键信号对应:
  m2h  = request.security("120", macd[1])   → df_2h["macd"].shift(1)
  s2h  = request.security("120", signal[1]) → df_2h["signal"].shift(1)
  m4h  = request.security("240", macd[1])   → df_4h["macd"].shift(1)
  s4h  = request.security("240", signal[1]) → df_4h["signal"].shift(1)
  rsi2h= request.security("120", rsi[1])    → df_2h["rsi"].shift(1)
  dailyWMA = request.security("D", wma[1])  → df_1d["wma"].shift(1)
"""

import os
import csv
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from collections import Counter

# ─── 配置 ─────────────────────────────────────────────────────────────────────
COIN            = "ETH"
START_DATE      = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%d")

MACD_FAST       = 12
MACD_SLOW       = 26
MACD_SIG        = 9
RSI_LEN         = 14
WMA_LEN         = 15
RSI_EXIT_MIN    = 50   # 空单离场条件之一：RSI[1] >= 50（原做多进场 RSI 阈值）

INITIAL_CAP     = 10_000.0
STOP_LOSS_PCT   = 0.03    # 止损: 入场价×(1+3%)，做空时价格上涨3%触发
TAKE_PROFIT_PCT = 0.06    # 止盈: 入场价×(1-6%)，做空时价格下跌6%触发
BREAKEVEN_PCT   = 0.03    # 保本触发: 盈利≥3%时SL移至成本价
FEE_RATE        = 0.0005  # 手续费 0.05%单边（双边0.1%）；设0可与TV对齐

TZ_CST   = timezone(timedelta(hours=8))
HL_URL   = "https://api.hyperliquid.xyz/info"
INTERVAL_MS = {
    "1h":  3_600_000,
    "2h":  7_200_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}


# ─── Hyperliquid K线获取 ───────────────────────────────────────────────────────
def _hl_chunk(coin, interval, start_ms, end_ms):
    for attempt in range(3):
        try:
            r = requests.post(HL_URL, json={
                "type": "candleSnapshot",
                "req": {"coin": coin, "interval": interval,
                        "startTime": start_ms, "endTime": end_ms}
            }, timeout=30)
            r.raise_for_status()
            data = r.json()
            if not data:
                if attempt < 2:
                    time.sleep(1.5)
                    continue
                return []
            return [{"t": int(c["t"]), "o": float(c["o"]), "h": float(c["h"]),
                     "l": float(c["l"]), "c": float(c["c"])} for c in data]
        except Exception as e:
            print(f"  ⚠️ [{interval}] 第{attempt+1}次请求错误: {e}")
            if attempt < 2:
                time.sleep(2.0)
    return []


def fetch_hl(coin, interval, start_str, extra_days=0):
    """分页拉取 Hyperliquid K线，返回 DataFrame"""
    itvl_ms    = INTERVAL_MS.get(interval, 3_600_000)
    batch_size = 100 if interval in ("1h", "30m", "15m") else 500
    batch_ms   = itvl_ms * batch_size
    start_dt   = datetime.strptime(start_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if extra_days:
        start_dt -= timedelta(days=extra_days)
    cur_start = int(start_dt.timestamp() * 1000)
    end_ms    = int(datetime.now(timezone.utc).timestamp() * 1000)

    rows, empty_cnt, total_req = [], 0, 0
    while cur_start < end_ms:
        cur_end   = min(cur_start + batch_ms, end_ms)
        chunk     = _hl_chunk(coin, interval, cur_start, cur_end)
        total_req += 1
        if chunk:
            rows.extend(chunk)
            cur_start = chunk[-1]["t"] + itvl_ms
            empty_cnt = 0
        else:
            cur_start  = cur_end + itvl_ms
            empty_cnt += 1
            if empty_cnt >= 5:
                print(f"  ⚠️ [{interval}] 连续5次空响应，已停止 (共{total_req}次请求, 已获{len(rows)}根)")
                break
        sleep_t = 0.5 if interval in ("1h", "30m") else 0.3
        time.sleep(sleep_t)

    if not rows:
        return pd.DataFrame(columns=["t", "o", "h", "l", "c"])

    df = (pd.DataFrame(rows)
          .drop_duplicates("t")
          .sort_values("t")
          .reset_index(drop=True))
    df["time"] = pd.to_datetime(df["t"], unit="ms", utc=True)
    return df


# ─── 指标计算 ──────────────────────────────────────────────────────────────────
def add_macd(df):
    ema_f        = df["c"].ewm(span=MACD_FAST, adjust=False).mean()
    ema_s        = df["c"].ewm(span=MACD_SLOW, adjust=False).mean()
    df["macd"]   = ema_f - ema_s
    df["signal"] = df["macd"].ewm(span=MACD_SIG, adjust=False).mean()
    return df


def add_rsi(df, period=RSI_LEN):
    delta    = df["c"].diff()
    gain     = delta.clip(lower=0)
    loss     = (-delta).clip(lower=0)
    avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
    rs       = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = 100 - 100 / (1 + rs)
    return df


def wma_series(series, period):
    w = np.arange(1, period + 1, dtype=float)
    return series.rolling(period).apply(lambda x: np.dot(x, w) / w.sum(), raw=True)


def fmt_t(ts_ms):
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc) \
                   .astimezone(TZ_CST).strftime("%Y-%m-%d %H:%M")


# ─── 辅助: 记录单笔做空交易 ────────────────────────────────────────────────────
def _record_trade(trades, exit_ts, exit_p, entry_p, entry_ts, capital, reason):
    # 100%权益复利（strategy.percent_of_equity=100，与Pine Script一致）
    qty       = capital / entry_p
    gross_pnl = (entry_p - exit_p) * qty          # 做空: 入场价 - 出场价
    fee       = (entry_p + exit_p) * qty * FEE_RATE
    pnl_net   = gross_pnl - fee
    pnl_pct   = (entry_p - exit_p) / entry_p * 100
    cap_after = capital + pnl_net
    print(f"   ✅ 平空 {fmt_t(exit_ts)} | {exit_p:.4f}"
          f" | {reason} | {pnl_pct:+.2f}% | 资金:{cap_after:.2f}")
    trades.append({
        "entry_time":  fmt_t(entry_ts),
        "exit_time":   fmt_t(exit_ts),
        "entry_price": round(entry_p, 6),
        "exit_price":  round(exit_p, 6),
        "pnl_pct":     round(pnl_pct, 4),
        "pnl_net":     round(pnl_net, 4),
        "reason":      reason,
        "cap_after":   round(cap_after, 4),
    })


# ─── 回测主函数 ────────────────────────────────────────────────────────────────
def run_backtest():
    print("=" * 66)
    print(f"  {COIN} 2H 趋势反转做空回测 (Hyperliquid 数据源)")
    print(f"  空单进场: 4H死叉[1]  OR  收盘 < 日线WMA[1]")
    print(f"  空单离场: 2H金叉[1]  AND  RSI[1]>={RSI_EXIT_MIN}  AND  收盘 > 日线WMA[1]")
    print(f"  止损:+{STOP_LOSS_PCT*100:.0f}%  止盈:-{TAKE_PROFIT_PCT*100:.0f}%"
          f"  保本触发:-{BREAKEVEN_PCT*100:.0f}%")
    print("=" * 66)

    # ── 拉取 K 线 ─────────────────────────────────────
    print(f"\n📥 拉取 {COIN} K线 (起始: {START_DATE})...")
    df_2h = fetch_hl(COIN, "2h", START_DATE)
    df_4h = fetch_hl(COIN, "4h", START_DATE)
    df_1d = fetch_hl(COIN, "1d", START_DATE, extra_days=60)  # 多60天供WMA预热

    for name, df in [("2H", df_2h), ("4H", df_4h), ("日线", df_1d)]:
        if df.empty:
            print(f"❌ {name} K线为空，终止")
            return
        s = df["time"].iloc[0].strftime("%Y-%m-%d")
        e = df["time"].iloc[-1].strftime("%Y-%m-%d")
        print(f"  ✅ {name}: {len(df):4d} 根  [{s} ~ {e}]")

    # ── 计算指标 ──────────────────────────────────────
    df_2h = add_macd(df_2h)   # 2H MACD（用于金叉→离场）
    df_2h = add_rsi(df_2h)    # 2H RSI（用于离场条件 RSI[1]>=50）
    df_4h = add_macd(df_4h)   # 4H MACD（用于死叉→进场）
    df_1d["wma"] = wma_series(df_1d["c"], WMA_LEN)  # 日线WMA15

    # ── Pine Script [1] 偏移 ──────────────────────────────────────────────────
    #
    # 【2H金叉离场信号】
    #   gc2h = ta.crossover(m2h, s2h)，其中 m2h = macd2H[1], s2h = signal2H[1]
    #   ⟹ 当前2H bar j: macd[j-2] <= sig[j-2]  AND  macd[j-1] > sig[j-1]
    #   → 在 2H 时间轴上直接计算，无需跨时间轴边沿检测
    df_2h["m_s1"] = df_2h["macd"].shift(1)
    df_2h["s_s1"] = df_2h["signal"].shift(1)
    df_2h["m_s2"] = df_2h["macd"].shift(2)
    df_2h["s_s2"] = df_2h["signal"].shift(2)
    df_2h["gc2h"] = (df_2h["m_s2"] <= df_2h["s_s2"]) & (df_2h["m_s1"] > df_2h["s_s1"])

    # 2H RSI[1]（Pine Script: rsi2h = request.security("120", rsi[1])）
    df_2h["rsi_s1"] = df_2h["rsi"].shift(1)

    # 【4H死叉进场信号】
    #   dc4h = ta.crossunder(m4h, s4h)，其中 m4h = macd4H[1], s4h = signal4H[1]
    #   ⟹ 4H bar j: macd4h[j-2] >= sig4h[j-2]  AND  macd4h[j-1] < sig4h[j-1]
    df_4h["m_s1"] = df_4h["macd"].shift(1)
    df_4h["s_s1"] = df_4h["signal"].shift(1)
    df_4h["m_s2"] = df_4h["macd"].shift(2)
    df_4h["s_s2"] = df_4h["signal"].shift(2)
    df_4h["dc4h"] = (df_4h["m_s2"] >= df_4h["s_s2"]) & (df_4h["m_s1"] < df_4h["s_s1"])

    # 日线WMA[1]
    df_1d["wma_s1"] = df_1d["wma"].shift(1)

    # ── 所有信号对齐到 2H 时间线 ──────────────────────
    for df in [df_2h, df_4h, df_1d]:
        df.sort_values("t", inplace=True)

    # 4H dc4h → 2H（merge_asof 向后填充）
    df_2h = pd.merge_asof(df_2h,
                          df_4h[["t", "dc4h"]],
                          on="t", direction="backward")

    # ── 边沿检测：4H信号在第二根2H bar上触发 ──────────────────────────────────
    # Pine Script request.security(lookahead=off)：
    #   4H bar 关闭后其值才对 2H 可见，等效于在当前4H周期的【第二根2H bar】触发
    _4H_MS = 14_400_000
    df_2h["_4h_start"] = (df_2h["t"] // _4H_MS) * _4H_MS
    _is_4h_second = (
        (df_2h["_4h_start"] == df_2h["_4h_start"].shift(1).fillna(-1)) &
        (df_2h["_4h_start"] != df_2h["_4h_start"].shift(2).fillna(-1))
    )
    df_2h["dc4h"] = df_2h["dc4h"].fillna(False) & _is_4h_second

    # 日线WMA[1] → 2H
    df_2h = pd.merge_asof(df_2h,
                          df_1d[["t", "wma_s1"]].rename(columns={"wma_s1": "daily_wma"}),
                          on="t", direction="backward")

    df_2h = df_2h.dropna(subset=["daily_wma"]).reset_index(drop=True)

    # ── 信号计算 ──────────────────────────────────────────────────────────────
    # aboveDaily = 2H收盘 > 日线WMA[1]（持续状态，用于离场条件）
    df_2h["aboveDaily"] = df_2h["c"] > df_2h["daily_wma"]

    # ▶ 空单进场: 仅 4H MACD死叉[1]
    df_2h["entry_sig"] = df_2h["dc4h"].fillna(False)

    # ▶ 空单离场（信号）= 原做多进场（AND逻辑）:
    #   2H MACD金叉[1]  AND  RSI2H[1]>=50  AND  2H收盘 > 日线WMA[1]
    df_2h["exit_sig"] = (
        df_2h["gc2h"].fillna(False) &
        (df_2h["rsi_s1"].fillna(0) >= RSI_EXIT_MIN) &
        df_2h["aboveDaily"].fillna(False)
    )

    print(f"\n  进场信号次数: {df_2h['entry_sig'].sum()}  (dc4h={df_2h['dc4h'].sum()}次)")
    print(f"  离场信号次数: {df_2h['exit_sig'].sum()}  (gc2h AND rsi>={RSI_EXIT_MIN} AND aboveWMA)")

    # ── 回测循环（每根2H bar推进一次）────────────────────
    n        = len(df_2h)
    capital  = INITIAL_CAP
    pos      = None      # None | "SHORT"
    ep       = 0.0       # entry_price
    ep_ts    = 0         # entry timestamp ms
    sl       = 0.0       # stop_loss（做空：入场价×1.03，在上方）
    tp       = 0.0       # take_profit（做空：入场价×0.94，在下方）
    be_on    = False     # breakeven 已激活
    p_entry  = False     # 挂单: 下一根bar开盘开空
    p_exit   = False     # 挂单: 下一根bar开盘平空（信号离场）

    trades = []

    for i in range(n):
        row   = df_2h.iloc[i]
        bar_t = int(row["t"])
        bar_o = float(row["o"])
        bar_h = float(row["h"])
        bar_l = float(row["l"])
        bar_c = float(row["c"])

        # ① 执行挂单进场（上一根2H发进场信号 → 本根开盘开空）──
        if p_entry and pos is None:
            ep      = bar_o
            ep_ts   = bar_t
            pos     = "SHORT"
            sl      = round(ep * (1 + STOP_LOSS_PCT), 8)
            tp      = round(ep * (1 - TAKE_PROFIT_PCT), 8)
            be_on   = False
            p_entry = False
            print(f"🔴 开空 {fmt_t(bar_t)} | 价格:{ep:.4f} | SL:{sl:.4f} TP:{tp:.4f}")
            continue   # 入场当根不做离场检查

        # ② 执行挂单离场（上一根信号触发 → 本根开盘平空）──
        if p_exit and pos == "SHORT":
            _record_trade(trades, bar_t, bar_o, ep, ep_ts, capital, "信号离场")
            capital = trades[-1]["cap_after"]
            pos = None; ep = sl = tp = 0.0; be_on = p_exit = False
            continue

        # ③ 持仓风控（止盈止损+保本）+ 离场信号检查 ──────────────────
        if pos == "SHORT":

            # 2a. 跳空高开 → 超过止损价直接以开盘价止损
            if bar_o >= sl:
                _record_trade(trades, bar_t, bar_o, ep, ep_ts, capital, "跳空止损")
                capital = trades[-1]["cap_after"]
                pos = None; ep = sl = tp = 0.0; be_on = False; continue

            # 2b. 跳空低开 → 低于止盈价直接以开盘价止盈
            if bar_o <= tp:
                _record_trade(trades, bar_t, bar_o, ep, ep_ts, capital, "跳空止盈")
                capital = trades[-1]["cap_after"]
                pos = None; ep = sl = tp = 0.0; be_on = False; continue

            # 2c. K线内最低价触达止盈
            if bar_l <= tp:
                _record_trade(trades, bar_t, tp, ep, ep_ts, capital, "止盈")
                capital = trades[-1]["cap_after"]
                pos = None; ep = sl = tp = 0.0; be_on = False; continue

            # 2d. K线内最高价触达止损（先检查旧止损，与Pine Script order一致）
            if bar_h >= sl:
                reason = "保本止损" if be_on else "止损"
                _record_trade(trades, bar_t, sl, ep, ep_ts, capital, reason)
                capital = trades[-1]["cap_after"]
                pos = None; ep = sl = tp = 0.0; be_on = False; continue

            # 2e. 保本激活：收盘价判断，激活后SL=成本价，下一根bar起生效
            if (not be_on) and bar_c <= ep * (1 - BREAKEVEN_PCT):
                be_on = True
                sl    = ep
                print(f"   🛡️  保本激活 @ 收盘{bar_c:.4f} → SL = 成本价 {sl:.4f}")

            # 2f. 离场信号（gc2h AND rsi[1]>=50 AND aboveDaily）→ 挂单下一根开盘平空
            if bool(row["exit_sig"]):
                p_exit = True

        # ③ 空仓检查进场信号（仅 dc4h）──────────────
        if pos is None and (not p_exit) and bool(row["entry_sig"]):
            p_entry = True
            reason_parts = []
            if bool(row.get("dc4h", False)):
                reason_parts.append("4H死叉")
            if bool(row.get("crossunder_daily", False)):
                reason_parts.append("下穿WMA")
            print(f"📍 进场信号 {fmt_t(bar_t)} | 收盘:{bar_c:.4f}"
                  f" | {' + '.join(reason_parts)} → 下根开盘开空")

    # ── 统计汇报 ──────────────────────────────────────
    print(f"\n{'='*66}")
    print(f"📊 回测结果  ·  {COIN} 2H 趋势反转做空")
    print(f"   期间  : {df_2h['time'].iloc[0].strftime('%Y-%m-%d')}"
          f" ~ {df_2h['time'].iloc[-1].strftime('%Y-%m-%d')}")
    print(f"   初始  : ${INITIAL_CAP:>12,.2f}")
    print(f"   最终  : ${capital:>12,.2f}")
    total_ret = (capital - INITIAL_CAP) / INITIAL_CAP * 100
    print(f"   总收益: {total_ret:+.2f}%")

    if not trades:
        print("   （无交易记录）")
    else:
        wins   = [t for t in trades if t["pnl_net"] > 0]
        losses = [t for t in trades if t["pnl_net"] <= 0]
        wr     = len(wins) / len(trades) * 100
        avg_w  = float(np.mean([t["pnl_pct"] for t in wins]))  if wins   else 0.0
        avg_l  = float(np.mean([t["pnl_pct"] for t in losses])) if losses else 0.0
        sum_w  = sum(t["pnl_net"] for t in wins)
        sum_l  = abs(sum(t["pnl_net"] for t in losses))
        pf     = sum_w / sum_l if sum_l else float("inf")

        # 最大回撤
        eq   = [INITIAL_CAP]
        for t in trades:
            eq.append(eq[-1] + t["pnl_net"])
        peak = mdd = 0.0
        for e in eq:
            if e > peak:
                peak = e
            dd = (peak - e) / peak if peak else 0.0
            if dd > mdd:
                mdd = dd

        avg_hold = float(np.mean([(
            datetime.strptime(t["exit_time"], "%Y-%m-%d %H:%M") -
            datetime.strptime(t["entry_time"], "%Y-%m-%d %H:%M")
        ).total_seconds() / 3600 for t in trades]))

        print(f"\n   总交易  : {len(trades)}")
        print(f"   胜率    : {wr:.1f}%  ({len(wins)}胜 / {len(losses)}负)")
        print(f"   均盈    : {avg_w:+.2f}%  |  均亏: {avg_l:+.2f}%")
        if avg_l != 0:
            print(f"   盈亏比  : {abs(avg_w / avg_l):.2f}")
        print(f"   盈利因子: {pf:.2f}")
        print(f"   最大回撤: {mdd * 100:.2f}%")
        print(f"   均持仓  : {avg_hold:.1f} 小时")

        print(f"\n   离场原因分布:")
        for reason, cnt in Counter(t["reason"] for t in trades).most_common():
            pnls = [t["pnl_pct"] for t in trades if t["reason"] == reason]
            print(f"     {reason:8s}: {cnt:3d}次  均{float(np.mean(pnls)):+.2f}%")

        # 导出 CSV
        out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trend_short_trades.csv")
        with open(out, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=trades[0].keys())
            writer.writeheader()
            writer.writerows(trades)
        print(f"\n   ✅ 交易记录已导出: {out}")

    print("=" * 66)


# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    run_backtest()
