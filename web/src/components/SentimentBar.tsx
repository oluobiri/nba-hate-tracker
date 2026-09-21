import type { CSSProperties } from 'react'

import { fmtInt, fmtPct } from '../lib/format'
import { negRate, neuRate, posRate } from '../lib/metrics'
import { SENTIMENTS, type Counts, type Sentiment } from '../lib/types'

export type BarSize = 'hero' | 'row' | 'mini'
export type BarLength = 'full' | 'relative'

export interface SentimentBarProps {
  counts: Counts
  /** `full` spans the container; `relative` spans `scale` of it (a volume lens). */
  length?: BarLength
  /** 0–1, the share of the container a relative bar takes. */
  scale?: number
  size?: BarSize
  /** What the bar is about, for the text alternative ("Draymond Green"). */
  subject?: string
}

const NAMES: Record<Sentiment, string> = { neg: 'negative', neu: 'neutral', pos: 'positive' }
const RATES: Record<Sentiment, (c: Counts) => number> = { neg: negRate, neu: neuRate, pos: posRate }

// Below this share of the bar a label moves to the outside list. The rule is
// set for a phone-width bar (~370 px); components.css also hides any label
// whose segment is narrower than the text, so nothing ever renders clipped.
const INSIDE_MIN: Record<BarSize, number> = { hero: 0.16, row: 0.13, mini: Number.POSITIVE_INFINITY }

/** Negative → neutral → positive, on an absolute 0–100 scale unless `length` is relative. */
export function SentimentBar({ counts, length = 'full', scale = 1, size = 'row', subject }: SentimentBarProps) {
  const shares = SENTIMENTS.map((s) => ({ s, share: RATES[s](counts) }))
  const width = length === 'relative' ? Math.max(0, Math.min(1, scale)) : 1
  const summary = `${subject ? `${subject}: ` : ''}${shares.map(({ s, share }) => `${fmtPct(share)} ${NAMES[s]}`).join(', ')} of ${fmtInt(counts.total)} comments`
  const outside = shares.filter(({ share }) => share > 0 && share * width < INSIDE_MIN[size])

  return (
    <div className={`sb sb--${size}`} role="img" aria-label={summary}>
      <div className="sb__track" style={{ '--sb-scale': width } as CSSProperties}>
        {shares.map(({ s, share }) => (
          <span key={s} className={`sb__seg sb__seg--${s}`} style={{ flexBasis: `${share * 100}%` }}>
            {size !== 'mini' && share * width >= INSIDE_MIN[size] && <span className="sb__label">{fmtPct(share)}</span>}
          </span>
        ))}
      </div>
      {size !== 'mini' && outside.length > 0 && (
        <ul className="sb__outside" aria-hidden="true">
          {outside.map(({ s, share }) => (
            <li key={s} style={{ '--sb-swatch': `var(--${s === 'neg' ? 'heat' : s === 'pos' ? 'ice' : 'neu'})` } as CSSProperties}>
              {fmtPct(share)} {NAMES[s]}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
