// Player-keyed tables, grouped once at build so each page gets its own rows.

/** Rows bucketed by attributed_player, in their original order. */
export function groupByPlayer<T extends { attributed_player: string }>(rows: readonly T[]): Map<string, T[]> {
  const m = new Map<string, T[]>()
  for (const r of rows) {
    const a = m.get(r.attributed_player)
    if (a) a.push(r)
    else m.set(r.attributed_player, [r])
  }
  return m
}
