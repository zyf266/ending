import request from './request'

export const getSymbols = () => request.get('/currency-monitor/symbols')
export const getStatus = () => request.get('/currency-monitor/status')
export const startMonitor = (data) => request.post('/currency-monitor/start', data)
export const stopMonitor = () => request.post('/currency-monitor/stop')
export const removePair = (data) => request.post('/currency-monitor/remove-pair', data)
