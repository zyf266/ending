import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import * as echarts from 'echarts'
import {
  getBubbleHistory,
  getLatestBubbleAnalysis,
  getBubbleReportById,
} from '../api/usWeeklyReport'
import AisPageShell from '../components/AisPageShell'
import './UsWeeklyReport.css'

const fmtScore = (v, max) =>
  v == null ? '—' : `${typeof v === 'number' ? v.toFixed(0) : v} / ${max ?? '—'}`

// 根据「市场状态」匹配情绪色
const marketStateStyle = (s = '') => {
  if (!s) return { color: '#fff', glow: 'rgba(255,255,255,0.4)' }
  if (/破裂|信用压力/.test(s)) return { color: '#f87171', glow: 'rgba(239,68,68,0.55)' }
  if (/下跌/.test(s)) return { color: '#fb7185', glow: 'rgba(244,63,94,0.5)' }
  if (/顶部震荡|震荡/.test(s)) return { color: '#fde047', glow: 'rgba(250,204,21,0.5)' }
  if (/加速/.test(s)) return { color: '#fb923c', glow: 'rgba(251,146,60,0.6)' }
  if (/强趋势|强势|过热/.test(s)) return { color: '#fbbf24', glow: 'rgba(251,191,36,0.55)' }
  if (/上涨|趋势/.test(s)) return { color: '#4ade80', glow: 'rgba(74,222,128,0.5)' }
  return { color: '#fff', glow: 'rgba(255,255,255,0.4)' }
}

const SegmentBar = ({ score, max, color }) => {
  const pct = score != null && max ? Math.max(0, Math.min(100, (Number(score) / Number(max)) * 100)) : 0
  return (
    <div className="uwr-seg-bar">
      <div className="uwr-seg-fill" style={{ width: `${pct}%`, background: color }} />
    </div>
  )
}

const StatPill = ({ label, value, tone = 'default' }) => (
  <div className={`uwr-pill uwr-pill-${tone}`}>
    <span className="uwr-pill-label">{label}</span>
    <span className="uwr-pill-value">{value || '—'}</span>
  </div>
)

const Stars = ({ n = 0 }) => (
  <span className="uwr-stars" aria-label={`${n}星`}>
    {'★'.repeat(Math.max(0, Math.min(5, n)))}
    <span className="uwr-stars-dim">{'★'.repeat(Math.max(0, 5 - n))}</span>
  </span>
)

const UsWeeklyReport = () => {
  const [analysis, setAnalysis] = useState(null)
  const [history, setHistory] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [showHistory, setShowHistory] = useState(false)
  const chartRef = useRef(null)

  const loadAll = useCallback(async () => {
    try {
      const [latest, hist] = await Promise.all([
        getLatestBubbleAnalysis().catch(() => null),
        getBubbleHistory(80).catch(() => null),
      ])
      if (latest && !latest.empty) {
        setAnalysis(latest)
        setSelectedId(latest.generated_at_utc || null)
      }
      if (hist?.items) setHistory(hist.items)
    } catch (_) {
      // ignore
    }
  }, [])

  const onSelectReport = useCallback(async (id) => {
    if (!id || id === selectedId) return
    setSelectedId(id)
    try {
      const res = await getBubbleReportById(id)
      if (res && !res.empty) setAnalysis(res)
    } catch (_) {
      // ignore
    }
  }, [selectedId])

  useEffect(() => {
    loadAll()
  }, [loadAll])

  // 主图：泡沫总分曲线（短/中/长/总分 四条折线）
  useEffect(() => {
    if (!chartRef.current) return
    const items = (history || []).filter((x) => x.bubble_total_score != null)
    if (!items.length) return
    const ch = echarts.init(chartRef.current)
    const xs = items.map((x) => (x.generated_at_utc || x.report_date || '').slice(0, 10))
    const mkLine = (name, color, key, width = 2) => ({
      name,
      type: 'line',
      smooth: true,
      symbol: 'circle',
      symbolSize: 9,
      data: items.map((x) => (x[key] != null ? x[key] : null)),
      lineStyle: { color, width },
      itemStyle: { color },
      connectNulls: true,
    })
    ch.setOption({
      tooltip: {
        trigger: 'axis',
        formatter: (params) => {
          const i = params[0]?.dataIndex ?? 0
          const it = items[i] || {}
          return [
            `<b>${xs[i]}</b>`,
            `短期：${it.short_term_score ?? '—'}/${it.short_term_max ?? 20}`,
            `中期：${it.mid_term_score ?? '—'}/${it.mid_term_max ?? 25}`,
            `长期：${it.long_term_score ?? '—'}/${it.long_term_max ?? 25}`,
          ].join('<br/>')
        },
      },
      legend: { data: ['短期', '中期', '长期'], top: 4, right: 10 },
      grid: { left: 50, right: 24, top: 40, bottom: 32 },
      xAxis: { type: 'category', data: xs, boundaryGap: false },
      yAxis: { type: 'value', min: 0, max: 25, name: '分数 (0-25)' },
      series: [
        mkLine('短期', '#fb7185', 'short_term_score', 2.5),
        mkLine('中期', '#f59e0b', 'mid_term_score', 2.5),
        mkLine('长期', '#a855f7', 'long_term_score', 2.5),
      ],
    })
    const onResize = () => ch.resize()
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      ch.dispose()
    }
  }, [history])

  const report = analysis?.report || null

  const sortedHistory = useMemo(() => {
    return [...(history || [])].sort((a, b) => {
      const ta = a.generated_at_utc || a.report_date || ''
      const tb = b.generated_at_utc || b.report_date || ''
      return tb.localeCompare(ta)
    })
  }, [history])

  return (
    <AisPageShell
      title="美股泡沫阶段监测"
      subtitle="周度泡沫评分、三层次综合判断与历史趋势；切换历史周报查看各期摘要与完整报告。"
    >
      <div className="uwr-stack">
      {/* 历史周报选择栏 */}
      {sortedHistory.length > 0 && (
        <div className="uwr-history-bar">
          <div className="uwr-history-bar-l">
            <span className="uwr-history-bar-title">历史周报</span>
            <span className="uwr-history-bar-count">共 {sortedHistory.length} 期</span>
          </div>
          <div className="uwr-history-tabs">
            {sortedHistory.slice(0, 4).map((h) => {
              const id = h.generated_at_utc
              const date = h.report_date || (h.generated_at_utc || '').slice(0, 10) || '—'
              const active = id === selectedId
              return (
                <button
                  type="button"
                  key={id}
                  className={`uwr-history-tab ${active ? 'active' : ''}`}
                  onClick={() => onSelectReport(id)}
                  title={h.report_label || ''}
                >
                  <span className="uwr-history-tab-date">{date}</span>
                  <span className="uwr-history-tab-score">
                    {h.bubble_total_score ?? '—'}
                  </span>
                  {h.report_label && <span className="uwr-history-tab-label">{h.report_label}</span>}
                </button>
              )
            })}
            {sortedHistory.length > 4 && (
              <button
                type="button"
                className="uwr-history-tab uwr-history-tab-more"
                onClick={() => setShowHistory(true)}
              >
                查看全部 ▾
              </button>
            )}
          </div>
        </div>
      )}

      {/* 历史抽屉（全部周报） */}
      {showHistory && (
        <div className="uwr-history-drawer-mask" onClick={() => setShowHistory(false)}>
          <div className="uwr-history-drawer" onClick={(e) => e.stopPropagation()}>
            <div className="uwr-history-drawer-h">
              <span>全部历史周报</span>
              <button type="button" className="uwr-history-close" onClick={() => setShowHistory(false)}>✕</button>
            </div>
            <div className="uwr-history-list">
              {sortedHistory.map((h) => {
                const id = h.generated_at_utc
                const date = h.report_date || id?.slice(0, 10) || '—'
                const active = id === selectedId
                return (
                  <button
                    type="button"
                    key={id}
                    className={`uwr-history-item ${active ? 'active' : ''}`}
                    onClick={() => {
                      onSelectReport(id)
                      setShowHistory(false)
                    }}
                  >
                    <div className="uwr-history-item-l">
                      <div className="uwr-history-item-date">{date}</div>
                      <div className="uwr-history-item-meta">
                        <span>{h.stage || '—'}</span>
                        <span>·</span>
                        <span>{h.market_state || '—'}</span>
                        <span>·</span>
                        <span>下周：{h.next_week_bias || '—'}</span>
                      </div>
                      {h.one_liner && <div className="uwr-history-item-one">{h.one_liner}</div>}
                    </div>
                    <div className="uwr-history-item-r">
                      <div className="uwr-history-item-score">
                        {h.bubble_total_score ?? '—'}
                      </div>
                      {!h.has_report && <div className="uwr-history-item-seed">仅评分摘要</div>}
                    </div>
                  </button>
                )
              })}
            </div>
          </div>
        </div>
      )}

      <div className="uwr-hero">
        <div className="uwr-hero-left">
          <div className="uwr-hero-tag">美股泡沫阶段监测 · 周度</div>
          <h2
            className="uwr-hero-title"
            style={{
              color: marketStateStyle(analysis?.market_state).color,
              textShadow: `0 0 18px ${marketStateStyle(analysis?.market_state).glow}`,
            }}
          >
            {analysis?.market_state || '—'}
          </h2>
          <div className="uwr-hero-sub">
            报告日期：{analysis?.report_date || (analysis?.generated_at_utc || '').slice(0, 10) || '—'}
            ｜下周倾向：<b>{analysis?.next_week_bias || '—'}</b>
          </div>
          {analysis?.one_liner && <div className="uwr-hero-one">{analysis.one_liner}</div>}
        </div>

        <div className="uwr-hero-right">
          <div className="uwr-score-3">
            <div className="uwr-score-cell">
              <div className="uwr-score-cell-h">短期 1-4 周</div>
              <div className="uwr-score-cell-v" style={{ color: '#fda4af' }}>
                {fmtScore(analysis?.short_term_score, analysis?.short_term_max ?? 20)}
              </div>
              <SegmentBar score={analysis?.short_term_score} max={analysis?.short_term_max ?? 20} color="#fb7185" />
            </div>
            <div className="uwr-score-cell">
              <div className="uwr-score-cell-h">中期 3-6 月</div>
              <div className="uwr-score-cell-v" style={{ color: '#fcd34d' }}>
                {fmtScore(analysis?.mid_term_score, analysis?.mid_term_max ?? 25)}
              </div>
              <SegmentBar score={analysis?.mid_term_score} max={analysis?.mid_term_max ?? 25} color="#f59e0b" />
            </div>
            <div className="uwr-score-cell">
              <div className="uwr-score-cell-h">长期 1-3 年</div>
              <div className="uwr-score-cell-v" style={{ color: '#c4b5fd' }}>
                {fmtScore(analysis?.long_term_score, analysis?.long_term_max ?? 25)}
              </div>
              <SegmentBar score={analysis?.long_term_score} max={analysis?.long_term_max ?? 25} color="#a855f7" />
            </div>
          </div>
        </div>
      </div>

      <div className="uwr-card">
        <div className="uwr-card-h">泡沫评分趋势（短期 / 中期 / 长期，0-25）</div>
        <div ref={chartRef} style={{ height: 360, padding: '8px 12px 16px' }} />
      </div>

      {/* 仅评分摘要提示（无完整 report） */}
      {analysis && !report && (
        <div className="uwr-card">
          <div className="uwr-meta" style={{ padding: '14px 16px' }}>
            此周报为「仅评分摘要」（{analysis.report_date || (analysis.generated_at_utc || '').slice(0, 10) || '—'}）。
            如需完整结构化内容，请切换至其他周报，或调用 DeepSeek 重新生成。
          </div>
        </div>
      )}

      {/* 综合判断 */}
      {report?.synthesis && (
        <div className="uwr-card">
          <div className="uwr-card-h">三层次综合判断</div>
          <div className="uwr-pill-grid">
            {report.synthesis.map((s, i) => (
              <StatPill key={i} label={s.label} value={s.value} tone={i === 3 ? 'danger' : i === 0 ? 'rose' : i === 1 ? 'amber' : 'violet'} />
            ))}
          </div>
        </div>
      )}

      {/* 5 件事 */}
      {report?.top5_events && (
        <div className="uwr-card">
          <div className="uwr-card-h">本周真正重要的 5 件事</div>
          <div className="uwr-events">
            {report.top5_events.map((e) => (
              <div className="uwr-event" key={e.id}>
                <div className="uwr-event-h">
                  <span className="uwr-event-id">#{e.id}</span>
                  <span className="uwr-event-title">{e.title}</span>
                </div>
                <div className="uwr-event-body">
                  <div><b>事实：</b>{e.fact}</div>
                  <div><b>来源 / 日期：</b><span className="uwr-mono">{e.source_date}</span></div>
                  <div><b>为什么重要：</b>{e.why_matters}</div>
                  <div><b>影响方向：</b>{e.direction}</div>
                  <div><b>是否改变交易计划：</b><span className="uwr-event-change">{e.plan_change}</span></div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 评分模型 三段 */}
      {(report?.score_short || report?.score_mid || report?.score_long) && (
        <div className="uwr-card">
          <div className="uwr-card-h">泡沫评分模型 · 三时间维度（0-5 分制）</div>
          <div className="uwr-score-3-block">
            {[
              { key: 'short', title: '短期泡沫压力 · 1-4 周', rows: report?.score_short, total: report?.score_short_total, max: report?.score_short_max, conclusion: report?.score_short_conclusion, color: '#fb7185' },
              { key: 'mid', title: '中期泡沫积累 · 3-6 月', rows: report?.score_mid, total: report?.score_mid_total, max: report?.score_mid_max, conclusion: report?.score_mid_conclusion, color: '#f59e0b' },
              { key: 'long', title: '长期结构性泡沫 · 1-3 年', rows: report?.score_long, total: report?.score_long_total, max: report?.score_long_max, conclusion: report?.score_long_conclusion, color: '#a855f7' },
            ].map((seg) => (
              <div key={seg.key} className="uwr-score-block">
                <div className="uwr-score-block-h" style={{ borderTopColor: seg.color }}>
                  <span className="uwr-score-block-title">{seg.title}</span>
                  <span className="uwr-score-block-total" style={{ color: seg.color }}>
                    {seg.total ?? '—'} / {seg.max ?? '—'}
                  </span>
                </div>
                <div className="uwr-table-wrap">
                  <table className="uwr-table">
                    <thead>
                      <tr>
                        <th style={{ width: 180 }}>维度</th>
                        <th style={{ width: 70 }}>得分</th>
                        <th>依据</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(seg.rows || []).map((r, i) => (
                        <tr key={i}>
                          <td><b>{r.dim}</b></td>
                          <td>
                            <span className="uwr-score-tag" style={{ background: seg.color }}>
                              {r.score}/{r.max}
                            </span>
                          </td>
                          <td>{r.basis}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {seg.conclusion && <div className="uwr-score-block-foot">{seg.conclusion}</div>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 持仓 */}
      {report?.positions?.length > 0 && (
        <div className="uwr-card">
          <div className="uwr-card-h">我的持仓周度处理</div>
          <div className="uwr-table-wrap">
            <table className="uwr-table">
              <thead>
                <tr>
                  <th>代码</th>
                  <th>当前状态</th>
                  <th>本周风险变化</th>
                  <th>建议动作</th>
                  <th>触发条件</th>
                  <th>失效条件</th>
                  <th>下周重点观察</th>
                </tr>
              </thead>
              <tbody>
                {report.positions.map((p, i) => (
                  <tr key={i}>
                    <td><b className="uwr-mono-em">{p.code}</b></td>
                    <td>{p.status}</td>
                    <td>{p.risk_change}</td>
                    <td><span className="uwr-tag tag-action">{p.action}</span></td>
                    <td>{p.trigger}</td>
                    <td>{p.invalidation}</td>
                    <td>{p.watch}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 三种情景 */}
      {report?.scenarios?.length > 0 && (
        <div className="uwr-card">
          <div className="uwr-card-h">下周三种情景计划</div>
          <div className="uwr-scenarios">
            {report.scenarios.map((s, i) => {
              const tone = i === 0 ? 'green' : i === 1 ? 'amber' : 'red'
              return (
                <div className={`uwr-scen uwr-scen-${tone}`} key={i}>
                  <div className="uwr-scen-h">
                    <span>{s.name}</span>
                    {s.probability != null && (
                      <span className="uwr-scen-prob">{(s.probability * 100).toFixed(0)}%</span>
                    )}
                  </div>
                  <div className="uwr-scen-row"><b>触发：</b>{s.trigger}</div>
                  <div className="uwr-scen-row uwr-scen-do"><b>应该做：</b>{s.do}</div>
                  <div className="uwr-scen-row uwr-scen-dont"><b>不能做：</b>{s.dont}</div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* 8 条行动 */}
      {report?.actions?.length > 0 && (
        <div className="uwr-card">
          <div className="uwr-card-h">下周交易行动清单（最多 8 条）</div>
          <div className="uwr-actions-list">
            {report.actions.map((a) => (
              <div className="uwr-act" key={a.idx}>
                <div className="uwr-act-num">{a.idx}</div>
                <div className="uwr-act-body">
                  <div className="uwr-act-h">
                    <span className="uwr-act-action">{a.action}</span>
                    <span className="uwr-act-target">{a.target}</span>
                  </div>
                  <div className="uwr-act-row"><b>原因：</b>{a.reason}</div>
                  <div className="uwr-act-row"><b>触发：</b>{a.trigger}</div>
                  <div className="uwr-act-row"><b>止损 / 失效：</b>{a.stop}</div>
                  <div className="uwr-act-row"><b>时间周期：</b><span className="uwr-tag tag-period">{a.period}</span></div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 转折点 */}
      {report?.watch_points?.length > 0 && (
        <div className="uwr-card">
          <div className="uwr-card-h">下周必须盯的转折点</div>
          <div className="uwr-table-wrap">
            <table className="uwr-table">
              <thead>
                <tr>
                  <th style={{ width: 36 }}>#</th>
                  <th style={{ width: 240 }}>转折点</th>
                  <th>具体内容</th>
                  <th style={{ width: 110 }}>关键性</th>
                </tr>
              </thead>
              <tbody>
                {report.watch_points.map((w) => (
                  <tr key={w.idx}>
                    <td>{w.idx}</td>
                    <td><b>{w.point}</b></td>
                    <td>{w.detail}</td>
                    <td><Stars n={w.stars} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 核心总结 */}
      {report?.core_summary && (
        <div className="uwr-card uwr-summary">
          <div className="uwr-card-h">核心总结</div>
          <pre className="uwr-summary-body">{report.core_summary}</pre>
        </div>
      )}

      {/* 关键反证条件 */}
      {analysis?.key_invalidation && (
        <div className="uwr-disclaimer" style={{ background: '#fff7ed', borderColor: '#fed7aa', color: '#9a3412' }}>
          <b>最关键反证条件：</b>{analysis.key_invalidation}
        </div>
      )}

      {/* 完整 Markdown 兜底（如果有） */}
      {analysis?.markdown && (
        <details className="uwr-card">
          <summary className="uwr-card-h" style={{ cursor: 'pointer' }}>查看完整 Markdown 原文</summary>
          <pre
            style={{
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              padding: '12px 16px 16px',
              margin: 0,
              lineHeight: 1.65,
              fontFamily: 'inherit',
              background: 'transparent',
            }}
          >
            {analysis.markdown}
          </pre>
        </details>
      )}

      {!analysis && (
        <div className="uwr-card">
          <div className="uwr-meta" style={{ padding: '14px 16px' }}>
            暂无报告。点击右上方按钮调用 DeepSeek 生成，或等待每周六 10:00 自动调度。
          </div>
        </div>
      )}
      </div>
    </AisPageShell>
  )
}

export default UsWeeklyReport
