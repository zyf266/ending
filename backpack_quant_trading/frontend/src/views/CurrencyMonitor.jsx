import React, { useEffect, useState, useRef } from 'react'
import {
  getSymbols,
  getSpotSymbols,
  getStatus,
  startMonitor,
  stopMonitor,
  removePair as apiRemovePair,
  getMinuteAlertStatus,
  startMinuteAlert,
  stopMinuteAlert,
  getSpotMinuteAlertStatus,
  startSpotMinuteAlert,
  stopSpotMinuteAlert,
  getChainActivityChains,
  getChainActivityStatus,
  startChainActivity,
  stopChainActivity,
  probeSpotMinuteAlert,
  testSpotMinuteDingtalk,
  probeChainActivity,
  checkChainActivityNow,
  testChainActivityDingtalk,
} from '../api/currencyMonitor'
import {
  getOptions as getMacdOptions,
  getStatus as getMacdStatus,
  startMonitor as startMacdMonitor,
  stopMonitor as stopMacdMonitor,
  removeTask as apiRemoveMacdTask,
} from '../api/macdPatternMonitor'
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

const DEFAULT_MACD_TF = [
  { label: '1小时 (60)', value: '60' },
  { label: '2小时 (120)', value: '120' },
  { label: '4小时 (240)', value: '240' },
  { label: '640分钟', value: '640' },
  { label: '日线 (D)', value: 'D' },
]

const DEFAULT_MACD_PATTERNS = [
  { label: '水上金叉转死叉', value: 'above_golden_to_death' },
  { label: '水下金叉转死叉', value: 'below_golden_to_death' },
  { label: '死叉转水下金叉', value: 'death_to_below_golden' },
  { label: '死叉转水上金叉', value: 'death_to_above_golden' },
]

const DEFAULT_CHAIN_OPTIONS = [
  { id: 'eth', name: 'Ethereum' },
  { id: 'arb', name: 'Arbitrum' },
  { id: 'bsc', name: 'BSC' },
]

const CurrencyMonitor = () => {
  const [symbolList, setSymbolList] = useState([])
  const [spotSymbolList, setSpotSymbolList] = useState([])
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

  const [spotMinuteLoading, setSpotMinuteLoading] = useState(false)
  const [spotMinuteStatus, setSpotMinuteStatus] = useState({
    running: false,
    symbols: [],
    interval: '1m',
    vol_pct_threshold: 5.0,
    volume_mult_threshold: 20.0,
    ob_notional_threshold: 200000,
  })
  const [spotMinuteForm, setSpotMinuteForm] = useState({
    symbols: [],
    interval: '1m',
    vol_pct_threshold: 5.0,
    volume_mult_threshold: 20.0,
    ob_notional_threshold: 200000,
  })

  const [chainLoading, setChainLoading] = useState(false)
  const [chainOptions, setChainOptions] = useState(DEFAULT_CHAIN_OPTIONS)
  const [chainStatus, setChainStatus] = useState({
    running: false,
    chains: [],
    activity_mult_threshold: 10,
    last_check: {},
  })
  const [chainForm, setChainForm] = useState({
    chains: ['eth', 'arb', 'bsc'],
    activity_mult_threshold: 10,
  })
  const [spotProbeMsg, setSpotProbeMsg] = useState('')
  const [chainProbeMsg, setChainProbeMsg] = useState('')

  const [macdLoading, setMacdLoading] = useState(false)
  const [macdStatus, setMacdStatus] = useState({ running: false, tasks: [] })
  const [macdTfOptions, setMacdTfOptions] = useState(DEFAULT_MACD_TF)
  const [macdPatternOptions, setMacdPatternOptions] = useState(DEFAULT_MACD_PATTERNS)
  const [macdForm, setMacdForm] = useState({
    symbols: [],
    timeframes: [],
    patterns: [],
  })
  const [alertedMacdTasks, setAlertedMacdTasks] = useState(new Set())

  const macdTfLabelMap = Object.fromEntries(
    macdTfOptions.map((t) => [t.value, t.label])
  )
  const macdPatternLabelMap = Object.fromEntries(
    macdPatternOptions.map((p) => [p.value, p.label])
  )

  const minutePairsForPool = minuteStatus.running
    ? (minuteStatus.symbols || []).map((s) => ({
        type: 'minute',
        key: `minute|${s}`,
        symbol: String(s).toUpperCase(),
        tf: `合约预警(${minuteStatus.interval || '1m'})`,
      }))
    : []
  const spotMinutePairsForPool = spotMinuteStatus.running
    ? (spotMinuteStatus.symbols || []).map((s) => ({
        type: 'spot-minute',
        key: `spot-minute|${s}`,
        symbol: String(s).toUpperCase(),
        tf: `现货预警(${spotMinuteStatus.interval || '1m'})`,
      }))
    : []
  const chainLabelMap = Object.fromEntries(chainOptions.map((c) => [c.id, c.name]))
  const chainPairsForPool = chainStatus.running
    ? (chainStatus.chains || []).map((c) => ({
        type: 'chain',
        key: `chain|${c}`,
        symbol: chainLabelMap[c] || String(c).toUpperCase(),
        tf: '链上15分钟',
      }))
    : []
  const currencyPairsForPool = (status.pairs || []).map((p) => ({
    type: 'pair',
    key: `pair|${p[0]}|${p[1]}`,
    symbol: p[0],
    tf: p[1],
  }))
  const macdTasksForPool = (macdStatus.tasks || []).map((t) => ({
    type: 'macd',
    key: `macd|${t[0]}|${t[1]}|${t[2]}`,
    symbol: t[0],
    tf: macdTfLabelMap[t[1]] || t[1],
    pattern: macdPatternLabelMap[t[2]] || t[2],
    tfValue: t[1],
    patternValue: t[2],
  }))
  const displayItems = [
    ...currencyPairsForPool,
    ...minutePairsForPool,
    ...spotMinutePairsForPool,
    ...chainPairsForPool,
    ...macdTasksForPool,
  ]
  const hasAnyAlerted =
    displayItems.some((p) => {
      if (p.type === 'macd') return alertedMacdTasks.has(`${p.symbol}|${p.tfValue}|${p.patternValue}`)
      return alertedPairs.has(`${p.symbol}|${p.tf}`)
    })

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

  const refreshSpotMinuteStatus = async () => {
    try {
      const res = await getSpotMinuteAlertStatus()
      setSpotMinuteStatus({
        running: !!res.running,
        symbols: res.symbols || [],
        interval: res.interval || '1m',
        vol_pct_threshold: Number(res.vol_pct_threshold ?? 5),
        volume_mult_threshold: Number(res.volume_mult_threshold ?? 20),
        ob_notional_threshold: Number(res.ob_notional_threshold ?? 200000),
      })
      if (!res.running) {
        setSpotMinuteForm((prev) => ({
          ...prev,
          interval: res.interval || '1m',
          vol_pct_threshold: Number(res.vol_pct_threshold ?? 5),
          volume_mult_threshold: Number(res.volume_mult_threshold ?? 20),
          ob_notional_threshold: Number(res.ob_notional_threshold ?? 200000),
        }))
      }
    } catch (_) {}
  }

  const refreshChainStatus = async () => {
    try {
      const res = await getChainActivityStatus()
      setChainStatus({
        running: !!res.running,
        chains: res.chains || [],
        activity_mult_threshold: Number(res.activity_mult_threshold ?? 10),
        last_check: res.last_check || {},
      })
      if (!res.running && res.activity_mult_threshold != null) {
        setChainForm((prev) => ({
          ...prev,
          activity_mult_threshold: Number(res.activity_mult_threshold ?? 10),
        }))
      }
    } catch (_) {}
  }

  const refreshMacdStatus = async () => {
    try {
      const res = await getMacdStatus()
      setMacdStatus({ running: !!res.running, tasks: res.tasks || [] })
      setAlertedMacdTasks(new Set(res.alerted || []))
    } catch (_) {}
  }

  const isAlerted = (item) => {
    if (item.type === 'macd') {
      return alertedMacdTasks.has(`${item.symbol}|${item.tfValue}|${item.patternValue}`)
    }
    return alertedPairs.has(`${item.symbol}|${item.tf}`)
  }

  useEffect(() => {
    let t1, t2, t3, t4, t5
    const load = async () => {
      try {
        const res = await getSymbols()
        setSymbolList(res.symbols || [])
      } catch (_) {}
      try {
        const spotRes = await getSpotSymbols()
        setSpotSymbolList(spotRes.symbols || [])
      } catch (_) {}
      try {
        const chainRes = await getChainActivityChains()
        if (chainRes.chains?.length) setChainOptions(chainRes.chains)
      } catch (_) {}
      try {
        const optRes = await getMacdOptions()
        if (optRes.timeframes?.length) setMacdTfOptions(optRes.timeframes)
        if (optRes.patterns?.length) setMacdPatternOptions(optRes.patterns)
      } catch (_) {}
      await refreshStatus()
      await refreshMinuteStatus()
      await refreshSpotMinuteStatus()
      await refreshChainStatus()
      await refreshMacdStatus()
      t1 = setInterval(refreshStatus, 5000)
      t2 = setInterval(refreshMinuteStatus, 5000)
      t3 = setInterval(refreshSpotMinuteStatus, 5000)
      t4 = setInterval(refreshChainStatus, 5000)
      t5 = setInterval(refreshMacdStatus, 5000)
    }
    load()
    return () => {
      if (t1) clearInterval(t1)
      if (t2) clearInterval(t2)
      if (t3) clearInterval(t3)
      if (t4) clearInterval(t4)
      if (t5) clearInterval(t5)
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

  const removePair = async (item) => {
    if (item.type === 'minute') {
      await handleMinuteStop()
      return
    }
    if (item.type === 'spot-minute') {
      await handleSpotMinuteStop()
      return
    }
    if (item.type === 'chain') {
      await handleChainStop()
      return
    }
    if (item.type === 'macd') {
      try {
        await apiRemoveMacdTask({
          symbol: item.symbol,
          timeframe: item.tfValue,
          pattern: item.patternValue,
        })
        await refreshMacdStatus()
      } catch (e) {
        alert(e?.response?.data?.detail || '移除失败')
      }
      return
    }
    try {
      await apiRemovePair({ symbol: item.symbol, timeframe: item.tf })
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
      alert('已启动合约分钟预警')
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
      alert('已停止合约预警')
      await refreshMinuteStatus()
    } catch (e) {
      alert(e?.response?.data?.detail || '停止失败')
    }
  }

  const handleSpotMinuteStart = async () => {
    if (!spotMinuteForm.symbols.length) {
      alert('请选择现货预警监控币种')
      return
    }
    setSpotMinuteLoading(true)
    try {
      await startSpotMinuteAlert({
        symbols: spotMinuteForm.symbols,
        interval: spotMinuteForm.interval,
        vol_pct_threshold: spotMinuteForm.vol_pct_threshold,
        volume_mult_threshold: spotMinuteForm.volume_mult_threshold,
        ob_notional_threshold: spotMinuteForm.ob_notional_threshold,
      })
      alert('已启动现货分钟预警')
      setSpotMinuteForm((prev) => ({ ...prev, symbols: [] }))
      await refreshSpotMinuteStatus()
    } catch (e) {
      alert(e?.response?.data?.detail || '启动失败')
    } finally {
      setSpotMinuteLoading(false)
    }
  }

  const handleSpotMinuteStop = async () => {
    try {
      await stopSpotMinuteAlert()
      alert('已停止现货预警')
      await refreshSpotMinuteStatus()
    } catch (e) {
      alert(e?.response?.data?.detail || '停止失败')
    }
  }

  const toggleChain = (chainId) => {
    setChainForm((prev) => ({
      ...prev,
      chains: prev.chains.includes(chainId)
        ? prev.chains.filter((c) => c !== chainId)
        : [...prev.chains, chainId],
    }))
  }

  const handleChainStart = async () => {
    if (!chainForm.chains.length) {
      alert('请至少选择一条链')
      return
    }
    setChainLoading(true)
    try {
      await startChainActivity({
        chains: chainForm.chains,
        activity_mult_threshold: chainForm.activity_mult_threshold,
        check_interval_sec: 900,
        cooldown_sec: 900,
      })
      alert('已启动链上活跃度监控')
      await refreshChainStatus()
    } catch (e) {
      alert(e?.response?.data?.detail || '启动失败')
    } finally {
      setChainLoading(false)
    }
  }

  const handleChainStop = async () => {
    try {
      await stopChainActivity()
      alert('已停止链上监控')
      await refreshChainStatus()
    } catch (e) {
      alert(e?.response?.data?.detail || '停止失败')
    }
  }

  const handleSpotProbe = async () => {
    const sym = spotMinuteForm.symbols[0] || 'BTCUSDT'
    setSpotProbeMsg('检测中…')
    try {
      const res = await probeSpotMinuteAlert({ symbol: sym, interval: spotMinuteForm.interval })
      if (res.ok) {
        setSpotProbeMsg(
          `✅ ${sym} 现货数据正常 | K线 ${res.klines_count} 根 | 深度 ${res.depth_ok ? 'OK' : '失败'}`
          + (res.would_alert?.length ? ` | 当前会触发 ${res.would_alert.length} 条预警` : ' | 当前未达预警阈值')
        )
      } else {
        setSpotProbeMsg(`❌ ${res.error || '探测失败'}${res.hint ? ` — ${res.hint}` : ''}`)
      }
    } catch (e) {
      setSpotProbeMsg(`❌ ${e?.response?.data?.detail || e?.message || '请求失败'}`)
    }
  }

  const handleSpotTestDingtalk = async () => {
    try {
      const sym = spotMinuteForm.symbols[0] || 'BTCUSDT'
      const res = await testSpotMinuteDingtalk({ symbol: sym })
      alert(res.message || '测试消息已发送，请查看钉钉')
    } catch (e) {
      alert(e?.response?.data?.detail || '钉钉测试失败')
    }
  }

  const handleChainProbe = async () => {
    setChainProbeMsg('检测中…')
    try {
      const res = await probeChainActivity({ chains: chainForm.chains.join(',') })
      const lines = Object.entries(res.results || {}).map(([id, row]) => {
        if (row.ok) {
          if (row.tx_count != null) {
            return `${row.chain_name}: ${row.tx_count?.toLocaleString()} 笔/15min`
          }
          return `${row.chain_name}: 区块 #${row.block_number} (${row.tx_in_latest_block} tx) via ${row.rpc}`
        }
        return `${row.chain_name || id}: 失败 (${row.error})`
      })
      setChainProbeMsg(
        res.ok
          ? `✅ 全部连通 | ${lines.join(' · ')}`
          : `⚠ ${res.ok_count}/${res.total} 条链可用 | ${lines.join(' · ')}`
      )
    } catch (e) {
      setChainProbeMsg(`❌ ${e?.response?.data?.detail || e?.message || '请求失败'}`)
    }
  }

  const handleChainCheckNow = async () => {
    setChainProbeMsg('立即检测中…')
    try {
      const res = await checkChainActivityNow()
      if (res.mode === 'running_service') {
        await refreshChainStatus()
        const lines = Object.entries(res.results || {}).map(([id, row]) => {
          const name = chainLabelMap[id] || id
          if (row.error) return `${name}: 失败`
          const ratio = row.ratio != null ? ` ${row.ratio}x` : ' (首轮基线)'
          return `${name}: ${row.tx_count?.toLocaleString()}笔${ratio}`
        })
        setChainProbeMsg(`✅ 已执行一轮 | ${lines.join(' · ')}`)
      } else {
        await handleChainProbe()
      }
    } catch (e) {
      setChainProbeMsg(`❌ ${e?.response?.data?.detail || e?.message || '请求失败'}`)
    }
  }

  const handleChainTestDingtalk = async () => {
    try {
      const res = await testChainActivityDingtalk()
      alert(res.message || '测试消息已发送，请查看钉钉')
    } catch (e) {
      alert(e?.response?.data?.detail || '钉钉测试失败')
    }
  }

  const toggleMacdItem = (field, v) => {
    setMacdForm((prev) => ({
      ...prev,
      [field]: prev[field].includes(v)
        ? prev[field].filter((x) => x !== v)
        : [...prev[field], v],
    }))
  }

  const handleMacdStart = async () => {
    if (!macdForm.symbols.length || !macdForm.timeframes.length || !macdForm.patterns.length) {
      alert('请选择币种、K线级别和形态类型')
      return
    }
    setMacdLoading(true)
    try {
      await startMacdMonitor({
        symbols: macdForm.symbols,
        timeframes: macdForm.timeframes,
        patterns: macdForm.patterns,
      })
      alert('已启动 MACD 形态监控')
      setMacdForm({ symbols: [], timeframes: [], patterns: [] })
      await refreshMacdStatus()
    } catch (e) {
      alert(e?.response?.data?.detail || '启动失败')
    } finally {
      setMacdLoading(false)
    }
  }

  const handleMacdStop = async () => {
    try {
      await stopMacdMonitor()
      alert('已停止 MACD 形态监控')
      await refreshMacdStatus()
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

      {/* Card 2: 合约分钟预警配置 */}
      <div className="mon-card mon-card-orange">
        <div className="mon-card-header mon-card-header-orange">
          <div className="mon-card-title">
            <span className="mon-icon">🔔</span>
            <span>合约分钟预警</span>
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
              🔔 {minuteLoading ? '启动中...' : '启动合约预警'}
            </button>
            <button className="mon-btn-outline-red" disabled={!minuteStatus.running} onClick={handleMinuteStop}>
              ◻ 停止预警
            </button>
          </div>
        </div>
      </div>

      {/* Card 2b: 现货分钟预警 */}
      <div className="mon-card mon-card-blue">
        <div className="mon-card-header mon-card-header-blue">
          <div className="mon-card-title">
            <span className="mon-icon">💱</span>
            <span>现货分钟预警</span>
            {spotMinuteStatus.running && (
              <span className="mon-badge-blue-card">⚡ 运行中</span>
            )}
          </div>
        </div>
        <div className="mon-card-body">
          <p className="mon-hint">
            币安现货市场：波动率、成交量倍数、订单簿大单，逻辑与合约分钟预警相同。
          </p>
          <div className="mon-grid-2">
            <div className="mon-field-group">
              <label className="mon-label">监控币种（现货）</label>
              <MultiSelectDropdown
                options={spotSymbolList}
                value={spotMinuteForm.symbols}
                onChange={(vals) => setSpotMinuteForm((prev) => ({ ...prev, symbols: vals }))}
                placeholder="搜索并选择现货币种..."
              />
              {spotMinuteForm.symbols.length > 0 && (
                <p className="mon-hint-blue-card">已选择 {spotMinuteForm.symbols.length} 个币种</p>
              )}
            </div>
            <div className="mon-params-stack">
              <div className="mon-field-group">
                <label className="mon-label-sm">K线级别</label>
                <select
                  value={spotMinuteForm.interval}
                  onChange={(e) => setSpotMinuteForm((prev) => ({ ...prev, interval: e.target.value }))}
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
                  value={spotMinuteForm.vol_pct_threshold}
                  onChange={(e) =>
                    setSpotMinuteForm((prev) => ({ ...prev, vol_pct_threshold: Number(e.target.value) }))
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
                  value={spotMinuteForm.volume_mult_threshold}
                  onChange={(e) =>
                    setSpotMinuteForm((prev) => ({ ...prev, volume_mult_threshold: Number(e.target.value) }))
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
                  value={spotMinuteForm.ob_notional_threshold}
                  onChange={(e) =>
                    setSpotMinuteForm((prev) => ({ ...prev, ob_notional_threshold: Number(e.target.value) }))
                  }
                  className="mon-input"
                />
              </div>
            </div>
          </div>

          {spotMinuteStatus.running && (
            <div className="mon-status-box">
              <span>⚠</span>
              <div>
                <p className="mon-status-title">当前运行参数</p>
                <p className="mon-status-detail">
                  币种: {spotMinuteStatus.symbols.join(', ')} | 级别: {spotMinuteStatus.interval} | 波动≥{spotMinuteStatus.vol_pct_threshold}% | 量能≥{spotMinuteStatus.volume_mult_threshold}x | 订单簿≥{spotMinuteStatus.ob_notional_threshold}
                </p>
              </div>
            </div>
          )}

          <div className="mon-btn-row">
            <button className="mon-btn-blue" disabled={spotMinuteLoading} onClick={handleSpotMinuteStart}>
              💱 {spotMinuteLoading ? '启动中...' : '启动现货预警'}
            </button>
            <button type="button" className="mon-btn-outline" onClick={handleSpotProbe}>
              🔍 连通性检测
            </button>
            <button type="button" className="mon-btn-outline" onClick={handleSpotTestDingtalk}>
              📨 测试钉钉
            </button>
            <button className="mon-btn-outline-red" disabled={!spotMinuteStatus.running} onClick={handleSpotMinuteStop}>
              ◻ 停止预警
            </button>
          </div>
          {spotProbeMsg && <p className="mon-hint-blue-card">{spotProbeMsg}</p>}
        </div>
      </div>

      {/* Card 2c: 链上活跃度监控 */}
      <div className="mon-card mon-card-teal">
        <div className="mon-card-header mon-card-header-teal">
          <div className="mon-card-title">
            <span className="mon-icon">⛓</span>
            <span>链上活跃度监控</span>
            {chainStatus.running && (
              <span className="mon-badge-teal">运行中</span>
            )}
          </div>
        </div>
        <div className="mon-card-body">
          <p className="mon-hint">
            每 15 分钟统计 ETH / Arbitrum / BSC 链上交易笔数。内置多个免费公共 RPC 会自动切换；若均失败，可设置环境变量 ETH_RPC_URL / ARB_RPC_URL / BSC_RPC_URL 后重启 API。
          </p>
          <div className="mon-grid-2">
            <div className="mon-field-group">
              <label className="mon-label">监控链（可多选）</label>
              <div className="mon-checkbox-list-inline">
                {chainOptions.map((c) => (
                  <label key={c.id} className="mon-checkbox-item">
                    <input
                      type="checkbox"
                      checked={chainForm.chains.includes(c.id)}
                      onChange={() => toggleChain(c.id)}
                    />
                    <span>{c.name}</span>
                  </label>
                ))}
              </div>
            </div>
            <div className="mon-params-stack">
              <div className="mon-field-group">
                <label className="mon-label-sm">活跃度倍数阈值 (x)</label>
                <input
                  type="number"
                  min={2}
                  step={1}
                  value={chainForm.activity_mult_threshold}
                  onChange={(e) =>
                    setChainForm((prev) => ({ ...prev, activity_mult_threshold: Number(e.target.value) }))
                  }
                  className="mon-input"
                />
              </div>
              <div className="mon-field-group">
                <label className="mon-label-sm">检测周期</label>
                <input type="text" value="15 分钟" disabled className="mon-input" />
              </div>
            </div>
          </div>

          {chainStatus.running && (
            <div className="mon-status-box">
              <span>⛓</span>
              <div>
                <p className="mon-status-title">最近检测</p>
                <p className="mon-status-detail">
                  链: {(chainStatus.chains || []).map((id) => chainLabelMap[id] || id).join(', ')}
                  {' '}| 阈值: {chainStatus.activity_mult_threshold}x
                  {Object.keys(chainStatus.last_check || {}).length > 0 && (
                    <>
                      {' '}| 最近: {Object.entries(chainStatus.last_check).map(([k, v]) =>
                        `${chainLabelMap[k] || k} ${v?.tx_count ?? '—'}笔${v?.ratio != null ? ` (${v.ratio}x)` : ''}`
                      ).join(' · ')}
                    </>
                  )}
                </p>
              </div>
            </div>
          )}

          <div className="mon-btn-row">
            <button className="mon-btn-teal" disabled={chainLoading} onClick={handleChainStart}>
              ⛓ {chainLoading ? '启动中...' : '启动链上监控'}
            </button>
            <button type="button" className="mon-btn-outline" onClick={handleChainProbe}>
              🔍 RPC 探测
            </button>
            <button type="button" className="mon-btn-outline" onClick={handleChainCheckNow}>
              ⚡ 立即检测
            </button>
            <button type="button" className="mon-btn-outline" onClick={handleChainTestDingtalk}>
              📨 测试钉钉
            </button>
            <button className="mon-btn-outline-red" disabled={!chainStatus.running} onClick={handleChainStop}>
              ◻ 停止监控
            </button>
          </div>
          {chainProbeMsg && <p className="mon-hint-teal">{chainProbeMsg}</p>}
        </div>
      </div>

      {/* Card 3: MACD 形态监控 */}
      <div className="mon-card mon-card-purple">
        <div className="mon-card-header">
          <div className="mon-card-title">
            <span className="mon-icon">📈</span>
            <span>MACD 金叉形态监控</span>
            {macdStatus.running && (
              <span className="mon-badge-purple">运行中</span>
            )}
          </div>
        </div>
        <div className="mon-card-body">
          <p className="mon-hint">
            MACD(12,26,9) 多级别趋势：K 线收线时检测四种状态转换，触发钉钉预警。
          </p>
          <div className="mon-grid-3">
            <div className="mon-field-group">
              <label className="mon-label">选择币种</label>
              <MultiSelectDropdown
                options={symbolList}
                value={macdForm.symbols}
                onChange={(vals) => setMacdForm((prev) => ({ ...prev, symbols: vals }))}
                placeholder="搜索并选择币种..."
              />
              {macdForm.symbols.length > 0 && (
                <p className="mon-hint-purple">已选择 {macdForm.symbols.length} 个币种</p>
              )}
            </div>
            <div className="mon-field-group">
              <label className="mon-label">K线级别（可多选）</label>
              <div className="mon-checkbox-list">
                {macdTfOptions.map((opt) => (
                  <label key={opt.value} className="mon-checkbox-item">
                    <input
                      type="checkbox"
                      checked={macdForm.timeframes.includes(opt.value)}
                      onChange={() => toggleMacdItem('timeframes', opt.value)}
                    />
                    <span>{opt.label}</span>
                  </label>
                ))}
              </div>
            </div>
            <div className="mon-field-group">
              <label className="mon-label">形态类型（可多选）</label>
              <div className="mon-checkbox-list">
                {macdPatternOptions.map((opt) => (
                  <label key={opt.value} className="mon-checkbox-item">
                    <input
                      type="checkbox"
                      checked={macdForm.patterns.includes(opt.value)}
                      onChange={() => toggleMacdItem('patterns', opt.value)}
                    />
                    <span>{opt.label}</span>
                  </label>
                ))}
              </div>
            </div>
          </div>
          <div className="mon-btn-row">
            <button className="mon-btn-purple" disabled={macdLoading} onClick={handleMacdStart}>
              ▶ {macdLoading ? '启动中...' : '开始监控'}
            </button>
            <button className="mon-btn-outline-red" disabled={!macdStatus.running} onClick={handleMacdStop}>
              ◻ 停止监控
            </button>
          </div>
        </div>
      </div>

      {/* Card 4: 监视/预警中的币种 */}
      <div className="mon-card">
        <div className="mon-card-header">
          <div className="mon-card-title">
            <span className="mon-icon">📊</span>
            <span>监视/预警中的币种</span>
            <span className="mon-badge-blue">{displayItems.length}</span>
            {hasAnyAlerted && (
              <span className="mon-badge-red">⚠ 异动提醒</span>
            )}
          </div>
        </div>
        <div className="mon-card-body">
          {displayItems.length > 0 && (
            <p className="mon-hint">
              已有监视/预警/监控时，选择更多配置后点击对应「开始」可追加；点击 × 可移除该项
            </p>
          )}
          {displayItems.length === 0 ? (
            <div className="mon-empty">
              <div className="mon-empty-icon">👁</div>
              <h3>暂无监视/预警</h3>
              <p>请先启动「币种监视」「合约/现货分钟预警」「链上监控」或「MACD 形态监控」</p>
            </div>
          ) : (
            <div className="mon-chips">
              {displayItems.map((item) => (
                <div
                  key={item.key}
                  className={`mon-chip ${isAlerted(item) ? 'mon-chip-alert' : ''}`}
                >
                  <span className="mon-chip-symbol">{item.symbol}</span>
                  <span className="mon-chip-tf">{item.tf}</span>
                  {item.pattern && (
                    <span className="mon-chip-pattern">{item.pattern}</span>
                  )}
                  <button className="mon-chip-x" onClick={() => removePair(item)}>×</button>
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
