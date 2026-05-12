import React, { useMemo } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { getAiStockReportByCode } from '../data/aiStockReports'
import './AiStock.css'

const mockSignalsFor = (code) => {
  const now = new Date()
  const pad = (n) => String(n).padStart(2, '0')
  const fmt = (d) =>
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`

  const base = String(code || '').toUpperCase()
  const priceBase = base === 'NVDA' ? 1200 : base === '600519' ? 1888 : 100
  return [
    {
      symbol: base,
      side: 'buy',
      price: priceBase + 3.93,
      strategy: 'AI 趋势跟随',
      timeframe: '1D',
      triggered_at: fmt(new Date(now.getTime() - 1000 * 60 * 8)),
    },
    {
      symbol: base,
      side: 'sell',
      price: priceBase + 8.11,
      strategy: 'AI 趋势跟随',
      timeframe: '1D',
      triggered_at: fmt(new Date(now.getTime() - 1000 * 60 * 6)),
    },
    {
      symbol: base,
      side: 'buy',
      price: priceBase - 12.27,
      strategy: '均线回踩',
      timeframe: '4H',
      triggered_at: fmt(new Date(now.getTime() - 1000 * 60 * 3)),
    },
    {
      symbol: base,
      side: 'sell',
      price: priceBase - 6.42,
      strategy: '均线回踩',
      timeframe: '4H',
      triggered_at: fmt(new Date(now.getTime() - 1000 * 60 * 1)),
    },
  ]
}

const AiStockSignals = () => {
  const { code } = useParams()
  const navigate = useNavigate()
  const item = useMemo(() => getAiStockReportByCode(code), [code])
  const signals = useMemo(() => mockSignalsFor(item?.code || code), [item?.code, code])

  return (
    <div className="page ais-page">
      <div className="ais-detail-header">
        <button type="button" className="ais-back" onClick={() => navigate(`/ai-stock/${encodeURIComponent(code || '')}`)}>
          ← 返回详情
        </button>
        <div className="ais-detail-title">
          <div className="ais-detail-name">历史信号</div>
          <div className="ais-detail-code">{item?.code || String(code || '').toUpperCase()}</div>
        </div>
        <div className="ais-detail-actions" />
      </div>

      <div className="ais-signal-list">
        {signals.map((s, idx) => {
          const isBuy = String(s.side).toLowerCase() === 'buy'
          return (
            <div key={idx} className="ais-signal-card">
              <div className="ais-signal-row">
                <div className="ais-signal-k">交易品种:</div>
                <div className="ais-signal-v ais-mono">{s.symbol}</div>
              </div>
              <div className="ais-signal-row">
                <div className="ais-signal-k">信号类型:</div>
                <div className="ais-signal-v">
                  {isBuy ? '买入' : '卖出'} <span className={`ais-dot ${isBuy ? 'buy' : 'sell'}`} />
                </div>
              </div>
              <div className="ais-signal-row">
                <div className="ais-signal-k">成交价格:</div>
                <div className="ais-signal-v">{Number.isFinite(Number(s.price)) ? Number(s.price).toFixed(2) : '-'}</div>
              </div>
              <div className="ais-signal-row">
                <div className="ais-signal-k">策略名称:</div>
                <div className="ais-signal-v">{s.strategy || '-'}</div>
              </div>
              <div className="ais-signal-row">
                <div className="ais-signal-k">周期:</div>
                <div className="ais-signal-v">{s.timeframe || '-'}</div>
              </div>
              <div className="ais-signal-row">
                <div className="ais-signal-k">触发时间:</div>
                <div className="ais-signal-v">{s.triggered_at || '-'}</div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default AiStockSignals

