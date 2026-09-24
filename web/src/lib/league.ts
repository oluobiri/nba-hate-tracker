// The league at once: every fanbase on every roster as cells, for the
// fanbases page. The team page's matrix (fanbase.ts) is read whole here:
// the two headline lists over every pair, the grid's plain props, and the
// sentences both share. Floors arrive as arguments, read from the manifest.
import type { TeamsRow } from '../data/types.gen'
import type { Described, DeltaLists, Matrix } from './fanbase'
import { nickname, possessive } from './fans'
import { fmtInt, fmtPct, fmtSigned } from './format'
import { negRate } from './metrics'
import type { Counts } from './types'

const SEP = '|'

/** A cell's key for deltaLists: the fan team, then the roster team. */
export const pairKey = (fan: string, roster: string): string => `${fan}${SEP}${roster}`

export function splitKey(key: string): { fan: string; roster: string } {
  const i = key.indexOf(SEP)
  return { fan: key.slice(0, i), roster: key.slice(i + 1) }
}

/** Every off-diagonal cell of the matrix, keyed, in the matrix's order. */
export function pairCells(m: Matrix): (Counts & { key: string })[] {
  const cells: (Counts & { key: string })[] = []
  for (const [fan, byRoster] of m.byFan) for (const [roster, c] of byRoster) if (roster !== fan) cells.push({ key: pairKey(fan, roster), ...c })
  return cells
}

/**
 * A pair as a list row: "Pistons fans → Hornets", linking to the target's
 * page at the section where the same cell sits as a row, the target's logo.
 */
export function describePair(teams: ReadonlyMap<string, TeamsRow>): (key: string) => Described {
  return (key) => {
    const { fan, roster } = splitKey(key)
    const target = teams.get(roster)!
    return { label: `${possessive(fan)} → ${nickname(roster)}`, href: `/fanbases/${target.abbreviation.toLowerCase()}/#league`, logo: target.logo_url }
  }
}

export interface GridTeam {
  abbr: string
  team: string
  href: string
}

/** The grid's axes: every team, alphabetical, as row and column. */
export function gridTeams(teams: readonly TeamsRow[]): GridTeam[] {
  return teams
    .map((t) => ({ abbr: t.abbreviation, team: t.team, href: `/fanbases/${t.abbreviation.toLowerCase()}/` }))
    .toSorted((a, b) => a.team.localeCompare(b.team))
}

export interface GridCell {
  /** Row: index into the teams, the fans. */
  f: number
  /** Column: index into the teams, the roster. */
  r: number
  n: number
  /** Negative comments. */
  neg: number
  /** The negative rate's Δ against the roster's usual, as a fraction. */
  dneg: number
}

const round4 = (v: number): number => Math.round(v * 1e4) / 1e4

/** Every cell the matrix holds, the diagonal included, by row then column. */
export function gridCells(m: Matrix, teams: readonly GridTeam[]): GridCell[] {
  const index = new Map(teams.map((t, i) => [t.team, i]))
  const cells: GridCell[] = []
  for (const [fan, byRoster] of m.byFan) {
    const f = index.get(fan)
    if (f === undefined) continue
    for (const [roster, c] of byRoster) {
      const r = index.get(roster)
      if (r === undefined) continue
      cells.push({ f, r, n: c.total, neg: c.neg, dneg: round4(negRate(c) - negRate(m.rosterAverage.get(roster)!)) })
    }
  }
  return cells.toSorted((a, b) => a.f - b.f || a.r - b.r)
}

/** The Δ that fills a cell: the farthest either list reaches from zero. */
export const deltaLimit = ([lo, hi]: readonly [number, number]): number => Math.max(-lo, hi)

/** The grid's cell floors, as multiples of the published one. */
export const MIN_MULTIPLES = [1, 2, 5, 10] as const
export const minPresets = (floor: number): number[] => MIN_MULTIPLES.map((k) => k * floor)

/** A cell read aloud: the tooltip, the cell's hidden text, the worked example. */
export function cellSentence(cell: GridCell, teams: readonly GridTeam[], min: number): string {
  const fans = possessive(teams[cell.f]!.team)
  const roster = nickname(teams[cell.r]!.team)
  if (cell.f === cell.r) return `${fans} on their own players — read on the team page.`
  if (cell.n < min) return `${fans} on ${roster} players — ${fmtInt(cell.n)} comments, under the minimum of ${fmtInt(min)}.`
  const rate = cell.neg / cell.n
  const n = Math.abs(Math.round(100 * cell.dneg))
  const against = n === 0 ? 'at' : `${points(n)} ${cell.dneg > 0 ? 'above' : 'below'}`
  return `${fans} on ${roster} players — ${fmtPct(rate, 0)} negative, ${against} the ${roster}' usual ${fmtPct(rate - cell.dneg, 0)}, from ${fmtInt(cell.n)} comments.`
}

const points = (n: number): string => `${n} point${n === 1 ? '' : 's'}`
const gap = (d: number): string => points(Math.abs(Math.round(100 * d)))
const pts = (d: number): string => `${fmtSigned(d, 0)} pts`
const pair = (key: string): { fans: string; roster: string } => {
  const { fan, roster } = splitKey(key)
  return { fans: possessive(fan), roster: nickname(roster) }
}

/** The page lede and the lists' text alternative: the lead grudge and the lead flowers. */
export function landingLede(lists: DeltaLists, total: number, floor: number): string {
  const g = lists.grudges[0]!
  const f = lists.flowers[0]!
  const gp = pair(g.key)
  const fp = pair(f.key)
  return `Across the ${fmtInt(lists.eligible)} of ${fmtInt(total)} fan–roster pairs with at least ${fmtInt(floor)} comments, the biggest grudge is ${gp.fans} on the ${gp.roster}, ${gap(g.delta)} more negative than the ${gp.roster}' usual; the warmest flowers are ${fp.fans} on the ${fp.roster}, ${gap(f.delta)} more positive than the ${fp.roster}' usual.`
}

/** The grid's caption: its shape, its floor, its two ends by negative Δ, signed. */
export function gridSummary(lists: DeltaLists, teams: number, total: number, floor: number): string {
  const harsh = lists.grudges[0]!
  const kind = lists.grudges.at(-1)!
  const hp = pair(harsh.key)
  const kp = pair(kind.key)
  return `${fmtInt(teams)} fanbases on ${fmtInt(teams)} rosters, each cell the fanbase's negative rate against the roster's usual: ${fmtInt(lists.eligible)} of ${fmtInt(total)} pairs have at least ${fmtInt(floor)} comments. Harshest: ${hp.fans} on ${hp.roster} players (${pts(harsh.delta)}); kindest: ${kp.fans} on ${kp.roster} players (${pts(kind.delta)}).`
}

export interface PickerTeam {
  abbr: string
  name: string
  href: string
  logo: string
}

export interface PickerGroup {
  conference: string
  teams: PickerTeam[]
}

const CONFERENCES = ['West', 'East']
const conferenceOrder = (c: string): number => (CONFERENCES.includes(c) ? CONFERENCES.indexOf(c) : CONFERENCES.length)

/** The picker: one group per conference, West first, alphabetical inside. */
export function pickerGroups(teams: readonly TeamsRow[]): PickerGroup[] {
  const groups = new Map<string, PickerTeam[]>()
  for (const t of teams.toSorted((a, b) => a.team.localeCompare(b.team))) {
    const list = groups.get(t.conference) ?? []
    list.push({ abbr: t.abbreviation, name: t.team, href: `/fanbases/${t.abbreviation.toLowerCase()}/`, logo: t.logo_url })
    groups.set(t.conference, list)
  }
  return [...groups]
    .toSorted(([a], [b]) => conferenceOrder(a) - conferenceOrder(b) || a.localeCompare(b))
    .map(([conference, list]) => ({ conference, teams: list }))
}
