import React, { useCallback, useEffect, useState } from 'react'
import {
  getPolymarketConfig,
  savePolymarketConfig,
  getPolymarketStatus,
  startPolymarketAlert,
  stopPolymarketAlert,
  testPolymarketDingtalk,
  quotePolymarket,
  quoteAllPolymarket,
} from '../api/polymarketAlert'
import AisPageShell from '../components/AisPageShell'
import './PolymarketAlert.css'

const emptyRule = () => ({
  id: `rule_${Date.now()}`,
  symbol: '',
  target_price: '',
  threshold_pct: 30,
})

const PolymarketAlert = () => {
  const [rules, setRules] = useState([emptyRule()])
  const [pollSec, setPollSec] = useState(60)
  const [cooldownMin, setCooldownMin] = useState(30)
  const [dingtalkConfigured, setDingtalkConfigured] = useState(false)
  const [msg, setMsg] = useState('')
  const [loading, setLoading] = useState(false)
  const [quotes, setQuotes] = useState([])
  const [status, setStatus] = useState({
    running: false,
    last_error: null,
    last_poll_at: null,
    last_push_count: 0,
    last_quotes: [],
    poll_logs: [],
  })

  const buildPayload = useCallback(
    () => ({
      poll_interval_sec: pollSec,
      alert_cooldown_minutes: cooldownMin,
      rules: rules
        .map((r) => ({
          id: r.id,
          symbol: String(r.symbol || '').trim().toUpperCase(),
          target_price: parseFloat(r.target_price),
          threshold_pct: parseFloat(r.threshold_pct) || 30,
          label: r.label || undefined,
        }))
        .filter((r) => r.symbol && r.target_price > 0),
    }),
    [rules, pollSec, cooldownMin]
  )

  const loadConfig = useCallback(async () => {
    try {
      const c = await getPolymarketConfig()
      const rs = c.rules || []
      if (rs.length) {
        setRules(
          rs.map((r) => ({
            id: r.id || emptyRule().id,
            symbol: r.symbol || '',
            target_price: r.target_price ?? '',
            threshold_pct: r.threshold_pct ?? 30,
            label: r.label || '',
          }))
        )
      }
      setPollSec(Number(c.poll_interval_sec) || 60)
      setCooldownMin(Number(c.alert_cooldown_minutes) || 30)
      setDingtalkConfigured(!!c.dingtalk_configured)
    } catch (_) {
      setMsg('加载配置失败')
    }
  }, [])

  const refreshStatus = useCallback(async () => {
    try {
      const s = await getPolymarketStatus()
      setStatus({
        running: !!s.running,
        last_error: s.last_error || null,
        last_poll_at: s.last_poll_at || null,
        last_push_count: Number(s.last_push_count) || 0,
        last_quotes: Array.isArray(s.last_quotes) ? s.last_quotes : [],
        poll_logs: Array.isArray(s.poll_logs) ? s.poll_logs : [],
      })
      if (s.last_quotes?.length) setQuotes(s.last_quotes)
    } catch (_) {}
  }, [])

  const refreshQuotes = useCallback(async () => {
    try {
      const r = await quoteAllPolymarket()
      setQuotes(r.quotes || [])
    } catch (e) {
      setMsg(e?.response?.data?.detail || e?.message || '查询失败')
    }
  }, [])

  useEffect(() => {
    loadConfig()
    refreshStatus()
    const t = setInterval(refreshStatus, 5000)
    return () => clearInterval(t)
  }, [loadConfig, refreshStatus])

  const updateRule = (idx, field, value) => {
    setRules((prev) => prev.map((r, i) => (i === idx ? { ...r, [field]: value } : r)))
  }

  const addRule = () => setRules((prev) => [...prev, emptyRule()])

  const removeRule = (idx) => {
    setRules((prev) => (prev.length <= 1 ? prev : prev.filter((_, i) => i !== idx)))
  }

  const handleSave = async () => {
    setLoading(true)
    setMsg('')
    try {
      const payload = buildPayload()
      if (!payload.rules.length) {
        setMsg('请至少填写一条有效规则（代码 + 价格）')
        return
      }
      await savePolymarketConfig(payload)
      setMsg('配置已保存')
      await loadConfig()
    } catch (e) {
      setMsg(e?.response?.data?.detail || e?.message || '保存失败')
    } finally {
      setLoading(false)
    }
  }

  const handleStart = async () => {
    setLoading(true)
    setMsg('')
    try {
      await savePolymarketConfig(buildPayload())
      const r = await startPolymarketAlert()
      setMsg(r?.message || '已启动')
      await refreshStatus()
    } catch (e) {
      setMsg(e?.response?.data?.detail || e?.message || '启动失败')
    } finally {
      setLoading(false)
    }
  }

  const handleStop = async () => {
    setLoading(true)
    try {
      await stopPolymarketAlert()
      setMsg('已停止')
      await refreshStatus()
    } catch (e) {
      setMsg(e?.message || '停止失败')
    } finally {
      setLoading(false)
    }
  }

  const handleTestDing = async () => {
    setLoading(true)
    try {
      await testPolymarketDingtalk()
      setMsg('钉钉测试已发送')
    } catch (e) {
      setMsg(e?.response?.data?.detail || '钉钉测试失败')
    } finally {
      setLoading(false)
    }
  }

  const handlePreviewRule = async (idx) => {
    const r = rules[idx]
    if (!r.symbol || !r.target_price) {
      setMsg('请先填写代码与目标价')
      return
    }
    setLoading(true)
    try {
      const q = await quotePolymarket({
        symbol: r.symbol,
        target_price: parseFloat(r.target_price),
        threshold_pct: parseFloat(r.threshold_pct) || 30,
      })
      setQuotes((prev) => {
        const rest = prev.filter((x) => x.rule_id !== q.rule_id)
        return [...rest, q]
      })
      if (q.ok) {
        setMsg(
          `${r.symbol} $${r.target_price} · Yes ${q.yes_probability_pct}%` +
            (q.triggered ? '（低于阈值，将提醒）' : '（未低于阈值）')
        )
      } else {
        setMsg(q.error || '未找到市场')
      }
    } catch (e) {
      setMsg(e?.response?.data?.detail || '查询失败')
    } finally {
      setLoading(false)
    }
  }

  const displayQuotes = quotes.length ? quotes : status.last_quotes

  return (
    <AisPageShell
      title="Polymarket 概率提醒"
      subtitle="输入股票代码、目标价与概率阈值。当 Polymarket 上对应「触及该价位」市场的 Yes 概率低于阈值时，通过钉钉推送（复用自选快讯 Webhook，关键词「提醒」）。"
    >
      <section className="qpt-panel">
        <h2>监控规则</h2>
        {rules.map((r, idx) => (
          <div className="pma-rule-row" key={r.id}>
            <div className="qpt-field pma-field-sm">
              <label>代码</label>
              <input
                type="text"
                placeholder="MSFT"
                value={r.symbol}
                onChange={(e) => updateRule(idx, 'symbol', e.target.value)}
              />
            </div>
            <div className="qpt-field pma-field-sm">
              <label>目标价 ($)</label>
              <input
                type="number"
                placeholder="450"
                value={r.target_price}
                onChange={(e) => updateRule(idx, 'target_price', e.target.value)}
              />
            </div>
            <div className="qpt-field pma-field-sm">
              <label>低于提醒 (%)</label>
              <input
                type="number"
                min="0"
                max="100"
                value={r.threshold_pct}
                onChange={(e) => updateRule(idx, 'threshold_pct', e.target.value)}
              />
            </div>
            <div className="pma-rule-actions">
              <button type="button" className="qpt-btn ghost" onClick={() => handlePreviewRule(idx)}>
                查询
              </button>
              <button type="button" className="qpt-btn ghost" onClick={() => removeRule(idx)}>
                删除
              </button>
            </div>
          </div>
        ))}
        <div className="qpt-actions">
          <button type="button" className="qpt-btn ghost" onClick={addRule}>
            + 添加规则
          </button>
        </div>
      </section>

      <section className="qpt-panel">
        <h2>轮询设置</h2>
        <div className="pma-row">
          <div className="qpt-field pma-field-sm">
            <label>轮询间隔（秒）</label>
            <input
              type="number"
              min="30"
              max="600"
              value={pollSec}
              onChange={(e) => setPollSec(Number(e.target.value) || 60)}
            />
          </div>
          <div className="qpt-field pma-field-sm">
            <label>重复提醒冷却（分钟）</label>
            <input
              type="number"
              min="5"
              value={cooldownMin}
              onChange={(e) => setCooldownMin(Number(e.target.value) || 30)}
            />
          </div>
        </div>
        <p className="qpt-hint">
          钉钉：{dingtalkConfigured ? '已配置（与自选快讯共用 Webhook）' : '未配置，请在 data/stock_news_alert_config.json 设置'}
        </p>
        <div className="qpt-actions">
          <button type="button" className="qpt-btn ghost" disabled={loading} onClick={handleSave}>
            保存配置
          </button>
          <button type="button" className="qpt-btn primary" disabled={loading} onClick={handleStart}>
            保存并启动
          </button>
          <button type="button" className="qpt-btn ghost" disabled={loading} onClick={handleStop}>
            停止
          </button>
          <button type="button" className="qpt-btn ghost" disabled={loading} onClick={handleTestDing}>
            测试钉钉
          </button>
          <button type="button" className="qpt-btn ghost" disabled={loading} onClick={refreshQuotes}>
            刷新全部报价
          </button>
        </div>
      </section>

      {msg && <p className="qpt-msg">{msg}</p>}

      <section className="qpt-panel">
        <h2>
          运行状态
          <span className={`qpt-badge ${status.running ? 'on' : 'off'}`}>
            {status.running ? '运行中' : '已停止'}
          </span>
        </h2>
        <p className="qpt-hint">
          上次轮询：{status.last_poll_at || '—'} · 本轮推送：{status.last_push_count}
          {status.last_error ? ` · 错误：${status.last_error}` : ''}
        </p>
      </section>

      {displayQuotes?.length > 0 && (
        <section className="qpt-panel">
          <h2>当前概率</h2>
          <div className="qpt-table-wrap">
          <table className="qpt-table">
            <thead>
              <tr>
                <th>标的</th>
                <th>价位</th>
                <th>Yes %</th>
                <th>阈值</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              {displayQuotes.map((q) => (
                <tr key={q.rule_id || `${q.symbol}-${q.target_price}`}>
                  <td>{q.symbol}</td>
                  <td>${q.target_price}</td>
                  <td>{q.ok ? `${q.yes_probability_pct}%` : '—'}</td>
                  <td>{q.threshold_pct}%</td>
                  <td>
                    {!q.ok && <span className="pma-err">{q.error}</span>}
                    {q.ok && (
                      <span className={q.triggered ? 'pma-ok' : 'pma-warn'}>
                        {q.triggered ? '低于阈值' : '未低于'}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </section>
      )}

      {status.poll_logs?.length > 0 && (
        <section className="qpt-panel">
          <h2>轮询日志</h2>
          <ul className="pma-logs">
            {status.poll_logs.slice(0, 8).map((log, i) => (
              <li key={i}>{log.message || JSON.stringify(log)}</li>
            ))}
          </ul>
        </section>
      )}
    </AisPageShell>
  )
}

export default PolymarketAlert
