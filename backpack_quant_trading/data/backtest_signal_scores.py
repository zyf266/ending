"""历史买入信号 AI 评分回测。

读取 TradingView 策略交易列表 CSV，在每条「趋势入场」信号发生的时刻，
从 Hyperliquid 拉取当时可见的 K 线、计算与实盘相同的指标，并调用 DeepSeek 评分；
最后与实际盈亏对照输出 CSV / JSON。

用法（项目根目录）:
  python backpack_quant_trading/data/backtest_signal_scores.py \\
    --csv "自适应做多_-_利润保护版_OKX_HYPEUSDT.P_2026-05-29_6e039.csv"

仅本地指标、不调 DeepSeek:
  python backpack_quant_trading/data/backtest_signal_scores.py --csv ... --local-only

需要环境变量 DEEPSEEK_API_KEY（--local-only 时不需要）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import pandas as pd

# 保证可从项目根目录直接运行
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# 与 run_api 一致：自动加载 backpack_quant_trading/.env 中的 DEEPSEEK_API_KEY
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
except ImportError:
    pass

from backpack_quant_trading.core.crypto_signal_scorer import (  # noqa: E402
    _normalize_symbol,
    build_deepseek_user_prompt,
    calibrate_deepseek_structured,
    call_deepseek_score,
    compute_local_buy_score,
    load_config,
)
from backpack_quant_trading.core.crypto_uptrend_scanner import (  # noqa: E402
    MIN_KLINES_FOR_SCAN,
    analyze_uptrend,
    klines_to_df,
)
from backpack_quant_trading.core.hyperliquid_klines import (  # noqa: E402
    INTERVAL_MS,
    fetch_hl_klines_sync,
    hl_bars_to_ohlcv,
    normalize_hl_interval,
    to_hl_coin,
)

DATA_DIR = Path(__file__).resolve().parent
DEFAULT_CSV = _ROOT / "自适应做多_-_利润保护版_OKX_HYPEUSDT.P_2026-05-29_6e039.csv"


def _parse_symbol_from_filename(path: Path) -> str:
    name = path.name.upper()
    m = re.search(r"([A-Z0-9]+USDT\.P)", name)
    if m:
        return m.group(1)
    m = re.search(r"_([A-Z]{2,10})USDT", name)
    if m:
        return f"{m.group(1)}USDT"
    return "HYPEUSDT"


def _parse_dt(text: str, tz_name: str) -> datetime:
    tz = ZoneInfo(tz_name)
    raw = (text or "").strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            naive = datetime.strptime(raw, fmt)
            return naive.replace(tzinfo=tz)
        except ValueError:
            continue
    raise ValueError(f"无法解析时间: {text!r}")


def load_tv_trades(csv_path: Path, *, tz_name: str, min_size: float) -> List[Dict[str, Any]]:
    """解析 TV 交易列表，合并同一 Trade number 的进出场。"""
    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    col_map = {c.strip(): c for c in df.columns}
    type_col = col_map.get("类型") or "类型"
    time_col = col_map.get("日期和时间") or "日期和时间"
    signal_col = col_map.get("信号") or "信号"
    trade_col = col_map.get("Trade number") or "Trade number"
    price_col = col_map.get("价格 USDT") or "价格 USDT"
    size_col = col_map.get("大小（数量）") or "大小（数量）"
    pnl_pct_col = col_map.get("Net PnL %") or "Net PnL %"
    pnl_usdt_col = col_map.get("Net PnL USDT") or "Net PnL USDT"
    exit_signal_col = signal_col

    entries: Dict[int, Dict[str, Any]] = {}
    exits: Dict[int, Dict[str, Any]] = {}

    for _, row in df.iterrows():
        trade_no = int(row[trade_col])
        kind = str(row[type_col]).strip()
        dt = _parse_dt(str(row[time_col]), tz_name)
        rec = {
            "trade_no": trade_no,
            "time": dt,
            "time_str": dt.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "signal": str(row[signal_col]).strip(),
            "price": float(row[price_col]),
            "size": float(row[size_col]),
            "pnl_pct": float(row[pnl_pct_col]),
            "pnl_usdt": float(row[pnl_usdt_col]),
        }
        if "进场" in kind:
            entries[trade_no] = rec
        elif "出场" in kind:
            exits[trade_no] = rec

    trades: List[Dict[str, Any]] = []
    for trade_no in sorted(entries.keys()):
        ent = entries[trade_no]
        ex = exits.get(trade_no, {})
        if ent["size"] < min_size:
            continue
        if "趋势入场" not in ent.get("signal", ""):
            continue
        trades.append({
            "trade_no": trade_no,
            "entry_time": ent["time"],
            "entry_time_str": ent["time_str"],
            "entry_signal": ent["signal"],
            "entry_price": ent["price"],
            "size": ent["size"],
            "exit_time": ex.get("time"),
            "exit_time_str": ex.get("time_str", ""),
            "exit_signal": ex.get("signal", ""),
            "exit_price": ex.get("price"),
            "pnl_pct": ex.get("pnl_pct", ent["pnl_pct"]),
            "pnl_usdt": ex.get("pnl_usdt", ent["pnl_usdt"]),
            "win": bool((ex.get("pnl_pct", ent["pnl_pct"]) or 0) > 0),
        })
    return trades


def fetch_klines_as_of(
    symbol: str,
    interval: str,
    as_of: datetime,
    *,
    total_limit: int = 100,
) -> Tuple[Optional[List[Dict[str, Any]]], str]:
    """拉取 as_of 时刻及之前已收盘的 K 线（不含未来数据）。"""
    coin = to_hl_coin(symbol)
    iv = normalize_hl_interval(interval)
    ms = INTERVAL_MS.get(iv, 14_400_000)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    end_ms = int(as_of.timestamp() * 1000)
    start_ms = end_ms - ms * (total_limit + 15)

    bars = fetch_hl_klines_sync(coin, iv, start_ms, end_ms)
    if not bars:
        return None, f"Hyperliquid 无 K 线: {coin} {iv} @ {as_of.isoformat()}"

    ohlcv = hl_bars_to_ohlcv(bars)
    ohlcv = [k for k in ohlcv if int(k["time"]) <= end_ms]
    if len(ohlcv) > total_limit:
        ohlcv = ohlcv[-total_limit:]

    if len(ohlcv) < MIN_KLINES_FOR_SCAN:
        return None, (
            f"K 线不足: {coin} {iv} @ {as_of.isoformat()} "
            f"({len(ohlcv)} 根, 需要 >= {MIN_KLINES_FOR_SCAN})"
        )
    return ohlcv, ""


def build_snapshot_at_time(
    symbol: str,
    as_of: datetime,
    *,
    interval: str,
    kline_limit: int,
) -> Tuple[Optional[Dict[str, Any]], str]:
    klines, err = fetch_klines_as_of(symbol, interval, as_of, total_limit=kline_limit)
    if not klines:
        return None, err

    df = klines_to_df(klines)
    is_up, metrics, chart = analyze_uptrend(
        df, min_bars=min(60, len(df) - 1), hl_coin=to_hl_coin(symbol),
    )

    tail = df.tail(10)
    recent_bars = []
    for _, row in tail.iterrows():
        recent_bars.append({
            "time": datetime.fromtimestamp(int(row["time"]) / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "close": round(float(row["close"]), 6),
            "volume": round(float(row["volume"]), 2),
            "rsi14": round(float(row["rsi14"]), 2) if pd.notna(row.get("rsi14")) else None,
            "macd_hist": round(float(row["macd_hist"]), 6) if pd.notna(row.get("macd_hist")) else None,
        })

    sym = _normalize_symbol(symbol)
    snapshot = {
        "symbol": sym,
        "hl_coin": to_hl_coin(symbol),
        "data_source": "hyperliquid",
        "interval": normalize_hl_interval(interval),
        "kline_count": len(df),
        "as_of_utc": as_of.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "scanner_uptrend": is_up,
        "in_top50_uptrend_list": None,
        "metrics": metrics,
        "recent_bars": recent_bars,
        "chart_tail": chart[-60:] if chart else [],
    }
    return snapshot, ""


def score_one_trade(
    trade: Dict[str, Any],
    *,
    symbol: str,
    interval: str,
    kline_limit: int,
    strategy_label: str,
    local_only: bool,
    temperature: float,
) -> Dict[str, Any]:
    as_of = trade["entry_time"]
    snapshot, err = build_snapshot_at_time(
        symbol, as_of, interval=interval, kline_limit=kline_limit,
    )
    row: Dict[str, Any] = {
        "trade_no": trade["trade_no"],
        "entry_time": trade["entry_time_str"],
        "entry_price": trade["entry_price"],
        "exit_time": trade.get("exit_time_str", ""),
        "exit_signal": trade.get("exit_signal", ""),
        "pnl_pct": trade["pnl_pct"],
        "pnl_usdt": trade["pnl_usdt"],
        "win": trade["win"],
        "ok": False,
        "error": "",
    }
    if not snapshot:
        row["error"] = err
        return row

    m = snapshot.get("metrics") or {}
    row.update({
        "ok": True,
        "kline_count": snapshot.get("kline_count"),
        "as_of_utc": snapshot.get("as_of_utc"),
        "scanner_uptrend": snapshot.get("scanner_uptrend"),
        "trend_score": m.get("trend_score"),
        "rsi14": m.get("rsi14"),
        "macd_hist": m.get("macd_hist"),
        "adx14": m.get("adx14"),
        "vol_ratio": m.get("vol_ratio"),
        "recent_change_pct": m.get("recent_change_pct"),
        "return_20_bars_pct": m.get("return_20_bars_pct"),
        "close_at_signal": m.get("close"),
    })

    anchor = compute_local_buy_score(m)
    row["local_anchor_score"] = anchor

    if local_only:
        row["ai_score"] = anchor
        row["grade"] = None
        row["recommendation"] = None
        row["summary"] = "local-only: 仅锚分，未调用 DeepSeek"
        return row

    prompt = build_deepseek_user_prompt(
        _normalize_symbol(symbol),
        "buy",
        snapshot,
        strategy_label=strategy_label,
        signal_note=(
            f"历史回测；信号价={trade['entry_price']}；"
            f"时间={as_of.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}；无未来数据。"
        ),
    )
    ds = call_deepseek_score(prompt, temperature=temperature)
    if not ds.get("ok"):
        row["error"] = ds.get("error", "DeepSeek 失败")
        row["ok"] = False
        return row

    st = calibrate_deepseek_structured(ds.get("structured") or {}, m)
    row.update({
        "ai_score": st.get("score"),
        "grade": st.get("grade"),
        "recommendation": st.get("recommendation"),
        "summary": st.get("summary"),
        "strengths": st.get("strengths"),
        "risks": st.get("risks"),
        "local_anchor_score": st.get("local_anchor_score", anchor),
    })
    return row


def _print_summary(rows: List[Dict[str, Any]]) -> None:
    scored = [r for r in rows if r.get("ok") and r.get("ai_score") is not None]
    local = [r for r in rows if r.get("ok")]
    print("\n========== 回测摘要 ==========")
    print(f"有效信号: {len(local)} / {len(rows)}")
    if not scored:
        print("无 AI 评分结果（可能使用了 --local-only 或 DeepSeek 失败）")
        return

    def _avg(vals: List[float]) -> float:
        return sum(vals) / len(vals) if vals else 0.0

    wins = [r for r in scored if r.get("win")]
    losses = [r for r in scored if not r.get("win")]
    print(f"AI 已评分: {len(scored)} 笔")
    print(f"胜率: {len(wins)}/{len(scored)} = {100*len(wins)/len(scored):.1f}%")
    print(f"平均盈亏%: {_avg([float(r['pnl_pct']) for r in scored]):.2f}%")
    print(f"平均 AI 分: {_avg([float(r['ai_score']) for r in scored if str(r.get('ai_score', '')).replace('.', '', 1).isdigit()]):.1f}")

    for label, subset in [("盈利单", wins), ("亏损单", losses)]:
        if not subset:
            continue
        scores = [float(r["ai_score"]) for r in subset if r.get("ai_score") is not None]
        if scores:
            print(f"  {label} 平均 AI 分: {_avg(scores):.1f}  平均盈亏%: {_avg([float(r['pnl_pct']) for r in subset]):.2f}%")

    buckets = [(80, 101, ">=80"), (60, 80, "60-79"), (0, 60, "<60")]
    print("\n按 AI 分档:")
    for lo, hi, name in buckets:
        b = [r for r in scored if lo <= float(r.get("ai_score") or 0) < hi]
        if not b:
            continue
        wr = 100 * sum(1 for x in b if x.get("win")) / len(b)
        print(f"  {name}: {len(b)} 笔, 胜率 {wr:.0f}%, 均盈亏% {_avg([float(x['pnl_pct']) for x in b]):.2f}%")

    rec_stats: Dict[str, List[Dict]] = {}
    for r in scored:
        rec = str(r.get("recommendation") or "unknown")
        rec_stats.setdefault(rec, []).append(r)
    if rec_stats:
        print("\n按 recommendation:")
        for rec, items in sorted(rec_stats.items()):
            wr = 100 * sum(1 for x in items if x.get("win")) / len(items)
            print(f"  {rec}: {len(items)} 笔, 胜率 {wr:.0f}%, 均盈亏% {_avg([float(x['pnl_pct']) for x in items]):.2f}%")


def main() -> int:
    parser = argparse.ArgumentParser(description="历史买入信号 AI 评分回测")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV, help="TV 策略交易列表 CSV")
    parser.add_argument("--symbol", default="", help="交易对，如 HYPEUSDT；默认从文件名解析")
    parser.add_argument("--interval", default="", help="K 线周期，默认读 scorer 配置 (4h)")
    parser.add_argument("--kline-limit", type=int, default=0, help="K 线根数，默认读配置")
    parser.add_argument("--tz", default="UTC", help="CSV 时间所在时区，如 UTC / Asia/Shanghai")
    parser.add_argument("--min-size", type=float, default=1.0, help="过滤过小仓位（忽略保证金碎片单）")
    parser.add_argument("--strategy-label", default="adaptive_long_profit_protect", help="写入 prompt 的策略名")
    parser.add_argument("--local-only", action="store_true", help="只算本地指标，不调 DeepSeek")
    parser.add_argument("--delay", type=float, default=1.2, help="每笔 DeepSeek 调用间隔秒数")
    parser.add_argument("--output", type=Path, default=None, help="输出 CSV 路径")
    parser.add_argument("--json-output", type=Path, default=None, help="输出 JSON 路径")
    args = parser.parse_args()

    csv_path = args.csv if args.csv.is_absolute() else _ROOT / args.csv
    if not csv_path.is_file():
        print(f"找不到 CSV: {csv_path}", file=sys.stderr)
        return 1

    cfg = load_config()
    symbol = args.symbol or _parse_symbol_from_filename(csv_path)
    interval = args.interval or cfg.get("kline_interval") or "4h"
    kline_limit = args.kline_limit or int(cfg.get("kline_limit") or 100)
    temperature = float(cfg.get("deepseek_temperature") or 0.2)

    trades = load_tv_trades(csv_path, tz_name=args.tz, min_size=args.min_size)
    if not trades:
        print("未解析到符合条件的买入信号（趋势入场 + 仓位 >= min-size）", file=sys.stderr)
        return 1

    stem = csv_path.stem
    out_csv = args.output or DATA_DIR / f"signal_score_backtest_{stem}.csv"
    out_json = args.json_output or DATA_DIR / f"signal_score_backtest_{stem}.json"

    print(f"CSV: {csv_path.name}")
    print(f"标的: {symbol} ({to_hl_coin(symbol)}) | 周期: {interval} | K线: {kline_limit} 根")
    print(f"时区: {args.tz} | 买入信号: {len(trades)} 笔 | DeepSeek: {'关闭' if args.local_only else '开启'}")
    if not args.local_only and not __import__("os").getenv("DEEPSEEK_API_KEY"):
        print("警告: 未设置 DEEPSEEK_API_KEY，DeepSeek 调用将失败；可加 --local-only 先测 K 线", file=sys.stderr)

    results: List[Dict[str, Any]] = []
    for i, trade in enumerate(trades, start=1):
        print(
            f"\n[{i}/{len(trades)}] #{trade['trade_no']} {trade['entry_time_str']} "
            f"价={trade['entry_price']} 实际盈亏={trade['pnl_pct']:.2f}%"
        )
        row = score_one_trade(
            trade,
            symbol=symbol,
            interval=interval,
            kline_limit=kline_limit,
            strategy_label=args.strategy_label,
            local_only=args.local_only,
            temperature=temperature,
        )
        if row.get("ok"):
            extra = f"趋势分={row.get('trend_score')} 规则上涨={row.get('scanner_uptrend')}"
            if row.get("local_anchor_score") is not None:
                extra += f" 锚分={row.get('local_anchor_score')}"
            if row.get("ai_score") is not None:
                extra += f" AI={row.get('ai_score')} ({row.get('grade')}) {row.get('recommendation')}"
            print(f"  -> {extra}")
        else:
            print(f"  -> 失败: {row.get('error')}")
        results.append(row)
        if not args.local_only and i < len(trades):
            time.sleep(max(0.0, args.delay))

    df_out = pd.DataFrame(results)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df_out.to_csv(out_csv, index=False, encoding="utf-8-sig")
    out_json.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n已写入:\n  {out_csv}\n  {out_json}")
    _print_summary(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
