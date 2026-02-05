"""AI 1分钟K线回测分析脚本（成本优化版）
测试本地指标预筛选 + AI分析的组合策略

回测参数:
- 初始资金: 1000 USDT
- 每次开单金额: 20 USDT
- 杠杆: 100x
- 止盈: 50%（价格涨0.5%）
- 止损: 25%（价格跌0.25%）
- 回测天数: 1天（约1440根1分钟K线）
"""
import asyncio
import sys
import os
import pandas as pd
import numpy as np

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
plt.rcParams['axes.unicode_minus'] = False


def calculate_technical_indicators(df):
    """计算本地技术指标（与策略中的逻辑一致）"""
    try:
        if len(df) < 50:
            return None
        
        close = df['close'].values
        high = df['high'].values
        low = df['low'].values
        
        # RSI(14)
        period = 14
        delta = np.diff(close)
        gains = np.where(delta > 0, delta, 0)
        losses = np.where(delta < 0, -delta, 0)
        
        avg_gain = np.mean(gains[-period:]) if len(gains) >= period else 0
        avg_loss = np.mean(losses[-period:]) if len(losses) >= period else 0
        
        if avg_loss == 0:
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
        
        # MACD
        ema12 = pd.Series(close).ewm(span=12, adjust=False).mean().iloc[-1]
        ema26 = pd.Series(close).ewm(span=26, adjust=False).mean().iloc[-1]
        dif = ema12 - ema26
        
        dif_series = pd.Series(close).ewm(span=12, adjust=False).mean() - pd.Series(close).ewm(span=26, adjust=False).mean()
        dea = dif_series.ewm(span=9, adjust=False).mean().iloc[-1]
        macd_hist = dif - dea
        
        # 布林带
        ma20 = np.mean(close[-20:])
        std20 = np.std(close[-20:])
        bb_upper = ma20 + 2 * std20
        bb_lower = ma20 - 2 * std20
        
        current_price = close[-1]
        
        return {
            'rsi': rsi,
            'macd_hist': macd_hist,
            'bb_upper': bb_upper,
            'bb_lower': bb_lower,
            'price': current_price
        }
    except Exception as e:
        print(f"指标计算失败: {e}")
        return None


def should_call_ai_for_entry(indicators):
    """判断是否需要调用AI（开仓预筛选）
    
    降低门槛：只需满足1个条件，增加交易机会
    """
    if not indicators:
        return False
    
    rsi = indicators['rsi']
    price = indicators['price']
    bb_upper = indicators['bb_upper']
    bb_lower = indicators['bb_lower']
    macd_hist = indicators['macd_hist']
    
    conditions_met = 0
    
    # 条件1: RSI极端
    if rsi < 40 or rsi > 60:
        conditions_met += 1
    
    # 条件2: 价格接近布林带
    dist_to_upper = abs(price - bb_upper) / price
    dist_to_lower = abs(price - bb_lower) / price
    if dist_to_upper < 0.01 or dist_to_lower < 0.01:
        conditions_met += 1
    
    # 条件3: MACD强信号
    if abs(macd_hist) > 0.5:
        conditions_met += 1
    
    return conditions_met >= 1  # 降低门槛：只需满足1个


async def main():
    """主函数"""
    print("=" * 80)
    print("🚀 AI 1分钟K线回测分析（成本优化版）")
    print("=" * 80)
    
    # 1. 获取K线数据
    print("\n📊 正在获取 ETH/USDC 的1天1分钟K线...")
    
    client = BackpackAPIClient()
    
    # 1天约1440根1分钟K线（Backpack限制单次请求时间跨度）
    target_count = 3000
    end_time = int(datetime.now().timestamp())
    start_time = end_time - (24 * 60 * 60)  # 1天
    
    try:
        klines = await client.get_klines(
            symbol="ETH_USDC_PERP",
            interval="1m",
            start_time=start_time,
            end_time=end_time,
            limit=target_count
        )
        
        print(f"✅ 成功获取 {len(klines)} 根K线")
        print(f"📅 时间范围: {klines[0]['start']} ~ {klines[-1]['start']}")
        
        # 2. 格式化数据
        print("\n🔄 格式化K线数据...")
        klines_formatted = []
        for i, k in enumerate(klines):
            klines_formatted.append({
                'index': i,
                'time': k['start'],
                'open': float(k['open']),
                'high': float(k['high']),
                'low': float(k['low']),
                'close': float(k['close']),
                'volume': float(k.get('volume', 0))
            })
        
        # 3. 模拟策略运行（本地预筛选 + AI调用）
        print("\n🤖 开始模拟策略运行...")
        print(f"💡 使用本地指标预筛选，预计降低85%AI调用")
        
        # 创建DataFrame方便指标计算
        df = pd.DataFrame(klines_formatted)
        
        # 统计变量
        ai_call_count = 0
        local_filter_skip_count = 0
        signals = []  # 存储所有信号
        position = None  # 当前持仓
        
        # 逐根K线模拟
        print(f"\n📊 开始逐根K线扫描 (共{len(klines_formatted)}根)...")
        
        for i in range(50, len(klines_formatted)):  # 从第50根开始，确保有足够历史数据
            # 计算本地指标
            df_slice = df.iloc[:i+1]
            indicators = calculate_technical_indicators(df_slice)
            
            if not indicators:
                continue
            
            # 判断是否需要调用AI
            if position is None:
                # 空仓：检查开仓条件
                should_call = should_call_ai_for_entry(indicators)
            else:
                # 持仓：检查平仓条件
                entry_price = position['entry_price']
                current_price = indicators['price']
                side = position['side']
                
                # 计算浮动盈亏
                if side == 'long':
                    pnl_pct = (current_price / entry_price - 1) * 100
                else:
                    pnl_pct = (1 - current_price / entry_price) * 100
                
                # 平仓条件：浮盈>50% 或 浮亏>25%（100倍杠杆）
                should_call = pnl_pct > 50 or pnl_pct < -25
            
            if should_call:
                ai_call_count += 1
                
                # 模拟AI返回信号（简化版：根据RSI和MACD判断）
                rsi = indicators['rsi']
                macd = indicators['macd_hist']
                price = indicators['price']
                
                # 输出AI分析详情
                print(f"  [{i}] AI分析: RSI={rsi:.1f}, MACD={macd:.2f}, 价格=${price:.2f}", end='')
                
                if position is None:
                    # 开仓逻辑：RSI主导（标准超买超卖区间）
                    if rsi < 40:  # 超卖
                        # 做多信号
                        signals.append({
                            'type': 'long_entry',
                            'price': price,
                            'time': klines_formatted[i]['time'],
                            'index': i
                        })
                        position = {'side': 'long', 'entry_price': price, 'entry_index': i}
                        print(f" → 开多")
                    
                    elif rsi > 60:  # 超买
                        # 做空信号
                        signals.append({
                            'type': 'short_entry',
                            'price': price,
                            'time': klines_formatted[i]['time'],
                            'index': i
                        })
                        position = {'side': 'short', 'entry_price': price, 'entry_index': i}
                        print(f" → 开空")
                    else:
                        print(f" → 无信号(RSI在中间区间)")
                
                else:
                    # 平仓逻辑
                    side = position['side']
                    entry_price = position['entry_price']
                    pnl_pct = (price / entry_price - 1) * 100 if side == 'long' else (1 - price / entry_price) * 100
                    
                    if side == 'long':
                        signals.append({
                            'type': 'long_exit',
                            'price': price,
                            'time': klines_formatted[i]['time'],
                            'index': i
                        })
                        print(f"  [{i}] 平多 @ ${price:.2f} (PnL={pnl_pct:+.2f}%)")
                    else:
                        signals.append({
                            'type': 'short_exit',
                            'price': price,
                            'time': klines_formatted[i]['time'],
                            'index': i
                        })
                        print(f"  [{i}] 平空 @ ${price:.2f} (PnL={pnl_pct:+.2f}%)")
                    
                    position = None
            else:
                local_filter_skip_count += 1
        
        # 4. 统计成本优化效果
        total_checks = ai_call_count + local_filter_skip_count
        save_rate = (local_filter_skip_count / total_checks * 100) if total_checks > 0 else 0
        
        print(f"\n💰 成本优化统计:")
        print(f"  总检查次数: {total_checks}")
        print(f"  AI调用次数: {ai_call_count}")
        print(f"  本地过滤: {local_filter_skip_count}")
        print(f"  节省率: {save_rate:.1f}%")
        
        # 5. 计算交易盈亏
        print("\n💰 交易盈亏分析")
        print("=" * 80)
        
        trades = []
        total_pnl = 0
        win_count = 0
        loss_count = 0
        initial_capital = 1000
        current_capital = initial_capital
        position_size_usd = 20
        leverage = 100
        
        # 配对信号计算盈亏
        open_position = None
        for signal in signals:
            if signal['type'] in ['long_entry', 'short_entry']:
                if open_position is None:
                    open_position = signal
            elif signal['type'] in ['long_exit', 'short_exit']:
                if open_position:
                    entry_price = open_position['price']
                    exit_price = signal['price']
                    
                    if open_position['type'] == 'long_entry':
                        price_direction = 1
                    else:
                        price_direction = -1
                    
                    price_change_percent = ((exit_price - entry_price) / entry_price) * 100
                    pnl_percent = price_change_percent * leverage * price_direction
                    pnl = position_size_usd * (pnl_percent / 100)
                    
                    current_capital += pnl
                    total_pnl += pnl
                    
                    if pnl > 0:
                        win_count += 1
                    else:
                        loss_count += 1
                    
                    trades.append({
                        'entry_price': entry_price,
                        'exit_price': exit_price,
                        'pnl': pnl,
                        'pnl_percent': pnl_percent,
                        'capital': current_capital
                    })
                    
                    print(f"交易 #{len(trades)}: ${entry_price:.2f} → ${exit_price:.2f} | PnL: ${pnl:+.2f} ({pnl_percent:+.2f}%) | 资金: ${current_capital:.2f}")
                    
                    open_position = None
        
        # 6. 综合统计
        print("\n📈 综合统计指标")
        print("=" * 80)
        
        total_trades = len(trades)
        if total_trades > 0:
            win_rate = (win_count / total_trades) * 100
            
            print(f"\n📊 交易统计:")
            print(f"  总交易次数: {total_trades} 次")
            print(f"  盈利次数: {win_count} 次")
            print(f"  亏损次数: {loss_count} 次")
            print(f"  胜率: {win_rate:.2f}%")
            
            print(f"\n💰 盈亏统计:")
            print(f"  总盈亏: ${total_pnl:+.2f}")
            print(f"  总收益率: {((current_capital - initial_capital) / initial_capital * 100):+.2f}%")
            print(f"  初始资金: ${initial_capital:.2f}")
            print(f"  最终资金: ${current_capital:.2f}")
        
        # 7. 绘制K线图
        print("\n📈 正在生成K线图表...")
        
        times = [datetime.strptime(k['time'], '%Y-%m-%d %H:%M:%S') for k in klines_formatted]
        opens = [k['open'] for k in klines_formatted]
        highs = [k['high'] for k in klines_formatted]
        lows = [k['low'] for k in klines_formatted]
        closes = [k['close'] for k in klines_formatted]
        
        fig, ax = plt.subplots(figsize=(24, 12))
        
        # 绘制K线
        for i in range(len(times)):
            color = 'g' if closes[i] >= opens[i] else 'r'
            ax.plot([times[i], times[i]], [lows[i], highs[i]], color=color, linewidth=0.5)
            ax.add_patch(Rectangle(
                (mdates.date2num(times[i]) - 0.0001, min(opens[i], closes[i])),
                0.0002,
                abs(closes[i] - opens[i]),
                facecolor=color,
                edgecolor=color,
                alpha=0.8
            ))
        
        # 标注信号
        for signal in signals:
            time_point = datetime.strptime(signal['time'], '%Y-%m-%d %H:%M:%S')
            price = signal['price']
            
            if signal['type'] == 'long_entry':
                ax.scatter(time_point, price, color='lime', s=150, marker='^', 
                          edgecolors='darkgreen', linewidths=2, zorder=5)
            elif signal['type'] == 'long_exit':
                ax.scatter(time_point, price, color='lightgreen', s=150, marker='v',
                          edgecolors='green', linewidths=2, zorder=5)
            elif signal['type'] == 'short_entry':
                ax.scatter(time_point, price, color='red', s=150, marker='v',
                          edgecolors='darkred', linewidths=2, zorder=5)
            elif signal['type'] == 'short_exit':
                ax.scatter(time_point, price, color='pink', s=150, marker='^',
                          edgecolors='red', linewidths=2, zorder=5)
        
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d %H:%M'))
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=6))
        plt.xticks(rotation=45, ha='right')
        ax.set_xlabel('时间', fontsize=12, weight='bold')
        ax.set_ylabel('价格 (USDT)', fontsize=12, weight='bold')
        ax.set_title(f'ETH/USDC 1分钟K线图 - AI买卖点标注（成本优化版）\n节省AI调用: {save_rate:.1f}% | 总交易: {total_trades}笔 | 收益率: {((current_capital - initial_capital) / initial_capital * 100):+.2f}%', 
                   fontsize=14, weight='bold', pad=20)
        ax.grid(True, alpha=0.3, linestyle='--')
        
        plt.tight_layout()
        
        chart_file = 'backtest_1m_optimized.png'
        plt.savefig(chart_file, dpi=150, bbox_inches='tight')
        print(f"✅ K线图表已保存: {chart_file}")
        plt.close()
        
        print("\n✅ 回测完成!")
        
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
