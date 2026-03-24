// Mock API functions for trading

export interface Strategy {
  label: string;
  value: string;
}

export interface Instance {
  id: string;
  platform: string;
  strategy_name: string;
  symbol: string;
  start_time: string;
  pid: number;
  balance: number;
  status: 'running' | 'registering';
}

export interface LaunchParams {
  platform: string;
  strategy: string;
  symbol: string;
  size: number;
  leverage: number;
  take_profit: number;
  stop_loss: number;
  api_key?: string;
  api_secret?: string;
  passphrase?: string;
  private_key?: string;
}

// Mock data
const mockStrategies: Strategy[] = [
  { label: '均值回归策略', value: 'mean_reversion' },
  { label: '双频趋势策略', value: 'dual_freq_trend' },
  { label: '网格交易', value: 'grid_trading' },
  { label: '动量突破', value: 'momentum_breakout' },
];

let mockInstances: Instance[] = [];

export const getStrategies = async (): Promise<{ strategies: Strategy[] }> => {
  return new Promise((resolve) => {
    setTimeout(() => {
      resolve({ strategies: mockStrategies });
    }, 300);
  });
};

export const getInstances = async (): Promise<{ instances: Instance[] }> => {
  return new Promise((resolve) => {
    setTimeout(() => {
      resolve({ instances: mockInstances });
    }, 300);
  });
};

export const launchStrategy = async (params: LaunchParams): Promise<{ message: string }> => {
  return new Promise((resolve) => {
    setTimeout(() => {
      const newInstance: Instance = {
        id: `inst-${Date.now()}`,
        platform: params.platform,
        strategy_name: mockStrategies.find(s => s.value === params.strategy)?.label || params.strategy,
        symbol: params.symbol,
        start_time: new Date().toLocaleString('zh-CN'),
        pid: Math.floor(Math.random() * 90000) + 10000,
        balance: Math.floor(Math.random() * 50000) + 10000,
        status: 'running',
      };
      mockInstances.push(newInstance);
      resolve({ message: '策略启动成功' });
    }, 500);
  });
};

export const stopInstance = async (id: string): Promise<{ message: string }> => {
  return new Promise((resolve) => {
    setTimeout(() => {
      mockInstances = mockInstances.filter(inst => inst.id !== id);
      resolve({ message: '已停止策略实例' });
    }, 300);
  });
};

export const getLogs = async (): Promise<{ logs: string }> => {
  return new Promise((resolve) => {
    setTimeout(() => {
      const mockLogs = `[2024-03-16 10:45:23] backpack_quant_trading.core.engine INFO: 策略引擎启动成功
[2024-03-16 10:45:24] backpack_quant_trading.core.live_trading INFO: 连接到Backpack交易所 ✓
[2024-03-16 10:45:25] backpack_quant_trading.strategies.mean_reversion INFO: 均值回归策略已加载, 参数: {'symbol': 'ETH/USDC', 'size': 20, 'leverage': 50}
[2024-03-16 10:45:26] backpack_quant_trading.core.data_manager INFO: 获取历史数据 ETH/USDC 1m K线
[2024-03-16 10:45:28] backpack_quant_trading.core.live_trading INFO: [信号] 均值回归策略检测到买入信号 | 价格: $2648.53 | 仓位: 0%
[2024-03-16 10:45:29] backpack_quant_trading.core.live_trading INFO: [下单] 市价买入 0.757 ETH @ $2648.53 | 保证金: $20 | 杠杆: 50x
[2024-03-16 10:45:30] backpack_quant_trading.core.live_trading INFO: [成交] 订单已成交 | ID: ORD-20240316-1045-ABC123
[2024-03-16 10:46:15] backpack_quant_trading.strategies.mean_reversion INFO: 持仓监控中 | 当前价格: $2650.12 | 未实现盈亏: +$60.23 (+3.01%)
[2024-03-16 10:47:05] backpack_quant_trading.core.live_trading INFO: [信号] 止盈触发 | 收益率: 3.5% | 止盈设置: 2%
[2024-03-16 10:47:06] backpack_quant_trading.core.live_trading INFO: [平仓] 市价卖出 0.757 ETH @ $2651.80 | 实现盈亏: +$70 (+3.5%)`;
      resolve({ logs: mockLogs });
    }, 200);
  });
};
