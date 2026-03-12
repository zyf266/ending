import request from './request'

/** @param cacheBust 为 true 时追加时间戳避免浏览器缓存，解决刷新/重启后数据不更新 */
export function getEthTrendOverview(cacheBust = false) {
  const q = cacheBust ? `?_t=${Date.now()}` : ''
  return request.get(`/strategy/eth-2h/overview${q}`)
}

export function getEthTrendKlines(cacheBust = false) {
  const q = cacheBust ? `?_t=${Date.now()}` : ''
  return request.get(`/strategy/eth-2h/klines${q}`)
}

export function getEthTrendTrades(cacheBust = false) {
  const q = cacheBust ? `?_t=${Date.now()}` : ''
  return request.get(`/strategy/eth-2h/trades${q}`)
}

export function getPaxgTrendOverview() {
  return request.get('/strategy/paxg-2h/overview')
}

export function getPaxgTrendKlines() {
  return request.get('/strategy/paxg-2h/klines')
}

export function getPaxgTrendTrades() {
  return request.get('/strategy/paxg-2h/trades')
}

export function getNas100TrendOverview(cacheBust = false) {
  const q = cacheBust ? `?_t=${Date.now()}` : ''
  return request.get(`/strategy/nas100-2h/overview${q}`)
}

export function getNas100TrendKlines(cacheBust = false) {
  const q = cacheBust ? `?_t=${Date.now()}` : ''
  return request.get(`/strategy/nas100-2h/klines${q}`)
}

export function getNas100TrendTrades(cacheBust = false) {
  const q = cacheBust ? `?_t=${Date.now()}` : ''
  return request.get(`/strategy/nas100-2h/trades${q}`)
}

