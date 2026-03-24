import React from 'react'
import StrategyDetail from './StrategyDetail'
import { getNas100TrendOverview, getNas100TrendTrades, getNas100TrendKlines } from '../api/strategy'

const title = '沐龙纳指趋势追踪增强策略 (ML-NAS)'
const subtitle =
  'ML-NAS 策略聚焦纳斯达克指数的中长期趋势行情，结合趋势强度与回撤过滤，围绕关键趋势段进行分批建仓与风控，强调顺势持有与风险控制。'

export default function Nas100TrendStrategy() {
  return (
    <StrategyDetail
      title={title}
      subtitle={subtitle}
      currencyLabel="USD"
      initialCapital={2000000}
      startDate="2024-01-01"
      getOverview={getNas100TrendOverview}
      getTrades={getNas100TrendTrades}
      getKlines={getNas100TrendKlines}
    />
  )
}
