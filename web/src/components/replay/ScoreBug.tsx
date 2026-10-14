// The score bug: the anchor of the stage, sticky at every width. Away and
// home with the leader in bone and the trailer in gray (never a hue), the
// clock, the line score, his live line and floor state, play and speed.
import '../../styles/replay.css'
import { type ClockReading, type Speed, SPEEDS } from '../../lib/clock'
import { fmtInt } from '../../lib/format'
import { type PeriodPoints, type PlayerLine } from '../../lib/replay'

export interface BugTeam {
  abbr: string
  logo: string
}

export interface ScoreBugProps {
  away: BugTeam
  home: BugTeam
  score: { away: number; home: number }
  clock: ClockReading
  line: readonly PeriodPoints[]
  his: { name: string; short: string; line: PlayerLine; onFloor: boolean }
  playing: boolean
  speed: Speed
  onToggle: () => void
  onSpeed: (s: Speed) => void
}

const cell = (v: number | null): string => (v === null ? '–' : String(v))

export function ScoreBug({ away, home, score, clock, line, his, playing, speed, onToggle, onSpeed }: ScoreBugProps) {
  const awayLeads = score.away >= score.home
  const homeLeads = score.home >= score.away
  const l = his.line
  return (
    <div className="bug" data-testid="bug">
      <div className="bug__score">
        <span className="bug__team mono">
          <img className="bug__logo" src={away.logo} alt="" width="30" height="30" decoding="async" />
          {away.abbr}
        </span>
        <span className={`bug__pts${awayLeads ? ' bug__pts--lead' : ''}`}>{score.away}</span>
        <span className="bug__clock">
          <span className="bug__period mono">{clock.label}</span>
          <span className="bug__time mono" data-testid="bug-time">
            {clock.time}
          </span>
        </span>
        <span className={`bug__pts${homeLeads ? ' bug__pts--lead' : ''}`}>{score.home}</span>
        <span className="bug__team mono">
          {home.abbr}
          <img className="bug__logo" src={home.logo} alt="" width="30" height="30" decoding="async" />
        </span>
      </div>
      <table className="bug__line mono">
        <thead>
          <tr>
            <th scope="col">
              <span className="visually-hidden">Team</span>
            </th>
            {line.map((p) => (
              <th key={p.period} scope="col" className={p.period === clock.period ? 'bug__cur' : undefined}>
                {p.label}
              </th>
            ))}
            <th scope="col" className="bug__tot">
              T
            </th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <th scope="row">{away.abbr}</th>
            {line.map((p) => (
              <td key={p.period} className={p.period === clock.period ? 'bug__cur' : undefined}>
                {cell(p.away)}
              </td>
            ))}
            <td className="bug__tot">{score.away}</td>
          </tr>
          <tr>
            <th scope="row">{home.abbr}</th>
            {line.map((p) => (
              <td key={p.period} className={p.period === clock.period ? 'bug__cur' : undefined}>
                {cell(p.home)}
              </td>
            ))}
            <td className="bug__tot">{score.home}</td>
          </tr>
        </tbody>
      </table>
      <div className="bug__his mono">
        <b className="bug__name">{his.name}</b>
        <b className="bug__name bug__name--short">{his.short.toUpperCase()}</b>
        <span>
          {fmtInt(l.pts)} pts · {fmtInt(l.reb)} reb · {fmtInt(l.ast)} ast · {fmtInt(l.blk)} blk
          <span className="bug__fg">
            {' '}
            · {l.fgm}-{l.fga} FG
          </span>
        </span>
        <span className={`bug__floor${his.onFloor ? ' bug__floor--on' : ''}`}>{his.onFloor ? '● on floor' : '○ bench'}</span>
      </div>
      <div className="bug__ctl">
        <button type="button" className="btn bug__play" onClick={onToggle} aria-label={playing ? 'Pause' : 'Play'} data-testid="bug-play">
          {playing ? '❚❚' : '▶'}
        </button>
        <span className="bug__speed" role="group" aria-label="Speed">
          {SPEEDS.map((s) => (
            <button key={s} type="button" className="btn bug__sp" aria-pressed={speed === s} onClick={() => onSpeed(s)}>
              {s}×
            </button>
          ))}
        </span>
      </div>
    </div>
  )
}
