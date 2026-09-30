// The recaps index and each recap's static shell. The registry is joined
// to the dimensions once per build and shared by the index, the route and
// its card; the hook is one sentence computed from the per-period counts;
// every figure goes through format.ts. Nothing here opens a recap file.
import type { GamesRow, Manifest, PeriodCounts, PlayerGamesRow, PlayersRow, RecapEntry, Tables } from '../data/types.gen'
import { fmtInt, fmtPct, ordinal } from './format'
import { gameLine, type GameLineParts } from './games'
import { countsOf, negRate, sumCounts } from './metrics'
import type { Counts } from './types'

export const recapHref = (key: string): string => `/recaps/${key}/`

/** game_id → the recap's href for one player: the games table's chip. */
export function recapHrefs(recaps: Record<string, RecapEntry>, player: string): Map<string, string> {
  return new Map(
    Object.entries(recaps)
      .filter(([, e]) => e.attributed_player === player)
      .map(([key, e]) => [e.game_id, recapHref(key)]),
  )
}

// --- The periods ------------------------------------------------------------

const REGULATION = 4

export interface PeriodCell {
  /** 1..n as the registry keys them. */
  key: number
  /** "Q1".."Q4", then "OT1".. */
  label: string
  counts: Counts
}

export const periodLabel = (n: number): string => (n <= REGULATION ? `Q${n}` : `OT${n - REGULATION}`)

/** "1st".."4th", then "1st overtime".., for sentences. */
const periodWord = (n: number): string => (n <= REGULATION ? ordinal(n) : `${ordinal(n - REGULATION)} overtime`)

/** The registry's per-period counts in period order, totals added. */
export function periodCells(byPeriod: Record<string, PeriodCounts>): PeriodCell[] {
  return Object.entries(byPeriod)
    .map(([k, c]) => ({ key: Number(k), label: periodLabel(Number(k)), counts: { neg: c.neg, neu: c.neu, pos: c.pos, total: c.neg + c.neu + c.pos } }))
    .toSorted((a, b) => a.key - b.key)
}

/** The strip's text alternative: each period's negative share and n. */
export function periodsText(cells: readonly PeriodCell[]): string {
  return cells
    .map((c) => (c.counts.total ? `${c.label} ${fmtPct(negRate(c.counts), 0)} negative of ${fmtInt(c.counts.total)}` : `${c.label} no comments`))
    .join(', ')
}

// --- The hook ----------------------------------------------------------------
// One computed sentence per recap. The thresholds are page choices, not
// rules: a move this size between periods reads as a turn. Every move is
// measured in the rounded points the sentence prints, so a printed gap of
// 20 always reads as one and a printed gap of 19 never does.

const SWING = 20
const RETURN = SWING / 2

const plural = (n: number, one: string, many: string): string => (n === 1 ? one : many)
const pts = (c: PeriodCell): number => Math.round(100 * negRate(c.counts))
const pctOf = (points: number): string => `${fmtInt(points)}%`
const pct = (c: PeriodCell): string => pctOf(pts(c))

/** One period standing off both neighbours, which agree with each other. */
function spike(cells: readonly PeriodCell[]): string | null {
  for (let i = 1; i < cells.length - 1; i++) {
    const [before, here, after] = [cells[i - 1]!, cells[i]!, cells[i + 1]!]
    const up = pts(here) - pts(before)
    const down = pts(here) - pts(after)
    if (Math.abs(pts(before) - pts(after)) > RETURN) continue
    if (up >= SWING && down >= SWING) return `spiked to ${pct(here)} negative in the ${periodWord(here.key)}, from ${pct(before)} either side`
    if (up <= -SWING && down <= -SWING) return `dipped to ${pct(here)} negative in the ${periodWord(here.key)}, from ${pct(before)} either side`
  }
  return null
}

/** The largest move between one period and a later one, when it reaches the threshold. */
function turn(cells: readonly PeriodCell[]): string | null {
  let best: { from: PeriodCell; to: PeriodCell; move: number } | null = null
  for (let i = 0; i < cells.length; i++) {
    for (let j = i + 1; j < cells.length; j++) {
      const move = pts(cells[j]!) - pts(cells[i]!)
      if (!best || Math.abs(move) > Math.abs(best.move)) best = { from: cells[i]!, to: cells[j]!, move }
    }
  }
  if (!best || Math.abs(best.move) < SWING) return null
  return `${pct(best.from)} negative in the ${periodWord(best.from.key)}, ${pct(best.to)} by the ${periodWord(best.to.key)}`
}

/**
 * The sentence the index leads with, from the periods the room spoke in.
 * Regulation is read first; the overtimes join only when regulation
 * holds no story, so a thin overtime never carries the headline.
 */
export function hook(cells: readonly PeriodCell[], usual: number): string {
  const raw = hookClause(cells, usual)
  return `${raw.charAt(0).toUpperCase()}${raw.slice(1)}.`
}

function hookClause(cells: readonly PeriodCell[], usual: number): string {
  const spoken = cells.filter((c) => c.counts.total > 0)
  const first = spoken[0]
  if (!first) return 'the room had nothing to say about him'
  if (spoken.length === 1) return `${pct(first)} negative in the ${periodWord(first.key)}, the only period with comments`
  const regulation = spoken.filter((c) => c.key <= REGULATION)
  const scopes = spoken.length > regulation.length ? [regulation, spoken] : [regulation]
  for (const scope of scopes) {
    const s = spike(scope)
    if (s) return s
  }
  for (const scope of scopes) {
    const t = turn(scope)
    if (t) return t
  }
  const lift = pts(first) - Math.round(100 * usual)
  if (first.key === 1 && lift >= SWING)
    return `${pct(first)} negative from the tip, ${fmtInt(lift)} ${plural(lift, 'point', 'points')} above his usual ${pctOf(Math.round(100 * usual))}`
  const points = spoken.map(pts)
  return `held between ${pctOf(Math.min(...points))} and ${pctOf(Math.max(...points))} negative all night`
}

// --- The verdict, the lines, the lag ----------------------------------------

export type Tone = 'neg' | 'pos' | 'neu'

/** The night's negative share minus his usual, the games table's rule; null under the floor. */
export function recapDelta(night: Counts | null, usual: Counts, floor: number): number | null {
  return night && night.total >= floor ? negRate(night) - negRate(usual) : null
}

/** Heat where the night was harsher than his usual, ice where kinder, bone otherwise. */
export function recapTone(delta: number | null): Tone {
  if (delta === null || delta === 0) return 'neu'
  return delta > 0 ? 'neg' : 'pos'
}

/** "19 pts · 14 reb · 38 min". */
export const boxLine = (box: PlayerGamesRow): string => `${fmtInt(box.pts)} pts · ${fmtInt(box.reb)} reb · ${fmtInt(box.minutes)} min`

/** "2,166 comments about him in a 47,934-comment thread". */
export const countsLine = (entry: RecapEntry): string =>
  `${fmtInt(entry.live_n)} comments about him in a ${fmtInt(entry.room_n)}-comment thread`

/** How long the room takes to react, in words; null when unmeasured. Never the seconds. */
export function lagPhrase(seconds: number | null): string | null {
  if (seconds === null) return null
  if (seconds < 45) return 'under a minute'
  if (seconds <= 90) return 'about a minute'
  return `about ${fmtInt(Math.round(seconds / 60))} minutes`
}

// --- The joins ---------------------------------------------------------------

export interface Recap {
  key: string
  entry: RecapEntry
  player: PlayersRow
  game: GamesRow
  line: GameLineParts
  box: PlayerGamesRow
  cells: PeriodCell[]
  /** The strip's population: his comments inside the period clocks. */
  inPeriods: Counts
  hook: string
  /** His season, every comment. */
  usual: Counts
  /** Every thread about him that night, post-game included; null when the view has no row. */
  night: Counts | null
  delta: number | null
  tone: Tone
}

/** Every curated recap in config order, joined once; the index, the route and the card read this. */
export function buildRecaps(manifest: Manifest, tables: Tables): Recap[] {
  const abbr = new Map(tables.teams.map((t) => [t.team, t.abbreviation]))
  const conferenceOf = new Map(tables.teams.map((t) => [t.team, t.conference]))
  const players = new Map(tables.players.map((p) => [p.attributed_player, p]))
  const games = new Map(tables.games.map((g) => [g.game_id, g]))
  const boxes = new Map(tables.player_games.map((r) => [`${r.game_id} ${r.attributed_player}`, r]))
  const nights = new Map(tables.game_sentiment.map((r) => [`${r.game_id} ${r.attributed_player}`, countsOf(r)]))
  const usuals = new Map(tables.player_overall.map((r) => [r.attributed_player, countsOf(r)]))
  const floor = manifest.rules.floors.game_min_n
  return Object.entries(manifest.recaps).map(([key, entry]) => {
    const at = `${entry.game_id} ${entry.attributed_player}`
    const player = players.get(entry.attributed_player)
    const game = games.get(entry.game_id)
    const box = boxes.get(at)
    const usual = usuals.get(entry.attributed_player)
    if (!player || !game || !box || !usual) throw new Error(`recap ${key}: the registry entry does not join to the dimensions`)
    const cells = periodCells(entry.by_period)
    const night = nights.get(at) ?? null
    const delta = recapDelta(night, usual, floor)
    return {
      key,
      entry,
      player,
      game,
      line: gameLine(game, abbr, conferenceOf),
      box,
      cells,
      inPeriods: sumCounts(cells.map((c) => c.counts)),
      hook: hook(cells, negRate(usual)),
      usual,
      night,
      delta,
      tone: recapTone(delta),
    }
  })
}

/** "Game 7, West Finals" or "Regular season, Oct 21": the game as a phrase. */
export const gamePhrase = (line: GameLineParts): string => (line.game ? `${line.game}, ${line.round}` : `${line.round}, ${line.date}`)

/** The index's description: the tagline, then the lead's night. */
export function indexLede(lead: Recap | null): string {
  const tagline = 'Every comment, as it landed.'
  if (!lead) return `${tagline} No recap is curated this season.`
  return `${tagline} The room on ${lead.entry.attributed_player}, ${gamePhrase(lead.line)}: ${lead.hook}`
}

/** The final verdict's sentence: every thread about him that night against his usual. */
export function nightSentence(name: string, night: Counts | null, usual: Counts, floor: number): string {
  if (!night) return `Nobody mentioned ${name} in the game's threads that night.`
  if (night.total < floor) return `Too few comments about ${name} that night to judge: ${fmtInt(night.total)}.`
  const delta = negRate(night) - negRate(usual)
  const points = Math.abs(Math.round(100 * delta))
  const against = points === 0 ? 'at his usual' : `${fmtInt(points)} ${plural(points, 'point', 'points')} ${delta > 0 ? 'harsher' : 'kinder'} than his usual ${fmtPct(negRate(usual), 0)}`
  return `Every thread about ${name} that night, post-game included: ${fmtPct(negRate(night), 0)} negative of ${fmtInt(night.total)} comments, ${against}.`
}

/** The first recap leads; the rest are the list. */
export const leadAndList = (recaps: readonly Recap[]): { lead: Recap | null; list: Recap[] } => ({ lead: recaps[0] ?? null, list: recaps.slice(1) })
