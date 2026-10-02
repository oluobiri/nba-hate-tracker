// The court: a full court in the site's hairlines, the home logo gray at
// centre, both teams' shots at the feed's full-court positions as the game
// plays (his larger and ringed, his blocks dashed on the shot they ended),
// the five on the floor per team as chips, behind each basket the team that
// scores there, swapping at half. The overlay carries the cards.
import '../../styles/replay.css'
import type { ReactNode } from 'react'

import { type Ends, courtXY, COURT, lastName, type Moment } from '../../lib/replay'
import type { RecapPlaysRow } from '../../data/types.gen'

export interface CourtProps {
  plays: readonly RecapPlaysRow[]
  playU: readonly number[]
  cursor: number
  u: number
  focusId: number
  focusTeam: string
  away: string
  home: { abbr: string; logo: string }
  ends: Ends | null
  onFloor: ReadonlySet<number>
  /** Each team's players in box order. */
  order: ReadonlyMap<string, number[]>
  names: ReadonlyMap<number, string>
  /** Shot index → the index of the block that ended it. */
  blocked: ReadonlyMap<number, number>
  /** The moment holding the caption, its mark pulsed on the court. */
  hot: Moment | null
  children?: ReactNode
}

/** A shot stays bright this long after it goes up, in replay seconds. */
const FRESH = 2.2
const BASKET_LEFT = 52.5
const BASKET_RIGHT = COURT.w - BASKET_LEFT

function Half({ left }: { left: boolean }) {
  const bb = left ? 0 : COURT.w
  const s = left ? 1 : -1
  const bx = left ? BASKET_LEFT : BASKET_RIGHT
  const sweep = s > 0 ? 1 : 0
  return (
    <g>
      <rect className="court__ln" x={left ? 0 : COURT.w - 190} y={170} width={190} height={160} />
      <circle className="court__ln" cx={bb + s * 190} cy={250} r={60} />
      <path className="court__ln" d={`M${bx},210 A40,40 0 0 ${sweep} ${bx},290`} />
      <line className="court__ln" x1={bb} y1={30} x2={bb + s * 140} y2={30} />
      <line className="court__ln" x1={bb} y1={470} x2={bb + s * 140} y2={470} />
      <path className="court__ln" d={`M${bb + s * 140},30 A237.5,237.5 0 0 ${sweep} ${bb + s * 140},470`} />
      <line className="court__board" x1={bb + s * 40} y1={220} x2={bb + s * 40} y2={280} />
      <circle className="court__rim" cx={bx} cy={250} r={7.5} />
    </g>
  )
}

function Chips({ team, ids, onFloor, focusId, names }: { team: string; ids: readonly number[]; onFloor: ReadonlySet<number>; focusId: number; names: ReadonlyMap<number, string> }) {
  const on = ids.filter((id) => onFloor.has(id))
  const him = ids.includes(focusId)
  return (
    <div className="chips mono">
      <span className="chips__tm">{team}</span>
      {on.map((id) => (
        <span key={id} className={`chip${id === focusId ? ' chip--him' : ''}`}>
          {lastName(names.get(id) ?? String(id)).toUpperCase()}
        </span>
      ))}
      {him && !onFloor.has(focusId) && <span className="chip chip--bench">{lastName(names.get(focusId) ?? '').toUpperCase()} · BENCH</span>}
    </div>
  )
}

export function Court({ plays, playU, cursor, u, focusId, focusTeam, away, home, ends, onFloor, order, names, blocked, hot, children }: CourtProps) {
  const endLabel = (team: string, x: number, rot: number) => (
    <g transform={`translate(${x},250) rotate(${rot})`}>
      <text className={`court__end${team === focusTeam ? ' court__end--him' : ''}`} textAnchor="middle" y={12}>
        {team}
        <tspan className="court__end-sub" dx={10}>
          SCORES HERE
        </tspan>
      </text>
    </g>
  )
  const shots: ReactNode[] = []
  for (let i = 0; i <= cursor; i++) {
    const r = plays[i]!
    if (r.kind !== 'shot') continue
    const xy = courtXY(r)
    if (!xy) continue
    const mine = r.person_id === focusId
    const fresh = u - playU[i]! < FRESH
    const isHot = hot !== null && hot.mark === i
    const rad = mine ? 11 : 6.5
    const cls = `court__shot${r.team_tricode === focusTeam ? ' court__shot--ours' : ''}${mine ? ' court__shot--him' : ''}${r.made ? ' court__shot--made' : ''}`
    const blockIdx = blocked.get(i)
    const byHim = blockIdx !== undefined && plays[blockIdx]!.person_id === focusId
    shots.push(
      <g key={r.action_number} className={`${cls}${fresh ? ' court__shot--fresh' : ''}${isHot ? ' court__shot--hot' : ''}`} transform={`translate(${xy[0].toFixed(1)},${xy[1].toFixed(1)})`}>
        {isHot && <circle className="court__pulse" r={14} />}
        <circle className="court__mark" r={rad} />
        {mine && <circle className="court__ring" r={rad + 6} />}
        {byHim && <circle className="court__blocked" r={16} />}
        {isHot && (
          <text className="court__moment" y={-26} textAnchor="middle">
            {hot.label}
          </text>
        )}
      </g>,
    )
  }
  return (
    <div className="courtbox">
      <Chips team={away} ids={order.get(away) ?? []} onFloor={onFloor} focusId={focusId} names={names} />
      <svg className="court" viewBox={`-64 -6 ${COURT.w + 128} ${COURT.h + 12}`} role="img" aria-label="The court: every shot so far, his marked">
        <rect className="court__floor" x={0} y={0} width={COURT.w} height={COURT.h} />
        <rect className="court__ln" x={0} y={0} width={COURT.w} height={COURT.h} />
        <line className="court__ln" x1={COURT.w / 2} y1={0} x2={COURT.w / 2} y2={COURT.h} />
        <circle className="court__ln" cx={COURT.w / 2} cy={COURT.h / 2} r={60} />
        <image className="court__logo" href={home.logo} x={COURT.w / 2 - 40} y={COURT.h / 2 - 40} width={80} height={80} />
        <Half left />
        <Half left={false} />
        {ends && (
          <g>
            {endLabel(ends.left, -32, -90)}
            {endLabel(ends.right, COURT.w + 32, 90)}
          </g>
        )}
        <g>{shots}</g>
      </svg>
      <Chips team={home.abbr} ids={order.get(home.abbr) ?? []} onFloor={onFloor} focusId={focusId} names={names} />
      {children && <div className="court__overlay">{children}</div>}
    </div>
  )
}
