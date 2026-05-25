export const AI_STOCK_REPORTS = [
  {
    code: 'NVDA',
    name: '英伟达',
    price: 1200.0,
    currency: 'USD',
    updated_at: '2026-05-08',
    report: {
      business: {
        title: '业务情况',
        left: '行业前景、竞争地位（护城河）、市场份额/客户集中、产品线，成长性（收入/ASP/平均售价）与定价权等',
        middle:
          'AI 驱动的 GPU/NVLink/交换机、HBM 生态是最强护城河；供给偏紧背景下 ASP 与毛利保持高位。客户（云厂商/大模型）Capex 周期仍强，但需关注需求边际与竞品迭代。',
        right: '强（AI 基础设施核心受益者，高性能加速/软件生态护城河）',
        target: 2000,
      },
      finance: {
        title: '财务状况',
        left: '营收/利润增长、ROE/ROIC、自由现金流（FCF）、负债率',
        middle:
          '收入与利润高增，现金流强，资产负债表健康；FCF 充沛，具备持续回购/投入研发的能力。',
        right: '优秀',
      },
      valuation: {
        title: '估值指标',
        left: 'P/E（Trailing & Forward）、PEG、EV/EBITDA、P/B、P/S、FCF Yield',
        middle:
          '估值处于高位区间（市场给 AI 龙头溢价）；Forward 估值相对可接受，但对增长兑现要求高，回撤时更有安全边际。',
        right: '估值偏贵，等待回撤/业绩兑现',
      },
      profitability: {
        title: '盈利能力',
        left: '毛利率/净利率、EPS 增长、一致性',
        middle:
          '毛利率维持高位，盈利质量强；EPS 连续超预期但波动仍受周期影响（AI 需求与供给约束）。',
        right: '看多，关注周期与结构性增长',
      },
      technical: {
        title: '技术面',
        left: '趋势、支撑/阻力、成交量、RSI/MACD',
        middle:
          '上升趋势中但短期超买，高波动；关键支撑/阻力区间需配合成交量与均线确认。',
        right: '等待回调 1200~1250 区间企稳再上；跌破关键位则转弱',
        key_level: 1200,
      },
      catalysts: {
        title: '催化剂',
        left: '产品 pipeline、宏观/利率、政策、地缘、行业回暖',
        middle:
          'AI 服务器/网络升级、HBM 供给改善、软件订阅扩张；客户 Capex 指引、财报超预期、行业景气上行均为正向催化。',
        right: '关注财报与 Capex 指引',
      },
      external: {
        title: '被动影响',
        left: '上下游产业链影响/竞品与关联企业业绩联动',
        middle:
          '上游 HBM/晶圆/封测供给约束会影响交付；竞品（AMD/自研 ASIC）与客户自研进展可能压制溢价；宏观与利率变化影响风险偏好。',
        right: '优秀',
      },
      safety: {
        title: '安全边际',
        left: '下行风险、波动率',
        middle: '高波动：估值高位时回撤风险更大；需要严格仓位与止损纪律。',
        right: '高位无明显安全边际',
      },
      conclusion: {
        title: '总结',
        text: '现价分批建仓 + 波动做 T；财报/指引确认后加仓；严格止损与仓位控制。',
      },
    },
  },
]

export const getAiStockReportByCode = (code) => {
  const k = String(code || '').trim().toUpperCase()
  return AI_STOCK_REPORTS.find((x) => String(x.code).toUpperCase() === k) || null
}

