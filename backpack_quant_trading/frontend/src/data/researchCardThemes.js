/** 与 PDF 研报封面一致的品牌主题色（卡片 logo / 顶栏 / 完整研报封面） */
const DEFAULT_THEME = {
  accent: '#6366f1',
  accent2: '#818cf8',
  badgeFrom: '#4f46e5',
  badgeTo: '#6366f1',
  topFrom: '#f8fafc',
  topTo: '#f1f5f9',
  border: 'rgba(99, 102, 241, 0.28)',
  borderHover: 'rgba(99, 102, 241, 0.42)',
  glow: 'rgba(99, 102, 241, 0.14)',
  shadow: 'rgba(79, 70, 229, 0.35)',
  tagline: '#0f172a',
}

export const RESEARCH_CARD_THEMES = {
  /** NVIDIA 绿 */
  NVDA: {
    accent: '#76B900',
    accent2: '#5a8f00',
    badgeFrom: '#76B900',
    badgeTo: '#3d6b00',
    topFrom: '#f4fce8',
    topTo: '#e5f5d0',
    border: 'rgba(118, 185, 0, 0.32)',
    borderHover: 'rgba(118, 185, 0, 0.5)',
    glow: 'rgba(118, 185, 0, 0.22)',
    shadow: 'rgba(61, 107, 0, 0.38)',
    tagline: '#1a3d00',
  },
  /** Intel 蓝 */
  INTC: {
    accent: '#0071C5',
    accent2: '#00A0E3',
    badgeFrom: '#0071C5',
    badgeTo: '#004280',
    topFrom: '#eff6ff',
    topTo: '#dbeafe',
    border: 'rgba(0, 113, 197, 0.3)',
    borderHover: 'rgba(0, 113, 197, 0.48)',
    glow: 'rgba(0, 113, 197, 0.16)',
    shadow: 'rgba(0, 66, 128, 0.35)',
    tagline: '#0c4a6e',
  },
  /** Circle 深绿 + 薄荷光带 */
  CRCL: {
    accent: '#4ade80',
    accent2: '#0e3d26',
    badgeFrom: '#22c55e',
    badgeTo: '#065f46',
    topFrom: '#ecfdf5',
    topTo: '#d1fae5',
    border: 'rgba(34, 197, 94, 0.3)',
    borderHover: 'rgba(34, 197, 94, 0.48)',
    glow: 'rgba(74, 222, 128, 0.2)',
    shadow: 'rgba(6, 95, 70, 0.35)',
    tagline: '#064e3b',
  },
  /** SanDisk 金琥珀 */
  SNDK: {
    accent: '#D4AF37',
    accent2: '#b8860b',
    badgeFrom: '#e8c547',
    badgeTo: '#92700c',
    topFrom: '#fffbeb',
    topTo: '#fef3c7',
    border: 'rgba(212, 175, 55, 0.35)',
    borderHover: 'rgba(180, 140, 30, 0.5)',
    glow: 'rgba(212, 175, 55, 0.22)',
    shadow: 'rgba(146, 112, 12, 0.38)',
    tagline: '#422006',
  },
  /** Ethereum 紫 */
  ETH: {
    accent: '#9D50BB',
    accent2: '#6b21a8',
    badgeFrom: '#a855f7',
    badgeTo: '#6b21a8',
    topFrom: '#faf5ff',
    topTo: '#f3e8ff',
    border: 'rgba(157, 80, 187, 0.32)',
    borderHover: 'rgba(107, 33, 168, 0.45)',
    glow: 'rgba(157, 80, 187, 0.2)',
    shadow: 'rgba(107, 33, 168, 0.35)',
    tagline: '#581c87',
  },
  /** Hyperliquid 青 + 紫 */
  HYPE: {
    accent: '#4FD1C5',
    accent2: '#9F7AEA',
    badgeFrom: '#2dd4bf',
    badgeTo: '#7c3aed',
    topFrom: '#f0fdfa',
    topTo: '#f5f3ff',
    border: 'rgba(79, 209, 197, 0.32)',
    borderHover: 'rgba(124, 58, 237, 0.4)',
    glow: 'rgba(79, 209, 197, 0.18)',
    shadow: 'rgba(45, 212, 191, 0.35)',
    tagline: '#134e4a',
  },
  /** 兆易创新 半导体红 */
  '603986': {
    accent: '#e11d48',
    accent2: '#f97316',
    badgeFrom: '#e11d48',
    badgeTo: '#c2410c',
    topFrom: '#fff1f2',
    topTo: '#fff7ed',
    border: 'rgba(225, 29, 72, 0.28)',
    borderHover: 'rgba(249, 115, 22, 0.38)',
    glow: 'rgba(225, 29, 72, 0.14)',
    shadow: 'rgba(194, 65, 12, 0.35)',
    tagline: '#881337',
  },
  /** 中船特气 深海蓝 */
  '688146': {
    accent: '#0369a1',
    accent2: '#0ea5e9',
    badgeFrom: '#0369a1',
    badgeTo: '#1e3a8a',
    topFrom: '#f0f9ff',
    topTo: '#e0f2fe',
    border: 'rgba(3, 105, 161, 0.28)',
    borderHover: 'rgba(14, 165, 233, 0.38)',
    glow: 'rgba(3, 105, 161, 0.14)',
    shadow: 'rgba(30, 58, 138, 0.35)',
    tagline: '#0c4a6e',
  },
  /** 中际旭创 光模块紫蓝 */
  '300308': {
    accent: '#7c3aed',
    accent2: '#2563eb',
    badgeFrom: '#7c3aed',
    badgeTo: '#1d4ed8',
    topFrom: '#f5f3ff',
    topTo: '#eff6ff',
    border: 'rgba(124, 58, 237, 0.28)',
    borderHover: 'rgba(37, 99, 235, 0.38)',
    glow: 'rgba(124, 58, 237, 0.14)',
    shadow: 'rgba(29, 78, 216, 0.35)',
    tagline: '#4c1d95',
  },
  /** Google 经典四色（蓝/红） */
  GOOGL: {
    accent: '#1a73e8',
    accent2: '#ea4335',
    badgeFrom: '#1a73e8',
    badgeTo: '#ea4335',
    topFrom: '#eff6ff',
    topTo: '#fff1f2',
    border: 'rgba(26, 115, 232, 0.28)',
    borderHover: 'rgba(234, 67, 53, 0.35)',
    glow: 'rgba(26, 115, 232, 0.12)',
    shadow: 'rgba(26, 115, 232, 0.32)',
    tagline: '#0b3d91',
  },
  /** Credo 蓝青（高速互联） */
  CRDO: {
    accent: '#0ea5e9',
    accent2: '#14b8a6',
    badgeFrom: '#0ea5e9',
    badgeTo: '#14b8a6',
    topFrom: '#eff6ff',
    topTo: '#f0fdfa',
    border: 'rgba(14, 165, 233, 0.28)',
    borderHover: 'rgba(20, 184, 166, 0.38)',
    glow: 'rgba(14, 165, 233, 0.12)',
    shadow: 'rgba(3, 105, 161, 0.32)',
    tagline: '#0c4a6e',
  },
  /** Marvell 红 */
  MRVL: {
    accent: '#e11d48',
    accent2: '#be123c',
    badgeFrom: '#e11d48',
    badgeTo: '#9f1239',
    topFrom: '#fff1f2',
    topTo: '#ffe4e6',
    border: 'rgba(225, 29, 72, 0.28)',
    borderHover: 'rgba(190, 18, 60, 0.4)',
    glow: 'rgba(225, 29, 72, 0.14)',
    shadow: 'rgba(159, 18, 57, 0.32)',
    tagline: '#881337',
  },
  /** Micron 黑金 */
  MU: {
    accent: '#ca8a04',
    accent2: '#1c1917',
    badgeFrom: '#ca8a04',
    badgeTo: '#292524',
    topFrom: '#fffbeb',
    topTo: '#f5f5f4',
    border: 'rgba(202, 138, 4, 0.32)',
    borderHover: 'rgba(28, 25, 23, 0.35)',
    glow: 'rgba(202, 138, 4, 0.16)',
    shadow: 'rgba(41, 37, 36, 0.35)',
    tagline: '#422006',
  },
  /** Microsoft 四色蓝 */
  MSFT: {
    accent: '#0078d4',
    accent2: '#00bcf2',
    badgeFrom: '#0078d4',
    badgeTo: '#005a9e',
    topFrom: '#eff6ff',
    topTo: '#e0f2fe',
    border: 'rgba(0, 120, 212, 0.28)',
    borderHover: 'rgba(0, 90, 158, 0.42)',
    glow: 'rgba(0, 120, 212, 0.12)',
    shadow: 'rgba(0, 90, 158, 0.32)',
    tagline: '#0c4a6e',
  },
  /** Nokia 蓝 */
  NOK: {
    accent: '#124191',
    accent2: '#00a9e0',
    badgeFrom: '#124191',
    badgeTo: '#00a9e0',
    topFrom: '#eff6ff',
    topTo: '#ecfeff',
    border: 'rgba(18, 65, 145, 0.28)',
    borderHover: 'rgba(0, 169, 224, 0.38)',
    glow: 'rgba(18, 65, 145, 0.12)',
    shadow: 'rgba(18, 65, 145, 0.32)',
    tagline: '#1e3a8a',
  },
  /** Rocket Lab 深空蓝 */
  RKLB: {
    accent: '#1e40af',
    accent2: '#7c3aed',
    badgeFrom: '#1e40af',
    badgeTo: '#4c1d95',
    topFrom: '#eff6ff',
    topTo: '#f5f3ff',
    border: 'rgba(30, 64, 175, 0.28)',
    borderHover: 'rgba(124, 58, 237, 0.38)',
    glow: 'rgba(30, 64, 175, 0.14)',
    shadow: 'rgba(76, 29, 149, 0.32)',
    tagline: '#1e3a8a',
  },
  /** IBM 条纹蓝 */
  IBM: {
    accent: '#054ada',
    accent2: '#0f62fe',
    badgeFrom: '#054ada',
    badgeTo: '#001d6c',
    topFrom: '#eff6ff',
    topTo: '#dbeafe',
    border: 'rgba(5, 74, 218, 0.28)',
    borderHover: 'rgba(15, 98, 254, 0.4)',
    glow: 'rgba(5, 74, 218, 0.12)',
    shadow: 'rgba(0, 29, 108, 0.32)',
    tagline: '#1e3a8a',
  },
}

export function getResearchCardTheme(code) {
  const key = String(code || '').toUpperCase().trim()
  return RESEARCH_CARD_THEMES[key] || DEFAULT_THEME
}

export function researchCardThemeClass(code) {
  const key = String(code || '').toUpperCase().trim()
  if (RESEARCH_CARD_THEMES[key]) return `ais-rc-theme-${key.toLowerCase()}`
  return 'ais-rc-theme-default'
}

/** 注入 CSS 变量，供 AiStock.css 使用 */
export function researchCardThemeStyle(code) {
  const t = getResearchCardTheme(code)
  return {
    '--rc-accent': t.accent,
    '--rc-accent-2': t.accent2,
    '--rc-badge-from': t.badgeFrom,
    '--rc-badge-to': t.badgeTo,
    '--rc-top-from': t.topFrom,
    '--rc-top-to': t.topTo,
    '--rc-border': t.border,
    '--rc-border-hover': t.borderHover,
    '--rc-glow': t.glow,
    '--rc-shadow': t.shadow,
    '--rc-tagline': t.tagline,
  }
}
