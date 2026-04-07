"""
ETH 2H 趋势反转做空 — A+B 胜率提升专项测试
数据拉取一次，以 A+B 为底座，测试新增过滤条件 D/E/F 及其组合

基准(A+B):
  进场: 4H MACD死叉[1]  AND  close<日线WMA  AND  rsi[1]<50
  离场: 2H MACD金叉[1]  AND  RSI[1]>=50  AND  close>日线WMA  +  止盈3%/止损6%/保本

新增过滤候选:
  D  - 2H MACD本身偏空: macd_s1 < signal_s1（2H趋势方向确认）
  E  - 日线WMA斜率向下: daily_wma < 前一日daily_wma（趋势延续确认）
  F  - 4H RSI < 50:     4H动量偏空（双时间轴动量共振）
"""

import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from collections import Counter

# ─── 固定参数 ──────────────────────────────────────────────────────────────────
COIN            = "ETH"
START_DATE      = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%d")
MACD_FAST, MACD_SLOW, MACD_SIG = 12, 26, 9
RSI_LEN, WMA_LEN                = 14, 15
RSI_EXIT_MIN                    = 50
INITIAL_CAP                     = 10_000.0
BREAKEVEN_PCT                   = 0.03
FEE_RATE                        = 0.0005
TZ_CST  = timezone(timedelta(hours=8))
HL_URL  = "https://api.hyperliquid.xyz/info"
INTERVAL_MS = {"2h": 7_200_000, "4h": 14_400_000, "1d": 86_400_000}


# ─── 数据获取 ──────────────────────────────────────────────────────────────────
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
                if attempt < 2: time.sleep(1.5)
                continue
            return [{"t": int(c["t"]), "o": float(c["o"]), "h": float(c["h"]),
                     "l": float(c["l"]), "c": float(c["c"])} for c in data]
        except Exception as e:
            print(f"  [{interval}] 第{attempt+1}次错误: {e}")
            if attempt < 2: time.sleep(2.0)
    return []


def fetch_hl(coin, interval, start_str, extra_days=0):
    itvl_ms   = INTERVAL_MS[interval]
    batch_ms  = itvl_ms * 500
    start_dt  = datetime.strptime(start_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
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
            cur_start += batch_ms + itvl_ms
            empty_cnt += 1
            if empty_cnt >= 5: break
        time.sleep(0.3)
    if not rows:
        return pd.DataFrame(columns=["t","o","h","l","c"])
    df = (pd.DataFrame(rows).drop_duplicates("t")
            .sort_values("t").reset_index(drop=True))
    df["time"] = pd.to_datetime(df["t"], unit="ms", utc=True)
    return df


# ─── 指标 ──────────────────────────────────────────────────────────────────────
def add_macd(df):
    ef = df["c"].ewm(span=MACD_FAST, adjust=False).mean()
    es = df["c"].ewm(span=MACD_SLOW, adjust=False).mean()
    df["macd"]   = ef - es
    df["signal"] = df["macd"].ewm(span=MACD_SIG, adjust=False).mean()
    return df

def add_rsi(df):
    d = df["c"].diff()
    g = d.clip(lower=0);  l = (-d).clip(lower=0)
    ag = g.ewm(com=RSI_LEN-1, adjust=False).mean()
    al = l.ewm(com=RSI_LEN-1, adjust=False).mean()
    rs = ag / al.replace(0, np.nan)
    df["rsi"] = 100 - 100 / (1 + rs)
    return df

def wma_series(s, p):
    w = np.arange(1, p+1, dtype=float)
    return s.rolling(p).apply(lambda x: np.dot(x,w)/w.sum(), raw=True)


# ─── 单次回测核心 ───────────────────────────────────────────────────────────────
def run_one(df2h, sl_pct, tp_pct, use_A, use_B, use_D=False, use_E=False, use_F=False):
    """
    底座: A(close<WMA) + B(rsi<50)
    use_D: 2H MACD偏空确认 (macd_s1 < signal_s1)
    use_E: 日线WMA斜率向下 (daily_wma < daily_wma_prev)
    use_F: 4H RSI < 50
    sl_pct / tp_pct: 止损止盈比例
    """
    cap = INITIAL_CAP
    pos = None; ep = sl = tp = 0.0; be_on = False
    p_entry = p_exit = False
    trades = []

    for i in range(len(df2h)):
        row   = df2h.iloc[i]
        bar_t = int(row["t"])
        bar_o = float(row["o"])
        bar_h = float(row["h"])
        bar_l = float(row["l"])
        bar_c = float(row["c"])

        # ① 进场
        if p_entry and pos is None:
            ep = bar_o; pos = "SHORT"
            sl = round(ep*(1+sl_pct), 8)
            tp = round(ep*(1-tp_pct), 8)
            be_on = p_entry = False
            continue

        # ② 信号平仓
        if p_exit and pos == "SHORT":
            qty       = cap / ep
            gross     = (ep - bar_o) * qty
            fee       = (ep + bar_o) * qty * FEE_RATE
            pnl       = gross - fee
            pnl_pct   = (ep - bar_o) / ep * 100
            trades.append({"r":"信号离场","p":round(pnl_pct,4),"n":round(pnl,4)})
            cap += pnl; pos = None; ep = sl = tp = 0.0; be_on = p_exit = False
            continue

        # ③ 持仓风控
        if pos == "SHORT":
            def record(price, reason):
                nonlocal cap, pos, ep, sl, tp, be_on
                qty   = cap / ep
                gross = (ep - price) * qty
                fee   = (ep + price) * qty * FEE_RATE
                pnl   = gross - fee
                pnl_p = (ep - price) / ep * 100
                trades.append({"r":reason,"p":round(pnl_p,4),"n":round(pnl,4)})
                cap += pnl; pos = None; ep = sl = tp = 0.0; be_on = False

            if bar_o >= sl: record(bar_o, "跳空止损"); continue
            if bar_o <= tp: record(bar_o, "跳空止盈"); continue
            if bar_l <= tp: record(tp,    "止盈");     continue
            if bar_h >= sl: record(sl, "保本止损" if be_on else "止损"); continue
            if (not be_on) and bar_c <= ep*(1-BREAKEVEN_PCT):
                be_on = True; sl = ep
            if bool(row["exit_sig"]): p_exit = True

        # ④ 空仓进场
        if pos is None and not p_exit:
            entry_ok = bool(row["dc4h"])
            if use_A: entry_ok = entry_ok and bool(row["belowDaily"])
            if use_B: entry_ok = entry_ok and (float(row["rsi_s1"]) < RSI_EXIT_MIN)
            if use_D: entry_ok = entry_ok and bool(row["macd_bias"])
            if use_E: entry_ok = entry_ok and bool(row["wma_down"])
            if use_F: entry_ok = entry_ok and bool(row["rsi4h_below50"])
            if entry_ok: p_entry = True

    # 统计
    if not trades:
        return {"trades":0,"ret":0,"wr":0,"pf":0,"mdd":0}
    wins   = [t for t in trades if t["n"] > 0]
    losses = [t for t in trades if t["n"] <= 0]
    sw     = sum(t["n"] for t in wins)
    sl_sum = abs(sum(t["n"] for t in losses))
    eq = [INITIAL_CAP]
    for t in trades: eq.append(eq[-1]+t["n"])
    peak = mdd = 0.0
    for e in eq:
        if e > peak: peak = e
        dd = (peak-e)/peak if peak else 0.0
        if dd > mdd: mdd = dd
    return {
        "trades": len(trades),
        "ret":    round((cap-INITIAL_CAP)/INITIAL_CAP*100, 2),
        "wr":     round(len(wins)/len(trades)*100, 1),
        "pf":     round(sw/sl_sum, 2) if sl_sum else 99.0,
        "mdd":    round(mdd*100, 2),
        "cap":    round(cap, 2),
        "dist":   dict(Counter(t["r"] for t in trades)),
    }


# ─── 主流程 ───────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("  ETH 2H 趋势反转做空 — A+B 胜率提升专项测试")
    print("=" * 60)
    print(f"\n📥 拉取 {COIN} K线 (起始: {START_DATE})...")

    df_2h = fetch_hl(COIN, "2h", START_DATE)
    df_4h = fetch_hl(COIN, "4h", START_DATE)
    df_1d = fetch_hl(COIN, "1d", START_DATE, extra_days=60)

    for name, df in [("2H",df_2h),("4H",df_4h),("日线",df_1d)]:
        print(f"  {name}: {len(df)}根  [{df['time'].iloc[0].strftime('%Y-%m-%d')} ~ {df['time'].iloc[-1].strftime('%Y-%m-%d')}]")

    # ── 指标 ──────────────────────────
    df_2h = add_macd(df_2h); df_2h = add_rsi(df_2h)
    df_4h = add_macd(df_4h); df_4h = add_rsi(df_4h)
    df_1d["wma"] = wma_series(df_1d["c"], WMA_LEN)

    # 2H 金叉[1] / RSI[1]
    df_2h["m_s1"] = df_2h["macd"].shift(1); df_2h["s_s1"] = df_2h["signal"].shift(1)
    df_2h["m_s2"] = df_2h["macd"].shift(2); df_2h["s_s2"] = df_2h["signal"].shift(2)
    df_2h["gc2h"]   = (df_2h["m_s2"] <= df_2h["s_s2"]) & (df_2h["m_s1"] > df_2h["s_s1"])
    df_2h["rsi_s1"] = df_2h["rsi"].shift(1)
    # D: 2H MACD偏空确认（上一根 macd < signal，整体偏空）
    df_2h["macd_bias"] = df_2h["m_s1"] < df_2h["s_s1"]

    # 4H 死叉[1] / RSI
    df_4h["m_s1"] = df_4h["macd"].shift(1); df_4h["s_s1"] = df_4h["signal"].shift(1)
    df_4h["m_s2"] = df_4h["macd"].shift(2); df_4h["s_s2"] = df_4h["signal"].shift(2)
    df_4h["dc4h"]        = (df_4h["m_s2"] >= df_4h["s_s2"]) & (df_4h["m_s1"] < df_4h["s_s1"])
    # F: 4H RSI < 50
    df_4h["rsi4h_s1"]    = df_4h["rsi"].shift(1)
    df_4h["rsi4h_below50"] = df_4h["rsi4h_s1"] < 50

    # 日线 WMA / 斜率
    df_1d["wma_s1"]   = df_1d["wma"].shift(1)
    df_1d["wma_prev"] = df_1d["wma"].shift(2)

    # merge 4H → 2H
    for df in [df_2h, df_4h, df_1d]: df.sort_values("t", inplace=True)
    df_2h = pd.merge_asof(df_2h,
                          df_4h[["t","dc4h","rsi4h_below50"]],
                          on="t", direction="backward")

    # 4H边沿检测（第二根2H bar）
    _4H_MS = 14_400_000
    df_2h["_4h_start"] = (df_2h["t"] // _4H_MS) * _4H_MS
    _is_4h_second = (
        (df_2h["_4h_start"] == df_2h["_4h_start"].shift(1).fillna(-1)) &
        (df_2h["_4h_start"] != df_2h["_4h_start"].shift(2).fillna(-1))
    )
    df_2h["dc4h"] = df_2h["dc4h"].fillna(False) & _is_4h_second

    # 日线WMA → 2H (用 wma_s1 = 前一天WMA，防重绘)
    df_2h = pd.merge_asof(df_2h,
                          df_1d[["t","wma_s1","wma_prev"]].rename(
                              columns={"wma_s1":"daily_wma","wma_prev":"daily_wma_prev"}),
                          on="t", direction="backward")
    df_2h = df_2h.dropna(subset=["daily_wma"]).reset_index(drop=True)

    # A: belowDaily
    df_2h["belowDaily"] = df_2h["c"] < df_2h["daily_wma"]
    # aboveDaily（离场用）
    df_2h["aboveDaily"] = df_2h["c"] > df_2h["daily_wma"]
    # E: 日线WMA斜率向下
    df_2h["wma_down"]   = df_2h["daily_wma"] < df_2h["daily_wma_prev"]

    # 离场信号（AND逻辑，固定）
    df_2h["exit_sig"] = (
        df_2h["gc2h"].fillna(False) &
        (df_2h["rsi_s1"].fillna(0) >= RSI_EXIT_MIN) &
        df_2h["aboveDaily"].fillna(False)
    )

    # 信号统计
    print(f"\n  信号统计:")
    print(f"    dc4h(第2根2H): {df_2h['dc4h'].sum()} 次")
    print(f"    belowDaily(A): {df_2h['belowDaily'].sum()} 根")
    print(f"    rsi_s1<50 (B): {(df_2h['rsi_s1']<50).sum()} 根")
    print(f"    macd_bias (D): {df_2h['macd_bias'].sum()} 根")
    print(f"    wma_down  (E): {df_2h['wma_down'].sum()} 根")
    print(f"    rsi4h<50  (F): {df_2h['rsi4h_below50'].sum()} 根")

    # ── 配置表（以A+B为底座，逐步叠加D/E/F）──────────────────
    SL, TP = 0.03, 0.06   # A+B底座保持3%/6%
    configs = [
        # 名称,        A,    B,    D,     E,     F
        ("A+B(基准)",  True, True, False, False, False),
        ("A+B+D",      True, True, True,  False, False),
        ("A+B+E",      True, True, False, True,  False),
        ("A+B+F",      True, True, False, False, True ),
        ("A+B+D+E",    True, True, True,  True,  False),
        ("A+B+D+F",    True, True, True,  False, True ),
        ("A+B+E+F",    True, True, False, True,  True ),
        ("A+B+D+E+F",  True, True, True,  True,  True ),
    ]

    results = []
    for name, a, b, d, e, f in configs:
        print(f"\n  运行: {name} ...")
        r = run_one(df_2h.copy(), SL, TP, a, b, d, e, f)
        r["name"] = name
        results.append(r)
        dist_str = "  ".join(f"{k}:{v}" for k,v in r.get("dist",{}).items())
        print(f"    → 收益:{r['ret']:+.2f}%  笔数:{r['trades']}  胜率:{r['wr']}%  "
              f"PF:{r['pf']}  回撤:{r['mdd']}%")
        print(f"       [{dist_str}]")

    # ── 对比汇总表 ────────────────────
    print("\n" + "=" * 80)
    print(f"{'配置':<12} {'收益':>8} {'笔数':>5} {'胜率':>7} {'盈利因子':>8} {'最大回撤':>9} {'最终资金':>12}")
    print("-" * 80)
    max_ret = max(x["ret"] for x in results)
    max_wr  = max(x["wr"]  for x in results)
    min_mdd = min(x["mdd"] for x in results)
    for r in results:
        flags = ""
        if r["ret"] == max_ret: flags += " ★"
        if r["wr"]  == max_wr:  flags += " ▲"
        if r["mdd"] == min_mdd: flags += " ▼"
        print(f"{r['name']:<12} {r['ret']:>+7.2f}% {r['trades']:>5} "
              f"{r['wr']:>6.1f}% {r['pf']:>8.2f} {r['mdd']:>8.2f}% "
              f"${r['cap']:>11,.2f}{flags}")
    print("=" * 80)
    print("  ★=最高收益  ▲=最高胜率  ▼=最低回撤")


if __name__ == "__main__":
    main()
