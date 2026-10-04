// The race: the official leaderboard replayed week by week. The field is the
// players who finish at or above the official minimum; a frame is every
// comment through that week, so the last frame is the leaderboard. In the rate
// races a bar appears at the entry floor and, counts only growing, never
// leaves; the count races have no floor. Both rule numbers arrive as arguments.
import { LENS_META } from './metrics'
import type { Counts } from './types'
import type { RaceBy, RaceMode } from './url'

/** One player's counts, in sentiment order. */
export type Triple = readonly [neg: number, neu: number, pos: number]

export interface RaceRank {
  /** The player's index in the field. */
  i: number
  n: number
  /** The share or the count the race ranks by. */
  value: number
}

/** 'new' the week a player joins the board's ranking; otherwise places gained (positive) or lost. */
export type Move = 'new' | number

const total = (c: Triple): number => c[0] + c[1] + c[2]
const side = (mode: RaceMode): 0 | 2 => (mode === 'hated' ? 0 : 2)
const lensOf = (mode: RaceMode): 'neg' | 'pos' => (mode === 'hated' ? 'neg' : 'pos')

/** The players who finish at or above the official minimum, in name order. */
export function raceField<T extends Counts & { name: string }>(overall: readonly T[], official: number): T[] {
  return overall.filter((p) => p.total >= official).toSorted((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0))
}

/** Each fielded player's counts per week of the spine; a week without a row adds nothing. */
export function weeklyCounts(
  names: readonly string[],
  rows: readonly (Counts & { name: string; week: string })[],
  spine: readonly string[],
): Triple[][] {
  const at = new Map(spine.map((w, k) => [w, k]))
  const who = new Map(names.map((n, i) => [n, i]))
  const out: Triple[][] = names.map(() => spine.map((): Triple => [0, 0, 0]))
  for (const r of rows) {
    const i = who.get(r.name)
    const k = at.get(r.week)
    if (i === undefined || k === undefined) continue
    out[i]![k] = [r.neg, r.neu, r.pos]
  }
  return out
}

/** Weekly counts as one string, player by player: a compact island prop. */
export const packCounts = (weekly: readonly (readonly Triple[])[]): string => weekly.flat(2).join(',')

/** The inverse of `packCounts`; throws when the string is not players × weeks × 3 whole numbers. */
export function unpackCounts(packed: string, players: number, weeks: number): Triple[][] {
  const flat = packed ? packed.split(',').map(Number) : []
  if (flat.length !== players * weeks * 3 || flat.some((v) => !Number.isInteger(v) || v < 0))
    throw new Error(`race counts: expected ${players} × ${weeks} × 3 whole numbers, got ${flat.length} values`)
  const at = (o: number): Triple => [flat[o]!, flat[o + 1]!, flat[o + 2]!]
  return Array.from({ length: players }, (_p, i) => Array.from({ length: weeks }, (_w, k) => at((i * weeks + k) * 3)))
}

/** Frames: for each week, every player's counts through that week. */
export function cumulate(weekly: readonly (readonly Triple[])[]): Triple[][] {
  const weeks = weekly[0]?.length ?? 0
  const frames: Triple[][] = Array.from({ length: weeks }, () => [])
  weekly.forEach((player, i) => {
    let run: Triple = [0, 0, 0]
    player.forEach((c, k) => {
      run = [run[0] + c[0], run[1] + c[1], run[2] + c[2]]
      frames[k]![i] = run
    })
  })
  return frames
}

/** One frame's order: by the share or the count, ties to the larger n. Rate races keep players at or above `entry`. */
export function rankFrame(frame: readonly Triple[], mode: RaceMode, by: RaceBy, entry: number): RaceRank[] {
  const s = side(mode)
  return frame
    .map((c, i) => {
      const n = total(c)
      return { i, n, value: by === 'rate' ? (n ? c[s] / n : 0) : c[s] }
    })
    .filter((r) => (by === 'rate' ? r.n >= entry : r.value > 0))
    .toSorted((a, b) => b.value - a.value || b.n - a.n)
}

/** Each ranked player's movement against the previous week; a player who held his place is absent. No previous week, no movement. */
export function movement(now: readonly RaceRank[], before: readonly RaceRank[] | null): Map<number, Move> {
  const moves = new Map<number, Move>()
  if (!before) return moves
  const was = new Map(before.map((r, k) => [r.i, k]))
  now.forEach((r, k) => {
    const prev = was.get(r.i)
    if (prev === undefined) moves.set(r.i, 'new')
    else if (prev !== k) moves.set(r.i, prev - k)
  })
  return moves
}

/** "NEW", "▲2", "▼1". */
export const moveLabel = (m: Move): string => (m === 'new' ? 'NEW' : m > 0 ? `▲${m}` : `▼${-m}`)

/** The hero's lead line; on the last week the rate races say the leaderboard's sentence. */
export function raceLead(mode: RaceMode, by: RaceBy, last: boolean): string {
  if (by === 'rate') {
    const hero = LENS_META[lensOf(mode)].hero
    return last ? `r/NBA's ${hero} player is` : `The ${hero} player so far`
  }
  const word = mode === 'hated' ? 'negative' : 'positive'
  return last ? `The most ${word} comments went to` : `The most ${word} comments so far`
}

/** The players who reach the top `top` in any week of one race, as field indices. */
export function everTop(frames: readonly (readonly Triple[])[], mode: RaceMode, by: RaceBy, entry: number, top: number): number[] {
  const seen = new Set<number>()
  for (const frame of frames) for (const r of rankFrame(frame, mode, by, entry).slice(0, top)) seen.add(r.i)
  return [...seen].toSorted((a, b) => a - b)
}
