// The replay's reading of a recap file: the room (his comments on the
// timeline), the floor from the stints, the box lines from the plays, and his
// moments. Every function is pure and reads rows the document frames give.
import type { Columnar, RecapDocument, RecapRows } from '../data/types.gen'

/** Column arrays as rows, once, when the file arrives. */
export function toRows<T extends object>(frame: Columnar<T>): T[] {
  const cols = Object.keys(frame) as (keyof T)[]
  const n = cols.length ? (frame[cols[0]!] as unknown[]).length : 0
  const out: T[] = []
  for (let i = 0; i < n; i++) {
    const row = {} as T
    for (const c of cols) row[c] = (frame[c] as T[keyof T][])[i]!
    out.push(row)
  }
  return out
}

export const recapRows = (doc: RecapDocument): RecapRows => ({
  periods: toRows(doc.frames.periods),
  threads: toRows(doc.frames.threads),
  stints: toRows(doc.frames.stints),
  plays: toRows(doc.frames.plays),
  comments: toRows(doc.frames.comments),
})
