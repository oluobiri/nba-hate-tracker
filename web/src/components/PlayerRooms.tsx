// Where he was talked about: one row per room at the floor, in the fixed
// order. Bar length is the room's share of his comments, the largest room
// the full track and the smallest kept at a floor width; the bar's split is
// the room's sentiment; the negative share, the positive share and n sit at
// the row's end. The harshest room carries the tag. Static HTML, no island.
import { fmtInt, fmtPct } from '../lib/format'
import { negRate, neuRate, posRate } from '../lib/metrics'
import { fmtShareOf, type PlayerRooms as PlayerRoomsModel } from '../lib/rooms'
import { fmtPoints } from '../lib/season'

export interface PlayerRoomsProps {
  /** His name, for the bars' spoken text. */
  name: string
  rooms: PlayerRoomsModel
}

// The narrowest bar, in % of the track.
const FLOOR_WIDTH = 3

export function PlayerRooms({ name, rooms }: PlayerRoomsProps) {
  const { drawn, maxShare } = rooms
  return (
    <div className="pr">
      <div className="pr__head mono" aria-hidden="true">
        <span />
        <span className="pr__spacer" />
        <span className="pr__figs">
          <span>% neg</span>
          <span>% pos</span>
          <span>n</span>
        </span>
      </div>
      {drawn.map((c) => {
        const width = Math.max((maxShare ? c.share / maxShare : 0) * 100, FLOOR_WIDTH)
        const text = `${c.label}: ${fmtPct(c.rate)} negative, ${fmtPct(neuRate(c.counts))} neutral, ${fmtPct(posRate(c.counts))} positive of ${fmtInt(c.counts.total)} comments about ${name}, ${fmtShareOf(c.share)} of his comments${c.harshest ? '; his harshest room' : ''}`
        return (
          <div key={c.key} className={`pr__row${c.harshest ? ' pr__row--harshest' : ''}`}>
            <span className="pr__name">
              <b>{c.label}</b>
              <span className="pr__share mono">{fmtShareOf(c.share)} of his comments</span>
              {c.harshest && <span className="pr__tag mono">Harshest</span>}
            </span>
            <span className="pr__bar" role="img" aria-label={text}>
              <i style={{ width: `${width}%` }}>
                <b className="neg" style={{ width: `${negRate(c.counts) * 100}%` }} />
                <b className="neu" style={{ width: `${neuRate(c.counts) * 100}%` }} />
                <b className="pos" style={{ width: `${posRate(c.counts) * 100}%` }} />
              </i>
            </span>
            <span className="pr__figs mono">
              <span className="pr__neg">{fmtPoints(c.rate)}</span>
              <span className="pr__pos">{fmtPoints(posRate(c.counts))}</span>
              <span className="pr__n">{fmtInt(c.counts.total)}</span>
            </span>
          </div>
        )
      })}
    </div>
  )
}
