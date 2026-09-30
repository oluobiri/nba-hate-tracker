// The replay's clocks. Wall time is the axis: `t` is integer wall seconds
// since tip-off, so a timeout is a stretch of t on which the game clock
// stands still while the comments keep coming. Playback units follow t
// inside a period and compress each break to one card of fixed width; the
// scrubber is drawn in playback units, the URL carries t. Everything here is
// pure and reads the periods and plays frames as rows.
import type { RecapPeriodsRow, RecapPlaysRow } from '../data/types.gen'
import { ordinal } from './format'
import { periodLabel, periodWord } from './recaps'

/** Playback units one break occupies, whatever its wall length: a page choice. */
export const BREAK_CARD = 180
/** Multipliers against wall time: a page choice. */
export const SPEEDS = [30, 60, 120, 300] as const
export type Speed = (typeof SPEEDS)[number]
/** The default preset is the one that plays the whole game nearest this: a page choice. */
export const TARGET_MINUTES = 3

const HALF = 2

export interface PeriodSpan {
  period: number
  /** "Q1".."Q4", then "OT1".. */
  label: string
  /** Epoch seconds of the period's start and end markers. */
  startWall: number
  endWall: number
  /** Cumulative game seconds at the markers. */
  startSeconds: number
  endSeconds: number
}

export interface Segment {
  kind: 'period' | 'break'
  /** The period, or the period a break follows. */
  period: number
  /** "Q3", "Halftime", "End of 3rd". */
  label: string
  /** Wall seconds since tip. */
  t0: number
  t1: number
  /** Playback units. */
  p0: number
  p1: number
}

export interface Timeline {
  /** Epoch seconds of the tip and the final buzzer. */
  tip: number
  buzzer: number
  /** Wall seconds from tip to buzzer: the domain of t. */
  total: number
  periods: PeriodSpan[]
  segments: Segment[]
  /** Playback units from tip to buzzer: the domain of the scrubber. */
  length: number
}

/** "Halftime" after the second period, "End of 3rd" otherwise. */
export function breakLabel(afterPeriod: number): string {
  return afterPeriod === HALF ? 'Halftime' : `End of ${periodWord(afterPeriod)}`
}

/** The timeline from the periods frame. Throws on a frame the clock cannot read. */
export function buildTimeline(rows: readonly RecapPeriodsRow[]): Timeline {
  const periods = rows
    .toSorted((a, b) => a.period - b.period)
    .map((r) => ({ period: r.period, label: periodLabel(r.period), startWall: r.start_wall, endWall: r.end_wall, startSeconds: r.start_seconds, endSeconds: r.end_seconds }))
  if (!periods.length) throw new Error('periods: empty')
  periods.forEach((p, i) => {
    if (p.period !== i + 1) throw new Error(`periods: ${p.period} where ${i + 1} was expected`)
    if (p.endWall <= p.startWall) throw new Error(`periods: ${p.label} ends before it starts`)
    const prev = periods[i - 1]
    if (prev && p.startWall < prev.endWall) throw new Error(`periods: ${p.label} starts before ${prev.label} ends`)
  })
  const tip = periods[0]!.startWall
  const buzzer = periods[periods.length - 1]!.endWall
  const segments: Segment[] = []
  let p = 0
  periods.forEach((span, i) => {
    const t0 = span.startWall - tip
    const t1 = span.endWall - tip
    segments.push({ kind: 'period', period: span.period, label: span.label, t0, t1, p0: p, p1: p + (t1 - t0) })
    p += t1 - t0
    const next = periods[i + 1]
    if (next && next.startWall > span.endWall) {
      segments.push({ kind: 'break', period: span.period, label: breakLabel(span.period), t0: t1, t1: next.startWall - tip, p0: p, p1: p + BREAK_CARD })
      p += BREAK_CARD
    }
  })
  return { tip, buzzer, total: buzzer - tip, periods, segments, length: p }
}

const clamp = (v: number, lo: number, hi: number): number => Math.min(hi, Math.max(lo, v))

// A period owns both its marker seconds (the end marker's own second is still
// live); a break owns the open interval between two periods.
function segmentAt(tl: Timeline, t: number): Segment {
  for (const s of tl.segments) {
    if (s.kind === 'period' ? t >= s.t0 && t <= s.t1 : t > s.t0 && t < s.t1) return s
  }
  return tl.segments[tl.segments.length - 1]!
}

/** Wall seconds since tip → playback units, linear inside each segment. */
export function toPlayback(tl: Timeline, t: number): number {
  const c = clamp(t, 0, tl.total)
  const s = segmentAt(tl, c)
  return s.p0 + ((c - s.t0) / (s.t1 - s.t0)) * (s.p1 - s.p0)
}

/** Playback units → wall seconds since tip, the inverse, rounded to the second. */
export function fromPlayback(tl: Timeline, p: number): number {
  const c = clamp(p, 0, tl.length)
  const s = tl.segments.find((seg) => c >= seg.p0 && c <= seg.p1) ?? tl.segments[tl.segments.length - 1]!
  return Math.round(s.t0 + ((c - s.p0) / (s.p1 - s.p0)) * (s.t1 - s.t0))
}

export type Phase = 'pre' | 'live' | 'break' | 'post'

export interface Moment {
  phase: Phase
  /** The period playing or just ended; 0 before the tip. */
  period: number
  /** "Q3", "Halftime", "Pregame", "Final". */
  label: string
  segment: Segment | null
}

/** Where t falls: before the tip, in a period, in a break, after the buzzer. */
export function phaseAt(tl: Timeline, t: number): Moment {
  if (t < 0) return { phase: 'pre', period: 0, label: 'Pregame', segment: null }
  if (t > tl.total) return { phase: 'post', period: tl.periods.length, label: 'Final', segment: null }
  const s = segmentAt(tl, t)
  return { phase: s.kind === 'period' ? 'live' : 'break', period: s.period, label: s.label, segment: s }
}

/** Index of the last play logged at or before t; -1 before the first. Plays are in feed order. */
export function playCursor(plays: readonly RecapPlaysRow[], tl: Timeline, t: number): number {
  const at = tl.tip + t
  let lo = 0
  let hi = plays.length
  while (lo < hi) {
    const mid = (lo + hi) >> 1
    if (plays[mid]!.wall_clock <= at) lo = mid + 1
    else hi = mid
  }
  return lo - 1
}

const FEED_CLOCK = /^PT(\d+)M(\d+)(?:\.\d+)?S$/

/** "PT11M35.00S" → "11:35"; "--:--" for a string the feed never writes. */
export function gameClock(clock: string): string {
  const m = FEED_CLOCK.exec(clock)
  if (!m) return '--:--'
  return `${m[1]!.padStart(2, '0')}:${m[2]!.padStart(2, '0')}`
}

/** "Q3 04:12": a play's stamp for the ticker and the feed. */
export function playStamp(play: Pick<RecapPlaysRow, 'period' | 'clock'>): string {
  return `${periodLabel(play.period)} ${gameClock(play.clock)}`
}

export type Stoppage = { kind: 'tip' } | { kind: 'timeout'; team: string | null } | { kind: 'period_end'; period: number; final: boolean } | null

/**
 * Why the clock stands still at the cursor, read back through the plays
 * logged on the same game second: a timeout holds through the substitutions
 * made during it; a period's start clears the previous end.
 */
export function stoppageAt(plays: readonly RecapPlaysRow[], cursor: number, tl: Timeline): Stoppage {
  const at = plays[cursor]
  if (!at) return { kind: 'tip' }
  for (let i = cursor; i >= 0; i--) {
    const p = plays[i]!
    if (p.game_seconds !== at.game_seconds) break
    if (p.kind === 'period_start') return p.period === 1 && i === cursor ? { kind: 'tip' } : null
    if (p.kind === 'timeout') return { kind: 'timeout', team: p.team_tricode }
    if (p.kind === 'period_end') return { kind: 'period_end', period: p.period, final: p.period === tl.periods.length }
  }
  return null
}

/** "TIMEOUT · SAS", "HALFTIME", "END OF 3RD", "FINAL"; null while the clock runs. */
export function stoppageLabel(s: Stoppage): string | null {
  if (!s) return null
  if (s.kind === 'tip') return 'TIP'
  if (s.kind === 'timeout') return s.team ? `TIMEOUT · ${s.team}` : 'TIMEOUT'
  if (s.final) return 'FINAL'
  if (s.period === HALF) return 'HALFTIME'
  return `END OF ${(s.period <= 4 ? ordinal(s.period) : periodLabel(s.period)).toUpperCase()}`
}

/** Real seconds the whole replay takes at a preset. */
export function durationSeconds(tl: Timeline, speed: Speed): number {
  return tl.length / speed
}

/** The preset whose whole-game duration is nearest TARGET_MINUTES. */
export function defaultSpeed(tl: Timeline): Speed {
  let best: Speed = SPEEDS[0]
  let gap = Infinity
  for (const s of SPEEDS) {
    const d = Math.abs(durationSeconds(tl, s) / 60 - TARGET_MINUTES)
    if (d < gap) {
      gap = d
      best = s
    }
  }
  return best
}

/** "the game in 3 min", never under one. */
export function speedPhrase(tl: Timeline, speed: Speed): string {
  return `the game in ${Math.max(1, Math.round(durationSeconds(tl, speed) / 60))} min`
}

const ET = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit' })

/** "9:47 PM ET" from epoch seconds. */
export function etTime(epoch: number): string {
  return `${ET.format(new Date(epoch * 1000))} ET`
}

/** The wall clock at t, in ET. */
export function wallStamp(tl: Timeline, t: number): string {
  return etTime(tl.tip + t)
}
