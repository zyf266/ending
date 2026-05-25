import React from 'react'
import StrategyDetail from './StrategyDetail'
import { getIntcOverview, getIntcTrades, getIntcKlines } from '../api/strategy'

const title = '美股动量轮动策略·INTC'
const subtitle =
  '聚焦 INTC 等半导体核心标的，结合趋势强度、回撤过滤与风险预算，进行中短期动量轮动配置，捕捉半导体板块主升浪行情。'

export default function UsMomentumIntcStrategy() {
  return (
    <StrategyDetail
      title={title}
      subtitle={subtitle}
      currencyLabel="USD"
      initialCapital={500000}
      startDate="2026-01-21"
      getOverview={getIntcOverview}
      getTrades={getIntcTrades}
      getKlines={getIntcKlines}
    />
  )
}
