// Tables grouped once at build so each page gets its own rows.

/** Rows bucketed by `key`, buckets and rows in their original order. */
export function groupBy<T>(rows: readonly T[], key: (row: T) => string): Map<string, T[]> {
  const m = new Map<string, T[]>()
  for (const r of rows) {
    const k = key(r)
    const a = m.get(k)
    if (a) a.push(r)
    else m.set(k, [r])
  }
  return m
}

/** Rows bucketed by attributed_player. */
export const groupByPlayer = <T extends { attributed_player: string }>(rows: readonly T[]): Map<string, T[]> =>
  groupBy(rows, (r) => r.attributed_player)
