import { describe, expect, it } from 'vitest'

import { groupBy, groupByPlayer } from './group'

describe('groupBy', () => {
  it('buckets rows by any key, keeping order within a bucket', () => {
    const rows = [
      { fan_team: 'a', n: 1 },
      { fan_team: 'b', n: 2 },
      { fan_team: 'a', n: 3 },
    ]
    const g = groupBy(rows, (r) => r.fan_team)
    expect([...g.keys()]).toEqual(['a', 'b'])
    expect(g.get('a')!.map((r) => r.n)).toEqual([1, 3])
    expect(g.get('zz')).toBeUndefined()
  })
})

describe('groupByPlayer', () => {
  it('buckets rows by player', () => {
    const rows = [
      { attributed_player: 'a', n: 1 },
      { attributed_player: 'b', n: 2 },
      { attributed_player: 'a', n: 3 },
    ]
    const g = groupByPlayer(rows)
    expect([...g.keys()]).toEqual(['a', 'b'])
    expect(g.get('a')!.map((r) => r.n)).toEqual([1, 3])
  })
})
