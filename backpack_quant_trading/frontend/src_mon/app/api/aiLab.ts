// Mock API functions for AI Lab

export interface KlineData {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface FetchKlineParams {
  symbol: string;
  interval: string;
  limit: number;
}

export interface AnalyzeParams {
  image_base64?: string;
  kline_json: any;
  user_query: string;
  symbol: string;
  interval: string;
}

export const fetchKline = async (params: FetchKlineParams): Promise<{ data?: KlineData[]; error?: string }> => {
  return new Promise((resolve) => {
    setTimeout(() => {
      // Generate mock kline data
      const now = Date.now();
      const intervalMs = {
        '1m': 60 * 1000,
        '15m': 15 * 60 * 1000,
        '1h': 60 * 60 * 1000,
        '2h': 2 * 60 * 60 * 1000,
        '4h': 4 * 60 * 60 * 1000,
        '1d': 24 * 60 * 60 * 1000,
        '1w': 7 * 24 * 60 * 60 * 1000,
      }[params.interval] || 15 * 60 * 1000;

      const data: KlineData[] = [];
      let basePrice = 2650; // ETH price

      for (let i = 0; i < params.limit; i++) {
        const time = now - (params.limit - i) * intervalMs;
        const volatility = 0.01;
        const open = basePrice + (Math.random() - 0.5) * basePrice * volatility;
        const close = open + (Math.random() - 0.5) * basePrice * volatility;
        const high = Math.max(open, close) + Math.random() * basePrice * volatility * 0.5;
        const low = Math.min(open, close) - Math.random() * basePrice * volatility * 0.5;
        const volume = Math.random() * 1000000;

        data.push({
          time: Math.floor(time / 1000),
          open: Number(open.toFixed(2)),
          high: Number(high.toFixed(2)),
          low: Number(low.toFixed(2)),
          close: Number(close.toFixed(2)),
          volume: Number(volume.toFixed(2)),
        });

        basePrice = close;
      }

      resolve({ data });
    }, 800);
  });
};

export const runAnalyze = async (params: AnalyzeParams): Promise<{ analysis: string; buy: number[]; sell: number[] }> => {
  return new Promise((resolve) => {
    setTimeout(() => {
      const mockAnalysis = `## DeepSeek V3 策略分析报告

### 市场概况
当前分析的交易对为 ${params.symbol}，时间周期为 ${params.interval}。

### 技术分析

**趋势判断:**
根据K线图形态和OHLC数据分析，当前市场呈现震荡上行趋势。价格在2640-2680区间内波动，整体呈现多头结构。

**支撑位与压力位:**
- 主要支撑位: 2645, 2638
- 主要压力位: 2678, 2685

**技术指标分析:**
1. 均线系统：短期均线上穿长期均线，形成金叉信号
2. 成交量：近期成交量温和放大，表明市场活跃度提升
3. 趋势强度：中等强度上涨趋势

### 交易建议

**买入信号:**
- 建议在 2648 附近建仓
- 回踩支撑位 2645 可加仓

**卖出信号:**
- 首次止盈位: 2678
- 第二止盈位: 2685

**风险控制:**
- 止损位设置在 2638 以下
- 建议仓位不超过总资金的30%

### 策略总结
当前市场处于上升通道中，建议采取逢低做多策略。密切关注2645支撑位的有效性，若跌破需及时止损。目标位看向2678-2685区间。

*本分析由 DeepSeek V3 AI 模型生成，仅供参考，不构成投资建议。*`;

      const buyPrices = [2648, 2645];
      const sellPrices = [2678, 2685];

      resolve({
        analysis: mockAnalysis,
        buy: buyPrices,
        sell: sellPrices,
      });
    }, 2000);
  });
};
