// Game nights against nights with no game: one dumbbell per phase on a
// shared raw axis, the regular season's level as a dashed rule, the
// no-game counts in the key. Every word is HTML; the track is a role=img.
import type { CSSProperties } from 'react'

import { fmtInt, fmtPct } from '../lib/format'
import { negRate } from '../lib/metrics'
import { fmtPoints, type GameNightRow } from '../lib/season'

export interface GameNightsProps {
  rows: readonly GameNightRow[]
  /** The regular season's negative share, every night. */
  level: number
}

export function GameNights({ rows, level }: GameNightsProps) {
  const values = [level, ...rows.flatMap((r) => [negRate(r.on), negRate(r.off)])]
  // Two points of air each side, on a scale stepped by two points.
  const lo = Math.max(0, Math.floor((Math.min(...values) - 0.01) * 50) / 50)
  const hi = Math.min(1, Math.ceil((Math.max(...values) + 0.01) * 50) / 50)
  const x = (v: number): number => (hi > lo ? ((v - lo) / (hi - lo)) * 100 : 50)
  return (
    <div className="gn">
      <div className="gn__row gn__row--head" aria-hidden="true">
        <span />
        <span className="gn__rule-label mono">
          <span style={{ left: `${x(level)}%` }}>{fmtPct(level, 1)}</span>
        </span>
      </div>
      {rows.map((r) => {
        const on = negRate(r.on)
        const off = negRate(r.off)
        const text = `${r.label}: ${fmtPct(on, 1)} negative on the ${fmtInt(r.onNights)} game nights, ${fmtPct(off, 1)} on the ${fmtInt(r.offNights)} nights with no game`
        return (
          <div key={r.key} className="gn__row">
            <b>{r.label}</b>
            <span className="gn__track" role="img" aria-label={text} style={{ '--rule': `${x(level)}%` } as CSSProperties}>
              <span className="gn__rule" />
              {r.off.total > 0 && r.on.total > 0 && <span className="gn__bar" style={{ left: `${Math.min(x(on), x(off))}%`, width: `${Math.abs(x(on) - x(off))}%` }} />}
              {r.off.total > 0 && (
                <>
                  <span className="gn__label gn__label--off mono" style={{ left: `${x(off)}%` }}>
                    {fmtPoints(off)}
                  </span>
                  <span className="gn__dot gn__dot--off" style={{ left: `${x(off)}%` }} />
                </>
              )}
              {r.on.total > 0 && (
                <>
                  <span className="gn__dot" style={{ left: `${x(on)}%` }} />
                  <span className="gn__label gn__label--on mono" style={{ left: `${x(on)}%` }}>
                    {fmtPoints(on)}
                  </span>
                </>
              )}
            </span>
          </div>
        )
      })}
      <ul className="key">
        <li>
          <i className="key__dot key__dot--full" /> Game nights
        </li>
        <li>
          <i className="key__dot key__dot--hollow" /> Nights with no game ({rows.map((r) => fmtInt(r.offNights)).join(' · ')})
        </li>
        <li>
          <i className="key__line key__line--rule" /> Regular season, all nights
        </li>
      </ul>
    </div>
  )
}
