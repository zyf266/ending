"""
ETH 2H 做多策略回测 — 对应 Pine Script "自适应做多"

逻辑:
  多单进场:  2H MACD金叉  AND  RSI>=50
  多单离场A: 2H MACD死叉  OR  收盘下穿2H WMA（逻辑离场）
  多单离场B: 止盈+5%  |  止损-3%  |  保本触发+1.5%→SL移至成本

参数（与 Pine Script 默认值一致，exitTF=120 即2H）:
  进场/离场周期: 2H  WMA:15  MACD(12,26,9)  RSI(14)
  TP:+5%  SL:-3%  BE触发:+1.5%
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

INITIAL_CAP     = 10_000.0
TAKE_PROFIT_PCT = 1    # 止盈: 入场价×(1+5%)
STOP_LOSS_PCT   = 1   # 止损: 入场价×(1-3%)
BREAKEVEN_PCT   = 1   # 保本触发: 盈利≥1.5%时SL移至成本价
FEE_RATE        = 0.0004  # 手续费单边0.04%（双边0.08%）

TZ_CST   = timezone(timedelta(hours=8))
HL_URL   = "https://api.hyperliquid.xyz/info"
INTERVAL_MS = {
    "2h": 7_200_000,
}


# ─── K线获取 ──────────────────────────────────────────────────────────────────
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
    itvl_ms    = INTERVAL_MS.get(interval, 7_200_000)
    batch_size = 500
    batch_ms   = itvl_ms * batch_size
    start_dt   = datetime.strptime(start_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if extra_days:
        start_dt -= timedelta(days=extra_days)
    cur_start = int(start_dt.timestamp() * 1000)
    end_ms    = int(datetime.now(timezone.utc).timestamp() * 1000)

    rows, empty_cnt = [], 0
    while cur_start < end_ms:
        cur_end = min(cur_start + batch_ms, end_ms)
        chunk   = _hl_chunk(coin, interval, cur_start, cur_end)
        if chunk:
            rows.extend(chunk)
            cur_start = chunk[-1]["t"] + itvl_ms
            empty_cnt = 0
        else:
            cur_start  = cur_end + itvl_ms
            empty_cnt += 1
            if empty_cnt >= 5:
                print(f"  ⚠️ [{interval}] 连续5次空响应，已停止 (已获{len(rows)}根)")
                break
        time.sleep(0.4)

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


# ─── 辅助: 记录单笔做多交易 ────────────────────────────────────────────────────
def _record_trade(trades, exit_ts, exit_p, entry_p, entry_ts, capital, reason,
                  mfe_high=None, mae_low=None):
    qty       = INITIAL_CAP / entry_p
    gross_pnl = (exit_p - entry_p) * qty          # 做多: 出场价 - 入场价
    fee       = (entry_p + exit_p) * qty * FEE_RATE
    pnl_net   = gross_pnl - fee
    pnl_pct   = (exit_p - entry_p) / entry_p * 100
    cap_after = capital + pnl_net

    # MFE: 做多有利波动（持仓最高价 - 入场价）
    mfe_pct = (mfe_high - entry_p) / entry_p * 100 if mfe_high and mfe_high > 0 else 0.0
    # MAE: 做多不利波动（入场价 - 持仓最低价）
    mae_pct = (entry_p - mae_low) / entry_p * 100 if mae_low and mae_low != float("inf") else 0.0

    print(f"   ✅ 平多 {fmt_t(exit_ts)} | {exit_p:.4f}"
          f" | {reason} | {pnl_pct:+.2f}% | 资金:{cap_after:.2f}"
          f"  [MFE:{mfe_pct:+.2f}% MAE:{mae_pct:+.2f}%]")
    trades.append({
        "entry_time":  fmt_t(entry_ts),
        "exit_time":   fmt_t(exit_ts),
        "entry_price": round(entry_p, 6),
        "exit_price":  round(exit_p, 6),
        "pnl_pct":     round(pnl_pct, 4),
        "pnl_net":     round(pnl_net, 4),
        "reason":      reason,
        "mfe_pct":     round(mfe_pct, 4),
        "mae_pct":     round(mae_pct, 4),
        "mfe_price":   round(mfe_high, 6) if mfe_high else 0.0,
        "mae_price":   round(mae_low, 6) if mae_low != float("inf") else 0.0,
        "cap_after":   round(cap_after, 4),
    })


# ─── 回测主函数 ────────────────────────────────────────────────────────────────
def run_backtest():
    print("=" * 62)
    print(f"  {COIN} 2H 做多策略回测（自适应做多）")
    print(f"  进场/离场: 2H | 信号: MACD金叉+RSI≥50")
    print(f"  离场: MACD死叉 OR 下穿WMA | TP:+{TAKE_PROFIT_PCT*100:.0f}%"
          f"  SL:-{STOP_LOSS_PCT*100:.0f}%  BE:+{BREAKEVEN_PCT*100:.1f}%")
    print("=" * 62)

    # ── 拉取 K 线 ─────────────────────────────────────
    print(f"\n📥 拉取 {COIN} 2H K线 (起始: {START_DATE})...")
    df = fetch_hl(COIN, "2h", START_DATE, extra_days=60)  # 多60天供指标预热

    if df.empty:
        print("❌ 2H K线为空，终止")
        return
    s = df["time"].iloc[0].strftime("%Y-%m-%d")
    e = df["time"].iloc[-1].strftime("%Y-%m-%d")
    print(f"  ✅ 2H: {len(df):4d} 根  [{s} ~ {e}]")

    # ── 计算指标 ──────────────────────────────────────
    df = add_macd(df)
    df = add_rsi(df)
    df["wma"] = wma_series(df["c"], WMA_LEN)

    # 2H MACD 金叉（进场信号）
    df["gc2h"] = (
        (df["macd"].shift(1) <= df["signal"].shift(1)) &
        (df["macd"] > df["signal"])
    )
    # 2H MACD 死叉（逻辑离场 A）
    df["dc2h"] = (
        (df["macd"].shift(1) >= df["signal"].shift(1)) &
        (df["macd"] < df["signal"])
    )
    # 收盘下穿 WMA15（逻辑离场 B）
    df["wma_crossunder"] = (
        (df["c"].shift(1) >= df["wma"].shift(1)) &
        (df["c"] < df["wma"])
    ).fillna(False)

    # ── 进场信号: 2H MACD金叉 AND RSI>=50
    df["entry_sig"] = (
        df["gc2h"].fillna(False) &
        (df["rsi"] >= 50)
    )
    # ── 离场信号: MACD死叉 OR 下穿WMA
    df["exit_sig"] = (
        df["dc2h"].fillna(False) |
        df["wma_crossunder"]
    )

    # 过滤预热数据，从 START_DATE 正式开始回测
    start_ts = int(datetime.strptime(START_DATE, "%Y-%m-%d")
                   .replace(tzinfo=timezone.utc).timestamp() * 1000)
    df = df[df["t"] >= start_ts].reset_index(drop=True)

    print(f"\n  进场信号: {df['entry_sig'].sum()}次  "
          f"(gc2h={df['gc2h'].sum()} rsi50={(df['rsi']>=50).sum()})")
    print(f"  离场信号: {df['exit_sig'].sum()}次  "
          f"(2H死叉={df['dc2h'].sum()}  WMA下穿={df['wma_crossunder'].sum()})")

    # ── 回测循环（每根2H推进一次）──────────────────────
    n        = len(df)
    capital  = INITIAL_CAP
    pos      = None
    ep       = 0.0
    ep_ts    = 0
    sl       = 0.0
    tp       = 0.0
    be_on    = False
    p_entry  = False
    p_exit   = False
    mfe_high = 0.0
    mae_low  = float("inf")

    trades = []

    for i in range(n):
        row   = df.iloc[i]
        bar_t = int(row["t"])
        bar_o = float(row["o"])
        bar_h = float(row["h"])
        bar_l = float(row["l"])
        bar_c = float(row["c"])

        # ① 执行挂单进场（上一根发信号 → 本根开盘开多）
        if p_entry and pos is None:
            ep       = bar_o
            ep_ts    = bar_t
            pos      = "LONG"
            sl       = round(ep * (1 - STOP_LOSS_PCT), 8)
            tp       = round(ep * (1 + TAKE_PROFIT_PCT), 8)
            be_on    = False
            p_entry  = False
            mfe_high = bar_o
            mae_low  = bar_o
            print(f"🟢 开多 {fmt_t(bar_t)} | 价格:{ep:.4f} | SL:{sl:.4f} TP:{tp:.4f}")
            continue

        # 更新持仓极值
        if pos == "LONG":
            if p_exit:
                if bar_o > mfe_high: mfe_high = bar_o
                if bar_o < mae_low:  mae_low  = bar_o
            else:
                if bar_h > mfe_high: mfe_high = bar_h
                if bar_l < mae_low:  mae_low  = bar_l

        # ② 执行挂单离场（上一根发信号 → 本根开盘平多）
        if p_exit and pos == "LONG":
            _record_trade(trades, bar_t, bar_o, ep, ep_ts, capital, "信号离场", mfe_high, mae_low)
            capital = trades[-1]["cap_after"]
            pos = None; ep = sl = tp = 0.0; be_on = p_exit = False
            mfe_high = 0.0; mae_low = float("inf")
            continue

        # ③ 持仓风控
        if pos == "LONG":

            # 跳空低开超过止损
            if bar_o <= sl:
                if bar_o < mae_low: mae_low = bar_o
                _record_trade(trades, bar_t, bar_o, ep, ep_ts, capital, "跳空止损", mfe_high, mae_low)
                capital = trades[-1]["cap_after"]
                pos = None; ep = sl = tp = 0.0; be_on = False
                mfe_high = 0.0; mae_low = float("inf")
                continue

            # 跳空高开超过止盈
            if bar_o >= tp:
                if bar_o > mfe_high: mfe_high = bar_o
                _record_trade(trades, bar_t, bar_o, ep, ep_ts, capital, "跳空止盈", mfe_high, mae_low)
                capital = trades[-1]["cap_after"]
                pos = None; ep = sl = tp = 0.0; be_on = False
                mfe_high = 0.0; mae_low = float("inf")
                continue

            # K线内最高价触达止盈
            if bar_h >= tp:
                _record_trade(trades, bar_t, tp, ep, ep_ts, capital, "止盈", mfe_high, mae_low)
                capital = trades[-1]["cap_after"]
                pos = None; ep = sl = tp = 0.0; be_on = False
                mfe_high = 0.0; mae_low = float("inf")
                continue

            # K线内最低价触达止损
            if bar_l <= sl:
                reason = "保本止损" if be_on else "止损"
                _record_trade(trades, bar_t, sl, ep, ep_ts, capital, reason, mfe_high, mae_low)
                capital = trades[-1]["cap_after"]
                pos = None; ep = sl = tp = 0.0; be_on = False
                mfe_high = 0.0; mae_low = float("inf")
                continue

            # 保本激活: 盈利≥1.5% 时SL移至成本价
            if (not be_on) and bar_h >= ep * (1 + BREAKEVEN_PCT):
                be_on  = True
                new_sl = ep
                if new_sl > sl:
                    sl = new_sl
                    print(f"   🛡️  保本激活 @ 高点{bar_h:.4f} → SL = {sl:.4f}")

            # 逻辑离场信号 → 挂单下一根开盘平多
            if bool(row["exit_sig"]):
                p_exit = True

        # ④ 空仓检查进场信号
        if bool(row["entry_sig"]):
            if pos is not None:
                print(f"⏭️  信号跳过 {fmt_t(bar_t)} | 已持仓(入场:{ep:.4f}) 无法开新单")
            elif p_exit:
                print(f"⏭️  信号跳过 {fmt_t(bar_t)} | 等待挂单平仓中")
            else:
                p_entry = True
                print(f"📍 进场信号 {fmt_t(bar_t)} | 收盘:{bar_c:.4f} | "
                      f"RSI:{row['rsi']:.1f} → 下根开盘开多")

    # ── 未平仓提示 ──────────────────────────────────────
    if pos == "LONG":
        last_bar  = df.iloc[-1]
        last_c    = float(last_bar["c"])
        last_t    = int(last_bar["t"])
        unreal_pct = (last_c - ep) / ep * 100
        qty        = INITIAL_CAP / ep
        unreal_net = (last_c - ep) * qty - (ep + last_c) * qty * FEE_RATE
        print(f"\n⚠️  未平仓单: 开多 {fmt_t(ep_ts)} | 入场:{ep:.4f}")
        print(f"   当前末根收盘: {last_c:.4f} ({fmt_t(last_t)})")
        print(f"   浮动盈亏: {unreal_pct:+.2f}%  ({unreal_net:+.2f} USDC)")
        print(f"   持仓时长: {(last_t - ep_ts) / 3600000:.1f} 小时")
        print(f"   SL:{sl:.4f}  TP:{tp:.4f}")
        print(f"   ⚡ 此单未被计入统计，因数据已到末尾无平仓信号")

    # ── 统计汇报 ──────────────────────────────────────
    print(f"\n{'='*62}")
    print(f"📊 回测结果  ·  {COIN} 2H 做多策略（自适应做多）")
    print(f"   期间  : {df['time'].iloc[0].strftime('%Y-%m-%d')}"
          f" ~ {df['time'].iloc[-1].strftime('%Y-%m-%d')}")
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
        eq = [INITIAL_CAP]
        for t in trades:
            eq.append(eq[-1] + t["pnl_net"])
        peak = mdd = 0.0
        for e in eq:
            if e > peak: peak = e
            dd = (peak - e) / peak if peak else 0.0
            if dd > mdd: mdd = dd

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

        mfes = [t["mfe_pct"] for t in trades]
        maes = [t["mae_pct"] for t in trades]
        print(f"\n   📈 有利波动 MFE（做多有利=价格上行）:")
        print(f"     均值:{float(np.mean(mfes)):+.2f}%  "
              f"中位:{float(np.median(mfes)):+.2f}%  "
              f"最大:{max(mfes):+.2f}%")
        for reason in ["信号离场", "止损", "保本止损", "止盈"]:
            sub = [t["mfe_pct"] for t in trades if t["reason"] == reason]
            if sub:
                print(f"     [{reason}] 均MFE: {float(np.mean(sub)):+.2f}%")
        print(f"\n   📉 不利波动 MAE（做多不利=价格下行）:")
        print(f"     均值:{float(np.mean(maes)):+.2f}%  "
              f"中位:{float(np.median(maes)):+.2f}%  "
              f"最大:{max(maes):+.2f}%")
        for reason in ["信号离场", "止损", "保本止损", "止盈"]:
            sub = [t["mae_pct"] for t in trades if t["reason"] == reason]
            if sub:
                print(f"     [{reason}] 均MAE: {float(np.mean(sub)):+.2f}%")

        out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           f"{COIN.lower()}_long_2h_trades.csv")
        with open(out, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=trades[0].keys())
            writer.writeheader()
            writer.writerows(trades)
        print(f"\n   ✅ 交易记录已导出: {out}")

    print("=" * 62)


if __name__ == "__main__":
    run_backtest()
