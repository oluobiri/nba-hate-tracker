// The replay's reading of a recap file: the room (every comment on the
// timeline, his with prefix counts), the floor from the stints, the box
// lines from the plays, his moments, the court's ends and the feed's
// selection. Every function is pure and reads the rows the frames give.
import type { Columnar, RecapCommentsRow, RecapDocument, RecapPeriodsRow, RecapPlaysRow, RecapRows, RecapStintsRow } from '../data/types.gen'
import { idxAt, type Timeline, uOfWall } from './clock'
import { periodLabel, type PeriodCell } from './recaps'
import { type Counts, type Sentiment, SENTIMENTS } from './types'

/** The right-now window: his last comments, by count, since density varies twentyfold. */
export const RIGHT_NOW = 25
/** The strip's rolling window over his comments, and the fewest it draws a point from. */
const FLOW_WINDOW = 60
const FLOW_MIN = 20
export const FLOW_SAMPLES = 300
export const FLOW_BINS = 150
/** Top density: the top-voted comment per this many replay seconds at 1×, scaled by speed. */
const TOP_BUCKET = 1.1

const PHASE_LIVE = 'live'
const PHASE_BREAK = 'break'
const KIND_SHOT = 'shot'
const KIND_FREE_THROW = 'free_throw'
const KIND_REBOUND = 'rebound'
const KIND_STEAL = 'steal'
const KIND_BLOCK = 'block'
const KIND_TURNOVER = 'turnover'
const KIND_FOUL = 'foul'
const KIND_SUB_IN = 'sub_in'
const KIND_SUB_OUT = 'sub_out'
const OFFENSIVE_REBOUND = 'offensive'
const TECHNICAL = 'technical'
const THREE = '3pt'

// --- Rows ---------------------------------------------------------------------

/** Column arrays as rows, once, when the file arrives. */
export function toRows<T extends object>(frame: Columnar<T>): T[] {
  const cols = Object.keys(frame) as (keyof T)[]
  const n = cols.length ? (frame[cols[0]!] as unknown[]).length : 0
  const out: T[] = []
  for (let i = 0; i < n; i++) {
    const row = {} as T
    for (const c of cols) row[c] = (frame[c] as T[keyof T][])[i]!
    out.push(row)
  }
  return out
}

export const recapRows = (doc: RecapDocument): RecapRows => ({
  periods: toRows(doc.frames.periods),
  threads: toRows(doc.frames.threads),
  stints: toRows(doc.frames.stints),
  plays: toRows(doc.frames.plays),
  comments: toRows(doc.frames.comments),
})

// --- The room -------------------------------------------------------------------

export interface ReplayComment {
  id: string
  postId: string
  /** Replay seconds. */
  u: number
  wall: number
  sentiment: Sentiment
  score: number
  fanTeam: string | null
  playerId: number | null
  isFocus: boolean
  body: string | null
  phase: string
  /** The period it belongs to, a break's to the period just played; null outside the game. */
  period: number | null
}

export interface Room {
  /** Every comment, in replay order. */
  comments: ReplayComment[]
  commentU: number[]
  /** Indices of his comments, in order. */
  focus: number[]
  focusU: number[]
  /** prefix[s][k]: how many of his first k comments are s. */
  prefix: Record<Sentiment, Int32Array>
}

const asSentiment = (s: string): Sentiment => (s === 'pos' ? 'pos' : s === 'neu' ? 'neu' : 'neg')

/** The period a comment was posted in, by the wall clock as the registry counts it; a break's is the period just played; null outside the game. */
export function periodOf(c: Pick<RecapCommentsRow, 'phase' | 'created_utc'>, periods: readonly RecapPeriodsRow[]): number | null {
  if (c.phase !== PHASE_LIVE && c.phase !== PHASE_BREAK) return null
  let period: number | null = null
  for (const p of periods) if (p.start_wall <= c.created_utc) period = p.period
  return period
}

export function buildRoom(comments: readonly RecapCommentsRow[], tl: Timeline): Room {
  const rows: ReplayComment[] = comments
    .map((c) => ({
      id: c.comment_id,
      postId: c.post_id,
      u: uOfWall(tl, c.created_utc),
      wall: c.created_utc,
      sentiment: asSentiment(c.sentiment),
      score: c.score,
      fanTeam: c.fan_team,
      playerId: c.player_id,
      isFocus: c.is_focus,
      body: c.body,
      phase: c.phase,
      period: periodOf(c, tl.periods),
    }))
    .toSorted((a, b) => a.u - b.u || a.id.localeCompare(b.id))
  const focus: number[] = []
  rows.forEach((c, i) => {
    if (c.isFocus) focus.push(i)
  })
  const prefix: Record<Sentiment, Int32Array> = { neg: new Int32Array(focus.length + 1), neu: new Int32Array(focus.length + 1), pos: new Int32Array(focus.length + 1) }
  focus.forEach((ci, k) => {
    for (const s of SENTIMENTS) prefix[s][k + 1] = prefix[s][k]! + (rows[ci]!.sentiment === s ? 1 : 0)
  })
  return { comments: rows, commentU: rows.map((c) => c.u), focus, focusU: focus.map((i) => rows[i]!.u), prefix }
}

/** The index of the last comment at or before `u`; −1 before the first. */
export const commentCursor = (room: Room, u: number): number => idxAt(room.commentU, u)

/** How many of his comments have landed by `u`. */
export const focusCount = (room: Room, u: number): number => idxAt(room.focusU, u) + 1

/** His comments from the a-th to the k-th (exclusive), from the prefix. */
export function countsBetween(room: Room, a: number, k: number): Counts {
  const neg = room.prefix.neg[k]! - room.prefix.neg[a]!
  const neu = room.prefix.neu[k]! - room.prefix.neu[a]!
  const pos = room.prefix.pos[k]! - room.prefix.pos[a]!
  return { neg, neu, pos, total: neg + neu + pos }
}

/** His last `n` comments by `u`: fewer when fewer have landed. */
export function rightNow(room: Room, u: number, n: number = RIGHT_NOW): Counts {
  const k = focusCount(room, u)
  return countsBetween(room, Math.max(0, k - n), k)
}

/** Every one of his comments by `u`. */
export const soFar = (room: Room, u: number): Counts => countsBetween(room, 0, focusCount(room, u))

/** His comments inside the game by period, at the final: the registry's by_period, re-read from the file. */
export function roomByPeriod(room: Room, periods: readonly RecapPeriodsRow[]): PeriodCell[] {
  const cells = periods.map((p) => ({ key: p.period, label: periodLabel(p.period), counts: { neg: 0, neu: 0, pos: 0, total: 0 } }))
  const byKey = new Map(cells.map((c) => [c.key, c.counts]))
  for (const i of room.focus) {
    const c = room.comments[i]!
    const counts = c.period === null ? undefined : byKey.get(c.period)
    if (!counts) continue
    counts[c.sentiment]++
    counts.total++
  }
  return cells
}

/** The comments about each player by the cursor: the box score's ROOM column. */
export function roomByPlayer(room: Room, cursor: number): Map<number, Counts> {
  const out = new Map<number, Counts>()
  for (let i = 0; i <= cursor; i++) {
    const c = room.comments[i]!
    if (c.playerId === null) continue
    let counts = out.get(c.playerId)
    if (!counts) {
      counts = { neg: 0, neu: 0, pos: 0, total: 0 }
      out.set(c.playerId, counts)
    }
    counts[c.sentiment]++
    counts.total++
  }
  return out
}

export interface FlowSeries {
  /** One point per sample across the whole replay; null where fewer than FLOW_MIN of his comments have landed. */
  neg: (number | null)[]
  pos: (number | null)[]
  /** Every comment's volume, binned. */
  bins: number[]
  max: number
}

/** The strip's series: his negative and positive shares over a rolling window, and the room's volume. */
export function flowSeries(room: Room, tl: Timeline, samples: number = FLOW_SAMPLES, bins: number = FLOW_BINS): FlowSeries {
  const neg: (number | null)[] = []
  const pos: (number | null)[] = []
  for (let k = 0; k <= samples; k++) {
    const u = (k / samples) * tl.totalU
    const j = focusCount(room, u)
    const a = Math.max(0, j - FLOW_WINDOW)
    const n = j - a
    if (n < FLOW_MIN) {
      neg.push(null)
      pos.push(null)
      continue
    }
    const c = countsBetween(room, a, j)
    neg.push(c.neg / n)
    pos.push(c.pos / n)
  }
  const volume: number[] = Array.from({ length: bins }, () => 0)
  for (const u of room.commentU) volume[Math.min(bins - 1, Math.floor((u / tl.totalU) * bins))]!++
  return { neg, pos, bins: volume, max: Math.max(1, ...volume) }
}

// --- The floor -------------------------------------------------------------------

/** Who is on the floor at game second `g` of `period`; a stint's end second is off, except at the buzzer. */
export function onFloor(stints: readonly RecapStintsRow[], period: number, g: number, periodEnd: number): Set<number> {
  const on = new Set<number>()
  for (const s of stints) {
    if (s.period !== period) continue
    if (s.start_seconds <= g && (g < s.end_seconds || (g === periodEnd && s.end_seconds === g))) on.add(s.person_id)
  }
  return on
}

/** Each team's players in the order the box score lists them: the opening five, then by first stint. */
export function rosterOrder(stints: readonly RecapStintsRow[]): Map<string, number[]> {
  const first = new Map<number, { team: string; start: number; period: number }>()
  for (const s of stints) {
    const seen = first.get(s.person_id)
    if (!seen || s.period < seen.period || (s.period === seen.period && s.start_seconds < seen.start)) first.set(s.person_id, { team: s.team_tricode, start: s.start_seconds, period: s.period })
  }
  const out = new Map<string, number[]>()
  for (const [id, f] of [...first.entries()].toSorted((a, b) => a[1].period - b[1].period || a[1].start - b[1].start || a[0] - b[0])) {
    if (!out.has(f.team)) out.set(f.team, [])
    out.get(f.team)!.push(id)
  }
  return out
}

/** person_id → the feed's short name ("V. Wembanyama"), from the first play that names him. */
export function playerNames(plays: readonly RecapPlaysRow[]): Map<number, string> {
  const out = new Map<number, string>()
  for (const p of plays) if (p.person_id && p.player_name_i && !out.has(p.person_id)) out.set(p.person_id, p.player_name_i)
  return out
}

/** "Wembanyama" from "V. Wembanyama"; the whole name when there is no initial. */
export const lastName = (name: string): string => name.replace(/^[A-Z]\.\s*/, '')

// --- The box -----------------------------------------------------------------------

export interface PlayerLine {
  pts: number
  reb: number
  oreb: number
  dreb: number
  ast: number
  stl: number
  blk: number
  tov: number
  pf: number
  fgm: number
  fga: number
  fg3m: number
  fg3a: number
  ftm: number
  fta: number
}

export const emptyLine = (): PlayerLine => ({ pts: 0, reb: 0, oreb: 0, dreb: 0, ast: 0, stl: 0, blk: 0, tov: 0, pf: 0, fgm: 0, fga: 0, fg3m: 0, fg3a: 0, ftm: 0, fta: 0 })

/** Every player's line from the plays through the cursor, by the rules the box score is checked with. */
export function boxLines(plays: readonly RecapPlaysRow[], cursor: number): Map<number, PlayerLine> {
  const out = new Map<number, PlayerLine>()
  const line = (id: number): PlayerLine => {
    let l = out.get(id)
    if (!l) {
      l = emptyLine()
      out.set(id, l)
    }
    return l
  }
  for (let i = 0; i <= cursor; i++) {
    const r = plays[i]!
    if (!r.person_id) continue
    const s = line(r.person_id)
    switch (r.kind) {
      case KIND_SHOT: {
        s.fga++
        if (r.action_type === THREE) s.fg3a++
        if (r.made) {
          s.fgm++
          s.pts += r.shot_value
          if (r.action_type === THREE) s.fg3m++
          if (r.assist_person_id) line(r.assist_person_id).ast++
        }
        break
      }
      case KIND_FREE_THROW: {
        s.fta++
        if (r.made) {
          s.ftm++
          s.pts += r.shot_value
        }
        break
      }
      case KIND_REBOUND: {
        s.reb++
        if (r.sub_type === OFFENSIVE_REBOUND) s.oreb++
        else s.dreb++
        break
      }
      case KIND_STEAL:
        s.stl++
        break
      case KIND_BLOCK:
        s.blk++
        break
      case KIND_TURNOVER:
        s.tov++
        break
      case KIND_FOUL:
        if (r.sub_type !== TECHNICAL) s.pf++
        break
      default:
        break
    }
  }
  return out
}

export const sumLines = (lines: readonly PlayerLine[]): PlayerLine => {
  const t = emptyLine()
  for (const l of lines) for (const k of Object.keys(t) as (keyof PlayerLine)[]) t[k] += l[k]
  return t
}

/** Away and home at the cursor; 0–0 before the first play. */
export function scoreAt(plays: readonly RecapPlaysRow[], cursor: number): { away: number; home: number } {
  const r = plays[cursor]
  return r ? { away: r.score_away, home: r.score_home } : { away: 0, home: 0 }
}

export interface PeriodPoints {
  period: number
  label: string
  /** Null until the period has begun. */
  away: number | null
  home: number | null
}

/** Points per period through the cursor: a period in progress shows its points so far. */
export function lineScore(plays: readonly RecapPlaysRow[], cursor: number, periods: readonly RecapPeriodsRow[]): PeriodPoints[] {
  const end = new Map<number, { away: number; home: number }>()
  for (let i = 0; i <= cursor; i++) {
    const r = plays[i]!
    end.set(r.period, { away: r.score_away, home: r.score_home })
  }
  let prev = { away: 0, home: 0 }
  return periods.map((p) => {
    const at = end.get(p.period)
    const row: PeriodPoints = { period: p.period, label: periodLabel(p.period), away: at ? at.away - prev.away : null, home: at ? at.home - prev.home : null }
    if (at) prev = at
    return row
  })
}

// --- His moments ---------------------------------------------------------------------

export interface Moment {
  /** The play's index. */
  i: number
  /** "DUNK", "BLOCK", "ASSIST", "MISS", "FOUL"… */
  label: string
  /** The caption's words after the label, his name stripped. */
  text: string
  /** The index of the shot to pulse on the court; null for a play with no spot. */
  mark: number | null
}

const DUNK = /dunk/i
const LAYUP = /layup/i
const FLAGRANT = /flagrant/i

const stripName = (text: string, name: string): string => text.replace(`${name} `, '')
const stripMiss = (text: string): string => text.replace(/^MISS /, '')

/** His shots, blocks, steals, turnovers, fouls and assists, by play index. */
export function moments(plays: readonly RecapPlaysRow[], focusId: number, focusName: string): Map<number, Moment> {
  const byNumber = new Map(plays.map((p, i) => [p.action_number, i]))
  const out = new Map<number, Moment>()
  plays.forEach((r, i) => {
    let label: string | null = null
    let text = r.description
    let mark: number | null = null
    if (r.person_id === focusId) {
      if (r.kind === KIND_SHOT) {
        label = r.made ? (DUNK.test(r.description) ? 'DUNK' : r.action_type === THREE ? 'THREE' : LAYUP.test(r.description) ? 'LAYUP' : 'BUCKET') : 'MISS'
        mark = i
        text = stripMiss(r.description)
      } else if (r.kind === KIND_BLOCK) {
        label = 'BLOCK'
        const shot = r.paired_action_number === null ? undefined : byNumber.get(r.paired_action_number)
        mark = shot ?? null
        text = shot === undefined ? r.description : `on ${stripMiss(plays[shot]!.description).replace(/ - blocked$/, '')}`
      } else if (r.kind === KIND_STEAL) label = 'STEAL'
      else if (r.kind === KIND_TURNOVER) label = 'TURNOVER'
      else if (r.kind === KIND_FOUL) label = FLAGRANT.test(r.description) ? 'FLAGRANT' : 'FOUL'
    } else if (r.assist_person_id === focusId && r.made) {
      label = 'ASSIST'
      mark = i
      text = `to ${r.description.replace(new RegExp(`\\s*\\(${focusName.replace('.', '\\.')} \\d+ AST\\)`), '')}`
    }
    if (label) out.set(i, { i, label, text: stripName(text, focusName), mark })
  })
  return out
}

/** The caption's play: the last one that is not a substitution. */
export function captionPlay(plays: readonly RecapPlaysRow[], cursor: number): RecapPlaysRow | null {
  for (let j = cursor; j >= 0; j--) {
    const r = plays[j]!
    if (r.kind !== KIND_SUB_IN && r.kind !== KIND_SUB_OUT) return r
  }
  return null
}

// --- The court -----------------------------------------------------------------------

export interface Ends {
  left: string
  right: string
}

/** Which team attacks which end, per period, read from where its shots went up; teams switch at half. */
export function courtEnds(plays: readonly RecapPlaysRow[], periods: readonly RecapPeriodsRow[]): Map<number, Ends> {
  const teams = [...new Set(plays.map((p) => p.team_tricode).filter((t): t is string => t !== null))]
  const out = new Map<number, Ends>()
  let last: Ends | null = null
  for (const p of periods) {
    const xs = new Map<string, number[]>()
    for (const r of plays) {
      if (r.period !== p.period || r.kind !== KIND_SHOT || r.x === null || !r.team_tricode) continue
      if (!xs.has(r.team_tricode)) xs.set(r.team_tricode, [])
      xs.get(r.team_tricode)!.push(r.x)
    }
    const means = [...xs.entries()].map(([t, v]) => [t, v.reduce((a, b) => a + b, 0) / v.length] as const).toSorted((a, b) => b[1] - a[1])
    if (means.length) {
      const right = means[0]![0]
      const left = means.find(([t]) => t !== right)?.[0] ?? teams.find((t) => t !== right) ?? right
      last = { left, right }
    }
    if (last) out.set(p.period, last)
  }
  return out
}

/** The court's coordinate space: 94 by 50 feet at ten units a foot. */
export const COURT = { w: 940, h: 500 }
/** A play's full-court position (x along, y across, both 0–100) on the court. */
export const courtXY = (r: Pick<RecapPlaysRow, 'x' | 'y'>): [number, number] | null => (r.x === null || r.y === null ? null : [(r.x / 100) * COURT.w, (r.y / 100) * COURT.h])

/** Shot index → the index of the block that ended it. */
export function blockedBy(plays: readonly RecapPlaysRow[]): Map<number, number> {
  const byNumber = new Map(plays.map((p, i) => [p.action_number, i]))
  const out = new Map<number, number>()
  plays.forEach((r, i) => {
    if (r.kind === KIND_BLOCK && r.paired_action_number !== null) {
      const shot = byNumber.get(r.paired_action_number)
      if (shot !== undefined) out.set(shot, i)
    }
  })
  return out
}

// --- The feed -----------------------------------------------------------------------

export type FeedView = 'him' | 'all'
export type FeedDensity = 'top' | 'all'

export interface FeedSelection {
  /** Indices into room.comments, in replay order. */
  idx: number[]
  u: number[]
}

/** The rows the feed draws: every bodied comment, or the top-voted one per bucket of replay time. */
export function feedSelection(room: Room, view: FeedView, density: FeedDensity, speed: number): FeedSelection {
  const pool: number[] = []
  room.comments.forEach((c, i) => {
    if (c.body !== null && (view === 'all' || c.isFocus)) pool.push(i)
  })
  let idx = pool
  if (density === 'top') {
    const best = new Map<number, number>()
    const bucket = TOP_BUCKET * speed
    for (const i of pool) {
      const k = Math.floor(room.comments[i]!.u / bucket)
      const b = best.get(k)
      if (b === undefined || room.comments[i]!.score > room.comments[b]!.score) best.set(k, i)
    }
    idx = [...best.values()].toSorted((a, b) => a - b)
  }
  return { idx, u: idx.map((i) => room.comments[i]!.u) }
}
