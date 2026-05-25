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
      const r = await testSignalScore({ symbol: 'ETH', action: 'buy', timeframe: cfg?.kline_interval || '4h' })
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
      subtitle="Hyperliquid 永续成交额 Top50 → HL 1000 根 K 线筛选上涨趋势；实盘 Webhook 收到 buy 后 DeepSeek 评分并推送钉钉"
    >
      {msg && <p className="ais-sub" style={{ marginBottom: 12 }}>{msg}</p>}

      <div className="csh-grid">
        <section className="csh-panel">
          <h3>配置</h3>
          <div className="csh-switch">
            <input
              type="checkbox"
              id="wh-en"
              checked={!!cfg?.webhook_scorer_enabled}
              onChange={(e) => setCfg((c) => ({ ...c, webhook_scorer_enabled: e.target.checked }))}
            />
            <label htmlFor="wh-en">实盘 Webhook 买入时自动 AI 评分 + 钉钉</label>
          </div>
          <div className="csh-field">
            <label>DeepSeek</label>
            <span className={deepseekOk ? 'csh-tag' : ''} style={deepseekOk ? {} : { background: '#fef2f2', color: '#b91c1c' }}>
              {deepseekOk ? '已配置 API Key' : '未配置 DEEPSEEK_API_KEY'}
            </span>
          </div>
          <div className="csh-field">
            <label>K 线周期（扫描 & 评分）</label>
            <select
              value={cfg?.kline_interval || '4h'}
              onChange={(e) => setCfg((c) => ({ ...c, kline_interval: e.target.value }))}
            >
              {['1h', '2h', '4h', '1d'].map((v) => (
                <option key={v} value={v}>{v}</option>
              ))}
            </select>
          </div>
          <div className="csh-field">
            <label>K 线根数</label>
            <input
              type="number"
              min={200}
              max={1500}
              value={cfg?.kline_limit ?? 100}
              onChange={(e) => setCfg((c) => ({ ...c, kline_limit: Number(e.target.value) }))}
            />
          </div>
          <div className="csh-field">
            <label>最低推送评分（低于不推钉钉）</label>
            <input
              type="number"
              min={0}
              max={100}
              value={cfg?.min_deepseek_score ?? 0}
              onChange={(e) => setCfg((c) => ({ ...c, min_deepseek_score: Number(e.target.value) }))}
            />
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
            <strong>说明：</strong>「上涨趋势扫描」只用 Hyperliquid K 线 + 本地指标，<strong>不调用 DeepSeek</strong>。
            DeepSeek 仅在 Webhook 买入或「测试 ETH 买入评分」时调用（模型 <code>deepseek-chat</code>，非 v4-pro）。
          </p>
          <p className="csh-meta">
            Webhook：<code>POST /api/trading/adaptive-long/webhook</code>，收到 buy 后评分并推钉钉。
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
              ? `上次：${scan.scanned_at} · 已分析 ${scan.analyzed_count ?? displayList.length}/${scan.total_candidates} · 近期上涨 ${scan.uptrend_count} · ${scan.duration_sec}s`
              : '尚未扫描，点击「开始扫描」（后台约 2–5 分钟，不消耗 DeepSeek）'}
          </p>
          {showSnapshot && (
            <p className="csh-meta" style={{ color: '#b45309', marginBottom: 12 }}>
              本次无币种满足「近期上涨」条件，下图展示 Top50 技术快照（按趋势分排序，供参考）。
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
                    <th>RSI</th>
                    <th>MACD柱</th>
                    <th>近期%</th>
                    <th>状态</th>
                  </tr>
                </thead>
                <tbody>
                  {displayList.map((row) => (
                    <tr key={row.symbol}>
                      <td><strong>{row.symbol}</strong> <span className="csh-tag">#{row.market_cap_rank}</span></td>
                      <td>{row.metrics?.trend_score ?? '—'}</td>
                      <td>{row.metrics?.rsi14 ?? '—'}</td>
                      <td>{row.metrics?.macd_hist ?? '—'}</td>
                      <td>{row.metrics?.recent_change_pct ?? row.metrics?.return_20_bars_pct ?? '—'}%</td>
                      <td>
                        {row.is_uptrend || row.metrics?.is_uptrend ? (
                          <span className="csh-tag">上涨</span>
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
