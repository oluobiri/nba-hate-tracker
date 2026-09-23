// The week axis of a player's season. player_temporal ships one row per
// week a player was mentioned, keyed by the Monday as an ISO timestamp
// string; missing weeks are missing rows, so a chart first lays the rows
// on the season's spine. Phases are cut on the manifest's calendar dates.
import { fmtInt, fmtPct } from './format'
import { negRate, posRate } from './metrics'
import type { Counts } from './types'

export type Phase = 'pre_season' | 'regular_season' | 'play_in' | 'playoffs' | 'off_season'

export const PHASE_LABELS: Record<Phase, string> = {
  pre_season: 'Preseason',
  regular_season: 'Regular season',
  play_in: 'Play-in',
  playoffs: 'Playoffs',
  off_season: 'Off-season',
}

export interface PhaseBand {
  phase: Phase
  label: string
  /** Index of the band's first week on the spine. */
  start: number
  /** Index one past the band's last week. */
  end: number
}

export type Calendar = Record<string, string | null>

const DAY_MS = 86_400_000
const WEEK_MS = 7 * DAY_MS

const dayOf = (key: string): string => key.slice(0, 10)

/** Every week key in order, with no gaps: the axis a chart lays its rows on. */
export function weekSpine(weeks: readonly string[]): string[] {
  const spine = [...new Set(weeks)].toSorted()
  for (let i = 1; i < spine.length; i++) {
    const gap = Date.parse(dayOf(spine[i]!)) - Date.parse(dayOf(spine[i - 1]!))
    if (gap !== WEEK_MS) throw new Error(`week spine has a gap between ${spine[i - 1]} and ${spine[i]}`)
  }
  return spine
}

/** Rows laid on the spine, null where the week has no row. */
export function spineRows<T extends { week: string }>(spine: readonly string[], rows: readonly T[]): (T | null)[] {
  const byWeek = new Map(rows.map((r) => [r.week, r]))
  return spine.map((w) => byWeek.get(w) ?? null)
}

/** The Monday key ("YYYY-MM-DDT00:00:00") of the week holding a "YYYY-MM-DD" day. */
export function weekOf(day: string): string {
  const t = Date.parse(day)
  const back = (new Date(t).getUTCDay() + 6) % 7
  return `${new Date(t - back * DAY_MS).toISOString().slice(0, 10)}T00:00:00`
}

/** "Feb 9" for a week key or a day. */
export function weekLabel(key: string): string {
  return new Date(Date.parse(dayOf(key))).toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' })
}

/** The season phase a day falls in, or null when the calendar has no opening night. */
export function phaseOf(day: string, cal: Calendar): Phase | null {
  const opening = cal['opening_night']
  if (!opening) return null
  const d = dayOf(day)
  if (d < opening) return 'pre_season'
  const finalsEnd = cal['finals_end']
  if (finalsEnd && d > finalsEnd) return 'off_season'
  const playoffs = cal['playoffs_start']
  if (playoffs && d >= playoffs) return 'playoffs'
  const playInStart = cal['play_in_start']
  const playInEnd = cal['play_in_end']
  if (playInStart && d >= playInStart && (!playInEnd || d <= playInEnd)) return 'play_in'
  return 'regular_season'
}

/** Contiguous runs of one phase along the spine; empty when the calendar cannot place a week. */
export function phaseBands(spine: readonly string[], cal: Calendar): PhaseBand[] {
  const bands: PhaseBand[] = []
  spine.forEach((week, i) => {
    const phase = phaseOf(week, cal)
    if (!phase) return
    const last = bands.at(-1)
    if (last && last.phase === phase && last.end === i) last.end = i + 1
    else bands.push({ phase, label: PHASE_LABELS[phase], start: i, end: i + 1 })
  })
  return bands.length === spine.length || bands.every((b) => b.end - b.start > 0) ? bands : []
}

/** The worst week (highest negative share) and best week (highest positive share) among weeks with at least `floor` comments, as spine indices. */
export function extremeWeeks(rows: readonly (Counts | null)[], floor: number): { worst: number | null; best: number | null } {
  let worst: number | null = null
  let best: number | null = null
  rows.forEach((r, i) => {
    if (!r || r.total < floor) return
    if (worst === null || negRate(r) > negRate(rows[worst]!)) worst = i
    if (best === null || posRate(r) > posRate(rows[best]!)) best = i
  })
  return { worst, best }
}

/** One sentence for the timeline: what the lines did, the worst and best weeks, how many weeks fell under the floor. */
export function timelineSummary(
  name: string,
  spine: readonly string[],
  rows: readonly (Counts | null)[],
  negLine: readonly (number | null)[],
  floor: number,
  k: number,
): string {
  const drawn = negLine.filter((v): v is number => v !== null)
  const thin = rows.filter((r) => !r || r.total < floor).length
  const floorNote = thin ? ` ${fmtInt(thin)} of ${fmtInt(spine.length)} weeks had fewer than ${fmtInt(floor)} comments and are left off the line.` : ''
  if (drawn.length < 2) return `Too few weeks with ${fmtInt(floor)} comments about ${name} to draw a line.${floorNote}`
  const { worst, best } = extremeWeeks(rows, floor)
  const lo = fmtPct(Math.min(...drawn), 0)
  const hi = fmtPct(Math.max(...drawn), 0)
  const worstNote =
    worst === null ? '' : ` His worst week was the week of ${weekLabel(spine[worst]!)}, ${fmtPct(negRate(rows[worst]!), 0)} negative of ${fmtInt(rows[worst]!.total)} comments`
  const bestNote = best === null ? '' : `${worst === null ? ' His' : '; his'} best the week of ${weekLabel(spine[best]!)}, ${fmtPct(posRate(rows[best]!), 0)} positive`
  const tail = worst === null && best === null ? '' : `${worstNote}${bestNote}.`
  return `Over ${fmtInt(k)}-week windows, the negative share of comments about ${name} ran between ${lo} and ${hi}.${tail}${floorNote}`
}
