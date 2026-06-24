import React from 'react'
import StrategyDetail from './StrategyDetail'
import { getAShareOverview, getAShareTrades, getAShareKlines } from '../api/strategy'

const CONFIG = {
  '300308': {
    name: '中际旭创',
    subtitle: '聚焦中际旭创等 AI 光模块龙头，2H 动量轮动捕捉算力基建主升浪，全仓滚仓复利执行。',
  },
  '603986': {
    name: '兆易创新',
    subtitle: '聚焦兆易创新等存储/MCU 龙头，2H 动量轮动捕捉存储超级周期与业绩兑现行情。',
  },
  '688146': {
    name: '中船特气',
    subtitle: '聚焦中船特气等半导体材料龙头，2H 动量轮动捕捉六氟化钨涨价与产能扩张周期。',
  },
}

export default function AShareMomentumStrategy({ code }) {
  const cfg = CONFIG[code] || { name: code, subtitle: '' }
  const slug = code
  return (
    <StrategyDetail
      title={`A股动量轮动策略·${cfg.name}`}
      subtitle={cfg.subtitle}
      currencyLabel="CNY"
      initialCapital={2000000}
      startDate="2026-01-01"
      getOverview={() => getAShareOverview(slug)}
      getTrades={() => getAShareTrades(slug)}
      getKlines={() => getAShareKlines(slug)}
    />
  )
}
