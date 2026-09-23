// A dot plot on one shared, zoomed axis with an average tick: the v1
// "Δ vs Avg" idiom. Ranks read down the column; every row is a link.
import type { CSSProperties } from 'react'

import { fmtInt } from '../lib/format'

export interface DeltaDotRow {
  key: string
  label: string
  href: string
  value: number
  n: number
  /** Drawn gray beside the label; the label carries the meaning. */
  logo?: string
}

export interface DeltaDotProps {
  /** Already sorted by the caller; ranks are positions. */
  rows: readonly DeltaDotRow[]
  /** The tick: computed by the caller from summed counts. */
  average: number
  domain: readonly [number, number]
  format: (v: number) => string
  /** The dot's colour job: heat for a negative rate, ice for positive, bone otherwise. */
  tone: 'neg' | 'pos' | 'neu'
  averageLabel?: string
}

export function DeltaDot({ rows, average, domain, format, tone, averageLabel = 'League average' }: DeltaDotProps) {
  const [lo, hi] = domain
  const pct = (v: number): number => (hi > lo ? ((v - lo) / (hi - lo)) * 100 : 50)
  const style = (v: number): CSSProperties => ({ '--dd-x': `${pct(v)}%`, '--dd-avg': `${pct(average)}%` }) as CSSProperties
  return (
    <div className={`dd dd--${tone}`}>
      <div className="dd__head mono" aria-hidden="true">
        <span className="dd__lo">{format(lo)}</span>
        <span className="dd__avg" style={style(average)}>
          {averageLabel} {format(average)}
        </span>
        <span className="dd__hi">{format(hi)}</span>
      </div>
      <ol className="dd__rows">
        {rows.map((r, i) => (
          <li key={r.key} className="dd__row">
            <a className="dd__link" href={r.href} aria-label={`${r.label}: ${format(r.value)} of ${fmtInt(r.n)} comments`}>
              <span className="dd__rank mono">{i + 1}</span>
              {r.logo ? <img className="dd__logo" src={r.logo} alt="" width="20" height="20" loading="lazy" decoding="async" /> : <span className="dd__logo" />}
              <span className="dd__label">{r.label}</span>
              <span className="dd__track" style={style(r.value)}>
                <span className="dd__tick" />
                <span className="dd__dot" />
              </span>
              <span className="dd__value mono">{format(r.value)}</span>
            </a>
          </li>
        ))}
      </ol>
    </div>
  )
}
