import type { ReactNode } from 'react'

import { fmtInt } from '../lib/format'
import { markNames } from '../lib/method'
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
  /** The names the finder matched, marked in the body as it spells them. */
  marks?: readonly string[]
  /** Between the body and the footer: the answer, a line about the comment. */
  children?: ReactNode
}

const SENTIMENT: Record<Sentiment, string> = { neg: 'Negative', neu: 'Neutral', pos: 'Positive' }

/** A body with the finder's names marked; plain text when there are none. */
export function MarkedBody({ body, marks }: { body: string; marks?: readonly string[] }) {
  if (!marks?.length) return <>{body}</>
  return (
    <>
      {markNames(body, marks).map((seg, i) =>
        seg.mark ? (
          <mark key={i}>{seg.text}</mark>
        ) : (
          <span key={i}>{seg.text}</span>
        ),
      )}
    </>
  )
}

/** A numbered receipt: the comment verbatim, its context, its source. Never a username. */
export function Exhibit({ number, body, sentiment, score, sourceUrl, context, flair, date, stamp, marks, children }: ExhibitProps) {
  return (
    <article className={`exhibit exhibit--${sentiment}`}>
      <header className="exhibit__head">
        <span>Exhibit {String(number).padStart(2, '0')}</span>
        {stamp && <Stamp kind={stamp} />}
        <span className="visually-hidden">{SENTIMENT[sentiment]}.</span>
        <span className="exhibit__flair">{flair ? `${flair} flair` : 'no flair'}</span>
      </header>
      <blockquote className="exhibit__body">
        <MarkedBody body={body} marks={marks} />
      </blockquote>
      {children && <div className="exhibit__extra">{children}</div>}
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
