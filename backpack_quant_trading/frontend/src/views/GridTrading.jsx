import React, { useEffect, useState } from 'react'
import { getGridStatus, startGrid as apiStartGrid, stopGrid, stopAllGrids } from '../api/grid'
import './GridTrading.css'

const EXCHANGES = [
  { label: 'Backpack', value: 'backpack' },
  { label: 'Deepcoin', value: 'deepcoin' },
  { label: 'Hyperliquid', value: 'hyper' },
  { label: 'Hyperliquid3', value: 'hip3_testnet' },
  { label: 'Ostium', value: 'ostium' },
]

const MODES = [
  { label: '做空网格', value: 'short_only' },
  { label: '做多网格', value: 'long_only' },
  { label: '双向网格', value: 'long_short' },
]

const modeLabel = (m) => {
  const map = { long_short: '双向', long_only: '做多', short_only: '做空' }
  return map[m] || m
}

const GridTrading = () => {
  const [grids, setGrids] = useState([])
  const [starting, setStarting] = useState(false)
  const [stopping, setStopping] = useState(false)
  const [form, setForm] = useState({
    exchange: 'backpack',
    symbol: 'ETH',
    price_lower: 2000,
    price_upper: 2500,
    grid_count: 5,
    investment_per_grid: 10,
    leverage: 10,
    grid_mode: 'short_only',
    api_key: '',
    secret_key: '',
  })

  const previewValid =
    form.price_lower != null &&
    form.price_upper != null &&
    form.price_lower < form.price_upper &&
    form.grid_count >= 2 &&
    form.investment_per_grid > 0 &&
    form.leverage >= 1

  const gridPreview = previewValid
    ? (() => {
        const { price_lower, price_upper, grid_count, investment_per_grid, leverage } = form
        const priceRange = price_upper - price_lower
        const gridSpacing = priceRange / grid_count
        const gridSpacingPercent = (gridSpacing / price_lower) * 100
        const totalInvestment = investment_per_grid * grid_count
        const positionValue = totalInvestment * leverage
        const profitPerGrid = (investment_per_grid * leverage * gridSpacingPercent) / 100
        const profitRatePercent = gridSpacingPercent * leverage - 0.1 * leverage
        const avgPrice = (price_lower + price_upper) / 2
        const liqPrice = leverage > 1 ? avgPrice * (1 - 1 / leverage + 0.005) : 0
        return {
          gridSpacing,
          gridSpacingPercent,
          totalInvestment,
          positionValue,
          profitPerGrid,
          profitRatePercent,
          liqPrice,
        }
      })()
    : null

  const refreshStatus = async () => {
    try {
      const res = await getGridStatus()
      setGrids(res.grids || [])
    } catch (_) {}
  }

  useEffect(() => {
    refreshStatus()
    const t = setInterval(refreshStatus, 3000)
    return () => clearInterval(t)
  }, [])

  const setField = (name, value) => setForm((prev) => ({ ...prev, [name]: value }))

  const startGrid = async () => {
    if (!form.symbol || !form.api_key || !form.secret_key) {
      alert('请填写交易对、API Key 和 Secret Key')
      return
    }
    setStarting(true)
    try {
      const res = await apiStartGrid({
        ...form,
        api_key: form.api_key,
        secret_key: form.secret_key,
      })
      if (res.ok) {
        alert('网格已启动')
        await refreshStatus()
      } else {
        alert(res.message || '启动失败')
      }
    } catch (e) {
      alert(e?.response?.data?.detail || '启动失败')
    } finally {
      setStarting(false)
    }
  }

  const stopOne = async (id) => {
    try {
      await stopGrid(id)
      alert('已停止')
      await refreshStatus()
    } catch (e) {
      alert(e?.response?.data?.detail || '停止失败')
    }
  }

  const stopAll = async () => {
    setStopping(true)
    try {
      await stopAllGrids()
      alert('已停止全部')
      await refreshStatus()
    } catch (e) {
      alert(e?.response?.data?.detail || '停止失败')
    } finally {
      setStopping(false)
    }
  }

  return (
    <div className="page grid-page">
      <div className="config-card card-block">
        <div className="card-block-header">交易参数</div>
        <div className="form-grid">
          <div className="form-item">
            <label>交易所</label>
            <select value={form.exchange} onChange={(e) => setField('exchange', e.target.value)}>
              {EXCHANGES.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </div>
          <div className="form-item">
            <label>交易对</label>
            <input
              value={form.symbol}
              onChange={(e) => setField('symbol', e.target.value)}
              placeholder="ETH / BTC / SOL..."
            />
          </div>
          <div className="form-item">
            <label>价格下限 (USDT)</label>
            <input
              type="number"
              min={0}
              step={0.01}
              value={form.price_lower}
              onChange={(e) => setField('price_lower', Number(e.target.value))}
            />
          </div>
          <div className="form-item">
            <label>价格上限 (USDT)</label>
            <input
              type="number"
              min={0}
              step={0.01}
              value={form.price_upper}
              onChange={(e) => setField('price_upper', Number(e.target.value))}
            />
          </div>
          <div className="form-item">
            <label>网格数量</label>
            <input
              type="number"
              min={2}
              max={100}
              value={form.grid_count}
              onChange={(e) => setField('grid_count', Number(e.target.value))}
            />
          </div>
          <div className="form-item">
            <label>单格投资 (USDT)</label>
            <input
              type="number"
              min={0}
              step={0.01}
              value={form.investment_per_grid}
              onChange={(e) => setField('investment_per_grid', Number(e.target.value))}
            />
          </div>
          <div className="form-item">
            <label>杠杆倍数</label>
            <input
              type="number"
              min={1}
              max={100}
              value={form.leverage}
              onChange={(e) => setField('leverage', Number(e.target.value))}
            />
          </div>
          <div className="form-item">
            <label>网格类型</label>
            <select value={form.grid_mode} onChange={(e) => setField('grid_mode', e.target.value)}>
              {MODES.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </div>
          <div className="form-item span-2">
            <label>API Key</label>
            <input
              type="password"
              value={form.api_key}
              onChange={(e) => setField('api_key', e.target.value)}
              placeholder="手动输入"
            />
          </div>
          <div className="form-item span-2">
            <label>Secret Key</label>
            <input
              type="password"
              value={form.secret_key}
              onChange={(e) => setField('secret_key', e.target.value)}
              placeholder="手动输入"
            />
          </div>
        </div>
        <div className="form-actions">
          <button type="button" className="btn-primary" disabled={starting} onClick={startGrid}>
            {starting ? '启动中...' : '启动当前类型网格'}
          </button>
        </div>

        {previewValid && gridPreview && (
          <div className="param-preview">
            <h4>参数预览</h4>
            <div className="preview-grid">
              <div className="preview-card">
                <div className="card-icon">📊</div>
                <div className="card-label">网格间距</div>
                <div className="card-value">
                  ${gridPreview.gridSpacing.toFixed(2)}{' '}
                  <span className="muted">({gridPreview.gridSpacingPercent.toFixed(2)}%)</span>
                </div>
              </div>
              <div className="preview-card">
                <div className="card-icon">💰</div>
                <div className="card-label">总投资</div>
                <div className="card-value">
                  ${gridPreview.totalInvestment.toFixed(2)} <span className="muted">(保证金)</span>
                </div>
              </div>
              <div className="preview-card">
                <div className="card-icon">📈</div>
                <div className="card-label">实际持仓价值</div>
                <div className="card-value">
                  ${gridPreview.positionValue.toFixed(2)}{' '}
                  <span className="muted">({form.leverage}x杠杆)</span>
                </div>
              </div>
              <div className="preview-card">
                <div className="card-icon">💵</div>
                <div className="card-label">单网格收益率</div>
                <div className="card-value profit">
                  {gridPreview.profitRatePercent.toFixed(2)}% ($
                  {gridPreview.profitPerGrid.toFixed(2)})
                </div>
              </div>
              <div className="preview-card">
                <div className="card-icon">🎯</div>
                <div className="card-label">建议网格数</div>
                <div className="card-value">
                  {form.grid_count} 格{' '}
                  <span className="muted">(间距 {gridPreview.gridSpacingPercent.toFixed(2)}%)</span>
                </div>
              </div>
              <div className="preview-card">
                <div className="card-icon">💥</div>
                <div className="card-label">预估强平价</div>
                <div className="card-value danger">${gridPreview.liqPrice.toFixed(2)}</div>
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="instances-card card-block">
        <div className="card-block-header">运行中的网格实例</div>
        {grids.length === 0 ? (
          <div className="grid-empty">
            <div className="grid-empty-icon">🔲</div>
            <h3>暂无运行中的网格</h3>
            <p>配置参数后点击「启动当前类型网格」开始交易</p>
          </div>
        ) : (
          <div className="grid-list">
            {grids.map((g) => (
              <div key={g.id} className="grid-card">
                <div className="grid-info">
                  <div className="tags">
                    <span className="tag tag-warning">{(g.exchange || '').toUpperCase()}</span>
                    <span className="status">● 运行中</span>
                  </div>
                  <h3>
                    {g.symbol} | {modeLabel(g.grid_mode)}
                  </h3>
                  <p>
                    价格 ${(g.current_price || 0).toFixed(2)} | 成交 {g.total_trades || 0} 次
                  </p>
                </div>
                <button type="button" className="btn-danger-sm" onClick={() => stopOne(g.id)}>
                  停止
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="card-block">
        <div className="card-block-header">网格日志</div>
        <div className="log-area">系统就绪，等待网格交易日志...</div>
      </div>
    </div>
  )
}

export default GridTrading
