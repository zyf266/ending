import React, { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { getPushHistory } from '../api/aiStockHub'
import './AiStock.css'

const AiStockNewsHistory = () => {
  const { code } = useParams()
  const navigate = useNavigate()
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const r = await getPushHistory({ limit: 100 })
      setItems(r.items || [])
    } catch (_) {
      setItems([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  return (
    <div className="page ais-page">
      <div className="ais-detail-header">
        <button type="button" className="ais-back" onClick={() => navigate('/ai-stock')}>
          ← 返回 AI选股
        </button>
        <div className="ais-detail-title">
          <div className="ais-detail-name">相关新闻历史</div>
          <div className="ais-detail-code">{String(code || 'NVDA').toUpperCase()}</div>
        </div>
      </div>
      <p className="ais-sub" style={{ margin: '0 0 12px' }}>
        数据来自 <code>backpack_quant_trading/data/manual_news_paste.txt</code>（最新一条）及{' '}
        <code>manual_news_history.json</code>。更新 txt 后刷新本页即可。
      </p>
      {loading && <div className="ais-muted">加载中…</div>}
      {!loading && items.length === 0 && (
        <div className="ais-empty">
          <div className="ais-empty-title">暂无记录</div>
          <div className="ais-empty-sub">请向 manual_news_paste.txt 粘贴钉钉快讯全文</div>
        </div>
      )}
      <ul className="ais-news-history">
        {items.map((n) => (
          <li key={n.id || n.summary} className="ais-news-item">
            <div className="ais-news-meta">
              <span className="ais-tag">{n.feed || '快讯'}</span>
              <span className="ais-muted">{n.time || n.saved_at}</span>
            </div>
            <div className="ais-news-text">{n.summary || n.text}</div>
            {n.raw ? <pre className="ais-raw-block">{n.raw}</pre> : null}
          </li>
        ))}
      </ul>
    </div>
  )
}

export default AiStockNewsHistory
