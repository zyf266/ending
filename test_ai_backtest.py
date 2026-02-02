"""
AI 回测分析测试脚本
获取2000根15分钟ETH K线进行AI分析和回测

回测参数:
- 初始资金: 500 USDT
- 每次开单金额: 20 USDT
- 杠杆: 50x
- 止盈: 100% (本金翻倍)
- 止损: 50% (亏损本金一半)
"""
import asyncio
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from backpack_quant_trading.core.api_client import BackpackAPIClient
from backpack_quant_trading.core.ai_adaptive import AIAdaptive
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Rectangle

# 配置matplotlib中文显示
plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False  # 解决负号显示问题


async def main():
    """主函数"""
    print("=" * 80)
    print("🚀 AI K线回测分析")
    print("=" * 80)
    
    # 1. 获取2000根15分钟K线（分批获取）
    print("\n📊 正在获取 ETH/USDC 的2000根15分钟K线...")
    
    client = BackpackAPIClient()
    
    # Backpack API对时间范围有限制，需要分批获取
    # 每批获取1000根（15分钟K线约10.4天），总共2批
    target_count = 2000
    batch_size = 1000
    batches = 2
    
    all_klines = []
    end_time = int(datetime.now().timestamp())
    
    try:
        for batch in range(batches):
            print(f"  正在获取第 {batch+1}/{batches} 批...")
            # 每批往前推11天（确保有足够数据，1000根15m K线约为10.4天）
            batch_end = end_time - (batch * 11 * 24 * 60 * 60)
            batch_start = batch_end - (11 * 24 * 60 * 60)
            
            batch_klines = await client.get_klines(
                symbol="ETH_USDC_PERP",
                interval="15m",  # 改为15分钟
                start_time=batch_start,
                end_time=batch_end,
                limit=batch_size
            )
            
            if batch_klines:
                all_klines.extend(batch_klines)
                print(f"    ✓ 获取到 {len(batch_klines)} 根K线")
            
            # 避免API频率限制
            if batch < batches - 1:
                await asyncio.sleep(0.5)
        
        # 去重并排序（按时间）
        seen_times = set()
        klines = []
        for k in all_klines:
            time_key = k['start']
            if time_key not in seen_times:
                seen_times.add(time_key)
                klines.append(k)
        
        # 按时间排序
        klines.sort(key=lambda x: x['start'])
        
        # 取最近2000根
        if len(klines) > target_count:
            klines = klines[-target_count:]
        
        print(f"✅ 成功获取 {len(klines)} 根K线")
        print(f"📅 时间范围: {klines[0]['start']} ~ {klines[-1]['start']}")
        
        # 2. 格式化数据供AI分析
        print("\n🔄 格式化K线数据...")
        analysis_count = len(klines)  # 全部用于AI分析
        
        print(f"   总K线数: {len(klines)} 根 (15分钟)")
        print(f"   AI分析: {analysis_count} 根")
        
        klines_formatted = []
        for i, k in enumerate(klines):
            klines_formatted.append({
                'index': i,
                'time': k['start'],  # start已经是格式化的时间字符串
                'open': float(k['open']),
                'high': float(k['high']),
                'low': float(k['low']),
                'close': float(k['close']),
                'volume': float(k.get('volume', 0))
            })
        
        # AI分析用的数据（全部）
        klines_for_ai = klines_formatted
        
        # 3. 调用AI分析
        print("\n🤖 AI 正在进行线性时间轴回测...")
        print(f"⏳ 模拟交易员从 {klines_for_ai[0]['time']} 逐步分析至 {klines_for_ai[-1]['time']}...")
        
        ai = AIAdaptive()
        result = ai.analyze_kline(
            kline_data=klines_for_ai,
            user_query=f"""
            【实战回测任务】你现在是一名正在观察 15分钟K线图的专业交易员。
            
            任务：请从左向右（从最早到最晚）扫描这{analysis_count}根K线，模拟真实的交易执行过程。
            
            【核心规则 - 必须遵守】
            1. **时间线性原则**：信号必须按照时间先后顺序产生，绝对禁止时间倒流或跳跃。
            2. **单边持仓约束**：你一次只能持有一个方向的仓位。必须先【平仓】当前订单，才能进行下一笔【开仓】。
            3. **逻辑严密性**：每一笔交易必须包含完整的 [开仓点位] 和 [平仓点位]，并说明逻辑。
            4. **盈亏比标准**：每笔预期盈亏比(RR)必须 ≥ 1.5:1。
            
            【输出格式 - 必须严格执行】
            请按顺序列出你的交易轨迹，格式如下：
            
            交易 1:
            - 类型: [做多/做空]
            - 开仓点: [价格] (发生于时间点/索引)
            - 平仓点: [价格] (发生于时间点/索引)
            - 逻辑: [简述为何开仓及为何平仓]
            
            交易 2:
            ...以此类推
            
            最后，请提取出汇总列表供系统解析（这是解析的关键）：
            做多信号: [价格1, 价格2, ...]  # 按发生顺序排列
            平多信号: [价格1, 价格2, ...]  # 按发生顺序排列
            做空信号: [价格1, 价格2, ...]  # 按发生顺序排列
            平空信号: [价格1, 价格2, ...]  # 按发生顺序排列
            
            【当前价格区间】: {klines_for_ai[0]['close']:.0f} ~ {klines_for_ai[-1]['close']:.0f}
            """
        )
        
        # 4. 输出分析结果
        print("\n" + "=" * 80)
        print("📊 AI 深度分析报告")
        print("=" * 80)
        print(result['analysis'])
        print("=" * 80)
        
        # 5. 解析并计算交易盈利
        import re
        
        analysis_text = result['analysis']
        
        # 【调试】打印关键内容用于检查格式
        print("\n" + "=" * 80)
        print("🔍 正在解析AI输出的买卖点位...")
        print("=" * 80)
        
        # 更宽松的正则表达式，支持各种 Markdown 格式和星号
        def extract_prices(label, text):
            # 兼容: **做多信号**: [价格], 做多信号: [价格], 做多信号 [价格]
            pattern = rf'[\*\_]*{label}[\*\_]*\s*[：:]?\s*\[([^\]]+)\]'
            match = re.search(pattern, text)
            if match:
                price_str = match.group(1)
                # 提取所有数字
                return [float(p) for p in re.findall(r'\d+\.?\d*', price_str)]
            return []

        long_entry_prices = extract_prices("做多信号", analysis_text)
        long_exit_prices = extract_prices("平多信号", analysis_text)
        short_entry_prices = extract_prices("做空信号", analysis_text)
        short_exit_prices = extract_prices("平空信号", analysis_text)

        # 打印解析结果
        print(f"✅ 解析到做多: {len(long_entry_prices)}个, 平多: {len(long_exit_prices)}个")
        print(f"✅ 解析到做空: {len(short_entry_prices)}个, 平空: {len(short_exit_prices)}个")
        
        # 兼容旧格式（买入/卖出）
        if not long_entry_prices and not short_entry_prices:
            print("\n尝试解析旧格式（买入点位/卖出点位）...")
            buy_match = re.search(r'\*?\*?买入点位\*?\*?[：:]\s*\[([^\]]+)\]', analysis_text)
            if buy_match:
                price_str = buy_match.group(1)
                long_entry_prices = [float(p.strip()) for p in re.findall(r'\d+\.?\d*', price_str)]
                print(f"✅ 兼容模式：解析到 {len(long_entry_prices)} 个买入点（作为做多信号）")
            
            sell_match = re.search(r'\*?\*?卖出点位\*?\*?[：:]\s*\[([^\]]+)\]', analysis_text)
            if sell_match:
                price_str = sell_match.group(1)
                long_exit_prices = [float(p.strip()) for p in re.findall(r'\d+\.?\d*', price_str)]
                print(f"✅ 兼容模式：解析到 {len(long_exit_prices)} 个卖出点（作为平多信号）")
        
        print("=" * 80)
        
        # 6. 计算交易盈亏统计（修复：确保买卖配对且时间顺序正确）
        print("\n" + "=" * 80)
        print("💰 交易盈亏分析")
        print("=" * 80)
        
        trades = []  # 存储所有交易记录
        total_pnl = 0  # 总盈亏
        win_count = 0  # 盈利次数
        loss_count = 0  # 亏损次数
        initial_capital = 500  # 初始资金 $500
        current_capital = initial_capital
        max_capital = initial_capital  # 最大资金
        max_drawdown = 0  # 最大回撤
        position_size_usd = 20  # 每次开单金额 $20
        leverage = 50  # 50x杠杆
        take_profit_ratio = 1.0  # 止盈100%
        stop_loss_ratio = 0.5  # 止损50%
        
        # 配对买卖点计算盈亏（重新设计：基于时间顺序的严格状态机）
        print("\n📊 逐笔交易明细:")
        print("-" * 80)
        
        # 第一步：构建所有信号点的时间序列
        all_signals = []
        
        # 做多信号（开多）
        for price in long_entry_prices:
            candidates = [k for k in klines_formatted if abs(k['low'] - price) < 50]
            if not candidates:
                candidates = klines_formatted
            kline = min(candidates, key=lambda k: abs(k['low'] - price))
            all_signals.append({
                'type': 'long_entry',
                'price': price,
                'time': datetime.strptime(kline['time'], '%Y-%m-%d %H:%M:%S'),
                'time_str': kline['time']
            })
        
        # 平多信号
        for price in long_exit_prices:
            candidates = [k for k in klines_formatted if abs(k['high'] - price) < 50]
            if not candidates:
                candidates = klines_formatted
            kline = min(candidates, key=lambda k: abs(k['high'] - price))
            all_signals.append({
                'type': 'long_exit',
                'price': price,
                'time': datetime.strptime(kline['time'], '%Y-%m-%d %H:%M:%S'),
                'time_str': kline['time']
            })
        
        # 做空信号（开空）
        for price in short_entry_prices:
            candidates = [k for k in klines_formatted if abs(k['high'] - price) < 50]
            if not candidates:
                candidates = klines_formatted
            kline = min(candidates, key=lambda k: abs(k['high'] - price))
            all_signals.append({
                'type': 'short_entry',
                'price': price,
                'time': datetime.strptime(kline['time'], '%Y-%m-%d %H:%M:%S'),
                'time_str': kline['time']
            })
        
        # 平空信号
        for price in short_exit_prices:
            candidates = [k for k in klines_formatted if abs(k['low'] - price) < 50]
            if not candidates:
                candidates = klines_formatted
            kline = min(candidates, key=lambda k: abs(k['low'] - price))
            all_signals.append({
                'type': 'short_exit',
                'price': price,
                'time': datetime.strptime(kline['time'], '%Y-%m-%d %H:%M:%S'),
                'time_str': kline['time']
            })
        
        # 按时间排序所有信号
        all_signals.sort(key=lambda x: x['time'])
        
        print(f"📋 信号序列分析：共{len(all_signals)}个信号点")
        print(f"   做多信号: {len(long_entry_prices)}个")
        print(f"   平多信号: {len(long_exit_prices)}个")
        print(f"   做空信号: {len(short_entry_prices)}个")
        print(f"   平空信号: {len(short_exit_prices)}个")
        print()
        
        # 第二步：使用状态机严格配对
        valid_trades = []
        position = None  # 当前持仓状态：None（空仓）或 {'entry': ..., 'type': 'long/short'}
        
        for i, signal in enumerate(all_signals):
            signal_type = signal['type']
            
            if position is None:
                # 空仓状态，只接受开仓信号（long_entry 或 short_entry）
                if signal_type == 'long_entry':
                    position = {
                        'entry': signal,
                        'type': 'long'
                    }
                    print(f"  ➤ 开多信号 @ {signal['time_str']}: ${signal['price']:.2f}")
                elif signal_type == 'short_entry':
                    position = {
                        'entry': signal,
                        'type': 'short'
                    }
                    print(f"  ➤ 开空信号 @ {signal['time_str']}: ${signal['price']:.2f}")
                elif signal_type in ['long_exit', 'short_exit']:
                    print(f"  ⚠️  跳过信号 @ {signal['time_str']}: 空仓时收到平仓信号（无效）")
            
            else:
                # 持仓状态，只接受对应的平仓信号
                entry = position['entry']
                trade_type = position['type']
                
                # 检查信号类型是否匹配
                if trade_type == 'long' and signal_type == 'long_exit':
                    # 做多 → 平多
                    pass  # 继续处理
                elif trade_type == 'short' and signal_type == 'short_exit':
                    # 做空 → 平空
                    pass  # 继续处理
                else:
                    # 信号不匹配
                    if signal_type in ['long_entry', 'short_entry']:
                        print(f"  ⚠️  跳过信号 @ {signal['time_str']}: 持仓时收到开仓信号（无效）")
                    else:
                        print(f"  ⚠️  跳过信号 @ {signal['time_str']}: 持仓类型不匹配（{trade_type} vs {signal_type}）")
                    continue
                
                # 验证时间顺序
                if signal['time'] <= entry['time']:
                    print(f"  ⚠️  跳过信号 @ {signal['time_str']}: 平仓时间早于开仓时间")
                    continue
                
                # 计算盈亏
                entry_price = entry['price']
                exit_price = signal['price']
                
                if trade_type == 'long':
                    direction = "做多"
                    close_direction = "平多"
                    price_direction = 1
                else:
                    direction = "做空"
                    close_direction = "平空"
                    price_direction = -1
                
                # 计算合约张数
                position_value = position_size_usd * leverage
                position_size_calc = position_value / entry_price
                
                # 计算价格变动百分比
                price_change_percent = ((exit_price - entry_price) / entry_price) * 100
                
                # 计算实际盈亏（考虑杠杆和方向）
                pnl_percent = price_change_percent * leverage * price_direction
                pnl = position_size_usd * (pnl_percent / 100)
                
                # 应用止盈止损
                max_profit = position_size_usd * take_profit_ratio
                max_loss = -position_size_usd * stop_loss_ratio
                
                if pnl > max_profit:
                    pnl = max_profit
                    pnl_percent = take_profit_ratio * 100
                elif pnl < max_loss:
                    pnl = max_loss
                    pnl_percent = -stop_loss_ratio * 100
                
                # 更新资金
                current_capital += pnl
                
                # 更新最大资金和回撤
                if current_capital > max_capital:
                    max_capital = current_capital
                drawdown = ((max_capital - current_capital) / max_capital) * 100
                if drawdown > max_drawdown:
                    max_drawdown = drawdown
                
                # 统计胜率
                if pnl > 0:
                    win_count += 1
                    status = "✅ 盈利"
                else:
                    loss_count += 1
                    status = "❌ 亏损"
                
                total_pnl += pnl
                
                # 记录交易
                valid_trades.append({
                    'id': len(valid_trades) + 1,
                    'direction': direction,
                    'close_direction': close_direction,
                    'buy_price': entry_price,
                    'buy_time': entry['time_str'],
                    'sell_price': exit_price,
                    'sell_time': signal['time_str'],
                    'pnl': pnl,
                    'pnl_percent': pnl_percent,
                    'capital': current_capital,
                    'drawdown': drawdown
                })
                
                print(f"  ✓ {close_direction}信号 @ {signal['time_str']}: ${signal['price']:.2f}")
                print(f"\n交易 #{len(valid_trades)}:")
                print(f"  开仓: ${entry_price:.2f} @ {entry['time_str']} 【{direction}】")
                print(f"  平仓: ${exit_price:.2f} @ {signal['time_str']} 【{close_direction}】")
                print(f"  持仓时长: {signal['time'] - entry['time']}")
                print(f"  开单金额: ${position_size_usd:.2f} | 杠杆: {leverage}x | 仓位: ${position_value:.2f}")
                print(f"  盈亏: {status} ${pnl:+.2f} ({pnl_percent:+.2f}%)")
                print(f"  账户: ${current_capital:.2f}")
                print(f"  回撤: {drawdown:.2f}%")
                
                # 平仓后回到空仓状态
                position = None
        
        if position is not None:
            print(f"\n⚠️  警告：最后有未平仓的持仓（开仓于 {position['entry']['time_str']}）")
        
        trades = valid_trades
        print()
        print("=" * 80)
        
        # 计算综合统计
        print("\n" + "=" * 80)
        print("📈 综合统计指标")
        print("=" * 80)
        
        total_trades = len(trades)
        if total_trades > 0:
            win_rate = (win_count / total_trades) * 100
            avg_win = sum(t['pnl'] for t in trades if t['pnl'] > 0) / win_count if win_count > 0 else 0
            avg_loss = sum(t['pnl'] for t in trades if t['pnl'] < 0) / loss_count if loss_count > 0 else 0
            profit_factor = abs(sum(t['pnl'] for t in trades if t['pnl'] > 0) / sum(t['pnl'] for t in trades if t['pnl'] < 0)) if loss_count > 0 else float('inf')
            
            print(f"\n📊 交易统计:")
            print(f"  总交易次数: {total_trades} 次")
            print(f"  盈利次数: {win_count} 次")
            print(f"  亏损次数: {loss_count} 次")
            print(f"  胜率: {win_rate:.2f}%")
            
            print(f"\n💰 盈亏统计:")
            print(f"  总盈亏: ${total_pnl:+.2f}")
            print(f"  总收益率: {((current_capital - initial_capital) / initial_capital * 100):+.2f}%")
            print(f"  平均盈利: ${avg_win:.2f}")
            print(f"  平均亏损: ${avg_loss:.2f}")
            print(f"  盈亏比: {profit_factor:.2f}")
            
            print(f"\n📉 风险指标:")
            print(f"  初始资金: ${initial_capital:.2f}")
            print(f"  最终资金: ${current_capital:.2f}")
            print(f"  最大资金: ${max_capital:.2f}")
            print(f"  最大回撤: {max_drawdown:.2f}%")
            
            # 计算夏普比率(简化版,假设无风险利率0)
            if total_trades > 1:
                returns = [t['pnl_percent'] for t in trades]
                avg_return = sum(returns) / len(returns)
                std_return = (sum((r - avg_return) ** 2 for r in returns) / (len(returns) - 1)) ** 0.5
                sharpe_ratio = (avg_return / std_return) if std_return > 0 else 0
                print(f"  夏普比率: {sharpe_ratio:.2f}")
            
            # 最大连续盈利/亏损
            max_consecutive_wins = 0
            max_consecutive_losses = 0
            current_wins = 0
            current_losses = 0
            
            for trade in trades:
                if trade['pnl'] > 0:
                    current_wins += 1
                    current_losses = 0
                    max_consecutive_wins = max(max_consecutive_wins, current_wins)
                else:
                    current_losses += 1
                    current_wins = 0
                    max_consecutive_losses = max(max_consecutive_losses, current_losses)
            
            print(f"\n🔥 连续统计:")
            print(f"  最大连续盈利: {max_consecutive_wins} 次")
            print(f"  最大连续亏损: {max_consecutive_losses} 次")
            
            # 资金曲线
            print(f"\n📈 资金曲线:")
            print(f"  起点: ${initial_capital:.2f}")
            for i, trade in enumerate(trades, 1):
                symbol = "▲" if trade['pnl'] > 0 else "▼"
                print(f"  交易{i}: ${trade['capital']:.2f} {symbol}")
        
        else:
            print("\n⚠️  未检测到完整的买卖对,无法计算盈亏统计")
            print(f"  做多信号: {len(long_entry_prices)} 个")
            print(f"  平多信号: {len(long_exit_prices)} 个")
            print(f"  做空信号: {len(short_entry_prices)} 个")
            print(f"  平空信号: {len(short_exit_prices)} 个")
        
        # 7. 绘制K线图表（显示买卖点）
        has_any_signals = (long_entry_prices or long_exit_prices or 
                          short_entry_prices or short_exit_prices)
        if has_any_signals:
            print("\n" + "=" * 80)
            print("📈 正在生成K线图表...")
            print("=" * 80)
            
            try:
                # 准备数据
                times = [datetime.strptime(k['time'], '%Y-%m-%d %H:%M:%S') for k in klines_formatted]
                opens = [k['open'] for k in klines_formatted]
                highs = [k['high'] for k in klines_formatted]
                lows = [k['low'] for k in klines_formatted]
                closes = [k['close'] for k in klines_formatted]
                
                # 创建图表
                fig, ax = plt.subplots(figsize=(20, 10))
                
                # 绘制K线
                for i in range(len(times)):
                    color = 'g' if closes[i] >= opens[i] else 'r'
                    # K线实体
                    ax.plot([times[i], times[i]], [lows[i], highs[i]], color=color, linewidth=0.5)
                    ax.add_patch(Rectangle(
                        (mdates.date2num(times[i]) - 0.0002, min(opens[i], closes[i])),
                        0.0004,
                        abs(closes[i] - opens[i]),
                        facecolor=color,
                        edgecolor=color,
                        alpha=0.8
                    ))
                
                # 标注做多开仓点（绿色向上箭头）
                for price in long_entry_prices:
                    closest = min(klines_formatted, key=lambda k: abs(k['low'] - price))
                    time_point = datetime.strptime(closest['time'], '%Y-%m-%d %H:%M:%S')
                    ax.scatter(time_point, price, color='lime', s=200, marker='^', 
                              edgecolors='darkgreen', linewidths=2, zorder=5, label='开多')
                    ax.annotate(f'多${price:.0f}', 
                               xy=(time_point, price), 
                               xytext=(0, -20),
                               textcoords='offset points',
                               ha='center',
                               fontsize=8,
                               color='darkgreen',
                               weight='bold')
                
                # 标注平多点（浅绿色向下箭头）
                for price in long_exit_prices:
                    closest = min(klines_formatted, key=lambda k: abs(k['high'] - price))
                    time_point = datetime.strptime(closest['time'], '%Y-%m-%d %H:%M:%S')
                    ax.scatter(time_point, price, color='lightgreen', s=200, marker='v',
                              edgecolors='green', linewidths=2, zorder=5, label='平多')
                    ax.annotate(f'平${price:.0f}', 
                               xy=(time_point, price),
                               xytext=(0, 20),
                               textcoords='offset points',
                               ha='center',
                               fontsize=8,
                               color='green',
                               weight='bold')
                
                # 标注做空开仓点（红色向下箭头）
                for price in short_entry_prices:
                    closest = min(klines_formatted, key=lambda k: abs(k['high'] - price))
                    time_point = datetime.strptime(closest['time'], '%Y-%m-%d %H:%M:%S')
                    ax.scatter(time_point, price, color='red', s=200, marker='v',
                              edgecolors='darkred', linewidths=2, zorder=5, label='开空')
                    ax.annotate(f'空${price:.0f}', 
                               xy=(time_point, price),
                               xytext=(0, 20),
                               textcoords='offset points',
                               ha='center',
                               fontsize=8,
                               color='darkred',
                               weight='bold')
                
                # 标注平空点（粉红色向上箭头）
                for price in short_exit_prices:
                    closest = min(klines_formatted, key=lambda k: abs(k['low'] - price))
                    time_point = datetime.strptime(closest['time'], '%Y-%m-%d %H:%M:%S')
                    ax.scatter(time_point, price, color='pink', s=200, marker='^',
                              edgecolors='red', linewidths=2, zorder=5, label='平空')
                    ax.annotate(f'平${price:.0f}', 
                               xy=(time_point, price),
                               xytext=(0, -20),
                               textcoords='offset points',
                               ha='center',
                               fontsize=8,
                               color='red',
                               weight='bold')
                
                # 图表配置
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d %H:%M'))
                ax.xaxis.set_major_locator(mdates.HourLocator(interval=6))  # 每6小时一个刻度
                plt.xticks(rotation=45, ha='right')
                ax.set_xlabel('时间', fontsize=12, weight='bold')
                ax.set_ylabel('价格 (USDT)', fontsize=12, weight='bold')
                ax.set_title(f'ETH/USDC 1分钟K线图 - AI买卖点标注 (共{len(klines_formatted)}根)', 
                           fontsize=14, weight='bold', pad=20)
                ax.grid(True, alpha=0.3, linestyle='--')
                
                # 去重图例
                handles, labels = ax.get_legend_handles_labels()
                by_label = dict(zip(labels, handles))
                ax.legend(by_label.values(), by_label.keys(), loc='upper left', fontsize=10)
                
                plt.tight_layout()
                
                # 保存图表
                chart_file = 'backtest_kline_chart.png'
                plt.savefig(chart_file, dpi=150, bbox_inches='tight')
                print(f"✅ K线图表已保存: {chart_file}")
                
                # 显示图表（可选）
                # plt.show()
                plt.close()
                
            except Exception as e:
                print(f"⚠️ 绘制图表失败: {e}")
                import traceback
                traceback.print_exc()
        
        # 8. 展示买卖点时间线
        if has_any_signals:
            print("\n" + "=" * 80)
            print("🎯 历史交易信号标注")
            print("=" * 80)
            
            if long_entry_prices:
                print(f"\n✅ 做多信号 ({len(long_entry_prices)}个):")
                for i, price in enumerate(long_entry_prices, 1):
                    closest = min(klines_formatted, key=lambda k: abs(k['low'] - price))
                    print(f"  {i}. 💰 ${price:.2f} | 📅 {closest['time']}")
            
            if long_exit_prices:
                print(f"\n🔄 平多信号 ({len(long_exit_prices)}个):")
                for i, price in enumerate(long_exit_prices, 1):
                    closest = min(klines_formatted, key=lambda k: abs(k['high'] - price))
                    print(f"  {i}. 💰 ${price:.2f} | 📅 {closest['time']}")
            
            if short_entry_prices:
                print(f"\n❌ 做空信号 ({len(short_entry_prices)}个):")
                for i, price in enumerate(short_entry_prices, 1):
                    closest = min(klines_formatted, key=lambda k: abs(k['high'] - price))
                    print(f"  {i}. 💰 ${price:.2f} | 📅 {closest['time']}")
            
            if short_exit_prices:
                print(f"\n🔄 平空信号 ({len(short_exit_prices)}个):")
                for i, price in enumerate(short_exit_prices, 1):
                    closest = min(klines_formatted, key=lambda k: abs(k['low'] - price))
                    print(f"  {i}. 💰 ${price:.2f} | 📅 {closest['time']}")
        
        # 9. 统计信息
        print("\n" + "=" * 80)
        print("📈 统计摘要")
        print("=" * 80)
        print(f"分析周期: {klines_formatted[0]['time']} ~ {klines_formatted[-1]['time']}")
        print(f"K线数量: {len(klines_formatted)} 根 (1分钟)")
        print(f"起始价格: ${klines_formatted[0]['open']:.2f}")
        print(f"结束价格: ${klines_formatted[-1]['close']:.2f}")
        price_change = ((klines_formatted[-1]['close'] - klines_formatted[0]['open']) / klines_formatted[0]['open']) * 100
        print(f"期间涨跌: {price_change:+.2f}%")
        
        if has_any_signals:
            print(f"\n交易信号统计:")
            print(f"  做多信号: {len(long_entry_prices)} 个")
            print(f"  平多信号: {len(long_exit_prices)} 个")
            print(f"  做空信号: {len(short_entry_prices)} 个")
            print(f"  平空信号: {len(short_exit_prices)} 个")
        
        print("\n✅ 分析完成!")
        
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
