import request from './request'

const CACHE_TTL = 24 * 60 * 60 * 1000 // 24小时
const _cache = {}

function cached(key, fetcher) {
  const hit = _cache[key]
  if (hit && Date.now() - hit.ts < CACHE_TTL) {
    return Promise.resolve(hit.data)
  }
  return fetcher().then((data) => {
    _cache[key] = { ts: Date.now(), data }
    return data
  })
}

/** 强制清除某个 key 的缓存（cacheBust=true 时使用）*/
function bust(key, fetcher) {
  delete _cache[key]
  return fetcher().then((data) => {
    _cache[key] = { ts: Date.now(), data }
    return data
  })
}

// ---------- ETH ----------
export function getEthTrendOverview(cacheBust = false) {
  const key = 'eth-overview'
  const fn = () => request.get('/strategy/eth-2h/overview')
  return cacheBust ? bust(key, fn) : cached(key, fn)
}

export function getEthTrendKlines(cacheBust = false) {
  const key = 'eth-klines'
  const fn = () => request.get('/strategy/eth-2h/klines')
  return cacheBust ? bust(key, fn) : cached(key, fn)
}

export function getEthTrendTrades(cacheBust = false) {
  const key = 'eth-trades'
  const fn = () => request.get('/strategy/eth-2h/trades')
  return cacheBust ? bust(key, fn) : cached(key, fn)
}

// ---------- PAXG 黄金 ----------
export function getPaxgTrendOverview(cacheBust = false) {
  const key = 'paxg-overview'
  const fn = () => request.get('/strategy/paxg-2h/overview')
  return cacheBust ? bust(key, fn) : cached(key, fn)
}

export function getPaxgTrendKlines(cacheBust = false) {
  const key = 'paxg-klines'
  const fn = () => request.get('/strategy/paxg-2h/klines')
  return cacheBust ? bust(key, fn) : cached(key, fn)
}

export function getPaxgTrendTrades(cacheBust = false) {
  const key = 'paxg-trades'
  const fn = () => request.get('/strategy/paxg-2h/trades')
  return cacheBust ? bust(key, fn) : cached(key, fn)
}

// ---------- NAS100 纳指 ----------
export function getNas100TrendOverview(cacheBust = false) {
  const key = 'nas100-overview'
  const fn = () => request.get('/strategy/nas100-2h/overview')
  return cacheBust ? bust(key, fn) : cached(key, fn)
}

export function getNas100TrendKlines(cacheBust = false) {
  const key = 'nas100-klines'
  const fn = () => request.get('/strategy/nas100-2h/klines')
  return cacheBust ? bust(key, fn) : cached(key, fn)
}

export function getNas100TrendTrades(cacheBust = false) {
  const key = 'nas100-trades'
  const fn = () => request.get('/strategy/nas100-2h/trades')
  return cacheBust ? bust(key, fn) : cached(key, fn)
}
