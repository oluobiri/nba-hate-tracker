// The player page's rooms: one cell per room at the floor, the room's share
// of his comments and its split, the harshest and the warmest room marked
// by net sentiment, and the lede. The floor arrives from the manifest; the
// one threshold here is a page choice. The room vocabulary lives here for
// every page that names one.
import type { PlayerRoomRow } from '../data/types.gen'
import { fmtInt, fmtPct } from './format'
import { countsOf, negRate, netSentiment } from './metrics'
import { fmtNet } from './net'
import type { Counts } from './types'

// Page choice, not a rule.
/** A gap between two rooms, in points, under which the lede says nothing of them; at or over it, one was harsher. */
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

/** Where a comment sat, as a phrase after "talked about most". */
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
  /** Net sentiment: the positive share minus the negative. */
  net: number
  /** The room's share of his comments. */
  share: number
  /** The lowest net of any drawn room; never set with fewer than two drawn. */
  harshest: boolean
  /** The highest net of any drawn room; never set with fewer than two drawn. */
  warmest: boolean
}

export interface UnderFloor {
  key: string
  label: string
  n: number
}

export interface PlayerRooms {
  /** The rooms at the floor, in ROOM_ORDER. */
  drawn: RoomCell[]
  /** The rooms under it, the largest first, for the method line. */
  under: UnderFloor[]
  /** The room with the most of his comments; null with nothing drawn. */
  biggest: RoomCell | null
  /** The lowest net over every drawn room, ties to the larger n; null under two drawn. */
  harshest: RoomCell | null
  /** The highest net over every drawn room, ties to the larger n; null under two drawn. */
  warmest: RoomCell | null
  /** The largest share, the full bar. */
  maxShare: number
}

const order = (key: string): number => {
  const i = ROOM_ORDER.indexOf(key)
  return i < 0 ? ROOM_ORDER.length : i
}
/** The cell that wins on `by`; on a tie the larger room, then the earlier in drawing order. */
const top = (cells: readonly RoomCell[], by: (c: RoomCell) => number): RoomCell | null =>
  cells.length ? cells.reduce((a, b) => (by(b) > by(a) || (by(b) === by(a) && b.counts.total > a.counts.total) ? b : a)) : null

/** His rooms at the floor, the biggest, the harshest and the warmest decided. */
export function playerRooms(rows: readonly PlayerRoomRow[], season: Counts, floor: number): PlayerRooms {
  const cells = rows
    .map((r) => {
      const counts = countsOf(r)
      return { key: r.post_type, label: ROOM_LABELS[r.post_type] ?? r.post_type, counts, rate: negRate(counts), net: netSentiment(counts), share: season.total ? counts.total / season.total : 0, harshest: false, warmest: false }
    })
    .toSorted((a, b) => order(a.key) - order(b.key) || a.key.localeCompare(b.key))
  const drawn = cells.filter((c) => c.counts.total >= floor)
  const under = cells
    .filter((c) => c.counts.total < floor)
    .map((c) => ({ key: c.key, label: c.label, n: c.counts.total }))
    .toSorted((a, b) => b.n - a.n || a.key.localeCompare(b.key))
  const biggest = top(drawn, (c) => c.counts.total)
  const harshest = drawn.length >= 2 ? top(drawn, (c) => -c.net) : null
  const warmest = drawn.length >= 2 ? top(drawn, (c) => c.net) : null
  if (harshest) harshest.harshest = true
  if (warmest) warmest.warmest = true
  return { drawn, under, biggest, harshest, warmest, maxShare: Math.max(0, ...drawn.map((c) => c.share)) }
}

/** A room's share of his comments, whole points; "under 1%" below one. */
export const fmtShareOf = (share: number): string => (share < 0.01 ? 'under 1%' : fmtPct(share, 0))

/** A gap in whole points, as the sentence says it; the branch is decided on the same rounding. */
const roundPoints = (gap: number): number => Math.round(Math.abs(gap) * 100)
const points = (gap: number): string => {
  const n = roundPoints(gap)
  return `${n} ${n === 1 ? 'point' : 'points'}`
}
const capital = (s: string): string => `${s[0]!.toUpperCase()}${s.slice(1)}`
const where = (c: RoomCell): string => ROOM_WHERE[c.key] ?? `in ${c.label.toLowerCase()}`
/** The label mid-sentence: "the game threads", "news"; a room with no words keeps its key. */
const named = (c: RoomCell): string => {
  const w = ROOM_WHERE[c.key]
  return w ? w.replace(/^(in|on|under) /, '') : c.label
}

/**
 * The lede. Where he was talked about most, its net sentiment against his
 * season's; his harshest and warmest rooms by net, each with its size; and
 * the game threads against the front page when both are drawn and the gap
 * reaches the band, a reading attached only in the two clean cases: harsher
 * game threads grade his play live; a front page below zero and below the
 * game threads is a story off the court. A loved player's trailing front
 * page is neither.
 */
export function roomsSentence(name: string, pr: PlayerRooms, season: Counts): string {
  const { drawn, biggest, harshest, warmest } = pr
  if (!biggest) return ''
  const seasonNet = netSentiment(season)
  const against = `${fmtInt(biggest.counts.total)} of his ${fmtInt(season.total)} comments, ${fmtNet(biggest.net)} net sentiment against ${fmtNet(seasonNet)} across his season.`
  if (drawn.length === 1) return `Only one room holds enough comments about ${name} to split. ${capital(where(biggest))}, ${against}`
  const parts = [`${name} was talked about most ${where(biggest)}: ${against}`]
  if (harshest && warmest && harshest.key !== warmest.key) {
    const sized = (c: RoomCell): string => (c.key === biggest.key ? named(c) : `${named(c)}, ${fmtNet(c.net)} on ${fmtShareOf(c.share)} of his comments`)
    parts.push(`His harshest room was ${sized(harshest)}; his warmest ${sized(warmest)}.`)
  }
  const gt = drawn.find((c) => c.key === 'game_thread')
  const fp = drawn.find((c) => c.key === 'general')
  if (gt && fp) {
    const gap = gt.net - fp.net
    if (roundPoints(gap) >= roundPoints(EXCEPTION_GAP)) {
      if (gap < 0) parts.push(`The game threads ran ${points(gap)} harsher than the front page: his play was graded live.`)
      else if (fp.net < 0) parts.push(`The front page ran ${points(gap)} harsher than the game threads, the reverse of the usual order: his season was a story off the court.`)
      else parts.push(`The game threads ran ${points(gap)} warmer than the front page.`)
    }
  }
  return parts.join(' ')
}

/** The method line under the rows: what a room is, the floor, the rooms left out, and what the marks mean. */
export function roomsMethod(name: string, floor: number, under: readonly UnderFloor[]): string {
  const left = under.length ? `; left out here: ${under.map((u) => `${u.label} (${fmtInt(u.n)})`).join(', ')}` : ''
  return (
    `A room is the kind of post a comment sat under: a game thread, the front page, a highlight. A room is drawn when it holds at least ${fmtInt(floor)} comments about ${name}${left}. ` +
    `The bar is the room's share of his comments, its split the room's sentiment. Harshest and warmest are by net sentiment, positive minus negative, from summed counts, never a mean of rates.`
  )
}
