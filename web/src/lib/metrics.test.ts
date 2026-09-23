import { describe, expect, it } from 'vitest'

import { countsOf, negRate, netSentiment, polarization, posRate, rankBy, rankDeltas, sumCounts } from './metrics'
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

describe('rankDeltas', () => {
  const rows = [
    { name: 'a', ...c(60, 20, 20) }, // n=100
    { name: 'b', ...c(700, 200, 100) }, // n=1000
    { name: 'c', ...c(9, 1, 0) }, // n=10, 90% neg
  ]
  const key = (r: { name: string }) => r.name

  it('reads 0 in the official view and null for unranked rows', () => {
    const official = rankBy(rows, 'neg', 100)
    const d = rankDeltas(official, official, key)
    expect(d.get('b')).toBe(0)
    expect(d.get('a')).toBe(0)
    expect(d.get('c')).toBeNull()
  })

  it('is positive for a row that moved up in the current view, null for a row the official view never ranked', () => {
    const official = rankBy(rows, 'neg', 100)
    const current = rankBy(rows, 'neg', 10)
    const d = rankDeltas(current, official, key)
    expect(d.get('c')).toBeNull() // newly ranked; nothing to compare against
    expect(d.get('b')).toBe(-1) // 1st officially, 2nd now
    expect(d.get('a')).toBe(-1)
  })
})
