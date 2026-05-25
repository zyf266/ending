/** API 不可用时的本地卡片兜底（与 data/*_research_card.json 一致） */
export const RESEARCH_CARDS_FALLBACK = {
  NVDA: {
    code: 'NVDA',
    name: '英伟达',
    tagline: 'AI时代的绝对霸主',
    report_date: '2026-05-20',
    scenarios: [
      { key: 'bull', label: '乐观情景', probability: '~40%', range_low: 320, range_high: 380 },
      { key: 'base', label: '基准情景', probability: '~45%', range_low: 240, range_high: 290 },
      { key: 'bear', label: '悲观情景', probability: '~15%', range_low: 140, range_high: 180 },
    ],
  },
  INTC: {
    code: 'INTC',
    name: '英特尔',
    tagline: 'AI时代战争转折与复苏',
    report_date: '2026-05-20',
    scenarios: [
      { key: 'bull', label: '乐观情景', probability: '~35%', range_low: 48, range_high: 58 },
      { key: 'base', label: '基准情景', probability: '~45%', range_low: 38, range_high: 46 },
      { key: 'bear', label: '悲观情景', probability: '~20%', range_low: 28, range_high: 34 },
    ],
  },
  CRCL: {
    code: 'CRCL',
    name: 'Circle',
    tagline: '连接传统金融与加密世界的稳定币基石',
    report_date: '2026-05-20',
    scenarios: [
      { key: 'bull', label: '乐观情景', probability: '~40%', range_low: 180, range_high: 220 },
      { key: 'base', label: '基准情景', probability: '~45%', range_low: 140, range_high: 170 },
      { key: 'bear', label: '悲观情景', probability: '~15%', range_low: 90, range_high: 120 },
    ],
  },
  ETH: {
    code: 'ETH',
    name: '以太坊',
    tagline: '全球智能合约与数字基础设施',
    report_date: '2026-05-20',
    scenarios: [
      { key: 'bull', label: '乐观情景', probability: '~40%', range_low: 4500, range_high: 5500 },
      { key: 'base', label: '基准情景', probability: '~45%', range_low: 3200, range_high: 4000 },
      { key: 'bear', label: '悲观情景', probability: '~15%', range_low: 2200, range_high: 2800 },
    ],
  },
  HYPE: {
    code: 'HYPE',
    name: 'Hyperliquid',
    tagline: '去中心化衍生品交易的领导者',
    report_date: '2026-05-20',
    scenarios: [
      { key: 'bull', label: '乐观情景', probability: '~40%', range_low: 35, range_high: 48 },
      { key: 'base', label: '基准情景', probability: '~45%', range_low: 24, range_high: 32 },
      { key: 'bear', label: '悲观情景', probability: '~15%', range_low: 14, range_high: 20 },
    ],
  },
  SNDK: {
    code: 'SNDK',
    name: 'SanDisk',
    tagline: 'AI存储周期节点的核心受益者',
    report_date: '2026-05-20',
    scenarios: [
      { key: 'bull', label: '乐观情景', probability: '~40%', range_low: 95, range_high: 115 },
      { key: 'base', label: '基准情景', probability: '~45%', range_low: 72, range_high: 88 },
      { key: 'bear', label: '悲观情景', probability: '~15%', range_low: 48, range_high: 60 },
    ],
  },
}
