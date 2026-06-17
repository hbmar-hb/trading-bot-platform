// Shared color helpers for Chart canvas overlays

export function hexToRgba(hex, alpha) {
  if (!hex || hex === 'transparent') return 'transparent'
  if (hex.startsWith('rgba(') || hex.startsWith('rgb(')) return hex

  const h = hex.startsWith('#') ? hex.slice(1) : hex
  if (h.length < 6) return hex

  const r = parseInt(h.slice(0, 2), 16)
  const g = parseInt(h.slice(2, 4), 16)
  const b = parseInt(h.slice(4, 6), 16)
  const a = alpha !== undefined
    ? alpha
    : (h.length >= 8 ? parseInt(h.slice(6, 8), 16) / 255 : 1)

  return `rgba(${r},${g},${b},${a.toFixed(3)})`
}
