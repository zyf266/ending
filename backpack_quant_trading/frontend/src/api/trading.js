import request from './request'

/** 保证 POST JSON 里始终是合法数字，避免 undefined 被序列化丢弃后后端用默认值 */
const finitePositive = (v, fallback) => {
  const n = Number(v)
  return Number.isFinite(n) && n > 0 ? n : fallback
}

export const getStrategies = () => request.get('/trading/strategies')
export const getInstances = () => request.get('/trading/instances')
export const launchStrategy = (data) => request.post('/trading/launch', data)
// 注意：DELETE 语义为“删除实例（停止+移除卡片）”；仅停止请用 stopInstance
export const deleteInstance = (id) => request.delete(`/trading/instances/${id}`)
export const stopInstance = (id) => request.post(`/trading/instances/${id}/stop`)
export const startInstance = (id) => request.post(`/trading/instances/${id}/start`)
export const updateInstance = (id, data) => request.put(`/trading/instances/${id}`, data)
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
    breakeven_pct:   params.breakeven_pct   || 0.03,
    price_filter_min: params.price_filter_min || 2000.0,
  })
export const stopEthTrendShort     = () => request.post('/trading/eth-trend-short/stop')
export const getEthTrendShortStatus = () => request.get('/trading/eth-trend-short/status')

// 自适应做多策略 (Webhook信号版)
export const startAdaptiveLong = (params = {}) =>
  request.post('/trading/adaptive-long/start', {
    coin:               params.coin               || '',
    exchange:           params.exchange           || 'hyperliquid',
    private_key:        params.private_key        || undefined,
    api_key:            params.api_key            || undefined,
    api_secret:         params.api_secret         || undefined,
    account_index:      params.account_index      ?? 0,
    api_key_index:      params.api_key_index      ?? 2,
    timeframe_filter:   params.timeframe_filter   || undefined,
    margin_amount:      finitePositive(params.margin_amount, 20),
    leverage:           Math.round(finitePositive(params.leverage, 50)),
    stop_loss_pct:      params.stop_loss_pct      || 0.03,
    take_profit_pct:    params.take_profit_pct    || 0.06,
    break_even_pct:     params.break_even_pct     || 0.03,
    lock_profit_pct:    params.lock_profit_pct    ?? 0,
    lock_profit_sl_pct: params.lock_profit_sl_pct ?? 0,
  })
export const stopAdaptiveLong      = () => request.post('/trading/adaptive-long/stop')
export const getAdaptiveLongStatus = () => request.get('/trading/adaptive-long/status')

// 自适应做空策略 (Webhook信号版)
export const startAdaptiveShort = (params = {}) =>
  request.post('/trading/adaptive-short/start', {
    coin:               params.coin               || '',
    exchange:           params.exchange           || 'hyperliquid',
    private_key:        params.private_key        || undefined,
    api_key:            params.api_key            || undefined,
    api_secret:         params.api_secret         || undefined,
    account_index:      params.account_index      ?? 0,
    api_key_index:      params.api_key_index      ?? 2,
    timeframe_filter:   params.timeframe_filter   || undefined,
    margin_amount:      finitePositive(params.margin_amount, 20),
    leverage:           Math.round(finitePositive(params.leverage, 50)),
    stop_loss_pct:      params.stop_loss_pct      || 0.03,
    take_profit_pct:    params.take_profit_pct    || 0.06,
    break_even_pct:     params.break_even_pct     || 0.03,
    lock_profit_pct:    params.lock_profit_pct    ?? 0,
    lock_profit_sl_pct: params.lock_profit_sl_pct ?? 0,
  })
export const stopAdaptiveShort      = () => request.post('/trading/adaptive-short/stop')
export const getAdaptiveShortStatus = () => request.get('/trading/adaptive-short/status')

// 自动平仓策略 (Webhook信号版)
export const startAutoClose = (params = {}) =>
  request.post('/trading/auto-close/start', {
    coin:        params.coin        || '',
    exchange:    params.exchange    || 'hyperliquid',
    wallet_memo: params.wallet_memo || '',
    private_key: params.private_key || undefined,
    api_key:     params.api_key     || undefined,
    api_secret:  params.api_secret  || undefined,
    account_index: params.account_index ?? 0,
    api_key_index: params.api_key_index ?? 2,
  })
export const stopAutoClose = () => request.post('/trading/auto-close/stop')
export const getAutoCloseStatus = () => request.get('/trading/auto-close/status')

