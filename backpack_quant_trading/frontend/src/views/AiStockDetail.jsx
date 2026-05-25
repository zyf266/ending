import React, { useEffect, useMemo, useRef, useState } from 'react'
import { NavLink, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { getAiStockReportByCode } from '../data/aiStockReports'
import NvdaFullReport from './NvdaFullReport'
import { getResearchCard, RESEARCH_CARD_CODES } from '../api/aiStockHub'
import { RESEARCH_CARDS_FALLBACK } from '../data/researchCardsFallback'
import './AiStock.css'

const Row = ({ title, left, middle, right, target, keyLevel }) => {
  return (
    <div className="ais-row">
      <div className="ais-cell ais-cell-title">{title}</div>
      <div className="ais-cell">{left || '-'}</div>
      <div className="ais-cell">{middle || '-'}</div>
      <div className="ais-cell">{right || '-'}</div>
      <div className="ais-cell ais-cell-num">{target != null ? String(target) : '-'}</div>
      <div className="ais-cell ais-cell-num">{keyLevel != null ? String(keyLevel) : '-'}</div>
    </div>
  )
}

const AiStockDetail = () => {
  const { code } = useParams()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const sym = String(code || '').toUpperCase()
  const isResearchPdf = RESEARCH_CARD_CODES.includes(sym)

  const legacyItem = useMemo(() => getAiStockReportByCode(code), [code])
  const [pdfMeta, setPdfMeta] = useState(null)
  const fbCard = RESEARCH_CARDS_FALLBACK[sym]
  const item =
    legacyItem ||
    (isResearchPdf && (pdfMeta || fbCard)
      ? {
          code: sym,
          name: pdfMeta?.name || fbCard?.name || sym,
          updated_at: pdfMeta?.report_date || fbCard?.report_date || '-',
          report: null,
        }
      : null)
  const r = legacyItem?.report
  const pdfOnly = isResearchPdf && !legacyItem
  const initialTab =
    searchParams.get('tab') === 'fullreport' && isResearchPdf
      ? 'fullreport'
      : pdfOnly
        ? 'fullreport'
        : 'analysis'
  const [tab, setTab] = useState(initialTab) // analysis | report | fullreport
  const [streaming, setStreaming] = useState(false)
  const [analysis, setAnalysis] = useState({})
  const idxRef = useRef(0)
  const timerRef = useRef(null)

  useEffect(() => {
    if (!isResearchPdf || legacyItem) {
      setPdfMeta(null)
      return undefined
    }
    getResearchCard(sym)
      .then((h) => {
        const card = h?.card || {}
        setPdfMeta({
          name: card.name || sym,
          report_date: card.report_date,
          tagline: card.tagline,
        })
      })
        .catch(() => {
          const fb = RESEARCH_CARDS_FALLBACK[sym]
          setPdfMeta({
            name: fb?.name || sym,
            report_date: fb?.report_date || '-',
            tagline: fb?.tagline,
          })
        })
    return undefined
  }, [sym, isResearchPdf, legacyItem])

  useEffect(() => {
    if (pdfOnly) setTab('fullreport')
  }, [pdfOnly])

  const sections = useMemo(() => (r ? [
    { key: 'business', title: r.business?.title || '业务情况', focus: r.business?.left, ai: r.business?.middle, view: r.business?.right, target: r.business?.target },
    { key: 'finance', title: r.finance?.title || '财务状况', focus: r.finance?.left, ai: r.finance?.middle, view: r.finance?.right },
    { key: 'valuation', title: r.valuation?.title || '估值指标', focus: r.valuation?.left, ai: r.valuation?.middle, view: r.valuation?.right },
    { key: 'profitability', title: r.profitability?.title || '盈利能力', focus: r.profitability?.left, ai: r.profitability?.middle, view: r.profitability?.right },
    { key: 'technical', title: r.technical?.title || '技术面', focus: r.technical?.left, ai: r.technical?.middle, view: r.technical?.right, keyLevel: r.technical?.key_level },
    { key: 'catalysts', title: r.catalysts?.title || '催化剂', focus: r.catalysts?.left, ai: r.catalysts?.middle, view: r.catalysts?.right },
    { key: 'external', title: r.external?.title || '被动影响', focus: r.external?.left, ai: r.external?.middle, view: r.external?.right },
    { key: 'safety', title: r.safety?.title || '安全边际', focus: r.safety?.left, ai: r.safety?.middle, view: r.safety?.right },
  ] : []), [r])

  const fullAnalysis = useMemo(() => {
    if (!r) return { conclusion: { title: '总结', text: '—' } }
    const safe = (v) => (v == null ? '' : String(v).trim())
    const init = {}
    for (const s of sections) {
      init[s.key] = {
        title: s.title,
        focus: safe(s.focus) || '—',
        ai: safe(s.ai) || '—',
        view: safe(s.view) || '—',
        target: s.target != null ? String(s.target) : '',
        keyLevel: s.keyLevel != null ? String(s.keyLevel) : '',
      }
    }
    init.conclusion = { title: r.conclusion?.title || '总结', text: safe(r.conclusion?.text) || '—' }
    return init
  }, [sections, r])

  const startStream = () => {
    if (timerRef.current) clearInterval(timerRef.current)
    setAnalysis(() => {
      const empty = {}
      for (const s of sections) {
        empty[s.key] = { title: s.title, focus: '', ai: '', view: '', target: '', keyLevel: '' }
      }
      empty.conclusion = { title: fullAnalysis.conclusion?.title || '总结', text: '' }
      return empty
    })
    idxRef.current = 0
    setStreaming(true)
    const steps = []
    for (const s of sections) {
      steps.push({ key: s.key, field: 'focus', text: fullAnalysis[s.key]?.focus || '—' })
      steps.push({ key: s.key, field: 'ai', text: fullAnalysis[s.key]?.ai || '—' })
      steps.push({ key: s.key, field: 'view', text: fullAnalysis[s.key]?.view || '—' })
      if (fullAnalysis[s.key]?.target) steps.push({ key: s.key, field: 'target', text: fullAnalysis[s.key].target })
      if (fullAnalysis[s.key]?.keyLevel) steps.push({ key: s.key, field: 'keyLevel', text: fullAnalysis[s.key].keyLevel })
    }
    steps.push({ key: 'conclusion', field: 'text', text: fullAnalysis.conclusion?.text || '—' })

    timerRef.current = setInterval(() => {
      const i = idxRef.current
      if (i >= steps.length) {
        clearInterval(timerRef.current)
        timerRef.current = null
        setStreaming(false)
        return
      }
      const step = steps[i]
      idxRef.current += 1
      setAnalysis((prev) => {
        const cur = prev?.[step.key] || {}
        const next = { ...prev }
        next[step.key] = { ...cur, [step.field]: step.text }
        return next
      })
    }, 220)
  }

  const stopStream = () => {
    if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
    setStreaming(false)
  }

  useEffect(() => {
    if (!r || tab === 'fullreport' || tab !== 'analysis') return undefined
    startStream()
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sym, tab, r])

  const fullReportMode = isResearchPdf && tab === 'fullreport'

  useEffect(() => {
    const el = document.querySelector('.page-content')
    if (!el) return undefined
    if (fullReportMode) {
      el.classList.add('page-content-fullreport')
    } else {
      el.classList.remove('page-content-fullreport')
    }
    return () => el.classList.remove('page-content-fullreport')
  }, [fullReportMode])

  if (!item) {
    return (
      <div className="page ais-page">
        <div className="ais-detail-header">
          <button type="button" className="ais-back" onClick={() => navigate('/ai-stock')}>
            ← 返回
          </button>
        </div>
        <div className="ais-empty">
          <div className="ais-empty-title">{isResearchPdf ? '加载研报…' : '未找到该股票'}</div>
          <div className="ais-empty-sub">
            <span className="ais-mono">{String(code || '')}</span>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className={`page ais-page ${fullReportMode ? 'ais-page-fullreport' : ''}`}>
      <div className="ais-hero">
        <div className="ais-hero-top">
          <button type="button" className="ais-back-link" onClick={() => navigate('/ai-stock')}>
            ← 返回
          </button>
        </div>
        <div className="ais-hero-main">
          <div className="ais-hero-left">
            <div className="ais-hero-icon">📈</div>
            <div>
              <div className="ais-hero-name-row">
                <div className="ais-hero-name">{item.name}</div>
                <div className="ais-hero-code">{item.code}</div>
              </div>
              <div className="ais-hero-meta">更新日期：{item.updated_at || '-'}</div>
            </div>
          </div>
          <div className="ais-hero-tabs">
            {!pdfOnly && (
              <button
                type="button"
                className={`ais-pill ${tab === 'analysis' ? 'active' : ''}`}
                onClick={() => {
                  setTab('analysis')
                  startStream()
                }}
              >
                AI分析
              </button>
            )}
            {isResearchPdf && (
              <button
                type="button"
                className={`ais-pill ${tab === 'fullreport' ? 'active' : ''}`}
                onClick={() => {
                  stopStream()
                  setTab('fullreport')
                }}
              >
                完整研报
              </button>
            )}
            {!pdfOnly && (
              <button
                type="button"
                className={`ais-pill ${tab === 'report' ? 'active' : ''}`}
                onClick={() => {
                  stopStream()
                  setTab('report')
                }}
              >
                研究要点
              </button>
            )}
            <NavLink to={`/ai-stock/${encodeURIComponent(item.code)}/signals`} className="ais-pill">
              历史信号
            </NavLink>
            <NavLink to="/ai-stock" className="ais-pill">
              列表
            </NavLink>
          </div>
        </div>
      </div>

      {tab === 'fullreport' && isResearchPdf ? (
        <NvdaFullReport symbol={sym} />
      ) : tab === 'analysis' && r && !pdfOnly ? (
        <>
          <div className="ais-analysis-toolbar">
            <div className="ais-analysis-status">{streaming ? '实时生成中' : '已生成'}</div>
            <div className="ais-analysis-actions">
              <button
                type="button"
                className="ais-ghost-btn"
                onClick={() => {
                  if (streaming) return
                  startStream()
                }}
              >
                查看生成
              </button>
              <button
                type="button"
                className="ais-primary-btn"
                onClick={() => {
                  stopStream()
                  setAnalysis(fullAnalysis)
                }}
              >
                立即展示
              </button>
            </div>
          </div>

          <div className="ais-card-grid">
            {sections.map((s) => {
              const a = analysis?.[s.key] || {}
              return (
                <div key={s.key} className="ais-info-card">
                  <div className="ais-info-title">{a.title || s.title}</div>
                  <div className="ais-info-block">
                    <div className="ais-info-k">关注点</div>
                    <div className="ais-info-v">{a.focus || (streaming ? '…' : fullAnalysis[s.key]?.focus)}</div>
                  </div>
                  <div className="ais-info-block">
                    <div className="ais-info-k">AI要点</div>
                    <div className="ais-info-v">{a.ai || (streaming ? '…' : fullAnalysis[s.key]?.ai)}</div>
                  </div>
                  <div className="ais-info-block">
                    <div className="ais-info-k">观点</div>
                    <div className="ais-info-v ais-info-v-strong">{a.view || (streaming ? '…' : fullAnalysis[s.key]?.view)}</div>
                  </div>
                  {(fullAnalysis[s.key]?.target || fullAnalysis[s.key]?.keyLevel) && (
                    <div className="ais-info-foot">
                      {fullAnalysis[s.key]?.target && (
                        <div className="ais-info-foot-item">
                          <span className="ais-info-foot-k">目标价</span>
                          <span className="ais-info-foot-v">{a.target || fullAnalysis[s.key]?.target}</span>
                        </div>
                      )}
                      {fullAnalysis[s.key]?.keyLevel && (
                        <div className="ais-info-foot-item">
                          <span className="ais-info-foot-k">关键位</span>
                          <span className="ais-info-foot-v">{a.keyLevel || fullAnalysis[s.key]?.keyLevel}</span>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>

          <div className="ais-conclusion">
            <div className="ais-conclusion-title">{analysis?.conclusion?.title || fullAnalysis.conclusion?.title || '总结'}</div>
            <div className="ais-conclusion-text">{analysis?.conclusion?.text || (streaming ? '…' : fullAnalysis.conclusion?.text) || '-'}</div>
          </div>
        </>
      ) : r ? (
        <>
          <div className="ais-table">
            <div className="ais-row ais-row-head">
              <div className="ais-cell ais-cell-title">维度</div>
              <div className="ais-cell">要看什么</div>
              <div className="ais-cell">AI要点</div>
              <div className="ais-cell">结论/观点</div>
              <div className="ais-cell ais-cell-num">目标价</div>
              <div className="ais-cell ais-cell-num">关键位</div>
            </div>

            <Row
              title={r.business?.title}
              left={r.business?.left}
              middle={r.business?.middle}
              right={r.business?.right}
              target={r.business?.target}
            />
            <Row
              title={r.finance?.title}
              left={r.finance?.left}
              middle={r.finance?.middle}
              right={r.finance?.right}
            />
            <Row
              title={r.valuation?.title}
              left={r.valuation?.left}
              middle={r.valuation?.middle}
              right={r.valuation?.right}
            />
            <Row
              title={r.profitability?.title}
              left={r.profitability?.left}
              middle={r.profitability?.middle}
              right={r.profitability?.right}
            />
            <Row
              title={r.technical?.title}
              left={r.technical?.left}
              middle={r.technical?.middle}
              right={r.technical?.right}
              keyLevel={r.technical?.key_level}
            />
            <Row
              title={r.catalysts?.title}
              left={r.catalysts?.left}
              middle={r.catalysts?.middle}
              right={r.catalysts?.right}
            />
            <Row
              title={r.external?.title}
              left={r.external?.left}
              middle={r.external?.middle}
              right={r.external?.right}
            />
            <Row
              title={r.safety?.title}
              left={r.safety?.left}
              middle={r.safety?.middle}
              right={r.safety?.right}
            />
          </div>

          <div className="ais-conclusion">
            <div className="ais-conclusion-title">{r.conclusion?.title || '总结'}</div>
            <div className="ais-conclusion-text">{r.conclusion?.text || '-'}</div>
          </div>
        </>
      ) : null}
    </div>
  )
}

export default AiStockDetail

