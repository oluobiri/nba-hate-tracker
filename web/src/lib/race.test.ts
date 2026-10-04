import { describe, expect, it } from 'vitest'

import { rankBy } from './metrics'
import { cumulate, everTop, moveLabel, movement, packCounts, raceField, raceLead, rankFrame, type Triple, unpackCounts, weeklyCounts } from './race'

const W1 = '2025-10-06T00:00:00'
const W2 = '2025-10-13T00:00:00'
const W3 = '2025-10-20T00:00:00'
const SPINE = [W1, W2, W3]

const player = (name: string, neg: number, neu: number, pos: number) => ({ name, neg, neu, pos, total: neg + neu + pos })
const week = (name: string, w: string, neg: number, neu: number, pos: number) => ({ ...player(name, neg, neu, pos), week: w })

describe('raceField', () => {
  it('keeps the players at or above the official minimum, in name order', () => {
    const overall = [player('c', 60, 30, 10), player('a', 50, 49, 0), player('b', 100, 0, 0)]
    expect(raceField(overall, 100).map((p) => p.name)).toEqual(['b', 'c'])
  })
})

describe('weeklyCounts and cumulate', () => {
  const rows = [week('a', W1, 1, 2, 3), week('a', W3, 10, 20, 30), week('b', W2, 5, 5, 5), week('z', W1, 9, 9, 9)]
  const weekly = weeklyCounts(['a', 'b'], rows, SPINE)

  it('lays the field on the spine; an absent week adds nothing and an unfielded player is ignored', () => {
    expect(weekly).toEqual([
      [[1, 2, 3], [0, 0, 0], [10, 20, 30]],
      [[0, 0, 0], [5, 5, 5], [0, 0, 0]],
    ])
  })

  it('makes one frame per week, every comment through that week', () => {
    expect(cumulate(weekly)).toEqual([
      [[1, 2, 3], [0, 0, 0]],
      [[1, 2, 3], [5, 5, 5]],
      [[11, 22, 33], [5, 5, 5]],
    ])
  })

  it('round-trips through the packed string', () => {
    expect(unpackCounts(packCounts(weekly), 2, 3)).toEqual(weekly)
  })

  it('rejects a packed string of the wrong size or with a broken number', () => {
    expect(() => unpackCounts('1,2,3', 2, 3)).toThrow(/2 × 3 × 3/)
    expect(() => unpackCounts('1,2,x', 1, 1)).toThrow(/race counts/)
  })
})

describe('rankFrame', () => {
  // a: 60% neg of 100; b: 60% neg of 200; c: 90% neg of 10; d: no comments.
  const frame: Triple[] = [[60, 30, 10], [120, 60, 20], [9, 1, 0], [0, 0, 0]]

  it('ranks a rate race at or above the entry floor, ties to the larger n', () => {
    expect(rankFrame(frame, 'hated', 'rate', 100).map((r) => r.i)).toEqual([1, 0])
    expect(rankFrame(frame, 'hated', 'rate', 10).map((r) => r.i)).toEqual([2, 1, 0])
  })

  it('ranks the loved race by the positive share', () => {
    const ranked = rankFrame(frame, 'loved', 'rate', 100)
    expect(ranked.map((r) => r.i)).toEqual([1, 0])
    expect(ranked[0]).toMatchObject({ n: 200, value: 0.1 })
  })

  it('gives a count race no floor, and leaves out a player with nothing on that side', () => {
    expect(rankFrame(frame, 'hated', 'count', 100).map((r) => [r.i, r.value])).toEqual([[1, 120], [0, 60], [2, 9]])
    expect(rankFrame(frame, 'loved', 'count', 100).map((r) => r.i)).toEqual([1, 0])
  })

  it('never drops a bar once it is in: counts only grow', () => {
    const frames = cumulate([
      [[60, 40, 0], [0, 50, 0], [0, 900, 0]],
      [[10, 10, 0], [40, 40, 0], [0, 0, 0]],
    ])
    const entered = frames.map((f) => rankFrame(f, 'hated', 'rate', 100).map((r) => r.i).toSorted())
    expect(entered).toEqual([[0], [0, 1], [0, 1]])
  })

  it('orders the last frame exactly as the leaderboard orders the same totals', () => {
    const rows = [player('a', 60, 30, 10), player('b', 120, 60, 20), player('c', 500, 400, 100), player('d', 9, 1, 0)]
    const last: Triple[] = rows.map((r) => [r.neg, r.neu, r.pos])
    for (const [mode, lens] of [['hated', 'neg'], ['loved', 'pos']] as const) {
      const board = rankBy(rows, lens, 100).filter((r) => r.rank !== null).map((r) => r.row.name)
      expect(rankFrame(last, mode, 'rate', 100).map((r) => rows[r.i]!.name)).toEqual(board)
    }
  })
})

const rank = (...order: number[]) => order.map((i) => ({ i, n: 100, value: 0 }))

describe('movement', () => {
  it('marks a newcomer, the places gained and the places lost, and omits a held place', () => {
    const moves = movement(rank(3, 0, 2, 1), rank(0, 1, 2))
    expect([...moves]).toEqual([[3, 'new'], [0, -1], [1, -2]])
    expect(moves.has(2)).toBe(false)
  })

  it('has nothing to say on the first week', () => {
    expect(movement(rank(0, 1), null).size).toBe(0)
  })

  it('labels a move', () => {
    expect([moveLabel('new'), moveLabel(2), moveLabel(-1)]).toEqual(['NEW', '▲2', '▼1'])
  })
})

describe('raceLead', () => {
  it('names the leader so far, and says the leaderboard\'s sentence on the last week', () => {
    expect(raceLead('hated', 'rate', false)).toBe('The most hated player so far')
    expect(raceLead('hated', 'rate', true)).toBe("r/NBA's most hated player is")
    expect(raceLead('loved', 'rate', true)).toBe("r/NBA's most loved player is")
  })

  it('speaks of comments in a count race', () => {
    expect(raceLead('hated', 'count', false)).toBe('The most negative comments so far')
    expect(raceLead('loved', 'count', true)).toBe('The most positive comments went to')
  })
})

describe('everTop', () => {
  it('lists every player who reaches the top of any frame', () => {
    const frames: Triple[][] = [
      [[90, 10, 0], [50, 50, 0], [10, 90, 0]],
      [[90, 10, 0], [50, 50, 0], [990, 10, 0]],
    ]
    expect(everTop(frames, 'hated', 'rate', 100, 1)).toEqual([0, 2])
    expect(everTop(frames, 'hated', 'rate', 100, 2)).toEqual([0, 1, 2])
  })
})
