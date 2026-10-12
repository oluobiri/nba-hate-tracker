// The season page's figures, computed from the tables at build. The nights
// come from corpus_daily (the attributed population on Eastern game nights)
// and games; the game-night split cuts the phases disjoint on the calendar.
// Every rate is a ratio of summed counts; the thresholds here are page
// choices, and the rules arrive as arguments from the manifest.
import type { CorpusDailyRow, GameSentimentRow, GamesRow } from '../data/types.gen'
import { nickname } from './fans'
import { fmtInt, fmtPct } from './format'
import { countsOf, negRate, posRate, sumCounts } from './metrics'
import type { NightNoteCopy } from './season-copy'
import type { Counts } from './types'
import { type Calendar, weekLabel } from './weeks'

// Page choices, not rules.
/** Nights in the centred window each point on a line pools. */
export const WINDOW = 7
/** Comments a night needs to be named the harshest or the warmest. */
export const NIGHT_MIN_N = 1000

const DAY_MS = 86_400_000

/** "YYYY-MM-DD" moved by n days. */
export const addDays = (iso: string, n: number): string => new Date(Date.parse(iso) + n * DAY_MS).toISOString().slice(0, 10)

/** "Fri, Feb 27". */
export const dayLabel = (iso: string): string => new Date(Date.parse(iso)).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', timeZone: 'UTC' })

// --- The calendar -------------------------------------------------------------

export interface SeasonCalendar {
  opening_night: string
  play_in_start: string
  playoffs_start: string
  finals_start: string
  finals_end: string
  all_star: string
  draft: string
  /** Every dated event the manifest names, by day, for the readouts. */
  events: ReadonlyMap<string, string>
}

const EVENT_NAMES: Record<string, string> = {
  opening_night: 'Opening night',
  nba_cup_final: 'NBA Cup final',
  christmas: 'Christmas',
  trade_deadline: 'Trade deadline',
  all_star: 'All-Star Game',
  play_in_start: 'The first play-in night',
  playoffs_start: 'The playoffs open',
  finals_start: 'Finals Game 1',
  finals_end: 'The last night of the Finals',
  draft: 'Draft night',
}

/** The dates the page cuts on, each required; the build fails naming the one that is missing. */
export function seasonCalendar(cal: Calendar): SeasonCalendar {
  const get = (key: string): string => {
    const v = cal[key]
    if (!v) throw new Error(`calendar: ${key} is missing; the season page cuts on it`)
    return v
  }
  const events = new Map<string, string>()
  for (const [key, name] of Object.entries(EVENT_NAMES)) {
    const day = cal[key]
    if (day) events.set(day, name)
  }
  return {
    opening_night: get('opening_night'),
    play_in_start: get('play_in_start'),
    playoffs_start: get('playoffs_start'),
    finals_start: get('finals_start'),
    finals_end: get('finals_end'),
    all_star: get('all_star'),
    draft: get('draft'),
    events,
  }
}

// --- The nights -------------------------------------------------------------------

export type NightPhase = 'pre' | 'regular' | 'playoffs' | 'off'

export const NIGHT_PHASE_LABELS: Record<NightPhase, string> = { pre: 'Preseason', regular: 'Regular season', playoffs: 'Playoffs', off: 'Offseason' }

/** The phase a night falls in, the play-in and the Finals folded into the playoffs. */
export function nightPhase(day: string, cal: SeasonCalendar): NightPhase {
  if (day < cal.opening_night) return 'pre'
  if (day > cal.finals_end) return 'off'
  if (day >= cal.play_in_start) return 'playoffs'
  return 'regular'
}

export interface Night {
  /** "YYYY-MM-DD", the Eastern game night. */
  day: string
  counts: Counts
  /** Games played that night, from games; the All-Star Game is not one. */
  games: number
  phase: NightPhase
}

/** One row per night in date order, each with its games and its phase. */
export function nightRows(daily: readonly CorpusDailyRow[], games: readonly GamesRow[], cal: SeasonCalendar): Night[] {
  const on = new Map<string, number>()
  for (const g of games) on.set(g.game_date, (on.get(g.game_date) ?? 0) + 1)
  return daily
    .toSorted((a, b) => a.day.localeCompare(b.day))
    .map((r) => ({ day: r.day, counts: { neg: r.neg_count, neu: r.neu_count, pos: r.pos_count, total: r.attributed }, games: on.get(r.day) ?? 0, phase: nightPhase(r.day, cal) }))
}

export type Pole = 'neg' | 'pos'

export const POLE_RATE: Record<Pole, (c: Counts) => number> = { neg: negRate, pos: posRate }

/**
 * The centred window pooled from counts: the k nights around each night
 * summed, then the rate. Null within k/2 of either end, where the window
 * would run off the season; never an average of nightly rates.
 */
export function pooledLine(nights: readonly Night[], k: number, pole: Pole): (number | null)[] {
  const half = Math.floor(k / 2)
  return nights.map((_, i) => {
    if (i - half < 0 || i + half >= nights.length) return null
    const c = sumCounts(nights.slice(i - half, i + half + 1).map((n) => n.counts))
    return c.total ? POLE_RATE[pole](c) : null
  })
}

/** Every comment in one phase, summed. */
export const phaseCounts = (nights: readonly Night[], phase: NightPhase): Counts => sumCounts(nights.filter((n) => n.phase === phase).map((n) => n.counts))

export interface NightExtremes {
  /** The highest negative share among nights at or above the floor. */
  harshest: Night | null
  /** The highest positive share among nights at or above the floor. */
  warmest: Night | null
  /** The most comments. */
  loudest: Night | null
}

export function extremeNights(nights: readonly Night[], floor: number): NightExtremes {
  const big = nights.filter((n) => n.counts.total >= floor)
  const top = (rows: readonly Night[], by: (c: Counts) => number): Night | null => rows.reduce<Night | null>((a, b) => (a === null || by(b.counts) > by(a.counts) ? b : a), null)
  return { harshest: top(big, negRate), warmest: top(big, posRate), loudest: top(nights, (c) => c.total) }
}

export interface Stretch {
  /** The first night from `from` with the line above the level. */
  from: string
  /** The first night after it with the line back at or under the level; null when it never came back. */
  to: string | null
  /** Nights from `from` up to `to`, or to the last night with a line. */
  nights: number
}

/** The stretch the line stayed above a level, looked for from a day on. */
export function aboveStretch(nights: readonly Night[], line: readonly (number | null)[], level: number, from: string): Stretch | null {
  const start = nights.findIndex((n, i) => n.day >= from && line[i] !== null && line[i]! > level)
  if (start < 0) return null
  const back = nights.findIndex((_, i) => i > start && line[i] !== null && line[i]! <= level)
  const lastDrawn = line.reduce<number>((last, v, i) => (v === null ? last : i), -1)
  const end = back < 0 ? lastDrawn + 1 : back
  return { from: nights[start]!.day, to: back < 0 ? null : nights[back]!.day, nights: end - start }
}

/** Points above or below a level, in words, for a night's readout. */
export function againstLevel(value: number | null, level: number): string {
  if (value === null) return ''
  const diff = value - level
  if (Math.abs(diff) < 0.0005) return 'Level with the regular season.'
  return `${(Math.abs(diff) * 100).toFixed(1)} points ${diff > 0 ? 'above' : 'below'} the regular season.`
}

/** What a night was: the calendar's name for it, else its games, else its phase. */
export function nightWhat(n: Night, cal: SeasonCalendar): string {
  const event = cal.events.get(n.day)
  if (event) return event
  if (n.games) return `${n.games} ${n.games === 1 ? 'game' : 'games'}`
  return n.phase === 'pre' ? 'Preseason' : n.phase === 'off' ? 'Offseason' : 'No games'
}

/** The night's spoken sentence: its split, and the lines through it. */
export function nightText(n: Night, cal: SeasonCalendar, neg: number | null, pos: number | null, level: number, k: number): string {
  const head = `${dayLabel(n.day)}, ${nightWhat(n, cal)}`
  if (!n.counts.total) return `${head}: no comments.`
  const own = `${fmtPct(negRate(n.counts), 1)} negative and ${fmtPct(posRate(n.counts), 1)} positive of ${fmtInt(n.counts.total)} comments`
  if (neg === null || pos === null) return `${head}: ${own}; too close to the edge of the season for the ${fmtInt(k)}-night line.`
  return `${head}: ${own}; the ${fmtInt(k)} nights around it ${fmtPct(neg, 1)} negative and ${fmtPct(pos, 1)} positive. ${againstLevel(neg, level)}`
}

// --- Game nights against nights with no game ---------------------------------------

export type SplitPhase = 'regular' | 'playoffs' | 'finals'

export interface GameNightRow {
  key: SplitPhase
  label: string
  /** Nights with a row in games. */
  on: Counts
  onNights: number
  /** Nights without one; the All-Star Game is one of them. */
  off: Counts
  offNights: number
}

/** The three phases cut disjoint on the calendar, each split by whether a game was played. */
export function gameNightSplit(nights: readonly Night[], cal: SeasonCalendar): GameNightRow[] {
  const spans: { key: SplitPhase; label: string; from: string; to: string }[] = [
    { key: 'regular', label: 'Regular season', from: cal.opening_night, to: addDays(cal.play_in_start, -1) },
    { key: 'playoffs', label: 'Playoffs', from: cal.play_in_start, to: addDays(cal.finals_start, -1) },
    { key: 'finals', label: 'Finals', from: cal.finals_start, to: cal.finals_end },
  ]
  return spans.map(({ key, label, from, to }) => {
    const span = nights.filter((n) => n.day >= from && n.day <= to)
    const on = span.filter((n) => n.games > 0)
    const off = span.filter((n) => n.games === 0)
    return { key, label, on: sumCounts(on.map((n) => n.counts)), onNights: on.length, off: sumCounts(off.map((n) => n.counts)), offNights: off.length }
  })
}

// --- The lede and the annotations ----------------------------------------------------

export interface Lede {
  opening: string
  /** The regular-season level, set bold on the page: "35.2% negative". */
  level: string
  closing: string
}

export const ledeText = (l: Lede): string => `${l.opening}${l.level}${l.closing}`

/** The page's lede: the stretch above the regular season, and when the harshest night came. */
export function nightsLede(stretch: Stretch | null, level: number, harshest: Night | null, cal: SeasonCalendar): Lede {
  const held = stretch !== null && (stretch.to === null || stretch.to > cal.finals_end)
  const opening = stretch
    ? `From the first play-in night on ${weekLabel(stretch.from)} ${held ? 'to the last night of the Finals' : `until ${weekLabel(stretch.to!)}`}, comments about players never cooled to their regular-season level of `
    : 'Through the playoffs, comments about players held near their regular-season level of '
  const harsh = harshest === null ? '' : harshest.day.slice(5, 7) === '02' ? ' The single most negative night of the season still came in February.' : ` The single most negative night of the season was ${weekLabel(harshest.day)}.`
  return { opening, level: `${fmtPct(level, 1)} negative`, closing: `.${harsh}` }
}

export interface NightNote {
  day: string
  pole: Pole
  /** "Feb 27 · Dort ejected". */
  head: string
  /** The head where the chart is narrow. */
  shortHead: string
  text: string
  shortText: string
  /** The ringed rate on the day. */
  rate: number
  /** A second, smaller ring on the day after, when the note names it. */
  also: { day: string; rate: number } | null
}

/** The curated note on the harshest stretch, its figures from the data; the build fails when the data no longer backs it. */
export function harshestNote(nights: readonly Night[], copy: NightNoteCopy, harshest: Night | null): NightNote {
  const i = nights.findIndex((n) => n.day === copy.day)
  if (i < 0) throw new Error(`season copy: no night on ${copy.day}`)
  const night = nights[i]!
  const next = nights[i + 1]
  if (!next) throw new Error(`season copy: ${copy.day} has no day after to name`)
  if (!harshest || (harshest.day !== night.day && harshest.day !== next.day))
    throw new Error(`season copy: ${copy.day} is annotated as the harshest night or its cause, but the harshest night at the floor is ${harshest?.day ?? 'none'}`)
  const own = fmtPct(negRate(night.counts), 1)
  const after = fmtPct(negRate(next.counts), 1)
  return {
    day: night.day,
    pole: 'neg',
    head: `${weekLabel(night.day)} · ${copy.title}`,
    shortHead: `${weekLabel(night.day)} · ${copy.title}`,
    text: `${copy.text} ${own} negative that night, ${after} the day after.`,
    shortText: `${copy.text} ${own}, then ${after} the day after.`,
    rate: negRate(night.counts),
    also: { day: next.day, rate: negRate(next.counts) },
  }
}

/** Every game's counts about players in its threads, summed over the players. */
export function gameComments(rows: readonly GameSentimentRow[]): Map<string, Counts> {
  const out = new Map<string, Counts>()
  for (const r of rows) out.set(r.game_id, sumCounts([out.get(r.game_id) ?? { neg: 0, neu: 0, pos: 0, total: 0 }, countsOf(r)]))
  return out
}

/** "Spurs win at OKC": the night's loudest game as its title; null when no game was played. */
export function nightGameTitle(day: string, games: readonly GamesRow[], byGame: ReadonlyMap<string, Counts>, abbr: ReadonlyMap<string, string>): string | null {
  const played = games.filter((g) => g.game_date === day).toSorted((a, b) => (byGame.get(b.game_id)?.total ?? 0) - (byGame.get(a.game_id)?.total ?? 0))
  const g = played[0]
  if (!g) return null
  const a = (t: string) => abbr.get(t) ?? t
  return g.winner === g.away_team ? `${nickname(g.winner)} win at ${a(g.home_team)}` : `${nickname(g.winner)} win over ${a(g.away_team)}`
}

/** The warmest night's note, every word computed. */
export function warmestNote(night: Night, title: string | null): NightNote {
  const date = weekLabel(night.day)
  const pos = fmtPct(posRate(night.counts), 1)
  return {
    day: night.day,
    pole: 'pos',
    head: title ? `${date} · ${title}` : date,
    shortHead: date,
    text: `The warmest night: ${pos} positive, ${fmtPct(negRate(night.counts), 1)} negative.`,
    shortText: `Warmest: ${pos} positive.`,
    rate: posRate(night.counts),
    also: null,
  }
}
