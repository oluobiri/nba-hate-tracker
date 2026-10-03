// The game by quarter: one mini bar per quarter (and overtime) at equal widths, the label
// above and n below, so a loud fourth quarter and a thin first read as what
// they are. Nothing is grayed and no floor is read; n does the honesty work.
import type { CSSProperties } from 'react'

import { fmtInt } from '../lib/format'
import { fmtNet, netOf, netStyle } from '../lib/net'
import { periodsText, type PeriodCell } from '../lib/recaps'
import { SentimentBar } from './SentimentBar'

export interface PeriodStripProps {
  cells: readonly PeriodCell[]
  size?: 'hero' | 'row'
  /** Whose comments these are, for the text alternative. */
  subject: string
  /** A net figure over each bar, coloured by its strength, on a page that speaks net. */
  figure?: 'net'
}

export function PeriodStrip({ cells, size = 'row', subject, figure }: PeriodStripProps) {
  return (
    <div className={`ps ps--${size}${figure ? ' ps--figured' : ''}`} role="img" aria-label={`${subject} by quarter: ${periodsText(cells, figure)}`} style={{ '--ps-n': cells.length } as CSSProperties}>
      {cells.map((c) => (
        <span key={c.key} className={`ps__cell${c.counts.total ? '' : ' ps__cell--silent'}`} aria-hidden="true">
          <span className="ps__label mono">{c.label}</span>
          {figure && (
            <span className="ps__figure" style={netStyle(netOf(c.counts))}>
              {fmtNet(netOf(c.counts))}
            </span>
          )}
          <SentimentBar counts={c.counts} size="mini" />
          <span className="ps__n mono">{c.counts.total ? fmtInt(c.counts.total) : '—'}</span>
        </span>
      ))}
    </div>
  )
}
