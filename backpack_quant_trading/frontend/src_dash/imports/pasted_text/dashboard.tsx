import React, { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import * as echarts from 'echarts'
import { getDashboard } from '../api/dashboard'
import { getInstances } from '../api/trading'
import './Dashboard.css'

function formatTime(s) {
  if (!s) return '--'
  const d = new Date(s)
  return d.toTimeString().slice(0, 8)
}

const Dashboard = () => {
  const chartRef = useRef(null)
  const [summary, setSummary] = useState({})
  const [chartData, setChartData] = useState([])
  const [positions, setPositions] = useState([])
  const [orders, setOrders] = useState([])
  const [trades, setTrades] = useState([])
  const [risks, setRisks] = useState([])
  const [exchange, setExchange] = useState('backpack')
  const [now, setNow] = useState('')

  const pnlClass = (summary.daily_pnl || 0) > 0 ? 'profit' : (summary.daily_pnl || 0) < 0 ? 'loss' : ''
  const pnlPrefix = (summary.daily_pnl || 0) > 0 ? '+' : (summary.daily_pnl || 0) < 0 ? '-' : ''
  const returnClass = (summary.daily_return || 0) > 0 ? 'profit' : (summary.daily_return || 0) < 0 ? 'loss' : ''
  const returnPrefix = (summary.daily_return || 0) > 0 ? '+' : (summary.daily_return || 0) < 0 ? '-' : ''

  const refresh = async () => {
    try {
      const res = await getDashboard(exchange)
      setSummary(res.summary || {})
      setChartData(res.chart || [])
      setPositions(res.positions || [])
      setOrders(res.orders || [])
      setTrades(res.trades || [])
      setRisks(res.risks || [])
    } catch (_) {}
  }

  const renderChart = () => {
    if (!chartRef.current || !chartData.length) return
    const ch = echarts.init(chartRef.current)
    ch.setOption({
      xAxis: { type: 'category', data: chartData.map((d) => d.timestamp?.slice(0, 16)) },
      yAxis: { type: 'value' },
      series: [
        {
          type: 'line',
          data: chartData.map((d) => d.value),
          areaStyle: { color: 'rgba(245, 158, 11, 0.18)' },
          lineStyle: { color: '#f59e0b', width: 3 },
        },
      ],
      grid: { left: 50, right: 20, top: 20, bottom: 30 },
    })
  }

  useEffect(() => {
    renderChart()
  }, [chartData])

  useEffect(() => {
    let t1
    const init = async () => {
      try {
        const res = await getInstances()
        const insts = res.instances || []
        if (insts.length) setExchange(insts[0].platform || 'backpack')
      } catch (_) {}
      await refresh()
      t1 = setInterval(refresh, 10000)
    }
    init()
    const t2 = setInterval(() => setNow(new Date().toISOString().slice(0, 19).replace('T', ' ')), 1000)
    return () => {
      if (t1) clearInterval(t1)
      clearInterval(t2)
    }
  }, [])

  return (
    <div className="page dashboard-page">
      <div className="title-row">
        <div className="title-main">
          <div className="title-badge">量化监控 · 实盘联动</div>
          <h2>数据资产监控大屏</h2>
          <p className="title-sub">实时汇总账户资产、盈亏表现与风险事件，让你一眼看清今天过得怎么样。</p>
        </div>
        <div className="meta">
          <div className="meta-chip online">
            <span className="dot"></span>
            <span>运行正常</span>
          </div>
          <div className="meta-time">{now}</div>
        </div>
      </div>

      <div className="summary-grid">
        <div className="summary-card primary">
          <div className="sum-label">总资产价值</div>
          <div className="sum-value">
            <span className="prefix">USD</span>
            <span className="main">
              ${(summary.portfolio_value || 0).toLocaleString('en-US', { minimumFractionDigits: 2 })}
            </span>
          </div>
          <div className="sum-footer">
            <span>含持仓市值与可用现金</span>
          </div>
        </div>
        <div className="summary-card">
          <div className="sum-label">可用现金</div>
          <div className="sum-value">
            <span className="prefix">CASH</span>
            <span className="main">
              ${(summary.cash_balance || 0).toLocaleString('en-US', { minimumFractionDigits: 2 })}
            </span>
          </div>
        </div>
        <div className={`summary-card ${pnlClass}`}>
          <div className="sum-label">当日盈亏</div>
          <div className="sum-value">
            <span className="prefix">P&L</span>
            <span className="main">
              {pnlPrefix}${Math.abs(summary.daily_pnl || 0).toLocaleString('en-US', { minimumFractionDigits: 2 })}
            </span>
          </div>
        </div>
        <div className={`summary-card ${returnClass}`}>
          <div className="sum-label">当日收益率</div>
          <div className="sum-value">
            <span className="prefix">RETURN</span>
            <span className="main">
              {returnPrefix}{(Math.abs(summary.daily_return || 0) * 100).toFixed(2)}%
            </span>
          </div>
        </div>
      </div>

      <div className="chart-card card-block">
        <div className="chart-header">
          <div className="chart-title">
            <span className="chart-icon">📈</span>
            <span>组合累计净值曲线</span>
          </div>
          <div className="chart-tags">
            <span className="tag tag-info">净值基准 1.0</span>
            <span className="tag tag-success">自动刷新</span>
          </div>
        </div>
        <div ref={chartRef} className="chart-area" />
      </div>

      <div className="tables-row">
        <div className="table-card card-block">
          <div className="card-header">
            <span className="card-title">当前活动仓位</span>
            <span className="card-sub">实时跟踪每一笔持仓盈亏</span>
          </div>
          {positions.length ? (
            <table className="data-table">
              <thead>
                <tr>
                  <th>交易对</th>
                  <th>方向</th>
                  <th>数量</th>
                  <th>入场价</th>
                  <th>当前价</th>
                  <th>未实现盈亏</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((row, i) => (
                  <tr key={i}>
                    <td>{row.symbol}</td>
                    <td>
                      <span className={row.side === 'long' ? 'long' : 'short'}>
                        {(row.side || '').toUpperCase()}
                      </span>
                    </td>
                    <td>{row.quantity}</td>
                    <td>${Number(row.entry_price || 0).toLocaleString()}</td>
                    <td>${Number(row.current_price || 0).toLocaleString()}</td>
                    <td>
                      <span className={(row.unrealized_pnl || 0) >= 0 ? 'profit' : 'loss'}>
                        ${Number(row.unrealized_pnl || 0).toLocaleString()}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="empty">无活跃持仓</div>
          )}
        </div>

        <div className="table-card card-block">
          <div className="card-header">
            <span className="card-title">活动订单</span>
            <span className="card-sub">挂单与进行中委托</span>
          </div>
          {orders.length ? (
            <table className="data-table">
              <thead>
                <tr>
                  <th>交易对</th>
                  <th>类型</th>
                  <th>方向</th>
                  <th>价格</th>
                  <th>数量</th>
                  <th>状态</th>
                </tr>
              </thead>
              <tbody>
                {orders.map((row, i) => (
                  <tr key={i}>
                    <td>{row.symbol}</td>
                    <td>{row.order_type}</td>
                    <td>
                      <span className={row.side === 'buy' ? 'long' : 'short'}>
                        {(row.side || '').toUpperCase()}
                      </span>
                    </td>
                    <td>
                      {row.price != null && row.price !== ''
                        ? '$' + Number(row.price).toLocaleString()
                        : row.order_type === 'market'
                          ? '市价'
                          : '-'}
                    </td>
                    <td>{row.quantity}</td>
                    <td>{row.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="empty">无活跃订单</div>
          )}
        </div>
      </div>

      <div className="tables-row">
        <div className="table-card card-block">
          <div className="card-header">
            <span className="card-title">成交历史</span>
            <span className="card-sub">最近成交与盈亏分布</span>
          </div>
          {trades.length ? (
            <table className="data-table">
              <thead>
                <tr>
                  <th>时间</th>
                  <th>交易对</th>
                  <th>方向</th>
                  <th>价格</th>
                  <th>成交额</th>
                  <th>盈亏</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((row, i) => (
                  <tr key={i}>
                    <td>{formatTime(row.created_at)}</td>
                    <td>{row.symbol}</td>
                    <td>
                      <span className={['long', 'buy'].includes(row.side) ? 'long' : 'short'}>
                        {(row.side || '').toUpperCase()}
                      </span>
                    </td>
                    <td>
                      {row.price != null && row.price !== ''
                        ? '$' + Number(row.price).toLocaleString()
                        : '-'}
                    </td>
                    <td>{row.quantity}</td>
                    <td>
                      {row.pnl_amount != null ? (
                        <span className={row.pnl_amount >= 0 ? 'profit' : 'loss'}>
                          ${Number(row.pnl_amount).toLocaleString()}
                        </span>
                      ) : (
                        '-'
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="empty">暂无成交历史</div>
          )}
        </div>

        <div className="table-card card-block">
          <div className="card-header">
            <span className="card-title">风险事件</span>
            <span className="card-sub">预警记录与系统提示</span>
          </div>
          {risks.length ? (
            <div className="risk-list">
              {risks.map((r) => (
                <div key={r.id} className="risk-item">
                  <div className="risk-head">
                    <span className={r.severity === 'high' ? 'danger' : 'warn'}>{r.event_type}</span>
                    <span className="time">{formatTime(r.created_at)}</span>
                  </div>
                  <p>{r.description}</p>
                </div>
              ))}
            </div>
          ) : (
            <div className="empty success">系统运行正常</div>
          )}
        </div>
      </div>

      <div className="capabilities-card card-block">
        <div className="cap-header">🚀 平台能力 · 快速入口</div>
        <div className="cap-grid">
          <Link to="/trading" className="cap-item">⚡ 实盘交易</Link>
          <Link to="/ai-lab" className="cap-item">🤖 AI 实验室</Link>
          <Link to="/strategies" className="cap-item">📐 量化策略矩阵</Link>
          <Link to="/grid-trading" className="cap-item">🎯 合约网格</Link>
          <Link to="/currency-monitor" className="cap-item">🔔 币种监视</Link>
          <Link to="/stock-ai" className="cap-item">📈 A股 AI 选股</Link>
          <Link to="/okx-console" className="cap-item">⌨️ OKX 操作台</Link>
        </div>
      </div>
    </div>
  )
}

export default Dashboard
