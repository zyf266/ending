"""
ETH 2H 做空策略回测 — 对应 Pine Script "自适应做空"（优化版 OR+D + 2H金叉离场）

逻辑：
  空单进场:  (4H MACD死叉[1]  OR  2H收盘下穿日线WMA)  AND  2H MACD[1]偏空(D)
  空单离场:  2H MACD金叉[1]（比4H金叉更灵敏，止损从26次降至14次）
  止损: +3%  止盈: -6%  保本触发: -2%（盈利≥2%时SL移至成本）

优化历史:
  原版(OR无过滤):      +7.75%  胜率34%  回撤36%  止损42次
  OR+D(4H金叉离场):  +61.46%  胜率45%  回撤26%  止损26次
  OR+D(2H金叉+BE2%): +64.68%  胜率41%  回撤23%  止损14次  盈利因子1.81

数据源 : Hyperliquid API (ETH)
进场周期: 2H  |  出场扫描周期: 2H
手续费  : 0.05% 单边（双边0.1%）
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
STOP_LOSS_PCT    = 0.03    # 止损: 入场价 × (1 + 3%)
TAKE_PROFIT_PCT  = 0.10   # 止盈: 入场价 × (1 - 10%)
LOCKIN_TRIG_PCT  = 0.04    # 锁利触发: 盈利≥4%时SL移至2%利润价（优先于保本）
LOCKIN_PROT_PCT  = 0.02    # 锁利保护: SL锁定在入场价×(1-2%)位置
BREAKEVEN_PCT    = 0.05    # 保本触发: 盈利≥5%时SL移至成本价（0%利润，锁利激活后无效）
PRICE_FILTER_MAX = 2000.0 # 价格下限过滤: 收盘价 < 此值时不开空（ETH低于2000不追空）
FEE_RATE        = 0.0005  # TV回测不计手续费（设0与TV对齐；实盘改为0.0005）

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
    # 1H及以下用100根/批，避免API数据为空
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
        # 调试：打印一次原始响应，帮助定位问题
        from datetime import datetime as _dt
        _test_start = int(_dt(2025, 10, 1, tzinfo=timezone.utc).timestamp() * 1000)
        _test_end   = int(_dt(2025, 10, 2, tzinfo=timezone.utc).timestamp() * 1000)
        try:
            _r = requests.post(HL_URL, json={
                "type": "candleSnapshot",
                "req": {"coin": coin, "interval": interval,
                        "startTime": _test_start, "endTime": _test_end}
            }, timeout=15)
            _data = _r.json()
            print(f"  🔍 [{interval}] 调试请求(2025-10-01~02): 状态={_r.status_code} 返回{len(_data) if isinstance(_data,list) else type(_data).__name__}条")
        except Exception as e:
            print(f"  🔍 [{interval}] 调试请求异常: {e}")
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


# ─── 回测主函数 ────────────────────────────────────────────────────────────────
def run_backtest():
    print("=" * 62)
    print(f"  {COIN} 2H 做空策略回测 (Hyperliquid 数据源)")
    print(f"  进场: 2H  |  出场扫描: 2H  |  方向: SHORT")
    print(f"  止损:+{STOP_LOSS_PCT*100:.0f}%  止盈:-{TAKE_PROFIT_PCT*100:.0f}%"
          f"  保本触发:-{BREAKEVEN_PCT*100:.0f}%")
    print("=" * 62)

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
    df_2h = add_macd(df_2h)            # 2H: MACD（D条件过滤 + 2H金叉离场）
    df_4h = add_macd(df_4h)            # 4H: MACD（进场死叉）
    df_1d["wma"] = wma_series(df_1d["c"], WMA_LEN)  # 日线WMA15

    # ── 4H 死叉[1]（进场信号）──────────────────────────
    # crossunder(m4h[1], s4h[1]):
    #   4H bar j: macd[j-2] >= sig[j-2]  AND  macd[j-1] < sig[j-1]
    df_4h["m_s1"] = df_4h["macd"].shift(1)
    df_4h["s_s1"] = df_4h["signal"].shift(1)
    df_4h["m_s2"] = df_4h["macd"].shift(2)
    df_4h["s_s2"] = df_4h["signal"].shift(2)
    df_4h["dc4h"] = (df_4h["m_s2"] >= df_4h["s_s2"]) & (df_4h["m_s1"] < df_4h["s_s1"])

    # ── 2H MACD 信号计算（[1]偏移，防重绘）────────────
    # gc2h = 2H金叉[1]: 前两根死叉 → 前一根金叉
    df_2h["m_s1"] = df_2h["macd"].shift(1)
    df_2h["s_s1"] = df_2h["signal"].shift(1)
    df_2h["m_s2"] = df_2h["macd"].shift(2)
    df_2h["s_s2"] = df_2h["signal"].shift(2)
    df_2h["gc2h"]      = (df_2h["m_s2"] <= df_2h["s_s2"]) & (df_2h["m_s1"] > df_2h["s_s1"])
    df_2h["macd_bias"] = df_2h["m_s1"] < df_2h["s_s1"]   # D条件: 偏空=True

    # 日线 WMA[1]
    df_1d["wma_s1"] = df_1d["wma"].shift(1)

    # ── 所有信号对齐到 2H 时间线（merge_asof 向后填充）──
    for df in [df_2h, df_4h, df_1d]:
        df.sort_values("t", inplace=True)

    # ── 2H 时间轴上计算日线WMA下穿（crossunder）──────
    _2h_wma = pd.merge_asof(df_2h[["t"]].copy(),
                             df_1d[["t", "wma_s1"]].rename(columns={"wma_s1": "_dw"}),
                             on="t", direction="backward")
    df_2h["_dw"] = _2h_wma["_dw"].values
    df_2h["crossunder_wma"] = (
        (df_2h["c"].shift(1) >= df_2h["_dw"].shift(1)) &
        (df_2h["c"] < df_2h["_dw"])
    ).fillna(False)

    # 4H dc4h → 2H
    df_2h = pd.merge_asof(df_2h, df_4h[["t", "dc4h"]], on="t", direction="backward")

    # ── 边沿检测：4H信号仅在该4H周期第二根2H bar可见 ──
    _4H_MS = 14_400_000
    df_2h["_4h_start"] = (df_2h["t"] // _4H_MS) * _4H_MS
    _is_4h_second = (
        (df_2h["_4h_start"] == df_2h["_4h_start"].shift(1).fillna(-1)) &
        (df_2h["_4h_start"] != df_2h["_4h_start"].shift(2).fillna(-1))
    )
    df_2h["dc4h"] = df_2h["dc4h"].fillna(False) & _is_4h_second

    # 日线 WMA[1] → 2H
    df_2h = pd.merge_asof(df_2h,
                          df_1d[["t", "wma_s1"]].rename(columns={"wma_s1": "daily_wma"}),
                          on="t", direction="backward")
    df_2h = df_2h.dropna(subset=["daily_wma"]).reset_index(drop=True)

    # ── 信号计算 ─────────────────────────────────────
    df_2h["above_daily"] = df_2h["c"] > df_2h["daily_wma"]

    # ▶ 空单进场：(4H MACD死叉[1]  OR  2H收盘下穿日线WMA)  AND  2H MACD[1]偏空(D)
    df_2h["entry_sig"] = (
        (df_2h["dc4h"].fillna(False) | df_2h["crossunder_wma"].fillna(False)) &
        df_2h["macd_bias"].fillna(False)
    )

    # ▶ 空单离场：2H MACD金叉[1]（exitTF=120，比4H金叉更灵敏，止损从26次降至14次）
    df_2h["exit_sig"] = df_2h["gc2h"].fillna(False)

    print(f"\n  进场信号: {df_2h['entry_sig'].sum()}次"
          f"  (dc4h={df_2h['dc4h'].sum()}  cross={df_2h['crossunder_wma'].sum()}  "
          f"macd_bias={df_2h['macd_bias'].sum()}根)")
    print(f"  离场信号: {df_2h['exit_sig'].sum()}次  (2H MACD金叉[1])")


    # ── 回测循环（每根2H bar推进一次）────────────────────
    n        = len(df_2h)
    capital  = INITIAL_CAP
    pos      = None      # None | "SHORT"
    ep       = 0.0       # entry_price
    ep_ts    = 0         # entry timestamp ms
    sl       = 0.0       # stop_loss price (做空: 入场价 × 1.03)
    tp       = 0.0       # take_profit price (做空: 入场价 × 0.94)
    be_on    = False     # breakeven already activated
    lockin_on = False    # 锁利已激活（盈利≥4%时SL锁到2%利润位）
    p_entry  = False     # pending: enter at next bar open
    p_exit   = False     # pending: exit at next bar open
    mfe_low  = float("inf")   # 持仓期间最低价（做空MFE = 价格最低点）
    mae_high = 0.0             # 持仓期间最高价（做空MAE = 价格最高点）

    trades = []

    for i in range(n):
        row   = df_2h.iloc[i]
        bar_t = int(row["t"])
        bar_o = float(row["o"])
        bar_h = float(row["h"])
        bar_l = float(row["l"])
        bar_c = float(row["c"])

        # ① 执行挂单进场（上一根2H发信号 → 本根开盘开空）──
        if p_entry and pos is None:
            ep      = bar_o
            ep_ts   = bar_t
            pos     = "SHORT"
            sl      = round(ep * (1 + STOP_LOSS_PCT), 8)
            tp      = round(ep * (1 - TAKE_PROFIT_PCT), 8)
            be_on   = False
            lockin_on = False
            p_entry = False
            mfe_low  = bar_o    # 重置为开仓价
            mae_high = bar_o    # 重置为开仓价
            print(f"🔴 开空 {fmt_t(bar_t)} | 价格:{ep:.4f} | SL:{sl:.4f} TP:{tp:.4f}")
            continue   # 入场当根不做离场检查

        # 更新持仓期间价格极值（用于 MFE/MAE 计算）
        # 注意：只在"非开盘即平仓"的bar上用bar_l/bar_h更新极值。
        # 若本bar将在bar_o执行信号离场，极值只更新到bar_o（不含bar内后续波动）
        if pos == "SHORT":
            # p_exit=True 表示本根K线将在开盘价平仓，极值只扩展到 bar_o
            if p_exit:
                if bar_o < mfe_low:  mfe_low  = bar_o
                if bar_o > mae_high: mae_high = bar_o
            else:
                if bar_l < mfe_low:  mfe_low  = bar_l
                if bar_h > mae_high: mae_high = bar_h

        # ② 执行挂单离场（上一根2H发信号 → 本根开盘平空）──
        if p_exit and pos == "SHORT":
            _record_trade(trades, bar_t, bar_o, ep, ep_ts, capital, "信号离场", mfe_low, mae_high)
            capital = trades[-1]["cap_after"]
            pos = None; ep = sl = tp = 0.0; be_on = lockin_on = p_exit = False
            mfe_low = float("inf"); mae_high = 0.0
            continue

        # ③ 持仓风控（做空：SL 在上方，TP 在下方）──────────
        if pos == "SHORT":

            # 3a. 跳空高开 → 超过止损价直接以开盘价止损
            if bar_o >= sl:
                # 跳空止损成交在bar_o，MAE最多到bar_o（不含bar内后续更高价）
                if bar_o > mae_high: mae_high = bar_o
                _record_trade(trades, bar_t, bar_o, ep, ep_ts, capital, "跳空止损", mfe_low, mae_high)
                capital = trades[-1]["cap_after"]
                pos = None; ep = sl = tp = 0.0; be_on = lockin_on = False
                mfe_low = float("inf"); mae_high = 0.0
                continue

            # 3b. 跳空低开 → 低于止盈价直接以开盘价止盈
            if bar_o <= tp:
                # 跳空止盈成交在bar_o，MFE最多到bar_o
                if bar_o < mfe_low: mfe_low = bar_o
                _record_trade(trades, bar_t, bar_o, ep, ep_ts, capital, "跳空止盈", mfe_low, mae_high)
                capital = trades[-1]["cap_after"]
                pos = None; ep = sl = tp = 0.0; be_on = lockin_on = False
                mfe_low = float("inf"); mae_high = 0.0
                continue

            # 3c. K线内最低价触达止盈
            if bar_l <= tp:
                _record_trade(trades, bar_t, tp, ep, ep_ts, capital, "止盈", mfe_low, mae_high)
                capital = trades[-1]["cap_after"]
                pos = None; ep = sl = tp = 0.0; be_on = lockin_on = False
                mfe_low = float("inf"); mae_high = 0.0
                continue

            # 3d. K线内最高价触达止损
            if bar_h >= sl:
                reason = "保本止损" if be_on else ("锁利止损" if lockin_on else "止损")
                _record_trade(trades, bar_t, sl, ep, ep_ts, capital, reason, mfe_low, mae_high)
                capital = trades[-1]["cap_after"]
                pos = None; ep = sl = tp = 0.0; be_on = lockin_on = False
                mfe_low = float("inf"); mae_high = 0.0
                continue

            # 3e. 锁利激活：盈利≥4%时SL移至入场价×(1-2%)，锁住2%利润
            # 做空盈利 = (ep - bar_c) / ep，bar_c越低盈利越高
            if (not lockin_on) and bar_c <= ep * (1 - LOCKIN_TRIG_PCT):
                lockin_on = True
                lockin_sl = round(ep * (1 - LOCKIN_PROT_PCT), 8)  # 入场价×0.98 = 2%利润位
                if lockin_sl < sl:   # 只在改善时更新（SL越低对做空持仓越有利）
                    sl = lockin_sl
                print(f"   🔒 锁利激活 @ 收盘{bar_c:.4f} → SL = {sl:.4f}（锁住+2%利润）")

            # 3f. 保本激活：盈利≥5%时SL移至成本价（锁利已激活时不会降级到0%）
            if (not be_on) and bar_c <= ep * (1 - BREAKEVEN_PCT):
                be_on = True
                be_sl = ep  # 成本价 = 0%利润
                if be_sl < sl:   # 只在改善时更新（保本价比锁利价更高时跳过）
                    sl = be_sl
                    print(f"   🛡️  保本激活 @ 收盘{bar_c:.4f} → SL = {sl:.4f}")

            # 3g. 离场信号 → 挂单下一根 2H 开盘平空
            if bool(row["exit_sig"]):
                p_exit = True

        # ④ 空仓检查进场信号 ──────────────────────────────
        if pos is None and (not p_exit) and bool(row["entry_sig"]):
            # 价格过滤：ETH 收盘价 < 2000 时不开空（避免在低位追空）
            if bar_c < PRICE_FILTER_MAX:
                continue
            p_entry = True
            reason_parts = []
            if bool(row.get("dc4h", False)):
                reason_parts.append("4H死叉")
            if bool(row.get("crossunder_wma", False)):
                reason_parts.append("下穿WMA")
            print(f"📍 进场信号 {fmt_t(bar_t)} | 收盘:{bar_c:.4f}"
                  f" | {' + '.join(reason_parts)} → 下根开盘开空")

    # ── 统计汇报 ──────────────────────────────────────
    print(f"\n{'='*62}")
    print(f"📊 回测结果  ·  {COIN} 2H 做空策略")
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

        # MFE / MAE 统计
        mfes = [t["mfe_pct"] for t in trades]
        maes = [t["mae_pct"] for t in trades]
        print(f"\n   📈 有利波动 MFE（做空有利=价格下行）:")
        print(f"     均值:{float(np.mean(mfes)):+.2f}%  "
              f"中位:{float(np.median(mfes)):+.2f}%  "
              f"最大:{max(mfes):+.2f}%")
        for reason in ["信号离场", "止损", "保本止损", "止盈"]:
            sub = [t["mfe_pct"] for t in trades if t["reason"] == reason]
            if sub: print(f"     [{reason}] 均MFE: {float(np.mean(sub)):+.2f}%")
        print(f"\n   📉 不利波动 MAE（做空不利=价格上行）:")
        print(f"     均值:{float(np.mean(maes)):+.2f}%  "
              f"中位:{float(np.median(maes)):+.2f}%  "
              f"最大:{max(maes):+.2f}%")
        for reason in ["信号离场", "止损", "保本止损", "止盈"]:
            sub = [t["mae_pct"] for t in trades if t["reason"] == reason]
            if sub: print(f"     [{reason}] 均MAE: {float(np.mean(sub)):+.2f}%")

        # 导出 CSV
        out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hype_short_trades.csv")
        with open(out, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=trades[0].keys())
            writer.writeheader()
            writer.writerows(trades)
        print(f"\n   ✅ 交易记录已导出: {out}")

    print("=" * 62)


# ─── 辅助: 记录单笔做空交易 ────────────────────────────────────────────────────
def _record_trade(trades, exit_ts, exit_p, entry_p, entry_ts, capital, reason,
                  mfe_low=None, mae_high=None):
    # TV使用固定名义仓位 $INITIAL_CAP（strategy.cash模式，非复利）
    # → 每笔仓位价值始终≈$10,000，与TV CSV"仓位大小（价值）"列吻合
    qty       = INITIAL_CAP / entry_p
    gross_pnl = (entry_p - exit_p) * qty          # 做空: 入场价 - 出场价
    fee       = (entry_p + exit_p) * qty * FEE_RATE
    pnl_net   = gross_pnl - fee
    pnl_pct   = (entry_p - exit_p) / entry_p * 100
    cap_after = capital + pnl_net

    # MFE: 有利波动（做空：入场价 → 持仓最低价，越低越有利）
    mfe_pct = (entry_p - mfe_low) / entry_p * 100 if mfe_low is not None and mfe_low != float("inf") else 0.0
    # MAE: 不利波动（做空：持仓最高价 → 入场价，越高越不利）
    mae_pct = (mae_high - entry_p) / entry_p * 100 if mae_high is not None and mae_high > 0 else 0.0

    print(f"   ✅ 平空 {fmt_t(exit_ts)} | {exit_p:.4f}"
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
        "mfe_pct":     round(mfe_pct, 4),   # 有利波动% (做空：入场→最低点)
        "mae_pct":     round(mae_pct, 4),   # 不利波动% (做空：最高点→入场)
        "mfe_price":   round(mfe_low, 6) if mfe_low != float("inf") else 0.0,
        "mae_price":   round(mae_high, 6),
        "cap_after":   round(cap_after, 4),
    })


# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    run_backtest()
