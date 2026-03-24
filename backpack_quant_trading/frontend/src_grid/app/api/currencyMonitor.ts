// Mock API for currency monitor

export const getSymbols = async (): Promise<{ symbols: string[] }> => {
  return new Promise((resolve) => {
    setTimeout(() => {
      const symbols = [
        'ETHUSDT',
        'BTCUSDT',
        'BNBUSDT',
        'SOLUSDT',
        'ADAUSDT',
        'XRPUSDT',
        'DOGEUSDT',
        'DOTUSDT',
        'MATICUSDT',
        'SHIBUSDT',
        'AVAXUSDT',
        'UNIUSDT',
        'LINKUSDT',
        'ATOMUSDT',
        'LTCUSDT',
        'NEARUSDT',
        'APTUSDT',
        'ARBUSDT',
        'OPUSDT',
        'INJUSDT',
      ];
      resolve({ symbols });
    }, 300);
  });
};
