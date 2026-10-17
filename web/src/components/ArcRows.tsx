// Season arcs: a dumbbell per player on one net-sentiment axis, the early
// dot hollow and the late dot filled, both coloured by their net on the
// player rule; the timing phrase under the name; the shares beside the
// figures, since net alone can hide a split room. The whole row is the link.
import type { CSSProperties } from 'react'

import { fmtInt } from '../lib/format'
import { negRate, posRate } from '../lib/metrics'
import { fmtNet, type PlayerNetRange, playerNetColor } from '../lib/net'
import { type Arc, ARC_WEEKS, arcText } from '../lib/season'
import { weekLabel } from '../lib/weeks'

export interface ArcDomain {
  lo: number
  hi: number
  ticks: readonly number[]
}

export interface ArcRowsProps {
  /** "Rose the most" / "Fell the most". */
  heading: string
  /** Ice for the risers, heat for the fallers: the heading's gradient. */
  tone: 'pos' | 'neg'
  arcs: readonly Arc[]
  domain: ArcDomain
  /** The season's player extremes, the colour scale for the dots and figures. */
  netRange: PlayerNetRange
}

const playerHref = (slug: string): string => `/player/${slug}/`
const pts = (v: number): string => fmtInt(Math.round(v * 100))

function Ticks({ domain, phone }: { domain: ArcDomain; phone?: boolean }) {
  const x = (v: number): number => ((v - domain.lo) / (domain.hi - domain.lo)) * 100
  return (
    <div className={`arc__ticks mono${phone ? ' arc__ticks--phone' : ''}`}>
      {domain.ticks.map((t) => (
        <span key={t} className={t === 0 ? 'arc__zero-tick' : undefined} style={{ left: `${x(t)}%` }}>
          {t === 0 ? '0' : fmtNet(t)}
        </span>
      ))}
    </div>
  )
}

export function ArcKey() {
  return (
    <ul className="key">
      <li>
        <i className="key__dot key__dot--early" /> First {fmtInt(ARC_WEEKS)} regular-season weeks
      </li>
      <li>
        <i className="key__dot key__dot--late" /> Last {fmtInt(ARC_WEEKS)} weeks he played, coloured by net sentiment
      </li>
    </ul>
  )
}

export function ArcRows({ heading, tone, arcs, domain, netRange }: ArcRowsProps) {
  const x = (v: number): number => ((v - domain.lo) / (domain.hi - domain.lo)) * 100
  const c = (v: number): string => playerNetColor(v, netRange)
  return (
    <div className={`arc arc--${tone}`}>
      <h3>{heading}</h3>
      <div className="arc__head mono" aria-hidden="true">
        <span>Player · when it moved</span>
        <Ticks domain={domain} />
        <span className="arc__head-right">Net · % neg · % pos</span>
      </div>
      <Ticks domain={domain} phone />
      {arcs.map((a) => (
        <a key={a.name} className="arc__row" href={playerHref(a.slug)}>
          <span className="arc__name">
            <b>{a.name}</b>
            <span className="mono">{[a.team, a.ended, `to ${weekLabel(a.to)}`].filter(Boolean).join(' · ')}</span>
            <span className="arc__when mono">{a.timing}</span>
          </span>
          <span className="arc__track" role="img" aria-label={arcText(a)}>
            <span className="arc__zero" style={{ left: `${x(0)}%` }} />
            <span className="arc__line" style={{ left: `${Math.min(x(a.early.net), x(a.late.net))}%`, width: `${Math.abs(x(a.late.net) - x(a.early.net))}%` }} />
            <span className="arc__dot arc__dot--early" style={{ left: `${x(a.early.net)}%`, '--c': c(a.early.net) } as CSSProperties} />
            <span className="arc__dot arc__dot--late" style={{ left: `${x(a.late.net)}%`, '--c': c(a.late.net) } as CSSProperties} />
          </span>
          <span className="arc__fig mono">
            <span>
              <span style={{ color: c(a.early.net) }}>{fmtNet(a.early.net)}</span> → <b style={{ color: c(a.late.net) }}>{fmtNet(a.late.net)}</b>
            </span>
            <small>
              <span className="neg">
                {pts(negRate(a.early.counts))} → {pts(negRate(a.late.counts))}
              </span>{' '}
              ·{' '}
              <span className="pos">
                {pts(posRate(a.early.counts))} → {pts(posRate(a.late.counts))}
              </span>
            </small>
          </span>
        </a>
      ))}
    </div>
  )
}

/** The flat names in one quiet line. */
export function ArcFlat({ arcs }: { arcs: readonly Arc[] }) {
  if (arcs.length === 0) return null
  return (
    <p className="arc__flat">
      Barely moved:{' '}
      {arcs.map((a, i) => (
        <span key={a.name}>
          {i > 0 && (i === arcs.length - 1 ? ' and ' : ', ')}
          <a href={playerHref(a.slug)}>{a.name}</a>
          <span className="mono">
            {' '}
            ({fmtNet(a.early.net)} → {fmtNet(a.late.net)})
          </span>
        </span>
      ))}
      .
    </p>
  )
}
