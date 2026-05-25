import request from './request'

export const getPolymarketConfig = () => request.get('/polymarket-alert/config')
export const savePolymarketConfig = (data) => request.post('/polymarket-alert/config', data)
export const getPolymarketStatus = () => request.get('/polymarket-alert/status')
export const startPolymarketAlert = () => request.post('/polymarket-alert/start')
export const stopPolymarketAlert = () => request.post('/polymarket-alert/stop')
export const testPolymarketDingtalk = () => request.post('/polymarket-alert/test-dingtalk')
export const quotePolymarket = (params) => request.get('/polymarket-alert/quote', { params })
export const quoteAllPolymarket = () => request.get('/polymarket-alert/quotes')
