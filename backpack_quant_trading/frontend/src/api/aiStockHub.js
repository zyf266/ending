import axios from 'axios'
import request from './request'

// 展示顺序：美股 → 加密 → A股（与 research_cards_registry.json 一致）
const US_STOCK_CODES = [
  'NVDA', 'INTC', 'GOOGL', 'MSFT', 'MU', 'MRVL', 'CRDO', 'SNDK', 'IBM', 'NOK', 'RKLB', 'CRCL',
]
const CRYPTO_CODES = ['ETH', 'HYPE', 'ONDO']
const A_SHARE_CODES = ['000858']

export const RESEARCH_CARD_CODES_FALLBACK = [...US_STOCK_CODES, ...CRYPTO_CODES, ...A_SHARE_CODES]

/** @deprecated 请用 fetchResearchCardCodes()；保留兼容旧引用 */
export const RESEARCH_CARD_CODES = RESEARCH_CARD_CODES_FALLBACK

const _DISPLAY_ORDER = new Map(
  RESEARCH_CARD_CODES_FALLBACK.map((code, index) => [code, index])
)

/** 按 美股 → 加密 → A股 排序；未知代码排在最后 */
export function sortResearchCardCodes(codes) {
  const uniq = []
  const seen = new Set()
  for (const raw of codes || []) {
    const c = String(raw || '').toUpperCase().trim()
    if (!c || seen.has(c)) continue
    seen.add(c)
    uniq.push(c)
  }
  return uniq.sort((a, b) => {
    const ia = _DISPLAY_ORDER.has(a) ? _DISPLAY_ORDER.get(a) : 9999
    const ib = _DISPLAY_ORDER.has(b) ? _DISPLAY_ORDER.get(b) : 9999
    if (ia !== ib) return ia - ib
    return a.localeCompare(b)
  })
}

export const getResearchCodes = () => request.get('/ai-stock-hub/research-codes')

/** 从服务端 registry 拉取代码列表，失败时回退到本地兜底 */
export async function fetchResearchCardCodes() {
  try {
    const r = await getResearchCodes()
    const codes = (r?.codes || [])
      .map((c) => String(c || '').toUpperCase().trim())
      .filter(Boolean)
    if (codes.length) return sortResearchCardCodes(codes)
  } catch {
    /* 使用兜底 */
  }
  return [...RESEARCH_CARD_CODES_FALLBACK]
}
export const getResearchCards = () => request.get('/ai-stock-hub/cards')
export const getResearchCard = (symbol) =>
  request.get(`/ai-stock-hub/card/${encodeURIComponent(symbol)}`)
export const getResearchReport = (symbol) =>
  request.get(`/ai-stock-hub/report/${encodeURIComponent(symbol)}`)

export const getNvdaCard = () => getResearchCard('NVDA')
export const getNvdaReport = () => getResearchReport('NVDA')

export const loadResearchPdfObjectUrl = async (symbol) => {
  const token = localStorage.getItem('token')
  const res = await axios.get(`/api/ai-stock-hub/pdf/${encodeURIComponent(symbol)}`, {
    responseType: 'blob',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    withCredentials: true,
  })
  const blob = res.data instanceof Blob ? res.data : new Blob([res.data], { type: 'application/pdf' })
  if (!blob.size) throw new Error('PDF 文件为空')
  return URL.createObjectURL(blob)
}

export const revokeObjectUrl = (url) => {
  if (url) URL.revokeObjectURL(url)
}

export const getPushHistory = (params) => request.get('/ai-stock-hub/push-history', { params })
export const getStrategySignals = (symbol, params) =>
  request.get(`/ai-stock-hub/signals/${encodeURIComponent(symbol)}`, { params })
