import React from 'react'
import StrategyDetail from './StrategyDetail'
import { getNvdaOverview, getNvdaTrades, getNvdaKlines } from '../api/strategy'

const title = '美股动量轮动策略·NVDA'
const subtitle =
  '聚焦 NVDA 等 AI 龙头，结合趋势强度、回撤过滤与风险预算，进行中短期动量轮动配置，捕捉 AI 主升浪与 Blackwell 出货周期。'

export default function UsMomentumNvdaStrategy() {
  return (
    <StrategyDetail
      title={title}
      subtitle={subtitle}
      currencyLabel="USD"
      initialCapital={1000000}
      startDate="2025-10-24"
      getOverview={getNvdaOverview}
      getTrades={getNvdaTrades}
      getKlines={getNvdaKlines}
    />
  )
}
