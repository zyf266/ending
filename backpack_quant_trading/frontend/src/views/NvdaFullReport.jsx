import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { getResearchReport } from '../api/aiStockHub'
import { researchCardThemeClass, researchCardThemeStyle } from '../data/researchCardThemes'
import './AiStock.css'

const ICONS = {
  chart: '◫',
  server: '▣',
  calendar: '▦',
  layers: '☰',
  target: '◎',
  chip: '◈',
  cash: '¤',
  trend: '↗',
  flow: '⇄',
  rocket: '↑',
  trophy: '★',
  network: '⬡',
  factory: '⌂',
  line: '∿',
  globe: '○',
  robot: '◇',
  stack: '▤',
  shield: '⛨',
  cloud: '☁',
  bolt: '⚡',
}

const PdfIcon = ({ name }) => (
  <span className="nv-pdf-icon" aria-hidden>
    {ICONS[name] || '●'}
  </span>
)

const isSubSection = (id) => /^\d+b$/i.test(String(id || ''))

const formatSectionNo = (id) => {
  const s = String(id || '')
  if (isSubSection(s)) return ''
  if (/^\d+$/.test(s)) return s.padStart(2, '0')
  return ''
}

const sectionDisplayTitle = (sec) => {
  const no = formatSectionNo(sec.id)
  if (no) return `${no} ${sec.title}`
  return sec.title
}

const blockSteps = (sec, block) => {
  const sid = sec.id
  const steps = []
  if (block.type === 'stat_cards') {
    for (const c of block.items || []) {
      steps.push({ kind: 'statCard', sectionId: sid, data: c })
    }
  } else if (block.type === 'icon_cards') {
    for (const c of block.items || []) {
      steps.push({ kind: 'iconCard', sectionId: sid, data: c })
    }
  } else if (block.type === 'dual_footer') {
    for (const c of block.items || []) {
      steps.push({ kind: 'dualItem', sectionId: sid, data: c })
    }
  } else if (block.type === 'two_columns') {
    for (const col of block.columns || []) {
      for (const c of col.items || []) {
        steps.push({ kind: 'colItem', sectionId: sid, colTitle: col.title, data: c })
      }
    }
  } else if (block.type === 'scenarios' || block.type === 'scenario_cards') {
    for (const c of block.items || []) {
      steps.push({ kind: 'scenario', sectionId: sid, data: c })
    }
  } else if (block.type === 'bullets') {
    for (const item of block.items || []) {
      const text = typeof item === 'string' ? item : item?.text || ''
      if (text) steps.push({ kind: 'bullet', sectionId: sid, text })
    }
  } else if (block.type === 'p') {
    steps.push({ kind: 'para', sectionId: sid, text: block.text })
  }
  return steps
}

const buildStreamPlan = (report) => {
  if (!report) return []
  const label = report.name ? `${report.name}（${report.code}）` : report.code || '标的'
  const steps = [
    { kind: 'think', text: `正在加载 ${label} 深度研报…` },
    { kind: 'think', text: '正在解析 PDF 版式与配色…' },
    {
      kind: 'header',
      tagline: report.tagline,
      code: report.code,
      institution: report.institution,
      date: report.report_date,
    },
  ]
  const thinkBySection = {
    '01': '正在渲染营收四象限数据卡…',
    '01b': '正在生成资产负债表洞察网格…',
    '02': '正在对比需求端与供给端…',
    '02b': '正在归纳需求催化剂…',
    '02c': '正在分析竞争格局…',
    '03': '正在扫描地缘与供应链风险…',
    '04': '正在计算毛利率与定价权…',
    '05': '正在解读管理层指引…',
    '06': '正在构建目标价情景模型…',
    '07': '正在生成交易策略建议…',
    '08': '正在综合宏观联动因素…',
  }
  for (const sec of report.sections || []) {
    const hint = thinkBySection[sec.id] || `正在渲染「${sec.title}」…`
    steps.push({ kind: 'think', text: hint })
    steps.push({ kind: 'sectionStart', sectionId: sec.id })
    for (const block of sec.blocks || []) {
      steps.push(...blockSteps(sec, block))
    }
  }
  if (report.conclusion) {
    steps.push({ kind: 'think', text: '正在撰写综合结论…' })
    steps.push({ kind: 'conclusion', text: report.conclusion })
  }
  return steps
}

const TypeText = ({ text, active }) => {
  const full = text || ''
  const [shown, setShown] = useState(full)
  useEffect(() => {
    if (!active) {
      setShown(full)
      return undefined
    }
    setShown('')
    let i = 0
    const chunk = Math.max(2, Math.ceil(full.length / 38))
    const t = setInterval(() => {
      i += chunk
      setShown(full.slice(0, Math.min(i, full.length)))
      if (i >= full.length) clearInterval(t)
    }, 22)
    return () => clearInterval(t)
  }, [active, full])
  return <>{shown}</>
}

const NvdaFullReport = ({ symbol = 'NVDA' }) => {
  const sym = String(symbol || 'NVDA').toUpperCase()
  const themeClass = researchCardThemeClass(sym)
  const themeStyle = researchCardThemeStyle(sym)
  const [report, setReport] = useState(null)
  const [loadErr, setLoadErr] = useState(null)
  const plan = useMemo(() => buildStreamPlan(report), [report])
  const [stepIdx, setStepIdx] = useState(0)
  const [streaming, setStreaming] = useState(false)
  const [thinkLog, setThinkLog] = useState([])
  const timerRef = useRef(null)
  const scrollRef = useRef(null)

  const visible = useMemo(() => plan.slice(0, stepIdx), [plan, stepIdx])
  const done = !streaming && stepIdx >= plan.length

  const stopStream = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
    setStreaming(false)
  }, [])

  const startStream = useCallback(() => {
    if (!plan.length) return
    stopStream()
    setStepIdx(0)
    setThinkLog([])
    setStreaming(true)
    const delayFor = (step) => {
      if (!step) return 0
      if (step.kind === 'think') return 380
      if (step.kind === 'sectionStart') return 450
      if (step.kind === 'header') return 340
      if (step.kind === 'conclusion') return 420
      if (step.kind === 'statCard') return 200
      if (step.kind === 'scenario') return 260
      if (step.kind === 'bullet') return 180
      return 210
    }
    const tick = (i) => {
      const step = plan[i]
      if (!step) {
        stopStream()
        setStepIdx(plan.length)
        return
      }
      if (step.kind === 'think') setThinkLog((p) => [...p.slice(-7), step.text])
      setStepIdx(i + 1)
      requestAnimationFrame(() => {
        if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight
      })
      let wait = delayFor(plan[i + 1] || step)
      if (i + 1 >= plan.length && step.kind === 'conclusion') {
        wait = Math.min(9000, (step.text?.length || 200) * 26 + 700)
      }
      timerRef.current = setTimeout(() => tick(i + 1), wait)
    }
    timerRef.current = setTimeout(() => tick(0), 240)
  }, [plan, stopStream])

  const showAll = useCallback(() => {
    stopStream()
    setStepIdx(plan.length)
    setThinkLog([])
  }, [plan.length, stopStream])

  useEffect(() => {
    setReport(null)
    setLoadErr(null)
    getResearchReport(sym)
      .then((r) => {
        setReport(r)
        setLoadErr(null)
      })
      .catch((e) => setLoadErr(e?.response?.data?.detail || e?.message || '研报加载失败'))
  }, [sym])

  useEffect(() => {
    if (report) startStream()
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
      stopStream()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [report])

  const count = (secId, kind) => visible.filter((s) => s.sectionId === secId && s.kind === kind).length

  const renderBlock = (sec, block, bi, isActive) => {
    const sid = sec.id
    if (block.type === 'stat_cards') {
      const n = count(sid, 'statCard')
      const cards = (block.items || []).filter((_, i) => done || i < n)
      if (!cards.length) return null
      const layout = block.layout === '3' ? 'nv-pdf-stat-row-3' : 'nv-pdf-stat-row-4'
      return (
        <div key={bi} className={`nv-pdf-stat-row ${layout}`}>
          {cards.map((c, i) => (
            <div key={i} className="nv-pdf-stat-card">
              <div className="nv-pdf-stat-card-hd">
                <PdfIcon name={c.icon} />
                <span>{c.title}</span>
              </div>
              <div className="nv-pdf-stat-value">{c.value}</div>
              {(c.lines || []).map((ln, j) => (
                <div key={j} className="nv-pdf-stat-line">{ln}</div>
              ))}
            </div>
          ))}
        </div>
      )
    }
    if (block.type === 'icon_cards') {
      const n = count(sid, 'iconCard')
      const cards = (block.items || []).filter((_, i) => done || i < n)
      if (!cards.length) return null
      const grid = block.layout === '2x2' ? 'nv-pdf-icon-grid-2x2' : 'nv-pdf-icon-grid-2x3'
      return (
        <div key={bi} className={`nv-pdf-icon-grid ${grid}`}>
          {cards.map((c, i) => (
            <div key={i} className="nv-pdf-icon-card">
              <div className="nv-pdf-icon-card-hd">
                <PdfIcon name={c.icon} />
                <span className="nv-pdf-icon-card-title">{c.title}</span>
              </div>
              <p className="nv-pdf-icon-card-text">
                <TypeText text={c.text} active={streaming && isActive && i === cards.length - 1} />
              </p>
            </div>
          ))}
        </div>
      )
    }
    if (block.type === 'dual_footer') {
      const n = count(sid, 'dualItem')
      const items = (block.items || []).filter((_, i) => done || i < n)
      if (!items.length) return null
      return (
        <div key={bi} className="nv-pdf-dual-footer">
          {items.map((c, i) => (
            <div key={i} className="nv-pdf-dual-item">
              <div className="nv-pdf-dual-hd">
                <PdfIcon name={c.icon} />
                <span>{c.title}</span>
              </div>
              <p className="nv-pdf-dual-text">
                <TypeText text={c.text} active={streaming && isActive && i === items.length - 1} />
              </p>
            </div>
          ))}
        </div>
      )
    }
    if (block.type === 'two_columns') {
      const n = count(sid, 'colItem')
      let shown = 0
      return (
        <div key={bi} className="nv-pdf-two-cols">
          {(block.columns || []).map((col, ci) => {
            const items = (col.items || []).map((c) => {
              const ok = done || shown < n
              if (ok) shown += 1
              return ok ? c : null
            }).filter(Boolean)
            if (!items.length) return null
            return (
              <div key={ci} className="nv-pdf-col-panel">
                <div className="nv-pdf-col-title">{col.title}</div>
                {items.map((c, i) => (
                  <div key={i} className="nv-pdf-col-item">
                    <div className="nv-pdf-col-item-hd">
                      <PdfIcon name={c.icon} />
                      <span>{c.title}</span>
                    </div>
                    <p className="nv-pdf-col-item-text">
                      <TypeText text={c.text} active={streaming && isActive && i === items.length - 1} />
                    </p>
                  </div>
                ))}
              </div>
            )
          })}
        </div>
      )
    }
    if (block.type === 'scenarios' || block.type === 'scenario_cards') {
      const n = count(sid, 'scenario')
      const cards = (block.items || []).filter((_, i) => done || i < n)
      if (!cards.length) return null
      return (
        <div key={bi} className="nv-pdf-scenario-row">
          {cards.map((c) => {
            const price =
              c.range_low != null && c.range_high != null
                ? `$${c.range_low} – $${c.range_high}`
                : (c.range || '')
            const sub = c.subtitle ? `${c.probability || ''} · ${c.subtitle}` : (c.probability || '')
            const note = c.note || c.text || ''
            return (
              <div key={c.key} className={`nv-pdf-scenario-card nv-pdf-scenario-${c.key}`}>
                <div className="nv-pdf-scenario-label">{c.label}</div>
                {sub && <div className="nv-pdf-scenario-sub">{sub}</div>}
                {price && <div className="nv-pdf-scenario-price">{price}</div>}
                {note && <div className="nv-pdf-scenario-note">{note}</div>}
              </div>
            )
          })}
        </div>
      )
    }
    if (block.type === 'bullets') {
      const n = count(sid, 'bullet')
      const items = (block.items || []).filter((_, i) => done || i < n)
      if (!items.length) return null
      return (
        <div key={bi} className="nv-pdf-bullets">
          {block.title && <div className="nv-pdf-bullets-title">{block.title}</div>}
          <ul className="ais-pdf-ul nv-pdf-ul">
            {items.map((item, i) => {
              const text = typeof item === 'string' ? item : item?.text || ''
              return (
                <li key={i}>
                  <TypeText text={text} active={streaming && isActive && i === items.length - 1} />
                </li>
              )
            })}
          </ul>
        </div>
      )
    }
    if (block.type === 'p') {
      if (!done && count(sid, 'para') < 1) return null
      const p = visible.find((s) => s.kind === 'para' && s.sectionId === sid)
      return (
        <p key={bi} className="nv-pdf-para">
          <TypeText text={p?.text || block.text} active={streaming && isActive} />
        </p>
      )
    }
    return null
  }

  const renderSection = (secId) => {
    const sec = (report?.sections || []).find((s) => s.id === secId)
    if (!sec || !visible.some((s) => s.kind === 'sectionStart' && s.sectionId === secId)) return null
    const isActive = [...visible].reverse().find((s) => s.sectionId)?.sectionId === secId && streaming
    return (
      <section key={secId} className={`nv-pdf-slide ${isActive ? 'nv-pdf-slide-active' : ''}`}>
        <h2 className="nv-pdf-slide-title">{sectionDisplayTitle(sec)}</h2>
        {sec.subtitle && <p className="nv-pdf-slide-sub">{sec.subtitle}</p>}
        {sec.blocks.map((b, i) => renderBlock(sec, b, i, isActive))}
      </section>
    )
  }

  const headerStep = visible.find((s) => s.kind === 'header')
  const conclusionVisible = visible.find((s) => s.kind === 'conclusion')
  const progress = plan.length ? Math.min(100, Math.round((stepIdx / plan.length) * 100)) : 0

  if (loadErr) return <div className="ais-pdf-error">{loadErr}</div>
  if (!report) return <div className="ais-muted ais-report-loading">正在加载研报…</div>

  return (
    <div className={`nv-pdf-report-root ${themeClass}`} style={themeStyle}>
      <div className="ais-analysis-toolbar nv-pdf-toolbar">
        <div className="ais-analysis-status">
          {streaming ? (
            <span className="ais-report-live">
              <span className="ais-report-dot" /> AI 研报生成中… {progress}%
            </span>
          ) : (
            '研报已生成'
          )}
          {streaming && (
            <div className="ais-report-progress">
              <div className="ais-report-progress-bar" style={{ width: `${progress}%` }} />
            </div>
          )}
        </div>
        <div className="ais-analysis-actions">
          <button type="button" className="ais-ghost-btn nv-pdf-btn-ghost" disabled={streaming} onClick={startStream}>
            重新生成
          </button>
          <button type="button" className="ais-primary-btn" onClick={showAll}>
            立即展示
          </button>
        </div>
      </div>

      {thinkLog.length > 0 && streaming && (
        <div className="ais-report-think nv-pdf-think">
          <div className="ais-report-think-title">
            AI 思考过程
            <span className="ais-report-think-pulse">分析中</span>
          </div>
          <ul className="ais-report-think-list">
            {thinkLog.map((t, i) => (
              <li key={i} className={i === thinkLog.length - 1 ? 'active' : 'done'}>{t}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="nv-pdf-canvas" ref={scrollRef}>
        {headerStep && (
          <header className="nv-pdf-cover-slide">
            <div className="nv-pdf-cover-code">
              {report?.name || headerStep.code} ({headerStep.code})
            </div>
            <h1 className="nv-pdf-cover-title">{headerStep.tagline}</h1>
            <p className="nv-pdf-cover-org">{headerStep.institution}</p>
            <p className="nv-pdf-cover-date">报告时间：{headerStep.date}</p>
          </header>
        )}
        {(report.sections || []).map((s) => renderSection(s.id))}
        {conclusionVisible && (
          <section className="nv-pdf-slide nv-pdf-slide-conclusion">
            <h2 className="nv-pdf-slide-title">综合结论</h2>
            <p className="nv-pdf-para">
              <TypeText
                text={conclusionVisible.text}
                active={streaming && stepIdx >= plan.length - 1 && stepIdx <= plan.length}
              />
            </p>
          </section>
        )}
      </div>
    </div>
  )
}

export default NvdaFullReport
