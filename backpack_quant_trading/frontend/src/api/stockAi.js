import request from './request'

export const getBoards = () => request.get('/stock-ai/boards')
export const getIndustries = () => request.get('/stock-ai/industries')
// 选股/预测可能需拉取多只日线，超时设为 5 分钟
export const screenStocks = (data) => request.post('/stock-ai/screen', data, { timeout: 300000 })
export const analyzeStocks = (items) => request.post('/stock-ai/analyze', { items })
export const analyzeStocksWithDaily = (items) => request.post('/stock-ai/analyze-with-daily', { items }, { timeout: 180000 })
// 单只股票分析：输入代码，拉取日 K 后交给 DeepSeek 分析
export const analyzeSingleStock = (stockCode) => request.post('/stock-ai/analyze-single', { stock_code: stockCode }, { timeout: 180000 })
// 每日预测：未来 3~5 日看涨概率排序（需先训练模型）
export const getDailyPredict = (data = {}) => request.post('/stock-ai/daily-predict', { top_n: 20, use_cache: true, force_refresh: false, ...data }, { timeout: 300000 })
export const trainModel = (data) => request.post('/stock-ai/train-model', data, { timeout: 600000 })
// 刷新 K 线缓存（pytdx/Tushare 增量），耗时可较长
export const refreshKlineCache = () => request.post('/stock-ai/refresh-cache', {}, { timeout: 600000 })
