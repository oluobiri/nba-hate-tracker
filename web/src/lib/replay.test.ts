import { existsSync, readdirSync, readFileSync } from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import { assertRecapDocument } from '../data/recap'
import type { Manifest, RecapDocument } from '../data/types.gen'
import { CURRENT_SEASON } from '../site'
import { BREAK_CARD, buildTimeline, gameClock, playCursor, stoppageAt, stoppageLabel } from './clock'
import { attackingEnd, breakCard, buildRoom, clockAt, commentCursor, commentStamp, COURT, courtMarks, courtPoint, feed, lineAt, periodOf, prepareComments, quarterBox, recapRows, RECENT_SECONDS, rightNow, roomByPeriod, scoreAt, soFar, ticker, toRows } from './replay'
import { comment, play, REGULATION } from './replay.fixture'
import type { Counts } from './types'

const c = (neg: number, neu: number, pos: number): Counts => ({ neg, neu, pos, total: neg + neu + pos })
const tl = buildTimeline(REGULATION)

describe('toRows and recapRows', () => {
  it('turn column arrays into rows once', () => {
    expect(toRows({ a: [1, 2], b: ['x', 'y'] })).toEqual([
      { a: 1, b: 'x' },
      { a: 2, b: 'y' },
    ])
    expect(toRows({})).toEqual([])
    const doc = { header: {}, frames: { periods: { period: [1] }, threads: {}, stints: {}, plays: {}, comments: { comment_id: ['a'] } } } as unknown as RecapDocument
    expect(recapRows(doc).periods).toEqual([{ period: 1 }])
    expect(recapRows(doc).comments).toEqual([{ comment_id: 'a' }])
  })
})

describe('prepareComments', () => {
  it('places each comment on the wall clock, in its period, with its flair abbreviated', () => {
    const rows = [
      comment({ comment_id: 'pre', created_utc: 900, phase: 'pre', fan_team: 'San Antonio Spurs' }),
      comment({ comment_id: 'q1', created_utc: 1500, fan_team: 'Nowhere FC' }),
      comment({ comment_id: 'brk', created_utc: 2100, phase: 'break' }),
      comment({ comment_id: 'q3', created_utc: 4200 }),
    ]
    const out = prepareComments(rows, tl, { 'San Antonio Spurs': 'SAS' })
    expect(out.map((x) => x.t)).toEqual([-100, 500, 1100, 3200])
    expect(out.map((x) => x.period)).toEqual([null, 1, 1, 3])
    expect(out.map((x) => x.flair)).toEqual(['SAS', 'Nowhere FC', null, null])
    expect(periodOf(tl, 6500)).toBe(4)
  })

  it('refuses a sentiment or phase outside the vocabulary', () => {
    expect(() => prepareComments([comment({ sentiment: 'meh' })], tl, {})).toThrow('comments[0]: sentiment "meh"')
    expect(() => prepareComments([comment({ phase: 'later' })], tl, {})).toThrow('comments[0]: phase "later"')
  })
})

describe('commentCursor', () => {
  it('counts the comments at or before t', () => {
    const cs = prepareComments([comment({ created_utc: 1000 }), comment({ created_utc: 1010 }), comment({ created_utc: 1010 }), comment({ created_utc: 1500 })], tl, {})
    expect(commentCursor(cs, -1)).toBe(0)
    expect(commentCursor(cs, 0)).toBe(1)
    expect(commentCursor(cs, 10)).toBe(3)
    expect(commentCursor(cs, 9999)).toBe(4)
  })
})

// A room: his comments through the game with a known pattern, the crowd
// between them, a pregame and a post-game row, and one row of his in each
// break, so every reading has a brute-force twin.
function room() {
  const rows = [comment({ comment_id: 'pre', created_utc: 950, phase: 'pre', sentiment: 'pos' })]
  const pattern = ['neg', 'neg', 'neu', 'pos'] as const
  let n = 0
  for (const p of REGULATION) {
    for (let k = 0; k < 8; k++) {
      const at = p.start_wall + 100 + k * 100
      rows.push(comment({ comment_id: `f${n}`, created_utc: at, sentiment: pattern[n % 4]!, score: n }))
      rows.push(comment({ comment_id: `r${n}`, created_utc: at + 1, is_focus: false, body: n % 3 === 0 ? 'room' : null, score: 100 - n, sentiment: 'neu' }))
      n++
    }
    if (p.period < 4) rows.push(comment({ comment_id: `b${p.period}`, created_utc: p.end_wall + 50, phase: 'break', sentiment: 'neg' }))
  }
  rows.push(comment({ comment_id: 'post', created_utc: 6500, phase: 'post', sentiment: 'neg' }))
  const comments = prepareComments(rows, tl, {})
  return { comments, room: buildRoom(comments, tl) }
}

const brute = (cs: ReturnType<typeof prepareComments>, pick: (x: (typeof cs)[number]) => boolean): Counts => {
  const out = c(0, 0, 0)
  for (const x of cs) if (pick(x)) out[x.sentiment]++
  out.total = out.neg + out.neu + out.pos
  return out
}

describe('the room on him', () => {
  const { comments, room: r } = room()
  const inPlay = (x: (typeof comments)[number]) => x.isFocus && (x.phase === 'live' || x.phase === 'break')

  it('counts every in-play comment of his so far, never the pregame or post-game rows', () => {
    const end = comments.length
    expect(soFar(r, end)).toEqual(brute(comments, inPlay))
    expect(soFar(r, end).total).toBe(32 + 3)
    const mid = commentCursor(comments, 3300)
    expect(soFar(r, mid)).toEqual(brute(comments, (x) => inPlay(x) && x.t <= 3300))
    expect(soFar(r, 0)).toEqual(c(0, 0, 0))
  })

  it('reads the right-now window as his last n in-play comments', () => {
    const at = commentCursor(comments, 1450)
    const last5 = comments.filter((x, i) => i < at && inPlay(x)).slice(-5)
    expect(rightNow(r, at, 5)).toEqual(brute(last5, () => true))
    expect(rightNow(r, at, 5).total).toBe(5)
    expect(rightNow(r, 3, 5).total).toBe(1)
  })

  it('fills the quarter box row period by period, break comments with the period they follow', () => {
    const end = roomByPeriod(r, comments.length)
    expect(end.map((cell) => cell.label)).toEqual(['Q1', 'Q2', 'Q3', 'Q4'])
    expect(end.map((cell) => cell.counts.total)).toEqual([9, 9, 9, 8])
    expect(end[0]!.counts).toEqual(brute(comments, (x) => inPlay(x) && x.period === 1))
    const mid = roomByPeriod(r, commentCursor(comments, 3300))
    expect(mid.map((cell) => cell.counts.total)).toEqual([9, 9, 1, 0])
    expect(roomByPeriod(r, 0).map((cell) => cell.counts.total)).toEqual([0, 0, 0, 0])
  })

  it('counts his comments inside a break for the card', () => {
    const halftime = tl.segments.find((s) => s.label === 'Halftime')!
    expect(breakCard(r, halftime)).toEqual({ label: 'Halftime', n: 1 })
  })
})

describe('the game at the cursor', () => {
  const plays = [
    play({ kind: 'period_start', period: 1, wall_clock: 1000, game_seconds: 0, clock: 'PT12M00.00S' }),
    play({ kind: 'shot', period: 1, wall_clock: 1100, game_seconds: 60, clock: 'PT11M00.00S', is_focus: true, pts: 2, reb: 1, ast: null, score_home: 2, score_away: 0, description: 'V. W dunk' }),
    play({ kind: 'timeout', period: 1, wall_clock: 1200, game_seconds: 120, clock: 'PT10M00.00S', team_tricode: 'SAS', score_home: 2, score_away: 3, description: 'SAS Timeout' }),
    play({ kind: 'sub_out', period: 1, wall_clock: 1400, game_seconds: 120, clock: 'PT10M00.00S', is_focus: true, pts: 2, reb: 1, ast: 1, score_home: 2, score_away: 3 }),
    play({ kind: 'period_end', period: 1, wall_clock: 2000, game_seconds: 720, clock: 'PT00M00.00S', score_home: 25, score_away: 20 }),
    play({ kind: 'period_start', period: 2, wall_clock: 2200, game_seconds: 720 }),
    play({ kind: 'period_end', period: 2, wall_clock: 3200, game_seconds: 1440, clock: 'PT00M00.00S', score_home: 50, score_away: 45 }),
    play({ kind: 'period_start', period: 3, wall_clock: 4200, game_seconds: 1440 }),
    play({ kind: 'shot', period: 3, wall_clock: 4700, game_seconds: 1700, clock: 'PT07M40.00S', score_home: 60, score_away: 50, description: 'Somebody 3PT' }),
  ]

  it('reads the score and his running line, carried from his last row with one', () => {
    expect(scoreAt(plays, -1)).toEqual({ home: 0, away: 0 })
    expect(scoreAt(plays, 8)).toEqual({ home: 60, away: 50 })
    expect(lineAt(plays, 0)).toBeNull()
    expect(lineAt(plays, 1)).toEqual({ pts: 2, reb: 1, ast: 0 })
    expect(lineAt(plays, 8)).toEqual({ pts: 2, reb: 1, ast: 1 })
  })

  it('freezes the game clock through a timeout while the wall clock runs', () => {
    expect(clockAt(plays, tl, 200)).toBe('10:00')
    expect(clockAt(plays, tl, 300)).toBe('10:00')
    expect(clockAt(plays, tl, 450)).toBe('10:00')
    expect(stoppageLabel(stoppageAt(plays, playCursor(plays, tl, 450), tl))).toBe('TIMEOUT · SAS')
    expect(clockAt(plays, tl, 99)).toBe('12:00')
    expect(clockAt(plays, tl, -1)).toBeNull()
  })

  it('fills the quarter box from the running score, the period in play flagged', () => {
    expect(quarterBox(plays, tl, 8)).toEqual([
      { period: 1, label: 'Q1', away: 20, home: 25, running: false },
      { period: 2, label: 'Q2', away: 25, home: 25, running: false },
      { period: 3, label: 'Q3', away: 5, home: 10, running: true },
      { period: 4, label: 'Q4', away: null, home: null, running: false },
    ])
    expect(quarterBox(plays, tl, 2)[0]).toEqual({ period: 1, label: 'Q1', away: 3, home: 2, running: true })
    expect(quarterBox(plays, tl, -1).every((row) => row.away === null && !row.running)).toBe(true)
    // A period whose end marker never came still closes when the next one starts.
    const noEnd = plays.filter((p) => !(p.kind === 'period_end' && p.period === 1))
    expect(quarterBox(noEnd, tl, noEnd.length - 1).slice(0, 3)).toEqual([
      { period: 1, label: 'Q1', away: 3, home: 2, running: false },
      { period: 2, label: 'Q2', away: 42, home: 48, running: false },
      { period: 3, label: 'Q3', away: 5, home: 10, running: true },
    ])
  })

  it('stamps a comment on the game clock while the game runs, on the phase otherwise', () => {
    expect(commentStamp(plays, tl, -30)).toBe('Pregame')
    expect(commentStamp(plays, tl, 300)).toBe('Q1 10:00')
    expect(commentStamp(plays, tl, 2700)).toBe('Halftime')
    expect(commentStamp(plays, tl, 3300)).toBe('Q3 12:00')
    expect(commentStamp(plays, tl, 9000)).toBe('Final')
  })

  it('narrates the last few plays, oldest first, stamped on the game clock', () => {
    expect(ticker(plays, 8).map((l) => `${l.stamp} ${l.text}`)).toEqual(['Q2 00:00 ', 'Q3 12:00 ', 'Q3 07:40 Somebody 3PT'])
    expect(ticker(plays, 1)).toHaveLength(2)
    expect(ticker(plays, -1)).toEqual([])
  })
})

describe('feed', () => {
  const { comments, room: r } = room()
  const end = comments.length

  it('shows his comments newest first, every one with a body', () => {
    const his = feed(r, end, 'his', 'all', 1000)
    expect(his.every((x) => x.isFocus && x.body !== null)).toBe(true)
    expect(his.length).toBe(1 + 32 + 3 + 1)
    expect(his[0]!.id).toBe('post')
    expect(his[1]!.id).toBe('f31')
    expect(feed(r, end, 'his', 'all', 3).map((x) => x.id)).toEqual(['post', 'f31', 'f30'])
  })

  it("shows the room's comments that kept a body, none of his", () => {
    const theirs = feed(r, end, 'room', 'all', 1000)
    expect(theirs.every((x) => !x.isFocus && x.body !== null)).toBe(true)
    expect(theirs.map((x) => x.id).slice(0, 2)).toEqual(['r30', 'r27'])
  })

  it('keeps the top-scored comment per wall minute at minute density', () => {
    // Every focus row sits 100 s apart, so each is its own minute; the room's are one second behind them.
    const at = commentCursor(comments, 1800)
    expect(feed(r, at, 'his', 'minute', 10).map((x) => x.id)).toEqual(['f13', 'f12', 'f11', 'f10', 'f9', 'f8', 'b1', 'f7', 'f6', 'f5'])
    expect(feed(r, at, 'his', 'minute', 100)).toHaveLength(16)
    const dense = buildRoom(
      prepareComments(
        [comment({ comment_id: 'a', created_utc: 1010, score: 1 }), comment({ comment_id: 'b', created_utc: 1020, score: 9 }), comment({ comment_id: 'c', created_utc: 1070, score: 3 })],
        tl,
        {},
      ),
      tl,
    )
    expect(feed(dense, 3, 'his', 'minute', 10).map((x) => x.id)).toEqual(['c', 'b'])
  })
})

describe('the court', () => {
  it('sends the home team right in the first half and left after, overtime included; the away team the other way', () => {
    expect([1, 2, 3, 4, 5, 6].map((p) => attackingEnd(p, true))).toEqual(['right', 'right', 'left', 'left', 'left', 'left'])
    expect([1, 2, 3, 4, 5, 6].map((p) => attackingEnd(p, false))).toEqual(['left', 'left', 'right', 'right', 'right', 'right'])
  })

  it('places a shot by its distance up the floor from the basket, mirrored between the ends', () => {
    expect(courtPoint(0, 0, 'left')).toEqual({ x: COURT.basket, y: COURT.h / 2 })
    expect(courtPoint(0, 0, 'right')).toEqual({ x: COURT.w - COURT.basket, y: COURT.h / 2 })
    const left = courtPoint(-100, 200, 'left')
    const right = courtPoint(-100, 200, 'right')
    expect(left).toEqual({ x: COURT.basket + 200, y: COURT.h / 2 - 100 })
    expect(right).toEqual({ x: COURT.w - left.x, y: COURT.h - left.y })
  })

  it('draws his shots at his end, his blocks at the other, the last seconds bright', () => {
    const plays = [
      play({ kind: 'shot', period: 1, game_seconds: 60, is_focus: true, made: true, x_legacy: 0, y_legacy: 10, description: 'V dunk', clock: 'PT11M00.00S' }),
      play({ kind: 'shot', period: 1, game_seconds: 120, is_focus: true, made: false, x_legacy: 100, y_legacy: 200 }),
      play({ kind: 'block', period: 1, game_seconds: 130, is_focus: true, x_legacy: 50, y_legacy: 50 }),
      play({ kind: 'shot', period: 1, game_seconds: 140, is_focus: false, made: true, x_legacy: 0, y_legacy: 0 }),
      play({ kind: 'heave', period: 1, game_seconds: 150, is_focus: true, x_legacy: null, y_legacy: null }),
      play({ kind: 'shot', period: 3, game_seconds: 1500, is_focus: true, made: true, x_legacy: 0, y_legacy: 10 }),
      play({ kind: 'rebound', period: 3, game_seconds: 1500 + RECENT_SECONDS + 1, is_focus: true }),
    ]
    const marks = courtMarks(plays, 2, 'home')
    expect(marks.map((m) => m.kind)).toEqual(['make', 'miss', 'block'])
    expect(marks[0]).toMatchObject({ ...courtPoint(0, 10, 'right'), recent: false, label: 'Q1 11:00 · V dunk' })
    expect(marks[1]).toMatchObject({ ...courtPoint(100, 200, 'right'), recent: true })
    expect(marks[2]).toMatchObject({ ...courtPoint(50, 50, 'left'), recent: true })
    expect(courtMarks(plays, 2, 'away')[0]).toMatchObject(courtPoint(0, 10, 'left'))
    const late = courtMarks(plays, 5, 'home')
    expect(late).toHaveLength(4)
    expect(late[3]).toMatchObject({ ...courtPoint(0, 10, 'left'), recent: true })
    expect(late.slice(0, 3).every((m) => !m.recent)).toBe(true)
    expect(courtMarks(plays, 6, 'home')[3]!.recent).toBe(false)
    expect(courtMarks(plays, -1, 'home')).toEqual([])
  })
})

// The published files, when the repo's data directory is beside the site
// (never in CI): the clock and the room read them as the extractor wrote them.
const DASHBOARD = path.resolve(__dirname, '../../../data', CURRENT_SEASON, 'dashboard')
const RECAPS = path.join(DASHBOARD, 'recaps')
const files = existsSync(RECAPS) ? readdirSync(RECAPS).filter((f) => f.endsWith('.json')) : []

describe.skipIf(files.length === 0)('the live recap files', () => {
  const manifest = files.length ? (JSON.parse(readFileSync(path.join(DASHBOARD, 'manifest.json'), 'utf8')) as Manifest) : null
  const load = (file: string) => {
    const doc = assertRecapDocument(JSON.parse(readFileSync(path.join(RECAPS, file), 'utf8')), file)
    const rows = recapRows(doc)
    const timeline = buildTimeline(rows.periods)
    const comments = prepareComments(rows.comments, timeline, {})
    return { rows, timeline, comments, room: buildRoom(comments, timeline), entry: manifest!.recaps[file.replace(/\.json$/, '')]! }
  }

  it.each(files)("%s: the room's row at the final equals the registry's per-period counts", (file) => {
    const { room: r, comments, entry } = load(file)
    const cells = roomByPeriod(r, comments.length)
    expect(Object.fromEntries(cells.map((cell) => [String(cell.key), { neg: cell.counts.neg, pos: cell.counts.pos, neu: cell.counts.neu }]))).toEqual(entry.by_period)
    expect(soFar(r, comments.length).total).toBe(cells.reduce((n, cell) => n + cell.counts.total, 0))
  })

  it.each(files)('%s: a comment inside the first timeout reads the frozen second, and halftime compresses to one card', (file) => {
    const { rows, timeline } = load(file)
    const i = rows.plays.findIndex((p) => p.kind === 'timeout')
    const timeout = rows.plays[i]!
    const next = rows.plays.slice(i + 1).find((p) => p.game_seconds !== timeout.game_seconds)!
    const mid = Math.floor((timeout.wall_clock + next.wall_clock) / 2) - timeline.tip
    expect(clockAt(rows.plays, timeline, mid)).toBe(gameClock(timeout.clock))
    expect(stoppageLabel(stoppageAt(rows.plays, playCursor(rows.plays, timeline, mid), timeline))).toBe(`TIMEOUT · ${timeout.team_tricode}`)
    const halftime = timeline.segments.find((s) => s.label === 'Halftime')!
    expect(halftime.p1 - halftime.p0).toBe(BREAK_CARD)
    expect(halftime.t1 - halftime.t0).toBeGreaterThan(BREAK_CARD)
  })

  it.each(files)('%s: overtime reads as OT, the quarter box sums to the final, and every one of his feed items has a body', (file) => {
    const { rows, timeline, room: r, comments } = load(file)
    const labels = timeline.periods.map((p) => p.label)
    expect(labels.slice(0, 4)).toEqual(['Q1', 'Q2', 'Q3', 'Q4'])
    expect(labels.slice(4)).toEqual(['OT1', 'OT2'].slice(0, labels.length - 4))
    const last = rows.plays[rows.plays.length - 1]!
    const box = quarterBox(rows.plays, timeline, rows.plays.length - 1)
    expect(box.reduce((n, row) => n + (row.home ?? 0), 0)).toBe(last.score_home)
    expect(box.reduce((n, row) => n + (row.away ?? 0), 0)).toBe(last.score_away)
    expect(box.every((row) => !row.running)).toBe(true)
    expect(stoppageLabel(stoppageAt(rows.plays, rows.plays.length - 1, timeline))).toBe('FINAL')
    expect(feed(r, comments.length, 'his', 'all', Infinity).every((x) => x.body !== null)).toBe(true)
    const marks = courtMarks(rows.plays, rows.plays.length - 1, 'home')
    expect(marks.length).toBe(rows.plays.filter((p) => p.is_focus && p.x_legacy !== null && (p.kind === 'shot' || p.kind === 'block')).length)
    expect(marks.every((m) => m.x >= 0 && m.x <= COURT.w && m.y >= 0 && m.y <= COURT.h)).toBe(true)
  })
})
