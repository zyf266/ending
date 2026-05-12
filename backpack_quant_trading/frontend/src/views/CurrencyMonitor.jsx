import React, { useEffect, useState, useRef } from 'react'
import {
  getSymbols,
  getStatus,
  startMonitor,
  stopMonitor,
  removePair as apiRemovePair,
  getMinuteAlertStatus,
  startMinuteAlert,
  stopMinuteAlert,
} from '../api/currencyMonitor'
import './CurrencyMonitor.css'

/* ===== 下拉多选组件 ===== */
const MultiSelectDropdown = ({ options, value, onChange, placeholder }) => {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const ref = useRef(null)

  useEffect(() => {
    const handler = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const filtered = options.filter((o) =>
    o.toLowerCase().includes(search.toLowerCase())
  )

  const toggle = (item) => {
    onChange(
      value.includes(item) ? value.filter((v) => v !== item) : [...value, item]
    )
  }

  const removeTag = (item, e) => {
    e.stopPropagation()
    onChange(value.filter((v) => v !== item))
  }

  return (
    <div className="msd" ref={ref}>
      <div className="msd-trigger" onClick={() => setOpen(!open)}>
        {value.length === 0 ? (
          <span className="msd-placeholder">{placeholder || '请选择...'}</span>
        ) : (
          <div className="msd-tags">
            {value.slice(0, 5).map((v) => (
              <span key={v} className="msd-tag">
                {v}
                <button type="button" className="msd-tag-x" onClick={(e) => removeTag(v, e)}>×</button>
              </span>
            ))}
            {value.length > 5 && <span className="msd-tag msd-tag-more">+{value.length - 5}</span>}
          </div>
        )}
        <span className="msd-arrow">{open ? '▲' : '▼'}</span>
      </div>
      {open && (
        <div className="msd-dropdown">
          <input
            className="msd-search"
            placeholder="搜索..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            autoFocus
          />
          <div className="msd-list">
            {filtered.map((item) => (
              <label key={item} className="msd-option">
                <input
                  type="checkbox"
                  checked={value.includes(item)}
                  onChange={() => toggle(item)}
                />
                <span>{item}</span>
              </label>
            ))}
            {filtered.length === 0 && <div className="msd-empty">无匹配项</div>}
          </div>
        </div>
      )}
    </div>
  )
}

const TIMEFRAME_OPTIONS = [
  { label: '1小时', value: '1小时' },
  { label: '2小时', value: '2小时' },
  { label: '4小时', value: '4小时' },
  { label: '天', value: '天' },
  { label: '周', value: '周' },
]

const MINUTE_INTERVALS = ['1m', '3m', '5m', '15m']

const CurrencyMonitor = () => {
  const [symbolList, setSymbolList] = useState([])
  const [selectedSymbols, setSelectedSymbols] = useState([])
  const [selectedTimeframes, setSelectedTimeframes] = useState([])
  const [status, setStatus] = useState({ running: false, pairs: [] })
  const [loading, setLoading] = useState(false)
  const [alertedPairs, setAlertedPairs] = useState(new Set())

  const [minuteLoading, setMinuteLoading] = useState(false)
  const [minuteStatus, setMinuteStatus] = useState({
    running: false,
    symbols: [],
    interval: '1m',
    vol_pct_threshold: 5.0,
    volume_mult_threshold: 20.0,
    ob_notional_threshold: 200000,
  })
  const [minuteForm, setMinuteForm] = useState({
    symbols: [],
    interval: '1m',
    vol_pct_threshold: 5.0,
    volume_mult_threshold: 20.0,
    ob_notional_threshold: 200000,
  })

  const minutePairsForPool = minuteStatus.running
    ? (minuteStatus.symbols || []).map((s) => [String(s).toUpperCase(), `预警(${minuteStatus.interval || '1m'})`])
    : []
  const displayPairs = [...(status.pairs || []), ...minutePairsForPool]
  const hasAnyAlerted = displayPairs.some((p) => alertedPairs.has(`${p[0]}|${p[1]}`))

  const isAlerted = (p) => alertedPairs.has(`${p[0]}|${p[1]}`)

  const refreshStatus = async () => {
    try {
      const res = await getStatus()
      setStatus({ running: res.running, pairs: res.pairs || [] })
      setAlertedPairs(new Set(res.alerted || []))
    } catch (_) {}
  }

  const refreshMinuteStatus = async () => {
    try {
      const res = await getMinuteAlertStatus()
      setMinuteStatus({
        running: !!res.running,
        symbols: res.symbols || [],
        interval: res.interval || '1m',
        vol_pct_threshold: Number(res.vol_pct_threshold ?? 5),
        volume_mult_threshold: Number(res.volume_mult_threshold ?? 20),
        ob_notional_threshold: Number(res.ob_notional_threshold ?? 200000),
      })
      if (!res.running) {
        setMinuteForm((prev) => ({
          ...prev,
          interval: res.interval || '1m',
          vol_pct_threshold: Number(res.vol_pct_threshold ?? 5),
          volume_mult_threshold: Number(res.volume_mult_threshold ?? 20),
          ob_notional_threshold: Number(res.ob_notional_threshold ?? 200000),
        }))
      }
    } catch (_) {}
  }

  useEffect(() => {
    let t1, t2
    const load = async () => {
      try {
        const res = await getSymbols()
        setSymbolList(res.symbols || [])
      } catch (_) {}
      await refreshStatus()
      await refreshMinuteStatus()
      t1 = setInterval(refreshStatus, 5000)
      t2 = setInterval(refreshMinuteStatus, 5000)
    }
    load()
    return () => {
      if (t1) clearInterval(t1)
      if (t2) clearInterval(t2)
    }
  }, [])

  const handleStart = async () => {
    if (!selectedSymbols.length || !selectedTimeframes.length) {
      alert('请选择币种和 K 线级别')
      return
    }
    setLoading(true)
    try {
      await startMonitor({ symbols: selectedSymbols, timeframes: selectedTimeframes })
      alert('已开始监视')
      setSelectedSymbols([])
      setSelectedTimeframes([])
      await refreshStatus()
    } catch (e) {
      alert(e?.response?.data?.detail || '启动失败')
    } finally {
      setLoading(false)
    }
  }

  const handleStop = async () => {
    try {
      await stopMonitor()
      alert('已停止全部监视')
      await refreshStatus()
    } catch (e) {
      alert(e?.response?.data?.detail || '停止失败')
    }
  }

  const removePair = async (symbol, timeframe) => {
    if (String(timeframe || '').startsWith('预警(')) {
      await handleMinuteStop()
      return
    }
    try {
      await apiRemovePair({ symbol, timeframe })
      await refreshStatus()
    } catch (e) {
      alert(e?.response?.data?.detail || '移除失败')
    }
  }

  const handleMinuteStart = async () => {
    if (!minuteForm.symbols.length) {
      alert('请选择预警监控币种')
      return
    }
    setMinuteLoading(true)
    try {
      await startMinuteAlert({
        symbols: minuteForm.symbols,
        interval: minuteForm.interval,
        vol_pct_threshold: minuteForm.vol_pct_threshold,
        volume_mult_threshold: minuteForm.volume_mult_threshold,
        ob_notional_threshold: minuteForm.ob_notional_threshold,
      })
      alert('已启动分钟预警')
      setMinuteForm((prev) => ({ ...prev, symbols: [] }))
      await refreshMinuteStatus()
    } catch (e) {
      alert(e?.response?.data?.detail || '启动失败')
    } finally {
      setMinuteLoading(false)
    }
  }

  const handleMinuteStop = async () => {
    try {
      await stopMinuteAlert()
      alert('已停止预警')
      await refreshMinuteStatus()
    } catch (e) {
      alert(e?.response?.data?.detail || '停止失败')
    }
  }

  const toggleTimeframe = (v) => {
    setSelectedTimeframes((prev) =>
      prev.includes(v) ? prev.filter((x) => x !== v) : [...prev, v]
    )
  }

  return (
    <div className="page mon-page">
      {/* Card 1: 监视配置 */}
      <div className="mon-card">
        <div className="mon-card-header">
          <div className="mon-card-title">
            <span className="mon-icon">👁</span>
            <span>监视配置</span>
          </div>
        </div>
        <div className="mon-card-body">
          <div className="mon-grid-2">
            <div className="mon-field-group">
              <label className="mon-label">选择币种</label>
              <MultiSelectDropdown
                options={symbolList}
                value={selectedSymbols}
                onChange={setSelectedSymbols}
                placeholder="搜索并选择币种..."
              />
              {selectedSymbols.length > 0 && (
                <p className="mon-hint-blue">已选择 {selectedSymbols.length} 个币种</p>
              )}
            </div>
            <div className="mon-field-group">
              <label className="mon-label">K线级别（可多选）</label>
              <div className="mon-checkbox-list">
                {TIMEFRAME_OPTIONS.map((opt) => (
                  <label key={opt.value} className="mon-checkbox-item">
                    <input
                      type="checkbox"
                      checked={selectedTimeframes.includes(opt.value)}
                      onChange={() => toggleTimeframe(opt.value)}
                    />
                    <span>{opt.label}</span>
                  </label>
                ))}
              </div>
              {selectedTimeframes.length > 0 && (
                <p className="mon-hint-blue">已选择 {selectedTimeframes.length} 个级别</p>
              )}
            </div>
          </div>
          <div className="mon-btn-row">
            <button className="mon-btn-primary" disabled={loading} onClick={handleStart}>
              ▶ {loading ? '启动中...' : '开始监视'}
            </button>
            <button className="mon-btn-outline-red" disabled={!status.running} onClick={handleStop}>
              ◻ 停止监视
            </button>
          </div>
        </div>
      </div>

      {/* Card 2: 分钟预警配置 */}
      <div className="mon-card mon-card-orange">
        <div className="mon-card-header mon-card-header-orange">
          <div className="mon-card-title">
            <span className="mon-icon">🔔</span>
            <span>分钟预警配置</span>
            {minuteStatus.running && (
              <span className="mon-badge-orange">⚡ 运行中</span>
            )}
          </div>
        </div>
        <div className="mon-card-body">
          <div className="mon-grid-2">
            <div className="mon-field-group">
              <label className="mon-label">监控币种</label>
              <MultiSelectDropdown
                options={symbolList}
                value={minuteForm.symbols}
                onChange={(vals) => setMinuteForm((prev) => ({ ...prev, symbols: vals }))}
                placeholder="搜索并选择币种..."
              />
              {minuteForm.symbols.length > 0 && (
                <p className="mon-hint-orange">已选择 {minuteForm.symbols.length} 个币种</p>
              )}
            </div>
            <div className="mon-params-stack">
              <div className="mon-field-group">
                <label className="mon-label-sm">K线级别</label>
                <select
                  value={minuteForm.interval}
                  onChange={(e) => setMinuteForm((prev) => ({ ...prev, interval: e.target.value }))}
                  className="mon-input"
                >
                  {MINUTE_INTERVALS.map((opt) => (
                    <option key={opt} value={opt}>{opt}</option>
                  ))}
                </select>
              </div>
              <div className="mon-field-group">
                <label className="mon-label-sm">波动阈值 (%)</label>
                <input
                  type="number"
                  min={0}
                  step={0.5}
                  value={minuteForm.vol_pct_threshold}
                  onChange={(e) =>
                    setMinuteForm((prev) => ({ ...prev, vol_pct_threshold: Number(e.target.value) }))
                  }
                  className="mon-input"
                />
              </div>
              <div className="mon-field-group">
                <label className="mon-label-sm">量能倍数 (x)</label>
                <input
                  type="number"
                  min={1}
                  step={1}
                  value={minuteForm.volume_mult_threshold}
                  onChange={(e) =>
                    setMinuteForm((prev) => ({ ...prev, volume_mult_threshold: Number(e.target.value) }))
                  }
                  className="mon-input"
                />
              </div>
              <div className="mon-field-group">
                <label className="mon-label-sm">订单簿大单 (USDT)</label>
                <input
                  type="number"
                  min={0}
                  step={10000}
                  value={minuteForm.ob_notional_threshold}
                  onChange={(e) =>
                    setMinuteForm((prev) => ({ ...prev, ob_notional_threshold: Number(e.target.value) }))
                  }
                  className="mon-input"
                />
              </div>
            </div>
          </div>

          {minuteStatus.running && (
            <div className="mon-status-box">
              <span>⚠</span>
              <div>
                <p className="mon-status-title">当前运行参数</p>
                <p className="mon-status-detail">
                  币种: {minuteStatus.symbols.join(', ')} | 级别: {minuteStatus.interval} | 波动≥{minuteStatus.vol_pct_threshold}% | 量能≥{minuteStatus.volume_mult_threshold}x | 订单簿≥{minuteStatus.ob_notional_threshold}
                </p>
              </div>
            </div>
          )}

          <div className="mon-btn-row">
            <button className="mon-btn-orange" disabled={minuteLoading} onClick={handleMinuteStart}>
              🔔 {minuteLoading ? '启动中...' : '启动预警'}
            </button>
            <button className="mon-btn-outline-red" disabled={!minuteStatus.running} onClick={handleMinuteStop}>
              ◻ 停止预警
            </button>
          </div>
        </div>
      </div>

      {/* Card 3: 监视/预警中的币种 */}
      <div className="mon-card">
        <div className="mon-card-header">
          <div className="mon-card-title">
            <span className="mon-icon">📊</span>
            <span>监视/预警中的币种</span>
            <span className="mon-badge-blue">{displayPairs.length}</span>
            {hasAnyAlerted && (
              <span className="mon-badge-red">⚠ 异动提醒</span>
            )}
          </div>
        </div>
        <div className="mon-card-body">
          {displayPairs.length > 0 && (
            <p className="mon-hint">
              已有监视/预警时，选择更多币种/级别后点击「开始监视」可追加；点击 × 可移除该项
            </p>
          )}
          {displayPairs.length === 0 ? (
            <div className="mon-empty">
              <div className="mon-empty-icon">👁</div>
              <h3>暂无监视/预警</h3>
              <p>请先启动「币种监视」或「分钟预警」</p>
            </div>
          ) : (
            <div className="mon-chips">
              {displayPairs.map((p) => (
                <div
                  key={`${p[0]}-${p[1]}`}
                  className={`mon-chip ${isAlerted(p) ? 'mon-chip-alert' : ''}`}
                >
                  <span className="mon-chip-symbol">{p[0]}</span>
                  <span className="mon-chip-tf">{p[1]}</span>
                  <button className="mon-chip-x" onClick={() => removePair(p[0], p[1])}>×</button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default CurrencyMonitor
