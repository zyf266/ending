"""
HYPE 4H进场/1H离场 做空策略 TP/SL 网格扫描
进场: (4H MACD死叉[1] OR 4H下穿日线WMA) AND 4H MACD[1]偏空(D)
离场: 1H MACD金叉[1]
扫描: SL 1%~10%  TP 3%~20%（找 HYPE 最优止盈止损组合）
数据: 近半年
"""

import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from collections import Counter

# ─── 固定参数 ──────────────────────────────────────────────────────────────────
COIN            = "HYPE"
START_DATE      = (datetime.now(timezone.utc) - timedelta(days=180)).strftime("%Y-%m-%d")
MACD_FAST, MACD_SLOW, MACD_SIG = 12, 26, 9
WMA_LEN         = 15
INITIAL_CAP     = 10_000.0
BREAKEVEN_PCT   = 0.05   # 保本触发（可被 be_pct 参数覆盖）
FEE_RATE        = 0.0005
TZ_CST  = timezone(timedelta(hours=8))
HL_URL  = "https://api.hyperliquid.xyz/info"
INTERVAL_MS = {"1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


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
            print(f"  [{interval}] 错误: {e}")
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
            rows.extend(chunk); cur_start = chunk[-1]["t"] + itvl_ms; empty_cnt = 0
        else:
            cur_start += batch_ms + itvl_ms; empty_cnt += 1
            if empty_cnt >= 5: break
        time.sleep(0.3)
    if not rows:
        return pd.DataFrame(columns=["t","o","h","l","c"])
    df = (pd.DataFrame(rows).drop_duplicates("t").sort_values("t").reset_index(drop=True))
    df["time"] = pd.to_datetime(df["t"], unit="ms", utc=True)
    return df


# ─── 指标 ──────────────────────────────────────────────────────────────────────
def add_macd(df):
    ef = df["c"].ewm(span=MACD_FAST, adjust=False).mean()
    es = df["c"].ewm(span=MACD_SLOW, adjust=False).mean()
    df["macd"]   = ef - es
    df["signal"] = df["macd"].ewm(span=MACD_SIG, adjust=False).mean()
    return df

def wma_series(s, p):
    w = np.arange(1, p+1, dtype=float)
    return s.rolling(p).apply(lambda x: np.dot(x,w)/w.sum(), raw=True)


# ─── 数据预处理（只算一次，供 run_one 复用）──────────────────────────────────
def prepare_df(df_1h_raw, df_4h_raw, df_1d_raw):
    df_1h = df_1h_raw.copy()
    df_4h = df_4h_raw.copy()
    df_1d = df_1d_raw.copy()

    # 指标计算
    df_1h = add_macd(df_1h)
    df_4h = add_macd(df_4h)
    df_1d["wma"] = wma_series(df_1d["c"], WMA_LEN)

    # 4H 死叉[1] + D条件（偏空）
    df_4h["m_s1"] = df_4h["macd"].shift(1); df_4h["s_s1"] = df_4h["signal"].shift(1)
    df_4h["m_s2"] = df_4h["macd"].shift(2); df_4h["s_s2"] = df_4h["signal"].shift(2)
    df_4h["dc4h"]      = (df_4h["m_s2"] >= df_4h["s_s2"]) & (df_4h["m_s1"] < df_4h["s_s1"])
    df_4h["macd_bias"] = df_4h["m_s1"] < df_4h["s_s1"]   # D条件: 4H MACD[1]偏空

    # 1H 金叉[1]（离场）
    df_1h["m_s1"] = df_1h["macd"].shift(1); df_1h["s_s1"] = df_1h["signal"].shift(1)
    df_1h["m_s2"] = df_1h["macd"].shift(2); df_1h["s_s2"] = df_1h["signal"].shift(2)
    df_1h["gc1h"] = (df_1h["m_s2"] <= df_1h["s_s2"]) & (df_1h["m_s1"] > df_1h["s_s1"])

    df_1d["wma_s1"] = df_1d["wma"].shift(1)
    for df in [df_1h, df_4h, df_1d]: df.sort_values("t", inplace=True)

    # 4H WMA下穿（在4H时间轴上计算）
    _4h_wma = pd.merge_asof(df_4h[["t"]].copy(),
                             df_1d[["t","wma_s1"]].rename(columns={"wma_s1":"_dw"}),
                             on="t", direction="backward")
    df_4h["_dw"] = _4h_wma["_dw"].values
    df_4h["crossunder_wma"] = (
        (df_4h["c"].shift(1) >= df_4h["_dw"].shift(1)) &
        (df_4h["c"] < df_4h["_dw"])
    ).fillna(False)

    # 4H信号 → 1H
    df_1h = pd.merge_asof(df_1h,
                          df_4h[["t","dc4h","crossunder_wma","macd_bias"]],
                          on="t", direction="backward")

    # 边沿检测：4H信号仅在该4H周期第4根（最后一根）1H bar可见
    _4H_MS = 14_400_000
    df_1h["_4h_start"] = (df_1h["t"] // _4H_MS) * _4H_MS
    _is_4h_last = (
        (df_1h["_4h_start"] == df_1h["_4h_start"].shift(1).fillna(-1)) &
        (df_1h["_4h_start"] == df_1h["_4h_start"].shift(2).fillna(-1)) &
        (df_1h["_4h_start"] == df_1h["_4h_start"].shift(3).fillna(-1)) &
        (df_1h["_4h_start"] != df_1h["_4h_start"].shift(4).fillna(-1))
    )
    df_1h["dc4h"]          = df_1h["dc4h"].fillna(False) & _is_4h_last
    df_1h["crossunder_wma"] = df_1h["crossunder_wma"].fillna(False) & _is_4h_last

    # 日线WMA → 1H
    df_1h = pd.merge_asof(df_1h,
                          df_1d[["t","wma_s1"]].rename(columns={"wma_s1":"daily_wma"}),
                          on="t", direction="backward")
    df_1h = df_1h.dropna(subset=["daily_wma"]).reset_index(drop=True)

    # 进场/离场信号
    df_1h["entry_sig"] = (
        (df_1h["dc4h"].fillna(False) | df_1h["crossunder_wma"].fillna(False)) &
        df_1h["macd_bias"].fillna(False)
    )
    df_1h["exit_sig"] = df_1h["gc1h"].fillna(False)
    return df_1h


# ─── 单次回测（循环在1H时间轴）──────────────────────────────────────────────
def run_one(df1h, sl_pct, tp_pct, be_pct=None, lockin_trig=0.0, lockin_prot=0.0):
    """
    sl_pct      : 止损比例（如 0.03 = 3%）
    tp_pct      : 止盈比例（如 0.06 = 6%）
    be_pct      : 保本触发比例（None=用全局 BREAKEVEN_PCT）
    lockin_trig : 锁利触发（0=不启用，如 0.04=盈利4%时激活）
    lockin_prot : 锁利保护比例（如 0.02=锁住2%利润）
    """
    _be_pct = be_pct if be_pct is not None else BREAKEVEN_PCT
    cap = INITIAL_CAP
    pos = None; ep = sl = tp = 0.0; be_on = lockin_on = False
    p_entry = p_exit = False
    trades = []

    for i in range(len(df1h)):
        row   = df1h.iloc[i]
        bar_o = float(row["o"]); bar_h = float(row["h"])
        bar_l = float(row["l"]); bar_c = float(row["c"])

        # ① 进场执行
        if p_entry and pos is None:
            ep = bar_o; pos = "SHORT"
            sl = round(ep*(1+sl_pct), 8); tp = round(ep*(1-tp_pct), 8)
            be_on = lockin_on = p_entry = False
            continue

        # ② 信号离场执行
        if p_exit and pos == "SHORT":
            qty   = cap / ep
            gross = (ep - bar_o) * qty
            fee   = (ep + bar_o) * qty * FEE_RATE
            pnl   = gross - fee
            trades.append({"r":"信号离场","p":round((ep-bar_o)/ep*100,4),"n":round(pnl,4)})
            cap += pnl; pos = None; ep = sl = tp = 0.0; be_on = lockin_on = p_exit = False
            continue

        # ③ 持仓风控
        if pos == "SHORT":
            def record(price, reason):
                nonlocal cap, pos, ep, sl, tp, be_on, lockin_on
                qty   = cap / ep
                gross = (ep - price) * qty
                fee   = (ep + price) * qty * FEE_RATE
                pnl   = gross - fee
                trades.append({"r":reason,"p":round((ep-price)/ep*100,4),"n":round(pnl,4)})
                cap += pnl; pos = None; ep = sl = tp = 0.0; be_on = lockin_on = False

            if bar_o >= sl: record(bar_o, "跳空止损"); continue
            if bar_o <= tp: record(bar_o, "跳空止盈"); continue
            if bar_l <= tp: record(tp,    "止盈");     continue
            if bar_h >= sl:
                record(sl, "保本止损" if be_on else ("锁利止损" if lockin_on else "止损"))
                continue

            # 锁利激活（优先于保本）
            if lockin_trig > 0 and (not lockin_on) and bar_c <= ep*(1-lockin_trig):
                lockin_on = True
                new_sl = round(ep*(1-lockin_prot), 8)
                if new_sl < sl: sl = new_sl

            # 保本激活
            if (not be_on) and bar_c <= ep*(1-_be_pct):
                be_on = True
                be_sl = ep
                if be_sl < sl: sl = be_sl

            # 离场信号：1H MACD金叉[1]
            if bool(row["exit_sig"]): p_exit = True

        # ④ 进场信号检测
        if pos is None and not p_exit:
            if bool(row["entry_sig"]): p_entry = True

    # 统计
    if not trades:
        return {"trades":0,"ret":0,"wr":0,"pf":0,"mdd":0,"cap":INITIAL_CAP,"dist":{}}
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
    print("=" * 70)
    print(f"  {COIN} 4H进场/1H离场 做空策略 TP/SL 网格扫描")
    print(f"  起始: {START_DATE}  手续费: {FEE_RATE*100*2:.2f}%双边")
    print("=" * 70)

    print(f"\n📥 拉取 {COIN} K线...")
    df_1h = fetch_hl(COIN, "1h", START_DATE)
    df_4h = fetch_hl(COIN, "4h", START_DATE)
    df_1d = fetch_hl(COIN, "1d", START_DATE, extra_days=60)

    for name, df in [("1H",df_1h),("4H",df_4h),("日线",df_1d)]:
        print(f"  {name}: {len(df)}根  [{df['time'].iloc[0].strftime('%Y-%m-%d')} ~ {df['time'].iloc[-1].strftime('%Y-%m-%d')}]")

    # 预处理（只算一次）
    df1h = prepare_df(df_1h, df_4h, df_1d)
    print(f"\n  进场信号: {df1h['entry_sig'].sum()}次  "
          f"(dc4h={df1h['dc4h'].sum()}  cross={df1h['crossunder_wma'].sum()}  "
          f"bias={df1h['macd_bias'].sum()}根)")
    print(f"  离场信号: {df1h['exit_sig'].sum()}次  (1H MACD金叉[1])")

    # ── TP×SL 网格扫描 ──────────────────────────────────────────────────────
    # HYPE 波动比 ETH 更大，范围覆盖 SL 1%~10%，TP 3%~20%
    SL_RANGE = [x/100 for x in range(1, 11)]          # 1%~10%
    TP_RANGE = [x/100 for x in range(3, 21)]           # 3%~20%（步长1%）
    BE_PCT   = 0.05
    LOCKIN_T = 0.04
    LOCKIN_P = 0.02

    print(f"\n🔍 网格扫描 SL:{SL_RANGE[0]*100:.0f}%~{SL_RANGE[-1]*100:.0f}%  "
          f"TP:{TP_RANGE[0]*100:.0f}%~{TP_RANGE[-1]*100:.0f}%  "
          f"共{len(SL_RANGE)*len(TP_RANGE)}组...")

    results = []
    for sl in SL_RANGE:
        for tp in TP_RANGE:
            r = run_one(df1h, sl, tp, be_pct=BE_PCT,
                        lockin_trig=LOCKIN_T, lockin_prot=LOCKIN_P)
            r["name"] = f"SL{int(sl*100)}%TP{int(tp*100)}%"
            r["sl"] = sl; r["tp"] = tp
            results.append(r)

    # ── 汇总表（按盈利因子排序）────────────────────────────────────────────
    results_sorted = sorted(results, key=lambda x: x["pf"], reverse=True)
    print("\n" + "=" * 105)
    print(f"{'配置':<18} {'收益':>8} {'笔数':>5} {'胜率':>7} {'盈利因子':>8} {'最大回撤':>9} {'止损':>6} {'止盈':>6} {'信号离场':>8} {'资金':>11}")
    print("-" * 105)
    max_ret = max(x["ret"] for x in results)
    max_pf  = max(x["pf"]  for x in results)
    min_mdd = min(x["mdd"] for x in results if x["trades"] > 0)
    for r in results_sorted[:30]:   # 只打印前30名
        d = r.get("dist", {})
        sl_cnt  = d.get("止损",0) + d.get("保本止损",0) + d.get("跳空止损",0) + d.get("锁利止损",0)
        tp_cnt  = d.get("止盈",0) + d.get("跳空止盈",0)
        sig_cnt = d.get("信号离场", 0)
        flags = ""
        if r["ret"] == max_ret: flags += "★收益"
        if r["pf"]  == max_pf:  flags += "★PF"
        if r["mdd"] == min_mdd: flags += "★回撤"
        print(f"{r['name']:<18} {r['ret']:>+7.2f}% {r['trades']:>5} "
              f"{r['wr']:>6.1f}% {r['pf']:>8.2f} {r['mdd']:>8.2f}% "
              f"{sl_cnt:>5}次 {tp_cnt:>5}次 {sig_cnt:>7}次 ${r['cap']:>10,.2f} {flags}")
    print("=" * 105)

    # 最优解推荐（综合评分）
    valid = [r for r in results if r["trades"] >= 5]
    if valid:
        best = max(valid, key=lambda x: x["pf"]*0.4 + x["ret"]/100*0.3 - x["mdd"]/100*0.3)
        print(f"\n🏆 综合最优解: {best['name']}")
        print(f"   SL={int(best['sl']*100)}%  TP={int(best['tp']*100)}%  "
              f"BE={int(BE_PCT*100)}%  锁利={int(LOCKIN_T*100)}%→{int(LOCKIN_P*100)}%")
        print(f"   收益:{best['ret']:+.2f}%  胜率:{best['wr']}%  "
              f"盈利因子:{best['pf']}  回撤:{best['mdd']}%")


if __name__ == "__main__":
    main()
