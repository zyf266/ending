"""
HYPE 做空策略功能测试脚本
测试内容:
  1.  sell 信号 → 开空仓，SL/TP/保本价格正确
  2.  buy 信号  → TV 平仓
  3.  无仓位时 buy 信号 → 忽略
  4.  已有仓位时重复 sell 信号 → 忽略
  5.  止损触发 (价格上涨超过 SL)
  6.  止盈触发 (价格下跌低于 TP)
  7.  保本激活 (盈利 >= 3% 时止损线移到成本价)
  8.  保本止损触发 (保本激活后价格回升到成本价以上)
  9.  盈利不足 3% 时保本不触发
  10. 止盈/止损平仓后再收到 buy 信号 → 忽略
  11. 完整交易流程: 开仓 → 保本激活 → TV 平仓
  12. 完整流程: 开仓 → 保本激活 → 保本止损自动平仓
"""

import asyncio
import sys
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

# 确保项目根目录在 Python 路径中
sys.path.insert(0, r"C:\Users\A1\PycharmProjects\PythonProject - 副本")

from backpack_quant_trading.strategy.hype_adaptive_short import (
    HYPEAdaptiveShortStrategy,
    TVSignal,
)

# =====================================================================
# 辅助函数
# =====================================================================

def make_strategy(
    entry_price: float = None,
    position: str = None,
    sl_pct: float = 0.03,
    tp_pct: float = 0.06,
    be_pct: float = 0.03,
    margin: float = 20.0,
    leverage: int = 50,
) -> HYPEAdaptiveShortStrategy:
    """
    创建带 Mock 客户端的策略实例
    可选预设已持仓状态 (position="SHORT", entry_price=xxxx)
    """
    with patch(
        "backpack_quant_trading.strategy.hype_adaptive_short.HyperliquidAPIClient"
    ):
        strategy = HYPEAdaptiveShortStrategy(
            symbol="ETH",
            private_key="test_key",
            stop_loss_pct=sl_pct,
            take_profit_pct=tp_pct,
            break_even_pct=be_pct,
            margin_amount=margin,
            leverage=leverage,
        )

    # 替换为完整 Mock 客户端
    mock_client = AsyncMock()
    mock_client._get_session = AsyncMock()
    mock_client.close = AsyncMock()
    mock_client.get_balance = AsyncMock(return_value=1000.0)
    mock_client.get_positions = AsyncMock(return_value=[])
    mock_client.get_price = AsyncMock(return_value=entry_price or 2000.0)
    mock_client.place_order = AsyncMock(return_value={"status": "OK"})
    strategy.client = mock_client

    # 预设持仓状态（跳过实际下单流程直接设置仓位）
    if position == "SHORT" and entry_price:
        strategy.position = "SHORT"
        strategy.entry_price = float(entry_price)
        strategy.position_size = round((margin * leverage) / entry_price, 4)
        strategy.current_sl = entry_price * (1 + sl_pct)
        strategy.current_tp = entry_price * (1 - tp_pct)
        strategy.break_even_activated = False
        strategy.entry_time = datetime.now()
        # 让 sync_position 返回当前状态
        mock_client.get_positions = AsyncMock(return_value=[
            {"side": "SHORT", "szi": -strategy.position_size, "entryPx": str(entry_price)}
        ])

    return strategy


def header(title: str):
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


# =====================================================================
# 测试类
# =====================================================================

class TestHYPEStrategyWebhook(unittest.IsolatedAsyncioTestCase):
    """Webhook 开平仓逻辑测试"""

    # ── 测试 1: sell 信号 → 开空仓 ─────────────────────────────────
    async def test_01_sell_opens_short(self):
        header("测试1: sell 信号 → 开空仓")

        strategy = make_strategy()
        entry_price = 2000.0

        strategy.client.get_price = AsyncMock(return_value=entry_price)
        strategy.client.get_positions = AsyncMock(side_effect=[
            [],  # execute_signal 内第一次 sync (before open)
            [{"side": "SHORT", "szi": -0.5, "entryPx": str(entry_price)}],  # open 后验证
        ])

        await strategy.execute_signal(TVSignal(交易品种="ETH", 操作="sell", 先前仓位大小="0"))

        self.assertEqual(strategy.position, "SHORT")
        self.assertAlmostEqual(strategy.entry_price, entry_price, places=2)

        expected_sl = round(entry_price * 1.03, 4)
        expected_tp = round(entry_price * 0.94, 4)
        self.assertAlmostEqual(strategy.current_sl, expected_sl, places=2)
        self.assertAlmostEqual(strategy.current_tp, expected_tp, places=2)
        self.assertFalse(strategy.break_even_activated)

        print(f"  入场价:   {strategy.entry_price}")
        print(f"  止损价:   {strategy.current_sl:.2f}  (+3%)")
        print(f"  止盈价:   {strategy.current_tp:.2f}  (-6%)")
        print(f"  保本价:   {entry_price * 0.97:.2f}  (-3%, 触发后止损移至入场价)")
        print("✅ 通过")

    # ── 测试 2: buy 信号 → TV 平仓 ────────────────────────────────
    async def test_02_buy_closes_short(self):
        header("测试2: buy 信号 → TV 平仓")

        strategy = make_strategy(entry_price=2000.0, position="SHORT")
        exit_price = 1900.0

        strategy.client.get_price = AsyncMock(return_value=exit_price)

        await strategy.execute_signal(TVSignal(交易品种="ETH", 操作="buy", 先前仓位大小="0.5"))

        self.assertIsNone(strategy.position)
        self.assertIsNone(strategy.entry_price)
        self.assertIsNone(strategy.current_sl)
        self.assertIsNone(strategy.current_tp)

        pnl_pct = (2000.0 - exit_price) / 2000.0 * 100
        print(f"  出场价: {exit_price}，盈亏: {pnl_pct:+.2f}%")
        print("✅ 通过")

    # ── 测试 3: 无仓位时 buy 信号 → 忽略 ─────────────────────────
    async def test_03_buy_without_position_ignored(self):
        header("测试3: 无仓位时 buy 信号 → 忽略")

        strategy = make_strategy()  # 无仓位
        strategy.client.get_positions = AsyncMock(return_value=[])

        await strategy.execute_signal(TVSignal(交易品种="ETH", 操作="buy", 先前仓位大小="0"))

        strategy.client.place_order.assert_not_called()
        self.assertIsNone(strategy.position)
        print("  buy 信号被安全忽略，place_order 未调用")
        print("✅ 通过")

    # ── 测试 4: 已有仓位时重复 sell 信号 → 忽略 ──────────────────
    async def test_04_duplicate_sell_ignored(self):
        header("测试4: 已有仓位时重复 sell 信号 → 忽略（不重复开仓）")

        strategy = make_strategy(entry_price=2000.0, position="SHORT")
        original_sl = strategy.current_sl

        await strategy.execute_signal(TVSignal(交易品种="ETH", 操作="sell", 先前仓位大小="0"))

        strategy.client.place_order.assert_not_called()
        self.assertAlmostEqual(strategy.current_sl, original_sl, places=4)
        print("  重复 sell 信号被忽略，原仓位未变动")
        print("✅ 通过")


class TestHYPEStrategyRiskControl(unittest.IsolatedAsyncioTestCase):
    """止损 / 止盈 / 保本 风控测试"""

    # ── 测试 5: 止损触发 ──────────────────────────────────────────
    async def test_05_stop_loss_trigger(self):
        header("测试5: 止损触发（价格上涨超过止损价）")

        ep = 2000.0
        strategy = make_strategy(entry_price=ep, position="SHORT")
        sl = strategy.current_sl  # 2060.0

        # 价格在止损价以内 → 不触发
        triggered, reason = await strategy.check_stop_loss_take_profit(ep, silent=True)
        self.assertFalse(triggered)

        # 价格超过止损价 → 触发止损
        triggered, reason = await strategy.check_stop_loss_take_profit(sl + 10, silent=True)
        self.assertTrue(triggered)
        self.assertEqual(reason, "止损")

        print(f"  入场价={ep}，止损价={sl:.2f}")
        print(f"  价格={ep} → 未触发")
        print(f"  价格={sl + 10:.2f} → 触发，原因='{reason}'")
        print("✅ 通过")

    # ── 测试 6: 止盈触发 ──────────────────────────────────────────
    async def test_06_take_profit_trigger(self):
        header("测试6: 止盈触发（价格下跌低于止盈价）")

        ep = 2000.0
        strategy = make_strategy(entry_price=ep, position="SHORT")
        tp = strategy.current_tp  # 1880.0

        # 价格高于止盈价 → 不触发
        triggered, reason = await strategy.check_stop_loss_take_profit(tp + 10, silent=True)
        self.assertFalse(triggered)

        # 价格跌破止盈价 → 触发止盈
        triggered, reason = await strategy.check_stop_loss_take_profit(tp - 10, silent=True)
        self.assertTrue(triggered)
        self.assertEqual(reason, "止盈")

        print(f"  入场价={ep}，止盈价={tp:.2f}")
        print(f"  价格={tp + 10:.2f} → 未触发")
        print(f"  价格={tp - 10:.2f} → 触发，原因='{reason}'")
        print("✅ 通过")

    # ── 测试 7: 保本激活 ──────────────────────────────────────────
    async def test_07_break_even_activation(self):
        header("测试7: 保本激活（盈利 ≥ 3% → 止损线移到成本价）")

        ep = 2000.0
        strategy = make_strategy(entry_price=ep, position="SHORT")
        original_sl = strategy.current_sl  # 2060.0

        # 盈利 2% → 不触发保本
        await strategy.update_stop_loss(ep * 0.98)
        self.assertFalse(strategy.break_even_activated)
        self.assertAlmostEqual(strategy.current_sl, original_sl, places=2)
        print(f"  盈利 2%，价格={ep * 0.98:.2f} → 保本未激活，SL={strategy.current_sl:.2f}")

        # 盈利刚好 3% → 激活保本
        await strategy.update_stop_loss(ep * 0.97)
        self.assertTrue(strategy.break_even_activated)
        self.assertAlmostEqual(strategy.current_sl, ep, places=2)
        print(f"  盈利 3%，价格={ep * 0.97:.2f} → 保本激活，SL: {original_sl:.2f} → {strategy.current_sl:.2f}（成本价）")

        # 保本只激活一次（再次调用不会重置）
        strategy.current_sl = ep + 5  # 模拟外部修改
        await strategy.update_stop_loss(ep * 0.95)  # 更大盈利
        self.assertAlmostEqual(strategy.current_sl, ep + 5, places=2, msg="保本只激活一次")
        print(f"  保本已激活，再次调用不重复移动止损线")
        print("✅ 通过")

    # ── 测试 8: 保本止损触发 ─────────────────────────────────────
    async def test_08_break_even_stop_triggered(self):
        header("测试8: 保本止损触发（保本激活后价格回升超过成本价）")

        ep = 2000.0
        strategy = make_strategy(entry_price=ep, position="SHORT")

        # 先激活保本（止损线移到成本价）
        await strategy.update_stop_loss(ep * 0.97)
        self.assertTrue(strategy.break_even_activated)
        self.assertAlmostEqual(strategy.current_sl, ep, places=2)

        # 价格回升到成本价 → 触发保本止损
        triggered, reason = await strategy.check_stop_loss_take_profit(ep, silent=True)
        self.assertTrue(triggered)
        self.assertEqual(reason, "保本止损")

        # 价格低于成本价 → 不触发（仍在盈利区间）
        triggered2, _ = await strategy.check_stop_loss_take_profit(ep - 10, silent=True)
        self.assertFalse(triggered2)

        print(f"  入场价={ep}，保本后止损线={strategy.current_sl:.2f}（成本价）")
        print(f"  价格={ep - 10:.2f} → 未触发（仍盈利中）")
        print(f"  价格={ep:.2f} → 触发，原因='{reason}'")
        print("✅ 通过")

    # ── 测试 9: 止盈/止损后 buy 信号 → 忽略 ─────────────────────
    async def test_09_buy_after_sl_tp_ignored(self):
        header("测试9: 止盈/止损平仓后再收到 buy 信号 → 忽略")

        ep = 2000.0
        strategy = make_strategy(entry_price=ep, position="SHORT")

        # 模拟止损触发后状态（position 已置 None）
        strategy.position = None
        strategy.entry_price = None
        strategy.current_sl = None
        strategy.current_tp = None
        strategy.client.get_positions = AsyncMock(return_value=[])

        await strategy.execute_signal(TVSignal(交易品种="ETH", 操作="buy", 先前仓位大小="0"))

        strategy.client.place_order.assert_not_called()
        self.assertIsNone(strategy.position)
        print("  止损/止盈后 position=None，buy 信号被安全忽略")
        print("✅ 通过")


class TestHYPEStrategyFullFlow(unittest.IsolatedAsyncioTestCase):
    """完整交易流程测试"""

    # ── 测试 10: 完整流程 - TV 信号开仓 → 保本激活 → TV 平仓 ──────
    async def test_10_full_flow_tv_close(self):
        header("测试10: 完整流程 — sell开仓 → 保本激活 → buy平仓")

        strategy = make_strategy()
        ep = 2000.0

        # Step 1: sell 开仓
        strategy.client.get_price = AsyncMock(return_value=ep)
        strategy.client.get_positions = AsyncMock(side_effect=[
            [],
            [{"side": "SHORT", "szi": -0.5, "entryPx": str(ep)}],
        ])
        await strategy.execute_signal(TVSignal(交易品种="ETH", 操作="sell", 先前仓位大小="0"))
        self.assertEqual(strategy.position, "SHORT")
        print(f"  ➜ Step1 开仓: 入场={ep}，SL={strategy.current_sl:.2f}，TP={strategy.current_tp:.2f}")

        # Step 2: 价格下跌 4% → 激活保本（3% 阈值）
        price_profit = ep * 0.96  # 1920.0
        await strategy.update_stop_loss(price_profit)
        self.assertTrue(strategy.break_even_activated)
        self.assertAlmostEqual(strategy.current_sl, ep, places=2)
        print(f"  ➜ Step2 保本激活: 价格={price_profit:.2f}，止损线 → 成本价 {strategy.current_sl:.2f}")

        # Step 3: TV buy 信号平仓
        exit_price = 1950.0
        strategy.client.get_price = AsyncMock(return_value=exit_price)
        strategy.client.get_positions = AsyncMock(return_value=[
            {"side": "SHORT", "szi": -0.5, "entryPx": str(ep)}
        ])
        await strategy.execute_signal(TVSignal(交易品种="ETH", 操作="buy", 先前仓位大小="0.5"))
        self.assertIsNone(strategy.position)

        pnl_pct = (ep - exit_price) / ep * 100
        print(f"  ➜ Step3 TV平仓: 出场={exit_price}，盈亏={pnl_pct:+.2f}%")
        print("✅ 通过")

    # ── 测试 11: 完整流程 - 开仓 → 保本 → 保本止损自动平仓 ─────────
    async def test_11_full_flow_breakeven_auto_close(self):
        header("测试11: 完整流程 — sell开仓 → 保本激活 → 保本止损自动平仓")

        strategy = make_strategy()
        ep = 2000.0

        # Step 1: 预设已开仓状态
        strategy.position = "SHORT"
        strategy.entry_price = ep
        strategy.position_size = 0.5
        strategy.current_sl = ep * 1.03    # 2060
        strategy.current_tp = ep * 0.94    # 1880
        strategy.break_even_activated = False
        strategy.client.get_positions = AsyncMock(return_value=[
            {"side": "SHORT", "szi": -0.5, "entryPx": str(ep)}
        ])
        print(f"  ➜ Step1 已开仓: 入场={ep}，SL={strategy.current_sl:.2f}，TP={strategy.current_tp:.2f}")

        # Step 2: 价格下跌 3.5% → 激活保本
        await strategy.update_stop_loss(ep * 0.965)
        self.assertTrue(strategy.break_even_activated)
        self.assertAlmostEqual(strategy.current_sl, ep, places=2)
        print(f"  ➜ Step2 保本激活: 止损线移至成本价 {strategy.current_sl:.2f}")

        # Step 3: 价格反弹回成本价以上 → 触发保本止损
        price_above_entry = ep + 1   # 2001
        triggered, reason = await strategy.check_stop_loss_take_profit(price_above_entry, silent=True)
        self.assertTrue(triggered)
        self.assertEqual(reason, "保本止损")
        print(f"  ➜ Step3 价格反弹至 {price_above_entry}，触发保本止损: '{reason}'")

        # Step 4: 执行平仓
        strategy.client.get_price = AsyncMock(return_value=price_above_entry)
        await strategy._safe_close(reason)
        self.assertIsNone(strategy.position)
        print(f"  ➜ Step4 平仓完成，仓位已清零")
        print("✅ 通过")

    # ── 测试 12: 止损自动触发完整流程 ───────────────────────────────
    async def test_12_full_flow_stop_loss_auto_close(self):
        header("测试12: 完整流程 — sell开仓 → 价格上涨 → 止损自动平仓")

        strategy = make_strategy()
        ep = 2000.0

        # Step 1: 开仓
        strategy.client.get_price = AsyncMock(return_value=ep)
        strategy.client.get_positions = AsyncMock(side_effect=[
            [],
            [{"side": "SHORT", "szi": -0.5, "entryPx": str(ep)}],
        ])
        await strategy.execute_signal(TVSignal(交易品种="ETH", 操作="sell", 先前仓位大小="0"))
        sl = strategy.current_sl
        print(f"  ➜ Step1 开仓: 入场={ep}，止损线={sl:.2f}")

        # Step 2: 价格上涨但未达止损 → 不触发
        triggered, _ = await strategy.check_stop_loss_take_profit(ep * 1.02, silent=True)
        self.assertFalse(triggered)
        print(f"  ➜ Step2 价格={ep * 1.02:.2f}（+2%），未触发止损")

        # Step 3: 价格超过止损线 → 触发
        price_over_sl = sl + 5
        triggered, reason = await strategy.check_stop_loss_take_profit(price_over_sl, silent=True)
        self.assertTrue(triggered)
        self.assertEqual(reason, "止损")

        # Step 4: 执行止损平仓
        strategy.client.get_price = AsyncMock(return_value=price_over_sl)
        strategy.client.get_positions = AsyncMock(return_value=[
            {"side": "SHORT", "szi": -0.5, "entryPx": str(ep)}
        ])
        await strategy._safe_close(reason)
        self.assertIsNone(strategy.position)

        pnl_pct = (ep - price_over_sl) / ep * 100
        print(f"  ➜ Step3 价格={price_over_sl:.2f}，触发止损（{reason}）")
        print(f"  ➜ Step4 止损平仓完成，亏损={pnl_pct:.2f}%")
        print("✅ 通过")


# =====================================================================
# 主入口
# =====================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  HYPE 做空策略功能测试")
    print("=" * 60)

    loader = unittest.TestLoader()
    loader.sortTestMethodsUsing = None  # 保持定义顺序

    suite = unittest.TestSuite()
    for cls in [
        TestHYPEStrategyWebhook,
        TestHYPEStrategyRiskControl,
        TestHYPEStrategyFullFlow,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    result = runner.run(suite)

    print("\n" + "=" * 60)
    if result.wasSuccessful():
        print(f"  🎉 全部 {result.testsRun} 个测试通过！")
    else:
        print(f"  ❌ {len(result.failures)} 个失败，{len(result.errors)} 个错误")
    print("=" * 60)

    sys.exit(0 if result.wasSuccessful() else 1)
