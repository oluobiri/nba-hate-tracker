// The room at t. Column arrays become rows once; the comments become one
// sorted list with a focus index and prefix counts, so every reading the
// page makes as the clock runs (the two bars, the quarter box's room row,
// the feed) is a cursor and a subtraction, never a scan of 17,000 rows.
// Pure; the island owns the clock.
import type { Columnar, RecapCommentsRow, RecapDocument, RecapPlaysRow, RecapRows } from '../data/types.gen'
import { gameClock, type Phase, playCursor, playStamp, type Segment, type Timeline } from './clock'
import { type PeriodCell, periodLabel } from './recaps'
import { type Counts, SENTIMENTS, type Sentiment } from './types'

/** How many of his comments the "right now" bar reads: a count window, a page choice. */
export const RIGHT_NOW = 25
/** Lines the ticker shows: a page choice. */
export const TICKER_LINES = 3

// --- Rows -------------------------------------------------------------------

/** One frame's column arrays as rows. */
export function toRows<T extends object>(frame: Columnar<T>): T[] {
  const cols = Object.keys(frame) as (keyof T)[]
  const first = cols[0]
  const n = first === undefined ? 0 : (frame[first] as unknown[]).length
  return Array.from({ length: n }, (_, i) => {
    const row = {} as T
    for (const c of cols) row[c] = (frame[c] as T[keyof T][])[i]!
    return row
  })
}

export function recapRows(doc: RecapDocument): RecapRows {
  const f = doc.frames
  return { periods: toRows(f.periods), threads: toRows(f.threads), stints: toRows(f.stints), plays: toRows(f.plays), comments: toRows(f.comments) }
}

// --- Comments ---------------------------------------------------------------

export interface ReplayComment {
  id: string
  postId: string
  /** Wall seconds since tip; negative before it. */
  t: number
  phase: Phase
  sentiment: Sentiment
  score: number
  /** The fan's team as an abbreviation when known, the name otherwise, null unflaired. */
  flair: string | null
  isFocus: boolean
  /** Kept by the selection rule: every one of his, the room's top few per bucket. */
  body: string | null
  /** The period it landed in, by the period markers' wall clock; null before the tip. */
  period: number | null
}

/** The last period whose start marker is at or before the comment. */
export function periodOf(tl: Timeline, createdUtc: number): number | null {
  let found: number | null = null
  for (const p of tl.periods) {
    if (p.startWall <= createdUtc) found = p.period
    else break
  }
  return found
}

const PHASES: readonly Phase[] = ['pre', 'live', 'break', 'post']

export function prepareComments(rows: readonly RecapCommentsRow[], tl: Timeline, flairAbbr: Readonly<Record<string, string>>): ReplayComment[] {
  return rows.map((r, i) => {
    if (!SENTIMENTS.includes(r.sentiment as Sentiment)) throw new Error(`comments[${i}]: sentiment ${JSON.stringify(r.sentiment)}`)
    if (!PHASES.includes(r.phase as Phase)) throw new Error(`comments[${i}]: phase ${JSON.stringify(r.phase)}`)
    return {
      id: r.comment_id,
      postId: r.post_id,
      t: r.created_utc - tl.tip,
      phase: r.phase as Phase,
      sentiment: r.sentiment as Sentiment,
      score: r.score,
      flair: r.fan_team === null ? null : (flairAbbr[r.fan_team] ?? r.fan_team),
      isFocus: r.is_focus,
      body: r.body,
      period: periodOf(tl, r.created_utc),
    }
  })
}

/** How many comments landed at or before t. Comments are sorted by t. */
export function commentCursor(comments: readonly ReplayComment[], t: number): number {
  let lo = 0
  let hi = comments.length
  while (lo < hi) {
    const mid = (lo + hi) >> 1
    if (comments[mid]!.t <= t) lo = mid + 1
    else hi = mid
  }
  return lo
}

// --- The room on him ----------------------------------------------------------
// His in-play comments (live and break: the strip's population) indexed
// once, with prefix counts per sentiment.

export interface Room {
  comments: ReplayComment[]
  /** Indices into `comments` of his in-play comments, ascending. */
  focus: number[]
  /** Cumulative counts over `focus`: prefix[k] counts the first k. */
  prefix: Record<Sentiment, Int32Array>
  /** Per period, the range of positions in `focus` that landed in it. */
  spans: { period: number; lo: number; hi: number }[]
}

const inPlay = (c: ReplayComment): boolean => c.isFocus && (c.phase === 'live' || c.phase === 'break')

export function buildRoom(comments: ReplayComment[], tl: Timeline): Room {
  const focus: number[] = []
  comments.forEach((c, i) => {
    if (inPlay(c)) focus.push(i)
  })
  const prefix: Record<Sentiment, Int32Array> = { neg: new Int32Array(focus.length + 1), neu: new Int32Array(focus.length + 1), pos: new Int32Array(focus.length + 1) }
  focus.forEach((idx, k) => {
    const s = comments[idx]!.sentiment
    for (const key of SENTIMENTS) prefix[key][k + 1] = prefix[key][k]! + (key === s ? 1 : 0)
  })
  const spans = tl.periods.map((p) => {
    let lo = focus.length
    let hi = 0
    focus.forEach((idx, k) => {
      if (comments[idx]!.period === p.period) {
        lo = Math.min(lo, k)
        hi = Math.max(hi, k + 1)
      }
    })
    return { period: p.period, lo: Math.min(lo, hi), hi }
  })
  return { comments, focus, prefix, spans }
}

/** How many of his in-play comments sit before the cursor. */
function focusCount(room: Room, cursor: number): number {
  let lo = 0
  let hi = room.focus.length
  while (lo < hi) {
    const mid = (lo + hi) >> 1
    if (room.focus[mid]! < cursor) lo = mid + 1
    else hi = mid
  }
  return lo
}

function between(room: Room, from: number, to: number): Counts {
  const neg = room.prefix.neg[to]! - room.prefix.neg[from]!
  const neu = room.prefix.neu[to]! - room.prefix.neu[from]!
  const pos = room.prefix.pos[to]! - room.prefix.pos[from]!
  return { neg, neu, pos, total: neg + neu + pos }
}

/** His last `n` in-play comments at the cursor. */
export function rightNow(room: Room, cursor: number, n: number = RIGHT_NOW): Counts {
  const k = focusCount(room, cursor)
  return between(room, Math.max(0, k - n), k)
}

/** Every in-play comment of his at the cursor. */
export function soFar(room: Room, cursor: number): Counts {
  return between(room, 0, focusCount(room, cursor))
}

/** The room's row of the quarter box: his in-play comments per period, up to the cursor. */
export function roomByPeriod(room: Room, cursor: number): PeriodCell[] {
  const k = focusCount(room, cursor)
  return room.spans.map((s) => ({ key: s.period, label: periodLabel(s.period), counts: between(room, Math.min(s.lo, k), Math.min(s.hi, k)) }))
}

/** "Halftime · 125 comments about him": his comments that landed inside a break. */
export function breakCard(room: Room, segment: Segment): { label: string; n: number } {
  let n = 0
  for (const idx of room.focus) {
    const c = room.comments[idx]!
    if (c.phase === 'break' && c.period === segment.period) n++
  }
  return { label: segment.label, n }
}

// --- The game -----------------------------------------------------------------

export interface Score {
  home: number
  away: number
}

/** The score at the cursor; 0–0 before the first play. */
export function scoreAt(plays: readonly RecapPlaysRow[], cursor: number): Score {
  const p = plays[cursor]
  return p ? { home: p.score_home, away: p.score_away } : { home: 0, away: 0 }
}

export interface Line {
  pts: number
  reb: number
  ast: number
}

/** His running line at the cursor, from the last of his rows that carries one. */
export function lineAt(plays: readonly RecapPlaysRow[], cursor: number): Line | null {
  for (let i = cursor; i >= 0; i--) {
    const p = plays[i]!
    if (p.is_focus && p.pts !== null) return { pts: p.pts, reb: p.reb ?? 0, ast: p.ast ?? 0 }
  }
  return null
}

export interface QuarterRow {
  period: number
  label: string
  /** Points in the period; null before it starts. */
  away: number | null
  home: number | null
  /** The period in play at the cursor. */
  running: boolean
}

/** Both teams' points per period from the running score, filling as the game plays. */
export function quarterBox(plays: readonly RecapPlaysRow[], tl: Timeline, cursor: number): QuarterRow[] {
  const ends = new Map<number, Score>()
  const started = new Set<number>()
  for (let i = 0; i <= cursor && i < plays.length; i++) {
    const p = plays[i]!
    started.add(p.period)
    if (p.kind === 'period_end') ends.set(p.period, { home: p.score_home, away: p.score_away })
  }
  const now = scoreAt(plays, cursor)
  let prev: Score = { home: 0, away: 0 }
  return tl.periods.map((span) => {
    const end = ends.get(span.period)
    const running = !end && started.has(span.period)
    const at = end ?? (running ? now : null)
    const row: QuarterRow = {
      period: span.period,
      label: span.label,
      away: at ? at.away - prev.away : null,
      home: at ? at.home - prev.home : null,
      running,
    }
    if (end) prev = end
    return row
  })
}

export interface TickerLine {
  key: number
  /** "Q3 04:12" */
  stamp: string
  text: string
}

/** The last few plays at the cursor, oldest first, as the feed describes them. */
export function ticker(plays: readonly RecapPlaysRow[], cursor: number, n: number = TICKER_LINES): TickerLine[] {
  const from = Math.max(0, cursor - n + 1)
  const out: TickerLine[] = []
  for (let i = from; i <= cursor && i < plays.length; i++) {
    const p = plays[i]!
    out.push({ key: i, stamp: playStamp(p), text: p.description })
  }
  return out
}

/** The game clock reading at t, frozen through a stoppage: the cursor play's clock. */
export function clockAt(plays: readonly RecapPlaysRow[], tl: Timeline, t: number): string | null {
  const cursor = playCursor(plays, tl, t)
  const p = plays[cursor]
  return p ? gameClock(p.clock) : null
}

// --- The feed -------------------------------------------------------------------

export type FeedView = 'his' | 'room'
export type Density = 'all' | 'minute'

const MINUTE = 60

/**
 * The feed at the cursor, newest first: his comments, or the room's that
 * kept a body. At 'minute' density one per wall minute, the top-scored.
 */
export function feed(room: Room, cursor: number, view: FeedView, density: Density, limit: number): ReplayComment[] {
  const out: ReplayComment[] = []
  const wanted = (c: ReplayComment) => (view === 'his' ? c.isFocus : !c.isFocus && c.body !== null)
  let i = Math.min(cursor, room.comments.length) - 1
  while (i >= 0 && out.length < limit) {
    const c = room.comments[i]!
    if (!wanted(c)) {
      i--
      continue
    }
    if (density === 'all') {
      out.push(c)
      i--
      continue
    }
    // The bucket this comment closes, walked back to its first row.
    const bucket = Math.floor(c.t / MINUTE)
    let best = c
    while (i >= 0 && Math.floor(room.comments[i]!.t / MINUTE) === bucket) {
      const d = room.comments[i]!
      if (wanted(d) && d.score > best.score) best = d
      i--
    }
    out.push(best)
  }
  return out
}
