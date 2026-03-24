import React, { useEffect, useState } from 'react'
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
      alert('已启动1分钟预警')
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

  const toggleSymbol = (s) => {
    setSelectedSymbols((prev) =>
      prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s]
    )
  }

  const toggleTimeframe = (v) => {
    setSelectedTimeframes((prev) =>
      prev.includes(v) ? prev.filter((x) => x !== v) : [...prev, v]
    )
  }

  const toggleMinuteSymbol = (s) => {
    setMinuteForm((prev) => ({
      ...prev,
      symbols: prev.symbols.includes(s)
        ? prev.symbols.filter((x) => x !== s)
        : [...prev.symbols, s],
    }))
  }

  return (
    <div className="page monitor-page">
      <div className="title-row">
        <h2>币种监视</h2>
      </div>

      <div className="card-block config-card">
        <div className="card-block-header">监视配置</div>
        <div className="config-form">
          <div className="form-group">
            <label>选择币种</label>
            <select
              multiple
              value={selectedSymbols}
              onChange={(e) => {
                const opts = e.target.selectedOptions
                setSelectedSymbols(Array.from(opts).map((o) => o.value))
              }}
              className="symbol-select"
            >
              {symbolList.slice(0, 200).map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
            <small>可多选</small>
          </div>
          <div className="form-group">
            <label>K线级别(多选)</label>
            <div className="timeframe-group">
              {TIMEFRAME_OPTIONS.map((opt) => (
                <label key={opt.value} className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={selectedTimeframes.includes(opt.value)}
                    onChange={() => toggleTimeframe(opt.value)}
                  />
                  {opt.label}
                </label>
              ))}
            </div>
          </div>
          <div className="btn-row">
            <button type="button" className="btn-primary" disabled={loading} onClick={handleStart}>
              {loading ? '启动中...' : '开始监视'}
            </button>
            <button type="button" className="btn-danger" disabled={!status.running} onClick={handleStop}>
              停止监视
            </button>
          </div>
        </div>
      </div>

      <div className="card-block minute-alert-card">
        <div className="card-block-header">分钟预警配置</div>
        <div className="minute-form-grid">
          <div className="minute-symbols">
            <label>监控币种</label>
            <select
              multiple
              value={minuteForm.symbols}
              onChange={(e) => {
                const opts = e.target.selectedOptions
                setMinuteForm((prev) => ({
                  ...prev,
                  symbols: Array.from(opts).map((o) => o.value),
                }))
              }}
              className="symbol-select symbol-select-full"
            >
              {symbolList.slice(0, 200).map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>
          <div className="minute-interval">
            <label>K线级别</label>
            <select
              value={minuteForm.interval}
              onChange={(e) => setMinuteForm((prev) => ({ ...prev, interval: e.target.value }))}
              className="w-120"
            >
              {MINUTE_INTERVALS.map((opt) => (
                <option key={opt} value={opt}>{opt}</option>
              ))}
            </select>
          </div>
          <div className="minute-vol">
            <label>波动阈值(%)</label>
            <input
              type="number"
              min={0}
              step={0.5}
              value={minuteForm.vol_pct_threshold}
              onChange={(e) =>
                setMinuteForm((prev) => ({ ...prev, vol_pct_threshold: Number(e.target.value) }))
              }
              className="w-160"
            />
          </div>
          <div className="minute-volume">
            <label>量能倍数(x)</label>
            <input
              type="number"
              min={1}
              step={1}
              value={minuteForm.volume_mult_threshold}
              onChange={(e) =>
                setMinuteForm((prev) => ({ ...prev, volume_mult_threshold: Number(e.target.value) }))
              }
              className="w-160"
            />
          </div>
          <div className="minute-ob">
            <label>订单簿大单(名义USDT)</label>
            <input
              type="number"
              min={0}
              step={10000}
              value={minuteForm.ob_notional_threshold}
              onChange={(e) =>
                setMinuteForm((prev) => ({ ...prev, ob_notional_threshold: Number(e.target.value) }))
              }
              className="w-220"
            />
            <div className="field-help">
              {minuteStatus.running
                ? `运行中：${(minuteStatus.symbols || []).join(', ')} ｜ interval=${minuteStatus.interval} ｜ 波动≥${minuteStatus.vol_pct_threshold}% ｜ 量能≥${minuteStatus.volume_mult_threshold}x ｜ 订单簿≥${minuteStatus.ob_notional_threshold}`
                : '未启动。启动后每分钟拉取币安K线/订单簿并通过钉钉推送。'}
            </div>
          </div>
          <div className="minute-actions">
            <button
              type="button"
              className="btn-primary"
              disabled={minuteLoading}
              onClick={handleMinuteStart}
            >
              {minuteLoading ? '启动中...' : '启动预警'}
            </button>
            <button
              type="button"
              className="btn-danger"
              disabled={!minuteStatus.running}
              onClick={handleMinuteStop}
            >
              停止预警
            </button>
          </div>
        </div>
      </div>

      <div className="card-block pool-card">
        <div className="card-block-header">监视/预警中的币种 (异动时变红)</div>
        {displayPairs.length > 0 && (
          <p className="hint">
            已有监视/预警时，选择更多币种/级别后点击「开始监视」可追加；点击 × 可移除该项（预警项点击 × 会停止预警）
          </p>
        )}
        {displayPairs.length === 0 ? (
          <div className="empty">暂无监视/预警，请先启动「币种监视」或「分钟预警」</div>
        ) : (
          <div className={`pool ${hasAnyAlerted ? 'pool-alerted' : ''}`}>
            {displayPairs.map((p) => (
              <div
                key={`${p[0]}-${p[1]}`}
                className={`pool-chip ${isAlerted(p) ? 'alerted' : ''}`}
              >
                <span className="chip-symbol">{p[0]}</span>
                <span className="chip-timeframe">{p[1]}</span>
                <button
                  type="button"
                  className="chip-close"
                  aria-label="移除"
                  onClick={() => removePair(p[0], p[1])}
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export default CurrencyMonitor
