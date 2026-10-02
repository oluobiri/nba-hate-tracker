// The replay's timeline: real seconds at 1× (`u`), built once from the plays.
// Live play runs at GAME_RATE game seconds per real second; a stoppage (the
// wall runs while the game clock stands) is squeezed to a short beat; a
// timeout, a quarter break and halftime are cards that hold the clock while
// the comments keep arriving. Every function here is pure.
import type { RecapPeriodsRow, RecapPlaysRow } from '../data/types.gen'
import { periodLabel } from './recaps'

/** Game seconds per real second at 1×: 48 minutes in 2. */
export const GAME_RATE = 24
/** Wall seconds per real second inside a stoppage. */
const STOP_RATE = 60
/** The longest beat an ordinary stoppage gets (fouls, free throws, subs), in tenths of a second. */
const STOP_CAP = 9 / 10
/** A timeout's card holds at least this long, and its stoppage at most TIMEOUT_CAP. */
const TIMEOUT_MIN = 2.5
const TIMEOUT_CAP = 3
/** The card after a period ends: a quarter break, halftime, or an overtime break. */
const BREAK_AFTER: Record<number, number> = { 1: 4, 2: 6, 3: 4 }
const BREAK_DEFAULT = 4
/** Pre-game comments squeezed into the first seconds; post-game reactions after the buzzer. */
export const PRE = 3
export const POST = 6
const PRE_WINDOW = 30 * 60
const POST_WINDOW = 20 * 60

const HALFTIME_AFTER = 2
const KIND_TIMEOUT = 'timeout'
const KIND_PERIOD_END = 'period_end'

export interface Anchor {
  u: number
  /** Epoch seconds. */
  wall: number
  /** Game seconds, counting up across periods. */
  g: number
  period: number
}

export type CardKind = 'timeout' | 'break' | 'halftime'

export interface Card {
  u0: number
  u1: number
  kind: CardKind
  /** "TIMEOUT · SAS", "END OF Q1", "HALFTIME". */
  label: string
  /** The period the card follows. */
  period: number
}

export interface Timeline {
  anchors: Anchor[]
  /** anchors[i].u, for the binary searches. */
  anchorU: number[]
  /** One per play, in feed order. */
  playU: number[]
  cards: Card[]
  /** The buzzer at 1×. */
  endU: number
  /** endU plus the post-game tail. */
  totalU: number
  /** Wall seconds of the tip and the final buzzer. */
  tip: number
  buzzer: number
  periods: RecapPeriodsRow[]
}

/** The last index whose value is at or before `x`; −1 before the first. */
export function idxAt(arr: readonly number[], x: number): number {
  let lo = 0
  let hi = arr.length - 1
  let r = -1
  while (lo <= hi) {
    const m = (lo + hi) >> 1
    if (arr[m]! <= x) {
      r = m
      lo = m + 1
    } else hi = m - 1
  }
  return r
}

const timeoutLabel = (p: RecapPlaysRow): string => (p.team_tricode ? `TIMEOUT · ${p.team_tricode}` : 'TIMEOUT')
const breakLabel = (period: number): string => (period === HALFTIME_AFTER ? 'HALFTIME' : `END OF ${periodLabel(period)}`)

/** The timeline from the plays in feed order and the periods frame. */
export function buildTimeline(plays: readonly RecapPlaysRow[], periods: readonly RecapPeriodsRow[]): Timeline {
  if (plays.length === 0 || periods.length === 0) throw new Error('a timeline needs plays and periods')
  const sorted = periods.toSorted((a, b) => a.period - b.period)
  const anchors: Anchor[] = []
  const playU: number[] = []
  const cards: Card[] = []
  let u = PRE
  let prev: RecapPlaysRow | null = null
  // The feed stamps a timeout and its substitutions on one second, so the
  // card is held open through them and spans the dead time that follows.
  let timeout: RecapPlaysRow | null = null
  for (const r of plays) {
    if (prev) {
      const dw = r.wall_clock - prev.wall_clock
      const dg = r.game_seconds - prev.game_seconds
      if (prev.kind === KIND_PERIOD_END) {
        const d = BREAK_AFTER[prev.period] ?? BREAK_DEFAULT
        cards.push({ u0: u, u1: u + d, kind: prev.period === HALFTIME_AFTER ? 'halftime' : 'break', label: breakLabel(prev.period), period: prev.period })
        u += d
        timeout = null
      } else if (!(timeout && dw === 0 && dg === 0)) {
        const idle = Math.max(dw - dg, 0)
        let stop = Math.min(idle / STOP_RATE, timeout || r.kind === KIND_TIMEOUT ? TIMEOUT_CAP : STOP_CAP)
        if (timeout) {
          stop = Math.max(stop, TIMEOUT_MIN)
          cards.push({ u0: u, u1: u + stop, kind: 'timeout', label: timeoutLabel(timeout), period: timeout.period })
          timeout = null
        }
        // The stoppage comes first, then play resumes: the clock holds, then runs.
        if (stop > 0 && dg > 0) {
          u += stop
          anchors.push({ u, wall: prev.wall_clock + idle, g: prev.game_seconds, period: prev.period })
          stop = 0
        }
        u += dg / GAME_RATE + stop
      }
    }
    anchors.push({ u, wall: r.wall_clock, g: r.game_seconds, period: r.period })
    playU.push(u)
    if (r.kind === KIND_TIMEOUT) timeout = r
    prev = r
  }
  return { anchors, anchorU: anchors.map((a) => a.u), playU, cards, endU: u, totalU: u + POST, tip: plays[0]!.wall_clock, buzzer: prev!.wall_clock, periods: sorted }
}

/** A wall-clock second as replay time: squeezed before the tip, stretched after the buzzer, interpolated between. */
export function uOfWall(tl: Timeline, wall: number): number {
  if (wall < tl.tip) return Math.max(0, PRE * (1 - (tl.tip - wall) / PRE_WINDOW))
  if (wall > tl.buzzer) return tl.endU + POST * Math.min(1, (wall - tl.buzzer) / POST_WINDOW)
  const a = tl.anchors
  let lo = 0
  let hi = a.length - 1
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1
    if (a[mid]!.wall <= wall) lo = mid
    else hi = mid
  }
  const x = a[lo]!
  const y = a[hi]!
  if (y.wall === x.wall) return x.u
  return x.u + ((y.u - x.u) * (wall - x.wall)) / (y.wall - x.wall)
}

/** The inverse: replay time back to the wall clock, for the `t` in a link. */
export function wallOfU(tl: Timeline, u: number): number {
  if (u <= 0) return tl.tip - PRE_WINDOW
  if (u < PRE) return tl.tip - PRE_WINDOW * (1 - u / PRE)
  if (u >= tl.endU) return tl.buzzer + (POST_WINDOW * Math.min(POST, u - tl.endU)) / POST
  const a = tl.anchors
  const i = Math.max(0, idxAt(tl.anchorU, u))
  const x = a[i]!
  const y = a[Math.min(i + 1, a.length - 1)]!
  if (y.u === x.u) return x.wall
  return x.wall + ((y.wall - x.wall) * (u - x.u)) / (y.u - x.u)
}

/** Whole wall seconds since the tip, the unit a deep link carries. */
export const tOfU = (tl: Timeline, u: number): number => Math.max(0, Math.round(wallOfU(tl, u) - tl.tip))
export const uOfT = (tl: Timeline, t: number): number => uOfWall(tl, tl.tip + t)

/** The index of the last play at or before `u`; −1 before the first. */
export const playCursor = (tl: Timeline, u: number): number => idxAt(tl.playU, u)

export const cardAt = (tl: Timeline, u: number): Card | null => tl.cards.find((c) => u >= c.u0 && u < c.u1) ?? null

export interface ClockReading {
  /** "Q1", "OT2", "HALF", "END Q3", "FINAL". */
  label: string
  /** "11:35". */
  time: string
  period: number
}

/** Seconds left as "m:ss", rounded up so the clock reads 0:01 until it reads 0:00. */
export function mmss(left: number): string {
  const s = Math.max(0, Math.ceil(Math.round(left * 1000) / 1000))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

/** The game clock at replay time `u`: it holds through every card. */
export function clockAt(tl: Timeline, u: number): ClockReading {
  const first = tl.periods[0]!
  const last = tl.periods[tl.periods.length - 1]!
  if (u >= tl.endU) return { label: 'FINAL', time: '0:00', period: last.period }
  const i = idxAt(tl.anchorU, u)
  if (i < 0) return { label: periodLabel(first.period), time: mmss(first.end_seconds - first.start_seconds), period: first.period }
  const a = tl.anchors[i]!
  const card = cardAt(tl, u)
  if (card && card.kind !== 'timeout') return { label: card.kind === 'halftime' ? 'HALF' : `END ${periodLabel(card.period)}`, time: '0:00', period: card.period }
  const b = tl.anchors[Math.min(i + 1, tl.anchors.length - 1)]!
  const g = b.u > a.u ? a.g + ((b.g - a.g) * (u - a.u)) / (b.u - a.u) : a.g
  const p = tl.periods.find((x) => x.period === a.period) ?? last
  return { label: periodLabel(a.period), time: mmss(p.end_seconds - g), period: a.period }
}

/** The replay time each period starts at, in period order, for the strip's bands. */
export function periodStartsU(tl: Timeline): { period: number; u: number }[] {
  const out: { period: number; u: number }[] = []
  for (const a of tl.anchors) if (out.length === 0 || out[out.length - 1]!.period !== a.period) out.push({ period: a.period, u: a.u })
  return out
}

const FEED_CLOCK = /^PT(\d+)M(\d+)(?:\.\d+)?S$/

/** The feed's "PT09M44.00S" as "9:44"; "--:--" when unreadable. */
export function gameClock(clock: string): string {
  const m = FEED_CLOCK.exec(clock)
  if (!m) return '--:--'
  return `${Number(m[1])}:${m[2]!.padStart(2, '0')}`
}

/** "Q3 4:12": where a play sits, for a stamp. */
export const playStamp = (play: Pick<RecapPlaysRow, 'period' | 'clock'>): string => `${periodLabel(play.period)} ${gameClock(play.clock)}`

const ET = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit' })

/** "8:43 PM ET". */
export function etTime(epoch: number): string {
  return `${ET.format(new Date(epoch * 1000))} ET`
}

/** "about 5 min at 1×": the replay's length in words. */
export const lengthPhrase = (tl: Timeline): string => `about ${Math.max(1, Math.round(tl.totalU / 60))} min at 1×`

/** The speed presets, as multiples of 1×. */
export const SPEEDS = [1, 2, 4] as const
export type Speed = (typeof SPEEDS)[number]
