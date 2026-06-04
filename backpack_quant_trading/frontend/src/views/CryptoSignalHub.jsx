import React, { useCallback, useEffect, useRef, useState } from 'react'
import * as echarts from 'echarts'
import AisPageShell from '../components/AisPageShell'
import {
  getCryptoSignalConfig,
  saveCryptoSignalConfig,
  getUptrendScan,
  runUptrendScan,
  getScoreHistory,
  testSignalScore,
  testCryptoDingtalk,
} from '../api/cryptoSignalHub'
import './CryptoSignalHub.css'

const CryptoSignalHub = () => {
  const [cfg, setCfg] = useState(null)
  const [deepseekOk, setDeepseekOk] = useState(false)
  const [scan, setScan] = useState(null)
  const [scanRunning, setScanRunning] = useState(false)
  const [history, setHistory] = useState([])
  const [msg, setMsg] = useState('')
  const [loading, setLoading] = useState(false)
  const barRef = useRef(null)
  const barChart = useRef(null)
  const miniRefs = useRef({})

  const loadAll = useCallback(async () => {
    try {
      const [c, s, h] = await Promise.all([
        getCryptoSignalConfig(),
        getUptrendScan(),
        getScoreHistory(40),
      ])
      setCfg(c?.config || {})
      setDeepseekOk(!!c?.deepseek_configured)
      setScan(s?.data)
      setScanRunning(!!s?.scan_running)
      setHistory(h?.items || [])
    } catch (e) {
      setMsg(String(e?.message || e))
    }
  }, [])

  useEffect(() => {
    loadAll()
    const t = setInterval(loadAll, 15000)
    return () => clearInterval(t)
  }, [loadAll])

  const displayList = (() => {
    if (!scan) return []
    if (scan.uptrend_list?.length) return scan.uptrend_list
    return (scan.snapshot_list || []).slice(0, 30)
  })()

  useEffect(() => {
    if (!barRef.current || !displayList.length) {
      if (barChart.current) {
        barChart.current.dispose()
        barChart.current = null
      }
      return undefined
    }
    const list = displayList
    const symbols = list.map((x) => x.symbol)
    const rets = list.map((x) => x.metrics?.recent_change_pct ?? x.metrics?.return_20_bars_pct ?? 0)
    if (!barChart.current) barChart.current = echarts.init(barRef.current)
    barChart.current.setOption({
      title: { text: '上涨趋势币 — 近期涨幅%', left: 'center', textStyle: { fontSize: 13 } },
      tooltip: { trigger: 'axis' },
      grid: { left: 48, right: 24, top: 48, bottom: 56 },
      xAxis: { type: 'category', data: symbols, axisLabel: { rotate: 35, fontSize: 10 } },
      yAxis: { type: 'value', name: '%' },
      series: [{
        type: 'bar',
        data: rets,
        itemStyle: {
          color: (p) => (p.value >= 0 ? '#10b981' : '#ef4444'),
        },
      }],
    })
    const onResize = () => barChart.current?.resize()
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [displayList])

  useEffect(() => {
    const list = displayList
    list.forEach((item) => {
      const el = miniRefs.current[item.symbol]
      if (!el || !item.chart?.length) return
      const ch = echarts.getInstanceByDom(el) || echarts.init(el)
      const times = item.chart.map((b) => {
        const d = new Date(b.time)
        return `${d.getMonth() + 1}/${d.getDate()}`
      })
      ch.setOption({
        animation: false,
        grid: { left: 4, right: 4, top: 4, bottom: 4 },
        xAxis: { type: 'category', data: times, show: false },
        yAxis: { type: 'value', show: false, scale: true },
        series: [
          { type: 'line', data: item.chart.map((b) => b.close), smooth: true, lineStyle: { width: 1.5, color: '#4f46e5' }, symbol: 'none' },
          { type: 'line', data: item.chart.map((b) => b.ema20), smooth: true, lineStyle: { width: 1, color: '#94a3b8' }, symbol: 'none' },
        ],
      })
    })
  }, [displayList])

  const onSaveConfig = async () => {
    setLoading(true)
    setMsg('')
    try {
      await saveCryptoSignalConfig(cfg)
      setMsg('配置已保存')
      await loadAll()
    } catch (e) {
      setMsg(String(e?.message || e))
    } finally {
      setLoading(false)
    }
  }

  const onRunScan = async () => {
    setLoading(true)
    setMsg('正在启动扫描…')
    try {
      const r = await runUptrendScan()
      setMsg(r?.message || '扫描已启动')
      setScanRunning(true)
    } catch (e) {
      setMsg(String(e?.message || e))
    } finally {
      setLoading(false)
    }
  }

  const onTestScore = async () => {
    if (!deepseekOk) {
      setMsg('请先在服务端配置 DEEPSEEK_API_KEY')
      return
    }
    setLoading(true)
    try {
      const r = await testSignalScore({ symbol: 'ETH', action: 'buy', timeframe: '4h' })
      setMsg(`测试完成：评分 ${r?.deepseek?.structured?.score ?? '—'}，钉钉 ${r?.dingtalk_ok ? '成功' : r?.dingtalk_msg}`)
      await loadAll()
    } catch (e) {
      setMsg(String(e?.message || e))
    } finally {
      setLoading(false)
    }
  }

  const uptrendList = scan?.uptrend_list || []
  const showSnapshot = scan?.scanned_at && uptrendList.length === 0 && displayList.length > 0

  return (
    <AisPageShell
      title="加密趋势扫描 & 买入信号 AI 评分"
      subtitle="上涨趋势扫描（本地 MACD）；Webhook 买入 → 钉钉 AI 评分为独立通道，与实盘开单门槛无关"
    >
      {msg && <p className="ais-sub" style={{ marginBottom: 12 }}>{msg}</p>}

      <div className="csh-grid">
        <section className="csh-panel">
          <h3>配置</h3>
          <div className="csh-switch">
            <input
              type="checkbox"
              id="wh-en"
              checked={cfg?.dingtalk_on_webhook_enabled ?? cfg?.webhook_scorer_enabled ?? true}
              onChange={(e) => setCfg((c) => ({
                ...c,
                dingtalk_on_webhook_enabled: e.target.checked,
                webhook_scorer_enabled: e.target.checked,
              }))}
            />
            <label htmlFor="wh-en">Webhook 买入时自动 AI 评分并推送钉钉（与实盘开单无关）</label>
          </div>
          <div className="csh-field">
            <label>DeepSeek</label>
            <span className={deepseekOk ? 'csh-tag' : ''} style={deepseekOk ? {} : { background: '#fef2f2', color: '#b91c1c' }}>
              {deepseekOk ? '已配置 API Key' : '未配置 DEEPSEEK_API_KEY'}
            </span>
          </div>
          <div className="csh-actions">
            <button type="button" className="ais-primary-btn" disabled={loading} onClick={onSaveConfig}>保存配置</button>
            <button type="button" className="ais-ghost-btn" disabled={loading} onClick={() => testCryptoDingtalk().then((r) => setMsg(r?.ok ? '钉钉测试成功' : r?.message))}>
              测试钉钉
            </button>
            <button type="button" className="ais-ghost-btn" disabled={loading || !deepseekOk} onClick={onTestScore}>
              测试 ETH 买入评分
            </button>
          </div>
          <p className="csh-meta">
            <strong>说明：</strong>上涨 = <strong>周线且日线</strong> MACD 金叉区间；强趋势 = 再满足 <strong>8h</strong> 金叉区间。
            <strong>进场</strong> = 背景通过 + 8h <strong>死叉交叉</strong>（死叉后）；<strong>离场</strong> = 日线 <strong>金叉交叉</strong>（金叉后）。
            死叉/金叉是交叉事件，用于进场或离场由配置决定，<strong>不调用 DeepSeek</strong>。
          </p>
          <p className="csh-meta">
            钉钉：Webhook buy 后按<strong>信号里的币种 + K 线级别</strong>从 HL 拉 K 线评分后推送。
            实盘开单门槛请在<strong>策略交易 → 自适应做多</strong>里设置「AI 评分开单门槛」。
          </p>
        </section>

        <section className="csh-panel">
          <h3>上涨趋势扫描（HL 成交额 Top50）</h3>
          <div className="csh-actions">
            <button type="button" className="ais-primary-btn" disabled={loading || scanRunning} onClick={onRunScan}>
              {scanRunning ? '扫描中…' : '开始扫描'}
            </button>
            <button type="button" className="ais-ghost-btn" disabled={loading} onClick={loadAll}>刷新</button>
          </div>
          <p className="csh-meta">
            {scan?.scanned_at
              ? `上次：${scan.scanned_at} · 已分析 ${scan.analyzed_count ?? displayList.length}/${scan.total_candidates} · 三层过滤通过 ${scan.uptrend_count} · ${scan.duration_sec}s · 每1小时自动更新`
              : '尚未扫描；服务启动后约 90 秒自动首次扫描，之后每 1 小时更新（也可手动「开始扫描」）'}
          </p>
          {showSnapshot && (
            <p className="csh-meta" style={{ color: '#b45309', marginBottom: 12 }}>
              本次无币种满足「三层过滤」背景条件，下图展示 Top50 技术快照（按趋势分排序，供参考）。
            </p>
          )}
          {scan?.filter && (
            <p className="csh-meta" style={{ marginBottom: 8 }}>
              上涨：{scan.filter.uptrend_rule || '周线且日线金叉'} · 强：{scan.filter.strong_rule || '周线日线8h金叉'}
              · Pine进场背景(且) D{scan.filter.pine_bg_cond1 || '金叉'}
              · 进场 {scan.filter.entry_tf} {scan.filter.entry_cond}
              · 离场 {scan.filter.exit_tf1} {scan.filter.exit_cond1} ({scan.filter.exit_logic || '或'})
            </p>
          )}
          {scan?.errors?.length > 0 && (
            <p className="csh-meta" style={{ marginBottom: 8 }}>
              K线异常：{scan.errors.slice(0, 5).join('；')}
              {scan.errors.length > 5 ? ` 等 ${scan.errors.length} 条` : ''}
            </p>
          )}
          {displayList.length > 0 && (
            <>
              <div ref={barRef} className="csh-chart" />
              <table className="csh-table">
                <thead>
                  <tr>
                    <th>币种</th>
                    <th>趋势分</th>
                    <th>周线</th>
                    <th>日线</th>
                    <th>8h</th>
                    <th>强趋势</th>
                    <th title="Pine 进场：8h 死叉交叉">进场</th>
                    <th title="Pine 离场：D 金叉交叉">离场</th>
                    <th>状态</th>
                  </tr>
                </thead>
                <tbody>
                  {displayList.map((row) => (
                    <tr key={row.symbol}>
                      <td><strong>{row.symbol}</strong> <span className="csh-tag">#{row.market_cap_rank}</span></td>
                      <td>{row.metrics?.trend_score ?? '—'}</td>
                      <td title={row.metrics?.bg1_zone || ''}>{row.metrics?.bg1_ok ? '✓' : '—'}</td>
                      <td title={row.metrics?.bg2_zone || ''}>{row.metrics?.bg2_ok ? '✓' : '—'}</td>
                      <td title={row.metrics?.bg3_zone || ''}>{row.metrics?.bg3_ok ? '✓' : '—'}</td>
                      <td>
                        {row.metrics?.strong_trend ? (
                          <span className="csh-tag">强</span>
                        ) : (
                          <span className="csh-meta">{row.metrics?.golden_tf_count ?? 0}/3</span>
                        )}
                      </td>
                      <td title={`${row.metrics?.entry_tf || '8h'} ${row.metrics?.entry_cond || ''}`}>
                        {row.metrics?.entry_trigger ? (
                          <span className="csh-tag">死叉</span>
                        ) : (
                          row.metrics?.entry_cross || '—'
                        )}
                      </td>
                      <td title={`${row.metrics?.exit_tf1 || '1d'} ${row.metrics?.exit_cond1 || ''}`}>
                        {row.metrics?.exit_conditions_met ? (
                          <span className="csh-tag" style={{ background: '#7f1d1d' }}>金叉</span>
                        ) : (
                          row.metrics?.exit1_cross || '—'
                        )}
                      </td>
                      <td>
                        {row.is_uptrend || row.metrics?.is_uptrend ? (
                          <span className="csh-tag">{row.metrics?.strong_trend ? '强+涨' : '上涨'}</span>
                        ) : (
                          <span title={row.metrics?.reject_reason || ''}>未达标</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="csh-mini-charts">
                {displayList.slice(0, 12).map((item) => (
                  <div key={item.symbol} className="csh-mini">
                    <div className="csh-mini-title">{item.symbol} 走势</div>
                    <div
                      className="csh-mini-chart"
                      ref={(el) => { miniRefs.current[item.symbol] = el }}
                    />
                  </div>
                ))}
              </div>
            </>
          )}
        </section>
      </div>

      <section className="csh-panel" style={{ marginTop: 20 }}>
        <h3>最近 Webhook 评分记录</h3>
        <div className="csh-history">
          {history.length === 0 ? (
            <p className="csh-meta">暂无记录</p>
          ) : (
            <table className="csh-table">
              <thead>
                <tr>
                  <th>时间</th>
                  <th>标的</th>
                  <th>评分</th>
                  <th>建议</th>
                  <th>钉钉</th>
                </tr>
              </thead>
              <tbody>
                {history.map((h, i) => (
                  <tr key={i}>
                    <td>{h.at}</td>
                    <td>{h.symbol} {h.action}</td>
                    <td>{h.score} ({h.grade})</td>
                    <td>{h.recommendation}</td>
                    <td>{h.dingtalk_ok ? '✓' : h.dingtalk_msg}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </section>
    </AisPageShell>
  )
}

export default CryptoSignalHub
