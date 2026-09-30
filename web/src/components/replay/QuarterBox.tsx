// The box score by period, filling as the game plays: both teams' points
// from the running score, and a third row for the room on him, the same
// mini bar and n the index's period strip uses. A table, since it is one.
import { fmtInt } from '../../lib/format'
import type { PeriodCell } from '../../lib/recaps'
import type { QuarterRow } from '../../lib/replay'
import { SentimentBar } from '../SentimentBar'

export interface QuarterBoxProps {
  rows: QuarterRow[]
  /** The room's row, one cell per period in the same order. */
  room: PeriodCell[]
  away: string
  home: string
  his: 'away' | 'home'
  /** His name, for the caption and the room row. */
  subject: string
}

const pts = (v: number | null): string => (v === null ? '—' : fmtInt(v))
const sum = (vs: (number | null)[]): number | null => (vs.some((v) => v !== null) ? vs.reduce<number>((n, v) => n + (v ?? 0), 0) : null)

export function QuarterBox({ rows: given, room, away, home, his, subject }: QuarterBoxProps) {
  // Before the file arrives the periods are the registry's, with no points.
  const rows: QuarterRow[] = given.length ? given : room.map((c) => ({ period: c.key, label: c.label, away: null, home: null, running: false }))
  const cells = new Map(room.map((c) => [c.key, c]))
  const total = room.reduce((n, c) => n + c.counts.total, 0)
  const teamRow = (side: 'away' | 'home', abbr: string) => (
    <tr className={side === his ? 'qb__team qb__team--his' : 'qb__team'}>
      <th scope="row">{abbr}</th>
      {rows.map((r) => (
        <td key={r.period} className={`mono${r.running ? ' qb__cell--live' : ''}`}>
          {pts(r[side])}
        </td>
      ))}
      <td className="mono qb__total">{pts(sum(rows.map((r) => r[side])))}</td>
    </tr>
  )
  return (
    <table className="qb">
      <caption className="visually-hidden">Points by quarter, and the room on {subject}</caption>
      <thead>
        <tr>
          <th scope="col">
            <span className="visually-hidden">Row</span>
          </th>
          {rows.map((r) => (
            <th key={r.period} scope="col" className={`mono${r.running ? ' qb__cell--live' : ''}`}>
              {r.label}
            </th>
          ))}
          <th scope="col" className="mono qb__total">
            T
          </th>
        </tr>
      </thead>
      <tbody>
        {teamRow('away', away)}
        {teamRow('home', home)}
        <tr className="qb__room">
          <th scope="row">The room on him</th>
          {rows.map((r) => {
            const c = cells.get(r.period)
            return (
              <td key={r.period} className={r.running ? 'qb__cell--live' : undefined}>
                {c && c.counts.total > 0 ? (
                  <>
                    <SentimentBar counts={c.counts} size="mini" subject={`${subject} in ${c.label}`} />
                    <span className="qb__n mono">{fmtInt(c.counts.total)}</span>
                  </>
                ) : (
                  <span className="qb__n mono">—</span>
                )}
              </td>
            )
          })}
          <td className="mono qb__total qb__n">{total ? fmtInt(total) : '—'}</td>
        </tr>
      </tbody>
    </table>
  )
}
