import request from './request'

export const getSymbols = () => request.get('/macd-pattern-monitor/symbols')
export const getOptions = () => request.get('/macd-pattern-monitor/options')
export const getStatus = () => request.get('/macd-pattern-monitor/status')
export const startMonitor = (data) => request.post('/macd-pattern-monitor/start', data)
export const stopMonitor = () => request.post('/macd-pattern-monitor/stop')
export const removeTask = (data) => request.post('/macd-pattern-monitor/remove-task', data)
