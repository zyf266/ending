import React from 'react'
import StrategyDetail from './StrategyDetail'
import { getMuOverview, getMuTrades, getMuKlines } from '../api/strategy'

const title = '美股动量轮动策略·MU'
const subtitle =
  '聚焦美光科技（MU）等存储龙头，结合趋势强度、回撤过滤与风险预算，进行中短期动量轮动配置，捕捉 AI 存储超级周期与 HBM 放量行情。'

export default function UsMomentumMuStrategy() {
  return (
    <StrategyDetail
      title={title}
      subtitle={subtitle}
      currencyLabel="USD"
      initialCapital={1000000}
      startDate="2026-01-28"
      getOverview={getMuOverview}
      getTrades={getMuTrades}
      getKlines={getMuKlines}
    />
  )
}
