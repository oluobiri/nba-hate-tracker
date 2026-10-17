// The population map's view: every tracked player grouped by roster team,
// the groups by their comment sum, the team header's count and net summed
// over the boxes shown, and the eyebrow's sentence. The seven without a
// roster team form one group that a conference view hides. Roster and
// conference come from the dimension tables; the official minimum arrives
// from the manifest. The label fitting is a character-width estimate,
// since the tiles are laid before they are painted.
import { fmtInt, fmtPct } from './format'
import { negRate, netSentiment, posRate, sumCounts } from './metrics'
import { fmtNet } from './net'
import type { Counts } from './types'

export interface PopulationRow extends Counts {
  name: string
  slug: string
  /** The roster team's full name; null for the seven. */
  team: string | null
  abbr: string | null
  logo: string | null
  /** As players.conference spells it; null for the seven. */
  conference: string | null
  /** His status without a roster team; null on a roster. */
  status: string | null
}

export type Scope = 'all' | 'official'
export type Conf = 'all' | 'East' | 'West'

export interface PopulationGroup {
  /** The abbreviation, or NO_ROSTER_KEY. */
  key: string
  abbr: string | null
  name: string
  logo: string | null
  counts: Counts
  /** The roster's net over the boxes shown; null for the no-roster group. */
  net: number | null
  /** The largest first. */
  players: PopulationRow[]
}

export interface PopulationView {
  /** The largest first; one group when zoomed. */
  groups: PopulationGroup[]
  eyebrow: string
  /** The zoomed group, or null. */
  zoomed: PopulationGroup | null
  /** The crumb beside the conference select: "Click a team to zoom", or the zoomed team and its size. */
  crumb: string
}

export interface ViewOptions {
  scope: Scope
  conf: Conf
  /** A group key, or null for the whole map. */
  zoom: string | null
  /** rules.qualified_threshold */
  official: number
}

export const NO_ROSTER_KEY = '—'
export const NO_ROSTER_NAME = 'No roster team'

export const CONFERENCES: readonly { key: Conf; label: string }[] = [
  { key: 'all', label: 'All teams' },
  { key: 'East', label: 'Eastern Conference' },
  { key: 'West', label: 'Western Conference' },
]

// Page choices, not rules: the widths at which a header or a tile sheds its words.
/** A team header shows its count and net from here. */
const HEADER_FULL = 190
/** …its net alone from here, and the abbreviation alone below. */
const HEADER_NET = 100
/** The no-roster header's full name from here, its short name from HEADER_SHORT, a dash below. */
const HEADER_NO_ROSTER = 140
const HEADER_SHORT = 80
/** The no-roster header's count from here. */
const HEADER_NO_ROSTER_COUNT = 110
/** The label's estimated width per character, as a share of its font size, and its padding. */
const CHAR_W = 0.47
const LABEL_PAD = 12
const LABEL_LINE = 0.92
const LABEL_MIN = 10
const LABEL_STEP = 0.88
/** The net line under a name needs this much room: a tile at least this wide, and this much height below the name. */
const NET_MIN_W = 54
const NET_LINE_H = 18

/** The roster's net: positive minus negative over its summed comments. */
export const teamNet = (rows: readonly Counts[]): number => netSentiment(sumCounts(rows))

/** The players at or above the official minimum. */
export const officialCount = (rows: readonly PopulationRow[], official: number): number => rows.filter((r) => r.total >= official).length

const groupOf = (key: string, rows: readonly PopulationRow[]): PopulationGroup => {
  const first = rows[0]!
  const noRoster = key === NO_ROSTER_KEY
  return {
    key,
    abbr: noRoster ? null : first.abbr,
    name: noRoster ? NO_ROSTER_NAME : first.team!,
    logo: noRoster ? null : first.logo,
    counts: sumCounts(rows),
    net: noRoster ? null : teamNet(rows),
    players: rows.toSorted((a, b) => b.total - a.total),
  }
}

/** The map for one state: the rows in scope and conference, grouped by roster, the zoomed group alone when zoomed. */
export function populationView(rows: readonly PopulationRow[], opts: ViewOptions): PopulationView {
  const inScope = rows.filter((r) => (opts.scope === 'all' || r.total >= opts.official) && (opts.conf === 'all' || r.conference === opts.conf))
  const byKey = new Map<string, PopulationRow[]>()
  for (const r of inScope) {
    const key = r.abbr ?? NO_ROSTER_KEY
    const list = byKey.get(key)
    if (list) list.push(r)
    else byKey.set(key, [r])
  }
  const all = [...byKey].map(([key, rs]) => groupOf(key, rs)).toSorted((a, b) => b.counts.total - a.counts.total)
  const zoomed = opts.zoom === null ? null : (all.find((g) => g.key === opts.zoom) ?? null)
  const groups = zoomed ? [zoomed] : all
  const shown = groups.flatMap((g) => g.players)
  const total = sumCounts(shown).total
  const teams = groups.filter((g) => g.key !== NO_ROSTER_KEY).length
  const conf = CONFERENCES.find((c) => c.key === opts.conf)!
  const eyebrow = zoomed
    ? `${fmtInt(total)} comments about ${fmtInt(shown.length)} players`
    : `${opts.conf === 'all' ? 'Population' : conf.label} · ${fmtInt(total)} comments about ${fmtInt(shown.length)} players on ${fmtInt(teams)} teams`
  const crumb = zoomed ? `${zoomed.name} · ${fmtInt(zoomed.players.length)} players` : 'Click a team to zoom'
  return { groups, eyebrow, zoomed, crumb }
}

export interface HeaderLabel {
  /** The abbreviation, or the no-roster name as it narrows. */
  title: string
  /** "254,925 · −15 net", "−15 net", "254,925" or nothing. */
  detail: string
}

/** The team header's words at a width: the count drops first, then the net. */
export function headerLabel(group: PopulationGroup, width: number): HeaderLabel {
  if (group.key === NO_ROSTER_KEY) {
    const title = width >= HEADER_NO_ROSTER ? NO_ROSTER_NAME : width >= HEADER_SHORT ? 'No roster' : NO_ROSTER_KEY
    return { title, detail: width >= HEADER_NO_ROSTER_COUNT ? fmtInt(group.counts.total) : '' }
  }
  const net = `${fmtNet(group.net)} net`
  const detail = width >= HEADER_FULL ? `${fmtInt(group.counts.total)} · ${net}` : width >= HEADER_NET ? net : ''
  return { title: group.abbr!, detail }
}

/** The header's spoken sentence: the team, its comments, its players and its net. */
export function headerText(group: PopulationGroup): string {
  const parts = [group.name, `${fmtInt(group.counts.total)} comments`, `${fmtInt(group.players.length)} players`]
  if (group.net !== null) parts.push(`team net ${fmtNet(group.net)}`)
  return parts.join(' · ')
}

export interface TileLabel {
  fontSize: number
  line1: string
  /** The surname line; empty when the name is on one line. */
  line2: string
}

/**
 * The name as it fits a tile: first name over surname, the size stepping
 * down to the minimum; then the surname alone; null when nothing fits.
 */
export function tileLabel(name: string, w: number, h: number, base: number): TileLabel | null {
  const [first = '', ...rest] = name.split(' ')
  const last = rest.join(' ')
  const fits = (text: string, fs: number, lines: number): boolean => text.length * CHAR_W * fs + LABEL_PAD <= w && fs * LABEL_LINE * lines + LABEL_PAD - 2 <= h
  if (last) {
    for (let fs = base; fs >= LABEL_MIN; fs *= LABEL_STEP) {
      if (fits(first.length >= last.length ? first : last, fs, 2)) return { fontSize: fs, line1: first, line2: last }
    }
  }
  const solo = last || first
  for (let fs = base; fs >= LABEL_MIN; fs *= LABEL_STEP) {
    if (fits(solo, fs, 1)) return { fontSize: fs, line1: solo, line2: '' }
  }
  return null
}

/** The base font size for a tile: scaled by its area, within the mock's bounds. */
export const tileBase = (w: number, h: number): number => Math.max(LABEL_MIN, Math.min(40, Math.sqrt(w * h) / 6.5))

/** Whether "−37 net" fits under the name. */
export function showNet(label: TileLabel | null, w: number, h: number): boolean {
  if (!label) return false
  const nameH = label.fontSize * LABEL_LINE * (label.line2 ? 2 : 1) + LABEL_PAD - 2
  return w >= NET_MIN_W && h >= nameH + NET_LINE_H
}

/** The tile's spoken sentence: name, team or status, comments, the split and the net. */
export function tileText(row: PopulationRow): string {
  const where = row.abbr ?? `${row.status} · ${NO_ROSTER_NAME.toLowerCase()}`
  return `${row.name} · ${where} · ${fmtInt(row.total)} comments · ${fmtPct(negRate(row))} negative, ${fmtPct(posRate(row))} positive, net ${fmtNet(netSentiment(row))}`
}
