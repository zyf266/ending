import React, { useEffect, useState } from 'react'
import {
  getStrategies,
  getInstances,
  launchStrategy,
  stopInstance,
  getLogs,
  getHypeStatus,
  toggleHypeStrategy,
  startHypeStrategy,
  startEthTrendShort,
  startAdaptiveLong,
} from '../api/trading'
import './Trading.css'

const PLATFORMS = [
  { label: 'Backpack', value: 'backpack' },
  { label: 'Deepcoin', value: 'deepcoin' },
  { label: 'Ostium', value: 'ostium' },
  { label: 'Hyperliquid', value: 'hyperliquid' },
]

const Trading = () => {
  const [showModal, setShowModal] = useState(false)
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
    // ETH趋势做空 / HYPE做空 / 自适应做多 固定平台为 hyperliquid
    if (name === 'strategy' && ['eth_trend_short', 'hype_adaptive_short', 'adaptive_long'].includes(value)) {
      setForm((prev) => ({ ...prev, platform: 'hyperliquid' }))
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

  const handleLaunch = async () => {
    // 【HYPE自适应做空策略】使用独立的启动端点
    if (form.strategy === 'hype_adaptive_short') {
      if (!form.private_key) {
        alert('请输入 Hyperliquid 私钥')
        return
      }
      setLaunching(true)
      try {
        // 从交易对中提取币种（如 ETH/USDC -> ETH）
        const symbol = form.symbol.split('/')[0].split('_')[0] || 'ETH'
        const res = await startHypeStrategy(symbol, form.private_key, {
          stop_loss_pct: form.hype_stop_loss / 100,
          take_profit_pct: form.hype_take_profit / 100,
          break_even_pct: form.hype_break_even / 100,
          margin_amount: form.size,
          leverage: form.leverage,
        })
        alert(res.message || 'HYPE做空策略启动成功')
        setShowModal(false)
        await refresh()
        await refreshHypeStatus()
      } catch (e) {
        alert(e?.response?.data?.detail || '启动失败')
      } finally {
        setLaunching(false)
      }
      return
    }

    // 【自适应做多策略】Webhook驱动，无需币种
    if (form.strategy === 'adaptive_long') {
      setLaunching(true)
      try {
        const res = await startAdaptiveLong({
          private_key:     form.private_key || undefined,
          margin_amount:   form.size,
          leverage:        form.leverage,
          stop_loss_pct:   form.hype_stop_loss / 100,
          take_profit_pct: form.hype_take_profit / 100,
          break_even_pct:  form.hype_break_even / 100,
        })
        alert(res.message || '自适应做多策略启动成功')
        setShowModal(false)
        await refresh()
      } catch (e) {
        alert(e?.response?.data?.detail || '启动失败')
      } finally {
        setLaunching(false)
      }
      return
    }

    // 【ETH趋势做空策略】使用独立的启动端点
    if (form.strategy === 'eth_trend_short') {
      if (!form.private_key) {
        alert('请输入 Hyperliquid 私钥')
        return
      }
      setLaunching(true)
      try {
        const res = await startEthTrendShort({
          symbol:           form.symbol.split('/')[0].split('_')[0] || 'ETH',
          private_key:      form.private_key,
          margin_amount:    form.size,
          leverage:         form.leverage,
          stop_loss_pct:    form.hype_stop_loss / 100,
          take_profit_pct:  form.hype_take_profit / 100,
          price_filter_min: form.eth_price_filter,
        })
        alert(res.message || 'ETH趋势做空策略启动成功')
        setShowModal(false)
        await refresh()
      } catch (e) {
        alert(e?.response?.data?.detail || '启动失败')
      } finally {
        setLaunching(false)
      }
      return
    }

    // 其他策略使用通用启动逻辑
    if (['backpack', 'deepcoin'].includes(form.platform)) {
      if (!form.api_key || !form.api_secret) {
        alert('请输入 API Key 和 Secret')
        return
      }
    } else {
      if (!form.private_key) {
        alert('请输入私钥')
        return
      }
    }
    setLaunching(true)
    try {
      const res = await launchStrategy({
        platform: form.platform,
        strategy: form.strategy,
        symbol: form.symbol,
        size: form.size,
        leverage: form.leverage,
        take_profit: form.take_profit,
        stop_loss: form.stop_loss,
        api_key: form.api_key || undefined,
        api_secret: form.api_secret || undefined,
        passphrase: form.passphrase || undefined,
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
      {/* 顶部四个统计卡片（和 src_trading 一致） */}
      <div className="trading-stats-row">
        <div className="trading-stat-card trading-stat-blue">
          <div className="trading-stat-icon">📶</div>
          <div className="trading-stat-main">
            <div className="trading-stat-title">运行中策略</div>
            <div className="trading-stat-value">{instances.length}</div>
            <div className="trading-stat-sub">个活跃实例</div>
          </div>
        </div>
        <div className="trading-stat-card trading-stat-green">
          <div className="trading-stat-icon">💵</div>
          <div className="trading-stat-main">
            <div className="trading-stat-title">总资产</div>
            <div className="trading-stat-value">$24,567</div>
            <div className="trading-stat-sub">+5.23% 今日</div>
          </div>
        </div>
        <div className="trading-stat-card trading-stat-purple">
          <div className="trading-stat-icon">📈</div>
          <div className="trading-stat-main">
            <div className="trading-stat-title">累计收益</div>
            <div className="trading-stat-value">+18.5%</div>
            <div className="trading-stat-sub">本月表现</div>
          </div>
        </div>
        <div className="trading-stat-card trading-stat-orange">
          <div className="trading-stat-icon">🎯</div>
          <div className="trading-stat-main">
            <div className="trading-stat-title">胜率</div>
            <div className="trading-stat-value">67.8%</div>
            <div className="trading-stat-sub">最近30笔</div>
          </div>
        </div>
      </div>

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
                    <span className={inst.status === 'registering' ? 'status reg' : 'status run'}>
                      <span className="status-dot" />
                      {inst.status === 'registering' ? 'REGISTERING' : 'RUNNING'}
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
                      disabled={togglingHype}
                      onClick={() => toggleHype(inst.id, !getHypeEnabled(inst.id))}
                    >
                      {getHypeEnabled(inst.id) ? '⏸ 暂停策略' : '▶ 启用策略'}
                    </button>
                  )}
                  <button type="button" className="inst-btn inst-btn-danger" onClick={() => stopOne(inst.id)}>
                    ⏹ 停止
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
        <div className="modal-overlay" onClick={() => setShowModal(false)}>
          <div className="modal-dialog" onClick={(e) => e.stopPropagation()}>
            <div className="modal-title">配置并启动实盘策略</div>
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
              {['backpack', 'deepcoin'].includes(form.platform) ? (
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
                  <div className="form-item">
                    <label>Private Key</label>
                    <input
                      type="password"
                      value={form.private_key}
                      onChange={(e) => setField('private_key', e.target.value)}
                      placeholder="输入 0x 开头的私钥"
                    />
                  </div>
                  {/* HYPE策略专用参数 - 只在HYPE策略时显示 */}
                  {form.strategy === 'hype_adaptive_short' && (
                    <>
                      <div className="form-item" style={{marginTop: '12px'}}>
                        <label>交易对</label>
                        <input
                          value={form.symbol}
                          onChange={(e) => setField('symbol', e.target.value)}
                          placeholder="HYPE/USDC"
                        />
                      </div>
                      <div className="modal-row-2" style={{marginTop: '12px'}}>
                        <div className="form-item">
                          <label>保证金 (USD)</label>
                          <input
                            type="number"
                            min={1}
                            step={1}
                            value={form.size}
                            onChange={(e) => setField('size', Number(e.target.value))}
                          />
                          <small style={{color: '#888', fontSize: '12px'}}>开仓保证金金额</small>
                        </div>
                        <div className="form-item">
                          <label>杠杆倍数</label>
                          <input
                            type="number"
                            min={1}
                            max={100}
                            step={1}
                            value={form.leverage}
                            onChange={(e) => setField('leverage', Number(e.target.value))}
                          />
                          <small style={{color: '#888', fontSize: '12px'}}>实际仓位 = 保证金 × 杠杆</small>
                        </div>
                      </div>
                      <div className="modal-row-2" style={{marginTop: '12px'}}>
                        <div className="form-item">
                          <label>止损比例 (%)</label>
                          <input
                            type="number"
                            min={0.1}
                            max={50}
                            step={0.1}
                            value={form.hype_stop_loss}
                            onChange={(e) => setField('hype_stop_loss', Number(e.target.value))}
                          />
                          <small style={{color: '#888', fontSize: '12px'}}>价格涨超入场价此比例时止损</small>
                        </div>
                        <div className="form-item">
                          <label>止盈比例 (%)</label>
                          <input
                            type="number"
                            min={0.1}
                            max={50}
                            step={0.1}
                            value={form.hype_take_profit}
                            onChange={(e) => setField('hype_take_profit', Number(e.target.value))}
                          />
                          <small style={{color: '#888', fontSize: '12px'}}>价格跌超入场价此比例时止盈</small>
                        </div>
                      </div>
                      <div className="form-item" style={{marginTop: '12px'}}>
                        <label>保本触发比例 (%)</label>
                        <input
                          type="number"
                          min={0.1}
                          max={50}
                          step={0.1}
                          value={form.hype_break_even}
                          onChange={(e) => setField('hype_break_even', Number(e.target.value))}
                        />
                        <small style={{color: '#888', fontSize: '12px'}}>盈利达到此比例时，止损移动到入场价（保本）</small>
                      </div>

                    </>
                  )}

                  {/* 自适应做多策略专用参数 - 无币种输入，币种从 Webhook 信号中自动获取 */}
                  {form.strategy === 'adaptive_long' && (
                    <>
                      <div className="modal-row-2" style={{marginTop: '12px'}}>
                        <div className="form-item">
                          <label>保证金 (USD)</label>
                          <input
                            type="number"
                            min={1}
                            step={1}
                            value={form.size}
                            onChange={(e) => setField('size', Number(e.target.value))}
                          />
                          <small style={{color: '#888', fontSize: '12px'}}>开仓保证金金额</small>
                        </div>
                        <div className="form-item">
                          <label>杠杆倍数</label>
                          <input
                            type="number"
                            min={1}
                            max={100}
                            step={1}
                            value={form.leverage}
                            onChange={(e) => setField('leverage', Number(e.target.value))}
                          />
                          <small style={{color: '#888', fontSize: '12px'}}>实际仓位 = 保证金 × 杠杆</small>
                        </div>
                      </div>
                      <div className="modal-row-2" style={{marginTop: '12px'}}>
                        <div className="form-item">
                          <label>止损比例 (%)</label>
                          <input
                            type="number"
                            min={0.1}
                            max={50}
                            step={0.1}
                            value={form.hype_stop_loss}
                            onChange={(e) => setField('hype_stop_loss', Number(e.target.value))}
                          />
                          <small style={{color: '#888', fontSize: '12px'}}>价格跌破入场价此比例时止损（做多）</small>
                        </div>
                        <div className="form-item">
                          <label>止盈比例 (%)</label>
                          <input
                            type="number"
                            min={0.1}
                            max={50}
                            step={0.1}
                            value={form.hype_take_profit}
                            onChange={(e) => setField('hype_take_profit', Number(e.target.value))}
                          />
                          <small style={{color: '#888', fontSize: '12px'}}>价格涨超入场价此比例时止盈（做多）</small>
                        </div>
                      </div>
                      <div className="form-item" style={{marginTop: '12px'}}>
                        <label>保本触发比例 (%)</label>
                        <input
                          type="number"
                          min={0.1}
                          max={50}
                          step={0.1}
                          value={form.hype_break_even}
                          onChange={(e) => setField('hype_break_even', Number(e.target.value))}
                        />
                        <small style={{color: '#888', fontSize: '12px'}}>盈利达到此比例时，止损上移至入场价（保本）</small>
                      </div>
                    </>
                  )}

                  {/* ETH趋势做空策略专用参数 */}
                  {form.strategy === 'eth_trend_short' && (
                    <>
                      <div className="form-item" style={{marginTop: '12px'}}>
                        <label>交易对</label>
                        <input
                          value={form.symbol}
                          onChange={(e) => setField('symbol', e.target.value)}
                          placeholder="ETH/USDC"
                        />
                      </div>
                      <div className="modal-row-2" style={{marginTop: '12px'}}>
                        <div className="form-item">
                          <label>保证金 (USD)</label>
                          <input
                            type="number" min={1} step={1}
                            value={form.size}
                            onChange={(e) => setField('size', Number(e.target.value))}
                          />
                          <small style={{color: '#888', fontSize: '12px'}}>开仓保证金金额</small>
                        </div>
                        <div className="form-item">
                          <label>杠杆倍数</label>
                          <input
                            type="number" min={1} max={100} step={1}
                            value={form.leverage}
                            onChange={(e) => setField('leverage', Number(e.target.value))}
                          />
                          <small style={{color: '#888', fontSize: '12px'}}>实际仓位 = 保证金 × 杠杆</small>
                        </div>
                      </div>
                      <div className="modal-row-2" style={{marginTop: '12px'}}>
                        <div className="form-item">
                          <label>止损比例 (%)</label>
                          <input
                            type="number" min={0.1} max={50} step={0.1}
                            value={form.hype_stop_loss}
                            onChange={(e) => setField('hype_stop_loss', Number(e.target.value))}
                          />
                          <small style={{color: '#888', fontSize: '12px'}}>价格涨超此比例时止损（做空）</small>
                        </div>
                        <div className="form-item">
                          <label>止盈比例 (%)</label>
                          <input
                            type="number" min={0.1} max={50} step={0.1}
                            value={form.hype_take_profit}
                            onChange={(e) => setField('hype_take_profit', Number(e.target.value))}
                          />
                          <small style={{color: '#888', fontSize: '12px'}}>价格跌超此比例时止盈（做空）</small>
                        </div>
                      </div>
                      <div className="form-item" style={{marginTop: '12px'}}>
                        <label>价格下限 (USD)</label>
                        <input
                          type="number" min={0} step={100}
                          value={form.eth_price_filter}
                          onChange={(e) => setField('eth_price_filter', Number(e.target.value))}
                        />
                        <small style={{color: '#888', fontSize: '12px'}}>ETH 价格低于此值时不开空单（0 = 不限制）</small>
                      </div>
                    </>
                  )}
                </div>
              )}

              {/* 交易参数配置 - HYPE/自适应做多/ETH趋势做空策略不显示此区域 */}
              {!['hype_adaptive_short', 'adaptive_long', 'eth_trend_short'].includes(form.strategy) && (
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
              <button type="button" className="btn-danger" onClick={() => setShowModal(false)}>
                取消
              </button>
              <button type="button" className="btn-primary" disabled={launching} onClick={handleLaunch}>
                {launching ? '启动中...' : '确认启动实盘进程'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default Trading