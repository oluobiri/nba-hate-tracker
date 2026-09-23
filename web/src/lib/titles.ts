// Weekly titles, computed from player_temporal rows at build. The Belt goes
// to the highest negative rate among rows at or above the floor that week;
// the Flowers to the highest positive rate under the same floor. Ties fall
// to the larger n. A week with no qualifier has no holder.
import { negRate, posRate } from './metrics'
import type { Counts } from './types'

export type TitleMetric = 'neg' | 'pos'

export interface WeekRow extends Counts {
  /** ISO datetime string from the loader; only the date part is read. */
  week: string
}

export interface Holder<T extends WeekRow> {
  week: string
  row: T
  rate: number
}

export interface Reign<T extends WeekRow> {
  from: string
  to: string
  weeks: number
  holders: Holder<T>[]
}

const RATE: Record<TitleMetric, (c: Counts) => number> = { neg: negRate, pos: posRate }

const WEEK_MS = 7 * 24 * 60 * 60 * 1000
const dayOf = (week: string): number => Date.parse(`${week.slice(0, 10)}T00:00:00Z`)

/** Holder per week, ascending by week; weeks with no row at the floor are absent. */
export function weeklyHolders<T extends WeekRow>(rows: readonly T[], metric: TitleMetric, floor: number): Holder<T>[] {
  const rate = RATE[metric]
  const best = new Map<string, Holder<T>>()
  for (const row of rows) {
    if (row.total < floor) continue
    const r = rate(row)
    const cur = best.get(row.week)
    if (!cur || r > cur.rate || (r === cur.rate && row.total > cur.row.total)) best.set(row.week, { week: row.week, row, rate: r })
  }
  return [...best.values()].toSorted((a, b) => dayOf(a.week) - dayOf(b.week))
}

/** Consecutive weeks held by one player (by `key`), merged. A week without a holder ends a reign. */
export function reigns<T extends WeekRow>(holders: readonly Holder<T>[], key: (row: T) => string): Reign<T>[] {
  const out: Reign<T>[] = []
  for (const h of holders) {
    const last = out.at(-1)
    const prev = last?.holders.at(-1)
    if (last && prev && key(prev.row) === key(h.row) && dayOf(h.week) - dayOf(prev.week) === WEEK_MS) {
      last.to = h.week
      last.weeks += 1
      last.holders.push(h)
    } else out.push({ from: h.week, to: h.week, weeks: 1, holders: [h] })
  }
  return out
}
