import { describe, expect, it } from 'vitest'

import { sumCounts } from './metrics'
import { EXCEPTION_GAP, fmtShareOf, HEADLINE_SHARE, playerRooms, ROOM_LABELS, ROOM_ORDER, ROOM_WHERE, roomsRule, roomsSentence } from './rooms'
import { playerRoom } from './season.fixture'
import type { Counts } from './types'

const FLOOR = 20
const seasonOf = (rows: readonly ReturnType<typeof playerRoom>[]): Counts => sumCounts(rows.map((r) => ({ neg: r.neg_count, neu: r.neu_count, pos: r.pos_count, total: r.comment_count })))

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
  // Game threads graded live: the harshest big room. Lowlights harsher still on a sliver. News under the floor.
  const rows = [
    playerRoom('Live', 'news', 10, 5, 4),
    playerRoom('Live', 'general', 300, 400, 300),
    playerRoom('Live', 'lowlight', 20, 3, 2),
    playerRoom('Live', 'game_thread', 500, 300, 200),
    playerRoom('Live', 'highlight', 60, 80, 60),
  ]
  const season = seasonOf(rows)
  const pr = playerRooms(rows, season, FLOOR)

  it('draws the rooms at the floor in the fixed order and lists the rest by size', () => {
    expect(pr.drawn.map((c) => c.key)).toEqual(['game_thread', 'general', 'highlight', 'lowlight'])
    expect(pr.under).toEqual([{ key: 'news', label: 'News', n: 19 }])
  })

  it('takes shares against his season, the largest the full bar', () => {
    const gt = pr.drawn[0]!
    expect(gt.share).toBeCloseTo(1000 / season.total, 12)
    expect(pr.maxShare).toBe(gt.share)
  })

  it('tags the harshest drawn room and heads the lede with the harshest at the share', () => {
    expect(pr.harshest?.key).toBe('lowlight')
    expect(pr.drawn.filter((c) => c.harshest).map((c) => c.key)).toEqual(['lowlight'])
    expect(pr.drawn.find((c) => c.key === 'lowlight')!.share).toBeLessThan(HEADLINE_SHARE)
    expect(pr.headline?.key).toBe('game_thread')
  })

  it('breaks a tie on the rate toward the larger room', () => {
    const tied = [playerRoom('Tie', 'game_thread', 50, 25, 25), playerRoom('Tie', 'general', 100, 50, 50)]
    const t = playerRooms(tied, seasonOf(tied), FLOOR)
    expect(t.harshest?.key).toBe('general')
    expect(t.headline?.key).toBe('general')
  })

  it('falls back to the harshest when no drawn room reaches the share', () => {
    // Most of his comments sit in rooms under the floor; the two drawn rooms are slivers.
    const thin = [playerRoom('Thin', 'injury', 15, 3, 2), playerRoom('Thin', 'lowlight', 12, 5, 3)]
    const t = playerRooms(thin, { neg: 100, neu: 200, pos: 300, total: 600 }, 15)
    expect(t.drawn.every((c) => c.share < HEADLINE_SHARE)).toBe(true)
    expect(t.headline?.key).toBe('injury')
  })

  it('tags nothing under two drawn rooms, and heads nothing with none', () => {
    const one = [playerRoom('One', 'general', 30, 30, 40), playerRoom('One', 'news', 5, 2, 1)]
    const o = playerRooms(one, seasonOf(one), FLOOR)
    expect(o.drawn).toHaveLength(1)
    expect(o.harshest).toBeNull()
    expect(o.headline?.key).toBe('general')
    expect(o.drawn[0]!.harshest).toBe(false)
    const none = playerRooms([playerRoom('None', 'general', 5, 5, 5)], { neg: 5, neu: 5, pos: 5, total: 15 }, FLOOR)
    expect(none).toMatchObject({ drawn: [], harshest: null, headline: null, maxShare: 0 })
    expect(none.under).toEqual([{ key: 'general', label: 'Front page', n: 15 }])
  })
})

const sentence = (rows: readonly ReturnType<typeof playerRoom>[], name = 'Him') => {
  const season = seasonOf(rows)
  return roomsSentence(name, playerRooms(rows, season, FLOOR), season)
}

describe('roomsSentence', () => {
  it('grades his play live when the game threads ran harsher by the gap', () => {
    const s = sentence([playerRoom('Him', 'game_thread', 60, 20, 20), playerRoom('Him', 'general', 40, 30, 30)])
    expect(s).toBe('Him was talked about most harshly in the game threads: 60.0% negative, against 50.0% across his season. The game threads ran 20 points harsher than the front page: his play was graded live.')
  })

  it('calls the season a story off the court when the front page ran harsher by the gap', () => {
    const s = sentence([playerRoom('Him', 'game_thread', 30, 40, 30), playerRoom('Him', 'general', 42, 30, 28)])
    expect(s).toContain('on the front page: 42.0% negative')
    expect(s).toContain('The front page ran 12 points harsher than the game threads, where most players draw their harshest share: his season was a story off the court.')
  })

  it('says level inside the gap, singular at one point', () => {
    const level = sentence([playerRoom('Him', 'game_thread', 40, 30, 30), playerRoom('Him', 'general', 41, 30, 29)])
    expect(level).toContain('The game threads and the front page ran level, 1 point apart.')
    expect(level).not.toContain('harsher')
    const hair = sentence([playerRoom('Him', 'game_thread', 400, 300, 300), playerRoom('Him', 'general', 403, 300, 297)])
    expect(hair).toContain('ran level, less than a point apart.')
    const edge = sentence([playerRoom('Him', 'game_thread', 40, 30, 30), playerRoom('Him', 'general', 45, 30, 25)])
    // 0.45 − 0.40 lands a hair under the gap in floating point; it is the gap on paper.
    expect(Math.abs(0.45 - 0.4)).toBeLessThan(EXCEPTION_GAP)
    expect(edge).toContain('The front page ran 5 points harsher')
  })

  it('names the tagged room in a tail when the headline passed it over', () => {
    const s = sentence([playerRoom('Him', 'game_thread', 500, 300, 200), playerRoom('Him', 'general', 300, 400, 300), playerRoom('Him', 'lowlight', 20, 3, 2)])
    expect(s.startsWith('Him was talked about most harshly in the game threads: 50.0% negative')).toBe(true)
    expect(s.endsWith('Lowlights ran harsher still, 80.0% negative, on 1% of his comments.')).toBe(true)
  })

  it('skips the second sentence without both rooms, and the tail when the tag is the headline', () => {
    const s = sentence([playerRoom('Him', 'news', 50, 30, 20), playerRoom('Him', 'highlight', 30, 40, 30)])
    expect(s).toBe('Him was talked about most harshly under news posts: 50.0% negative, against 40.0% across his season.')
  })

  it('has a one-room form and nothing to say with no room drawn', () => {
    expect(sentence([playerRoom('Him', 'general', 30, 30, 40), playerRoom('Him', 'news', 5, 2, 1)])).toBe('Only one room holds enough comments about Him to split. On the front page, 30.0% negative, against 32.4% across his season.')
    expect(sentence([playerRoom('Him', 'general', 5, 5, 5)])).toBe('')
  })
})

describe('the rule line and the share', () => {
  it('names the floor, the rooms left out with their counts, and the lede share', () => {
    const rule = roomsRule('Him', 200, [
      { key: 'post_game_thread', label: 'Post-game threads', n: 199 },
      { key: 'daily', label: 'Daily chat thread', n: 34 },
    ])
    expect(rule).toContain('at least 200 comments about Him; left out here: Post-game threads (199), Daily chat thread (34).')
    expect(rule).toContain(`rooms holding at least ${fmtShareOf(HEADLINE_SHARE)} of his comments`)
    expect(roomsRule('Him', 200, [])).toContain('comments about Him. The lede')
  })

  it('rounds a share to whole points and names a sliver as under 1%', () => {
    expect(fmtShareOf(0.306)).toBe('31%')
    expect(fmtShareOf(0.012)).toBe('1%')
    expect(fmtShareOf(0.005)).toBe('under 1%')
  })
})
