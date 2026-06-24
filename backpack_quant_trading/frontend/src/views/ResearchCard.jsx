import React from 'react'
import { researchCardThemeClass, researchCardThemeStyle } from '../data/researchCardThemes'
import './AiStock.css'

const formatPrice = (price, currency) => {
  if (price == null || !Number.isFinite(Number(price))) return '—'
  const n = Number(price)
  if (currency === 'CNY') return `¥${n.toFixed(2)}`
  if (currency === 'USD') return `$${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}`
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 })
}

const formatScenarioRange = (low, high, currency) => {
  if (low == null || high == null) return '—'
  if (currency === 'CNY') return `¥${low} – ¥${high}`
  return `$${low} – $${high}`
}

const ResearchCard = ({ code: codeProp, hub, loading, index = 0, onOpenNews, onOpenSignals, onOpenDetail }) => {
  const card = hub?.card || {}
  const code = String(codeProp || card.code || '').toUpperCase()
  const scenarios = card.scenarios || []
  const highlights = card.highlights || []
  const newsSummary = hub?.news_summary
  const signalSummary = hub?.signal_summary
  const price = hub?.price
  const priceUpdatedAt = hub?.price_updated_at
  const currency = hub?.currency || 'USD'

  const stagger = `${Math.min(index, 8) * 0.08}s`
  const themeClass = researchCardThemeClass(code)
  const themeStyle = researchCardThemeStyle(code)

  if (loading) {
    return (
      <div
        className={`ais-card ais-card-research ais-card-loading ${themeClass}`}
        style={{ '--ais-stagger': stagger, ...themeStyle }}
      >
        <div className="ais-rc-shimmer" />
        <div className="ais-muted">加载 {code}…</div>
      </div>
    )
  }

  return (
    <article
      className={`ais-card ais-card-research ais-card-enter ${themeClass}`}
      style={{ '--ais-stagger': stagger, ...themeStyle }}
    >
      <div className="ais-rc-glow" aria-hidden />
      <header className="ais-rc-top">
        <div className="ais-rc-top-main">
          <div className="ais-rc-badge">{code}</div>
          <div className="ais-rc-head-text">
            <h3 className="ais-rc-tagline">{card.tagline || code}</h3>
            <span className="ais-rc-name">{card.name || code}</span>
          </div>
        </div>
        <div className="ais-rc-price-block">
          <span className="ais-rc-price-label">当前价格</span>
          <span className="ais-rc-price">{formatPrice(price, currency)}</span>
          {priceUpdatedAt ? (
            <span className="ais-rc-price-updated" title="每日北京时间 5:00 自动同步">
              报价 {priceUpdatedAt}
            </span>
          ) : null}
        </div>
      </header>

      {scenarios.length > 0 ? (
        <div className="ais-scenario-row">
          {scenarios.map((s) => (
            <div key={s.key} className={`ais-scenario ais-scenario-${s.key}`}>
              <div className="ais-scenario-label">{s.label}</div>
              <div className="ais-scenario-prob">{s.probability}</div>
              <div className="ais-scenario-range">
                {formatScenarioRange(s.range_low, s.range_high, currency)}
              </div>
              {s.subtitle && <div className="ais-scenario-sub">{s.subtitle}</div>}
            </div>
          ))}
        </div>
      ) : highlights.length > 0 ? (
        <ul className="ais-research-highlights">
          {highlights.map((h, i) => (
            <li key={i}>{h}</li>
          ))}
        </ul>
      ) : null}

      <div className="ais-rc-feeds">
        <section className="ais-rc-feed">
          <div className="ais-rc-feed-hd">
            <span className="ais-rc-feed-icon" aria-hidden>◇</span>
            <span>相关新闻</span>
          </div>
          {newsSummary ? (
            <button type="button" className="ais-rc-feed-body" onClick={onOpenNews}>
              <p className="ais-rc-feed-text">{newsSummary}</p>
              <span className="ais-rc-feed-link">查看全部历史 →</span>
            </button>
          ) : (
            <p className="ais-rc-feed-empty">暂无匹配快讯</p>
          )}
        </section>
        <section className="ais-rc-feed">
          <div className="ais-rc-feed-hd">
            <span className="ais-rc-feed-icon ais-rc-feed-icon-signal" aria-hidden>◆</span>
            <span>相关信号</span>
          </div>
          {signalSummary ? (
            <button type="button" className="ais-rc-feed-body" onClick={onOpenSignals}>
              <p className="ais-rc-feed-text">{signalSummary}</p>
              <span className="ais-rc-feed-link">查看全部信号 →</span>
            </button>
          ) : (
            <p className="ais-rc-feed-empty">暂无匹配信号</p>
          )}
        </section>
      </div>

      <footer className="ais-rc-footer">
        <button type="button" className="ais-rc-cta" onClick={onOpenDetail}>
          完整研报
          <span className="ais-rc-cta-arrow" aria-hidden>→</span>
        </button>
      </footer>
    </article>
  )
}

export default ResearchCard
