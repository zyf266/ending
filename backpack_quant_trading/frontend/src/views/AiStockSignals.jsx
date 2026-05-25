import React, { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { getStrategySignals } from '../api/aiStockHub'
import './AiStock.css'

const AiStockSignals = () => {
  const { code } = useParams()
  const navigate = useNavigate()
  const sym = String(code || 'NVDA').toUpperCase()
  const [signals, setSignals] = useState([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const r = await getStrategySignals(sym, { limit: 100 })
      setSignals(r.items || [])
    } catch (_) {
      setSignals([])
    } finally {
      setLoading(false)
    }
  }, [sym])

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
          <div className="ais-detail-name">历史信号</div>
          <div className="ais-detail-code">{sym}</div>
        </div>
      </div>
      <p className="ais-sub" style={{ margin: '0 0 12px' }}>
        数据来自 <code>manual_signal_paste.txt</code> 与 <code>manual_signal_history.json</code>。
      </p>
      {loading && <div className="ais-muted">加载中…</div>}
      {!loading && signals.length === 0 && (
        <div className="ais-empty">
          <div className="ais-empty-title">暂无信号</div>
          <div className="ais-empty-sub">请向 manual_signal_paste.txt 粘贴钉钉策略信号全文</div>
        </div>
      )}
      <div className="ais-signal-list">
        {signals.map((s, idx) => (
          <div key={s.id || idx} className="ais-signal-card">
            <div className="ais-signal-row">
              <div className="ais-signal-k">摘要</div>
              <div className="ais-signal-v">{s.summary || '-'}</div>
            </div>
            {s.raw ? <pre className="ais-raw-block">{s.raw}</pre> : null}
          </div>
        ))}
      </div>
    </div>
  )
}

export default AiStockSignals
