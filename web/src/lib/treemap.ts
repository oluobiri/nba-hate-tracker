// A squarified treemap: items laid into a box as rectangles whose areas
// are proportional to their values, each row of rectangles chosen so its
// worst aspect ratio is as near square as the next item allows. Items are
// laid in the order given; the caller sorts them. Pure geometry, no DOM.

export interface Box {
  x: number
  y: number
  w: number
  h: number
}

export interface Rect<T> extends Box {
  item: T
}

export interface Weighted<T> {
  item: T
  value: number
}

/** The worst aspect ratio in a row of areas laid along a side of length `side`. */
function worst(areas: readonly number[], side: number): number {
  const s = areas.reduce((a, b) => a + b, 0)
  const max = Math.max(...areas)
  const min = Math.min(...areas)
  return Math.max((side * side * max) / (s * s), (s * s) / (side * side * min))
}

/**
 * Rectangles for the positive-valued items, in the input order, filling the
 * box exactly. Zero and negative values are dropped; an empty list or a box
 * with no area is empty.
 */
export function squarify<T>(items: readonly Weighted<T>[], box: Box): Rect<T>[] {
  const out: Rect<T>[] = []
  const kept = items.filter((i) => i.value > 0)
  const total = kept.reduce((a, i) => a + i.value, 0)
  if (!total || box.w <= 0 || box.h <= 0) return out
  const k = (box.w * box.h) / total
  let rest = kept.map((i) => ({ item: i.item, area: i.value * k }))
  let { x, y, w, h } = box
  while (rest.length) {
    const side = Math.min(w, h)
    let row = [rest[0]!]
    let i = 1
    while (i < rest.length) {
      const next = [...row, rest[i]!]
      if (worst(next.map((q) => q.area), side) <= worst(row.map((q) => q.area), side)) {
        row = next
        i++
      } else break
    }
    const s = row.reduce((a, q) => a + q.area, 0)
    if (w >= h) {
      const cw = s / h
      let cy = y
      for (const q of row) {
        const qh = q.area / cw
        out.push({ item: q.item, x, y: cy, w: cw, h: qh })
        cy += qh
      }
      x += cw
      w -= cw
    } else {
      const ch = s / w
      let cx = x
      for (const q of row) {
        const qw = q.area / ch
        out.push({ item: q.item, x: cx, y, w: qw, h: ch })
        cx += qw
      }
      y += ch
      h -= ch
    }
    rest = rest.slice(i)
  }
  return out
}

/** A rectangle snapped to whole pixels and shrunk by `inset` on every side; null when nothing is left. */
export function snap<T>(r: Rect<T>, inset: number): Rect<T> | null {
  const x = Math.round(r.x) + inset
  const y = Math.round(r.y) + inset
  const w = Math.round(r.x + r.w) - Math.round(r.x) - 2 * inset
  const h = Math.round(r.y + r.h) - Math.round(r.y) - 2 * inset
  return w < 1 || h < 1 ? null : { item: r.item, x, y, w, h }
}
