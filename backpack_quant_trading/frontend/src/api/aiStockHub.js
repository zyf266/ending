import axios from 'axios'
import request from './request'

// 卡片列表以服务端 registry 为准；这里仅作为前端兜底顺序
export const RESEARCH_CARD_CODES = ['NVDA', 'INTC', 'CRCL', 'SNDK', 'ETH', 'HYPE', 'ONDO', '000858', 'GOOGL', 'CRDO']

export const getResearchCodes = () => request.get('/ai-stock-hub/research-codes')
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
