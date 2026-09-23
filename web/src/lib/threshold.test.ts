import { describe, expect, it } from 'vitest'

import { snapThreshold, thresholdStops } from './threshold'

describe('thresholdStops', () => {
  const stops = thresholdStops(200, 165_616, 5_000)

  it('is ascending, bounded by the floor and the largest n, and round', () => {
    expect(stops[0]).toBe(200)
    expect(stops.at(-1)!).toBeLessThanOrEqual(165_616)
    expect([...stops].toSorted((a, b) => a - b)).toEqual(stops)
    expect(new Set(stops).size).toBe(stops.length)
    for (const s of stops) expect(s % 100).toBe(0)
  })

  it('always includes the official minimum and stays log-spaced', () => {
    expect(stops).toContain(5_000)
    expect(stops).toContain(1_000)
    expect(stops).toContain(100_000)
    expect(stops.length).toBeGreaterThan(12)
    expect(stops.length).toBeLessThan(25)
  })

  it('includes an off-series floor and official value', () => {
    const s = thresholdStops(250, 9_999, 4_321)
    expect(s[0]).toBe(250)
    expect(s).toContain(4_321)
    expect(s.at(-1)!).toBeLessThanOrEqual(9_999)
  })
})

describe('snapThreshold', () => {
  it('snaps to the nearest stop, lower on a tie', () => {
    const stops = [200, 500, 1_000]
    expect(snapThreshold(640, stops)).toBe(500)
    expect(snapThreshold(750, stops)).toBe(500)
    expect(snapThreshold(760, stops)).toBe(1_000)
    expect(snapThreshold(5, stops)).toBe(200)
  })
})
