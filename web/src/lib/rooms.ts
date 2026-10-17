// The player page's rooms: one cell per room at the floor, the room's share
// of his comments and its split, the harshest room marked, and the lede.
// The floor arrives from the manifest; the two thresholds here are page
// choices. The room vocabulary lives here for every page that names one.
import type { PlayerRoomRow } from '../data/types.gen'
import { fmtInt, fmtPct } from './format'
import { countsOf, negRate } from './metrics'
import type { Counts } from './types'

// Page choices, not rules.
/** The share of his comments a room needs to carry the lede's claim; the tag has no such bar. */
export const HEADLINE_SHARE = 0.1
/** A gap between two rooms, in points, under which they ran level; at or over it, one was harsher. */
export const EXCEPTION_GAP = 0.05

/** Every room in the order the rows are drawn: the threads first, then the front page, then the small rooms. */
export const ROOM_ORDER: readonly string[] = ['game_thread', 'post_game_thread', 'daily', 'general', 'highlight', 'news', 'lowlight', 'injury', 'discussion']

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

/** Where a comment sat, as a phrase after "talked about most harshly". */
export const ROOM_WHERE: Record<string, string> = {
  game_thread: 'in the game threads',
  post_game_thread: 'in the post-game threads',
  daily: 'in the daily chat thread',
  general: 'on the front page',
  highlight: 'under highlights',
  news: 'under news posts',
  lowlight: 'under lowlights',
  injury: 'under injury posts',
  discussion: 'in discussion posts',
}

export interface RoomCell {
  key: string
  label: string
  counts: Counts
  /** The negative share. */
  rate: number
  /** The room's share of his comments. */
  share: number
  /** The highest negative share of any drawn room; never set with fewer than two drawn. */
  harshest: boolean
}

export interface UnderFloor {
  key: string
  label: string
  n: number
}

export interface PlayerRooms {
  /** The rooms at the floor, in ROOM_ORDER. */
  drawn: RoomCell[]
  /** The rooms under it, the largest first, for the rule line. */
  under: UnderFloor[]
  /** The tagged room: the highest negative share over every drawn room, ties to the larger n; null under two drawn. */
  harshest: RoomCell | null
  /** The lede's room: the highest negative share among rooms at HEADLINE_SHARE, falling back to the harshest; null with nothing drawn. */
  headline: RoomCell | null
  /** The largest share, the full bar. */
  maxShare: number
}

const order = (key: string): number => {
  const i = ROOM_ORDER.indexOf(key)
  return i < 0 ? ROOM_ORDER.length : i
}
const harsher = (a: RoomCell, b: RoomCell): RoomCell => (b.rate > a.rate || (b.rate === a.rate && b.counts.total > a.counts.total) ? b : a)
const pick = (cells: readonly RoomCell[]): RoomCell | null => (cells.length ? cells.reduce(harsher) : null)

/** His rooms at the floor, the tag and the lede's room decided. */
export function playerRooms(rows: readonly PlayerRoomRow[], season: Counts, floor: number): PlayerRooms {
  const cells = rows
    .map((r) => {
      const counts = countsOf(r)
      return { key: r.post_type, label: ROOM_LABELS[r.post_type] ?? r.post_type, counts, rate: negRate(counts), share: season.total ? counts.total / season.total : 0, harshest: false }
    })
    .toSorted((a, b) => order(a.key) - order(b.key) || a.key.localeCompare(b.key))
  const drawn = cells.filter((c) => c.counts.total >= floor)
  const under = cells
    .filter((c) => c.counts.total < floor)
    .map((c) => ({ key: c.key, label: c.label, n: c.counts.total }))
    .toSorted((a, b) => b.n - a.n || a.key.localeCompare(b.key))
  const top = pick(drawn)
  const harshest = drawn.length >= 2 ? top : null
  if (harshest) harshest.harshest = true
  const headline = pick(drawn.filter((c) => c.share >= HEADLINE_SHARE)) ?? top
  return { drawn, under, harshest, headline, maxShare: Math.max(0, ...drawn.map((c) => c.share)) }
}

/** A room's share of his comments, whole points; "under 1%" below one. */
export const fmtShareOf = (share: number): string => (share < 0.01 ? 'under 1%' : fmtPct(share, 0))

/** A gap in whole points, as the sentence says it; the branch is decided on the same rounding. */
const roundPoints = (gap: number): number => Math.round(Math.abs(gap) * 100)
const points = (gap: number): string => {
  const n = roundPoints(gap)
  return n === 0 ? 'less than a point' : `${n} ${n === 1 ? 'point' : 'points'}`
}

/**
 * The lede. The headline room against his season; the game threads against
 * the front page when both are drawn, a side taken only at the exception
 * gap; and the tagged room when the headline passed it over.
 */
export function roomsSentence(name: string, pr: PlayerRooms, season: Counts): string {
  const { drawn, harshest, headline } = pr
  if (!headline) return ''
  const against = `${fmtPct(headline.rate)} negative, against ${fmtPct(negRate(season))} across his season.`
  if (drawn.length === 1) {
    const where = ROOM_WHERE[headline.key] ?? `in ${headline.label.toLowerCase()}`
    return `Only one room holds enough comments about ${name} to split. ${where[0]!.toUpperCase()}${where.slice(1)}, ${against}`
  }
  const parts = [`${name} was talked about most harshly ${ROOM_WHERE[headline.key] ?? `in ${headline.label.toLowerCase()}`}: ${against}`]
  const gt = drawn.find((c) => c.key === 'game_thread')
  const fp = drawn.find((c) => c.key === 'general')
  if (gt && fp) {
    const gap = fp.rate - gt.rate
    if (roundPoints(gap) < roundPoints(EXCEPTION_GAP)) parts.push(`The game threads and the front page ran level, ${points(gap)} apart.`)
    else if (gap > 0) parts.push(`The front page ran ${points(gap)} harsher than the game threads, the reverse of the usual order: his season was a story off the court.`)
    else parts.push(`The game threads ran ${points(gap)} harsher than the front page: his play was graded live.`)
  }
  if (harshest && harshest.key !== headline.key) parts.push(`${harshest.label} ran harsher still, ${fmtPct(harshest.rate)} negative, on ${fmtShareOf(harshest.share)} of his comments.`)
  return parts.join(' ')
}

/** The rule line under the rows: what a room is, the floor, the rooms left out, and which room the lede speaks for. */
export function roomsRule(name: string, floor: number, under: readonly UnderFloor[]): string {
  const left = under.length ? `; left out here: ${under.map((u) => `${u.label} (${fmtInt(u.n)})`).join(', ')}` : ''
  return (
    `A room is the kind of post a comment sat under: a game thread, the front page, a highlight. A room is drawn when it holds at least ${fmtInt(floor)} comments about ${name}${left}. ` +
    `The lede speaks for rooms holding at least ${fmtShareOf(HEADLINE_SHARE)} of his comments; the harshest mark goes to the highest negative share of any drawn room. Shares are from summed counts, never a mean of rates.`
  )
}
