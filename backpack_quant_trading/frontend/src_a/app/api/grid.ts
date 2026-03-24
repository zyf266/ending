// Mock API functions for Grid Trading

export interface GridInstance {
  id: string;
  exchange: string;
  symbol: string;
  grid_mode: string;
  price_lower: number;
  price_upper: number;
  grid_count: number;
  current_price: number;
  total_trades: number;
  profit: number;
  status: string;
  start_time: string;
}

export interface StartGridParams {
  exchange: string;
  symbol: string;
  price_lower: number;
  price_upper: number;
  grid_count: number;
  investment_per_grid: number;
  leverage: number;
  grid_mode: string;
  api_key: string;
  secret_key: string;
}

let mockGrids: GridInstance[] = [];

export const getGridStatus = async (): Promise<{ grids: GridInstance[] }> => {
  return new Promise((resolve) => {
    setTimeout(() => {
      // Update current prices and trades randomly
      mockGrids = mockGrids.map((g) => ({
        ...g,
        current_price: g.current_price + (Math.random() - 0.5) * 10,
        total_trades: g.total_trades + Math.floor(Math.random() * 3),
        profit: g.profit + Math.random() * 5,
      }));
      resolve({ grids: mockGrids });
    }, 300);
  });
};

export const startGrid = async (params: StartGridParams): Promise<{ ok: boolean; message?: string }> => {
  return new Promise((resolve) => {
    setTimeout(() => {
      const newGrid: GridInstance = {
        id: `grid_${Date.now()}`,
        exchange: params.exchange,
        symbol: params.symbol,
        grid_mode: params.grid_mode,
        price_lower: params.price_lower,
        price_upper: params.price_upper,
        grid_count: params.grid_count,
        current_price: (params.price_lower + params.price_upper) / 2,
        total_trades: 0,
        profit: 0,
        status: 'running',
        start_time: new Date().toLocaleString('zh-CN'),
      };
      mockGrids.push(newGrid);
      resolve({ ok: true, message: '网格启动成功' });
    }, 800);
  });
};

export const stopGrid = async (id: string): Promise<{ ok: boolean }> => {
  return new Promise((resolve) => {
    setTimeout(() => {
      mockGrids = mockGrids.filter((g) => g.id !== id);
      resolve({ ok: true });
    }, 500);
  });
};

export const stopAllGrids = async (): Promise<{ ok: boolean }> => {
  return new Promise((resolve) => {
    setTimeout(() => {
      mockGrids = [];
      resolve({ ok: true });
    }, 500);
  });
};
