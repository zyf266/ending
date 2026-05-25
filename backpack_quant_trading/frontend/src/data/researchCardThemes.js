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
