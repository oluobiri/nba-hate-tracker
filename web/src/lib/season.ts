// The season page's figures, computed from the tables at build. The nights
// come from corpus_daily (the attributed population on Eastern game nights)
// and games; the game-night split cuts the phases disjoint on the calendar.
// Every rate is a ratio of summed counts; the thresholds here are page
// choices, and the rules arrive as arguments from the manifest.
import type { CorpusDailyRow, GameSentimentRow, GamesRow, PlayerGamesRow, PlayerRoomRow, PlayerTemporalRow, PlayersRow, PostsRow, RecapEntry, RoomTemporalRow, TeamsRow } from '../data/types.gen'
import { nickname } from './fans'
import { fmtInt, fmtPct, fmtSigned } from './format'
import { type GameLineParts, gameLine } from './games'
import { countsOf, negRate, netSentiment, posRate, sumCounts } from './metrics'
import { fmtNet } from './net'
import type { NightNoteCopy } from './season-copy'
import type { Counts } from './types'
import { type Calendar, weekLabel, weekOf, weekSpine } from './weeks'

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

// --- The rooms ------------------------------------------------------------------------
// A room is the kind of post a comment was written under. room_temporal is
// weekly; a week takes the phase most of its nights fall in, so the play-in
// week is a playoff week. The split between the phases is a shift-share on
// symmetric midpoint weights: hold each room's tone and move the crowd, then
// hold the crowd and move the tone; the two add up to the rise exactly.

/** Comments a player's gap between two rooms needs, in points, to be named an exception. */
export const EXCEPTION_GAP = 0.05

export const ROOM_LABELS: Record<string, string> = {
  game_thread: 'Game threads',
  post_game_thread: 'Post-game threads',
  daily: 'Daily chat thread',
  general: 'Front page',
  highlight: 'Highlights',
  news: 'News',
  lowlight: 'Lowlights',
  injury: 'Injury posts',
  discussion: 'Discussion posts',
}

export interface Band {
  key: string
  label: string
  /** The rooms the band folds. */
  members: readonly string[]
}

/** The volume panel's seven bands in stacking order; the last folds the small rooms. */
export const BANDS: readonly Band[] = [
  { key: 'game_thread', label: 'Game threads', members: ['game_thread'] },
  { key: 'post_game_thread', label: 'Post-game threads', members: ['post_game_thread'] },
  { key: 'daily', label: 'Daily chat thread', members: ['daily'] },
  { key: 'general', label: 'Front page', members: ['general'] },
  { key: 'highlight', label: 'Highlights', members: ['highlight'] },
  { key: 'news', label: 'News', members: ['news'] },
  { key: 'rest', label: 'Everything else', members: ['lowlight', 'injury', 'discussion'] },
]

/** The rooms large enough to speak for in the lede. */
export const BIG_ROOMS: readonly string[] = ['game_thread', 'general', 'highlight', 'post_game_thread', 'news']

const ZERO: Counts = { neg: 0, neu: 0, pos: 0, total: 0 }
const addInto = (into: Map<string, Counts>, key: string, c: Counts): void => void into.set(key, sumCounts([into.get(key) ?? ZERO, c]))
const weekDay = (key: string): string => key.slice(0, 10)

/** The phase most of a week's nights fall in; a tie goes to the earlier phase. */
export function weekPhase(monday: string, cal: SeasonCalendar): NightPhase {
  const seen: NightPhase[] = []
  const tally = new Map<NightPhase, number>()
  for (let i = 0; i < 7; i++) {
    const p = nightPhase(addDays(weekDay(monday), i), cal)
    if (!tally.has(p)) seen.push(p)
    tally.set(p, (tally.get(p) ?? 0) + 1)
  }
  return seen.reduce((best, p) => (tally.get(p)! > tally.get(best)! ? p : best))
}

export interface RoomSplitRow {
  key: string
  label: string
  big: boolean
  reg: Counts
  po: Counts
  whole: Counts
  shareReg: number
  sharePo: number
  shareWhole: number
  /** The negative share in each phase; a room missing from one phase takes the other's. */
  rateReg: number
  ratePo: number
  /** Points of the rise from the crowd moving into or out of this room. */
  mix: number
  /** Points of the rise from this room's own tone moving. */
  harsh: number
}

export interface RoomSplit {
  reg: Counts
  po: Counts
  /** The playoffs' negative share minus the regular season's. */
  lift: number
  mix: number
  harsh: number
  rooms: RoomSplitRow[]
}

/** Every room pooled over the regular season and the playoffs, and the rise split two ways. */
export function roomSplit(rows: readonly RoomTemporalRow[], cal: SeasonCalendar): RoomSplit {
  const phases = new Map<string, NightPhase>()
  const pooled = { regular: new Map<string, Counts>(), playoffs: new Map<string, Counts>(), whole: new Map<string, Counts>() }
  for (const r of rows) {
    let phase = phases.get(r.week)
    if (!phase) phases.set(r.week, (phase = weekPhase(r.week, cal)))
    const c = countsOf(r)
    addInto(pooled.whole, r.post_type, c)
    if (phase === 'regular') addInto(pooled.regular, r.post_type, c)
    if (phase === 'playoffs') addInto(pooled.playoffs, r.post_type, c)
  }
  const reg = sumCounts([...pooled.regular.values()])
  const po = sumCounts([...pooled.playoffs.values()])
  const whole = sumCounts([...pooled.whole.values()])
  const lift = negRate(po) - negRate(reg)
  const rooms = [...pooled.whole.keys()].toSorted().map((key) => {
    const c0 = pooled.regular.get(key) ?? ZERO
    const c1 = pooled.playoffs.get(key) ?? ZERO
    const s0 = reg.total ? c0.total / reg.total : 0
    const s1 = po.total ? c1.total / po.total : 0
    const r0 = c0.total ? negRate(c0) : negRate(c1)
    const r1 = c1.total ? negRate(c1) : r0
    const w = pooled.whole.get(key)!
    return {
      key,
      label: ROOM_LABELS[key] ?? key,
      big: BIG_ROOMS.includes(key),
      reg: c0,
      po: c1,
      whole: w,
      shareReg: s0,
      sharePo: s1,
      shareWhole: whole.total ? w.total / whole.total : 0,
      rateReg: r0,
      ratePo: r1,
      mix: ((s1 - s0) * (r0 + r1)) / 2,
      harsh: ((r1 - r0) * (s0 + s1)) / 2,
    }
  })
  const mix = rooms.reduce((a, r) => a + r.mix, 0)
  const harsh = rooms.reduce((a, r) => a + r.harsh, 0)
  if (Math.abs(lift - (mix + harsh)) > 1e-9) throw new Error(`room split: the mix (${mix}) and the tone (${harsh}) do not add up to the rise (${lift})`)
  return { reg, po, lift, mix, harsh, rooms }
}

export interface BandSeries {
  key: string
  label: string
  /** Comments per week on the spine. */
  n: number[]
}

export interface PhaseRun {
  phase: NightPhase
  /** Spine indices, inclusive. */
  from: number
  to: number
}

export interface Weekly {
  /** Week keys, as the rows carry them. */
  spine: string[]
  phases: NightPhase[]
  runs: PhaseRun[]
  totals: number[]
  bands: BandSeries[]
}

/** The seven bands week by week on the season's spine, with each week's phase and total. */
export function bandWeekly(rows: readonly RoomTemporalRow[], cal: SeasonCalendar): Weekly {
  const spine = weekSpine(rows.map((r) => r.week))
  const cell = new Map<string, number>()
  for (const r of rows) cell.set(`${r.post_type} ${r.week}`, (cell.get(`${r.post_type} ${r.week}`) ?? 0) + r.comment_count)
  const bands = BANDS.map((b) => ({ key: b.key, label: b.label, n: spine.map((w) => b.members.reduce((a, m) => a + (cell.get(`${m} ${w}`) ?? 0), 0)) }))
  const totals = spine.map((_, i) => bands.reduce((a, b) => a + b.n[i]!, 0))
  const phases = spine.map((w) => weekPhase(w, cal))
  const runs: PhaseRun[] = []
  phases.forEach((p, i) => {
    const last = runs.at(-1)
    if (last && last.phase === p) last.to = i
    else runs.push({ phase: p, from: i, to: i })
  })
  return { spine, phases, runs, totals, bands }
}

export interface RoomRow {
  key: string
  label: string
  reg: Counts
  po: Counts
  shareReg: number
  sharePo: number
}

/** One row per band with its counts in each phase, and the largest share for the bar scale. */
export function roomRows(split: RoomSplit): { rows: RoomRow[]; maxShare: number } {
  const byKey = new Map(split.rooms.map((r) => [r.key, r]))
  const rows = BANDS.map((b) => {
    const members = b.members.map((m) => byKey.get(m)).filter((r): r is RoomSplitRow => r !== undefined)
    const reg = sumCounts(members.map((r) => r.reg))
    const po = sumCounts(members.map((r) => r.po))
    return { key: b.key, label: b.label, reg, po, shareReg: split.reg.total ? reg.total / split.reg.total : 0, sharePo: split.po.total ? po.total / split.po.total : 0 }
  })
  const maxShare = Math.max(0, ...rows.flatMap((r) => [r.shareReg, r.sharePo]))
  return { rows, maxShare }
}

/** Every room over the whole season, the biggest first. */
export const roomTable = (split: RoomSplit): RoomSplitRow[] => split.rooms.toSorted((a, b) => b.whole.total - a.whole.total)

/** A share of the comments with the precision a small room needs: "46%", "1.0%", "0.13%". */
export function fmtShare(s: number): string {
  return s < 0.005 ? fmtPct(s, 2) : s < 0.015 ? fmtPct(s, 1) : fmtPct(s, 0)
}

/** "a third", "half": the nearest common fraction. */
const FRACTIONS: readonly [number, string][] = [
  [0.2, 'a fifth'],
  [0.25, 'a quarter'],
  [1 / 3, 'a third'],
  [0.4, 'two fifths'],
  [0.5, 'half'],
  [0.6, 'three fifths'],
  [2 / 3, 'two thirds'],
  [0.75, 'three quarters'],
]
export const fraction = (v: number): string => FRACTIONS.reduce((a, b) => (Math.abs(b[0] - v) < Math.abs(a[0] - v) ? b : a))[1]

/** "+1.9", "−3.9": points, one decimal, a real minus. */
export const fmtPts = (v: number, dp = 1): string => fmtSigned(v, dp).replace('-', '−')
/** "35.2": a share in points without the sign. */
export const fmtPoints = (v: number, dp = 1): string => (100 * v).toFixed(dp)

/** How the big rooms moved, in words: every one harsher, all but one, or most. */
export function bigRoomsMoved(split: RoomSplit): string {
  const kinder = split.rooms.filter((r) => r.big && r.harsh < 0)
  if (kinder.length === 0) return 'Every big room got more negative.'
  if (kinder.length === 1) return `Every big room got more negative except ${kinder[0]!.label.toLowerCase()}.`
  return 'Most big rooms got more negative.'
}

/** The rooms' lede: the rise, and how much of it the crowd moving explains. */
export function roomsLede(split: RoomSplit): string {
  const from = `In the playoffs, comments about players went from ${fmtPct(negRate(split.reg), 1)} to ${fmtPct(negRate(split.po), 1)} negative.`
  if (split.lift <= 0 || split.mix <= 0) return `${from} The crowd's move between rooms does not explain it.`
  const kinder = split.rooms.filter((r) => r.big && r.harsh < 0).length
  const rooms = kinder === 0 ? 'every big room' : kinder === 1 ? 'nearly every big room' : 'most big rooms'
  return `${from} About ${fraction(split.mix / split.lift)} of that is game threads taking over the conversation; the rest is ${rooms} getting more negative.`
}

export interface Tile {
  key: 'rise' | 'mix' | 'harsh'
  figure: string
  /** After the figure, small: "of the 5.8 pts". */
  unit: string | null
  title: string
  sub: string
}

/** The three tiles: the rise, and the two things that made it. */
export function roomTiles(split: RoomSplit): Tile[] {
  const gt = split.rooms.find((r) => r.key === 'game_thread')
  const lift = fmtPoints(split.lift)
  return [
    {
      key: 'rise',
      figure: `${fmtPoints(negRate(split.reg))} → ${fmtPoints(negRate(split.po))}`,
      unit: null,
      title: '% negative, regular season → playoffs',
      sub: `${fmtInt(split.reg.total)} and ${fmtInt(split.po.total)} comments about players under a post whose room is known.`,
    },
    {
      key: 'mix',
      figure: fmtPts(split.mix),
      unit: `of the ${lift} pts`,
      title: 'Because the crowd moved',
      sub: gt ? `Into harsher rooms: game threads went from ${fmtPct(gt.shareReg, 0)} of the comments to ${fmtPct(gt.sharePo, 0)}. Each room held at its regular-season tone.` : 'Each room held at its regular-season tone.',
    },
    {
      key: 'harsh',
      figure: fmtPts(split.harsh),
      unit: `of the ${lift} pts`,
      title: 'Because each room got harsher',
      sub: `${bigRoomsMoved(split)} The crowd held at its regular-season spread.`,
    },
  ]
}

export interface RoomGap {
  name: string
  slug: string
  gameThread: Counts
  frontPage: Counts
  /** The game thread's negative share minus the front page's. */
  gap: number
}

export interface PlayerAngle {
  qualified: number
  /** Qualified players with both rooms at the room floor. */
  compared: number
  harsher: number
  median: number
  /** Players kinder in the game thread by at least the exception gap, the biggest gap first. */
  exceptions: RoomGap[]
}

/** The room gap at player grain: the game thread against the front page, for the qualified players with both rooms at the floor. */
export function playerAngle(rows: readonly PlayerRoomRow[], qualified: ReadonlySet<string>, slugOf: ReadonlyMap<string, string>, roomFloor: number): PlayerAngle {
  const cells = new Map<string, { gt?: Counts; fp?: Counts }>()
  for (const r of rows) {
    if (r.comment_count < roomFloor || !qualified.has(r.attributed_player)) continue
    if (r.post_type !== 'game_thread' && r.post_type !== 'general') continue
    const cell = cells.get(r.attributed_player) ?? {}
    cell[r.post_type === 'game_thread' ? 'gt' : 'fp'] = countsOf(r)
    cells.set(r.attributed_player, cell)
  }
  const gaps: RoomGap[] = [...cells.entries()]
    .filter(([, c]) => c.gt && c.fp)
    .map(([name, c]) => ({ name, slug: slugOf.get(name) ?? name, gameThread: c.gt!, frontPage: c.fp!, gap: negRate(c.gt!) - negRate(c.fp!) }))
    .toSorted((a, b) => b.gap - a.gap || a.name.localeCompare(b.name))
  const sorted = gaps.map((g) => g.gap).toSorted((a, b) => a - b)
  const mid = sorted.length >> 1
  const median = sorted.length === 0 ? 0 : sorted.length % 2 ? sorted[mid]! : (sorted[mid - 1]! + sorted[mid]!) / 2
  return {
    qualified: qualified.size,
    compared: gaps.length,
    harsher: gaps.filter((g) => g.gap > 0).length,
    median,
    exceptions: gaps.filter((g) => g.gap <= -EXCEPTION_GAP).toReversed(),
  }
}

/** The sentence under the rows, in two parts: the finding, then the named exceptions (linked on the page). */
export function playerAngleText(angle: PlayerAngle): { lead: string; exceptions: RoomGap[]; tail: string | null } {
  if (angle.compared === 0) return { lead: 'No player at the official minimum has both rooms at the floor.', exceptions: [], tail: null }
  const share = angle.harsher / angle.compared
  const who = share >= 0.8 ? 'Nearly every player is' : share >= 0.5 ? 'Most players are' : 'Fewer than half the players are'
  const lead = `${who} talked about more harshly in the game thread than on the front page: ${fmtInt(angle.harsher)} of the ${fmtInt(angle.compared)} at the official minimum, by a median of ${fmtInt(Math.round(Math.abs(angle.median) * 100))} points.`
  if (angle.exceptions.length === 0) return { lead, exceptions: [], tail: null }
  return { lead, exceptions: angle.exceptions, tail: 'The exceptions are players whose season was a story more than a schedule: ' }
}

// --- Season arcs ----------------------------------------------------------------------
// Each qualified player's first eight regular-season weeks against the eight
// weeks ending at his last game played, so a Finals run, an April exit and a
// season cut short are measured by one rule. Net sentiment is the metric; the
// shape at three points (early, the late regular season, the playoffs) gives
// the timing phrase.

/** Weeks in each window. */
export const ARC_WEEKS = 8
/** Comments a window needs. */
export const ARC_MIN_N = 1000
/** Players shown each way. */
export const ARCS = 6
/** A playoff move this large, against the arc, is a slip or a recovery. */
const ARC_COUNTER_MOVE = 0.04

const addWeeks = (key: string, n: number): string => `${addDays(weekDay(key), 7 * n)}T00:00:00`
const monthName = (key: string): string => new Date(Date.parse(weekDay(key))).toLocaleDateString('en-US', { month: 'long', timeZone: 'UTC' })

export interface ArcPoint {
  counts: Counts
  net: number
}

export interface Arc {
  name: string
  slug: string
  /** His roster team's abbreviation, or empty. */
  team: string
  /** How his season ended: "Finals run", "Second round", "Cut short". */
  ended: string
  /** "YYYY-MM-DD", his last game. */
  to: string
  early: ArcPoint
  late: ArcPoint
  /** The last eight regular-season weeks; null under the floor. */
  lateRs: ArcPoint | null
  /** The playoff weeks of the late window; null when it has none, or under the floor. */
  po: ArcPoint | null
  /** Late net minus early net. */
  delta: number
  timing: string
}

const pooledPoint = (cells: readonly (Counts | undefined)[], floor: number): ArcPoint | null => {
  const counts = sumCounts(cells.filter((c): c is Counts => c !== undefined))
  return counts.total >= floor ? { counts, net: netSentiment(counts) } : null
}

const ROUND_ENDINGS: Record<number, string> = { 1: 'First round', 2: 'Second round', 3: 'Conference finals', 4: 'Finals run' }

/** How a season ended, from his last game's date and row. */
export function endedAs(last: string, lastGame: GamesRow | null, cal: SeasonCalendar): string {
  if (last < addDays(cal.play_in_start, -7)) return 'Cut short'
  if (last < cal.play_in_start) return 'Season end'
  if (last < cal.playoffs_start) return 'Play-in'
  const round = lastGame?.playoff_round === null || lastGame?.playoff_round === undefined ? null : Math.trunc(lastGame.playoff_round)
  return (round !== null && ROUND_ENDINGS[round]) || 'Playoffs'
}

/** When the arc moved, from its three points; `month` names the regular season's turn when one is needed. */
export function timing(early: ArcPoint, late: ArcPoint, lateRs: ArcPoint | null, po: ArcPoint | null, month: () => string): string {
  const total = late.net - early.net
  const up = total > 0
  if (po === null) return `${up ? 'Rose' : 'Fell'} through the regular season`
  if (lateRs === null) return 'Turned in the playoffs'
  const regMove = lateRs.net - early.net
  const poMove = po.net - lateRs.net
  const sameReg = regMove > 0 === up
  const samePo = poMove > 0 === up
  if (Math.abs(poMove) >= (2 / 3) * Math.abs(total) && samePo && Math.abs(regMove) < 0.5 * Math.abs(total)) return 'Turned in the playoffs'
  if (Math.abs(regMove) >= (2 / 3) * Math.abs(total) && sameReg) {
    if (!samePo && Math.abs(poMove) >= ARC_COUNTER_MOVE) return `Turned in ${month()}, ${up ? 'slipped back in the playoffs' : 'recovered in the playoffs'}`
    return `Turned in ${month()}, held through the playoffs`
  }
  if (sameReg && samePo) return up ? 'Rose all season' : 'Fell all season'
  return samePo ? 'Turned in the playoffs' : `Turned in ${month()}`
}

export interface ArcInputs {
  temporal: readonly PlayerTemporalRow[]
  playerGames: readonly PlayerGamesRow[]
  games: readonly GamesRow[]
  players: readonly PlayersRow[]
  teams: readonly TeamsRow[]
  qualified: ReadonlySet<string>
}

/** Every qualified player with both windows at the floor and no overlap between them, unsorted. */
export function arcField({ temporal, playerGames, games, players, teams, qualified }: ArcInputs, cal: SeasonCalendar): Arc[] {
  const abbr = new Map(teams.map((t) => [t.team, t.abbreviation]))
  const dim = new Map(players.map((p) => [p.attributed_player, p]))
  const gameRows = new Map(games.map((g) => [g.game_id, g]))
  const byWeek = new Map<string, Map<string, Counts>>()
  for (const r of temporal) {
    const weeks = byWeek.get(r.attributed_player) ?? new Map<string, Counts>()
    weeks.set(r.week, countsOf(r))
    byWeek.set(r.attributed_player, weeks)
  }
  // His last game, and the row for it.
  const last = new Map<string, { day: string; game: GamesRow }>()
  for (const pg of playerGames) {
    const g = gameRows.get(pg.game_id)
    if (!g) continue
    const cur = last.get(pg.attributed_player)
    if (!cur || g.game_date > cur.day) last.set(pg.attributed_player, { day: g.game_date, game: g })
  }
  const firstWeek = weekOf(cal.opening_night)
  const early = Array.from({ length: ARC_WEEKS }, (_, i) => addWeeks(firstWeek, i))
  const lastRsWeek = weekOf(addDays(cal.play_in_start, -1))
  const lateRsWeeks = Array.from({ length: ARC_WEEKS }, (_, i) => addWeeks(lastRsWeek, -i))
  const poFirstWeek = weekOf(cal.play_in_start)
  const earlyEnd = Date.parse(weekDay(early.at(-1)!))

  const out: Arc[] = []
  for (const name of [...qualified].toSorted()) {
    const end = last.get(name)
    const weeks = byWeek.get(name)
    if (!end || !weeks) continue
    const lateWeeks = Array.from({ length: ARC_WEEKS }, (_, i) => addWeeks(weekOf(end.day), -i))
    if (Date.parse(weekDay(lateWeeks.at(-1)!)) <= earlyEnd) continue
    const window = (keys: readonly string[]) => pooledPoint(keys.map((w) => weeks.get(w)), ARC_MIN_N)
    const e = window(early)
    const l = window(lateWeeks)
    if (!e || !l) continue
    const lateRs = window(lateRsWeeks)
    const poWeeks = lateWeeks.filter((w) => w >= poFirstWeek)
    const po = poWeeks.length ? window(poWeeks) : null
    const up = l.net > e.net
    // The month at the middle of the regular season's biggest four-week move in the arc's direction.
    const month = (): string => {
      let best: number | null = null
      let bestWeek: string | null = null
      for (let w = addWeeks(early.at(-1)!, 1); Date.parse(weekDay(addWeeks(w, 3))) <= Date.parse(weekDay(lastRsWeek)); w = addWeeks(w, 1)) {
        const block = window(Array.from({ length: 4 }, (_, i) => addWeeks(w, i)))
        if (!block) continue
        const move = (block.net - e.net) * (up ? 1 : -1)
        if (best === null || move > best) {
          best = move
          bestWeek = w
        }
      }
      return monthName(addWeeks(bestWeek ?? early.at(-1)!, 2))
    }
    const p = dim.get(name)
    out.push({
      name,
      slug: p?.slug ?? name,
      team: (p?.roster_team && abbr.get(p.roster_team)) || '',
      ended: endedAs(end.day, end.game, cal),
      to: end.day,
      early: e,
      late: l,
      lateRs,
      po,
      delta: l.net - e.net,
      timing: timing(e, l, lateRs, po, month),
    })
  }
  return out
}

export interface ArcLists {
  rose: Arc[]
  fell: Arc[]
  flat: Arc[]
  field: number
}

/** The biggest climbs, the biggest falls, the stillest arcs. */
export function arcLists(field: readonly Arc[]): ArcLists {
  const byDelta = field.toSorted((a, b) => b.delta - a.delta || a.name.localeCompare(b.name))
  return {
    rose: byDelta.slice(0, ARCS),
    fell: byDelta.slice(-ARCS).toReversed(),
    flat: field.toSorted((a, b) => Math.abs(a.delta) - Math.abs(b.delta) || a.name.localeCompare(b.name)).slice(0, ARCS),
    field: field.length,
  }
}

const netPoints = (v: number): number => Math.abs(Math.round(100 * v))
const netWord = (v: number): string => (v < 0 ? 'negative' : 'positive')

/** How his last eight weeks ended, as a clause. */
function endedClause(a: Arc): string {
  switch (a.ended) {
    case 'Finals run':
      return 'were a Finals run'
    case 'Cut short':
      return 'ended early'
    case 'Season end':
      return 'ended with the regular season'
    default:
      return `ended in the ${a.ended.toLowerCase()}`
  }
}

/** The arcs' lede: the biggest climb and the biggest fall. */
export function arcsLede(lists: ArcLists): string {
  const climb = lists.rose[0]
  const fall = lists.fell[0]
  if (!climb || !fall || lists.field < 2) return `Too few players clear both windows to measure an arc.`
  return (
    `${climb.name} won r/NBA over more than anyone: his net sentiment went from ${fmtInt(netPoints(climb.early.net))} points ${netWord(climb.early.net)} in his first ${fmtInt(ARC_WEEKS)} weeks to ${fmtInt(netPoints(climb.late.net))} ${netWord(climb.late.net)} in his last ${fmtInt(ARC_WEEKS)}, among the ${fmtInt(lists.field)} players measured. ` +
    `${fall.name} fell the furthest, ${fmtInt(netPoints(fall.delta))} points, and his last ${fmtInt(ARC_WEEKS)} weeks ${endedClause(fall)}.`
  )
}

/** The dumbbell axis: the shown arcs' range rounded out to the nearest ten points, with a tick every ten. */
export function arcDomain(arcs: readonly Arc[]): { lo: number; hi: number; ticks: number[] } {
  const values = arcs.flatMap((a) => [a.early.net, a.late.net])
  const lo = values.length ? Math.floor(Math.min(...values) * 10) / 10 : -0.5
  const hi = values.length ? Math.ceil(Math.max(...values) * 10) / 10 : 0.5
  const ticks: number[] = []
  for (let t = lo; t <= hi + 1e-9; t += 0.1) ticks.push(Math.round(t * 10) / 10)
  return { lo, hi, ticks }
}

/** The row's spoken sentence. */
export const arcText = (a: Arc): string => `${a.name}: net sentiment ${fmtNet(a.early.net)} in his first ${fmtInt(ARC_WEEKS)} weeks, ${fmtNet(a.late.net)} in his last ${fmtInt(ARC_WEEKS)}; ${a.timing.toLowerCase()}.`

// --- The loudest threads ---------------------------------------------------------------
// A game's threads are its game thread and its post-game thread together.
// The figure counts the comments in them about a tracked player; the Reddit
// count beside it is every comment the two posts carry. The play-in sits
// with the playoffs, as the rooms count the week it falls in.

/** Threads in each list. */
export const THREADS = 5
/** A second name in a thread's sentence needs this many comments in the thread… */
export const THREAD_SECOND_MIN_N = 500
/** …and this much more negative than the thread. */
export const THREAD_SECOND_GAP = 0.2

const THREAD_TYPES: ReadonlySet<string> = new Set(['game_thread', 'post_game_thread'])

export interface ThreadPlayer {
  name: string
  slug: string
  counts: Counts
}

export interface ThreadRecap {
  key: string
  name: string
}

export interface Thread {
  gameId: string
  /** "YYYY-MM-DD". */
  date: string
  /** "West Finals · Game 1", "Opening night", "Regular season". */
  stage: string
  line: GameLineParts
  /** Every comment about a tracked player in the game's threads. */
  counts: Counts
  /** Every comment Reddit counts in the same threads; null when the posts are not bridged. */
  reddit: number | null
  top: ThreadPlayer
  /** A player at the second-name floor who ran the gap or more harsher than the thread. */
  second: ThreadPlayer | null
  recaps: ThreadRecap[]
}

/** game_id → every curated recap of that game, in registry order. */
export function recapsByGame(recaps: Record<string, RecapEntry>): Map<string, ThreadRecap[]> {
  const out = new Map<string, ThreadRecap[]>()
  for (const [key, e] of Object.entries(recaps)) out.set(e.game_id, [...(out.get(e.game_id) ?? []), { key, name: e.attributed_player }])
  return out
}

/** What the game was: its round and game in the playoffs, else the calendar's name for the night, else the phase. */
export function stageOf(game: GamesRow, line: GameLineParts, cal: SeasonCalendar): string {
  if (game.season_type === 'playoffs') return [line.round, line.game].filter(Boolean).join(' · ')
  if (game.nba_cup_final) return 'NBA Cup final'
  const event = cal.events.get(game.game_date)
  if (event === 'Opening night' || event === 'Christmas') return event
  if (game.season_type === 'play_in') return 'Play-in'
  return 'Regular season'
}

export interface ThreadInputs {
  sentiment: readonly GameSentimentRow[]
  posts: readonly PostsRow[]
  games: readonly GamesRow[]
  players: readonly PlayersRow[]
  teams: readonly TeamsRow[]
  recaps: Record<string, RecapEntry>
}

/** The games with the most comments about players in their threads, on one side of the play-in's start. */
export function loudestThreads({ sentiment, posts, games, players, teams, recaps }: ThreadInputs, cal: SeasonCalendar, playoffs: boolean): Thread[] {
  const abbr = new Map(teams.map((t) => [t.team, t.abbreviation]))
  const conferenceOf = new Map(teams.map((t) => [t.team, t.conference]))
  const slugOf = new Map(players.map((p) => [p.attributed_player, p.slug]))
  const gameRows = new Map(games.map((g) => [g.game_id, g]))
  const byGame = gameComments(sentiment)
  const reddit = new Map<string, number>()
  for (const p of posts) if (p.game_id && THREAD_TYPES.has(p.post_type)) reddit.set(p.game_id, (reddit.get(p.game_id) ?? 0) + p.num_comments)
  const inGame = new Map<string, GameSentimentRow[]>()
  for (const r of sentiment) inGame.set(r.game_id, [...(inGame.get(r.game_id) ?? []), r])
  const recapsOf = recapsByGame(recaps)
  const who = (r: GameSentimentRow): ThreadPlayer => ({ name: r.attributed_player, slug: slugOf.get(r.attributed_player) ?? r.attributed_player, counts: countsOf(r) })

  return [...byGame.entries()]
    .flatMap(([gameId, counts]) => {
      const g = gameRows.get(gameId)
      return g && g.game_date >= cal.play_in_start === playoffs ? [{ g, counts }] : []
    })
    .toSorted((a, b) => b.counts.total - a.counts.total || a.g.game_date.localeCompare(b.g.game_date) || a.g.game_id.localeCompare(b.g.game_id))
    .slice(0, THREADS)
    .map(({ g, counts }) => {
      const rows = (inGame.get(g.game_id) ?? []).toSorted((a, b) => b.comment_count - a.comment_count || a.attributed_player.localeCompare(b.attributed_player))
      const top = rows[0]!
      const threadRate = negRate(counts)
      const second = rows.find((r) => r !== top && r.comment_count >= THREAD_SECOND_MIN_N && negRate(countsOf(r)) - threadRate >= THREAD_SECOND_GAP)
      const line = gameLine(g, abbr, conferenceOf)
      return {
        gameId: g.game_id,
        date: g.game_date,
        stage: stageOf(g, line, cal),
        line,
        counts,
        reddit: reddit.get(g.game_id) ?? null,
        top: who(top),
        second: second ? who(second) : null,
        recaps: recapsOf.get(g.game_id) ?? [],
      }
    })
}

/** "19.6% negative on 6,783": a player's figure in the thread. */
export const threadFigure = (p: ThreadPlayer): string => `${fmtPct(negRate(p.counts), 1)} negative on ${fmtInt(p.counts.total)}`

/** The thread's spoken line: the split, then who it was about. */
export function threadText(t: Thread): string {
  const about = `${fmtInt(t.counts.total)} comments about players${t.reddit === null ? '' : ` of ${fmtInt(t.reddit)} in the thread`}`
  const split = `${fmtPct(negRate(t.counts), 1)} negative, ${fmtPct(posRate(t.counts), 1)} positive`
  const second = t.second ? ` ${t.second.name} ${threadFigure(t.second)}.` : ''
  const score = `${t.line.away.abbr} ${t.line.away.score} @ ${t.line.home.abbr} ${t.line.home.score}`
  return `${t.stage} · ${score} · ${t.line.date}: ${about}, ${split}. Mostly about ${t.top.name}, ${threadFigure(t.top)}.${second}`
}
