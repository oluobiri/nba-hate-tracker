// A dot plot on one shared, zoomed axis with an average tick: the v1
// "Δ vs Avg" idiom. Ranks read down the column; every row is a link.
import type { CSSProperties } from 'react'

import { fmtInt, fmtSigned } from '../lib/format'

export interface DeltaDotRow {
  key: string
  label: string
  href: string
  value: number
  n: number
  /** Drawn gray beside the label; the label carries the meaning. */
  logo?: string
  /** A small mark after the label ("own fans"); the row gets a bone outline. */
  tag?: string
  /** The link's spoken sentence, when the generated one would not say enough (a Δ axis). */
  text?: string
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
  /** Print each row's distance from the tick, in points, as a last column. */
  showDelta?: boolean
}

// Within this share of either end, the tick's label hangs inward instead of centred.
const EDGE = 22

export function DeltaDot({ rows, average, domain, format, tone, averageLabel = 'League average', showDelta = false }: DeltaDotProps) {
  const [lo, hi] = domain
  const pct = (v: number): number => (hi > lo ? ((v - lo) / (hi - lo)) * 100 : 50)
  const style = (v: number): CSSProperties => ({ '--dd-x': `${pct(v)}%`, '--dd-avg': `${pct(average)}%` }) as CSSProperties
  // Every row prints its value, so the axis carries only the tick's label,
  // which hangs inward near either end.
  const avgPct = pct(average)
  const edge = avgPct < EDGE ? 'start' : avgPct > 100 - EDGE ? 'end' : null
  return (
    <div className={`dd dd--${tone}${showDelta ? ' dd--delta' : ''}`}>
      <div className="dd__head mono" aria-hidden="true">
        <span className={`dd__avg${edge ? ` dd__avg--${edge}` : ''}`} style={style(average)}>
          {averageLabel} {format(average)}
        </span>
        {showDelta && <span className="dd__dhead">Δ pts</span>}
      </div>
      <ol className="dd__rows">
        {rows.map((r, i) => {
          const delta = r.value - average
          const text = r.text ?? `${r.label}: ${format(r.value)} of ${fmtInt(r.n)} comments${showDelta ? `, ${fmtSigned(delta, 0)} points against the ${averageLabel.toLowerCase()}` : ''}`
          return (
            <li key={r.key} className={`dd__row${r.tag ? ' dd__row--tagged' : ''}`}>
              <a className="dd__link" href={r.href} aria-label={text}>
                <span className="dd__rank mono">{i + 1}</span>
                {r.logo ? <img className="dd__logo" src={r.logo} alt="" width="20" height="20" loading="lazy" decoding="async" /> : <span className="dd__logo" />}
                <span className="dd__label">
                  {r.label}
                  {r.tag && <span className="dd__tag mono">{r.tag}</span>}
                </span>
                <span className="dd__track" style={style(r.value)}>
                  <span className="dd__tick" />
                  <span className="dd__dot" />
                </span>
                <span className="dd__value mono">{format(r.value)}</span>
                {showDelta && <span className="dd__delta mono">{fmtSigned(delta, 0)}</span>}
              </a>
            </li>
          )
        })}
      </ol>
    </div>
  )
}
