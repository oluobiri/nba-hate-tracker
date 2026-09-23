import { describe, expect, it } from 'vitest'

import { type FanRow, fanLists, fanSplit, fansSummary } from './fans'
import type { Counts } from './types'

const c = (neg: number, neu: number, pos: number): Counts => ({ neg, neu, pos, total: neg + neu + pos })
const row = (team: string, neg: number, neu: number, pos: number): FanRow => ({ team, ...c(neg, neu, pos) })

const ROWS = [row('Los Angeles Lakers', 40, 40, 20), row('Boston Celtics', 70, 20, 10), row('Miami Heat', 20, 30, 50), row('Utah Jazz', 2, 1, 1)]
const OVERALL = c(200, 150, 150) // 500 overall; 304 flaired → 196 unflaired

describe('fanSplit', () => {
  it('splits own, rivals and the unflaired remainder from counts', () => {
    const s = fanSplit(OVERALL, ROWS, 'Los Angeles Lakers')
    expect(s.own).toEqual(c(40, 40, 20))
    expect(s.rivals).toEqual(c(92, 51, 61))
    expect(s.flaired).toEqual(c(132, 91, 81))
    expect(s.unflaired).toEqual(c(68, 59, 69))
  })

  it('has no own tile for a free agent, so every flaired fan is a rival', () => {
    const s = fanSplit(OVERALL, ROWS, null)
    expect(s.own).toBeNull()
    expect(s.rivals).toEqual(s.flaired)
  })

  it('gives an empty own tile when his own fans never commented', () => {
    expect(fanSplit(OVERALL, ROWS, 'Denver Nuggets').own).toEqual(c(0, 0, 0))
  })

  it('never reports a negative unflaired count', () => {
    expect(fanSplit(c(1, 1, 1), ROWS, null).unflaired).toEqual(c(0, 0, 0))
  })
})

describe('fanLists', () => {
  it('ranks fanbases at the floor by negative and by positive rate, tagging his own', () => {
    const l = fanLists(ROWS, 50, 'Los Angeles Lakers', 5)
    expect(l.eligible).toBe(3) // Utah is under the floor
    expect(l.haters.map((r) => r.team)).toEqual(['Boston Celtics', 'Los Angeles Lakers', 'Miami Heat'])
    expect(l.defenders.map((r) => r.team)).toEqual(['Miami Heat', 'Los Angeles Lakers', 'Boston Celtics'])
    expect(l.haters[1]!.own).toBe(true)
    expect(l.haters[0]!.own).toBe(false)
  })

  it('cuts each list to the limit and averages over every flaired row, floor or not', () => {
    const l = fanLists(ROWS, 50, null, 1)
    expect(l.haters).toHaveLength(1)
    expect(l.average).toEqual(c(132, 91, 81))
  })
})

describe('fansSummary', () => {
  it('states the split and names the extremes', () => {
    const s = fanSplit(OVERALL, ROWS, 'Los Angeles Lakers')
    expect(fansSummary('Leader', s, fanLists(ROWS, 50, 'Los Angeles Lakers', 5), 50, 'Los Angeles Lakers')).toBe(
      'Of what r/NBA says about Leader, his own Lakers fans are 40% negative, rival fans 45%, unflaired commenters 35%. Among the 3 fanbases with at least 50 comments, Celtics fans are hardest on him at 70% negative and Heat fans kindest at 50% positive.',
    )
  })

  it('drops the own clause for a free agent and says when nobody stands out', () => {
    const s = fanSplit(OVERALL, ROWS, null)
    expect(fansSummary('Nomad', s, fanLists(ROWS, 500, null, 5), 500, null)).toBe(
      'Of what r/NBA says about Nomad, flaired fans 43%, unflaired commenters 35%. Fewer than two fanbases have 500 comments about him, so no fanbase stands out.',
    )
  })
})
