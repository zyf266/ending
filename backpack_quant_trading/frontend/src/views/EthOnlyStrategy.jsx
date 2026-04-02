import React from 'react'
import StrategyDetail from './StrategyDetail'
import { getEthOnlyOverview, getEthOnlyTrades, getEthOnlyKlines } from '../api/strategy'

const title = '沐龙加密趋势追踪策略 (ML-DTS) · ETH'
const subtitle =
  'ML-DTS 策略专注于以太坊（ETH）市场，捕捉由市场波动率扩张驱动的中长期趋势，通过多时间框架协同分析（日线、4 小时、2 小时），确保仅在趋势明朗时介入，避免震荡行情中的无效损耗。策略基于量化规则驱动，旨在通过纪律性执行实现风险调整后的超额收益（Alpha）。'

export default function EthOnlyStrategy() {
  return (
    <StrategyDetail
      title={title}
      subtitle={subtitle}
      currencyLabel="USDT"
      startDate="2024-01-01"
      initialCapital={30000000}
      fixedProfitFactor={2.58}
      getOverview={getEthOnlyOverview}
      getTrades={getEthOnlyTrades}
      getKlines={getEthOnlyKlines}
    />
  )
}
