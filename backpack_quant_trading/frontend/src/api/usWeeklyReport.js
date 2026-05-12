import request from './request'

// 这个接口聚合 20+ 个外部免费源，首次冷启动较慢；这里用更长的超时（默认 axios 30s 会被切断）。
export const getUsWeeklySnapshot = (forceRefresh = false) =>
  request.get('/us-weekly-report/snapshot', {
    timeout: 120000,
    params: forceRefresh ? { force_refresh: true } : {},
  })

// 历史泡沫分析（用于首页曲线 & 详情页）
export const getBubbleHistory = (limit = 80) =>
  request.get('/us-weekly-report/history', { params: { limit } })

// 最新一份 DeepSeek 分析
export const getLatestBubbleAnalysis = () =>
  request.get('/us-weekly-report/latest')

// 按 ID（generated_at_utc）取某一周完整报告
export const getBubbleReportById = (id) =>
  request.get('/us-weekly-report/report', { params: { id } })

// 手动触发一次分析（调用 DeepSeek，可能 30~90 秒）
export const triggerBubbleAnalyze = (payload = {}) =>
  request.post('/us-weekly-report/analyze', payload, { timeout: 180000 })
