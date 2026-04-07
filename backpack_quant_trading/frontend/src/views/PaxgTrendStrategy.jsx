import React from 'react'
import StrategyDetail from './StrategyDetail'
import { getPaxgTrendOverview, getPaxgTrendTrades, getPaxgTrendKlines } from '../api/strategy'

const title = '黄金波动率周期捕捉策略'
const subtitle =
  '专注于黄金（XAU/USD）市场的波动率周期捕捉。其逻辑基于黄金价格波动率的均值回归特性，通过识别波动率从收敛转向扩张的临界点，结合宏观趋势过滤，专注在价格回调至关键支撑区域时布局。策略坚持「低位等待、确定性介入」原则，避免追高操作，追求波动率扩张带来的确定性收益。'

export default function PaxgTrendStrategy() {
  return (
    <StrategyDetail
      title={title}
      subtitle={subtitle}
      currencyLabel="USD"
      initialCapital={2000000}
      startDate="2024-01-01"
      fixedProfitFactor={2.25}
      getOverview={getPaxgTrendOverview}
      getTrades={getPaxgTrendTrades}
      getKlines={getPaxgTrendKlines}
    />
  )
}
