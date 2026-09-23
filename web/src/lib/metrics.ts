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
