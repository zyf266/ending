import React, { useEffect, useState } from 'react'
import {
  getStrategies,
  getInstances,
  launchStrategy,
  stopInstance,
  getLogs,
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

  useEffect(() => {
    let t1, t2
    const load = async () => {
      try {
        const res = await getStrategies()
        setStrategies(res.strategies || [])
      } catch (_) {}
      await refresh()
      t1 = setInterval(refresh, 5000)
      t2 = setInterval(refreshLogs, 10000)
    }
    load()
    return () => {
      if (t1) clearInterval(t1)
      if (t2) clearInterval(t2)
    }
  }, [])

  const handleLaunch = async () => {
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

  return (
    <div className="page trading-page">
      <div className="header-row">
        <h2>实盘控制中心</h2>
        <button type="button" className="btn-primary" onClick={() => setShowModal(true)}>
          + 增加新策略
        </button>
      </div>

      <div className="instances-card card-block">
        <div className="card-block-header">运行中的策略实例 (ACTIVE INSTANCES)</div>
        {instances.length === 0 ? (
          <div className="empty">暂无运行中的策略，请增加新策略</div>
        ) : (
          <div className="instance-grid">
            {instances.map((inst) => (
              <div key={inst.id} className="instance-card">
                <div className="inst-info">
                  <div className="tags">
                    <span className={`tag ${inst.platform === 'ostium' ? 'tag-warning' : ''}`}>
                      {(inst.platform || '').toUpperCase()}
                    </span>
                    <span className={inst.status === 'registering' ? 'status reg' : 'status run'}>
                      {inst.status === 'registering' ? '● REGISTERING' : '● RUNNING'}
                    </span>
                  </div>
                  <h3>{inst.strategy_name}</h3>
                  <p>💹 {inst.symbol}</p>
                  <p className="meta">🕒 {inst.start_time} | PID: {inst.pid}</p>
                </div>
                <div className="inst-actions">
                  <div className="balance">
                    <p>💰 账户余额</p>
                    <h2>{inst.balance} USD</h2>
                  </div>
                  <button type="button" className="btn-danger-sm" onClick={() => stopOne(inst.id)}>
                    停止
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="log-card card-block">
        <div className="card-block-header">终端实时输出日志 (SYSTEM LOGS)</div>
        <pre className="log-content">{logs}</pre>
      </div>

      {showModal && (
        <div className="modal-overlay" onClick={() => setShowModal(false)}>
          <div className="modal-dialog" onClick={(e) => e.stopPropagation()}>
            <div className="modal-title">配置并启动实盘策略</div>
            <div className="modal-body">
              <div className="form-item">
                <label>交易平台</label>
                <select
                  value={form.platform}
                  onChange={(e) => setField('platform', e.target.value)}
                  style={{ width: '100%' }}
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
                  style={{ width: '100%' }}
                >
                  {strategies.map((s) => (
                    <option key={s.value} value={s.value}>
                      {s.label}
                    </option>
                  ))}
                </select>
              </div>
              {['backpack', 'deepcoin'].includes(form.platform) && (
                <>
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
                </>
              )}
              {!['backpack', 'deepcoin'].includes(form.platform) && (
                <div className="form-item">
                  <label>Private Key</label>
                  <input
                    type="password"
                    value={form.private_key}
                    onChange={(e) => setField('private_key', e.target.value)}
                    placeholder="输入 0x 开头的私钥"
                  />
                </div>
              )}
              <div className="form-item">
                <label>交易对</label>
                <input
                  value={form.symbol}
                  onChange={(e) => setField('symbol', e.target.value)}
                  placeholder="ETH/USDC"
                />
              </div>
              <div className="form-item">
                <label>下单保证金</label>
                <input
                  type="number"
                  min={1}
                  value={form.size}
                  onChange={(e) => setField('size', Number(e.target.value))}
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
