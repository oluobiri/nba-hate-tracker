// The game log as a real table, read across its width on a desk: date,
// phase, opponent, result, the box line, Reddit's count for the game's
// threads against his loudest, then the room's verdict in net with its bar
// and the Recap chip inline where one is curated. On a phone the box line
// collapses to points/rebounds/assists, the wide columns go, the phase
// stacks under the date and the result under the opponent, so the table
// never scrolls sideways. Wins bold, losses gray.
import { fmtInt } from '../lib/format'
import type { GameLine } from '../lib/games'
import { weekLabel } from '../lib/weeks'
import { RecapChip } from './RecapChip'
import { VerdictDelta } from './VerdictDelta'

export interface GamesTableProps {
  rows: readonly GameLine[]
  /** The visually hidden caption: what this table is. */
  caption: string
  /** Reddit's count in his loudest game's threads: the comment bar's full width. */
  loudest: number
}

const signed = (v: number): string => (v > 0 ? `+${v}` : String(v))

export function GamesTable({ rows, caption, loudest }: GamesTableProps) {
  return (
    <table className="gt">
      <caption className="visually-hidden">{caption}</caption>
      <thead>
        <tr>
          <th scope="col" className="gt__date-h">
            Date
          </th>
          <th scope="col" className="gt__wide gt__left">
            Phase
          </th>
          <th scope="col" className="gt__opp-h">
            Opp
          </th>
          <th scope="col" className="gt__wide gt__left">
            Result
          </th>
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
          <th scope="col" className="gt__wide">
            FG
          </th>
          <th scope="col" className="gt__wide">
            3P
          </th>
          <th scope="col" className="gt__wide">
            <abbr title="Turnovers">TOV</abbr>
          </th>
          <th scope="col" className="gt__wide">
            +/−
          </th>
          <th scope="col" className="gt__narrow">
            <abbr title="Points / rebounds / assists">P/R/A</abbr>
          </th>
          <th scope="col" className="gt__wide">
            <abbr title="Every comment in the game's threads, as Reddit counts them">Comments</abbr>
          </th>
          <th scope="col" className="gt__verdict-h">
            Verdict
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map((g) => (
          <tr key={g.gameId} className={`gt__row gt__row--${g.win ? 'w' : 'l'}${g.dnp ? ' gt__row--dnp' : ''}`}>
            <th scope="row" className="gt__date mono">
              {weekLabel(g.date)}
              {g.phase && <span className="gt__phase gt__stack">{g.phase}</span>}
            </th>
            <td className="gt__wide gt__phase-col mono">{g.phase}</td>
            <td className="gt__opp mono">
              {g.home === false ? '@' : 'vs'} {g.opponentAbbr}
              <span className="gt__res gt__stack">
                <span className="gt__wl">{g.win ? 'W' : 'L'}</span> {g.score}
              </span>
            </td>
            <td className="gt__wide gt__res mono">
              <span className="gt__wl">{g.win ? 'W' : 'L'}</span> {g.score}
            </td>
            <td className="gt__wide mono">{g.dnp ? 'DNP' : g.minutes}</td>
            <td className="gt__wide mono">{g.dnp ? '—' : g.pts}</td>
            <td className="gt__wide mono">{g.dnp ? '—' : g.reb}</td>
            <td className="gt__wide mono">{g.dnp ? '—' : g.ast}</td>
            <td className="gt__wide mono">{g.dnp ? '—' : g.fg}</td>
            <td className="gt__wide mono">{g.dnp ? '—' : g.fg3}</td>
            <td className="gt__wide mono">{g.dnp ? '—' : g.tov}</td>
            <td className="gt__wide mono">{g.dnp ? '—' : signed(g.plusMinus)}</td>
            <td className="gt__narrow mono">{g.dnp ? 'DNP' : `${g.pts}/${g.reb}/${g.ast}`}</td>
            <td className="gt__wide gt__n mono">
              <span className="gt__bar" aria-hidden="true">
                {g.reddit !== null && loudest > 0 && <i style={{ width: `${(g.reddit / loudest) * 100}%` }} />}
              </span>
              {g.reddit === null ? '—' : fmtInt(g.reddit)}
            </td>
            <td className="gt__verdict">
              <span className="gt__vc">
                <VerdictDelta delta={g.delta} n={g.counts?.total ?? 0} />
                {g.recapHref && <RecapChip href={g.recapHref} />}
              </span>
              {!g.talked && g.counts === null && <span className="visually-hidden">Nobody mentioned him: {fmtInt(0)} comments.</span>}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
