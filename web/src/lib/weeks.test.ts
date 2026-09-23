import { describe, expect, it } from 'vitest'

import { negRate, rollingRate } from './metrics'
import type { Counts } from './types'
import { extremeWeeks, phaseBands, phaseOf, spineRows, timelineSummary, weekLabel, weekOf, weekSpine } from './weeks'

const c = (neg: number, neu: number, pos: number): Counts => ({ neg, neu, pos, total: neg + neu + pos })
const W = ['2025-09-29T00:00:00', '2025-10-06T00:00:00', '2025-10-13T00:00:00', '2025-10-20T00:00:00', '2025-10-27T00:00:00']

// A season shaped like 2025-26, dates shifted onto the small spine above.
const CAL = {
  opening_night: '2025-10-08',
  play_in_start: '2025-10-21',
  play_in_end: '2025-10-23',
  playoffs_start: '2025-10-25',
  finals_start: '2025-10-30',
  finals_end: '2025-11-02',
}

describe('weekSpine', () => {
  it('sorts, de-duplicates and accepts consecutive Mondays', () => {
    expect(weekSpine([W[2]!, W[0]!, W[1]!, W[1]!])).toEqual(W.slice(0, 3))
  })

  it('throws on a gap, so a chart never quietly bridges one', () => {
    expect(() => weekSpine([W[0]!, W[2]!])).toThrow(/gap/)
  })
})

describe('spineRows', () => {
  it('lays rows on the spine with null for a missing week', () => {
    const rows = [
      { week: W[0]!, n: 1 },
      { week: W[2]!, n: 3 },
    ]
    expect(spineRows(W.slice(0, 3), rows)).toEqual([rows[0], null, rows[1]])
  })
})

describe('weekOf', () => {
  it('maps any day to its Monday key', () => {
    expect(weekOf('2025-10-06')).toBe('2025-10-06T00:00:00') // a Monday
    expect(weekOf('2025-10-09')).toBe('2025-10-06T00:00:00') // Thursday
    expect(weekOf('2025-10-12')).toBe('2025-10-06T00:00:00') // Sunday closes the week
    expect(weekOf('2025-10-13')).toBe('2025-10-13T00:00:00')
  })
})

describe('weekLabel', () => {
  it('prints the month and day', () => {
    expect(weekLabel('2026-02-09T00:00:00')).toBe('Feb 9')
    expect(weekLabel('2025-12-22')).toBe('Dec 22')
  })
})

describe('phaseOf', () => {
  it('cuts the season on the calendar', () => {
    expect(phaseOf('2025-10-01', CAL)).toBe('pre_season')
    expect(phaseOf('2025-10-08', CAL)).toBe('regular_season')
    expect(phaseOf('2025-10-21', CAL)).toBe('play_in')
    expect(phaseOf('2025-10-23', CAL)).toBe('play_in')
    expect(phaseOf('2025-10-24', CAL)).toBe('regular_season')
    expect(phaseOf('2025-10-25', CAL)).toBe('playoffs')
    expect(phaseOf('2025-11-02', CAL)).toBe('playoffs')
    expect(phaseOf('2025-11-03', CAL)).toBe('off_season')
  })

  it('is null without an opening night, and tolerates other missing dates', () => {
    expect(phaseOf('2025-10-08', { opening_night: null })).toBeNull()
    expect(phaseOf('2025-12-01', { opening_night: '2025-10-08' })).toBe('regular_season')
  })
})

describe('phaseBands', () => {
  it('groups the spine into contiguous runs with labels', () => {
    expect(phaseBands(W, CAL)).toEqual([
      { phase: 'pre_season', label: 'Preseason', start: 0, end: 2 },
      { phase: 'regular_season', label: 'Regular season', start: 2, end: 4 },
      { phase: 'playoffs', label: 'Playoffs', start: 4, end: 5 },
    ])
  })

  it('is empty when the calendar has no opening night', () => {
    expect(phaseBands(W, { opening_night: null })).toEqual([])
  })
})

describe('extremeWeeks', () => {
  it('finds the most negative and most positive weeks at or above the floor', () => {
    const rows = [c(9, 1, 0), c(30, 50, 20), null, c(10, 50, 40), c(40, 40, 20)]
    expect(extremeWeeks(rows, 10)).toEqual({ worst: 0, best: 3 })
    expect(extremeWeeks(rows, 50)).toEqual({ worst: 4, best: 3 }) // the 10-comment week drops out
  })

  it('is null on both sides when nothing reaches the floor', () => {
    expect(extremeWeeks([c(1, 0, 0), null], 5)).toEqual({ worst: null, best: null })
  })
})

describe('timelineSummary', () => {
  const rows = [c(30, 50, 20), c(60, 20, 20), null, c(10, 50, 40), c(40, 40, 20)]

  it('states the range, the extremes and the weeks left off', () => {
    const line = rollingRate(rows, 2, negRate, 30)
    expect(timelineSummary('Leader', W, rows, line, 30, 2)).toBe(
      'Over 2-week windows, the negative share of comments about Leader ran between 10% and 60%. His worst week was the week of Oct 6, 60% negative of 100 comments; his best the week of Oct 20, 40% positive. 1 of 5 weeks had fewer than 30 comments and are left off the line.',
    )
  })

  it('says so when there is nothing to draw', () => {
    const thin = [c(1, 0, 0), null, null, null, null]
    expect(timelineSummary('Quiet', W, thin, rollingRate(thin, 2, negRate, 30), 30, 2)).toBe(
      'Too few weeks with 30 comments about Quiet to draw a line. 5 of 5 weeks had fewer than 30 comments and are left off the line.',
    )
  })
})
