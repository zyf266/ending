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

// ETH 趋势做空策略 (信号自驱动版)
export const startEthTrendShort = (params = {}) =>
  request.post('/trading/eth-trend-short/start', {
    symbol:          params.symbol          || 'ETH',
    private_key:     params.private_key     || undefined,
    margin_amount:   params.margin_amount   || 20,
    leverage:        params.leverage        || 50,
    stop_loss_pct:   params.stop_loss_pct   || 0.03,
    take_profit_pct: params.take_profit_pct || 0.10,
    lockin_trig_pct: params.lockin_trig_pct || 0.04,
    lockin_prot_pct: params.lockin_prot_pct || 0.02,
    breakeven_pct:   params.breakeven_pct   || 0.05,
    price_filter_min: params.price_filter_min || 2000.0,
  })
export const stopEthTrendShort     = () => request.post('/trading/eth-trend-short/stop')
export const getEthTrendShortStatus = () => request.get('/trading/eth-trend-short/status')

// 自适应做多策略 (Webhook信号版)
export const startAdaptiveLong = (params = {}) =>
  request.post('/trading/adaptive-long/start', {
    private_key:     params.private_key     || undefined,
    margin_amount:   params.margin_amount   || 20,
    leverage:        params.leverage        || 50,
    stop_loss_pct:   params.stop_loss_pct   || 0.03,
    take_profit_pct: params.take_profit_pct || 0.06,
    break_even_pct:  params.break_even_pct  || 0.03,
  })
export const stopAdaptiveLong      = () => request.post('/trading/adaptive-long/stop')
export const getAdaptiveLongStatus = () => request.get('/trading/adaptive-long/status')

