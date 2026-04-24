import React from 'react'
import StrategyDetail from './StrategyDetail'
import { getCrclOverview, getCrclTrades, getCrclKlines } from '../api/strategy'

const title = '美股动量轮动策略·CRCL'
const subtitle =
  '聚焦美股核心指数与强势板块，结合趋势强度、回撤过滤与风险预算，进行中短期动量轮动配置。捕捉CRCL等高动量标的的主升浪行情。'

export default function UsMomentumCrclStrategy() {
  return (
    <StrategyDetail
      title={title}
      subtitle={subtitle}
      currencyLabel="USD"
      initialCapital={1000000}
      startDate="2026-02-13"
      getOverview={getCrclOverview}
      getTrades={getCrclTrades}
      getKlines={getCrclKlines}
    />
  )
}
