import { describe, expect, it } from 'vitest'

import { sumCounts } from './metrics'
import { EXCEPTION_GAP, fmtShareOf, playerRooms, ROOM_LABELS, ROOM_ORDER, ROOM_WHERE, roomsMethod, roomsSentence } from './rooms'
import { playerRoom } from './season.fixture'
import type { Counts } from './types'

const FLOOR = 20
type Row = ReturnType<typeof playerRoom>
const seasonOf = (rows: readonly Row[]): Counts => sumCounts(rows.map((r) => ({ neg: r.neg_count, neu: r.neu_count, pos: r.pos_count, total: r.comment_count })))
const sentence = (rows: readonly Row[], name = 'Him') => {
  const season = seasonOf(rows)
  return roomsSentence(name, playerRooms(rows, season, FLOOR), season)
}

describe('the room vocabulary', () => {
  it('orders, labels and places every room', () => {
    expect(ROOM_ORDER).toHaveLength(9)
    for (const key of ROOM_ORDER) {
      expect(ROOM_LABELS[key]).toBeTruthy()
      expect(ROOM_WHERE[key]).toBeTruthy()
    }
  })
})

describe('playerRooms', () => {
  // The front page is the biggest room; the game threads the harshest by net; the post-game threads the warmest; news under the floor.
  const rows = [
    playerRoom('Live', 'news', 10, 5, 4),
    playerRoom('Live', 'general', 300, 400, 300),
    playerRoom('Live', 'post_game_thread', 10, 20, 70),
    playerRoom('Live', 'game_thread', 500, 300, 150),
    playerRoom('Live', 'highlight', 60, 80, 60),
  ]
  const season = seasonOf(rows)
  const pr = playerRooms(rows, season, FLOOR)

  it('draws the rooms at the floor in the fixed order and lists the rest by size', () => {
    expect(pr.drawn.map((c) => c.key)).toEqual(['game_thread', 'post_game_thread', 'general', 'highlight'])
    expect(pr.under).toEqual([{ key: 'news', label: 'News', n: 19 }])
  })

  it('takes shares against his season, the largest the full bar, and carries net', () => {
    const fp = pr.drawn.find((c) => c.key === 'general')!
    expect(fp.share).toBeCloseTo(1000 / season.total, 12)
    expect(pr.maxShare).toBe(fp.share)
    expect(pr.biggest?.key).toBe('general')
    expect(pr.drawn[0]!.net).toBeCloseTo((150 - 500) / 950, 12)
  })

  it('tags the lowest and the highest net', () => {
    expect(pr.harshest?.key).toBe('game_thread')
    expect(pr.warmest?.key).toBe('post_game_thread')
    expect(pr.drawn.filter((c) => c.harshest).map((c) => c.key)).toEqual(['game_thread'])
    expect(pr.drawn.filter((c) => c.warmest).map((c) => c.key)).toEqual(['post_game_thread'])
  })

  it('tags by net, not by the negative share', () => {
    // The front page has the lower negative share and the lower net: less praise.
    const flip = [playerRoom('Flip', 'game_thread', 50, 25, 25), playerRoom('Flip', 'general', 44, 39, 17)]
    const f = playerRooms(flip, seasonOf(flip), FLOOR)
    expect(f.drawn.find((c) => c.key === 'general')!.rate).toBeLessThan(f.drawn.find((c) => c.key === 'game_thread')!.rate)
    expect(f.harshest?.key).toBe('general')
  })

  it('breaks a tie on net toward the larger room, and on size toward the drawing order', () => {
    const tied = [playerRoom('Tie', 'general', 100, 50, 50), playerRoom('Tie', 'game_thread', 50, 25, 25)]
    const t = playerRooms(tied, seasonOf(tied), FLOOR)
    expect(t.harshest?.key).toBe('general')
    expect(t.warmest?.key).toBe('general')
    const even = [playerRoom('Even', 'general', 30, 30, 40), playerRoom('Even', 'game_thread', 40, 30, 30)]
    expect(playerRooms(even, seasonOf(even), FLOOR).biggest?.key).toBe('game_thread')
  })

  it('tags nothing under two drawn rooms, and has no biggest room with none', () => {
    const one = [playerRoom('One', 'general', 30, 30, 40), playerRoom('One', 'news', 5, 2, 1)]
    const o = playerRooms(one, seasonOf(one), FLOOR)
    expect(o.drawn).toHaveLength(1)
    expect(o.harshest).toBeNull()
    expect(o.warmest).toBeNull()
    expect(o.biggest?.key).toBe('general')
    expect(o.drawn[0]).toMatchObject({ harshest: false, warmest: false })
    const none = playerRooms([playerRoom('None', 'general', 5, 5, 5)], { neg: 5, neu: 5, pos: 5, total: 15 }, FLOOR)
    expect(none).toMatchObject({ drawn: [], biggest: null, harshest: null, warmest: null, maxShare: 0 })
    expect(none.under).toEqual([{ key: 'general', label: 'Front page', n: 15 }])
  })
})

describe('playerRooms on odd rows', () => {
  it('keeps a room it has no words for, labelled by its key and sorted last', () => {
    const rows = [playerRoom('Odd', 'zzz_new_room', 30, 30, 40), playerRoom('Odd', 'news', 20, 30, 50)]
    const pr = playerRooms(rows, seasonOf(rows), FLOOR)
    expect(pr.drawn.map((c) => c.key)).toEqual(['news', 'zzz_new_room'])
    expect(pr.drawn[1]!.label).toBe('zzz_new_room')
    const s = roomsSentence('Odd', pr, seasonOf(rows))
    expect(s).toContain('talked about most under news posts')
    expect(s).toContain('His harshest room was zzz_new_room, +10 on 50% of his comments; his warmest news posts.')
  })

  it('gives every share as zero against an empty season', () => {
    const rows = [playerRoom('Empty', 'general', 30, 30, 40), playerRoom('Empty', 'news', 20, 30, 50)]
    const pr = playerRooms(rows, { neg: 0, neu: 0, pos: 0, total: 0 }, FLOOR)
    expect(pr.drawn.map((c) => c.share)).toEqual([0, 0])
    expect(pr.maxShare).toBe(0)
  })

  it('marks the tags on the cells it built, never on the rows or a previous call', () => {
    const rows = [playerRoom('Twice', 'game_thread', 60, 20, 20), playerRoom('Twice', 'general', 40, 30, 30)]
    const first = playerRooms(rows, seasonOf(rows), FLOOR)
    expect(playerRooms(rows, seasonOf(rows), 1000).drawn).toHaveLength(0)
    expect(first.drawn.filter((c) => c.harshest)).toHaveLength(1)
    expect(playerRooms(rows, seasonOf(rows), FLOOR).drawn.filter((c) => c.warmest)).toHaveLength(1)
    expect('harshest' in rows[0]!).toBe(false)
  })
})

describe('roomsSentence', () => {
  it('opens on the biggest room with its net sentiment against his season, then the two tagged rooms with their size', () => {
    const s = sentence([playerRoom('Him', 'game_thread', 60, 20, 20), playerRoom('Him', 'general', 40, 30, 30), playerRoom('Him', 'post_game_thread', 10, 20, 70)])
    expect(s).toBe(
      'Him was talked about most in the game threads: 100 of his 300 comments, −40 net sentiment against +3 across his season. His harshest room was the game threads; his warmest the post-game threads, +60 on 33% of his comments. The game threads ran 30 points harsher than the front page: his play was graded live.',
    )
  })

  it('sizes both tagged rooms when neither is the biggest', () => {
    const s = sentence([playerRoom('Him', 'general', 300, 400, 300), playerRoom('Him', 'lowlight', 20, 3, 2), playerRoom('Him', 'post_game_thread', 10, 20, 70)])
    expect(s).toContain('His harshest room was lowlights, −72 on 2% of his comments; his warmest the post-game threads, +60 on 9% of his comments.')
  })

  it('calls the season a story off the court when the front page ran below zero and below the game threads', () => {
    const s = sentence([playerRoom('Him', 'game_thread', 30, 40, 30), playerRoom('Him', 'general', 42, 30, 28)])
    expect(s).toContain('The front page ran 14 points harsher than the game threads, the reverse of the usual order: his season was a story off the court.')
  })

  it('says only that the game threads ran warmer when the front page is still above zero', () => {
    // A loved player: the game threads warmer than the front page, the front page trailing his season but positive.
    const s = sentence([playerRoom('Him', 'game_thread', 17, 27, 56), playerRoom('Him', 'general', 20, 40, 40), playerRoom('Him', 'news', 16, 52, 32)])
    expect(s).toContain('The game threads ran 19 points warmer than the front page.')
    expect(s).not.toContain('off the court')
    expect(s).not.toContain('graded live')
  })

  it('says nothing of the pair inside the band, deciding on the rounded points the sentence would print', () => {
    const level = sentence([playerRoom('Him', 'game_thread', 40, 30, 30), playerRoom('Him', 'general', 42, 30, 28)])
    expect(level).not.toContain('than the front page')
    // 4.6 points rounds to 5 and reads as the gap, so it takes a side.
    const near = sentence([playerRoom('Him', 'game_thread', 400, 300, 300), playerRoom('Him', 'general', 423, 300, 277)])
    expect(Math.abs(0.046)).toBeLessThan(EXCEPTION_GAP)
    expect(near).toContain('The front page ran 5 points harsher')
  })

  it('skips the pair without both rooms, and the tags when the two agree', () => {
    const s = sentence([playerRoom('Him', 'news', 50, 30, 20), playerRoom('Him', 'highlight', 30, 40, 30)])
    // Equal rooms: the biggest is the first in drawing order, highlights before news.
    expect(s).toBe('Him was talked about most under highlights: 100 of his 200 comments, 0 net sentiment against −15 across his season. His harshest room was news posts, −30 on 50% of his comments; his warmest highlights.')
    const same = sentence([playerRoom('Him', 'news', 30, 40, 30), playerRoom('Him', 'highlight', 30, 40, 30)])
    expect(same).toBe('Him was talked about most under highlights: 100 of his 200 comments, 0 net sentiment against 0 across his season.')
  })

  it('has a one-room form and nothing to say with no room drawn', () => {
    expect(sentence([playerRoom('Him', 'general', 30, 30, 40), playerRoom('Him', 'news', 5, 2, 1)])).toBe('Only one room holds enough comments about Him to split. On the front page, 100 of his 108 comments, +10 net sentiment against +6 across his season.')
    expect(sentence([playerRoom('Him', 'general', 5, 5, 5)])).toBe('')
  })
})

describe('the method line and the share', () => {
  it('names the floor, the rooms left out with their counts, and the marks', () => {
    const m = roomsMethod('Him', 200, [
      { key: 'post_game_thread', label: 'Post-game threads', n: 199 },
      { key: 'daily', label: 'Daily chat thread', n: 34 },
    ])
    expect(m).toContain('at least 200 comments about Him; left out here: Post-game threads (199), Daily chat thread (34).')
    expect(m).toContain('Harshest and warmest are by net sentiment')
    expect(roomsMethod('Him', 200, [])).toContain('comments about Him. The bar')
  })

  it('rounds a share to whole points and names a sliver as under 1%', () => {
    expect(fmtShareOf(0.306)).toBe('31%')
    expect(fmtShareOf(0.012)).toBe('1%')
    expect(fmtShareOf(0.005)).toBe('under 1%')
  })
})
