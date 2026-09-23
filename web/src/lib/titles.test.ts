import { describe, expect, it } from 'vitest'

import { reignRate, reigns, tally, weeklyHolders, type WeekRow } from './titles'

interface Row extends WeekRow {
  name: string
}

const row = (week: string, name: string, neg: number, neu: number, pos: number): Row => ({
  week: `${week}T00:00:00`,
  name,
  neg,
  neu,
  pos,
  total: neg + neu + pos,
})

const W1 = '2025-10-06'
const W2 = '2025-10-13'
const W3 = '2025-10-20'
const W4 = '2025-10-27'

describe('weeklyHolders', () => {
  it('takes the highest rate at or above the floor, per week, ascending', () => {
    const rows = [
      row(W2, 'b', 60, 30, 10), // 60% neg, n=100
      row(W1, 'a', 50, 40, 10), // 50% neg, n=100
      row(W1, 'c', 9, 1, 0), // 90% neg but n=10, under the floor
    ]
    const holders = weeklyHolders(rows, 'neg', 100)
    expect(holders.map((h) => [h.week.slice(0, 10), h.row.name])).toEqual([
      [W1, 'a'],
      [W2, 'b'],
    ])
    expect(holders[0]!.rate).toBeCloseTo(0.5)
  })

  it('breaks a tie by the larger n and omits a week with no qualifier', () => {
    const rows = [row(W1, 'a', 50, 50, 0), row(W1, 'b', 100, 100, 0), row(W2, 'c', 1, 1, 0)]
    const holders = weeklyHolders(rows, 'neg', 100)
    expect(holders.map((h) => h.row.name)).toEqual(['b'])
  })

  it('scores the Flowers by positive rate', () => {
    const rows = [row(W1, 'a', 10, 40, 50), row(W1, 'b', 60, 30, 10)]
    expect(weeklyHolders(rows, 'pos', 100)[0]!.row.name).toBe('a')
  })
})

const key = (r: Row) => r.name

describe('reigns', () => {

  it('merges consecutive weeks by one holder', () => {
    const holders = weeklyHolders([row(W1, 'a', 60, 40, 0), row(W2, 'a', 70, 30, 0), row(W3, 'b', 80, 20, 0)], 'neg', 100)
    const r = reigns(holders, key)
    expect(r.map((x) => [x.holders[0]!.row.name, x.weeks, x.from.slice(0, 10), x.to.slice(0, 10)])).toEqual([
      ['a', 2, W1, W2],
      ['b', 1, W3, W3],
    ])
  })

  it('does not bridge a week with no holder', () => {
    const holders = weeklyHolders([row(W1, 'a', 60, 40, 0), row(W2, 'a', 1, 1, 0), row(W3, 'a', 70, 30, 0)], 'neg', 100)
    expect(holders).toHaveLength(2)
    expect(reigns(holders, key).map((x) => x.weeks)).toEqual([1, 1])
  })

  it('keeps a reign open across four weeks', () => {
    const holders = weeklyHolders([W1, W2, W3, W4].map((w) => row(w, 'a', 60, 40, 0)), 'neg', 100)
    expect(reigns(holders, key)).toHaveLength(1)
    expect(reigns(holders, key)[0]!.weeks).toBe(4)
  })
})

describe('reignRate', () => {
  it('is the rate of the summed counts, not the mean of the weekly rates', () => {
    const holders = weeklyHolders([row(W1, 'a', 90, 10, 0), row(W2, 'a', 10, 90, 0)], 'neg', 100)
    const [reign] = reigns(holders, (r) => r.name)
    expect(reign!.weeks).toBe(2)
    expect(reignRate(reign!, 'neg')).toBeCloseTo(0.5)
    const heavier = weeklyHolders([row(W1, 'a', 900, 100, 0), row(W2, 'a', 10, 90, 0)], 'neg', 100)
    expect(reignRate(reigns(heavier, (r) => r.name)[0]!, 'neg')).toBeCloseTo(910 / 1100)
  })
})

describe('tally', () => {
  it('counts weeks per holder, most first', () => {
    const holders = weeklyHolders(
      [row(W1, 'a', 60, 40, 0), row(W2, 'b', 60, 40, 0), row(W3, 'a', 60, 40, 0), row(W4, 'a', 60, 40, 0)],
      'neg',
      100,
    )
    expect(tally(holders, key).map((t) => [t.row.name, t.weeks])).toEqual([
      ['a', 3],
      ['b', 1],
    ])
  })
})
