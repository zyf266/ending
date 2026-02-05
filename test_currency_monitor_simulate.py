"""
模拟特别K-倍数策略触发场景
运行: python test_currency_monitor_simulate.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backpack_quant_trading.core.binance_monitor import (
    run_special_k_strategy,
    send_dingtalk_alert,
    fetch_binance_klines,
)


def make_klines(base_price: float, closes: list, base_time: int = 1700000000000) -> list:
    """根据收盘价序列生成 K 线列表"""
    result = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i > 0 else base_price
        h = max(o, c) * 1.002
        l = min(o, c) * 0.998
        result.append({
            "open_time": base_time + i * 7200000,
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": 1000.0,
            "close_time": base_time + (i + 1) * 7200000 - 1,
        })
    return result


def simulate_with_real_data():
    """用真实币安数据检测当前是否触发"""
    # 【修复】改为合约市场常用币种
    test_symbol = "1000SHIBUSDT"  # SHIB 合约，波动大更容易触发
    print(f"获取 币安{test_symbol} 2小时 K线...")
    symbol_klines = fetch_binance_klines(test_symbol, "2h", limit=500)
    eth_klines = fetch_binance_klines("ETHUSDT", "2h", limit=500)
    if not symbol_klines or not eth_klines:
        print("获取K线失败")
        return False
    triggered = run_special_k_strategy(symbol_klines, eth_klines)
    print(f"当前真实数据策略触发: {triggered}")
    return triggered


def simulate_with_mock_data():
    """
    构造满足条件的模拟数据：先跌后涨产生金叉 + 连阳4根 + 涨幅强于ETH
    """
    base = 100.0
    eth_base = 3000.0
    # 前 60 根下跌
    symbol_closes = [base - i * 0.15 for i in range(60)]
    # 接着 40 根上涨（易产生金叉）
    symbol_closes += [base - 9 + i * 0.25 for i in range(40)]
    # 最后 4 根连阳，涨幅 5%
    for _ in range(4):
        symbol_closes.append(symbol_closes[-1] * 1.0122)
    # ETH 同步长度，涨幅约 1%
    eth_closes = [eth_base + i * 0.1 for i in range(len(symbol_closes) - 4)]
    for _ in range(4):
        eth_closes.append(eth_closes[-1] * 1.0025)

    symbol_klines = make_klines(base, symbol_closes)
    eth_klines = make_klines(eth_base, eth_closes)
    triggered = run_special_k_strategy(symbol_klines, eth_klines)
    print(f"模拟数据策略触发: {triggered}")
    return triggered


def send_test_dingtalk():
    """直接发送一条模拟钉钉，展示触发时的消息格式"""
    # 【修复】改为合约市场常用币种
    ok = send_dingtalk_alert("1000SHIBUSDT", "2小时", "【模拟测试】品种涨幅强于ETH且满足连阳")
    print(f"钉钉模拟发送: {'成功' if ok else '失败（请检查 DINGTALK_TOKEN）'}")
    return ok


if __name__ == "__main__":
    print("=" * 55)
    print("币种监视 - 策略触发模拟")
    print("=" * 55)

    print("\n[1] 真实数据检测（1000SHIBUSDT 2h 合约市场）")
    print("-" * 40)
    simulate_with_real_data()

    print("\n[2] 模拟数据检测")
    print("-" * 40)
    simulate_with_mock_data()

    print("\n[3] 钉钉消息模拟（发送到您的钉钉群）")
    print("-" * 40)
    send_test_dingtalk()

    print("\n" + "=" * 55)
    print("完成。若钉钉发送成功，您将在钉钉群看到异动消息。")
    print("=" * 55)
