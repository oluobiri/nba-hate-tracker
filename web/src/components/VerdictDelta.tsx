// The room's verdict on one game against his usual: a signed figure and a
// short bar centred on his baseline. Heat when harsher, ice when kinder;
// the sign is printed, so colour never carries it alone. The figure is a Δ
// in the negative share, or in net on a page that speaks net.
import type { CSSProperties } from 'react'

import { fmtInt, fmtSigned } from '../lib/format'

export interface VerdictDeltaProps {
  /** This game's negative share minus his season share; null when the room was too quiet to judge. */
  delta: number | null
  /** Comments about him in the game's threads. */
  n: number
  /** How many points of delta the bar spans each way: a page choice, the same on every row. */
  span?: number
  /** What the Δ is in: the negative share (harsher when positive) or net (harsher when negative). */
  metric?: 'neg' | 'net'
  /** A row's inline figure, or a section's wide axis with the figure over the dot and the ends labeled. */
  size?: 'row' | 'hero'
  /** What zero stands for on the hero axis: "his season (+4)". */
  tickLabel?: string
}

const DEFAULT_SPAN = 0.4
/** The hero form sits beside net figures, which print a true minus. */
const minus = (v: string): string => v.replace('-', '−')

export function VerdictDelta({ delta, n, span = DEFAULT_SPAN, metric = 'neg', size = 'row', tickLabel }: VerdictDeltaProps) {
  const harsher = delta !== null && (metric === 'net' ? delta < 0 : delta > 0)
  const tone = delta === null || delta === 0 ? 'neu' : harsher ? 'neg' : 'pos'
  const pts = delta === null ? 0 : Math.round(Math.abs(delta) * 100)
  const against = metric === 'net' ? 'his season' : 'his usual'
  const text =
    delta === null
      ? `Too few comments to judge: ${fmtInt(n)}.`
      : pts === 0
        ? `At ${against}, from ${fmtInt(n)} comments.`
        : `${pts} ${pts === 1 ? 'point' : 'points'} ${harsher ? 'harsher' : 'kinder'} than ${against}, from ${fmtInt(n)} comments.`
  const half = Math.min(1, Math.abs(delta ?? 0) / span) * 50
  const fill = { '--vd-l': `${delta !== null && delta < 0 ? 50 - half : 50}%`, '--vd-w': `${half}%`, '--vd-x': `${delta !== null && delta < 0 ? 50 - half : 50 + half}%` } as CSSProperties
  if (size === 'hero') {
    return (
      <div className={`vd vd--hero vd--${tone}`} style={fill}>
        <span className="vd__figure mono" aria-hidden="true">
          {delta === null ? '—' : minus(fmtSigned(delta, 0))}
          <small>{delta === null ? '' : ' pts'}</small>
        </span>
        <span className="vd__track" aria-hidden="true">
          {delta !== null && pts > 0 && <span className="vd__fill" />}
          <span className="vd__base" />
          {delta !== null && <span className="vd__dot" />}
        </span>
        <span className="vd__ends mono" aria-hidden="true">
          <span>{minus(fmtSigned(-span, 0))}</span>
          <span className="vd__tick">{tickLabel ?? 'his usual'}</span>
          <span>{fmtSigned(span, 0)}</span>
        </span>
        <span className="visually-hidden">{text}</span>
      </div>
    )
  }
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
