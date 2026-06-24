import React from 'react'
import StrategyDetail from './StrategyDetail'
import { getAShareOverview, getAShareTrades, getAShareKlines } from '../api/strategy'

const CONFIG = {
  '300308': {
    name: '中际旭创',
    subtitle: '聚焦中际旭创等 AI 光模块龙头，2H 动量轮动捕捉算力基建主升浪，全仓滚仓复利执行。',
    initialCapital: 2000000,
  },
  '603986': {
    name: '兆易创新',
    subtitle: '聚焦兆易创新等存储/MCU 龙头，2H 动量轮动捕捉存储超级周期与业绩兑现行情。',
    initialCapital: 2000000,
  },
  '688146': {
    name: '中船特气',
    subtitle: '聚焦中船特气等半导体材料龙头，2H 动量轮动捕捉六氟化钨涨价与产能扩张周期。',
    initialCapital: 500000,
    startDate: '2026-05-01',
  },
  '002837': {
    name: '英维克',
    subtitle: '聚焦英维克等精密温控龙头，2H 动量轮动捕捉 AI 算力液冷与储能温控景气周期。',
    initialCapital: 500000,
  },
}

export default function AShareMomentumStrategy({ code }) {
  const cfg = CONFIG[code] || { name: code, subtitle: '', initialCapital: 2000000 }
  const slug = code
  return (
    <StrategyDetail
      title={`A股动量轮动策略·${cfg.name}`}
      subtitle={cfg.subtitle}
      currencyLabel="CNY"
      initialCapital={cfg.initialCapital}
      startDate={cfg.startDate || '2026-01-01'}
      getOverview={() => getAShareOverview(slug)}
      getTrades={() => getAShareTrades(slug)}
      getKlines={() => getAShareKlines(slug)}
    />
  )
}
