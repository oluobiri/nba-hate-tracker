// How each room talked: one row per band with a three-colour share bar for
// the regular season and for the playoffs. Bar length is the room's share
// of the phase's comments, with a floor so the smallest room still shows
// its split; the negative and positive shares sit at the row's end.
import { fmtPct } from '../lib/format'
import { negRate, neuRate, posRate } from '../lib/metrics'
import { fmtPoints, fmtShare, type RoomRow } from '../lib/season'
import type { Counts } from '../lib/types'

export interface RoomRowsProps {
  rows: readonly RoomRow[]
  /** The largest share on either side, the full bar. */
  maxShare: number
}

// The narrowest bar, in % of the track.
const FLOOR_WIDTH = 3

function Bar({ label, counts, share, maxShare }: { label: string; counts: Counts; share: number; maxShare: number }) {
  const width = Math.max((maxShare ? share / maxShare : 0) * 100, FLOOR_WIDTH)
  return (
    <span className="rm__bar">
      <span className="mono">{label}</span>
      <i style={{ width: `${width}%` }}>
        {counts.total > 0 && (
          <>
            <b className="neg" style={{ width: `${negRate(counts) * 100}%` }} />
            <b className="neu" style={{ width: `${neuRate(counts) * 100}%` }} />
            <b className="pos" style={{ width: `${posRate(counts) * 100}%` }} />
          </>
        )}
      </i>
    </span>
  )
}

const figures = (c: Counts) =>
  c.total ? (
    <span>
      <span className="neg">{fmtPoints(negRate(c))}</span>
      <span className="pos">{fmtPoints(posRate(c))}</span>
    </span>
  ) : (
    <span>
      <span>—</span>
      <span>—</span>
    </span>
  )

export function RoomRows({ rows, maxShare }: RoomRowsProps) {
  return (
    <div className="rm">
      <div className="rm__head mono" aria-hidden="true">
        <span />
        <span />
        <span className="rm__fig-head">
          <span>% neg</span>
          <span>% pos</span>
        </span>
      </div>
      {rows.map((r) => {
        const text = `${r.label}: ${fmtPct(r.shareReg, 1)} of the regular season's comments at ${r.reg.total ? `${fmtPct(negRate(r.reg), 1)} negative` : 'no comments'}, ${fmtPct(r.sharePo, 1)} of the playoffs' at ${r.po.total ? `${fmtPct(negRate(r.po), 1)} negative` : 'no comments'}`
        return (
          <div key={r.key} className="rm__row">
            <span className="rm__name">
              <b>{r.label}</b>
              <span className="mono">
                {fmtShare(r.shareReg)} → {fmtShare(r.sharePo)} of comments
              </span>
            </span>
            <span className="rm__bars" role="img" aria-label={text}>
              <Bar label="RS" counts={r.reg} share={r.shareReg} maxShare={maxShare} />
              <Bar label="PO" counts={r.po} share={r.sharePo} maxShare={maxShare} />
            </span>
            <span className="rm__fig mono">
              {figures(r.reg)}
              {figures(r.po)}
            </span>
          </div>
        )
      })}
    </div>
  )
}
