// Count-based re-aggregation only. A rate is sum(part) / sum(total),
// never an average of rates; the manifest's rules.metrics spells the
// same formulas. Thresholds arrive as arguments, read from the manifest.
import type { Counts, Lens } from './types'

export const negRate = (c: Counts): number => (c.total ? c.neg / c.total : 0)
export const posRate = (c: Counts): number => (c.total ? c.pos / c.total : 0)
export const neuRate = (c: Counts): number => (c.total ? c.neu / c.total : 0)
export const netSentiment = (c: Counts): number => posRate(c) - negRate(c)
// Polarization is the non-neutral share: (neg + pos) / total.
export const polarization = (c: Counts): number => (c.total ? (c.neg + c.pos) / c.total : 0)

export const sumCounts = (rows: readonly Counts[]): Counts =>
  rows.reduce(
    (a, r) => ({ neg: a.neg + r.neg, neu: a.neu + r.neu, pos: a.pos + r.pos, total: a.total + r.total }),
    { neg: 0, neu: 0, pos: 0, total: 0 },
  )

export function countsOf(row: {
  neg_count: number
  neu_count: number
  pos_count: number
  comment_count: number
}): Counts {
  return { neg: row.neg_count, neu: row.neu_count, pos: row.pos_count, total: row.comment_count }
}

export interface LensMeta {
  label: string
  short: string
  unit: string
  hero: string
  value: (c: Counts) => number
  kind: 'rate' | 'count'
}

export const LENS_META: Record<Lens, LensMeta> = {
  neg: { label: 'Most hated', short: 'NEG%', unit: '% of comments negative', hero: 'most hated', value: negRate, kind: 'rate' },
  pos: { label: 'Most loved', short: 'POS%', unit: '% of comments positive', hero: 'most loved', value: posRate, kind: 'rate' },
  volume: { label: 'Volume', short: 'N', unit: 'comments attributed', hero: 'most discussed', value: (c) => c.total, kind: 'count' },
  polar: { label: 'Polarization', short: 'POLAR', unit: '% of comments that take a side', hero: 'most argued about', value: polarization, kind: 'rate' },
}

export interface Ranked<T extends Counts> {
  row: T
  value: number
  // null below the threshold: the row keeps its sort position, unranked.
  rank: number | null
}

/** Sort by the lens value (ties broken by volume) and number the rows at or above `threshold` comments. */
export function rankBy<T extends Counts>(rows: readonly T[], lens: Lens, threshold: number): Ranked<T>[] {
  const value = LENS_META[lens].value
  const sorted = rows
    .map((row) => ({ row, value: value(row) }))
    .toSorted((a, b) => b.value - a.value || b.row.total - a.row.total)
  let r = 0
  return sorted.map((x) => ({ ...x, rank: x.row.total >= threshold ? ++r : null }))
}

/** The ranked neighbours of one row: the row a place above and a place below, over ranked rows only. */
export function neighbours<T extends Counts>(
  ranked: readonly Ranked<T>[],
  key: (row: T) => string,
  k: string,
): { prev: Ranked<T> | null; next: Ranked<T> | null } {
  const rows = ranked.filter((r) => r.rank !== null)
  const i = rows.findIndex((r) => key(r.row) === k)
  if (i < 0) return { prev: null, next: null }
  return { prev: rows[i - 1] ?? null, next: rows[i + 1] ?? null }
}

/**
 * Trailing window over a spined series: entry i sums the counts of rows
 * i-k+1..i. A null row is a week with no comments. Windows short of k at the
 * start still sum what they have; a window with no comments at all is null.
 */
export function rollingCounts(rows: readonly (Counts | null)[], k: number): (Counts | null)[] {
  return rows.map((_, i) => {
    const window = rows.slice(Math.max(0, i - k + 1), i + 1).filter((r): r is Counts => r !== null)
    const c = sumCounts(window)
    return c.total ? c : null
  })
}

/** A rate over each trailing window, null where the window has fewer than `floor` comments. */
export function rollingRate(
  rows: readonly (Counts | null)[],
  k: number,
  rate: (c: Counts) => number,
  floor: number,
): (number | null)[] {
  return rollingCounts(rows, k).map((c) => (c && c.total >= floor ? rate(c) : null))
}

/** Pearson correlation; null with fewer than three points or no variance on either side. */
export function pearson(xs: readonly number[], ys: readonly number[]): number | null {
  const n = Math.min(xs.length, ys.length)
  if (n < 3) return null
  const mean = (v: readonly number[]) => v.slice(0, n).reduce((a, b) => a + b, 0) / n
  const mx = mean(xs)
  const my = mean(ys)
  let sxy = 0
  let sxx = 0
  let syy = 0
  for (let i = 0; i < n; i++) {
    const dx = xs[i]! - mx
    const dy = ys[i]! - my
    sxy += dx * dy
    sxx += dx * dx
    syy += dy * dy
  }
  if (!sxx || !syy) return null
  return sxy / Math.sqrt(sxx * syy)
}

export interface BoxLine {
  pts: number
  fgm: number
  fga: number
  ftm: number
  fta: number
  oreb: number
  dreb: number
  stl: number
  ast: number
  blk: number
  pf: number
  tov: number
}

/** Hollinger's Game Score: one number for a night's box line. */
export function gameScore(g: BoxLine): number {
  return (
    g.pts +
    0.4 * g.fgm -
    0.7 * g.fga -
    0.4 * (g.fta - g.ftm) +
    0.7 * g.oreb +
    0.3 * g.dreb +
    g.stl +
    0.7 * g.ast +
    0.7 * g.blk -
    0.4 * g.pf -
    g.tov
  )
}

/** Rank movement per row between two views of the same lens: official rank minus current rank, null when either is unranked. */
export function rankDeltas<T extends Counts>(
  current: readonly Ranked<T>[],
  official: readonly Ranked<T>[],
  key: (row: T) => string,
): Map<string, number | null> {
  const was = new Map(official.map((r) => [key(r.row), r.rank]))
  return new Map(
    current.map((r) => {
      const before = was.get(key(r.row)) ?? null
      return [key(r.row), r.rank === null || before === null ? null : before - r.rank]
    }),
  )
}
