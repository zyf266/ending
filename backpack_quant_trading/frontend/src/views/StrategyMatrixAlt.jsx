import React, { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { BarChart3, Activity, TrendingUp, Wallet, Percent, Search, Filter, Plus, LayoutGrid, List, ChevronDown } from 'lucide-react'
import { StatCard } from '../components/StatCard'
import { StrategyCardMatrix } from '../components/StrategyCardMatrix'
import { formatProfitFactor } from '../utils/formatProfitFactor'
import {
  getEthTrendOverview,
  getEthOnlyOverview,
  getPaxgTrendOverview,
  getNas100TrendOverview,
  getIntcOverview,
  getNvdaOverview,
  getAShareOverview,
  getMatrixYearlyReturns,
} from '../api/strategy'

const A_SHARE_KEYS = ['300308', '603986', '688146', '002837']
const DEFAULT_USD_CNY = 7.25

const strategies = [
  {
    to: '/strategies/us-momentum-nvda',
    icon: '🟢',
    title: '美股动量轮动策略·NVDA',
    code: 'ML-USM',
    description: '聚焦 NVDA 等 AI 龙头，结合趋势强度、回撤过滤与风险预算，进行中短期动量轮动配置，捕捉 AI 主升浪与 Blackwell 出货周期。',
    status: '运行中',
    statusColor: 'bg-green-500 text-white',
    progress: 68,
    progressColor: '#3b82f6',
    riskIndex: '低风险',
    isRiskWarning: false,
  },
  {
    to: '/strategies/us-momentum-intc',
    icon: '💠',
    title: '美股动量轮动策略·INTC',
    code: 'ML-USM',
    description: '聚焦 INTC 等半导体核心标的，结合趋势强度、回撤过滤与风险预算，进行中短期动量轮动配置，捕捉半导体板块主升浪行情。',
    status: '运行中',
    statusColor: 'bg-green-500 text-white',
    progress: 68,
    progressColor: '#3b82f6',
    riskIndex: '中风险',
    isRiskWarning: true,
  },
  {
    to: '/strategies/a-share-300308',
    icon: '🏮',
    title: 'A股动量轮动策略·中际旭创',
    code: 'ML-AMR',
    description: '聚焦中际旭创（300308）AI 光模块龙头，2H 动量轮动全仓复利，捕捉算力基建主升浪。',
    status: '运行中',
    statusColor: 'bg-green-500 text-white',
    progress: 72,
    progressColor: '#10b981',
    riskIndex: '中风险',
    isRiskWarning: true,
  },
  {
    to: '/strategies/a-share-603986',
    icon: '🏮',
    title: 'A股动量轮动策略·兆易创新',
    code: 'ML-AMR',
    description: '聚焦兆易创新（603986）存储龙头，2H 动量轮动全仓复利，捕捉存储超级周期与业绩爆发。',
    status: '运行中',
    statusColor: 'bg-green-500 text-white',
    progress: 72,
    progressColor: '#10b981',
    riskIndex: '中风险',
    isRiskWarning: true,
  },
  {
    to: '/strategies/a-share-688146',
    icon: '🏮',
    title: 'A股动量轮动策略·中船特气',
    code: 'ML-AMR',
    description: '聚焦中船特气（688146）半导体材料龙头，2H 动量轮动全仓复利，捕捉涨价与产能扩张周期。',
    status: '运行中',
    statusColor: 'bg-green-500 text-white',
    progress: 72,
    progressColor: '#10b981',
    riskIndex: '高风险',
    isRiskWarning: true,
  },
  {
    to: '/strategies/a-share-002837',
    icon: '🏮',
    title: 'A股动量轮动策略·英维克',
    code: 'ML-AMR',
    description: '聚焦英维克（002837）精密温控龙头，2H 动量轮动全仓复利，捕捉 AI 液冷与储能温控景气周期。',
    status: '运行中',
    statusColor: 'bg-green-500 text-white',
    progress: 72,
    progressColor: '#10b981',
    riskIndex: '中风险',
    isRiskWarning: true,
  },
  {
    to: '/strategies/eth-only',
    icon: '₿',
    title: '加密趋势追踪策略 · ETH',
    code: 'ML-DTS',
    description: '专注BTC/ETH/HYPE等主流加密货币，捕捉由波动率扩张驱动的中长期趋势，通过多周期协同过滤震荡噪音，追求稳健的风险调整后收益。',
    status: '运行中',
    statusColor: 'bg-green-500 text-white',
    progress: 98,
    progressColor: '#10b981',
    riskIndex: '低风险',
    isRiskWarning: false,
  },
  {
    to: '/strategies/eth-trend',
    icon: '🔥',
    title: '加密趋势追踪策略 · HYPE',
    code: 'ML-DTS',
    description: '专注BTC/ETH/HYPE等新兴加密货币，捕捉由波动率扩张驱动的中长期趋势，通过多周期协同过滤震荡噪音，追求稳健的风险调整后收益。',
    status: '运行中',
    statusColor: 'bg-green-500 text-white',
    progress: 98,
    progressColor: '#10b981',
    riskIndex: '中风险',
    isRiskWarning: true,
  },
  {
    to: '/strategies/paxg-trend',
    icon: '🥇',
    title: '黄金波动率周期捕捉策略',
    code: 'ML-GVCS',
    description: '专注 XAU/USD 波动率周期，结合宏观趋势与关键支撑区间布局，坚持「低位等待、确定性介入」原则，利用波动率扩张捕捉中期行情。',
    status: '已平仓',
    statusColor: 'bg-gray-400 text-white',
    progress: 80,
    progressColor: '#9ca3af',
    riskIndex: '低风险',
    isRiskWarning: false,
  },
  {
    to: '/strategies/nas100-trend',
    icon: '📈',
    title: '纳指波动率增强策略',
    code: 'ML-NAS',
    description: '聚焦纳斯达克指数的中长期趋势行情，结合趋势强度与回撤过滤，围绕关键趋势段进行分批建仓与风控，强调顺势持有与风险控制。',
    status: '已平仓',
    statusColor: 'bg-gray-400 text-white',
    progress: 60,
    progressColor: '#3b82f6',
    riskIndex: '低风险',
    isRiskWarning: false,
  },
]

/** 单策略：由总收益与自身回测区间复利年化（%）；区间不足 9 个月返回 null */
function computeAnnualizedPct(ov) {
  if (!ov || ov.total_return_pct == null || !ov.start_date || !ov.end_date) return null
  const ret = Number(ov.total_return_pct)
  if (!Number.isFinite(ret) || Math.abs(ret) < 1e-6) return null
  const days = Math.max(1, (new Date(ov.end_date) - new Date(ov.start_date)) / 86400000)
  const years = days / 365
  if (years < 0.75) return null
  return ((1 + ret / 100) ** (1 / years) - 1) * 100
}

const formatYearPct = (v) => {
  if (v == null || !Number.isFinite(Number(v))) return '--'
  const n = Number(v)
  return `${n > 0 ? '+' : ''}${n.toFixed(2)}%`
}

export default function StrategyMatrixAlt() {
  const path = useLocation().pathname
  const [overviews, setOverviews] = useState({})
  const [yearlyReturns, setYearlyReturns] = useState(null)

  useEffect(() => {
    const reqs = [
      { key: 'eth', fn: getEthOnlyOverview },
      { key: 'hype', fn: getEthTrendOverview },
      { key: 'paxg', fn: getPaxgTrendOverview },
      { key: 'nas100', fn: getNas100TrendOverview },
      { key: 'intc', fn: getIntcOverview },
      { key: 'nvda', fn: getNvdaOverview },
      { key: '300308', fn: () => getAShareOverview('300308') },
      { key: '603986', fn: () => getAShareOverview('603986') },
      { key: '688146', fn: () => getAShareOverview('688146') },
      { key: '002837', fn: () => getAShareOverview('002837') },
    ]

    Promise.allSettled([
      ...reqs.map((r) => r.fn()),
      getMatrixYearlyReturns(),
    ]).then((results) => {
      const next = {}
      reqs.forEach((r, i) => {
        if (results[i].status === 'fulfilled' && results[i].value) {
          next[r.key] = results[i].value
        }
      })
      setOverviews(next)
      const yr = results[reqs.length]
      if (yr.status === 'fulfilled' && yr.value) setYearlyReturns(yr.value)
    })
  }, [])

  const usdCny = Number(yearlyReturns?.usd_cny) > 0 ? Number(yearlyReturns.usd_cny) : DEFAULT_USD_CNY

  const profitToUsd = (key, profit) => {
    if (profit == null) return 0
    if (A_SHARE_KEYS.includes(key)) return Number(profit) / usdCny
    return Number(profit)
  }

  // 动态计算统计数据
  const runningCount = strategies.filter((s) => s.status === '运行中').length
  const overviewEntries = Object.entries(overviews)
  const avgWinRate = overviewEntries.length
    ? (overviewEntries.reduce((s, [, o]) => s + (o.win_rate_pct || 0), 0) / overviewEntries.length).toFixed(2)
    : '--'
  const totalProfit = overviewEntries.length
    ? overviewEntries.reduce((s, [key, o]) => s + profitToUsd(key, o.strategy_profit), 0)
    : null
  const totalProfitStr = totalProfit != null
    ? totalProfit >= 1e6
      ? `$${(totalProfit / 1e6).toFixed(2)}M`
      : `$${(totalProfit / 1e3).toFixed(1)}K`
    : '--'

  const yearRows = yearlyReturns?.years || {}
  const y2024 = yearRows['2024']
  const y2025 = yearRows['2025']
  const y2026 = yearRows['2026']

  const statsPrimary = [
    {
      title: '策略总数',
      value: String(strategies.length),
      icon: BarChart3,
      iconColor: 'bg-blue-500',
    },
    {
      title: '运行中策略',
      value: String(runningCount),
      percentage: `${Math.round((runningCount / strategies.length) * 100)}%`,
      icon: Activity,
      iconColor: 'bg-blue-400',
    },
    {
      title: '平均胜率',
      value: overviewEntries.length ? `${avgWinRate}%` : '--',
      icon: TrendingUp,
      iconColor: 'bg-blue-500',
    },
    {
      title: '累计收益',
      value: totalProfitStr,
      icon: Wallet,
      iconColor: 'bg-blue-500',
    },
  ]

  const statsYearly = [
    { title: '2024年化', value: formatYearPct(y2024?.annualized_pct) },
    { title: '2025年化', value: formatYearPct(y2025?.annualized_pct) },
    { title: '2026年化', value: formatYearPct(y2026?.annualized_pct) },
    { title: '2027年化', value: '--' },
  ]

  // 与 strategies 数组顺序一致
  const strategyKeys = ['nvda', 'intc', '300308', '603986', '688146', '002837', 'eth', 'hype', 'paxg', 'nas100']
  const useLiveDrawdown = new Set(['intc', 'nvda', '300308', '603986', '688146', '002837'])
  const enrichedStrategies = strategies.map((s, i) => {
    const key = strategyKeys[i]
    const ov = overviews[key]
    const fixedDrawdown = ['--', '--', '--', '--', '--', '--', '-3.48%', '-6.47%', '-1.44%', '-4%']
    const fixedProfitFactor = ['--', '--', '--', '--', '--', '--', '2.58', '2.84', '2.25', '0.71']
    const liveDrawdown = ov?.max_drawdown_pct != null
      ? `-${Number(ov.max_drawdown_pct).toFixed(2)}%`
      : null
    const drawdown = useLiveDrawdown.has(key) && liveDrawdown ? liveDrawdown : fixedDrawdown[i]
    const profitFactor =
      key === 'intc' ? '10.39' : key === 'nvda' ? '9.8' : (ov ? formatProfitFactor(ov.profit_factor) : fixedProfitFactor[i])
    if (!ov) return { ...s, annualReturn: '--', annualReturnLabel: '平均年化', drawdown, profitFactor }
    let annualReturn = '--'
    let annualReturnLabel = '平均年化'
    const ann = computeAnnualizedPct(ov)
    if (ann != null) {
      annualReturn = `${ann > 0 ? '+' : ''}${ann.toFixed(2)}%`
    } else if (ov.total_return_pct != null) {
      annualReturnLabel = '区间收益'
      annualReturn = `${ov.total_return_pct > 0 ? '+' : ''}${ov.total_return_pct.toFixed(2)}%`
    }
    return {
      ...s,
      annualReturn,
      annualReturnLabel,
      drawdown,
      profitFactor,
    }
  })

  return (
    <div className="strategy-matrix-alt min-h-full w-full">
      <div className="mx-auto w-full max-w-[1920px] px-4 py-5">
        <div className="stats-grid-strategy mb-3 grid grid-cols-2 gap-3 md:grid-cols-4">
          {statsPrimary.map((stat) => (
            <StatCard
              key={stat.title}
              title={stat.title}
              value={stat.value}
              change={stat.change}
              isPositive={stat.isPositive}
              percentage={stat.percentage}
              icon={stat.icon}
              iconColor={stat.iconColor}
            />
          ))}
        </div>
        <div className="stats-grid-strategy mb-6 grid grid-cols-2 gap-3 md:grid-cols-4">
          {statsYearly.map((stat) => (
            <StatCard
              key={stat.title}
              title={stat.title}
              value={stat.value}
              icon={Percent}
              iconColor="bg-indigo-500"
            />
          ))}
        </div>

        <div className="mb-6 flex flex-1 flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-0 flex-1 items-center gap-3">
            <div className="relative max-w-[400px] flex-1">
              <Search className="absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-[#9ca3af]" />
              <input
                type="text"
                placeholder="搜索策略名称或代码..."
                className="w-full rounded-lg border border-[#e5e7eb] bg-white py-2.5 pl-[40px] pr-4 text-sm outline-none transition-[border-color,box-shadow] focus:border-[#3b82f6] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.1)]"
              />
            </div>
            <button
              type="button"
              className="flex items-center gap-2 rounded-lg border border-[#e5e7eb] bg-white px-4 py-2.5 text-sm text-[#374151] transition-colors hover:bg-[#f9fafb]"
            >
              <Filter className="h-4 w-4 shrink-0" />
              <span>全部状态</span>
              <ChevronDown className="h-4 w-4 shrink-0" />
            </button>
          </div>
          <div className="flex items-center gap-2">
            <div className="flex rounded-lg bg-[#f3f4f6] p-1">
              <button
                type="button"
                className="rounded-md bg-[#3b82f6] p-2 text-white transition-colors hover:bg-[#2563eb]"
                title="网格"
              >
                <LayoutGrid className="h-4 w-4" />
              </button>
              <button
                type="button"
                className="rounded-md p-2 text-[#6b7280] transition-colors hover:bg-[#e5e7eb]"
                title="列表"
              >
                <List className="h-4 w-4" />
              </button>
            </div>
            <button
              type="button"
              className="flex items-center gap-2 rounded-lg bg-[#3b82f6] px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-[#2563eb]"
            >
              <Plus className="h-4 w-4" />
              <span>新建策略</span>
            </button>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {enrichedStrategies.map((s, index) => (
            <StrategyCardMatrix
              key={`${s.code}-${index}`}
              to={s.to}
              icon={s.icon}
              title={s.title}
              code={s.code}
              description={s.description}
              status={s.status}
              statusColor={s.statusColor}
              progress={s.progress}
              progressColor={s.progressColor}
              annualReturn={s.annualReturn}
              annualReturnLabel={s.annualReturnLabel}
              drawdown={s.drawdown}
              profitFactor={s.profitFactor}
              riskIndex={s.riskIndex}
              isRiskWarning={s.isRiskWarning}
              isActive={path === s.to}
            />
          ))}
        </div>
      </div>
    </div>
  )
}
