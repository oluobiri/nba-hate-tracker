// The team page: one fanbase as a row and a column of the fan × roster
// matrix. A cell is player_fan_team summed to (fan, roster); every Δ is a
// rate from summed counts against a baseline of summed counts, in points.
// Floors arrive as arguments, read from the manifest.
import { nickname, possessive } from './fans'
import { fmtInt, fmtPct, fmtSigned, ordinal } from './format'
import { negRate, posRate, sumCounts } from './metrics'
import type { Counts } from './types'

export interface MatrixRow extends Counts {
  fan: string
  /** The commented player's roster team; null for a free agent, who belongs to no column. */
  roster: string | null
}

export interface Matrix {
  /** fan → roster → summed counts, the fan's own roster included. */
  byFan: Map<string, Map<string, Counts>>
  /** roster → fan → summed counts. */
  byRoster: Map<string, Map<string, Counts>>
  /** roster → summed over every fanbase: the baseline a cell is read against. */
  rosterAverage: Map<string, Counts>
}

const add = (m: Map<string, Counts>, k: string, c: Counts): void => {
  m.set(k, sumCounts([m.get(k) ?? { neg: 0, neu: 0, pos: 0, total: 0 }, c]))
}

const nested = (m: Map<string, Map<string, Counts>>, a: string, b: string, c: Counts): void => {
  const inner = m.get(a) ?? new Map<string, Counts>()
  add(inner, b, c)
  m.set(a, inner)
}

/** The whole matrix from player-grain rows, once per build. */
export function fanRosterMatrix(rows: readonly MatrixRow[]): Matrix {
  const byFan = new Map<string, Map<string, Counts>>()
  const byRoster = new Map<string, Map<string, Counts>>()
  const rosterAverage = new Map<string, Counts>()
  for (const r of rows) {
    if (r.roster === null) continue
    nested(byFan, r.fan, r.roster, r)
    nested(byRoster, r.roster, r.fan, r)
    add(rosterAverage, r.roster, r)
  }
  return { byFan, byRoster, rosterAverage }
}

export interface FanbaseRank {
  /** 1 = the highest negative rate of all fanbases. */
  rank: number
  of: number
}

/** The header sentence; doubles as the page description. */
export function fanbaseVerdict(team: string, counts: Counts, { rank, of }: FanbaseRank): string {
  const place = rank === 1 ? 'The saltiest' : rank === of ? 'The least salty' : `The ${ordinal(rank)} saltiest`
  return `${place} fanbase of ${fmtInt(of)}: ${fmtPct(negRate(counts), 0)} of what ${possessive(team)} say about players is negative, ${fmtPct(posRate(counts), 0)} positive, across ${fmtInt(counts.total)} comments.`
}

export interface RosterPlayer {
  attributed_player: string
  slug: string
  position: string | null
  headshot_url: string
}

export interface GapRow {
  name: string
  slug: string
  position: string | null
  headshot: string
  own: Counts
  /** Every other flaired fanbase, summed. */
  rivals: Counts
  /** Own negative rate minus the rivals', as a fraction; null under the floor. */
  delta: number | null
}

/** One row per tracked player on the roster, kindest first; under-floor rows last, by own n. */
export function gapRows(team: string, roster: readonly RosterPlayer[], rowsByPlayer: Map<string, readonly (Counts & { fan: string })[]>, floor: number): GapRow[] {
  const rows = roster.map((p): GapRow => {
    const all = rowsByPlayer.get(p.attributed_player) ?? []
    const own = sumCounts(all.filter((r) => r.fan === team))
    const rivals = sumCounts(all.filter((r) => r.fan !== team))
    const delta = own.total >= floor && rivals.total > 0 ? negRate(own) - negRate(rivals) : null
    return { name: p.attributed_player, slug: p.slug, position: p.position, headshot: p.headshot_url, own, rivals, delta }
  })
  return rows.toSorted((a, b) => {
    if (a.delta === null || b.delta === null) return a.delta === null ? (b.delta === null ? b.own.total - a.own.total : 1) : -1
    return a.delta - b.delta || b.own.total - a.own.total
  })
}

const pts = (delta: number): string => `${fmtSigned(delta, 0)} pts`
const points = (delta: number): string => `${(100 * Math.abs(delta)).toFixed(0)} points`

/** The Own players lede: how many of their own they are kinder to, and the two extremes. */
export function gapSummary(team: string, rows: readonly GapRow[], floor: number): string {
  const fans = possessive(team)
  const judged = rows.filter((r): r is GapRow & { delta: number } => r.delta !== null)
  const thin = rows.length - judged.length
  const thinNote = thin ? ` ${fmtInt(thin)} more ${thin === 1 ? 'sits' : 'sit'} under the floor of ${fmtInt(floor)} of their own comments.` : ''
  if (rows.length === 0) return `${fans} have no tracked player on their roster.`
  if (judged.length === 0) return `${fans} have fewer than ${fmtInt(floor)} comments about any of their own ${fmtInt(rows.length)} tracked players, so no gap is shown.`
  if (judged.length === 1) {
    const [r] = judged
    const dir = r!.delta < 0 ? 'kinder' : r!.delta > 0 ? 'harsher' : 'no different'
    const how = dir === 'no different' ? 'no different from rival fans on' : `${points(r!.delta)} ${dir} than rival fans to`
    return `${fans} are ${how} ${r!.name}, their one tracked player with enough of their own comments.${thinNote}`
  }
  const kinder = judged.filter((r) => r.delta < 0).length
  const softest = judged[0]!
  const hardest = judged.at(-1)!
  const count = kinder === judged.length ? `all ${fmtInt(judged.length)}` : `${fmtInt(kinder)} of their ${fmtInt(judged.length)}`
  return `${fans} are kinder than rival fans to ${count} players: softest on ${softest.name} (${pts(softest.delta)}), hardest on ${hardest.name} (${pts(hardest.delta)}).${thinNote}`
}

export interface Described {
  label: string
  href: string
  logo: string
}

export interface DeltaRow extends Described {
  key: string
  n: number
  /** The cell's rate for this list's sentiment, as a fraction. */
  rate: number
  /** The baseline's rate for the same sentiment. */
  baseline: number
  delta: number
}

export interface DeltaLists {
  /** By negative-rate Δ, largest first. */
  grudges: DeltaRow[]
  /** By positive-rate Δ, largest first. */
  flowers: DeltaRow[]
  eligible: number
  /** Spans zero and every Δ in both lists, so top rows and the rest share one axis. */
  domain: [number, number]
}

/** Both lists over the cells at or above the floor, each Δ against its own key's baseline. */
export function deltaLists(cells: readonly (Counts & { key: string })[], baseline: (key: string) => Counts, floor: number, describe: (key: string) => Described): DeltaLists {
  const eligible = cells.filter((c) => c.total >= floor)
  const rows = (rate: (c: Counts) => number): DeltaRow[] =>
    eligible
      .map((c) => {
        const base = rate(baseline(c.key))
        return { key: c.key, ...describe(c.key), n: c.total, rate: rate(c), baseline: base, delta: rate(c) - base }
      })
      .toSorted((a, b) => b.delta - a.delta || b.n - a.n)
  const grudges = rows(negRate)
  const flowers = rows(posRate)
  const deltas = [...grudges, ...flowers].map((r) => r.delta)
  return { grudges, flowers, eligible: eligible.length, domain: [Math.min(0, ...deltas), Math.max(0, ...deltas)] }
}

/** Grudges and flowers lede: this fanbase against the other rosters. */
export function targetsSummary(team: string, lists: DeltaLists, floor: number): string {
  if (lists.eligible < 2) return fewEligibleSentence(team, lists.eligible, floor, 'targets')
  const g = lists.grudges[0]!
  const f = lists.flowers[0]!
  return `Across the ${fmtInt(lists.eligible)} rosters ${possessive(team)} have at least ${fmtInt(floor)} comments about, they are hardest on the ${g.label} (${pts(g.delta)} negative against that roster's usual) and warmest to the ${f.label} (${pts(f.delta)} positive against usual).`
}

/** The league lede: the other fanbases against this roster. */
export function leagueSummary(team: string, lists: DeltaLists, floor: number): string {
  if (lists.eligible < 2) return fewEligibleSentence(team, lists.eligible, floor, 'fans')
  const g = lists.grudges[0]!
  const f = lists.flowers[0]!
  return `Of the ${fmtInt(lists.eligible)} fanbases with at least ${fmtInt(floor)} comments about ${nickname(team)} players, ${g.label} are hardest on them (${pts(g.delta)} negative against the ${nickname(team)}' usual) and ${f.label} warmest (${pts(f.delta)} positive against usual).`
}

/** The one-sentence state when a list would have fewer than two rows. */
export function fewEligibleSentence(team: string, eligible: number, floor: number, side: 'targets' | 'fans'): string {
  const what = side === 'targets' ? `${eligible === 1 ? 'roster has' : 'rosters have'} at least ${fmtInt(floor)} comments from ${possessive(team)}` : `${eligible === 1 ? 'fanbase has' : 'fanbases have'} at least ${fmtInt(floor)} comments about ${nickname(team)} players`
  return `Only ${fmtInt(eligible)} ${what}, too few to rank.`
}
