import request from './request'

export const fetchKline = (params = {}) =>
  request.post(`/ai-lab/fetch-kline?symbol=${params.symbol || 'ETHUSDT'}&interval=${params.interval || '15m'}&limit=${params.limit ?? 1500}`)
export const runAnalyze = (data) =>
  request.post('/ai-lab/analyze', data, { timeout: 180000 }) // AI 分析耗时长，延长至 3 分钟
