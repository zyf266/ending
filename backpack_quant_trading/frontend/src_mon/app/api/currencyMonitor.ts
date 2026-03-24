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
        'SUIUSDT',
        'PEPEUSDT',
        'WLDUSDT',
        'FILUSDT',
        'ETCUSDT',
      ];
      resolve({ symbols });
    }, 300);
  });
};

interface MonitorStatus {
  running: boolean;
  pairs: [string, string][];
  alerted: string[];
}

let monitorRunning = false;
let monitorPairs: [string, string][] = [];
let alertedPairs = new Set<string>();

export const getStatus = async (): Promise<MonitorStatus> => {
  return new Promise((resolve) => {
    setTimeout(() => {
      // Randomly alert some pairs
      if (Math.random() > 0.7 && monitorPairs.length > 0) {
        const randomPair = monitorPairs[Math.floor(Math.random() * monitorPairs.length)];
        alertedPairs.add(`${randomPair[0]}|${randomPair[1]}`);
      }
      
      resolve({
        running: monitorRunning,
        pairs: monitorPairs,
        alerted: Array.from(alertedPairs),
      });
    }, 300);
  });
};

export const startMonitor = async (params: { symbols: string[]; timeframes: string[] }): Promise<void> => {
  return new Promise((resolve) => {
    setTimeout(() => {
      monitorRunning = true;
      const newPairs: [string, string][] = [];
      params.symbols.forEach((symbol) => {
        params.timeframes.forEach((timeframe) => {
          newPairs.push([symbol, timeframe]);
        });
      });
      monitorPairs = [...monitorPairs, ...newPairs];
      resolve();
    }, 500);
  });
};

export const stopMonitor = async (): Promise<void> => {
  return new Promise((resolve) => {
    setTimeout(() => {
      monitorRunning = false;
      monitorPairs = [];
      alertedPairs.clear();
      resolve();
    }, 300);
  });
};

export const removePair = async (params: { symbol: string; timeframe: string }): Promise<void> => {
  return new Promise((resolve) => {
    setTimeout(() => {
      monitorPairs = monitorPairs.filter(
        (p) => !(p[0] === params.symbol && p[1] === params.timeframe)
      );
      alertedPairs.delete(`${params.symbol}|${params.timeframe}`);
      resolve();
    }, 200);
  });
};

interface MinuteAlertStatus {
  running: boolean;
  symbols: string[];
  interval: string;
  vol_pct_threshold: number;
  volume_mult_threshold: number;
  ob_notional_threshold: number;
}

let minuteAlertRunning = false;
let minuteAlertConfig: MinuteAlertStatus = {
  running: false,
  symbols: [],
  interval: '1m',
  vol_pct_threshold: 5.0,
  volume_mult_threshold: 20.0,
  ob_notional_threshold: 200000,
};

export const getMinuteAlertStatus = async (): Promise<MinuteAlertStatus> => {
  return new Promise((resolve) => {
    setTimeout(() => {
      resolve(minuteAlertConfig);
    }, 200);
  });
};

export const startMinuteAlert = async (params: {
  symbols: string[];
  interval: string;
  vol_pct_threshold: number;
  volume_mult_threshold: number;
  ob_notional_threshold: number;
}): Promise<void> => {
  return new Promise((resolve) => {
    setTimeout(() => {
      minuteAlertConfig = {
        running: true,
        ...params,
      };
      minuteAlertRunning = true;
      resolve();
    }, 500);
  });
};

export const stopMinuteAlert = async (): Promise<void> => {
  return new Promise((resolve) => {
    setTimeout(() => {
      minuteAlertConfig.running = false;
      minuteAlertRunning = false;
      resolve();
    }, 300);
  });
};