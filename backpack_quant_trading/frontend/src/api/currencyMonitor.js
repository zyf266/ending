import request from './request'

export const getSymbols = () => request.get('/currency-monitor/symbols')
export const getStatus = () => request.get('/currency-monitor/status')
export const startMonitor = (data) => request.post('/currency-monitor/start', data)
export const stopMonitor = () => request.post('/currency-monitor/stop')
export const removePair = (data) => request.post('/currency-monitor/remove-pair', data)

// 1分钟预警（波动/量能/订单簿墙）
export const getMinuteAlertStatus = () => request.get('/currency-monitor/minute-alert/status')
export const startMinuteAlert = (data) => request.post('/currency-monitor/minute-alert/start', data)
export const stopMinuteAlert = () => request.post('/currency-monitor/minute-alert/stop')
