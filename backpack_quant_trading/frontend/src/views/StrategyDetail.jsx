import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import * as echarts from 'echarts'
import './StrategyDetail.css'

const DEFAULT_INITIAL_CAPITAL = 2000000
const FIXED_START_DATE = '2024-04-01'
const _today = new Date().toISOString().slice(0, 10)
const FIXED_END_DATE = _today
const DEFAULT_END_DATE = _today

const formatPct = (v) => {
  if (v == null) return '--'
  const n = Number(v)
  const sign = n > 0 ? '+' : n < 0 ? '-' : ''
  return `${sign}${Math.abs(n).toFixed(2)}%`
}

const formatPctAbs = (v) => {
  if (v == null) return '--'
  return `${Math.abs(Number(v)).toFixed(2)}%`
}

const formatMoney = (v) => {
  if (v == null) return ''
  const n = Number(v)
  const sign = n > 0 ? '+' : n < 0 ? '-' : ''
  return `${sign}${Math.abs(n).toLocaleString()}`
}

const formatMoneyPlain = (v) => {
  if (v == null) return '0'
  const n = Number(v)
  return n.toLocaleString()
}

function computeOverviewFromTrades(tradesArray, initial = DEFAULT_INITIAL_CAPITAL) {
  if (!tradesArray?.length) return null
  const exitTrades = tradesArray.filter((t) => {
    const tp = String(t.trade_type || '')
    return tp.includes('出') || tp.includes('出场') || tp.includes('止损') || tp.toLowerCase().includes('close')
  })
  const base = exitTrades.length ? exitTrades : tradesArray

  const tradeMap = new Map()
  for (const t of base) {
    const raw = t.trade_no ?? 0
    const key = Number.isFinite(Number(raw)) ? Number(raw) : raw
    tradeMap.set(key, Number(t.pnl || 0))
  }
  const pnls = Array.from(tradeMap.values())

  let running = 0
  const equity = pnls.map((p) => {
    running += p
    return initial + running
  })
  const finalEquity = equity[equity.length - 1]
  const totalReturnPct = ((finalEquity / initial) - 1) * 100

  let peak = equity[0]
  let maxDd = 0
  for (const v of equity) {
    if (v > peak) peak = v
    const dd = (v / peak - 1) * 100
    if (dd < maxDd) maxDd = dd
  }

  const wins = pnls.filter((p) => p > 0)
  const losses = pnls.filter((p) => p < 0)
  const totalTrades = pnls.length
  const winRatePct = totalTrades ? (wins.length / totalTrades) * 100 : 0
  const grossProfit = wins.reduce((s, p) => s + p, 0) || 0
  const grossLossAbs = Math.abs(losses.reduce((s, p) => s + p, 0)) || 1e-9
  const profitFactor = grossProfit / grossLossAbs

  return {
    strategy_profit: running,
    total_return_pct: Number(totalReturnPct.toFixed(2)),
    max_drawdown_pct: Number(Math.abs(maxDd).toFixed(2)),
    win_rate_pct: Number(winRatePct.toFixed(2)),
    profit_factor: Number(profitFactor.toFixed(2)),
    total_trades: totalTrades,
  }
}

export default function StrategyDetail({ title, subtitle, currencyLabel, initialCapital = DEFAULT_INITIAL_CAPITAL, startDate, endDate, fixedProfitFactor = null, getOverview, getTrades, getKlines }) {
  const navigate = useNavigate()
  const initial = useMemo(() => Number(initialCapital || DEFAULT_INITIAL_CAPITAL), [initialCapital])
  const fixedStart = startDate || FIXED_START_DATE
  const fixedEnd = endDate || DEFAULT_END_DATE

  const getDedupExitTradeItems = (tradesList) => {
    if (!Array.isArray(tradesList) || tradesList.length === 0) return []
    const exitTrades = tradesList.filter((t) => {
      const tp = String(t.trade_type || '')
      const sig = String(t.signal || '').toLowerCase()
      return (
        tp.includes('出') ||
        tp.includes('出场') ||
        tp.includes('止损') ||
        tp.toLowerCase().includes('close') ||
        sig.includes('close')
      )
    })
    const base = exitTrades.length ? exitTrades : tradesList

    const tradeMap = new Map()
    base.forEach((t, idx) => {
      const raw = t.trade_no
      const key = raw && Number(raw) ? Number(raw) : `idx_${idx}`
      // 同一个 trade_no 只保留一次（出场行），避免进/出两行翻倍
      tradeMap.set(key, {
        pnl: Number(t.pnl || 0),
        pnl_pct: Number(t.pnl_pct || 0),
      })
    })
    return Array.from(tradeMap.values())
  }

  const equityChartRef = useRef(null)
  const klineChartRef = useRef(null)
  const profitStructRef = useRef(null)
  const contributionRef = useRef(null)
  const pnlHistRef = useRef(null)
  const winLossRef = useRef(null)

  const equityChart = useRef(null)
  const klineChart = useRef(null)
  const profitStructChart = useRef(null)
  const contributionChart = useRef(null)
  const pnlHistChart = useRef(null)
  const winLossChart = useRef(null)

  const [overview, setOverview] = useState(null)
  const [trades, setTrades] = useState([])
  const [tradesSorted, setTradesSorted] = useState([])
  const [klines, setKlines] = useState([])
  const [allTrades, setAllTrades] = useState([])
  const [allKlines, setAllKlines] = useState([])
  const [loading, setLoading] = useState(false)
  const [loadingSignals, setLoadingSignals] = useState(false)
  const [activeTab, setActiveTab] = useState('metrics')
  const [detailRows, setDetailRows] = useState([])
  const [detailInfoRows, setDetailInfoRows] = useState([])
  const [dateRange, setDateRange] = useState([fixedStart, fixedEnd])
  const [tradePage, setTradePage] = useState(1)

  const displayTrades = tradesSorted.length ? tradesSorted : trades

  const buildDetailRows = (currentOverview, currentTrades) => {
    if (!currentOverview || !currentTrades.length) {
      setDetailRows([])
      return
    }
    const ov = currentOverview
    const pnls = currentTrades.map((t) => Number(t.pnl || 0))

    const grossProfit = pnls.filter((p) => p > 0).reduce((s, p) => s + p, 0) / 2
    const grossLoss = pnls.filter((p) => p < 0).reduce((s, p) => s + p, 0) / 2
    const grossLossAbs = Math.abs(grossLoss)

    const netProfit = Number(ov.strategy_profit ?? 0)
    const unrealized = 0
    const profitFactor = Number(fixedProfitFactor ?? ov.profit_factor ?? 0)
    const totalTradesVal = Number(ov.total_trades ?? 0)
    const expectedPayoff = totalTradesVal ? netProfit / totalTradesVal : 0

    const rows = [
      {
        name: '初始资本',
        all: `${formatMoneyPlain(initial)} ${currencyLabel}`,
        long: `${formatMoneyPlain(initial)} ${currencyLabel}`,
        short: `0 ${currencyLabel}`,
      },
      {
        name: '未实现盈亏',
        all: `${formatMoney(unrealized)} ${currencyLabel}`,
        long: `${formatMoney(unrealized)} ${currencyLabel}`,
        short: `0 ${currencyLabel}`,
      },
      {
        name: '净利润',
        all: `${formatMoneyPlain(netProfit)} ${currencyLabel}  ${formatPct(ov.total_return_pct)}`,
        long: `${formatMoneyPlain(netProfit)} ${currencyLabel}  ${formatPct(ov.total_return_pct)}`,
        short: `0 ${currencyLabel}  0.00%`,
      },
      {
        name: '毛利润',
        all: `${formatMoneyPlain(grossProfit)} ${currencyLabel}  ${formatPct(
          (grossProfit / initial) * 100
        )}`,
        long: `${formatMoneyPlain(grossProfit)} ${currencyLabel}  ${formatPct(
          (grossProfit / initial) * 100
        )}`,
        short: `0 ${currencyLabel}  0.00%`,
      },
      {
        name: '毛亏损',
        all: `${formatMoneyPlain(grossLossAbs)} ${currencyLabel}  ${formatPct(
          (-grossLossAbs / initial) * 100
        )}`,
        long: `${formatMoneyPlain(grossLossAbs)} ${currencyLabel}  ${formatPct(
          (-grossLossAbs / initial) * 100
        )}`,
        short: `0 ${currencyLabel}  0.00%`,
      },
      {
        name: '盈利因子',
        all: profitFactor.toFixed(2),
        long: profitFactor.toFixed(2),
        short: '—',
      },
      {
        name: '已支付佣金',
        all: `0 ${currencyLabel}`,
        long: `0 ${currencyLabel}`,
        short: `0 ${currencyLabel}`,
      },
      {
        name: '预期收益',
        all: `${formatMoneyPlain(expectedPayoff)} ${currencyLabel}`,
        long: `${formatMoneyPlain(expectedPayoff)} ${currencyLabel}`,
        short: `0 ${currencyLabel}`,
      },
    ]

    setDetailRows(rows)
  }

  const buildDetailInfoRows = (currentOverview, currentTrades) => {
    if (!currentOverview || !currentTrades.length) {
      setDetailInfoRows([])
      return
    }
    const ov = currentOverview

    // 一买一卖算一笔：优先取“出场/止损/close”行；纳指用 signal=long close，也要识别
    const exitTrades = currentTrades.filter((t) => {
      const tp = String(t.trade_type || '')
      const sig = String(t.signal || '').toLowerCase()
      return (
        tp.includes('出') ||
        tp.includes('出场') ||
        tp.includes('止损') ||
        tp.toLowerCase().includes('close') ||
        sig.includes('close')
      )
    })
    const base = exitTrades.length ? exitTrades : currentTrades

    // 按 trade_no 去重统计（避免进/出两行导致翻倍）；若缺失 trade_no 用索引兜底
    const tradeMap = new Map()
    base.forEach((t, idx) => {
      const raw = t.trade_no
      const key = raw && Number(raw) ? Number(raw) : `idx_${idx}`
      tradeMap.set(key, { pnl: Number(t.pnl || 0), pct: Number(t.pnl_pct || 0) })
    })
    const items = Array.from(tradeMap.values())
    const total = items.length

    const basePnls = items.map((x) => x.pnl)
    const basePcts = items.map((x) => x.pct)
    const winCount = basePnls.filter((p) => p > 0).length
    const lossCount = basePnls.filter((p) => p < 0).length
    const flats = total - winCount - lossCount
    const winRate = total ? (winCount / total) * 100 : 0

    const netProfit = Number(ov.strategy_profit ?? 0)
    const avgTrade = total ? netProfit / total : 0
    const wins = basePnls.filter((p) => p > 0)
    const losses = basePnls.filter((p) => p < 0)
    const winPcts = basePcts.filter((_, i) => basePnls[i] > 0)
    const lossPcts = basePcts.filter((_, i) => basePnls[i] < 0)
    const avgWin = winCount ? wins.reduce((s, p) => s + p, 0) / winCount : 0
    const avgLoss = lossCount ? losses.reduce((s, p) => s + p, 0) / lossCount : 0
    const avgWinPct = winPcts.length ? winPcts.reduce((s, p) => s + p, 0) / winPcts.length : 0
    const avgLossPct = lossPcts.length ? lossPcts.reduce((s, p) => s + p, 0) / lossPcts.length : 0
    const winLossRate = avgLossPct !== 0 ? avgWinPct / Math.abs(avgLossPct) : 0

    const maxWin = wins.length ? Math.max(...wins) : 0
    const maxLoss = losses.length ? Math.min(...losses) : 0
    const maxWinIdx = wins.length ? basePnls.indexOf(maxWin) : -1
    const maxLossIdx = losses.length ? basePnls.indexOf(maxLoss) : -1
    const maxWinPct = maxWinIdx >= 0 ? basePcts[maxWinIdx] : 0
    const maxLossPct = maxLossIdx >= 0 ? basePcts[maxLossIdx] : 0

    const rows = [
      { name: '总交易', all: total, long: total, short: 0 },
      { name: '总未平仓交易', all: 0, long: 0, short: 0 },
      { name: '盈利交易', all: winCount, long: winCount, short: 0 },
      { name: '亏损交易', all: lossCount, long: lossCount, short: 0 },
      {
        name: '获利百分比',
        all: `${winRate.toFixed(2)}%`,
        long: `${winRate.toFixed(2)}%`,
        short: '—',
      },
      {
        name: '平均盈亏',
        all: `${avgTrade.toLocaleString()} ${currencyLabel}`,
        long: `${avgTrade.toLocaleString()} ${currencyLabel}`,
        short: `0 ${currencyLabel}`,
      },
      {
        name: '平均盈利交易',
        all: `${avgWin.toLocaleString()} ${currencyLabel}`,
        long: `${avgWin.toLocaleString()} ${currencyLabel}`,
        short: `0 ${currencyLabel}`,
      },
      {
        name: '平均亏损交易',
        all: `${avgLoss.toLocaleString()} ${currencyLabel}`,
        long: `${avgLoss.toLocaleString()} ${currencyLabel}`,
        short: `0 ${currencyLabel}`,
      },
      {
        name: '平均盈利率/平均亏损率',
        all: winLossRate.toFixed(3),
        long: winLossRate.toFixed(3),
        short: '—',
      },
      {
        name: '最大盈利交易',
        all: `${maxWin.toLocaleString()} ${currencyLabel}`,
        long: `${maxWin.toLocaleString()} ${currencyLabel}`,
        short: `0 ${currencyLabel}`,
      },
      {
        name: '最大盈利交易百分比',
        all: `${maxWinPct.toFixed(2)}%`,
        long: `${maxWinPct.toFixed(2)}%`,
        short: '0.00%',
      },
      {
        name: '最大亏损占总盈利的百分比例',
        all:
          netProfit !== 0
            ? `${((Math.abs(maxLoss) / Math.abs(netProfit)) * 100).toFixed(2)}%`
            : '0.00%',
        long:
          netProfit !== 0
            ? `${((Math.abs(maxLoss) / Math.abs(netProfit)) * 100).toFixed(2)}%`
            : '0.00%',
        short: '0.00%',
      },
      {
        name: '最大亏损交易',
        all: `${maxLoss.toLocaleString()} ${currencyLabel}`,
        long: `${maxLoss.toLocaleString()} ${currencyLabel}`,
        short: `0 ${currencyLabel}`,
      },
      {
        name: '最大亏损交易百分比',
        all: `${maxLossPct.toFixed(2)}%`,
        long: `${maxLossPct.toFixed(2)}%`,
        short: '0.00%',
      },
      {
        name: '盈亏平衡交易',
        all: flats,
        long: flats,
        short: 0,
      },
    ]

    setDetailInfoRows(rows)
  }

  const applyDateFilter = (_range, baseTrades, baseKlines, baseOverview) => {
    let filteredTradesLocal = baseTrades
    let filteredKlinesLocal = baseKlines
    const [startStr, endStr] = _range
    const start = new Date(startStr)
    const end = new Date(`${endStr}T23:59:59`)
    filteredTradesLocal = baseTrades.filter((t) => {
      const dt = new Date(t.trade_time)
      return dt >= start && dt <= end
    })
    filteredKlinesLocal = baseKlines.filter((k) => {
      const dt = new Date(k.timestamp)
      return dt >= start && dt <= end
    })

    setTrades(filteredTradesLocal)
    setKlines(filteredKlinesLocal)
    setTradePage(1)

    const computed = computeOverviewFromTrades(filteredTradesLocal, initial)
    // 后端 overview 为权威口径（尤其是本金/收益率）；本地 computed 仅用于兜底
    const merged = computed ? { ...computed, ...(baseOverview || {}) } : baseOverview
    setOverview(merged)

    const sorted = [...filteredTradesLocal].sort(
      (a, b) => new Date(b.trade_time).getTime() - new Date(a.trade_time).getTime()
    )
    setTradesSorted(sorted)

    buildDetailRows(merged, filteredTradesLocal)
    buildDetailInfoRows(merged, filteredTradesLocal)

    setTimeout(() => {
      renderKline(filteredKlinesLocal, filteredTradesLocal)
      renderEquity(filteredTradesLocal)
      renderProfitStruct(merged, filteredTradesLocal)
      renderContribution(filteredTradesLocal, filteredKlinesLocal)
      renderPnlHistogram(filteredTradesLocal)
      renderWinLoss(filteredTradesLocal)
    }, 0)
  }

  const loadData = async () => {
    setLoading(true)
    setLoadingSignals(true)
    try {
      const promises = [
        getOverview ? getOverview(true) : Promise.resolve(null),
        getTrades ? getTrades(true) : Promise.resolve([]),
      ]
      if (getKlines) {
        promises.push(getKlines(true))
      }
      const results = await Promise.all(promises)
      const ovRes = results[0]
      const tradesRes = Array.isArray(results[1]) ? results[1] : []
      const klinesRes = results[2] && Array.isArray(results[2]) ? results[2] : []

      setAllTrades(tradesRes)
      setAllKlines(klinesRes)

      const baseOverview = ovRes && typeof ovRes === 'object' ? ovRes : {}
      applyDateFilter([fixedStart, fixedEnd], tradesRes, klinesRes, baseOverview)
    } catch (e) {
      console.error('load strategy data error', e)
    } finally {
      setLoading(false)
      setLoadingSignals(false)
    }
  }

  const renderEquity = (tradesList) => {
    if (!equityChartRef.current || !tradesList.length) return
    if (!equityChart.current) {
      equityChart.current = echarts.init(equityChartRef.current)
    }
    const equityPct = tradesList.map((t) => {
      const pnl = t.cum_pnl || 0
      return ((initial + pnl) / initial - 1) * 100
    })
    const x = tradesList.map((t) => t.trade_time?.replace?.('T', ' ').slice(0, 16) || '')

    equityChart.current.setOption({
      grid: { left: 60, right: 40, top: 30, bottom: 40 },
      tooltip: {
        trigger: 'axis',
        valueFormatter: (v) => (v == null ? '' : `${Number(v).toFixed(2)}%`),
      },
      xAxis: {
        type: 'category',
        data: x,
        boundaryGap: false,
        axisLabel: {
          formatter: (v) => {
            const str = typeof v === 'string' ? v : x[Number(v)] || ''
            const d = new Date(str.replace(' ', 'T'))
            if (Number.isNaN(d.getTime())) return String(v)
            const year = d.getFullYear()
            const month = d.getMonth() + 1
            return `${year}年${month}月`
          },
        },
      },
      yAxis: {
        type: 'value',
        axisLabel: { formatter: (v) => `${Number(v).toFixed(0)}%` },
        splitLine: { show: true },
      },
      series: [
        {
          name: '策略收益',
          type: 'line',
          data: equityPct,
          smooth: true,
          showSymbol: false,
          lineStyle: { width: 2, color: '#10b981' },
          areaStyle: { opacity: 0.08, color: '#10b981' },
        },
      ],
    })
  }

  const renderKline = (klinesData, tradesList) => {
    if (!klineChartRef.current || !klinesData?.length) return
    if (!klineChart.current) {
      klineChart.current = echarts.init(klineChartRef.current)
    }

    const x = klinesData.map((k) =>
      (k.timestamp || '').toString().slice(0, 16).replace('T', ' ')
    )
    const ohlc = klinesData.map((k) => [k.open, k.close, k.low, k.high])

    const buyPoints = []
    const sellPoints = []

    const findIndexByTime = (tStr) => {
      const target = new Date(tStr).getTime()
      let idx = klinesData.findIndex((k) => new Date(k.timestamp).getTime() >= target)
      if (idx === -1) idx = klinesData.length - 1
      return idx
    }

    tradesList.forEach((tr) => {
      const idx = findIndexByTime(tr.trade_time)
      if (idx < 0) return
      const price = tr.price
      const tp = String(tr.trade_type || '')
      if (tp.includes('进') || tp.includes('入场')) {
        buyPoints.push([x[idx], price])
      } else if (tp.includes('出') || tp.includes('出场') || tp.includes('止损') || tp.toLowerCase().includes('close')) {
        sellPoints.push([x[idx], price])
      }
    })

    const total = x.length
    const barsPerMonthApprox = 12 * 30
    const barsToShow = Math.min(total, barsPerMonthApprox * 3)
    const startPct = total <= barsToShow ? 0 : ((total - barsToShow) / total) * 100

    klineChart.current.setOption({
      tooltip: { trigger: 'axis' },
      xAxis: {
        type: 'category',
        data: x,
        boundaryGap: true,
      },
      yAxis: {
        type: 'value',
        scale: true,
      },
      dataZoom: [
        { type: 'inside', start: startPct, end: 100 },
        { type: 'slider', start: startPct, end: 100, height: 18 },
      ],
      series: [
        {
          name: 'K线',
          type: 'candlestick',
          data: ohlc,
          itemStyle: {
            color: '#ec0000',
            color0: '#00b15d',
            borderColor: '#ec0000',
            borderColor0: '#00b15d',
          },
        },
        {
          name: '趋入',
          type: 'scatter',
          symbol: 'triangle',
          symbolSize: 16,
          itemStyle: {
            color: '#00b15d',
            borderColor: '#fff',
            borderWidth: 2,
          },
          label: {
            show: true,
            position: 'top',
            formatter: '趋入',
            color: '#00b15d',
            fontSize: 12,
            fontWeight: 'bold',
          },
          data: buyPoints,
        },
        {
          name: '趋出',
          type: 'scatter',
          symbol: 'triangle',
          symbolRotate: 180,
          symbolSize: 16,
          itemStyle: {
            color: '#ff4d4f',
            borderColor: '#fff',
            borderWidth: 2,
          },
          label: {
            show: true,
            position: 'bottom',
            formatter: '趋出',
            color: '#ff4d4f',
            fontSize: 12,
            fontWeight: 'bold',
          },
          data: sellPoints,
        },
      ],
    })
  }

  const renderProfitStruct = (currentOverview, currentTrades) => {
    if (!profitStructRef.current || !currentOverview || !currentTrades.length) return
    if (!profitStructChart.current) {
      profitStructChart.current = echarts.init(profitStructRef.current)
    }
    const items = getDedupExitTradeItems(currentTrades)
    const pnls = items.map((x) => Number(x.pnl || 0))
    const grossProfit = pnls.filter((p) => p > 0).reduce((s, p) => s + p, 0)
    const grossLossAbs = Math.abs(pnls.filter((p) => p < 0).reduce((s, p) => s + p, 0))
    const openPnl = 0
    const net = Number(currentOverview.strategy_profit ?? 0)
    let fee = grossProfit - grossLossAbs - net
    fee = Math.abs(fee)

    const labels = ['总盈利', '未平仓盈亏', '总亏损', '手续费', '总盈亏']
    const values = [grossProfit, openPnl, grossLossAbs, fee, net]
    const maxAbs = Math.max(...values.map((v) => Math.abs(v)))
    const step = 25000000
    const axisMax = Math.max(step, Math.ceil(maxAbs / step) * step)

    profitStructChart.current.setOption({
      grid: { left: 60, right: 20, top: 24, bottom: 30 },
      tooltip: {
        trigger: 'axis',
        valueFormatter: (v) =>
          v == null ? '' : `${Number(v).toLocaleString()} ${currencyLabel}`,
      },
      xAxis: { type: 'category', data: labels },
      yAxis: {
        type: 'value',
        max: axisMax,
        interval: axisMax / 4,
        axisLabel: {
          formatter: (v) => `${(v / 1000000).toFixed(0)}M`,
        },
      },
      series: [
        {
          type: 'bar',
          data: values,
          barWidth: '30%',
          itemStyle: {
            color: (params) => {
              const i = params.dataIndex
              if (i === 0) return '#10b981'
              if (i === 1) return '#3b82f6'
              if (i === 2) return '#ef4444'
              if (i === 3) return '#f59e0b'
              return '#6366f1'
            },
          },
        },
      ],
    })
  }

  const renderContribution = (currentTrades, currentKlines) => {
    if (!contributionRef.current || !currentTrades.length || !currentKlines.length) return
    if (!contributionChart.current) {
      contributionChart.current = echarts.init(contributionRef.current)
    }

    const firstTradeTime = new Date(currentTrades[0].trade_time).getTime()
    const lastTradeTime = new Date(currentTrades[currentTrades.length - 1].trade_time).getTime()
    const slicedKlines = currentKlines.filter((k) => {
      const ts = new Date(k.timestamp).getTime()
      return ts >= firstTradeTime && ts <= lastTradeTime
    })
    if (!slicedKlines.length) return

    const firstClose = slicedKlines[0].close || 1
    const bhPctSeries = slicedKlines.map((k) => (k.close / firstClose - 1) * 100)
    const bhMin = Math.min(...bhPctSeries)
    const bhMax = Math.max(...bhPctSeries)
    const bhCurrent = bhPctSeries[bhPctSeries.length - 1]

    const equityPct = currentTrades.map((t) => {
      const pnl = t.cum_pnl || 0
      return ((initial + pnl) / initial - 1) * 100
    })
    const stratMin = 0
    const stratMax = Math.max(...equityPct)
    const stratCurrent = equityPct[equityPct.length - 1]

    const yMin = Math.min(bhMin, stratMin) - 10
    const yMax = Math.max(bhMax, stratMax) + 10

    contributionChart.current.setOption({
      title: { text: '基准', left: 0, top: 0, textStyle: { fontSize: 13 } },
      grid: { left: 60, right: 60, top: 32, bottom: 40 },
      tooltip: {
        trigger: 'item',
        formatter: (p) => {
          const { seriesName, data } = p
          const label = data.label
          return `${seriesName}<br/>${label} ${Number(data.value[1]).toFixed(2)}%`
        },
      },
      legend: {
        bottom: 0,
        data: ['买入和持有的损益', '策略损益'],
      },
      xAxis: {
        type: 'category',
        data: ['买入持有', '策略损益'],
        axisLine: { show: true },
        axisTick: { show: true },
      },
      yAxis: {
        type: 'value',
        min: yMin,
        max: yMax,
        axisLabel: { formatter: (v) => `${v.toFixed(0)}%` },
        splitLine: { show: true },
      },
      series: [
        {
          name: '买入和持有的损益',
          type: 'scatter',
          symbolSize: 10,
          itemStyle: { color: '#f59e0b' },
          data: [
            { x: '买入持有', y: bhMin, label: '最小' },
            { x: '买入持有', y: bhCurrent, label: '当前' },
            { x: '买入持有', y: bhMax, label: '最大' },
          ].map((d) => ({
            value: [d.x, d.y],
            label: d.label,
          })),
          label: {
            show: true,
            position: 'left',
            formatter: (p) => `${p.data.label} ${Number(p.data.value[1]).toFixed(2)}%`,
          },
        },
        {
          name: '策略损益',
          type: 'scatter',
          symbolSize: 10,
          itemStyle: { color: '#3b82f6' },
          data: [
            { x: '策略损益', y: stratMin, label: '最小' },
            { x: '策略损益', y: stratCurrent, label: '当前' },
            { x: '策略损益', y: stratMax, label: '最大' },
          ].map((d) => ({
            value: [d.x, d.y],
            label: d.label,
          })),
          label: {
            show: true,
            position: 'right',
            formatter: (p) => `${p.data.label} ${Number(p.data.value[1]).toFixed(2)}%`,
          },
        },
      ],
    })
  }

  const renderPnlHistogram = (currentTrades) => {
    if (!pnlHistRef.current || !currentTrades.length) return
    if (!pnlHistChart.current) {
      pnlHistChart.current = echarts.init(pnlHistRef.current)
    }

    const exitTrades = currentTrades.filter((t) => {
      const tp = String(t.trade_type || '')
      return tp.includes('出') || tp.includes('出场') || tp.includes('止损') || tp.toLowerCase().includes('close')
    })
    const source = exitTrades.length ? exitTrades : currentTrades
    const pnls = source.map((t) => t.pnl_pct)

    const bins = []
    const labels = []
    const lossCounts = []
    const winCounts = []

    for (let v = -6; v < 16; v += 2) {
      const a = v
      const b = v + 2
      bins.push([a, b])
      labels.push(`${a}%`)
      lossCounts.push(pnls.filter((x) => x < 0 && x >= a && x < b).length)
      winCounts.push(pnls.filter((x) => x >= 0 && x >= a && x < b).length)
    }

    const avgLoss =
      pnls.filter((x) => x < 0).reduce((s, x) => s + x, 0) /
      Math.max(1, pnls.filter((x) => x < 0).length)
    const avgWin =
      pnls.filter((x) => x > 0).reduce((s, x) => s + x, 0) /
      Math.max(1, pnls.filter((x) => x > 0).length)

    pnlHistChart.current.setOption({
      grid: { left: 40, right: 20, top: 30, bottom: 40 },
      tooltip: { trigger: 'axis' },
      legend: {
        data: ['亏损', '获利', '平均亏损', '平均获利'],
        top: 0,
      },
      xAxis: {
        type: 'category',
        data: labels,
        axisLabel: { rotate: 45 },
      },
      yAxis: { type: 'value' },
      series: [
        {
          name: '亏损',
          type: 'bar',
          stack: 'pnl',
          data: lossCounts,
          itemStyle: { color: '#ef4444' },
        },
        {
          name: '获利',
          type: 'bar',
          stack: 'pnl',
          data: winCounts,
          itemStyle: { color: '#10b981' },
        },
        {
          name: '平均亏损',
          type: 'line',
          data: labels.map((_, idx) => {
            const [a, b] = bins[idx]
            return avgLoss >= a && avgLoss < b ? Math.max(...lossCounts, ...winCounts) : null
          }),
          lineStyle: { type: 'dashed', color: '#ef4444' },
          symbol: 'none',
        },
        {
          name: '平均获利',
          type: 'line',
          data: labels.map((_, idx) => {
            const [a, b] = bins[idx]
            return avgWin >= a && avgWin < b ? Math.max(...lossCounts, ...winCounts) : null
          }),
          lineStyle: { type: 'dashed', color: '#10b981' },
          symbol: 'none',
        },
      ],
      graphic: [
        {
          type: 'text',
          left: 'center',
          bottom: 4,
          style: {
            text: `平均亏损：${avgLoss.toFixed(2)}%    平均获利：${avgWin.toFixed(2)}%`,
            fill: '#6b7280',
            fontSize: 11,
          },
        },
      ],
    })
  }

  const renderWinLoss = (currentTrades) => {
    if (!winLossRef.current || !currentTrades.length) return
    if (!winLossChart.current) {
      winLossChart.current = echarts.init(winLossRef.current)
    }

    const items = getDedupExitTradeItems(currentTrades)
    const wins = items.filter((t) => t.pnl > 0).length
    const losses = items.filter((t) => t.pnl < 0).length
    const flats = items.length - wins - losses
    const total = items.length
    const winPct = total ? (wins / total) * 100 : 0
    const lossPct = total ? (losses / total) * 100 : 0
    const flatPct = total ? (flats / total) * 100 : 0

    winLossChart.current.setOption({
      tooltip: { trigger: 'item' },
      legend: {
        orient: 'vertical',
        right: 10,
        top: 'center',
        formatter(name) {
          if (name === '盈利') return `盈利   ${wins} 笔交易   ${winPct.toFixed(2)}%`
          if (name === '亏损') return `亏损   ${losses} 笔交易   ${lossPct.toFixed(2)}%`
          return `盈亏平衡   ${flats} 笔交易   ${flatPct.toFixed(2)}%`
        },
      },
      series: [
        {
          name: '胜/负比率',
          type: 'pie',
          radius: ['45%', '70%'],
          center: ['35%', '50%'],
          avoidLabelOverlap: false,
          label: {
            show: true,
            position: 'center',
            formatter: `${total}\n总交易`,
            fontSize: 16,
            lineHeight: 22,
          },
          data: [
            { value: wins, name: '盈利', itemStyle: { color: '#10b981' } },
            { value: losses, name: '亏损', itemStyle: { color: '#ef4444' } },
            { value: flats, name: '盈亏平衡', itemStyle: { color: '#f97316' } },
          ],
        },
      ],
    })
  }

  useEffect(() => {
    loadData()
    const handleResize = () => {
      if (equityChart.current) equityChart.current.resize()
      if (klineChart.current) klineChart.current.resize()
      if (profitStructChart.current) profitStructChart.current.resize()
      if (contributionChart.current) contributionChart.current.resize()
      if (pnlHistChart.current) pnlHistChart.current.resize()
      if (winLossChart.current) winLossChart.current.resize()
    }
    window.addEventListener('resize', handleResize)
    return () => {
      window.removeEventListener('resize', handleResize)
      if (equityChart.current) equityChart.current.dispose()
      if (klineChart.current) klineChart.current.dispose()
      if (profitStructChart.current) profitStructChart.current.dispose()
      if (contributionChart.current) contributionChart.current.dispose()
      if (pnlHistChart.current) pnlHistChart.current.dispose()
      if (winLossChart.current) winLossChart.current.dispose()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [title])

  const onShortcut = (type) => {
    const today = new Date().toISOString().slice(0, 10)
    let start = fixedStart
    if (type === 'month') {
      const d = new Date()
      start = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`
    } else if (type === '3m') {
      const d = new Date()
      d.setMonth(d.getMonth() - 3)
      start = d.toISOString().slice(0, 10)
    } else if (type === 'ytd') {
      start = `${new Date().getFullYear()}-01-01`
    } else if (type === 'all') {
      start = fixedStart
    }
    const range = [start, today]
    setDateRange(range)
    applyDateFilter(range, allTrades, allKlines, overview)
  }

  const onFilterClick = () => {
    applyDateFilter(dateRange, allTrades, allKlines, overview)
  }

  const onResetClick = () => {
    const range = [fixedStart, fixedEnd]
    setDateRange(range)
    applyDateFilter(range, allTrades, allKlines, overview)
  }

  const currentOverviewForSimpleCards = overview || computeOverviewFromTrades(displayTrades, initial)

  return (
    <div className="page strategy-page">
      <div className="title-row">
        <div className="title-main">
          <div className="title-top">
            <h2>{title}</h2>
            <button type="button" className="back-link" onClick={() => navigate('/strategies')}>
              返回策略矩阵
            </button>
          </div>
          <p className="sub">{subtitle}</p>
        </div>
        <div className="filter-row">
          <div className="date-range">
            <input
              type="date"
              className="date-input"
              value={dateRange[0]}
              onChange={(e) => setDateRange([e.target.value, dateRange[1]])}
            />
            <span className="date-sep">至</span>
            <input
              type="date"
              className="date-input"
              value={dateRange[1]}
              onChange={(e) => setDateRange([dateRange[0], e.target.value])}
            />
          </div>
          <div className="date-shortcuts">
            <button type="button" onClick={() => onShortcut('month')}>
              本月
            </button>
            <button type="button" onClick={() => onShortcut('3m')}>
              近3个月
            </button>
            <button type="button" onClick={() => onShortcut('ytd')}>
              本年
            </button>
            <button type="button" onClick={() => onShortcut('all')}>
              全部
            </button>
          </div>
          <button type="button" className="btn-filter" onClick={onFilterClick}>
            筛选
          </button>
          <button type="button" className="btn-reset" onClick={onResetClick}>
            重置
          </button>
        </div>
      </div>

      {getKlines && (
        <div className="chart-card">
          <div className="card-block-header">📍 价格 K 线</div>
          {loadingSignals ? (
            <div className="chart-loading">加载中...</div>
          ) : klines.length ? (
            <div ref={klineChartRef} className="kline-area" />
          ) : (
            <div className="chart-loading">暂无K线数据</div>
          )}
        </div>
      )}

      {currentOverviewForSimpleCards && (
        <div className="summary-grid">
          <div className="summary-card">
            <p>💰 总盈亏</p>
            <h3 className={currentOverviewForSimpleCards.total_return_pct >= 0 ? 'profit' : 'loss'}>
              {formatMoney(currentOverviewForSimpleCards.strategy_profit)} {currencyLabel}{' '}
              {formatPct(currentOverviewForSimpleCards.total_return_pct)}
            </h3>
          </div>
          <div className="summary-card">
            <p>🔢 总交易次数</p>
            <h3>{currentOverviewForSimpleCards.total_trades}</h3>
          </div>
          <div className="summary-card">
            <p>🎯 盈利交易占比</p>
            <h3 className={currentOverviewForSimpleCards.win_rate_pct >= 50 ? 'profit' : 'loss'}>
              {formatPct(currentOverviewForSimpleCards.win_rate_pct)}
            </h3>
          </div>
          <div className="summary-card">
            <p>⚖️ 盈亏比</p>
            <h3>{Number(fixedProfitFactor ?? currentOverviewForSimpleCards.profit_factor ?? 0).toFixed(2)}</h3>
          </div>
        </div>
      )}

      <div className="chart-card">
        <div className="card-block-header">📈 策略权益曲线</div>
        {loading ? <div className="chart-loading">加载中...</div> : <div ref={equityChartRef} className="chart-area" />}
      </div>

      <div className="tabs-container">
        <div className="tabs-row">
          <button
            type="button"
            className={`tab-btn ${activeTab === 'metrics' ? 'active' : ''}`}
            onClick={() => setActiveTab('metrics')}
          >
            指标
          </button>
          <button
            type="button"
            className={`tab-btn ${activeTab === 'trades' ? 'active' : ''}`}
            onClick={() => setActiveTab('trades')}
          >
            交易清单
          </button>
        </div>

        {activeTab === 'metrics' && (
          <>
            {overview && (
              <div className="analysis-row">
                <div className="chart-card analysis-card">
                  <div className="card-block-header">📈 利润结构</div>
                  <div ref={profitStructRef} className="chart-area-small" />
                </div>
                <div className="chart-card analysis-card">
                  <div className="card-block-header">📌 贡献</div>
                  <div ref={contributionRef} className="chart-area-small" />
                </div>
              </div>
            )}

            {trades.length > 0 && (
              <div className="analysis-row">
                <div className="chart-card analysis-card">
                  <div className="card-block-header">📊 收益分布</div>
                  <div ref={pnlHistRef} className="chart-area-small" />
                </div>
                <div className="chart-card analysis-card">
                  <div className="card-block-header">🥧 胜率结构</div>
                  <div ref={winLossRef} className="chart-area-small" />
                </div>
              </div>
            )}

            {detailRows.length > 0 && (
              <div className="chart-card metrics-card">
                <div className="card-block-header">📋 指标</div>
                <div className="metrics-table-wrap">
                  <table className="metrics-table">
                    <thead>
                      <tr>
                        <th>指标</th>
                        <th>全部</th>
                        <th>做多</th>
                        <th>做空</th>
                      </tr>
                    </thead>
                    <tbody>
                      {detailRows.map((row) => (
                        <tr key={row.name}>
                          <td>{row.name}</td>
                          <td>{row.all}</td>
                          <td>{row.long}</td>
                          <td>{row.short}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {detailInfoRows.length > 0 && (
              <div className="chart-card metrics-card">
                <div className="card-block-header">📊 详细信息</div>
                <div className="metrics-table-wrap">
                  <table className="metrics-table">
                    <thead>
                      <tr>
                        <th>指标</th>
                        <th>全部</th>
                        <th>做多</th>
                        <th>做空</th>
                      </tr>
                    </thead>
                    <tbody>
                      {detailInfoRows.map((row) => (
                        <tr key={row.name}>
                          <td>{row.name}</td>
                          <td>{row.all}</td>
                          <td>{row.long}</td>
                          <td>{row.short}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </>
        )}

        {activeTab === 'trades' && (
          <div className="chart-card trades-card">
            <div className="card-block-header">📊 交易明细</div>
            {!displayTrades.length && !loading && (
              <div className="empty">暂无回测交易数据，请先调用接口导入 CSV</div>
            )}
            {displayTrades.length > 0 && (() => {
              const PAGE_SIZE = 20
              // 先按 trade_no 分组配对，让进场和出场相邻
              const grouped = {}
              displayTrades.forEach(r => {
                if (!grouped[r.trade_no]) grouped[r.trade_no] = []
                grouped[r.trade_no].push(r)
              })
              // 每组内部：进场行排前，出场行排后
              const isEntry = (row) => {
                const tp = String(row.trade_type || '')
                const sig = String(row.signal || '').toLowerCase()
                return tp.includes('进') || tp.includes('进场') || tp.includes('入场') || sig.includes('buy') || sig.includes('long 1') || sig === '买' || sig.includes('买')
              }
              const sortedGroups = Object.keys(grouped)
                .map(Number)
                .sort((a, b) => b - a) // 按 trade_no 降序（最新在前）
              const reorderedRows = []
              sortedGroups.forEach(no => {
                const group = grouped[no]
                const entries = group.filter(r => isEntry(r))
                const exits = group.filter(r => !isEntry(r))
                // 出场行在前，进场行在后（与原始展示一致）
                exits.forEach(r => reorderedRows.push(r))
                entries.forEach(r => reorderedRows.push(r))
              })
              const totalPages = Math.ceil(sortedGroups.length / PAGE_SIZE)
              const pageNos = sortedGroups.slice((tradePage - 1) * PAGE_SIZE, tradePage * PAGE_SIZE)
              const pageRows = reorderedRows.filter(r => pageNos.includes(r.trade_no))
              return (
                <>
                  <div className="trades-table-wrap">
                    <table className="trades-table">
                      <thead>
                        <tr>
                          <th>交易 #</th>
                          <th>类型</th>
                          <th>信号</th>
                          <th>时间</th>
                          <th>价格</th>
                          <th>仓位大小</th>
                          <th>仓位价值 {currencyLabel}</th>
                          <th>净损益 {currencyLabel}</th>
                          <th>净损益 %</th>
                          <th>有利波动 {currencyLabel}</th>
                          <th>有利波动 %</th>
                          <th>不利波动 {currencyLabel}</th>
                          <th>不利波动 %</th>
                          <th>累计P&L {currencyLabel}</th>
                          <th>累计P&L %</th>
                        </tr>
                      </thead>
                      <tbody>
                        {pageRows.map((row, i) => {
                          const entry = isEntry(row)
                          // 计算同一 trade_no 在 pageRows 里出现的次数和当前是第几次
                          const sameNoRows = pageRows.filter((r) => r.trade_no === row.trade_no)
                          const sameNoCount = sameNoRows.length
                          const sameNoIndex = pageRows.slice(0, i).filter((r) => r.trade_no === row.trade_no).length
                          const showTradeNo = sameNoIndex === 0
                          return (
                            <tr key={i} className={entry ? 'row-entry' : ''}>
                              {showTradeNo && (
                                <td rowSpan={sameNoCount} style={{ verticalAlign: 'middle', fontWeight: 600, textAlign: 'center' }}>{row.trade_no}</td>
                              )}
                              <td>{row.trade_type}</td>
                              <td>{row.signal}</td>
                              <td>{row.trade_time?.replace?.('T', ' ').slice(0, 16)}</td>
                              <td>{row.price}</td>
                              <td>{row.position_qty}</td>
                              <td>{Number(row.position_value || 0).toLocaleString()}</td>
                              <td>{entry ? '--' : <span className={row.pnl >= 0 ? 'profit' : 'loss'}>{Number(row.pnl || 0).toLocaleString()}</span>}</td>
                              <td>{entry ? '--' : <span className={row.pnl_pct >= 0 ? 'profit' : 'loss'}>{(row.pnl_pct ?? 0).toFixed(2)}%</span>}</td>
                              <td>{entry ? '--' : (row.runup != null ? Number(row.runup || 0).toLocaleString() : '--')}</td>
                              <td>{entry ? '--' : (row.runup_pct != null ? `${Number(row.runup_pct || 0).toFixed(2)}%` : '--')}</td>
                              <td>{entry ? '--' : (row.drawdown != null ? Number(row.drawdown || 0).toLocaleString() : '--')}</td>
                              <td>{entry ? '--' : (row.drawdown_pct != null ? `${Number(row.drawdown_pct || 0).toFixed(2)}%` : '--')}</td>
                              <td>{entry ? '--' : (row.cum_pnl != null ? Number(row.cum_pnl || 0).toLocaleString() : '--')}</td>
                              <td>{entry ? '--' : (row.cum_pnl_pct != null ? `${Number(row.cum_pnl_pct || 0).toFixed(2)}%` : '--')}</td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                  {totalPages > 1 && (
                    <div className="trades-pagination">
                      <button type="button" disabled={tradePage === 1} onClick={() => setTradePage(1)}>"</button>
                      <button type="button" disabled={tradePage === 1} onClick={() => setTradePage((p) => p - 1)}>‹</button>
                      <span>第 {tradePage} / {totalPages} 页（共 {displayTrades.length} 条）</span>
                      <button type="button" disabled={tradePage === totalPages} onClick={() => setTradePage((p) => p + 1)}>›</button>
                      <button type="button" disabled={tradePage === totalPages} onClick={() => setTradePage(totalPages)}>"</button>
                    </div>
                  )}
                </>
              )
            })()}
          </div>
        )}
      </div>
    </div>
  )
}

