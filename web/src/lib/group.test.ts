import { describe, expect, it } from 'vitest'

import { groupByPlayer } from './group'

describe('groupByPlayer', () => {
  it('buckets rows by player, keeping order within a bucket', () => {
    const rows = [
      { attributed_player: 'a', n: 1 },
      { attributed_player: 'b', n: 2 },
      { attributed_player: 'a', n: 3 },
    ]
    const g = groupByPlayer(rows)
    expect([...g.keys()]).toEqual(['a', 'b'])
    expect(g.get('a')!.map((r) => r.n)).toEqual([1, 3])
    expect(g.get('zz')).toBeUndefined()
  })
})
