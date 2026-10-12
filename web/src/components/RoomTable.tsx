// Every room over the whole season, the biggest first, with the regular
// season → playoffs column filled for every room. No net column, and not
// sortable: nine rows.
import { fmtInt, fmtPct } from '../lib/format'
import { negRate, neuRate, posRate } from '../lib/metrics'
import { fmtPoints, type RoomSplitRow } from '../lib/season'

export interface RoomTableProps {
  rows: readonly RoomSplitRow[]
  /** The visually hidden caption. */
  caption: string
}

export function RoomTable({ rows, caption }: RoomTableProps) {
  return (
    <div className="rt">
      <table>
        <caption className="visually-hidden">{caption}</caption>
        <thead>
          <tr>
            <th scope="col">Room</th>
            <th scope="col">Comments</th>
            <th scope="col">Share</th>
            <th scope="col">% neg</th>
            <th scope="col">% neu</th>
            <th scope="col">% pos</th>
            <th scope="col">% neg, RS → PO</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key}>
              <th scope="row">{r.label}</th>
              <td>{fmtInt(r.whole.total)}</td>
              <td>{fmtPct(r.shareWhole, 1)}</td>
              <td className="neg">{fmtPoints(negRate(r.whole))}</td>
              <td>{fmtPoints(neuRate(r.whole))}</td>
              <td className="pos">{fmtPoints(posRate(r.whole))}</td>
              <td>
                {fmtPoints(r.rateReg)} → {fmtPoints(r.ratePo)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
