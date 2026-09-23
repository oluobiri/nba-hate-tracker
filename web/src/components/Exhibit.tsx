import { fmtInt } from '../lib/format'
import type { ReceiptContext } from '../lib/receipts'
import type { Sentiment } from '../lib/types'
import { Stamp, type StampKind } from './Stamp'

export interface ExhibitProps {
  number: number
  body: string
  sentiment: Sentiment
  score: number
  /** Reddit permalink to the comment. */
  sourceUrl: string
  /** The post the comment lived in, as one line; null when the bridge has no row for it. */
  context: ReceiptContext | null
  /** The commenter's flair as a team abbreviation; null when unflaired. */
  flair: string | null
  /** "May 8, 2026". */
  date: string
  stamp?: StampKind
}

const SENTIMENT: Record<Sentiment, string> = { neg: 'Negative', neu: 'Neutral', pos: 'Positive' }

/** A numbered receipt: the comment verbatim, its context, its source. Never a username. */
export function Exhibit({ number, body, sentiment, score, sourceUrl, context, flair, date, stamp }: ExhibitProps) {
  return (
    <article className={`exhibit exhibit--${sentiment}`}>
      <header className="exhibit__head">
        <span>Exhibit {String(number).padStart(2, '0')}</span>
        {stamp && <Stamp kind={stamp} />}
        <span className="visually-hidden">{SENTIMENT[sentiment]}.</span>
        <span className="exhibit__flair">{flair ? `${flair} flair` : 'no flair'}</span>
      </header>
      <blockquote className="exhibit__body">{body}</blockquote>
      <footer className="exhibit__foot">
        {context === null ? (
          <span className="exhibit__ctx exhibit__ctx--missing">Post unavailable</span>
        ) : (
          <span className="exhibit__ctx">
            <b>{context.label}</b> · {context.text}
          </span>
        )}
        <span className="exhibit__meta mono">
          <span className="exhibit__score" aria-label={`${fmtInt(score)} points`}>
            ▲ {fmtInt(score)}
          </span>
          <span className="exhibit__date">{date}</span>
          <a href={sourceUrl} rel="noopener noreferrer">
            Source ↗
          </a>
        </span>
      </footer>
    </article>
  )
}

/** The permalink of a comment from the fact's ids. */
export function commentUrl(linkId: string, commentId: string): string {
  return `https://www.reddit.com/r/nba/comments/${linkId.replace(/^t3_/, '')}/_/${commentId}/`
}
