// The room's verdict on one game against his usual: a signed figure and a
// short bar centred on his baseline. Heat when harsher, ice when kinder;
// the sign is printed, so colour never carries it alone.
import type { CSSProperties } from 'react'

import { fmtInt, fmtSigned } from '../lib/format'

export interface VerdictDeltaProps {
  /** This game's negative share minus his season share; null when the room was too quiet to judge. */
  delta: number | null
  /** Comments about him in the game's threads. */
  n: number
  /** How many points of delta the bar spans each way: a page choice, the same on every row. */
  span?: number
}

const DEFAULT_SPAN = 0.4

export function VerdictDelta({ delta, n, span = DEFAULT_SPAN }: VerdictDeltaProps) {
  const tone = delta === null || delta === 0 ? 'neu' : delta > 0 ? 'neg' : 'pos'
  const pts = delta === null ? 0 : Math.round(Math.abs(delta) * 100)
  const text =
    delta === null
      ? `Too few comments to judge: ${fmtInt(n)}.`
      : pts === 0
        ? `At his usual, from ${fmtInt(n)} comments.`
        : `${pts} points ${delta > 0 ? 'harsher' : 'kinder'} than his usual, from ${fmtInt(n)} comments.`
  const half = Math.min(1, Math.abs(delta ?? 0) / span) * 50
  const fill = { '--vd-l': `${delta !== null && delta < 0 ? 50 - half : 50}%`, '--vd-w': `${half}%` } as CSSProperties
  return (
    <span className={`vd vd--${tone}`}>
      <span className="vd__figure mono" aria-hidden="true">
        {delta === null ? '—' : fmtSigned(delta, 0)}
      </span>
      <span className="vd__track" aria-hidden="true">
        <span className="vd__base" />
        {delta !== null && pts > 0 && <span className="vd__fill" style={fill} />}
      </span>
      <span className="vd__n mono" aria-hidden="true">
        n={fmtInt(n)}
      </span>
      <span className="visually-hidden">{text}</span>
    </span>
  )
}
