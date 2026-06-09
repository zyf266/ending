import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AI_STOCK_REPORTS } from '../data/aiStockReports'
import { RESEARCH_CARDS_FALLBACK } from '../data/researchCardsFallback'
import {
  fetchResearchCardCodes,
  getResearchCard,
  getResearchCards,
  RESEARCH_CARD_CODES_FALLBACK,
  sortResearchCardCodes,
} from '../api/aiStockHub'
import ResearchCard from './ResearchCard'
import './AiStock.css'

const formatPrice = (price, currency) => {
  if (price == null || !Number.isFinite(Number(price))) return '-'
  const n = Number(price)
  if (currency === 'CNY') return `¥${n.toFixed(2)}`
  if (currency === 'USD') return `$${n.toFixed(2)}`
  return `${n.toFixed(2)}`
}

const fallbackHub = (code) => ({
  card: RESEARCH_CARDS_FALLBACK[code] || { code, name: code, tagline: code, scenarios: [] },
  price: null,
  currency: 'USD',
  news_summary: null,
  signal_summary: null,
})

const AiStock = () => {
  const navigate = useNavigate()
  const [q, setQ] = useState('')
  const [hubs, setHubs] = useState({})
  const [cardCodes, setCardCodes] = useState(RESEARCH_CARD_CODES_FALLBACK)
  const [loading, setLoading] = useState(true)
  const [loadErr, setLoadErr] = useState(null)
  const [refreshPulse, setRefreshPulse] = useState(0)

  const loadCards = useCallback(async () => {
    setLoading(true)
    setLoadErr(null)
    const map = {}
    let codes = RESEARCH_CARD_CODES_FALLBACK

    try {
      codes = await fetchResearchCardCodes()
      setCardCodes(codes)
    } catch {
      /* 保持兜底列表 */
    }

    try {
      const r = await getResearchCards()
      for (const item of r?.items || []) {
        const code = String(item?.card?.code || '').toUpperCase()
        if (code) map[code] = item
      }
      // 以 API 返回的卡片为准补全列表（防止 registry 新增但兜底未更新）
      const fromItems = (r?.items || [])
        .map((item) => String(item?.card?.code || '').toUpperCase())
        .filter(Boolean)
      if (fromItems.length) {
        codes = sortResearchCardCodes([...codes, ...fromItems])
        setCardCodes(codes)
      }
    } catch (e) {
      setLoadErr(e?.response?.data?.detail || e?.message || '批量加载失败')
    }

    await Promise.all(
      codes.map(async (code) => {
        if (map[code]?.card?.tagline) return
        try {
          map[code] = await getResearchCard(code)
        } catch {
          if (!map[code]) map[code] = fallbackHub(code)
        }
      })
    )

    for (const code of codes) {
      if (!map[code]) map[code] = fallbackHub(code)
    }

    setHubs(map)
    setRefreshPulse((n) => n + 1)
    setLoading(false)
  }, [])

  useEffect(() => {
    loadCards()
    const t = setInterval(loadCards, 30 * 60 * 1000)
    return () => clearInterval(t)
  }, [loadCards])

  const researchList = useMemo(() => {
    const kw = q.trim().toLowerCase()
    const filtered = cardCodes.filter((code) => {
      const hub = hubs[code] || fallbackHub(code)
      const card = hub?.card || {}
      if (!kw) return true
      const c = String(code).toLowerCase()
      const name = String(card.name || '').toLowerCase()
      const tag = String(card.tagline || '').toLowerCase()
      return c.includes(kw) || name.includes(kw) || tag.includes(kw)
    })
    return sortResearchCardCodes(filtered)
  }, [q, hubs, cardCodes])

  const legacyList = useMemo(() => {
    const kw = q.trim().toLowerCase()
    const codes = new Set(cardCodes)
    return AI_STOCK_REPORTS.filter((x) => {
      if (codes.has(String(x.code).toUpperCase())) return false
      if (!kw) return true
      const code = String(x.code || '').toLowerCase()
      const name = String(x.name || '').toLowerCase()
      return code.includes(kw) || name.includes(kw)
    })
  }, [q, cardCodes])

  const gridKey = `${q || 'all'}-${refreshPulse}`

  return (
    <div className="page ais-page">
      <div className="ais-shell">
        <header className="ais-header">
          <div className="ais-title-row">
            <div>
              <h3 className="ais-title">AI选股</h3>
              <p className="ais-sub">机构级 PDF 研报 · 一行两个卡片 · 点击进入完整深度分析</p>
            </div>
            <div className="ais-search">
              <input
                className="ais-input"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="搜索：代码 / 名称（如 NVDA、INTC、ETH）"
              />
            </div>
          </div>
          {loadErr && <div className="ais-load-err">{loadErr}（已使用本地卡片数据）</div>}
        </header>

        <div className={`ais-grid ais-grid-research${loading ? ' ais-grid-loading' : ''}`} key={gridKey}>
          {researchList.map((code, index) => (
            <ResearchCard
              key={code}
              index={index}
              code={code}
              hub={hubs[code] || fallbackHub(code)}
              loading={loading && !hubs[code]}
              onOpenNews={() => navigate(`/ai-stock/${code}/news`)}
              onOpenSignals={() => navigate(`/ai-stock/${code}/signals`)}
              onOpenDetail={() => navigate(`/ai-stock/${code}?tab=fullreport`)}
            />
          ))}
          {legacyList.map((item) => (
            <button
              key={item.code}
              type="button"
              className="ais-card ais-card-enter"
              onClick={() => navigate(`/ai-stock/${encodeURIComponent(item.code)}`)}
            >
              <div className="ais-card-top">
                <div className="ais-name">{item.name}</div>
                <div className="ais-code">{item.code}</div>
              </div>
              <div className="ais-price-row">
                <div className="ais-price">{formatPrice(item.price, item.currency)}</div>
                <div className="ais-muted">更新 {item.updated_at || '-'}</div>
              </div>
              <div className="ais-tags">
                <span className="ais-tag">研究卡片</span>
                <span className="ais-tag ais-tag-outline">AI分析</span>
              </div>
            </button>
          ))}
          {!loading && researchList.length === 0 && legacyList.length === 0 && (
            <div className="ais-empty ais-empty-span2">
              <div className="ais-empty-title">没有匹配结果</div>
              <div className="ais-empty-sub">换个关键词试试</div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default AiStock
