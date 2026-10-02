import { existsSync, readdirSync, readFileSync } from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import { assertRecapDocument } from '../data/recap'
import type { RecapDocument, RecapEntry } from '../data/types.gen'
import { CURRENT_SEASON } from '../site'
import { buildTimeline, PRE, uOfWall } from './clock'
import {
  blockedBy,
  boxLines,
  buildRoom,
  captionPlay,
  commentCursor,
  courtEnds,
  courtXY,
  feedSelection,
  flowSeries,
  lastName,
  lineScore,
  moments,
  onFloor,
  periodOf,
  playerNames,
  recapRows,
  rightNow,
  roomByPeriod,
  roomByPlayer,
  rosterOrder,
  scoreAt,
  soFar,
  sumLines,
  toRows,
} from './replay'
import { comment, play, smallGame, stint } from './replay.fixture'

describe('toRows', () => {
  it('turns column arrays into rows and an empty frame into none', () => {
    expect(toRows({ a: [1, 2], b: ['x', 'y'] })).toEqual([
      { a: 1, b: 'x' },
      { a: 2, b: 'y' },
    ])
    expect(toRows({ a: [], b: [] })).toEqual([])
  })
})

const { periods, plays } = smallGame()
const tl = buildTimeline(plays, periods)

describe('the room', () => {
  // his: three in play, one in the break, one post; the room's: one with a body, one without
  const comments = [
    comment({ comment_id: 'a', created_utc: 1005, sentiment: 'neg', player_id: 1 }),
    comment({ comment_id: 'b', created_utc: 1050, sentiment: 'pos', score: 9, player_id: 1 }),
    comment({ comment_id: 'c', created_utc: 1050, sentiment: 'neu', score: 3, player_id: 1 }),
    comment({ comment_id: 'd', created_utc: 1900, sentiment: 'neg', phase: 'break', game_seconds: 720, player_id: 1 }),
    comment({ comment_id: 'e', created_utc: 2900, sentiment: 'pos', phase: 'post', game_seconds: 1440, player_id: 1 }),
    comment({ comment_id: 'r', created_utc: 1030, sentiment: 'neg', is_focus: false, player_id: 7, body: 'room' }),
    comment({ comment_id: 's', created_utc: 1040, sentiment: 'pos', is_focus: false, player_id: 7, body: null }),
  ].map((c) => ({ ...c, game_seconds: c.phase === 'live' ? c.created_utc - 1000 : c.game_seconds }))
  const room = buildRoom(comments, tl)

  it('orders every comment by replay time and indexes his', () => {
    expect(room.comments.map((c) => c.id)).toEqual(['a', 'r', 's', 'b', 'c', 'd', 'e'])
    expect(room.focus.map((i) => room.comments[i]!.id)).toEqual(['a', 'b', 'c', 'd', 'e'])
    expect(room.comments[0]!.u).toBeCloseTo(uOfWall(tl, 1005), 6)
    expect(commentCursor(room, 0)).toBe(-1)
    expect(commentCursor(room, tl.totalU)).toBe(6)
  })

  it('counts his comments so far and the last n from the prefix', () => {
    const atHalf = tl.cards[1]!.u0 + 1
    expect(soFar(room, atHalf)).toEqual({ neg: 1, neu: 1, pos: 1, total: 3 })
    expect(rightNow(room, atHalf, 2)).toEqual({ neg: 0, neu: 1, pos: 1, total: 2 })
    expect(soFar(room, tl.totalU)).toEqual({ neg: 2, neu: 1, pos: 2, total: 5 })
    expect(rightNow(room, PRE - 1)).toEqual({ neg: 0, neu: 0, pos: 0, total: 0 })
  })

  it('assigns periods: a break comment to the period just played, nothing outside the game', () => {
    expect(periodOf({ phase: 'live', created_utc: 1005 }, periods)).toBe(1)
    expect(periodOf({ phase: 'live', created_utc: 1800 }, periods)).toBe(1)
    expect(periodOf({ phase: 'live', created_utc: 2000 }, periods)).toBe(2)
    expect(periodOf({ phase: 'break', created_utc: 1900 }, periods)).toBe(1)
    expect(periodOf({ phase: 'post', created_utc: 2900 }, periods)).toBeNull()
    expect(periodOf({ phase: 'pre', created_utc: 900 }, periods)).toBeNull()
    expect(roomByPeriod(room, periods).map((c) => [c.label, c.counts.total])).toEqual([
      ['Q1', 4],
      ['Q2', 0],
    ])
  })

  it('counts the room by player for the box score', () => {
    const by = roomByPlayer(room, 6)
    expect(by.get(1)).toEqual({ neg: 2, neu: 1, pos: 2, total: 5 })
    expect(by.get(7)).toEqual({ neg: 1, neu: 0, pos: 1, total: 2 })
    expect(roomByPlayer(room, -1).size).toBe(0)
  })

  it('draws the feed from bodied rows only, the top-voted one per bucket', () => {
    expect(feedSelection(room, 'him', 'all', 1).idx.map((i) => room.comments[i]!.id)).toEqual(['a', 'b', 'c', 'd', 'e'])
    expect(feedSelection(room, 'all', 'all', 1).idx.map((i) => room.comments[i]!.id)).toEqual(['a', 'r', 'b', 'c', 'd', 'e'])
    // b and c share a second; b has the votes
    const top = feedSelection(room, 'him', 'top', 1)
    expect(top.idx.map((i) => room.comments[i]!.id)).not.toContain('c')
    expect(top.idx.map((i) => room.comments[i]!.id)).toContain('b')
    expect(top.u).toEqual(top.idx.map((i) => room.comments[i]!.u))
  })

  it('leaves the strip empty until enough of his comments have landed', () => {
    const flow = flowSeries(room, tl, 10, 5)
    expect(flow.neg).toHaveLength(11)
    expect(flow.neg.every((v) => v === null)).toBe(true)
    expect(flow.bins.reduce((a, b) => a + b, 0)).toBe(7)
    expect(flow.max).toBeGreaterThanOrEqual(1)
  })
})

describe('the floor', () => {
  const stints = [
    stint({ person_id: 1, team_tricode: 'AAA', period: 1, start_seconds: 0, end_seconds: 300 }),
    stint({ person_id: 2, team_tricode: 'AAA', period: 1, start_seconds: 300, end_seconds: 720 }),
    stint({ person_id: 3, team_tricode: 'BBB', period: 1, start_seconds: 0, end_seconds: 720 }),
    stint({ person_id: 1, team_tricode: 'AAA', period: 2, start_seconds: 720, end_seconds: 1440 }),
    stint({ person_id: 4, team_tricode: 'BBB', period: 2, start_seconds: 900, end_seconds: 1440 }),
  ]

  it('reads who is on at a second, a stint ending there is off except at the buzzer', () => {
    expect([...onFloor(stints, 1, 0, 720)]).toEqual([1, 3])
    expect([...onFloor(stints, 1, 300, 720)]).toEqual([2, 3])
    expect([...onFloor(stints, 1, 720, 720)]).toEqual([2, 3])
    expect([...onFloor(stints, 2, 720, 1440)]).toEqual([1])
    expect([...onFloor(stints, 2, 1440, 1440)]).toEqual([1, 4])
  })

  it('orders each roster by first appearance, the opening five first', () => {
    expect([...rosterOrder(stints).entries()]).toEqual([
      ['AAA', [1, 2]],
      ['BBB', [3, 4]],
    ])
  })

  it('names players from the plays and shortens to the last name', () => {
    const names = playerNames([play({ person_id: 1, player_name_i: 'V. Wembanyama' }), play({ person_id: 1, player_name_i: 'other' }), play({ person_id: 0, player_name_i: 'x' })])
    expect([...names.entries()]).toEqual([[1, 'V. Wembanyama']])
    expect(lastName('V. Wembanyama')).toBe('Wembanyama')
    expect(lastName("D'A. Fox")).toBe("D'A. Fox")
  })
})

describe('the box', () => {
  it('counts every line from the plays by the box rules and sums them', () => {
    const rows = [
      play({ person_id: 1, kind: 'shot', action_type: '3pt', made: true, shot_value: 3, assist_person_id: 2 }),
      play({ person_id: 1, kind: 'shot', action_type: '2pt', made: false, shot_value: 2 }),
      play({ person_id: 1, kind: 'free_throw', action_type: 'freethrow', made: true, shot_value: 1 }),
      play({ person_id: 1, kind: 'free_throw', action_type: 'freethrow', made: false, shot_value: 1 }),
      play({ person_id: 2, kind: 'rebound', sub_type: 'offensive' }),
      play({ person_id: 2, kind: 'rebound', sub_type: 'defensive' }),
      play({ person_id: 2, kind: 'steal' }),
      play({ person_id: 1, kind: 'block' }),
      play({ person_id: 2, kind: 'turnover' }),
      play({ person_id: 2, kind: 'foul', sub_type: 'personal' }),
      play({ person_id: 2, kind: 'foul', sub_type: 'technical' }),
      play({ person_id: 0, kind: 'rebound', sub_type: 'defensive' }),
      play({ person_id: 0, kind: 'heave', made: false }),
    ]
    const lines = boxLines(rows, rows.length - 1)
    expect(lines.get(1)).toEqual({ pts: 4, reb: 0, oreb: 0, dreb: 0, ast: 0, stl: 0, blk: 1, tov: 0, pf: 0, fgm: 1, fga: 2, fg3m: 1, fg3a: 1, ftm: 1, fta: 2 })
    expect(lines.get(2)).toEqual({ pts: 0, reb: 2, oreb: 1, dreb: 1, ast: 1, stl: 1, blk: 0, tov: 1, pf: 1, fgm: 0, fga: 0, fg3m: 0, fg3a: 0, ftm: 0, fta: 0 })
    expect(lines.has(0)).toBe(false)
    expect(sumLines([...lines.values()]).pts).toBe(4)
    expect(boxLines(rows, -1).size).toBe(0)
  })

  it('reads the score and the points per period through the cursor', () => {
    expect(scoreAt(plays, -1)).toEqual({ away: 0, home: 0 })
    expect(scoreAt(plays, 3)).toEqual({ away: 1, home: 2 })
    expect(lineScore(plays, 1, periods)).toEqual([
      { period: 1, label: 'Q1', away: 0, home: 2 },
      { period: 2, label: 'Q2', away: null, home: null },
    ])
    expect(lineScore(plays, 7, periods).map((p) => [p.away, p.home])).toEqual([
      [1, 2],
      [0, 0],
    ])
  })
})

describe('his moments', () => {
  const me = 9
  const rows = [
    play({ action_number: 1, person_id: me, kind: 'shot', action_type: '2pt', made: true, description: 'V. Wembanyama running DUNK (2 PTS) (S. Castle 1 AST)' }),
    play({ action_number: 2, person_id: me, kind: 'shot', action_type: '3pt', made: false, description: "MISS V. Wembanyama 26' 3PT" }),
    play({ action_number: 3, person_id: 5, kind: 'shot', action_type: '2pt', made: false, description: "MISS J. Brunson 4' driving Layup - blocked", x: 10, y: 50 }),
    play({ action_number: 4, person_id: me, kind: 'block', paired_action_number: 3, description: 'V. Wembanyama BLOCK (1 BLK)' }),
    play({ action_number: 5, person_id: 5, kind: 'shot', action_type: '2pt', made: true, assist_person_id: me, description: 'S. Castle cutting Layup (4 PTS) (V. Wembanyama 2 AST)' }),
    play({ action_number: 6, person_id: me, kind: 'foul', description: 'V. Wembanyama P.FOUL (P1.T2)' }),
    play({ action_number: 7, person_id: me, kind: 'turnover', description: 'V. Wembanyama bad pass TURNOVER (P1.T3)' }),
    play({ action_number: 8, person_id: me, kind: 'steal', description: 'V. Wembanyama STEAL (1 STL)' }),
    play({ action_number: 9, person_id: me, kind: 'shot', action_type: '2pt', made: true, description: "V. Wembanyama 2' Layup (6 PTS)" }),
    play({ action_number: 10, person_id: me, kind: 'rebound', description: 'V. Wembanyama REBOUND' }),
    play({ action_number: 11, person_id: me, kind: 'sub_out', description: 'SUB out: V. Wembanyama' }),
  ]
  const m = moments(rows, me, 'V. Wembanyama')

  it('labels his plays, marks the court, and words the caption without his name', () => {
    expect([...m.keys()]).toEqual([0, 1, 3, 4, 5, 6, 7, 8])
    expect(m.get(0)).toEqual({ i: 0, label: 'DUNK', text: 'running DUNK (2 PTS) (S. Castle 1 AST)', mark: 0 })
    expect(m.get(1)).toEqual({ i: 1, label: 'MISS', text: "26' 3PT", mark: 1 })
    expect(m.get(3)).toEqual({ i: 3, label: 'BLOCK', text: "on J. Brunson 4' driving Layup", mark: 2 })
    expect(m.get(4)).toEqual({ i: 4, label: 'ASSIST', text: 'to S. Castle cutting Layup (4 PTS)', mark: 4 })
    expect(m.get(5)!.label).toBe('FOUL')
    expect(m.get(6)!.label).toBe('TURNOVER')
    expect(m.get(7)!.label).toBe('STEAL')
    expect(m.get(8)!.label).toBe('LAYUP')
    expect([...blockedBy(rows).entries()]).toEqual([[2, 3]])
  })

  it('captions the last play that is not a substitution', () => {
    expect(captionPlay(rows, 10)!.action_number).toBe(10)
    expect(captionPlay(rows, -1)).toBeNull()
  })
})

describe('the court', () => {
  it('reads each team’s end from its shots and switches at half', () => {
    const ends = courtEnds(plays, periods)
    expect(ends.get(1)).toEqual({ left: 'BBB', right: 'AAA' })
    expect(ends.get(2)).toEqual({ left: 'AAA', right: 'BBB' })
    expect(courtXY({ x: 50, y: 50 })).toEqual([470, 250])
    expect(courtXY({ x: null, y: 50 })).toBeNull()
  })
})

// The published files, when the repo's data directory is beside the site.
const RECAPS = path.resolve(__dirname, '../../../data', CURRENT_SEASON, 'dashboard/recaps')
const files = existsSync(RECAPS) ? readdirSync(RECAPS).filter((f) => f.endsWith('.json')) : []
const load = (file: string): RecapDocument => assertRecapDocument(JSON.parse(readFileSync(path.join(RECAPS, file), 'utf8')), file)
const manifest = files.length ? (JSON.parse(readFileSync(path.resolve(RECAPS, '../manifest.json'), 'utf8')) as { recaps: Record<string, RecapEntry> }) : null

describe.skipIf(files.length === 0)('the live files', () => {
  it.each(files)('%s: the room by period at the final is the registry’s by_period', (file) => {
    const doc = load(file)
    const rows = recapRows(doc)
    const room = buildRoom(rows.comments, buildTimeline(rows.plays, rows.periods))
    const want = manifest!.recaps[file.replace(/\.json$/, '')]!.by_period
    for (const cell of roomByPeriod(room, rows.periods)) {
      const w = want[String(cell.key)]!
      expect({ neg: cell.counts.neg, neu: cell.counts.neu, pos: cell.counts.pos }, `${file} ${cell.label}`).toEqual({ neg: w.neg, neu: w.neu, pos: w.pos })
    }
  })

  it.each(files)('%s: the box lines sum to the final score and five are on the floor at every play', (file) => {
    const doc = load(file)
    const { plays: rows, periods: ps, stints } = recapRows(doc)
    const lines = boxLines(rows, rows.length - 1)
    const order = rosterOrder(stints)
    const names = playerNames(rows)
    const final = scoreAt(rows, rows.length - 1)
    const points = (team: string) => sumLines((order.get(team) ?? []).map((id) => lines.get(id) ?? sumLines([]))).pts
    const teams = [...order.keys()]
    expect(teams).toHaveLength(2)
    expect(teams.map(points).toSorted((a, b) => a - b)).toEqual([final.away, final.home].toSorted((a, b) => a - b))
    for (const team of teams) for (const id of order.get(team)!) expect(names.has(id), `${file} ${id} unnamed`).toBe(true)
    const byPeriod = new Map(ps.map((p) => [p.period, p.end_seconds]))
    for (const r of rows) {
      if (r.kind === 'period_end') continue
      const on = onFloor(stints, r.period, r.game_seconds, byPeriod.get(r.period)!)
      for (const team of teams) expect([...on].filter((id) => order.get(team)!.includes(id)), `${file} ${r.action_number} ${team}`).toHaveLength(5)
    }
    const ls = lineScore(rows, rows.length - 1, ps)
    expect(ls.reduce((a, p) => a + (p.home ?? 0), 0)).toBe(final.home)
    expect(ls.reduce((a, p) => a + (p.away ?? 0), 0)).toBe(final.away)
  })

  it.each(files)('%s: every end is read and every one of his shots has a spot', (file) => {
    const doc = load(file)
    const { plays: rows, periods: ps } = recapRows(doc)
    const ends = courtEnds(rows, ps)
    for (const p of ps) expect(ends.get(p.period)!.left).not.toBe(ends.get(p.period)!.right)
    expect(ends.get(1)!.right).toBe(ends.get(3)!.left)
    const m = moments(rows, doc.header.player_id, rows.find((r) => r.person_id === doc.header.player_id)!.player_name_i!)
    for (const mo of m.values()) {
      if (mo.mark !== null) expect(courtXY(rows[mo.mark]!), `${file} ${mo.label} ${mo.i}`).not.toBeNull()
      expect(mo.text).not.toContain(doc.header.attributed_player)
    }
    if (file.includes('wembanyama')) expect(m.size).toBe(31)
  })
})
