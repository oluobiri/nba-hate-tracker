// The room's verdict on one game against his season: a signed net figure
// and a short bar centred on his season's net. Heat when harsher, ice when
// warmer; the sign is printed, so colour never carries it alone. A row in
// the games table and the recap page's hero share it.
import type { CSSProperties } from 'react'

import { fmtInt } from '../lib/format'
import { fmtNet } from '../lib/net'

export interface VerdictDeltaProps {
  /** This game's net minus his season net; null when the room was too quiet to judge. */
  delta: number | null
  /** Comments about him in the game's threads. */
  n: number
  /** How many points of net the bar spans each way: the same on every row. */
  span?: number
  /** A row's inline figure, or a section's wide axis with the figure over the dot and the ends labeled. */
  size?: 'row' | 'hero'
  /** What zero stands for on the hero axis: "his season (+4)". */
  tickLabel?: string
}

/** The bar's reach each way, in net points: a page choice shared by every verdict. */
const NET_SPAN = 0.6

export function VerdictDelta({ delta, n, span = NET_SPAN, size = 'row', tickLabel }: VerdictDeltaProps) {
  const pts = delta === null ? 0 : Math.round(Math.abs(delta) * 100)
  const harsher = delta !== null && delta < 0
  const tone = delta === null || pts === 0 ? 'neu' : harsher ? 'neg' : 'pos'
  const text =
    delta === null
      ? `Too few comments to judge: ${fmtInt(n)}.`
      : pts === 0
        ? `At his season, from ${fmtInt(n)} comments.`
        : `${pts} ${pts === 1 ? 'point' : 'points'} ${harsher ? 'harsher' : 'warmer'} than his season, from ${fmtInt(n)} comments.`
  const half = Math.min(1, Math.abs(delta ?? 0) / span) * 50
  const fill = { '--vd-l': `${harsher ? 50 - half : 50}%`, '--vd-w': `${half}%`, '--vd-x': `${harsher ? 50 - half : 50 + half}%` } as CSSProperties
  if (size === 'hero') {
    return (
      <div className={`vd vd--hero vd--${tone}`} style={fill}>
        <span className="vd__figure mono" aria-hidden="true">
          {fmtNet(delta)}
          <small>{delta === null ? '' : ' pts'}</small>
        </span>
        <span className="vd__track" aria-hidden="true">
          {pts > 0 && <span className="vd__fill" />}
          <span className="vd__base" />
          {delta !== null && <span className="vd__dot" />}
        </span>
        <span className="vd__ends mono" aria-hidden="true">
          <span>{fmtNet(-span)}</span>
          <span className="vd__tick">{tickLabel ?? 'his season'}</span>
          <span>{fmtNet(span)}</span>
        </span>
        <span className="visually-hidden">{text}</span>
      </div>
    )
  }
  return (
    <span className={`vd vd--${tone}`}>
      <span className="vd__figure mono" aria-hidden="true">
        {fmtNet(delta)}
      </span>
      <span className="vd__track" aria-hidden="true">
        <span className="vd__base" />
        {pts > 0 && <span className="vd__fill" style={fill} />}
      </span>
      <span className="vd__n mono" aria-hidden="true">
        n={fmtInt(n)}
      </span>
      <span className="visually-hidden">{text}</span>
    </span>
  )
}
