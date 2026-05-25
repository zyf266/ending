import request from './request'

export const getStockNewsConfig = () => request.get('/stock-news-alert/config')
export const saveStockNewsConfig = (data) => request.post('/stock-news-alert/config', data)
export const getStockNewsStatus = () => request.get('/stock-news-alert/status')
export const startStockNewsAlert = (data) => request.post('/stock-news-alert/start', data || {})
export const stopStockNewsAlert = () => request.post('/stock-news-alert/stop')
export const testStockNewsDingtalk = () => request.post('/stock-news-alert/test-dingtalk')
export const probeJin10 = () => request.get('/stock-news-alert/probe-jin10')
export const getSourceCatalog = () => request.get('/stock-news-alert/source-catalog')
export const getProbeSources = () => request.get('/stock-news-alert/probe-sources')
export const getFeedsPreview = (params) =>
  request.get('/stock-news-alert/feeds-preview', { params })
export const getPollLogs = (params) =>
  request.get('/stock-news-alert/poll-logs', { params })
