// The game log as a real table. Eleven columns on a desk; on a phone the
// box line collapses to points/rebounds/assists and the wide columns go,
// so the table never scrolls sideways. Wins bold, losses gray.
import { fmtInt } from '../lib/format'
import type { GameLine } from '../lib/games'
import { weekLabel } from '../lib/weeks'
import { VerdictDelta } from './VerdictDelta'

export interface GamesTableProps {
  rows: readonly GameLine[]
  /** The visually hidden caption: what this table is. */
  caption: string
}

const PHASE: Record<string, string> = { pre_season: 'Pre', play_in: 'Play-in', playoffs: 'PO' }

const signed = (v: number): string => (v > 0 ? `+${v}` : String(v))

export function GamesTable({ rows, caption }: GamesTableProps) {
  return (
    <table className="gt">
      <caption className="visually-hidden">{caption}</caption>
      <thead>
        <tr>
          <th scope="col">Date</th>
          <th scope="col">Opp</th>
          <th scope="col">Result</th>
          <th scope="col" className="gt__wide">
            Min
          </th>
          <th scope="col" className="gt__wide">
            Pts
          </th>
          <th scope="col" className="gt__wide">
            Reb
          </th>
          <th scope="col" className="gt__wide">
            Ast
          </th>
          <th scope="col" className="gt__narrow">
            <abbr title="Points / rebounds / assists">P/R/A</abbr>
          </th>
          <th scope="col" className="gt__wide">
            <abbr title="Game Score">GmSc</abbr>
          </th>
          <th scope="col" className="gt__wide">
            +/−
          </th>
          <th scope="col" className="gt__verdict-h">
            Verdict
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map((g) => {
          const phase = PHASE[g.seasonType]
          return (
            <tr key={g.gameId} className={`gt__row gt__row--${g.win ? 'w' : 'l'}${g.dnp ? ' gt__row--dnp' : ''}`}>
              <th scope="row" className="gt__date mono">
                {weekLabel(g.date)}
                {phase && <span className="gt__phase">{phase}</span>}
              </th>
              <td className="gt__opp mono">
                {g.home === false ? '@' : 'vs'} {g.opponentAbbr}
              </td>
              <td className="gt__res mono">
                <span className="gt__wl">{g.win ? 'W' : 'L'}</span> {g.score}
              </td>
              <td className="gt__wide mono">{g.dnp ? 'DNP' : g.minutes}</td>
              <td className="gt__wide mono">{g.dnp ? '—' : g.pts}</td>
              <td className="gt__wide mono">{g.dnp ? '—' : g.reb}</td>
              <td className="gt__wide mono">{g.dnp ? '—' : g.ast}</td>
              <td className="gt__narrow mono">{g.dnp ? 'DNP' : `${g.pts}/${g.reb}/${g.ast}`}</td>
              <td className="gt__wide mono">{g.dnp ? '—' : g.gameScore.toFixed(1)}</td>
              <td className="gt__wide mono">{g.dnp ? '—' : signed(g.plusMinus)}</td>
              <td className="gt__verdict">
                <VerdictDelta delta={g.delta} n={g.counts?.total ?? 0} />
                {!g.talked && g.counts === null && <span className="visually-hidden">Nobody mentioned him: {fmtInt(0)} comments.</span>}
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}
