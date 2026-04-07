import React from 'react'
import StrategyDetail from './StrategyDetail'
import { getEthTrendOverview, getEthTrendTrades, getEthTrendKlines } from '../api/strategy'

const title = '加密趋势追踪策略'
const subtitle =
  '专注于主流加密货币市场（如 BTC、ETH、HYPE）。其核心理念是捕捉由市场波动率扩张驱动的中长期趋势，通过多时间框架协同分析（如日线、4 小时、2 小时），确保仅在趋势明朗时介入，避免震荡行情中的无效损耗。策略基于量化规则驱动，旨在通过纪律性执行实现风险调整后的超额收益（Alpha）。'

export default function EthTrendStrategy() {
  return (
    <StrategyDetail
      title={title}
      subtitle={subtitle}
      currencyLabel="USDT"
      startDate="2025-02-21"
      initialCapital={1000000}
      fixedProfitFactor={2.84}
      getOverview={getEthTrendOverview}
      getTrades={getEthTrendTrades}
      getKlines={getEthTrendKlines}
    />
  )
}
