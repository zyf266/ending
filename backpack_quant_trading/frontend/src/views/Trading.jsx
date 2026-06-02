import React, { useEffect, useState } from 'react'
import {
  getStrategies,
  getInstances,
  launchStrategy,
  stopInstance,
  deleteInstance,
  startInstance,
  updateInstance,
  getLogs,
  getHypeStatus,
  toggleHypeStrategy,
  startHypeStrategy,
  startEthTrendShort,
  startAdaptiveLong,
  startAdaptiveShort,
  startAutoClose,
} from '../api/trading'
import './Trading.css'

const PLATFORMS = [
  { label: 'Backpack', value: 'backpack' },
  { label: 'Deepcoin', value: 'deepcoin' },
  { label: 'Ostium', value: 'ostium' },
  { label: 'Hyperliquid', value: 'hyperliquid' },
  { label: 'Binance', value: 'binance' },
  { label: 'Lighter', value: 'lighter' },
]

const Trading = () => {
  const ADAPTIVE_KEYS = ['adaptive_long', 'adaptive_short']
  const [showModal, setShowModal] = useState(false)
  const [editingId, setEditingId] = useState(null)
  const [showKeyEditor, setShowKeyEditor] = useState(false)
  const [instances, setInstances] = useState([])
  const [logs, setLogs] = useState('等待日志输出...')
  const [strategies, setStrategies] = useState([])
  const [launching, setLaunching] = useState(false)
  const [instancesCollapsed, setInstancesCollapsed] = useState(false)
  const [logsCollapsed, setLogsCollapsed] = useState(false)
  const [hypeStatus, setHypeStatus] = useState({ running: false, instances: [] })
  const [togglingHype, setTogglingHype] = useState(false)
  const [form, setForm] = useState({
    platform: 'backpack',
    strategy: 'mean_reversion',
    symbol: 'ETH/USDC',
    wallet_memo: '',
    size: 20,
    leverage: 50,
    take_profit: 2.0,
    stop_loss: 1.5,
    api_key: '',
    api_secret: '',
    passphrase: '',
    private_key: '',
    // HYPE / 做空做多策略专用参数
    hype_stop_loss: 3.0,
    hype_take_profit: 6.0,
    hype_break_even: 3.0,
    eth_price_filter: 2000,
    adaptive_long_coin: '',    // 自适应做多：交易对币种
    adaptive_long_xyz: '',     // 已废弃: XYZ 是 HIP-3 DEX 而非子账户，无需地址
    adaptive_long_account_index: 0,  // Lighter 账户索引
    adaptive_long_api_key_index: 2,  // Lighter API 密鑰索引
    // 与全局 form.size / leverage 解耦，避免请求体缺字段时后端回落到默认 20×50
    adaptive_long_margin: 20,
    adaptive_long_leverage: 50,
    adaptive_long_timeframe: '',     // K线级别过滤
    adaptive_long_lock_profit: 0,    // 锁利触发盈利%，0=不启用
    adaptive_long_lock_profit_sl: 0, // 锁利后 SL 锁定盈利%
    adaptive_long_min_ai_score: 0,   // 0=不启用；买入 Webhook 须 AI 分>=该值才开单
    adaptive_short_coin: '',    // 自适应做空：交易对币种
    adaptive_short_account_index: 0,
    adaptive_short_api_key_index: 2,
    adaptive_short_margin: 20,
    adaptive_short_leverage: 50,
    adaptive_short_timeframe: '',
    adaptive_short_lock_profit: 0,
    adaptive_short_lock_profit_sl: 0,
    auto_close_coin: '',        // 自动平仓：交易对币种
    auto_close_account_index: 0, // 自动平仓：Lighter 账户索引
    auto_close_api_key_index: 2, // 自动平仓：Lighter API key index
  })

  const isDualFreq = form.strategy === 'dual_freq_trend'

  const setField = (name, value) => {
    setForm((prev) => ({ ...prev, [name]: value }))
    if (name === 'strategy' && value === 'dual_freq_trend') {
      setForm((prev) => ({
        ...prev,
        leverage: 100,
        size: 10,
        take_profit: 150,
        stop_loss: 50,
      }))
    }
    // ETH趋势做空 / HYPE做空 固定平台为 hyperliquid；自适应做多支持 hyperliquid 和 binance
    if (name === 'strategy' && ['eth_trend_short', 'hype_adaptive_short'].includes(value)) {
      setForm((prev) => ({ ...prev, platform: 'hyperliquid' }))
    }
    if (name === 'strategy' && value === 'adaptive_long') {
      // 自适应做多：默认 hyperliquid，但也允许切换到 binance / lighter
      // 关键：切换策略时重置“周期过滤”，避免沿用上一次选择导致误过滤
      setForm((prev) => ({
        ...prev,
        platform: 'hyperliquid',
        adaptive_long_timeframe: '',
        // 从当前全局保证金/杠杆带入专用字段，保证界面与请求一致
        adaptive_long_margin: prev.size,
        adaptive_long_leverage: prev.leverage,
      }))
    }
    if (name === 'strategy' && value === 'adaptive_short') {
      setForm((prev) => ({
        ...prev,
        platform: 'hyperliquid',
        adaptive_short_timeframe: '',
        adaptive_short_margin: prev.size,
        adaptive_short_leverage: prev.leverage,
      }))
    }
    if (name === 'strategy' && value === 'auto_close') {
      setForm((prev) => ({
        ...prev,
        // 自动平仓：仅需私钥+币种（支持 hyperliquid / lighter）
        platform: (prev.platform === 'lighter' ? 'lighter' : 'hyperliquid'),
        api_key: '',
        api_secret: '',
        passphrase: '',
        auto_close_account_index: prev.auto_close_account_index ?? 0,
        auto_close_api_key_index: prev.auto_close_api_key_index ?? 2,
      }))
    }
  }

  const refresh = async () => {
    try {
      const res = await getInstances()
      setInstances(res.instances || [])
    } catch (_) {}
  }

  const refreshLogs = async () => {
    try {
      const res = await getLogs()
      setLogs(res.logs || '等待日志输出...')
    } catch (_) {}
  }

  const refreshHypeStatus = async () => {
    try {
      const res = await getHypeStatus()
      setHypeStatus(res || { running: false, instances: [] })
    } catch (_) {}
  }

  useEffect(() => {
    let t1, t2, t3
    const load = async () => {
      try {
        const res = await getStrategies()
        setStrategies(res.strategies || [])
      } catch (_) {}
      await refresh()
      await refreshLogs()
      await refreshHypeStatus()
      t1 = setInterval(refresh, 5000)
      t2 = setInterval(refreshLogs, 10000)
      t3 = setInterval(refreshHypeStatus, 5000)
    }
    load()
    return () => {
      if (t1) clearInterval(t1)
      if (t2) clearInterval(t2)
      if (t3) clearInterval(t3)
    }
  }, [])

  const CEX_PLATFORMS = ['backpack', 'deepcoin', 'binance']
  
  const handleLaunch = async () => {
    // 编辑实例：保存参数（必要时后端会自动重启）
    if (editingId) {
      setLaunching(true)
      try {
        const isLong = form.strategy === 'adaptive_long'
        const isBinance = form.platform === 'binance'
        const isLighter = form.platform === 'lighter'
        const coin = (isLong ? form.adaptive_long_coin : form.adaptive_short_coin).toUpperCase().trim()
        if (!coin) { alert('请填写交易对（如 BTC、ETH、HYPE）'); return }
        const payload = {
          wallet_memo: form.wallet_memo || '',
          exchange: form.platform,
          coin,
          timeframe_filter: isLong ? (form.adaptive_long_timeframe || undefined) : (form.adaptive_short_timeframe || undefined),
          margin_amount: isLong ? form.adaptive_long_margin : form.adaptive_short_margin,
          leverage: isLong ? form.adaptive_long_leverage : form.adaptive_short_leverage,
          stop_loss_pct: form.hype_stop_loss / 100,
          take_profit_pct: form.hype_take_profit / 100,
          break_even_pct: form.hype_break_even / 100,
          lock_profit_pct: isLong
            ? (form.adaptive_long_lock_profit > 0 ? form.adaptive_long_lock_profit / 100 : 0)
            : (form.adaptive_short_lock_profit > 0 ? form.adaptive_short_lock_profit / 100 : 0),
          lock_profit_sl_pct: isLong
            ? (form.adaptive_long_lock_profit > 0 ? form.adaptive_long_lock_profit_sl / 100 : 0)
            : (form.adaptive_short_lock_profit > 0 ? form.adaptive_short_lock_profit_sl / 100 : 0),
          private_key: (!isBinance) ? (form.private_key || undefined) : undefined,
          api_key: isBinance ? (form.api_key || undefined) : undefined,
          api_secret: isBinance ? (form.api_secret || undefined) : undefined,
          account_index: isLighter ? (isLong ? form.adaptive_long_account_index : form.adaptive_short_account_index) : undefined,
          api_key_index: isLighter ? (isLong ? form.adaptive_long_api_key_index : form.adaptive_short_api_key_index) : undefined,
          ...(isLong ? { min_ai_score_for_trade: Math.max(0, Number(form.adaptive_long_min_ai_score) || 0) } : {}),
        }
        const res = await updateInstance(editingId, payload)
        alert(res?.message || '已保存')
        setShowModal(false)
        setEditingId(null)
        await refresh()
      } catch (e) {
        alert(e?.response?.data?.detail || '保存失败')
      } finally {
        setLaunching(false)
      }
      return
    }

    // 【HYPE自适应做空策略】—— CEX 平台走通用流程，面向链平台才走独立端点
    if (form.strategy === 'hype_adaptive_short') {
      if (CEX_PLATFORMS.includes(form.platform)) {
        // Binance/Backpack/Deepcoin —— 走通用 launchStrategy
        if (!form.api_key || !form.api_secret) { alert('请输入 API Key 和 Secret'); return }
      } else {
        // Hyperliquid/Ostium —— 走専用端点
        if (!form.private_key) { alert('请输入 Hyperliquid 私鑰'); return }
        setLaunching(true)
        try {
          const symbol = form.symbol.split('/')[0].split('_')[0] || 'ETH'
          const res = await startHypeStrategy(symbol, form.private_key, {
            stop_loss_pct: form.hype_stop_loss / 100,
            take_profit_pct: form.hype_take_profit / 100,
            break_even_pct: form.hype_break_even / 100,
            margin_amount: form.size,
            leverage: form.leverage,
          })
          alert(res.message || 'HYPE做空策略启动成功')
          setShowModal(false); await refresh(); await refreshHypeStatus()
        } catch (e) { alert(e?.response?.data?.detail || '启动失败') }
        finally { setLaunching(false) }
        return
      }
    }
  
    // 【自适应做多策略】Webhook驱动，支持 Hyperliquid 和 Binance
    if (form.strategy === 'adaptive_long') {
      const coin = form.adaptive_long_coin.toUpperCase().trim()
      if (!coin) { alert('请填写交易对（如 BTC、ETH、HYPE）'); return }
      setLaunching(true)
      try {
        const isBinance = form.platform === 'binance'
        const isLighter = form.platform === 'lighter'
        const res = await startAdaptiveLong({
          coin,
          exchange:          form.platform,
          wallet_memo:       form.wallet_memo || '',
          private_key:       (!isBinance) ? (form.private_key || undefined) : undefined,
          api_key:           isBinance ? form.api_key : undefined,
          api_secret:        isBinance ? form.api_secret : undefined,
          account_index:     isLighter ? form.adaptive_long_account_index : undefined,
          api_key_index:     isLighter ? form.adaptive_long_api_key_index : undefined,
          timeframe_filter:  form.adaptive_long_timeframe || undefined,
          lock_profit_pct:   form.adaptive_long_lock_profit > 0 ? form.adaptive_long_lock_profit / 100 : undefined,
          lock_profit_sl_pct: form.adaptive_long_lock_profit > 0 ? form.adaptive_long_lock_profit_sl / 100 : undefined,
          margin_amount:     form.adaptive_long_margin,
          leverage:          form.adaptive_long_leverage,
          min_ai_score_for_trade: Math.max(0, Number(form.adaptive_long_min_ai_score) || 0),
          stop_loss_pct:     form.hype_stop_loss / 100,
          take_profit_pct:   form.hype_take_profit / 100,
          break_even_pct:    form.hype_break_even / 100,
        })
        alert(res.message || `${coin}做多策略启动成功`)
        setShowModal(false); await refresh()
      } catch (e) { alert(e?.response?.data?.detail || '启动失败') }
      finally { setLaunching(false) }
      return
    }

    // 【自适应做空策略】Webhook驱动，支持 Hyperliquid / Binance / Lighter
    if (form.strategy === 'adaptive_short') {
      const coin = form.adaptive_short_coin.toUpperCase().trim()
      if (!coin) { alert('请填写交易对（如 BTC、ETH、HYPE）'); return }
      setLaunching(true)
      try {
        const isBinance = form.platform === 'binance'
        const isLighter = form.platform === 'lighter'
        const res = await startAdaptiveShort({
          coin,
          exchange:          form.platform,
          wallet_memo:       form.wallet_memo || '',
          private_key:       (!isBinance) ? (form.private_key || undefined) : undefined,
          api_key:           isBinance ? form.api_key : undefined,
          api_secret:        isBinance ? form.api_secret : undefined,
          account_index:     isLighter ? form.adaptive_short_account_index : undefined,
          api_key_index:     isLighter ? form.adaptive_short_api_key_index : undefined,
          timeframe_filter:  form.adaptive_short_timeframe || undefined,
          lock_profit_pct:   form.adaptive_short_lock_profit > 0 ? form.adaptive_short_lock_profit / 100 : undefined,
          lock_profit_sl_pct: form.adaptive_short_lock_profit > 0 ? form.adaptive_short_lock_profit_sl / 100 : undefined,
          margin_amount:     form.adaptive_short_margin,
          leverage:          form.adaptive_short_leverage,
          stop_loss_pct:     form.hype_stop_loss / 100,
          take_profit_pct:   form.hype_take_profit / 100,
          break_even_pct:    form.hype_break_even / 100,
        })
        alert(res.message || `${coin}做空策略启动成功`)
        setShowModal(false); await refresh()
      } catch (e) { alert(e?.response?.data?.detail || '启动失败') }
      finally { setLaunching(false) }
      return
    }
  
    // 【自动平仓策略】Webhook驱动：只处理 sell → 平仓；buy 忽略
    if (form.strategy === 'auto_close') {
      const coin = form.auto_close_coin.toUpperCase().trim()
      if (!coin) { alert('请填写交易对（如 BTC、ETH、HYPE）'); return }
      if (!['hyperliquid', 'lighter'].includes(form.platform)) {
        alert('自动平仓策略目前仅支持 Hyperliquid / Lighter')
        return
      }
      if (!form.private_key) { alert('请输入私鑰'); return }
      if (form.platform === 'lighter') {
        const idx = Number(form.auto_close_account_index)
        if (!Number.isFinite(idx) || idx <= 0) {
          alert('Lighter 需要填写正确的 Account Index（如 /explorer/accounts/723233 → 723233）')
          return
        }
      }
      setLaunching(true)
      try {
        const res = await startAutoClose({
          coin,
          exchange: form.platform,
          wallet_memo: form.wallet_memo || '',
          private_key: form.private_key || undefined,
          account_index: form.platform === 'lighter' ? Number(form.auto_close_account_index) : undefined,
          api_key_index: form.platform === 'lighter' ? Number(form.auto_close_api_key_index ?? 2) : undefined,
        })
        alert(res.message || `${coin}自动平仓策略启动成功`)
        setShowModal(false); await refresh()
      } catch (e) { alert(e?.response?.data?.detail || '启动失败') }
      finally { setLaunching(false) }
      return
    }

    // 【ETH趋势做空策略】—— 始终走专用端点，CEX 平台传 exchange+api_key，链平台传 private_key
    if (form.strategy === 'eth_trend_short') {
      if (CEX_PLATFORMS.includes(form.platform)) {
        if (!form.api_key || !form.api_secret) { alert('请输入 API Key 和 Secret'); return }
      } else {
        if (!form.private_key) { alert('请输入 Hyperliquid 私鑰'); return }
      }
      setLaunching(true)
      try {
        const isCEX = CEX_PLATFORMS.includes(form.platform)
        const res = await startEthTrendShort({
          symbol:           form.symbol.split('/')[0].split('_')[0] || 'ETH',
          exchange:         form.platform,
          private_key:      isCEX ? undefined : form.private_key,
          api_key:          isCEX ? form.api_key : undefined,
          api_secret:       isCEX ? form.api_secret : undefined,
          margin_amount:    form.size,
          leverage:         form.leverage,
          stop_loss_pct:    form.hype_stop_loss / 100,
          take_profit_pct:  form.hype_take_profit / 100,
          price_filter_min: form.eth_price_filter,
        })
        alert(res.message || 'ETH趋势做空策略启动成功')
        setShowModal(false); await refresh()
      } catch (e) { alert(e?.response?.data?.detail || '启动失败') }
      finally { setLaunching(false) }
      return
    }
  
    // ── 通用启动流程（所有策略在 CEX 平台，以及其他策略在任意平台）──
    if (CEX_PLATFORMS.includes(form.platform)) {
      if (!form.api_key || !form.api_secret) {
        alert('请输入 API Key 和 Secret')
        return
      }
    } else {
      if (!form.private_key) {
        alert('请输入私鑰')
        return
      }
    }
    setLaunching(true)
    try {
      const res = await launchStrategy({
        platform:    form.platform,
        strategy:    form.strategy,
        symbol:      form.symbol,
        size:        form.size,
        leverage:    form.leverage,
        take_profit: form.strategy === 'hype_adaptive_short' || form.strategy === 'eth_trend_short' || ADAPTIVE_KEYS.includes(form.strategy)
          ? form.hype_take_profit
          : form.take_profit,
        stop_loss:   form.strategy === 'hype_adaptive_short' || form.strategy === 'eth_trend_short' || ADAPTIVE_KEYS.includes(form.strategy)
          ? form.hype_stop_loss
          : form.stop_loss,
        api_key:     form.api_key || undefined,
        api_secret:  form.api_secret || undefined,
        passphrase:  form.passphrase || undefined,
        private_key: form.private_key || undefined,
      })
      alert(res.message || '启动成功')
      setShowModal(false)
      await refresh()
    } catch (e) {
      alert(e?.response?.data?.detail || '启动失败')
    } finally {
      setLaunching(false)
    }
  }

  const stopOne = async (id) => {
    try {
      await stopInstance(id)
      alert('已停止')
      await refresh()
    } catch (e) {
      alert(e?.response?.data?.detail || '停止失败')
    }
  }

  const startOne = async (id) => {
    try {
      const res = await startInstance(id)
      alert(res?.message || '已启动')
      await refresh()
    } catch (e) {
      alert(e?.response?.data?.detail || '启动失败')
    }
  }

  const deleteOne = async (id) => {
    if (!window.confirm('确定删除该实例卡片吗？删除会同时停止实例。')) return
    try {
      await deleteInstance(id)
      alert('已删除')
      await refresh()
    } catch (e) {
      alert(e?.response?.data?.detail || '删除失败')
    }
  }

  const editOne = (inst) => {
    const cfg = inst?.config || {}
    const strategy = cfg.strategy || (String(inst.strategy_name || '').includes('做多') ? 'adaptive_long' : 'adaptive_short')
    const exchange = (cfg.exchange || inst.platform || 'hyperliquid')
    const coin = (cfg.coin || inst.symbol || '').toString().replace(/[^A-Z0-9]/g, '').toUpperCase()
    setForm((prev) => ({
      ...prev,
      platform: exchange,
      strategy,
      wallet_memo: cfg.wallet_memo || '',
      // 安全：不回显私钥。留空代表“不修改”，后端会沿用已保存的密文密钥。
      private_key: '',
      api_key: cfg.api_key || prev.api_key,
      api_secret: '',
      hype_stop_loss: Number(cfg.stop_loss_pct ?? (prev.hype_stop_loss / 100)) * 100,
      hype_take_profit: Number(cfg.take_profit_pct ?? (prev.hype_take_profit / 100)) * 100,
      hype_break_even: Number(cfg.break_even_pct ?? (prev.hype_break_even / 100)) * 100,
      adaptive_long_coin: coin,
      adaptive_short_coin: coin,
      adaptive_long_timeframe: cfg.timeframe_filter || '',
      adaptive_short_timeframe: cfg.timeframe_filter || '',
      adaptive_long_margin: cfg.margin_amount ?? prev.adaptive_long_margin,
      adaptive_short_margin: cfg.margin_amount ?? prev.adaptive_short_margin,
      adaptive_long_leverage: cfg.leverage ?? prev.adaptive_long_leverage,
      adaptive_short_leverage: cfg.leverage ?? prev.adaptive_short_leverage,
      adaptive_long_account_index: cfg.account_index ?? prev.adaptive_long_account_index,
      adaptive_short_account_index: cfg.account_index ?? prev.adaptive_short_account_index,
      adaptive_long_api_key_index: cfg.api_key_index ?? prev.adaptive_long_api_key_index,
      adaptive_short_api_key_index: cfg.api_key_index ?? prev.adaptive_short_api_key_index,
      adaptive_long_lock_profit: Number(cfg.lock_profit_pct ?? 0) * 100,
      adaptive_long_lock_profit_sl: Number(cfg.lock_profit_sl_pct ?? 0) * 100,
      adaptive_long_min_ai_score: Number(cfg.min_ai_score_for_trade ?? 0),
      adaptive_short_lock_profit: Number(cfg.lock_profit_pct ?? 0) * 100,
      adaptive_short_lock_profit_sl: Number(cfg.lock_profit_sl_pct ?? 0) * 100,
    }))
    setEditingId(inst.id)
    setShowKeyEditor(false)
    setShowModal(true)
  }

  const getHypeEnabled = (instanceId) => {
    const item = (hypeStatus.instances || []).find((x) => x.instance_id === instanceId)
    return item ? !!item.is_enabled : true
  }

  const toggleHype = async (instanceId, enabled) => {
    setTogglingHype(true)
    try {
      const res = await toggleHypeStrategy(enabled, instanceId)
      alert(res?.message || `策略已${enabled ? '开启' : '关闭'}`)
      await refreshHypeStatus()
    } catch (e) {
      alert(e?.response?.data?.detail || '切换失败')
    } finally {
      setTogglingHype(false)
    }
  }

  return (
    <div className="page trading-page">
      {/* 策略实例管理标题行 + 按钮 */}
      <div className="instances-header-row">
        <div>
          <h3 className="instances-header-title">策略实例管理</h3>
          <p className="instances-header-sub">查看和管理所有运行中的量化交易策略</p>
        </div>
        <button type="button" className="btn-primary" onClick={() => setShowModal(true)}>
          + 启动新策略
        </button>
      </div>

      {/* 运行中的策略实例卡片区 */}
      <div className="instances-card">
        <div className="instances-card-header" onClick={() => setInstancesCollapsed(!instancesCollapsed)}>
          <button type="button" className="section-toggle-btn">
            <span className="section-toggle-icon">{instancesCollapsed ? '▶' : '▼'}</span>
            <span className="instances-card-title-text">运行中的策略实例</span>
          </button>
          <div className="instances-count-pill">
            运行中
            <span className="instances-count-dot" />
            {instances.length}
          </div>
        </div>

        {!instancesCollapsed && (instances.length === 0 ? (
          <div className="instances-empty">
            <div className="instances-empty-icon">🚀</div>
            <h4>暂无运行中的策略</h4>
            <p>点击「启动新策略」按钮开始您的量化交易之旅</p>
            <button type="button" className="btn-primary" onClick={() => setShowModal(true)}>
              + 立即启动
            </button>
          </div>
        ) : (
          <div className="instance-grid">
            {instances.map((inst) => (
              <div key={inst.id} className="instance-card">
                {/* 顶部状态栏 */}
                <div className="inst-header">
                  <div className="inst-tags">
                    <span className={`tag ${inst.platform === 'ostium' ? 'tag-warning' : ''}`}>
                      {(inst.platform || '').toUpperCase()}
                    </span>
                    <span className={inst.status === 'stopped' ? 'status stop' : (inst.status === 'registering' ? 'status reg' : 'status run')}>
                      <span className="status-dot" />
                      {inst.status === 'stopped' ? 'STOPPED' : (inst.status === 'registering' ? 'REGISTERING' : 'RUNNING')}
                    </span>
                  </div>
                  <div className="inst-balance">
                    <span className="inst-balance-label">账户余额</span>
                    <span className="inst-balance-value">
                      {inst.balance && !isNaN(Number(inst.balance))
                        ? `$${Number(inst.balance).toLocaleString()}`
                        : '--'}
                    </span>
                  </div>
                </div>

                {/* 策略名称与交易对 */}
                <div className="inst-body">
                  <h3 className="inst-name">{inst.strategy_name}</h3>
                  <div className="inst-meta-row">
                    <span className="inst-symbol-badge">{inst.symbol}</span>
                    <span className="inst-meta-text">{inst.start_time || '--'}</span>
                  </div>
                </div>

                {/* 底部操作区 */}
                <div className="inst-footer">
                  {inst.strategy_name === 'HYPE做空策略(Webhook版)' && (
                    <button
                      type="button"
                      className={`inst-btn ${getHypeEnabled(inst.id) ? 'inst-btn-warning' : 'inst-btn-primary'}`}
                      disabled={togglingHype || inst?.can_operate === false}
                      title={inst?.can_operate === false ? (inst?.operate_block_reason || '非本人账户启动，已隔离') : ''}
                      onClick={() => toggleHype(inst.id, !getHypeEnabled(inst.id))}
                    >
                      {getHypeEnabled(inst.id) ? '⏸ 暂停策略' : '▶ 启用策略'}
                    </button>
                  )}
                  <button
                    type="button"
                    className="inst-btn inst-btn-primary"
                    disabled={inst.status !== 'stopped' || inst?.can_operate === false}
                    title={inst?.can_operate === false ? (inst?.operate_block_reason || '非本人账户启动，已隔离') : ''}
                    onClick={() => startOne(inst.id)}
                  >
                    ▶ 启动
                  </button>
                  <button
                    type="button"
                    className="inst-btn inst-btn-danger"
                    disabled={inst.status === 'stopped' || inst?.can_operate === false}
                    title={inst?.can_operate === false ? (inst?.operate_block_reason || '非本人账户启动，已隔离') : ''}
                    onClick={() => stopOne(inst.id)}
                  >
                    ⏹ 停止
                  </button>
                  <button
                    type="button"
                    className="inst-btn inst-btn-warning"
                    disabled={inst?.can_operate === false}
                    title={inst?.can_operate === false ? (inst?.operate_block_reason || '非本人账户启动，已隔离') : ''}
                    onClick={() => editOne(inst)}
                  >
                    ✏ 修改
                  </button>
                  <button
                    type="button"
                    className="inst-btn inst-btn-ghost"
                    disabled={inst?.can_operate === false}
                    title={inst?.can_operate === false ? (inst?.operate_block_reason || '非本人账户启动，已隔离') : ''}
                    onClick={() => deleteOne(inst.id)}
                  >
                    🗑 删除
                  </button>
                </div>
              </div>
            ))}
          </div>
        ))}
      </div>

      {/* 系统日志区域 */}
      <div className="log-card">
        <div className="log-header" onClick={() => setLogsCollapsed(!logsCollapsed)}>
          <button type="button" className="section-toggle-btn">
            <span className="section-toggle-icon">{logsCollapsed ? '▶' : '▼'}</span>
            <span className="log-title">系统日志</span>
          </button>
          <span className="log-badge">实时更新</span>
          <span className="log-filename">system.log</span>
        </div>
        {!logsCollapsed && (
          <div className="log-window">
            <div className="log-window-bar">
              <span className="log-dot log-dot-red" />
              <span className="log-dot log-dot-yellow" />
              <span className="log-dot log-dot-green" />
            </div>
            <pre className="log-content">{logs}</pre>
          </div>
        )}
      </div>

      {/* 配置弹窗 */}
      {showModal && (
        <div className="modal-overlay" onClick={() => { setShowModal(false); setEditingId(null); setShowKeyEditor(false) }}>
          <div className="modal-dialog" onClick={(e) => e.stopPropagation()}>
            <div className="modal-title">{editingId ? '修改策略参数（保存后自动生效）' : '配置并启动实盘策略'}</div>
            <div className="modal-body">
              {/* 第一行：平台 + 策略 */}
              <div className="modal-row-2">
                <div className="form-item">
                  <label>交易平台</label>
                  <select
                    value={form.platform}
                    onChange={(e) => setField('platform', e.target.value)}
                  >
                    {PLATFORMS.map((p) => (
                      <option key={p.value} value={p.value}>
                        {p.label}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="form-item">
                  <label>交易策略</label>
                  <select
                    value={form.strategy}
                    onChange={(e) => setField('strategy', e.target.value)}
                  >
                    {strategies.map((s) => (
                      <option key={s.value} value={s.value}>
                        {s.label}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              {/* API 密钥配置 / 私钥配置 */}
              {['backpack', 'deepcoin', 'binance'].includes(form.platform) ? (
                <div className="modal-section modal-section-yellow">
                  <div className="modal-section-title">
                    <span>API 密钥配置</span>
                    <small>请从交易所获取 API 密钥，确保权限仅限于交易</small>
                  </div>
                  <div className="modal-row-2">
                    <div className="form-item">
                      <label>API Key</label>
                      <input
                        type="password"
                        value={form.api_key}
                        onChange={(e) => setField('api_key', e.target.value)}
                        placeholder="输入 API Key"
                      />
                    </div>
                    <div className="form-item">
                      <label>API Secret</label>
                      <input
                        type="password"
                        value={form.api_secret}
                        onChange={(e) => setField('api_secret', e.target.value)}
                        placeholder="输入 API Secret"
                      />
                    </div>
                  </div>
                  {form.platform === 'deepcoin' && (
                    <div className="form-item">
                      <label>Passphrase</label>
                      <input
                        type="password"
                        value={form.passphrase}
                        onChange={(e) => setField('passphrase', e.target.value)}
                        placeholder="输入 Passphrase"
                      />
                    </div>
                  )}
                </div>
              ) : (
                <div className="modal-section modal-section-purple">
                  <div className="modal-section-title">
                    <span>私钥配置</span>
                    <small>该平台使用链上钱包，请输入私钥</small>
                  </div>
                  {form.strategy !== 'auto_close' && (
                    <div className="form-item">
                      <label>钱包备注（可选）</label>
                      <input
                        type="text"
                        value={form.wallet_memo}
                        onChange={(e) => setField('wallet_memo', e.target.value)}
                        placeholder="例如：主钱包/测试钱包/服务器A"
                      />
                    </div>
                  )}
                  {!editingId ? (
                    <div className="form-item">
                      <label>Private Key</label>
                      <input
                        type="password"
                        value={form.private_key}
                        onChange={(e) => setField('private_key', e.target.value)}
                        placeholder="输入 0x 开头的私钥"
                      />
                    </div>
                  ) : (
                    <div className="form-item">
                      {!showKeyEditor ? (
                        <button type="button" className="btn-secondary" onClick={() => setShowKeyEditor(true)}>
                          修改私钥
                        </button>
                      ) : (
                        <>
                          <label>Private Key</label>
                          <input
                            type="password"
                            value={form.private_key}
                            onChange={(e) => setField('private_key', e.target.value)}
                            placeholder="输入 0x 开头的私钥"
                          />
                        </>
                      )}
                    </div>
                  )}
                </div>
              )}

              {/* ── 策略专用参数（所有平台通用，在认证块之后独立渲染）── */}

              {/* HYPE自适应做空策略专用参数 */}
              {form.strategy === 'hype_adaptive_short' && (
                <div className="modal-section modal-section-blue">
                  <div className="modal-section-title"><span>策略参数配置</span></div>
                  <div className="form-item">
                    <label>交易对</label>
                    <input value={form.symbol} onChange={(e) => setField('symbol', e.target.value)} placeholder="HYPE/USDC" />
                  </div>
                  <div className="modal-row-2" style={{marginTop: '12px'}}>
                    <div className="form-item">
                      <label>保证金 (USD)</label>
                      <input type="number" min={1} step={1} value={form.size} onChange={(e) => setField('size', Number(e.target.value))} />
                      <small style={{color:'#888',fontSize:'12px'}}>开仓保证金金额</small>
                    </div>
                    <div className="form-item">
                      <label>杠杆倍数</label>
                      <input type="number" min={1} max={100} step={1} value={form.leverage} onChange={(e) => setField('leverage', Number(e.target.value))} />
                      <small style={{color:'#888',fontSize:'12px'}}>实际仓位 = 保证金 × 杠杆</small>
                    </div>
                  </div>
                  <div className="modal-row-2" style={{marginTop: '12px'}}>
                    <div className="form-item">
                      <label>止损比例 (%)</label>
                      <input type="number" min={0.1} max={50} step={0.1} value={form.hype_stop_loss} onChange={(e) => setField('hype_stop_loss', Number(e.target.value))} />
                      <small style={{color:'#888',fontSize:'12px'}}>价格涨超入场价此比例时止损（做空）</small>
                    </div>
                    <div className="form-item">
                      <label>止盈比例 (%)</label>
                      <input type="number" min={0.1} max={50} step={0.1} value={form.hype_take_profit} onChange={(e) => setField('hype_take_profit', Number(e.target.value))} />
                      <small style={{color:'#888',fontSize:'12px'}}>价格跌超入场价此比例时止盈（做空）</small>
                    </div>
                  </div>
                  <div className="form-item" style={{marginTop: '12px'}}>
                    <label>保本触发比例 (%)</label>
                    <input type="number" min={0.1} max={50} step={0.1} value={form.hype_break_even} onChange={(e) => setField('hype_break_even', Number(e.target.value))} />
                    <small style={{color:'#888',fontSize:'12px'}}>盈利达到此比例时，止损移动到入场价（保本）</small>
                  </div>
                </div>
              )}

              {/* 自适应做多策略专用参数 */}
              {form.strategy === 'adaptive_long' && (
                <div className="modal-section modal-section-blue">
                  <div className="modal-section-title"><span>策略参数配置</span></div>
                  <div className="form-item">
                    <label>交易对</label>
                    <input
                      type="text"
                      value={form.adaptive_long_coin}
                      onChange={(e) => setField('adaptive_long_coin', e.target.value.toUpperCase())}
                      placeholder="如: BTC / ETH / HYPE"
                    />
                    <small style={{color:'#888',fontSize:'12px'}}>只响应该币种的 Webhook 信号</small>
                  </div>
                  <div className="form-item" style={{marginTop:'12px'}}>
                    <label>K线级别过滤</label>
                    <select value={form.adaptive_long_timeframe} onChange={(e) => setField('adaptive_long_timeframe', e.target.value)}>
                      <option value="">不限制（响应所有周期信号）</option>
                      <option value="1M">1分钟</option>
                      <option value="3M">3分钟</option>
                      <option value="5M">5分钟</option>
                      <option value="15M">15分钟</option>
                      <option value="30M">30分钟</option>
                      <option value="1H">1小时</option>
                      <option value="2H">2小时</option>
                      <option value="4H">4小时</option>
                      <option value="1D">1日</option>
                    </select>
                    <small style={{color:'#888',fontSize:'12px'}}>只开指定周期的 Webhook 信号才进行开单，TradingView 信号需带 K线级别字段</small>
                  </div>
                  <div className="form-item" style={{marginTop:'12px'}}>
                    <label>AI 评分开单门槛</label>
                    <input
                      type="number"
                      min={0}
                      max={100}
                      step={1}
                      value={form.adaptive_long_min_ai_score}
                      onChange={(e) => setField('adaptive_long_min_ai_score', Number(e.target.value))}
                      placeholder="0"
                    />
                    <small style={{color:'#888',fontSize:'12px'}}>
                      0=不筛选。买入 Webhook 先按信号币种+K线级别在 HL 拉 K 线并 AI 评分，仅当评分≥该值才开单（与钉钉推送无关）
                    </small>
                  </div>
                  {/* 平台认证配置 - Binance 显示 API，Lighter 显示私鑰+账户索引，其他显示私鑰 */}
                  {form.platform === 'binance' ? (
                    <>
                      <div className="form-item" style={{marginTop:'12px'}}>
                        <label>Binance API Key</label>
                        <input type="text" value={form.api_key} onChange={(e) => setField('api_key', e.target.value)} placeholder="输入 Binance API Key" />
                      </div>
                      <div className="form-item" style={{marginTop:'8px'}}>
                        <label>Binance API Secret</label>
                        <input type="password" value={form.api_secret} onChange={(e) => setField('api_secret', e.target.value)} placeholder="输入 Binance API Secret" />
                      </div>
                    </>
                  ) : form.platform === 'lighter' ? (
                    <>
                      <div className="form-item" style={{marginTop:'12px'}}>
                        <label>Lighter 私鑰</label>
                        <input type="password" value={form.private_key} onChange={(e) => setField('private_key', e.target.value)} placeholder="输八 0x 开头的私鑰" />
                        <small style={{color:'#888',fontSize:'12px'}}>链上签名验证，对应 Lighter 钉包私鑰</small>
                      </div>
                      <div className="form-item" style={{marginTop:'8px'}}>
                        <label>Account Index  <small style={{color:'#aaa'}}>可选，默认自动识别</small></label>
                        <input type="number" min={0} step={1} value={form.adaptive_long_account_index} onChange={(e) => setField('adaptive_long_account_index', Number(e.target.value))} />
                        <small style={{color:'#888',fontSize:'12px'}}>若余额为 0，请到 Lighter 平台确认你的 Account Index 填入</small>
                      </div>
                    </>
                  ) : (
                    <div className="form-item" style={{marginTop:'12px'}}>
                      <label>XYZ HIP-3 DEX</label>
                      <input type="text" value="自动识别" disabled style={{color:'#888',background:'#f5f5f5'}} />
                      <small style={{color:'#27ae60',fontSize:'12px'}}>系统自动识别资产所属 DEX：加密资产→Perps，CRCL等美股→XYZ HIP-3 DEX</small>
                    </div>
                  )}
                  <div className="modal-row-2" style={{marginTop: '12px'}}>
                    <div className="form-item">
                      <label>保证金 (USD)</label>
                      <input type="number" min={0.1} step={0.1} value={form.adaptive_long_margin} onChange={(e) => setField('adaptive_long_margin', Number(e.target.value))} />
                      <small style={{color:'#888',fontSize:'12px'}}>开仓保证金金额（仅本策略启动请求使用）</small>
                    </div>
                    <div className="form-item">
                      <label>杠杆倍数</label>
                      <input type="number" min={1} max={100} step={1} value={form.adaptive_long_leverage} onChange={(e) => setField('adaptive_long_leverage', Number(e.target.value))} />
                      <small style={{color:'#888',fontSize:'12px'}}>实际仓位 = 保证金 × 杠杆</small>
                    </div>
                  </div>
                  <div className="modal-row-2" style={{marginTop: '12px'}}>
                    <div className="form-item">
                      <label>止损比例 (%)</label>
                      <input type="number" min={0.1} max={50} step={0.1} value={form.hype_stop_loss} onChange={(e) => setField('hype_stop_loss', Number(e.target.value))} />
                      <small style={{color:'#888',fontSize:'12px'}}>价格跌破入场价此比例时止损（做多）</small>
                    </div>
                    <div className="form-item">
                      <label>止盈比例 (%)</label>
                      <input type="number" min={0.1} max={50} step={0.1} value={form.hype_take_profit} onChange={(e) => setField('hype_take_profit', Number(e.target.value))} />
                      <small style={{color:'#888',fontSize:'12px'}}>价格涨超入场价此比例时止盈（做多）</small>
                    </div>
                  </div>
                  <div className="form-item" style={{marginTop: '12px'}}>
                    <label>保本触发比例 (%)</label>
                    <input type="number" min={0.1} max={50} step={0.1} value={form.hype_break_even} onChange={(e) => setField('hype_break_even', Number(e.target.value))} />
                    <small style={{color:'#888',fontSize:'12px'}}>盈利达到此比例时，止损上移至入场价（保本）</small>
                  </div>
                  <div className="form-item" style={{marginTop: '12px'}}>
                    <label>锁利触发比例 (%)  <small style={{color:'#aaa'}}>可选</small></label>
                    <input type="number" min={0} max={50} step={0.1} value={form.adaptive_long_lock_profit} onChange={(e) => setField('adaptive_long_lock_profit', Number(e.target.value))} placeholder="0=不启用" />
                    <small style={{color:'#888',fontSize:'12px'}}>盈利达到此比例后，将 SL 上移锁住部分利润；0 表示不启用</small>
                  </div>
                  {form.adaptive_long_lock_profit > 0 && (
                    <div className="form-item" style={{marginTop: '12px'}}>
                      <label>锁利 SL 比例 (%)</label>
                      <input type="number" min={0} max={50} step={0.1} value={form.adaptive_long_lock_profit_sl} onChange={(e) => setField('adaptive_long_lock_profit_sl', Number(e.target.value))} />
                      <small style={{color:'#888',fontSize:'12px'}}>锁利触发后，SL = 入场价 × (1 + 此比例)，如 1.5 即入场价的 +1.5%</small>
                    </div>
                  )}
                </div>
              )}

              {/* 自动平仓策略专用参数 */}
              {form.strategy === 'auto_close' && (
                <div className="modal-section modal-section-blue">
                  <div className="modal-section-title"><span>策略参数配置</span></div>
                  <div className="form-item">
                    <label>交易对</label>
                    <input
                      type="text"
                      value={form.auto_close_coin}
                      onChange={(e) => setField('auto_close_coin', e.target.value.toUpperCase())}
                      placeholder="如: BTC / ETH / HYPE"
                    />
                    <small style={{color:'#888',fontSize:'12px'}}>只在收到 sell 信号时对该币种执行平仓；buy 信号会被忽略</small>
                  </div>
                  {form.platform === 'lighter' && (
                    <>
                      <div className="form-item" style={{marginTop:'12px'}}>
                        <label>Account Index</label>
                        <input
                          type="number"
                          min={1}
                          step={1}
                          value={form.auto_close_account_index}
                          onChange={(e) => setField('auto_close_account_index', Number(e.target.value))}
                          placeholder="如 723233"
                        />
                        <small style={{color:'#888',fontSize:'12px'}}>
                          打开 `https://app.lighter.xyz`，进入账户页面，URL 里的数字就是 account_index（如 /explorer/accounts/723233）
                        </small>
                      </div>
                      <div className="form-item" style={{marginTop:'12px'}}>
                        <label>API Key Index <small style={{color:'#aaa'}}>可选</small></label>
                        <input
                          type="number"
                          min={0}
                          step={1}
                          value={form.auto_close_api_key_index}
                          onChange={(e) => setField('auto_close_api_key_index', Number(e.target.value))}
                        />
                        <small style={{color:'#888',fontSize:'12px'}}>默认 2；与 Lighter API Key 的索引一致</small>
                      </div>
                    </>
                  )}
                </div>
              )}

              {/* 自适应做空策略专用参数 */}
              {form.strategy === 'adaptive_short' && (
                <div className="modal-section modal-section-blue">
                  <div className="modal-section-title"><span>策略参数配置</span></div>
                  <div className="form-item">
                    <label>交易对</label>
                    <input
                      type="text"
                      value={form.adaptive_short_coin}
                      onChange={(e) => setField('adaptive_short_coin', e.target.value.toUpperCase())}
                      placeholder="如: BTC / ETH / HYPE"
                    />
                    <small style={{color:'#888',fontSize:'12px'}}>只响应该币种的 Webhook 信号</small>
                  </div>
                  <div className="form-item" style={{marginTop:'12px'}}>
                    <label>K线级别过滤</label>
                    <select value={form.adaptive_short_timeframe} onChange={(e) => setField('adaptive_short_timeframe', e.target.value)}>
                      <option value="">不限制（响应所有周期信号）</option>
                      <option value="1M">1分钟</option>
                      <option value="3M">3分钟</option>
                      <option value="5M">5分钟</option>
                      <option value="15M">15分钟</option>
                      <option value="30M">30分钟</option>
                      <option value="1H">1小时</option>
                      <option value="2H">2小时</option>
                      <option value="4H">4小时</option>
                      <option value="1D">1日</option>
                    </select>
                    <small style={{color:'#888',fontSize:'12px'}}>只开指定周期的 Webhook 信号才进行开单，TradingView 信号需带 K线级别字段</small>
                  </div>
                  {form.platform === 'binance' ? (
                    <>
                      <div className="form-item" style={{marginTop:'12px'}}>
                        <label>Binance API Key</label>
                        <input type="text" value={form.api_key} onChange={(e) => setField('api_key', e.target.value)} placeholder="输入 Binance API Key" />
                      </div>
                      <div className="form-item" style={{marginTop:'8px'}}>
                        <label>Binance API Secret</label>
                        <input type="password" value={form.api_secret} onChange={(e) => setField('api_secret', e.target.value)} placeholder="输入 Binance API Secret" />
                      </div>
                    </>
                  ) : form.platform === 'lighter' ? (
                    <>
                      <div className="form-item" style={{marginTop:'12px'}}>
                        <label>Lighter 私鑰</label>
                        <input type="password" value={form.private_key} onChange={(e) => setField('private_key', e.target.value)} placeholder="输入 0x 开头的私鑰" />
                        <small style={{color:'#888',fontSize:'12px'}}>链上签名验证，对应 Lighter 钱包私鑰</small>
                      </div>
                      <div className="form-item" style={{marginTop:'8px'}}>
                        <label>Account Index  <small style={{color:'#aaa'}}>可选，默认自动识别</small></label>
                        <input type="number" min={0} step={1} value={form.adaptive_short_account_index} onChange={(e) => setField('adaptive_short_account_index', Number(e.target.value))} />
                        <small style={{color:'#888',fontSize:'12px'}}>若余额为 0，请到 Lighter 平台确认你的 Account Index 填入</small>
                      </div>
                    </>
                  ) : (
                    <div className="form-item" style={{marginTop:'12px'}}>
                      <label>XYZ HIP-3 DEX</label>
                      <input type="text" value="自动识别" disabled style={{color:'#888',background:'#f5f5f5'}} />
                      <small style={{color:'#27ae60',fontSize:'12px'}}>系统自动识别资产所属 DEX：加密资产→Perps，CRCL等美股→XYZ HIP-3 DEX</small>
                    </div>
                  )}
                  <div className="modal-row-2" style={{marginTop: '12px'}}>
                    <div className="form-item">
                      <label>保证金 (USD)</label>
                      <input type="number" min={0.1} step={0.1} value={form.adaptive_short_margin} onChange={(e) => setField('adaptive_short_margin', Number(e.target.value))} />
                      <small style={{color:'#888',fontSize:'12px'}}>开仓保证金金额（仅本策略启动请求使用）</small>
                    </div>
                    <div className="form-item">
                      <label>杠杆倍数</label>
                      <input type="number" min={1} max={100} step={1} value={form.adaptive_short_leverage} onChange={(e) => setField('adaptive_short_leverage', Number(e.target.value))} />
                      <small style={{color:'#888',fontSize:'12px'}}>实际仓位 = 保证金 × 杠杆</small>
                    </div>
                  </div>
                  <div className="modal-row-2" style={{marginTop: '12px'}}>
                    <div className="form-item">
                      <label>止损比例 (%)</label>
                      <input type="number" min={0.1} max={50} step={0.1} value={form.hype_stop_loss} onChange={(e) => setField('hype_stop_loss', Number(e.target.value))} />
                      <small style={{color:'#888',fontSize:'12px'}}>价格涨超入场价此比例时止损（做空）</small>
                    </div>
                    <div className="form-item">
                      <label>止盈比例 (%)</label>
                      <input type="number" min={0.1} max={50} step={0.1} value={form.hype_take_profit} onChange={(e) => setField('hype_take_profit', Number(e.target.value))} />
                      <small style={{color:'#888',fontSize:'12px'}}>价格跌超入场价此比例时止盈（做空）</small>
                    </div>
                  </div>
                  <div className="form-item" style={{marginTop: '12px'}}>
                    <label>保本触发比例 (%)</label>
                    <input type="number" min={0.1} max={50} step={0.1} value={form.hype_break_even} onChange={(e) => setField('hype_break_even', Number(e.target.value))} />
                    <small style={{color:'#888',fontSize:'12px'}}>盈利达到此比例时，止损下移至入场价（保本）</small>
                  </div>
                  <div className="form-item" style={{marginTop: '12px'}}>
                    <label>锁利触发比例 (%)  <small style={{color:'#aaa'}}>可选</small></label>
                    <input type="number" min={0} max={50} step={0.1} value={form.adaptive_short_lock_profit} onChange={(e) => setField('adaptive_short_lock_profit', Number(e.target.value))} placeholder="0=不启用" />
                    <small style={{color:'#888',fontSize:'12px'}}>盈利达到此比例后，将 SL 下移锁住部分利润；0 表示不启用</small>
                  </div>
                  {form.adaptive_short_lock_profit > 0 && (
                    <div className="form-item" style={{marginTop: '12px'}}>
                      <label>锁利 SL 比例 (%)</label>
                      <input type="number" min={0} max={50} step={0.1} value={form.adaptive_short_lock_profit_sl} onChange={(e) => setField('adaptive_short_lock_profit_sl', Number(e.target.value))} />
                      <small style={{color:'#888',fontSize:'12px'}}>锁利触发后，SL = 入场价 × (1 - 此比例)，如 1.5 即入场价的 -1.5%</small>
                    </div>
                  )}
                </div>
              )}

              {/* ETH趋势做空策略专用参数 */}
              {form.strategy === 'eth_trend_short' && (
                <div className="modal-section modal-section-blue">
                  <div className="modal-section-title"><span>策略参数配置</span></div>
                  <div className="form-item">
                    <label>交易对</label>
                    <input value={form.symbol} onChange={(e) => setField('symbol', e.target.value)} placeholder="ETH/USDC" />
                  </div>
                  <div className="modal-row-2" style={{marginTop: '12px'}}>
                    <div className="form-item">
                      <label>保证金 (USD)</label>
                      <input type="number" min={1} step={1} value={form.size} onChange={(e) => setField('size', Number(e.target.value))} />
                      <small style={{color:'#888',fontSize:'12px'}}>开仓保证金金额</small>
                    </div>
                    <div className="form-item">
                      <label>杠杆倍数</label>
                      <input type="number" min={1} max={100} step={1} value={form.leverage} onChange={(e) => setField('leverage', Number(e.target.value))} />
                      <small style={{color:'#888',fontSize:'12px'}}>实际仓位 = 保证金 × 杠杆</small>
                    </div>
                  </div>
                  <div className="modal-row-2" style={{marginTop: '12px'}}>
                    <div className="form-item">
                      <label>止损比例 (%)</label>
                      <input type="number" min={0.1} max={50} step={0.1} value={form.hype_stop_loss} onChange={(e) => setField('hype_stop_loss', Number(e.target.value))} />
                      <small style={{color:'#888',fontSize:'12px'}}>价格涨超此比例时止损（做空）</small>
                    </div>
                    <div className="form-item">
                      <label>止盈比例 (%)</label>
                      <input type="number" min={0.1} max={50} step={0.1} value={form.hype_take_profit} onChange={(e) => setField('hype_take_profit', Number(e.target.value))} />
                      <small style={{color:'#888',fontSize:'12px'}}>价格跌超此比例时止盈（做空）</small>
                    </div>
                  </div>
                  <div className="form-item" style={{marginTop: '12px'}}>
                    <label>价格下限 (USD)</label>
                    <input type="number" min={0} step={100} value={form.eth_price_filter} onChange={(e) => setField('eth_price_filter', Number(e.target.value))} />
                    <small style={{color:'#888',fontSize:'12px'}}>ETH 价格低于此值时不开空单（0 = 不限制）</small>
                  </div>
                </div>
              )}

              {/* 交易参数配置 - HYPE/多币种做多/ETH趋势做空/自动平仓策略不显示此区域 */}
              {!['hype_adaptive_short', 'adaptive_long', 'adaptive_short', 'eth_trend_short', 'auto_close'].includes(form.strategy) && (
                <div className="modal-section modal-section-blue">
                <div className="modal-section-title">
                  <span>交易参数配置</span>
                  <small>设置交易品种、保证金、杠杆和止盈止损参数</small>
                </div>
                <div className="modal-row-2">
                  <div className="form-item">
                    <label>交易对</label>
                    <input
                      value={form.symbol}
                      onChange={(e) => setField('symbol', e.target.value)}
                      placeholder="ETH/USDC"
                    />
                  </div>
                  <div className="form-item">
                    <label>下单保证金 (USD)</label>
                    <input
                      type="number"
                      min={1}
                      value={form.size}
                      onChange={(e) => setField('size', Number(e.target.value))}
                    />
                  </div>
                </div>
                <div className="modal-row-2">
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
                    <label>{isDualFreq ? '止盈(保证金收益%)' : '止盈比例 (%)'}</label>
                    <input
                      type="number"
                      min={0}
                      max={isDualFreq ? 300 : 100}
                      step={0.1}
                      value={form.take_profit}
                      onChange={(e) => setField('take_profit', Number(e.target.value))}
                    />
                  </div>
                </div>
                <div className="form-item">
                  <label>{isDualFreq ? '止损(保证金收益%)' : '止损比例 (%)'}</label>
                  <input
                    type="number"
                    min={0}
                    max={isDualFreq ? 200 : 100}
                    step={0.1}
                    value={form.stop_loss}
                    onChange={(e) => setField('stop_loss', Number(e.target.value))}
                  />
                </div>
                </div>
              )}
            </div>

            <div className="dialog-footer">
              <button type="button" className="btn-danger" onClick={() => { setShowModal(false); setEditingId(null); setShowKeyEditor(false) }}>
                取消
              </button>
              <button type="button" className="btn-primary" disabled={launching} onClick={handleLaunch}>
                {launching ? (editingId ? '保存中...' : '启动中...') : (editingId ? '保存并应用' : '确认启动实盘进程')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default Trading
