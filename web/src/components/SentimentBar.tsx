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

/** Negative → neutral → positive, on an absolute 0–100 scale unless `length` is relative. */
export function SentimentBar({ counts, length = 'full', scale = 1, size = 'row', subject }: SentimentBarProps) {
  const shares = SENTIMENTS.map((s) => ({ s, share: RATES[s](counts) }))
  const width = length === 'relative' ? Math.max(0, Math.min(1, scale)) : 1
  const summary = `${subject ? `${subject}: ` : ''}${shares.map(({ s, share }) => `${fmtPct(share)} ${NAMES[s]}`).join(', ')} of ${fmtInt(counts.total)} comments`
  // A relative bar is a length; its shares are in the text alternative only.
  const labelled = size !== 'mini' && length === 'full'

  // Each segment and its mirror cell below share a width, so one container
  // query decides where the label goes: inside when it fits, under when not.
  return (
    <div className={`sb sb--${size}`} role="img" aria-label={summary}>
      <div className="sb__track" style={{ '--sb-scale': width } as CSSProperties}>
        {shares.map(({ s, share }) => (
          <span key={s} className={`sb__seg sb__seg--${s}`} style={{ flexBasis: `${share * 100}%` }}>
            {labelled && share > 0 && <span className="sb__label">{fmtPct(share)}</span>}
          </span>
        ))}
      </div>
      {labelled && (
        <div className="sb__under" aria-hidden="true">
          {shares.map(({ s, share }) => (
            <span key={s} className={`sb__under-cell sb__under-cell--${s}`} style={{ flexBasis: `${share * 100}%` }}>
              {share > 0 && (
                <span className="sb__under-label">
                  {fmtPct(share)} {NAMES[s]}
                </span>
              )}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
