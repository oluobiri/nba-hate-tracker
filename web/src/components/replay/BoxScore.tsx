// The box score, both teams, live: a dot on whoever is on the floor, his
// row lit, team totals, and a ROOM column, net and a mix bar of the comments
// about each player so far, with n.
import '../../styles/replay.css'
import { fmtInt } from '../../lib/format'
import { fmtNet, netOf, netStyle } from '../../lib/net'
import { emptyLine, lastName, type PlayerLine, sumLines } from '../../lib/replay'
import type { Counts } from '../../lib/types'
import { SentimentBar } from '../SentimentBar'

export interface BoxTeam {
  abbr: string
  score: number
  /** In box order. */
  ids: readonly number[]
}

export interface BoxScoreProps {
  /** Away, then home. */
  teams: readonly [BoxTeam, BoxTeam]
  lines: ReadonlyMap<number, PlayerLine>
  names: ReadonlyMap<number, string>
  onFloor: ReadonlySet<number>
  focusId: number
  /** player_id → the comments about him so far. */
  room: ReadonlyMap<number, Counts>
}

const HEADS: { key: keyof PlayerLine | 'fg' | 'fg3' | 'ft'; label: string; wide?: boolean }[] = [
  { key: 'pts', label: 'PTS' },
  { key: 'reb', label: 'REB' },
  { key: 'ast', label: 'AST' },
  { key: 'stl', label: 'STL', wide: true },
  { key: 'blk', label: 'BLK', wide: true },
  { key: 'tov', label: 'TO', wide: true },
  { key: 'pf', label: 'PF', wide: true },
  { key: 'fg', label: 'FG', wide: true },
  { key: 'fg3', label: '3P', wide: true },
  { key: 'ft', label: 'FT', wide: true },
]

const cellOf = (l: PlayerLine, key: (typeof HEADS)[number]['key']): string => {
  if (key === 'fg') return `${l.fgm}-${l.fga}`
  if (key === 'fg3') return `${l.fg3m}-${l.fg3a}`
  if (key === 'ft') return `${l.ftm}-${l.fta}`
  return String(l[key])
}

function Team({ team, lines, names, onFloor, focusId, room }: { team: BoxTeam } & Omit<BoxScoreProps, 'teams'>) {
  const total = sumLines(team.ids.map((id) => lines.get(id) ?? emptyLine()))
  return (
    <div className="replay__panel">
      <table className="bx mono">
        <caption>
          <b>{team.abbr}</b> · {team.score}
        </caption>
        <thead>
          <tr>
            <th scope="col">Player</th>
            {HEADS.map((h) => (
              <th key={h.key} scope="col" className={h.wide ? 'bx__wide' : undefined}>
                {h.label}
              </th>
            ))}
            <th scope="col" title="Net sentiment of the comments about him so far">
              ROOM
            </th>
            <th scope="col">n</th>
          </tr>
        </thead>
        <tbody>
          {team.ids.map((id) => {
            const l = lines.get(id) ?? emptyLine()
            const r = room.get(id)
            const net = r ? netOf(r) : null
            const on = onFloor.has(id)
            return (
              <tr key={id} className={`${on ? 'bx__on' : ''}${id === focusId ? ' bx__him' : ''}`}>
                <th scope="row" className="bx__name">
                  <span className="bx__dot" aria-hidden="true" />
                  <span className="visually-hidden">{on ? 'On the floor: ' : ''}</span>
                  {names.get(id) ?? lastName(String(id))}
                </th>
                {HEADS.map((h) => (
                  <td key={h.key} className={h.wide ? 'bx__wide' : undefined}>
                    {cellOf(l, h.key)}
                  </td>
                ))}
                <td className="bx__room">
                  {r ? (
                    <span className="bx__rm">
                      <span style={netStyle(net)}>{fmtNet(net)}</span>
                      <SentimentBar counts={r} size="mini" subject={names.get(id)} />
                    </span>
                  ) : (
                    '—'
                  )}
                </td>
                <td className="bx__n">{r ? fmtInt(r.total) : ''}</td>
              </tr>
            )
          })}
          <tr className="bx__tot">
            <th scope="row">Team</th>
            {HEADS.map((h) => (
              <td key={h.key} className={h.wide ? 'bx__wide' : undefined}>
                {cellOf(total, h.key)}
              </td>
            ))}
            <td />
            <td />
          </tr>
        </tbody>
      </table>
    </div>
  )
}

export function BoxScore({ teams, ...rest }: BoxScoreProps) {
  return (
    <section className="box" aria-label="Box score">
      {teams.map((t) => (
        <Team key={t.abbr} team={t} {...rest} />
      ))}
    </section>
  )
}
