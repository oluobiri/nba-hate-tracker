import { describe, expect, it } from 'vitest'

import {
  countsOf,
  gameScore,
  negRate,
  neighbours,
  netSentiment,
  pearson,
  polarization,
  posRate,
  rankBy,
  rankDeltas,
  rollingCounts,
  rollingRate,
  sumCounts,
} from './metrics'
import type { Counts } from './types'

const c = (neg: number, neu: number, pos: number): Counts => ({ neg, neu, pos, total: neg + neu + pos })

describe('rates', () => {
  it('derive from counts and read 0 on an empty row', () => {
    const row = c(30, 50, 20)
    expect(negRate(row)).toBeCloseTo(0.3)
    expect(posRate(row)).toBeCloseTo(0.2)
    expect(netSentiment(row)).toBeCloseTo(-0.1)
    expect(polarization(row)).toBeCloseTo(0.5)
    expect(negRate(c(0, 0, 0))).toBe(0)
  })
})

describe('sumCounts', () => {
  it('re-aggregates by summing counts, which is not the mean of the rates', () => {
    const rows = [c(90, 5, 5), c(1, 8, 1)]
    const summed = sumCounts(rows)
    expect(summed).toEqual({ neg: 91, neu: 13, pos: 6, total: 110 })
    const meanOfRates = (negRate(rows[0]!) + negRate(rows[1]!)) / 2
    expect(negRate(summed)).toBeCloseTo(91 / 110)
    expect(negRate(summed)).not.toBeCloseTo(meanOfRates, 2)
  })
})

describe('countsOf', () => {
  it('lifts a table row into Counts', () => {
    expect(countsOf({ neg_count: 1, neu_count: 2, pos_count: 3, comment_count: 6 })).toEqual(c(1, 2, 3))
  })
})

describe('rankBy', () => {
  const rows = [
    { name: 'a', ...c(60, 20, 20) }, // 60% neg, n=100
    { name: 'b', ...c(700, 200, 100) }, // 70% neg, n=1000
    { name: 'c', ...c(9, 1, 0) }, // 90% neg, n=10
  ]

  it('orders by the lens value and numbers only rows at the threshold', () => {
    const ranked = rankBy(rows, 'neg', 100)
    expect(ranked.map((r) => r.row.name)).toEqual(['c', 'b', 'a'])
    expect(ranked.map((r) => r.rank)).toEqual([null, 1, 2])
  })

  it('takes the threshold from the caller, so a lower one ranks more rows', () => {
    expect(rankBy(rows, 'neg', 10).map((r) => r.rank)).toEqual([1, 2, 3])
  })

  it('ranks volume by total', () => {
    expect(rankBy(rows, 'volume', 0).map((r) => r.row.name)).toEqual(['b', 'a', 'c'])
  })
})

const byName = (r: { name: string }) => r.name

describe('rankDeltas', () => {
  const rows = [
    { name: 'a', ...c(60, 20, 20) }, // n=100
    { name: 'b', ...c(700, 200, 100) }, // n=1000
    { name: 'c', ...c(9, 1, 0) }, // n=10, 90% neg
  ]
  it('reads 0 in the official view and null for unranked rows', () => {
    const official = rankBy(rows, 'neg', 100)
    const d = rankDeltas(official, official, byName)
    expect(d.get('b')).toBe(0)
    expect(d.get('a')).toBe(0)
    expect(d.get('c')).toBeNull()
  })

  it('is positive for a row that moved up in the current view, null for a row the official view never ranked', () => {
    const official = rankBy(rows, 'neg', 100)
    const current = rankBy(rows, 'neg', 10)
    const d = rankDeltas(current, official, byName)
    expect(d.get('c')).toBeNull() // newly ranked; nothing to compare against
    expect(d.get('b')).toBe(-1) // 1st officially, 2nd now
    expect(d.get('a')).toBe(-1)
  })
})

describe('neighbours', () => {
  const rows = [
    { name: 'a', ...c(60, 20, 20) },
    { name: 'b', ...c(700, 200, 100) },
    { name: 'c', ...c(9, 1, 0) }, // unranked at 100
    { name: 'd', ...c(30, 50, 20) },
  ]
  const ranked = rankBy(rows, 'neg', 100) // b (70%), a (60%), d (30%); c unranked

  it('walks ranked rows only, skipping the unranked', () => {
    expect(neighbours(ranked, byName, 'a')).toMatchObject({ prev: { row: { name: 'b' } }, next: { row: { name: 'd' } } })
  })

  it('has no prev at the top and no next at the bottom', () => {
    expect(neighbours(ranked, byName, 'b').prev).toBeNull()
    expect(neighbours(ranked, byName, 'd').next).toBeNull()
  })

  it('returns nothing for an unranked or unknown row', () => {
    expect(neighbours(ranked, byName, 'c')).toEqual({ prev: null, next: null })
    expect(neighbours(ranked, byName, 'zz')).toEqual({ prev: null, next: null })
  })
})

describe('rollingCounts', () => {
  // Six weeks, the third missing.
  const weeks = [c(10, 0, 0), c(0, 10, 0), null, c(0, 0, 10), c(5, 5, 0), c(0, 0, 0)]

  it('sums a trailing window of k, partial at the start, over the gap', () => {
    const out = rollingCounts(weeks, 4)
    expect(out[0]).toEqual(c(10, 0, 0))
    expect(out[1]).toEqual(c(10, 10, 0))
    expect(out[2]).toEqual(c(10, 10, 0)) // the gap adds nothing
    expect(out[3]).toEqual(c(10, 10, 10))
    expect(out[4]).toEqual(c(5, 15, 10)) // week 1 has dropped out
  })

  it('is null where the window has no comments', () => {
    expect(rollingCounts([null, null, c(0, 0, 0)], 2)).toEqual([null, null, null])
  })
})

describe('rollingRate', () => {
  it('takes the rate of the summed window, not a mean of weekly rates, and floors thin windows', () => {
    const weeks = [c(90, 5, 5), c(1, 8, 1)]
    const out = rollingRate(weeks, 2, negRate, 1)
    expect(out[1]).toBeCloseTo(91 / 110)
    expect(out[1]).not.toBeCloseTo((0.9 + 0.1) / 2, 2)
    expect(rollingRate(weeks, 2, negRate, 200)).toEqual([null, null])
    expect(rollingRate(weeks, 1, negRate, 11)).toEqual([0.9, null])
  })
})

describe('pearson', () => {
  it('reads ±1 on a line and near 0 on noise', () => {
    expect(pearson([1, 2, 3, 4], [2, 4, 6, 8])).toBeCloseTo(1)
    expect(pearson([1, 2, 3, 4], [8, 6, 4, 2])).toBeCloseTo(-1)
    expect(pearson([1, 2, 3, 4, 5], [1, 3, 2, 3, 1])).toBeCloseTo(0)
  })

  it('is null with fewer than three points or no variance', () => {
    expect(pearson([1, 2], [1, 2])).toBeNull()
    expect(pearson([1, 1, 1], [1, 2, 3])).toBeNull()
  })
})

describe('gameScore', () => {
  it('scores a box line by Hollinger', () => {
    // 30 pts on 11/20, 6/8 FT, 2 oreb, 8 dreb, 1 stl, 7 ast, 1 blk, 3 pf, 4 tov
    const line = { pts: 30, fgm: 11, fga: 20, ftm: 6, fta: 8, oreb: 2, dreb: 8, stl: 1, ast: 7, blk: 1, pf: 3, tov: 4 }
    // 30 + 4.4 − 14 − 0.8 + 1.4 + 2.4 + 1 + 4.9 + 0.7 − 1.2 − 4 = 24.8
    expect(gameScore(line)).toBeCloseTo(24.8)
  })

  it('reads 0 on an empty line', () => {
    expect(gameScore({ pts: 0, fgm: 0, fga: 0, ftm: 0, fta: 0, oreb: 0, dreb: 0, stl: 0, ast: 0, blk: 0, pf: 0, tov: 0 })).toBe(0)
  })
})
