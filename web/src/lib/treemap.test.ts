import { describe, expect, it } from 'vitest'

import { type Rect, snap, squarify } from './treemap'

const box = { x: 10, y: 20, w: 600, h: 400 }
const area = (r: Rect<unknown>): number => r.w * r.h
const overlaps = (a: Rect<unknown>, b: Rect<unknown>): boolean => a.x < b.x + b.w - 1e-9 && b.x < a.x + a.w - 1e-9 && a.y < b.y + b.h - 1e-9 && b.y < a.y + a.h - 1e-9
const inside = (r: Rect<unknown>): boolean => r.x >= box.x - 1e-9 && r.y >= box.y - 1e-9 && r.x + r.w <= box.x + box.w + 1e-9 && r.y + r.h <= box.y + box.h + 1e-9

const items = [60, 30, 25, 20, 15, 10, 5, 3, 2].map((value, i) => ({ item: `p${i}`, value }))

describe('squarify', () => {
  const rects = squarify(items, box)

  it('lays one rectangle per item, areas in proportion, summing to the box', () => {
    expect(rects).toHaveLength(items.length)
    const total = items.reduce((a, i) => a + i.value, 0)
    for (const [i, r] of rects.entries()) expect(area(r)).toBeCloseTo((items[i]!.value / total) * box.w * box.h, 6)
    expect(rects.reduce((a, r) => a + area(r), 0)).toBeCloseTo(box.w * box.h, 6)
  })

  it('never overlaps and stays inside the box', () => {
    for (const r of rects) expect(inside(r), String(r.item)).toBe(true)
    for (let i = 0; i < rects.length; i++) for (let j = i + 1; j < rects.length; j++) expect(overlaps(rects[i]!, rects[j]!), `${rects[i]!.item} × ${rects[j]!.item}`).toBe(false)
  })

  it('keeps the input order', () => {
    expect(rects.map((r) => r.item)).toEqual(items.map((i) => i.item))
  })

  it('fills the box with a single item', () => {
    const [r, ...rest] = squarify([{ item: 'solo', value: 7 }], box)
    expect(rest).toEqual([])
    expect(r!.item).toBe('solo')
    for (const k of ['x', 'y', 'w', 'h'] as const) expect(r![k]).toBeCloseTo(box[k], 9)
  })

  it('is empty for no items, for no weight, and for a box with no area', () => {
    expect(squarify([], box)).toEqual([])
    expect(squarify([{ item: 'none', value: 0 }], box)).toEqual([])
    expect(squarify(items, { ...box, h: 0 })).toEqual([])
  })

  it('drops items without weight and lays the rest', () => {
    const rs = squarify([{ item: 'a', value: 1 }, { item: 'none', value: 0 }, { item: 'b', value: 1 }], box)
    expect(rs.map((r) => r.item)).toEqual(['a', 'b'])
    expect(rs.reduce((a, r) => a + area(r), 0)).toBeCloseTo(box.w * box.h, 6)
  })

  it('lays a tall box top to bottom', () => {
    const rs = squarify(items.slice(0, 2), { x: 0, y: 0, w: 100, h: 300 })
    expect(rs[0]).toMatchObject({ x: 0, y: 0, w: 100 })
    expect(rs[1]!.y).toBeCloseTo(rs[0]!.h, 9)
  })
})

describe('snap', () => {
  it('rounds to whole pixels and insets every side', () => {
    // Edges round first (10.4 → 10, 110.6 → 111; 20.6 → 21, 70.9 → 71), then the inset comes off both sides.
    expect(snap({ item: 'a', x: 10.4, y: 20.6, w: 100.2, h: 50.3 }, 1)).toEqual({ item: 'a', x: 11, y: 22, w: 99, h: 48 })
  })

  it('is null when the inset eats the rectangle', () => {
    expect(snap({ item: 'a', x: 0, y: 0, w: 2, h: 10 }, 1)).toBeNull()
  })

  it('keeps neighbours flush: the right edge of one is the left edge of the next', () => {
    const a = snap({ item: 'a', x: 0, y: 0, w: 33.3, h: 10 }, 0)!
    const b = snap({ item: 'b', x: 33.3, y: 0, w: 33.3, h: 10 }, 0)!
    expect(a.x + a.w).toBe(b.x)
  })
})
