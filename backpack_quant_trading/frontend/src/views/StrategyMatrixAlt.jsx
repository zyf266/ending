import React, { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { BarChart3, Activity, TrendingUp, Wallet, Search, Filter, Plus, LayoutGrid, List, ChevronDown } from 'lucide-react'
import { StatCard } from '../components/StatCard'
import { StrategyCardMatrix } from '../components/StrategyCardMatrix'
import { getEthTrendOverview, getEthOnlyOverview, getPaxgTrendOverview, getNas100TrendOverview, getCrclOverview } from '../api/strategy'

const strategies = [
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
    to: '/strategies/us-momentum-crcl',
    icon: '🇺🇸',
    title: '美股动量轮动策略·CRCL',
    code: 'ML-USM',
    description: '专注 CRCL 等高波动资产，通过多周期协同过滤震荡噪音，精准捕捉由趋势扩张驱动的中长期波段，利用量化计算严控风险回撤，追求稳健的风险调整后收益。',
    status: '运行中',
    statusColor: 'bg-green-500 text-white',
    progress: 68,
    progressColor: '#3b82f6',
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
  {
    to: '/strategies/eth-trend',
    icon: '🏮',
    title: 'A股动量轮动策略',
    code: 'ML-AMR',
    description: '聚焦A股市场中的强势板块与个股，结合市场情绪指标与技术支撑进行动量捕捉，在震荡市依托强势因子做板块轮动，在趋势市集中持仓捕捉主升。',
    status: '测试中',
    statusColor: 'bg-blue-500 text-white',
    progress: 72,
    progressColor: '#10b981',
    riskIndex: '低风险',
    isRiskWarning: false,
  },
]

export default function StrategyMatrixAlt() {
  const path = useLocation().pathname
  const [overviews, setOverviews] = useState({})

  useEffect(() => {
    const reqs = [
      { key: 'eth', fn: getEthOnlyOverview },
      { key: 'hype', fn: getEthTrendOverview },
      { key: 'paxg', fn: getPaxgTrendOverview },
      { key: 'nas100', fn: getNas100TrendOverview },
      { key: 'crcl', fn: getCrclOverview },
    ]

    Promise.allSettled(reqs.map((r) => r.fn())).then((results) => {
      const next = {}
      results.forEach((r, i) => {
        if (r.status === 'fulfilled' && r.value) next[reqs[i].key] = r.value
      })
      setOverviews(next)
    })
  }, [])

  // 动态计算统计数据
  const runningCount = strategies.filter((s) => s.status === '运行中').length
  const overviewList = Object.values(overviews)
  const avgWinRate = overviewList.length
    ? (overviewList.reduce((s, o) => s + (o.win_rate_pct || 0), 0) / overviewList.length).toFixed(2)
    : '--'
  const totalProfit = overviewList.length
    ? overviewList.reduce((s, o) => s + (o.strategy_profit || 0), 0)
    : null
  const totalProfitStr = totalProfit != null
    ? totalProfit >= 1e6
      ? `$${(totalProfit / 1e6).toFixed(2)}M`
      : `$${(totalProfit / 1e3).toFixed(1)}K`
    : '--'

  const stats = [
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
      value: overviewList.length ? `${avgWinRate}%` : '--',
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

  const strategyKeys = ['eth', 'hype', 'crcl', 'paxg', 'nas100', null]
  const enrichedStrategies = strategies.map((s, i) => {
    const ov = overviews[strategyKeys[i]]
    // 固定展示值：最大回撤和盈亏比
    const fixedDrawdown = ['-3.48%', '-6.47%', '-10.89%', '-1.44%', '-4%', '--']
    const fixedProfitFactor = ['2.58', '2.84', '4.21', '2.25', '0.71', '--']
    if (!ov) return { ...s, annualReturn: '--', annualReturnLabel: '平均年化', drawdown: fixedDrawdown[i], profitFactor: fixedProfitFactor[i] }
    let annualReturn = '--'
    let annualReturnLabel = '平均年化'
    if (ov.total_return_pct != null && ov.start_date && ov.end_date) {
      const days = Math.max(1, (new Date(ov.end_date) - new Date(ov.start_date)) / 86400000)
      const years = days / 365
      if (years >= 0.75) {
        // 数据超过9个月才做年化
        const ann = ((1 + ov.total_return_pct / 100) ** (1 / years) - 1) * 100
        annualReturn = `${ann > 0 ? '+' : ''}${ann.toFixed(2)}%`
      } else {
        // 数据太短，显示区间总收益
        annualReturnLabel = '区间收益'
        annualReturn = `${ov.total_return_pct > 0 ? '+' : ''}${ov.total_return_pct.toFixed(2)}%`
      }
    }
    return {
      ...s,
      annualReturn,
      annualReturnLabel,
      drawdown: fixedDrawdown[i],
      profitFactor: fixedProfitFactor[i],
    }
  })

  return (
    <div className="strategy-matrix-alt min-h-full w-full bg-[#f9fafb]">
      <div className="mx-auto w-full max-w-[1920px] px-4 py-5">
        {/* Stats Grid */}
        <div className="stats-grid-strategy mb-6 grid grid-cols-2 gap-3 xl:grid-cols-4">
          {stats.map((stat, index) => (
            <StatCard
              key={index}
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

        {/* 搜索与筛选栏 */}
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

        {/* Strategies Grid - 2 columns */}
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
