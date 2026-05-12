import React, { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AI_STOCK_REPORTS } from '../data/aiStockReports'
import './AiStock.css'

const formatPrice = (price, currency) => {
  if (price == null || !Number.isFinite(Number(price))) return '-'
  const n = Number(price)
  if (currency === 'CNY') return `¥${n.toFixed(2)}`
  if (currency === 'USD') return `$${n.toFixed(2)}`
  return `${n.toFixed(2)}`
}

const AiStock = () => {
  const navigate = useNavigate()
  const [q, setQ] = useState('')

  const list = useMemo(() => {
    const kw = q.trim().toLowerCase()
    if (!kw) return AI_STOCK_REPORTS
    return AI_STOCK_REPORTS.filter((x) => {
      const code = String(x.code || '').toLowerCase()
      const name = String(x.name || '').toLowerCase()
      return code.includes(kw) || name.includes(kw)
    })
  }, [q])

  return (
    <div className="page ais-page">
      <div className="ais-header">
        <div className="ais-title-row">
          <div>
            <h3 className="ais-title">AI选股</h3>
            <p className="ais-sub">卡片列表查看，点击进入研究要点详情</p>
          </div>
          <div className="ais-search">
            <input
              className="ais-input"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="搜索：代码 / 名称（如 NVDA、茅台）"
            />
          </div>
        </div>
      </div>

      <div className="ais-grid">
        {list.map((item) => (
          <button
            key={item.code}
            type="button"
            className="ais-card"
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
        {list.length === 0 && (
          <div className="ais-empty">
            <div className="ais-empty-title">没有匹配结果</div>
            <div className="ais-empty-sub">换个关键词试试</div>
          </div>
        )}
      </div>
    </div>
  )
}

export default AiStock

