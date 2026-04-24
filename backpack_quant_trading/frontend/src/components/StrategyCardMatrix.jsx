import React from 'react'
import { Link } from 'react-router-dom'
import { CircularProgress } from './CircularProgress'
import { TrendingUp, TrendingDown, Target, AlertTriangle } from 'lucide-react'

function MetricCard({ icon, label, value, isPositive, bgColor }) {
  const valueColor =
    isPositive === undefined
      ? 'text-gray-900'
      : isPositive
        ? 'text-green-600'
        : 'text-red-600'

  return (
    <div className={`rounded-lg p-3.5 ${bgColor}`}>
      <div className="mb-1.5 flex items-center gap-2">
        {icon}
        <span className="text-sm text-gray-500">{label}</span>
      </div>
      <div className={`text-base font-semibold ${valueColor}`}>{value}</div>
    </div>
  )
}

export function StrategyCardMatrix({
  to,
  title,
  code,
  description,
  status,
  statusColor,
  progress,
  progressColor,
  annualReturn,
  annualReturnLabel = '平均年化',
  drawdown,
  profitFactor,
  riskIndex,
  isRiskWarning = false,
  isActive,
  icon,
}) {
  const derivedStatusColor = (() => {
    const s = String(status || '')
    if (s.includes('运行')) return 'bg-green-500 text-white'
    if (s.includes('测试')) return 'bg-blue-500 text-white'
    if (s.includes('已平仓')) return 'bg-gray-400 text-white'
    return statusColor || 'bg-gray-100 text-gray-700'
  })()

  const derivedProgressColor = (() => {
    const s = String(status || '')
    if (s.includes('运行')) return '#10b981'
    if (s.includes('测试')) return '#3b82f6'
    return progressColor || '#3b82f6'
  })()

  const content = (
    <>
      <div className="mb-4 flex items-start justify-between">
        <div className="flex items-center gap-3 flex-1">
          {icon && (
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-blue-50 to-indigo-100 text-2xl shadow-sm">
              {icon}
            </div>
          )}
          <div className="min-w-0">
            <h3 className="mb-1 text-xl font-bold text-gray-900">{title}</h3>
            {/* code 已隐藏 */}
          </div>
        </div>
        <div className="flex items-center gap-3">
          <span className={`rounded-full px-3 py-1.5 text-sm font-medium ${derivedStatusColor}`}>
            {status}
          </span>
        </div>
      </div>
      <p className="strategy-card-desc mb-4 line-clamp-2 text-base leading-relaxed text-[#6b7280]">{description}</p>
      <div className="grid grid-cols-2 gap-3">
        <MetricCard
          icon={<TrendingUp className="h-5 w-5 text-blue-500" />}
          label={annualReturnLabel}
          value={annualReturn}
          isPositive={true}
          bgColor="bg-blue-50"
        />
        <MetricCard
          icon={<TrendingDown className="h-5 w-5 text-red-500" />}
          label="最大回撤"
          value={drawdown}
          isPositive={false}
          bgColor="bg-red-50"
        />
        <MetricCard
          icon={<Target className="h-5 w-5 text-green-600" />}
          label="盈亏比"
          value={profitFactor}
          bgColor="bg-green-50"
        />
        <MetricCard
          icon={
            <AlertTriangle
              className={`h-5 w-5 ${isRiskWarning ? 'text-red-500' : 'text-green-600'}`}
            />
          }
          label="风险指数"
          value={riskIndex}
          bgColor={isRiskWarning ? 'bg-red-50' : 'bg-green-50'}
        />
      </div>
    </>
  )

  const className = `strategy-card-matrix block rounded-xl border bg-white p-6 text-inherit no-underline transition-all duration-200 ${
    isActive ? 'border-[#3b82f6] shadow-[0_10px_25px_rgba(59,130,246,0.15)]' : 'border-[#e5e7eb] hover:border-[#3b82f6] hover:shadow-[0_10px_25px_rgba(59,130,246,0.15)] hover:-translate-y-0.5'
  }`

  if (to) {
    return (
      <Link to={to} className={className}>
        {content}
      </Link>
    )
  }
  return <div className={className}>{content}</div>
}
