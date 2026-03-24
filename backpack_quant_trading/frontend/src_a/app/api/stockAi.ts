// Mock API for Stock AI

export const getBoards = async () => {
  return new Promise((resolve) => {
    setTimeout(() => {
      resolve({
        options: [
          { value: '主板', label: '主板（沪市+深市）' },
          { value: '创业板', label: '创业板' },
          { value: '科创板', label: '科创板' },
          { value: '北交所', label: '北交所' },
        ],
      });
    }, 300);
  });
};

export const getIndustries = async () => {
  return new Promise((resolve) => {
    setTimeout(() => {
      resolve({
        options: [
          { value: '化学原料', label: '化学原料' },
          { value: '贵金属', label: '贵金属' },
          { value: '电力', label: '电力' },
          { value: '银行', label: '银行' },
          { value: '半导体', label: '半导体' },
          { value: '医药生物', label: '医药生物' },
          { value: '计算机', label: '计算机' },
          { value: '新能源', label: '新能源' },
        ],
      });
    }, 300);
  });
};

export const screenStocks = async (params: any) => {
  return new Promise((resolve) => {
    setTimeout(() => {
      const mockStocks = [
        {
          code: '600519',
          name: '贵州茅台',
          market: '沪市主板',
          score: 85.5,
          close: 1680.5,
          pct_chg: 2.3,
          details: { macd_hist: 0.25, rsi: 68, kdj_j: 72, volume_ratio: 1.8 },
          description: '量价配合良好，MACD金叉',
        },
        {
          code: '000858',
          name: '五粮液',
          market: '深市主板',
          score: 78.2,
          close: 135.6,
          pct_chg: 1.5,
          details: { macd_hist: 0.12, rsi: 62, kdj_j: 65, volume_ratio: 1.5 },
          description: '技术面良好',
        },
        {
          code: '601318',
          name: '中国平安',
          market: '沪市主板',
          score: 72.8,
          close: 48.2,
          pct_chg: -0.8,
          details: { macd_hist: -0.05, rsi: 55, kdj_j: 58, volume_ratio: 1.2 },
          description: '调整中',
        },
      ];

      resolve({
        list: mockStocks.slice(0, params.top_n || 30),
        candidates_count: 150,
        from_full_market: !params.boards?.length && !params.industries?.length,
      });
    }, 1500);
  });
};

export const analyzeStocksWithDaily = async (stocks: any[]) => {
  return new Promise((resolve) => {
    setTimeout(() => {
      resolve({
        analysis: `根据当前技术指标分析：

1. 贵州茅台（600519）：技术面强势，MACD金叉，RSI在超买区域边缘，建议关注回调机会
2. 五粮液（000858）：技术指标良好，量能配合，可继续持有
3. 中国平安（601318）：处于调整阶段，建议等待企稳信号

总体建议：当前市场情绪偏积极，但需注意风险控制，建议分批建仓。`,
      });
    }, 2000);
  });
};

export const analyzeSingleStock = async (code: string) => {
  return new Promise((resolve) => {
    setTimeout(() => {
      resolve({
        analysis: `${code} 技术分析：

K线形态：近期呈现震荡上行走势
MACD：金叉形成，红柱持续放大
RSI：当前值65，处于强势区域
KDJ：J值超过80，存在短期超买风险

综合判断：技术面偏多，建议短线操作注意回调风险。`,
      });
    }, 1800);
  });
};

export const getDailyPredict = async (params: any) => {
  return new Promise((resolve) => {
    setTimeout(() => {
      const mockPredicts = [
        { code: '600519', name: '贵州茅台', proba_up: 0.85, close: 1680.5 },
        { code: '000858', name: '五粮液', proba_up: 0.78, close: 135.6 },
        { code: '601318', name: '中国平安', proba_up: 0.72, close: 48.2 },
        { code: '000333', name: '美的集团', proba_up: 0.68, close: 58.9 },
        { code: '600036', name: '招商银行', proba_up: 0.65, close: 32.5 },
      ];

      resolve({
        list: mockPredicts.slice(0, params.top_n || 20),
        date: new Date().toISOString().split('T')[0],
      });
    }, 1200);
  });
};

export const trainModel = async (params: any) => {
  return new Promise((resolve) => {
    setTimeout(() => {
      resolve({
        ok: true,
        n_samples: 1250,
        n_stocks: params.stock_codes.length,
        message: '模型训练完成',
      });
    }, 3000);
  });
};

export const refreshKlineCache = async () => {
  return new Promise((resolve) => {
    setTimeout(() => {
      resolve({
        ok: true,
        rows_added: 1580,
        max_date: new Date().toISOString().split('T')[0],
        message: '缓存刷新成功',
      });
    }, 2000);
  });
};
