import React, { useCallback, useEffect, useState } from 'react'
import {
  getStockNewsConfig,
  saveStockNewsConfig,
  getStockNewsStatus,
  startStockNewsAlert,
  stopStockNewsAlert,
  testStockNewsDingtalk,
  probeJin10,
  getSourceCatalog,
  getProbeSources,
  getFeedsPreview,
  removeStockNewsWatch,
} from '../api/stockNewsAlert'
import AisPageShell from '../components/AisPageShell'
import './StockNewsAlert.css'

const splitLines = (s) =>
  String(s || '')
    .split(/[\n,，;；]+/)
    .map((x) => x.trim())
    .filter(Boolean)

const DEFAULT_SOURCE_KEYS = ['jin10', 'ths', 'eastmoney', 'sina', 'futu', 'yahoo']

const StockNewsAlert = () => {
  const [watchText, setWatchText] = useState('')
  const [pollSec, setPollSec] = useState(30)
  const [onlyMaterial, setOnlyMaterial] = useState(true)
  const [onlyExtraImpact, setOnlyExtraImpact] = useState(false)
  const [extraKw, setExtraKw] = useState('')
  const [dingtalkConfigured, setDingtalkConfigured] = useState(false)
  const [newsSources, setNewsSources] = useState([...DEFAULT_SOURCE_KEYS])
  const [sourceLabels, setSourceLabels] = useState({})
  const [msg, setMsg] = useState('')
  const [loading, setLoading] = useState(false)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [preview, setPreview] = useState(null)
  const [probeSources, setProbeSources] = useState(null)
  const [status, setStatus] = useState({
    running: false,
    last_error: null,
    last_poll_at: null,
    last_push_count: 0,
    last_poll_summary: null,
    poll_logs: [],
    log_file: 'log/stock_news_alert.log',
    monitor_pool: [],
  })

  const buildPayload = useCallback(
    () => ({
      watch_names: splitLines(watchText),
      poll_interval_sec: pollSec,
      only_material: onlyMaterial,
      only_extra_impact_keywords: onlyExtraImpact,
      extra_impact_keywords: splitLines(extraKw),
      news_sources: newsSources.length ? newsSources : [...DEFAULT_SOURCE_KEYS],
    }),
    [watchText, pollSec, onlyMaterial, onlyExtraImpact, extraKw, newsSources]
  )

  const loadConfig = useCallback(async () => {
    try {
      const [c, cat] = await Promise.all([
        getStockNewsConfig(),
        getSourceCatalog().catch(() => ({})),
      ])
      const names = c.watch_names || []
      if (!c.running) {
        setWatchText(Array.isArray(names) ? names.join('\n') : String(names))
      } else {
        setWatchText('')
      }
      setPollSec(Number(c.poll_interval_sec) || 30)
      setOnlyMaterial(c.only_material !== false)
      setOnlyExtraImpact(!!c.only_extra_impact_keywords)
      const extra = c.extra_impact_keywords || []
      setExtraKw(Array.isArray(extra) ? extra.join(',') : String(extra))
      setDingtalkConfigured(!!c.dingtalk_configured)
      const ns = c.news_sources
      if (Array.isArray(ns) && ns.length) {
        setNewsSources(ns.map((x) => String(x).toLowerCase()).filter((k) => DEFAULT_SOURCE_KEYS.includes(k)))
      } else {
        setNewsSources([...DEFAULT_SOURCE_KEYS])
      }
      if (cat?.labels) setSourceLabels(cat.labels)
    } catch (_) {
      setMsg('加载配置失败')
    }
  }, [])

  const refreshStatus = useCallback(async () => {
    try {
      const s = await getStockNewsStatus()
      setStatus({
        running: !!s.running,
        last_error: s.last_error || null,
        last_poll_at: s.last_poll_at || null,
        last_push_count: Number(s.last_push_count) || 0,
        last_poll_summary: s.last_poll_summary || null,
        poll_logs: Array.isArray(s.poll_logs) ? s.poll_logs : [],
        log_file: s.log_file || 'log/stock_news_alert.log',
        monitor_pool: Array.isArray(s.monitor_pool) ? s.monitor_pool : [],
      })
    } catch (_) {}
  }, [])

  const refreshProbe = useCallback(async () => {
    try {
      const r = await getProbeSources()
      setProbeSources(r?.sources || null)
    } catch (_) {
      setProbeSources(null)
    }
  }, [])

  const loadPreview = useCallback(async () => {
    setPreviewLoading(true)
    try {
      const r = await getFeedsPreview({ per_source: 10 })
      setPreview(r)
      if (r?.sources) setProbeSources(r.sources)
    } catch (e) {
      setMsg(e?.response?.data?.detail || e?.message || '加载预览失败')
    } finally {
      setPreviewLoading(false)
    }
  }, [])

  useEffect(() => {
    loadConfig()
    refreshStatus()
    refreshProbe()
    const t = setInterval(refreshStatus, 5000)
    return () => clearInterval(t)
  }, [loadConfig, refreshStatus, refreshProbe])

  const toggleSource = (key) => {
    setNewsSources((prev) => {
      if (prev.includes(key)) {
        const next = prev.filter((k) => k !== key)
        return next.length ? next : [key]
      }
      return [...prev, key].sort((a, b) => DEFAULT_SOURCE_KEYS.indexOf(a) - DEFAULT_SOURCE_KEYS.indexOf(b))
    })
  }

  const labelFor = (key) => sourceLabels[key] || key

  const formatPollStats = (stats) => {
    if (!stats || typeof stats !== 'object') return ''
    const parts = []
    if (stats.skipped_pushed != null) parts.push(`已推送过 ${stats.skipped_pushed}`)
    if (stats.skipped_no_watch != null) parts.push(`未命中关键词 ${stats.skipped_no_watch}`)
    if (stats.skipped_not_material != null) parts.push(`非重要快讯 ${stats.skipped_not_material}`)
    if (stats.skipped_not_fresh != null) parts.push(`非最新 ${stats.skipped_not_fresh}`)
    if (stats.skipped_bootstrap_seed != null) parts.push(`首轮已见 ${stats.skipped_bootstrap_seed}`)
    if (stats.skipped_similar != null) parts.push(`内容相似 ${stats.skipped_similar}`)
    if (stats.matched != null) parts.push(`新命中 ${stats.matched}`)
    if (stats.pushed_ok != null) parts.push(`已推送 ${stats.pushed_ok}`)
    return parts.join(' · ')
  }

  const onSave = async () => {
    setLoading(true)
    setMsg('')
    try {
      await saveStockNewsConfig(buildPayload())
      setMsg('已保存配置')
      await refreshProbe()
    } catch (e) {
      setMsg(e?.response?.data?.detail || e?.message || '保存失败')
    } finally {
      setLoading(false)
    }
  }

  const formatMonitorRules = (item) => {
    const parts = []
    parts.push(`轮询 ${item.poll_interval_sec || pollSec}s`)
    if (item.only_material !== false) parts.push('仅重要快讯')
    if (item.only_extra_impact_keywords) parts.push('影响面仅自定义词')
    const extra = item.extra_impact_keywords || []
    if (extra.length) parts.push(`自定义影响词 ${extra.join('、')}`)
    return parts.join(' · ')
  }

  const onStart = async () => {
    setLoading(true)
    setMsg('')
    try {
      const payload = buildPayload()
      const names = payload.watch_names
      const poolCount = (status.monitor_pool || []).length
      if (!names.length && poolCount === 0) {
        setMsg('请先填写自选关键词')
        setLoading(false)
        return
      }
      await saveStockNewsConfig(payload)
      await startStockNewsAlert({ watch_names: names })
      setWatchText('')
      setMsg(status.running && names.length ? '已追加监控关键词' : '已启动监控')
      await refreshStatus()
    } catch (e) {
      setMsg(
        typeof e?.response?.data?.detail === 'string'
          ? e.response.data.detail
          : e?.message || '启动失败'
      )
    } finally {
      setLoading(false)
    }
  }

  const onRemoveWatch = async (keyword) => {
    if (!keyword) return
    setLoading(true)
    setMsg('')
    try {
      const r = await removeStockNewsWatch(keyword)
      setMsg(r?.message || `已移除 ${keyword}`)
      await refreshStatus()
    } catch (e) {
      setMsg(
        typeof e?.response?.data?.detail === 'string'
          ? e.response.data.detail
          : e?.message || '移除失败'
      )
    } finally {
      setLoading(false)
    }
  }

  const poolItems = status.monitor_pool || []
  const recentHitKeywords = new Set(
    poolItems.filter((item) => item.last_push?.at).map((item) => item.keyword)
  )

  const onStop = async () => {
    setLoading(true)
    try {
      await stopStockNewsAlert()
      setMsg('已停止')
      await refreshStatus()
    } catch (e) {
      setMsg(e?.message || '停止失败')
    } finally {
      setLoading(false)
    }
  }

  const onTestDing = async () => {
    setLoading(true)
    setMsg('')
    try {
      await saveStockNewsConfig(buildPayload())
      await testStockNewsDingtalk()
      setMsg('钉钉测试消息已发送')
    } catch (e) {
      setMsg(
        typeof e?.response?.data?.detail === 'string'
          ? e.response.data.detail
          : e?.message || '测试失败'
      )
    } finally {
      setLoading(false)
    }
  }

  const onProbe = async () => {
    setLoading(true)
    setMsg('')
    try {
      const r = await probeJin10()
      if (r.ok) setMsg(`金十接口正常，本页拉取 ${r.count} 条`)
      else setMsg(`金十接口异常：${r.error || '未知'}`)
    } catch (e) {
      setMsg(e?.message || '探测失败')
    } finally {
      setLoading(false)
    }
  }

  const onProbeAll = async () => {
    setLoading(true)
    setMsg('')
    try {
      await saveStockNewsConfig(buildPayload())
      await refreshProbe()
      const r = await getProbeSources()
      const src = r?.sources || {}
      setProbeSources(src)
      const parts = DEFAULT_SOURCE_KEYS.map((k) => {
        const o = src[k]
        if (!o?.enabled) return `${labelFor(k)}: 未启用`
        return o.ok ? `${labelFor(k)}: ${o.count}条` : `${labelFor(k)}: 失败`
      })
      setMsg(parts.join(' ｜ '))
    } catch (e) {
      setMsg(e?.message || '探测失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <AisPageShell
      title="自选重大快讯（多源聚合）"
      subtitle="聚合金十、同花顺、东方财富、新浪、富途等公开快讯接口；命中自选关键词且符合「重要快讯」规则时钉钉推送。数据仅供个人研究备忘，接口可能变更，不构成投资建议。钉钉须使用 POST 完整 Webhook。"
    >
      <section className="qpt-panel">
        <h2>数据源（勾选参与监控与预览）</h2>
        <div className="sna-source-grid">
          {DEFAULT_SOURCE_KEYS.map((key) => (
            <label key={key} className="sna-source-item">
              <input
                type="checkbox"
                checked={newsSources.includes(key)}
                onChange={() => toggleSource(key)}
              />
              <span>{labelFor(key)}</span>
              <code className="qpt-code">{key}</code>
            </label>
          ))}
        </div>
        <div className="qpt-hint">
          至少保留一个数据源；保存配置后「探测全部」与预览会按勾选生效。雅虎财经会按下方「自选关键词」逐条搜索（如 NVDA），不再使用通用 finance 流。
        </div>
      </section>

      <section className="qpt-panel">
        <h2>各源状态</h2>
        {!probeSources && (
          <div className="qpt-hint">首次进入或接口失败时无数据，请点击「探测全部数据源」。</div>
        )}
        <div className="sna-probe-row">
          {DEFAULT_SOURCE_KEYS.map((key) => {
            const o = probeSources ? probeSources[key] : null
            if (!o) {
              return (
                <div key={key} className="sna-probe-pill off">
                  <span className="sna-probe-name">{labelFor(key)}</span>
                  <span>—</span>
                </div>
              )
            }
            const cls = o.enabled ? (o.ok ? 'ok' : 'err') : 'off'
            return (
              <div key={key} className={`sna-probe-pill ${cls}`}>
                <span className="sna-probe-name">{labelFor(key)}</span>
                {!o.enabled && <span>未启用</span>}
                {o.enabled && o.ok && <span>{o.count} 条</span>}
                {o.enabled && !o.ok && <span title={o.error || ''}>异常</span>}
              </div>
            )
          })}
        </div>
        <div className="qpt-actions">
          <button type="button" className="qpt-btn" disabled={loading} onClick={onProbeAll}>
            探测全部数据源
          </button>
          <button type="button" className="qpt-btn ghost" disabled={loading} onClick={onProbe}>
            仅探测金十
          </button>
          <button type="button" className="qpt-btn ghost" disabled={previewLoading} onClick={loadPreview}>
            {previewLoading ? '加载预览…' : '刷新聚合预览'}
          </button>
        </div>
      </section>

      {(preview?.rows || []).length > 0 && (
        <section className="qpt-panel">
          <h2>聚合预览（各源截取部分条）</h2>
          <div className="qpt-table-wrap">
            <table className="qpt-table">
              <thead>
                <tr>
                  <th>来源</th>
                  <th>时间</th>
                  <th>内容</th>
                </tr>
              </thead>
              <tbody>
                {preview.rows.map((row, i) => (
                  <tr key={`${row.feed_key}-${i}`}>
                    <td className="sna-td-feed">{row.feed}</td>
                    <td className="sna-td-time">{row.time}</td>
                    <td className="sna-td-text">
                      {row.text}
                      {row.url ? (
                        <a className="sna-link" href={row.url} target="_blank" rel="noreferrer">
                          原文
                        </a>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <section className="qpt-panel">
        <h2>监控配置</h2>
        <div className="qpt-field">
          <label>自选关键词（每行一个，或逗号分隔）</label>
          <textarea
            value={watchText}
            onChange={(e) => setWatchText(e.target.value)}
            placeholder={'NVDA\n英伟达\n或填 全美股（不限代码，仅按下方影响面词推送）'}
          />
          <div className="qpt-hint">
            监控<strong>所有美股</strong>的评级/目标价变动：自选填 <code className="qpt-code">全美股</code> 或{' '}
            <code className="qpt-code">*</code>，勾选下方两项「影响面仅自定义词」「仅重要快讯」，并在影响面框填入评级/目标价关键词；数据源建议只勾选雅虎、富途。
          </div>
        </div>
        <div className="qpt-hint" style={{ marginBottom: '14px' }}>
          钉钉 Webhook 已在服务端配置（{dingtalkConfigured ? '已检测到' : '未检测到，请在 data/stock_news_alert_config.json 配置'}）。
        </div>
        <div className="qpt-field">
          <label>轮询间隔（秒，10–300）</label>
          <input
            type="number"
            min={10}
            max={300}
            value={pollSec}
            onChange={(e) => setPollSec(Number(e.target.value))}
          />
        </div>
        <div className="qpt-field">
          <label>额外「影响面」关键词（逗号或换行分隔，可选）</label>
          <textarea
            value={extraKw}
            onChange={(e) => setExtraKw(e.target.value)}
            placeholder="如：拆股、分红"
          />
          <div className="qpt-hint">
            推送需同时满足：① 正文命中「自选关键词」；② 开启「仅重要快讯」时，还须命中影响面词
            {onlyExtraImpact ? '（已勾选下方选项：仅自定义词，金十重磅标记不再单独放行）' : '或金十 important 重磅标记'}。
            未勾选「影响面仅使用自定义词」时，系统还会叠加内置词（加息、财报、评级、目标价等）。
          </div>
        </div>
        <div className="qpt-row">
          <label className="cb">
            <input
              type="checkbox"
              checked={onlyExtraImpact}
              onChange={(e) => setOnlyExtraImpact(e.target.checked)}
            />
            影响面仅使用上方自定义词（不含内置加息/财报等）
          </label>
        </div>
        <div className="qpt-row">
          <label className="cb">
            <input
              type="checkbox"
              checked={onlyMaterial}
              onChange={(e) => setOnlyMaterial(e.target.checked)}
            />
            仅推送「重要快讯」（推荐）
          </label>
        </div>
        <div className="qpt-actions">
          <button type="button" className="qpt-btn ghost" disabled={loading} onClick={onSave}>
            仅保存配置
          </button>
          <button type="button" className="qpt-btn ghost" disabled={loading} onClick={onTestDing}>
            测试钉钉
          </button>
        </div>
      </section>

      <section className="qpt-panel">
        <h2>运行状态</h2>
        <div className="qpt-status">
          <div>
            服务：
            <span className={status.running ? 'ok' : ''}>
              {status.running ? '运行中' : '已停止'}
            </span>
          </div>
          <div>上次轮询：{status.last_poll_at || '—'}</div>
          <div>上轮新命中条数：{status.last_push_count}</div>
          {status.last_error && (
            <div className="err">最近异常：{status.last_error}</div>
          )}
        </div>
        <div className="qpt-actions">
          <button type="button" className="qpt-btn primary" disabled={loading} onClick={onStart}>
            {status.running ? '保存并追加' : '保存并启动'}
          </button>
          <button type="button" className="qpt-btn danger" disabled={loading || !status.running} onClick={onStop}>
            停止
          </button>
        </div>
      </section>

      <section className="qpt-panel sna-pool-panel">
        <h2>
          监控池
          {poolItems.length > 0 && <span className="sna-pool-count">{poolItems.length}</span>}
          {status.running && poolItems.length > 0 && (
            <span className="sna-pool-badge">运行中</span>
          )}
        </h2>
        {poolItems.length > 0 && (
          <div className="qpt-hint">
            已启动的新闻监控会显示在下方；填写新关键词后再次「保存并启动」可追加；点击 × 可移除单项（全部移除后自动停止）。
          </div>
        )}
        {poolItems.length === 0 ? (
          <div className="sna-pool-empty">
            <div className="sna-pool-empty-icon">📰</div>
            <h3>暂无运行中的新闻监控</h3>
            <p>填写自选关键词并点击「保存并启动」后，监控项会出现在此处</p>
          </div>
        ) : (
          <div className="sna-pool-grid">
            {poolItems.map((item) => (
              <div
                key={item.keyword}
                className={`sna-pool-card ${recentHitKeywords.has(item.keyword) ? 'hit' : ''}`}
              >
                <div className="sna-pool-card-head">
                  <span className="sna-pool-keyword">{item.keyword}</span>
                  <button
                    type="button"
                    className="sna-pool-remove"
                    disabled={loading}
                    onClick={() => onRemoveWatch(item.keyword)}
                    aria-label={`移除 ${item.keyword}`}
                  >
                    ×
                  </button>
                </div>
                <div className="sna-pool-meta">
                  <span className="sna-pool-label">数据源</span>
                  <span>{(item.source_labels || item.sources || []).join('、') || '—'}</span>
                </div>
                <div className="sna-pool-meta">
                  <span className="sna-pool-label">规则</span>
                  <span>{formatMonitorRules(item)}</span>
                </div>
                {item.last_push ? (
                  <div className="sna-pool-last">
                    <span className="sna-pool-label">最近命中</span>
                    <div className="sna-pool-last-body">
                      <span className="sna-pool-last-time">{item.last_push.at}</span>
                      {item.last_push.feed && (
                        <span className="sna-pool-last-feed">{item.last_push.feed}</span>
                      )}
                      <p className="sna-pool-last-text">{item.last_push.text}</p>
                    </div>
                  </div>
                ) : (
                  <div className="sna-pool-meta muted">
                    <span className="sna-pool-label">最近命中</span>
                    <span>暂无推送记录</span>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="qpt-panel">
        <h2>轮询日志</h2>
        <div className="qpt-hint">
          启动后每 {pollSec} 秒轮询一次；仅推送本轮新出现的快讯（首轮不推历史）。完整记录见{' '}
          <code className="qpt-code">{status.log_file}</code>。钉钉消息须含关键词「提醒」。
        </div>
        {status.last_poll_summary?.message && (
          <div className="sna-poll-latest">
            <div className="sna-poll-latest-time">{status.last_poll_summary.at}</div>
            <div>{status.last_poll_summary.message}</div>
            {formatPollStats(status.last_poll_summary.stats) && (
              <div className="sna-poll-stats">{formatPollStats(status.last_poll_summary.stats)}</div>
            )}
            {(status.last_poll_summary.matched_samples || []).length > 0 && (
              <ul className="sna-poll-samples">
                {status.last_poll_summary.matched_samples.map((row, i) => (
                  <li key={`sample-${i}`}>
                    <span className="sna-poll-sample-feed">{row.feed}</span>
                    <span className="sna-poll-sample-text">{row.text}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
        <div className="sna-poll-log-wrap">
          {(status.poll_logs || []).length === 0 ? (
            <div className="qpt-hint">暂无轮询记录；点击「保存并启动」后开始写入。</div>
          ) : (
            (status.poll_logs || []).map((log, i) => (
              <div key={`${log.at}-${i}`} className={`sna-poll-log-line ${log.error ? 'err' : ''}`}>
                <span className="sna-poll-log-time">{log.at}</span>
                <span className="sna-poll-log-msg">{log.message}</span>
                {formatPollStats(log.stats) && (
                  <span className="sna-poll-log-stats">{formatPollStats(log.stats)}</span>
                )}
              </div>
            ))
          )}
        </div>
      </section>

      {msg && <div className="qpt-panel qpt-msg sna-msg-panel">{msg}</div>}
    </AisPageShell>
  )
}

export default StockNewsAlert
