/** 盈亏比展示：无亏损时显示 ∞ */
export function formatProfitFactor(value) {
  if (value == null || value === '') return '∞'
  const n = Number(value)
  if (!Number.isFinite(n)) return '∞'
  if (n > 9999) return '∞'
  return n.toFixed(2)
}
