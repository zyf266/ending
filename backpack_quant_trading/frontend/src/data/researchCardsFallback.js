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
      { key: 'bull', label: '乐观情景', probability: '30%', range_low: 150, range_high: 180 },
      { key: 'base', label: '基准情景', probability: '45%', range_low: 90, range_high: 120 },
      { key: 'bear', label: '悲观情景', probability: '25%', range_low: 50, range_high: 70 },
    ],
  },
  CRCL: {
    code: 'CRCL',
    name: 'Circle',
    tagline: '连接传统金融与加密世界的稳定币基石',
    report_date: '2026-05-20',
    scenarios: [
      { key: 'bull', label: '乐观情景', probability: '~35%', range_low: 180, range_high: 240 },
      { key: 'base', label: '基准情景', probability: '~45%', range_low: 120, range_high: 160 },
      { key: 'bear', label: '悲观情景', probability: '~20%', range_low: 60, range_high: 90 },
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
      { key: 'bull', label: '乐观情景', probability: '~35%', range_low: 1800, range_high: 2200 },
      { key: 'base', label: '基准情景', probability: '~45%', range_low: 1200, range_high: 1600 },
      { key: 'bear', label: '悲观情景', probability: '~20%', range_low: 600, range_high: 900 },
    ],
  },

  ONDO: {
    code: 'ONDO',
    name: 'Ondo Finance',
    tagline: 'RWA 基础设施领导者',
    report_date: '2026-05-21',
    scenarios: [
      { key: 'bull', label: '乐观情景', probability: '~25–30%', range_low: 1.8, range_high: 3.0 },
      { key: 'base', label: '基准情景', probability: '~50%', range_low: 0.85, range_high: 1.4 },
      { key: 'bear', label: '悲观情景', probability: '~20–25%', range_low: 0.2, range_high: 0.5 },
    ],
  },

  '000858': {
    code: '000858',
    name: '五粮液',
    tagline: '行业筑底企稳 · 高股息逆向优选标的',
    report_date: '2026-05-24',
    scenarios: [
      { key: 'bull', label: '乐观行情', probability: '30%', range_low: 128, range_high: 145 },
      { key: 'base', label: '基准行情', probability: '45%', range_low: 105, range_high: 118 },
      { key: 'bear', label: '悲观行情', probability: '25%', range_low: 65, range_high: 75 },
    ],
  },

  GOOGL: {
    code: 'GOOGL',
    name: '谷歌',
    tagline: 'AI基础设施与广告/云现金流机器',
    report_date: '2026-06-02',
    scenarios: [
      { key: 'bull', label: '乐观情景', probability: '15%', range_low: 480, range_high: 550 },
      { key: 'base', label: '基准情景', probability: '65%', range_low: 400, range_high: 450 },
      { key: 'bear', label: '悲观情景', probability: '20%', range_low: 280, range_high: 340 },
    ],
  },

  CRDO: {
    code: 'CRDO',
    name: 'Credo',
    tagline: 'AI数据中心高速互联“连接骨干”',
    report_date: '2026-06-02',
    scenarios: [
      { key: 'bull', label: '乐观情景', probability: '20%', range_low: 280, range_high: 350 },
      { key: 'base', label: '基准情景', probability: '55%', range_low: 210, range_high: 260 },
      { key: 'bear', label: '悲观情景', probability: '25%', range_low: 120, range_high: 170 },
    ],
  },
}
