// Where he was talked about: one row per room at the floor, in the fixed
// order. Bar length is the room's share of his comments, the largest room
// the full track and the smallest kept at a floor width; the bar's split is
// the room's sentiment; the negative share, the positive share and n sit at
// the row's end. The harshest and the warmest room by net sentiment carry a
// tag. Static HTML, no island.
import { fmtInt, fmtPct } from '../lib/format'
import { negRate, neuRate, posRate } from '../lib/metrics'
import { fmtShareOf, type PlayerRooms as PlayerRoomsModel } from '../lib/rooms'
import { fmtPoints } from '../lib/season'

export interface PlayerRoomsProps {
  rooms: PlayerRoomsModel
}

// The narrowest bar, in % of the track.
const FLOOR_WIDTH = 3

export function PlayerRooms({ rooms }: PlayerRoomsProps) {
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
        // The visible text already says the room, its share, the tag and the two figures; the bar adds the neutral share.
        const text = `${fmtPct(c.rate)} negative, ${fmtPct(neuRate(c.counts))} neutral, ${fmtPct(posRate(c.counts))} positive`
        return (
          <div key={c.key} className={`pr__row${c.harshest ? ' pr__row--harshest' : ''}${c.warmest ? ' pr__row--warmest' : ''}`}>
            <span className="pr__name">
              <b>{c.label}</b>
              <span className="pr__share mono">{fmtShareOf(c.share)} of his comments</span>
              {c.harshest && <span className="pr__tag pr__tag--harshest mono">Harshest</span>}
              {c.warmest && <span className="pr__tag pr__tag--warmest mono">Warmest</span>}
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
