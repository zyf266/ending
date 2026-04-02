import request from './request'

export const getStrategies = () => request.get('/trading/strategies')
export const getInstances = () => request.get('/trading/instances')
export const launchStrategy = (data) => request.post('/trading/launch', data)
export const stopInstance = (id) => request.delete(`/trading/instances/${id}`)
export const getLogs = () => request.get('/trading/logs')

// HYPE 自适应做空策略 (Webhook信号版)
export const startHypeStrategy = (symbol = 'ETH', private_key, params = {}) => 
  request.post('/trading/hype/start', { 
    symbol, 
    private_key, 
    stop_loss_pct: params.stop_loss_pct || 0.03,
    take_profit_pct: params.take_profit_pct || 0.06,
    break_even_pct: params.break_even_pct || 0.03,
    margin_amount: params.margin_amount || 20,
    leverage: params.leverage || 50,
    kline_interval: params.kline_interval || '2h',
  })
export const stopHypeStrategy = () => request.post('/trading/hype/stop')
export const getHypeStatus = () => request.get('/trading/hype/status')
export const toggleHypeStrategy = (enabled, instance_id) => request.post('/trading/hype/toggle', { enabled, instance_id })
